"""
Split calculation logic.
Mirrors the logic in build_report.py but works on live Dataverse data.
"""
from datetime import date, datetime

# HMRC 2025 annual average FX rates (unitsPerGbp → used as multiplier from foreign to GBP)
# Source: https://www.gov.uk/government/collections/exchange-rates-for-customs-and-vat
TEAM_ORDER = {
    "Bristol":  ["Team Batt", "Team Charlie", "Team Sion", "Team Harry W"],
    "London":   ["Team Data & Cyber", "Team Snoz"],
    "Chicago":  ["Team JD", "Team Matty", "Team Adam"],
}

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
    # (defined at module level as TEAM_ORDER)

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

        team = ov.get("crbb7_team") or _default_team(c, territory)
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


def _default_team(consultant: dict, territory: str) -> str:
    """
    Reads team directly from Mercury team memberships.
    Picks the first team whose name matches a known report team for this territory.
    """
    known_teams = set(TEAM_ORDER.get(territory, []))
    if not known_teams:
        return ""
    for t in consultant.get("teammembership_association", []):
        if t.get("name") in known_teams:
            return t["name"]
    return ""


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
