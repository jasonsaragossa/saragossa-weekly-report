"""
Split calculation logic.
Mirrors the logic in build_report.py but works on live Dataverse data.
"""
from datetime import date, datetime

# HMRC 2025 annual average FX rates (unitsPerGbp → used as multiplier from foreign to GBP)
# Source: https://www.gov.uk/government/collections/exchange-rates-for-customs-and-vat
TO_GBP = {
    "GBP": 1.000, "USD": 0.789, "EUR": 0.838,
    "SGD": 0.591, "HKD": 0.101, "CAD": 0.575, "AUD": 0.491,
}
TO_USD = {
    "USD": 1.000, "GBP": 1.267, "EUR": 1.062,
    "SGD": 0.748, "HKD": 0.129, "CAD": 0.729, "AUD": 0.623,
}


def parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def split_factor(placement: dict, uid: str) -> float:
    """Returns this user's fraction of the placement (0, 1/3, 2/3, 1, 1/4, etc.)"""
    conro = placement.get("_mercury_contractorrelationship_userid_value")
    fields = [
        placement.get("_mercury_clientrelationshipowner_value"),
        placement.get("_crimson_consultant_value"),
        placement.get("_mercury_assignmentowner_value"),
        conro,
    ]
    denom = 4.0 if conro else 3.0
    count = sum(1 for f in fields if f == uid)
    return count / denom if count > 0 else 0.0


def compute_metrics(uid: str, placements: list[dict], display_ccy: str, today: date) -> dict:
    """
    Returns YTD, Written, Year Prediction, and Rolling 12M for a single user.
    """
    ytd_start    = date(today.year, 1, 1)
    written_end  = date(today.year, 12, 31)
    roll12_start = date(today.year - 1, today.month, today.day + 1
                        if today.day < 28 else today.day)

    # ISO week number for year prediction
    week_no = today.isocalendar()[1]

    fx = TO_GBP if display_ccy == "GBP" else TO_USD

    ytd = written = roll12 = 0.0

    for p in placements:
        factor = split_factor(p, uid)
        if factor == 0:
            continue

        gp  = p.get("recruit_truegrossprofit") or 0.0
        ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode")
        d   = parse_date(p["crimson_startdate"])

        val = gp * factor * fx.get(ccy, 1.0)

        if ytd_start <= d <= written_end:
            written += val
            if d <= today:
                ytd += val

        if roll12_start <= d <= today:
            is_nb = "new business" in (p.get("crimson_specialinstructionsclient") or "").lower()
            roll12 += val * (1.5 if is_nb else 1.0)

    year_pred = (written / week_no) * 52 if written > 0 else 0.0

    return {
        "ytd":       round(ytd, 2),
        "written":   round(written, 2),
        "year_pred": round(year_pred, 2),
        "roll12":    round(roll12, 2),
    }


def build_report(
    consultants: list[dict],
    placements: list[dict],
    overrides: list[dict],
    today: date,
) -> dict:
    """
    Assembles the full report structure.

    consultants: list from Dataverse systemusers
    placements:  list from Dataverse crimson_placements
    overrides:   list from crbb7_useroverrides
    today:       report date

    Returns a dict keyed by territory name, each value a list of team groups.
    """
    # Build override lookup by userid
    override_map = {o["crbb7_userid"]: o for o in overrides}

    # Territory → display currency
    CCY = {
        "Bristol":          "GBP",
        "London":           "GBP",
        "London Contract":  "GBP",
        "Chicago":          "USD",
        "New York":         "USD",
        "Chicago Contract": "USD",
    }

    # Default team ordering per territory (team → sort key)
    TEAM_ORDER = {
        "Bristol":  ["Team Batt", "Team Charlie", "Team Sion", "Team Harry W"],
        "London":   ["Team Data & Cyber", "Team Snoz"],
        "Chicago":  ["Team JD", "Team Matty", "Team Adam"],
    }

    # Group consultants by territory
    from collections import defaultdict
    by_territory = defaultdict(list)

    for c in consultants:
        uid       = c["systemuserid"]
        territory = _territory_name(c.get("_territoryid_value"))
        if not territory:
            continue

        ov = override_map.get(uid, {})
        if ov.get("crbb7_ishidden"):
            continue  # hidden by admin

        team = ov.get("crbb7_team") or _default_team(uid, territory)
        role = _clean_role(c.get("jobtitle") or "")
        ccy  = CCY.get(territory, "GBP")

        metrics = compute_metrics(uid, placements, ccy, today)

        by_territory[territory].append({
            "uid":      uid,
            "name":     c.get("fullname", ""),
            "role":     role,
            "team":     team,
            "createdon": c.get("createdon", ""),
            "sym":      "£" if ccy == "GBP" else "$",
            **metrics,
        })

    # Sort and group each territory
    report = {}
    for territory, members in by_territory.items():
        order = TEAM_ORDER.get(territory)
        if order:
            # Sort within team by createdon
            members.sort(key=lambda m: (
                order.index(m["team"]) if m["team"] in order else -1,
                m.get("createdon", "")
            ))
            # Group into teams
            groups = []
            seen_teams = []
            for m in members:
                if m["team"] not in seen_teams:
                    seen_teams.append(m["team"])
                groups_map = {g["team"]: g for g in groups}
                if m["team"] not in groups_map:
                    groups.append({"team": m["team"], "members": []})
                next(g for g in groups if g["team"] == m["team"])["members"].append(m)
            report[territory] = {"type": "teams", "groups": groups}
        else:
            # Flat sort by createdon
            members.sort(key=lambda m: m.get("createdon", ""))
            report[territory] = {"type": "flat", "members": members}

    return report


# ── Helpers ───────────────────────────────────────────────────────────────────

from shared.dataverse import TERRITORY_IDS as _TERRITORY_IDS
_TERRITORY_NAME_MAP = {v: k for k, v in _TERRITORY_IDS.items()}

def _territory_name(tid: str) -> str:
    return _TERRITORY_NAME_MAP.get(tid)


# Default team assignments (used when Mercury team field is blank and no override set)
_DEFAULT_TEAMS = {
    # Bristol
    "4935f278-3264-ee11-8def-6045bd0c1d6a": "Team Batt",
    "5db0b87b-3264-ee11-8def-6045bd0c1c1b": "Team Batt",
    "6cce3e73-3264-ee11-8def-002248c7244c": "Team Batt",
    "1e36f278-3264-ee11-8def-6045bd0c1d6a": "Team Batt",
    "18a4c869-3264-ee11-8def-6045bd0c1c1b": "Team Charlie",
    "7a9c971e-decd-ef11-b8e8-6045bdfcb26b": "Team Charlie",
    "ec50e9d9-6f24-f111-8342-7c1e5209a533": "Team Charlie",
    "aeb0b87b-3264-ee11-8def-6045bd0c1c1b": "Team Sion",
    "b66c43de-dcb9-ee11-9078-6045bd0c1c1b": "Team Sion",
    "7b3a3779-3264-ee11-8def-002248c7244c": "Team Sion",
    "4eebf101-72b5-f011-bbd2-7ced8d38bc76": "Team Sion",
    "c16b951b-72b5-f011-bbd2-000d3a0b968e": "Team Sion",
    "e8a2bb75-3264-ee11-8def-6045bd0c1c1b": "Team Harry W",
    "fef8b081-3264-ee11-8def-6045bd0c1c1b": "Team Harry W",
    "c61c64e7-331f-ef11-840a-7c1e5202d395": "Team Harry W",
    "92e7c547-d03d-ef11-a316-7c1e5209b93e": "Team Harry W",
    # London
    "1b55466d-3264-ee11-8def-002248c7244c": "Team Data & Cyber",
    "36b3f816-9313-ef11-9f89-6045bdfc783a": "Team Data & Cyber",
    "aea2bb75-3264-ee11-8def-6045bd0c1c1b": "Team Snoz",
    "aece3e73-3264-ee11-8def-002248c7244c": "Team Snoz",
    "82459d8d-1866-ef11-a670-7c1e521e091e": "Team Snoz",
    "daf84725-accd-ef11-b8e8-7c1e52030438": "Team Snoz",
    "3d9b7f7a-9c46-f011-877a-7c1e5265898b": "Team Snoz",
    # Chicago
    "263b3779-3264-ee11-8def-002248c7244c": "Team JD",
    "7f967670-5311-f011-998a-7c1e5265e7a2": "Team JD",
    "4e91b476-36a8-f011-bbd2-002248422ca5": "Team JD",
    "5b12d316-46af-f011-bbd2-002248422ca5": "Team JD",
    "778a4e38-fe3e-f111-88b5-7c1e5209a533": "Team JD",
    "94b0b87b-3264-ee11-8def-6045bd0c1c1b": "Team Matty",
    "72e1ec7e-3264-ee11-8def-6045bd0c1d6a": "Team Matty",
    "823dbaba-bb7c-ee11-8179-002248c7244c": "Team Matty",
    "5dc0690b-365e-ef11-bfe3-6045bdd0de71": "Team Matty",
    "172d900a-5211-f011-998a-7c1e5265898b": "Team Matty",
    "b8f8b081-3264-ee11-8def-6045bd0c1c1b": "Team Adam",
    "8f1dc6e3-b392-ef11-8a68-7c1e522e3320": "Team Adam",
    "1bb9cdd5-7644-f111-bec7-7ced8d6b281b": "Team Adam",
}

def _default_team(uid: str, territory: str) -> str:
    return _DEFAULT_TEAMS.get(uid, "")


_ROLE_STRIP = [
    "- data & cyber", "- technology", "- financial technology",
    "- buy side", "- investment management", "- quantitative",
    "buy side ", "data & cyber ", "technology ",
]

def _clean_role(title: str) -> str:
    t = title.lower()
    for phrase in _ROLE_STRIP:
        t = t.replace(phrase, "")
    return t.strip().title()
