"""
Split calculation logic.
Mirrors the logic in build_report.py but works on live Dataverse data.
"""
from datetime import date, datetime

# HMRC 2025 annual average FX rates (unitsPerGbp → used as multiplier from foreign to GBP)
# Source: https://www.gov.uk/government/collections/exchange-rates-for-customs-and-vat
def _build_fx_tables(rates_units_per_gbp: dict) -> tuple:
    """
    Convert {iso_code: unitsPerGbp} from Dataverse into TO_GBP and TO_USD dicts.
    unitsPerGbp: how many units of foreign currency = 1 GBP (HMRC format).
    Falls back to hardcoded values for any currency not in the live table.
    """
    usd_per_gbp = rates_units_per_gbp.get("USD") or TO_USD.get("GBP", 1.267)
    to_gbp = {"GBP": 1.0}
    to_usd = {"GBP": usd_per_gbp, "USD": 1.0}
    for ccy, units in rates_units_per_gbp.items():
        if not units or ccy == "GBP":
            continue
        to_gbp[ccy] = 1.0 / units          # 1 CCY → GBP:  divide by units-per-GBP
        to_usd[ccy] = usd_per_gbp / units  # 1 CCY → USD:  (USD/GBP) ÷ (CCY/GBP)
    # Fill gaps with hardcoded fallback
    for ccy in TO_GBP:
        if ccy not in to_gbp:
            to_gbp[ccy] = TO_GBP[ccy]
        if ccy not in to_usd:
            to_usd[ccy] = TO_USD[ccy]
    return to_gbp, to_usd


TEAM_ORDER = {
    "Bristol":  ["Team Batt", "Team Charlie", "Team Sion", "Team Harry W"],
    "London":   ["Team Data & Cyber", "Team Data and Cyber", "Team Snoz"],
    "Chicago":  ["Team JD", "Team Matty", "Team Adam", "Team Adam W"],
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


def compute_metrics(uid: str, placements: list[dict], display_ccy: str, today: date, to_gbp: dict = None, to_usd: dict = None) -> dict:
    """
    Returns YTD, Written, Year Prediction, and Rolling 12M for a single user.
    """
    ytd_start    = date(today.year, 1, 1)
    written_end  = date(today.year, 12, 31)
    roll12_start = date(today.year - 1, today.month, today.day + 1
                        if today.day < 28 else today.day)

    # ISO week number for year prediction
    week_no = today.isocalendar()[1]

    fx = (to_gbp or TO_GBP) if display_ccy == "GBP" else (to_usd or TO_USD)

    ytd = written = roll12_base = roll12_uplift = 0.0

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
            roll12_base   += val
            roll12_uplift += val * 0.5 if is_nb else 0.0

    year_pred = (written / week_no) * 52 if written > 0 else 0.0

    return {
        "ytd":          round(ytd, 2),
        "written":      round(written, 2),
        "year_pred":    round(year_pred, 2),
        "roll12":       round(roll12_base, 2),
        "roll12_uplift": round(roll12_uplift, 2),
        "roll12_total": round(roll12_base + roll12_uplift, 2),
    }


def compute_wnf(uid: str, live_contracts: list, display_ccy: str, to_gbp: dict = None, to_usd: dict = None) -> float:
    """Returns the user's share of WNF across all live contract placements."""
    fx = (to_gbp or TO_GBP) if display_ccy == "GBP" else (to_usd or TO_USD)
    total = 0.0
    for p in live_contracts:
        factor = split_factor(p, uid)
        if factor == 0:
            continue
        wnf = p.get("recruit_trueweeklygrossprofit") or 0.0
        ccy = (p.get("recruit_trueweeklygrossprofitcurrency") or {}).get("isocurrencycode")
        total += wnf * factor * fx.get(ccy, 1.0)
    return round(total, 2)


def compute_monthly_breakdown(
    uid: str, placements: list, display_ccy: str, year: int,
    to_gbp: dict = None, to_usd: dict = None,
    after_date: date = None, before_date: date = None,
) -> dict:
    """
    Returns {1: val, 2: val, ..., 12: val} — GP split for uid in the given year.
    after_date:  only include placements with start_date >= after_date
    before_date: only include placements with start_date <  before_date
    """
    fx = (to_gbp or TO_GBP) if display_ccy == "GBP" else (to_usd or TO_USD)
    months = {m: 0.0 for m in range(1, 13)}
    for p in placements:
        factor = split_factor(p, uid)
        if factor == 0:
            continue
        d = parse_date(p["crimson_startdate"])
        if d.year != year:
            continue
        if after_date  and d < after_date:
            continue
        if before_date and d >= before_date:
            continue
        gp  = p.get("recruit_truegrossprofit") or 0.0
        ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode")
        months[d.month] += gp * factor * fx.get(ccy, 1.0)
    return {str(k): round(v, 2) for k, v in months.items()}


def build_admin_report(
    consultants: list,
    placements_this: list,
    placements_last: list,
    overrides: list,
    today: date,
    team_map: dict = None,
    budgets: list = None,
    fx_rates: dict = None,
) -> dict:
    """
    Builds the admin analytics report: monthly breakdown per consultant,
    territory totals, YoY comparison, and budget figures.
    """
    year = today.year
    to_gbp, to_usd = _build_fx_tables(fx_rates) if fx_rates else (TO_GBP, TO_USD)
    override_map = {o["crbb7_userid"]: o for o in overrides}

    CCY = {
        "Bristol":          "GBP",
        "London":           "GBP",
        "London Contract":  "GBP",
        "Chicago":          "USD",
        "New York":         "USD",
        "Chicago Contract": "USD",
        "Cameron Scott":    "GBP",
    }

    # Budget map for current year: {territory: {months: {1: amt, ...}, total: float}}
    budget_map = {}
    for b in (budgets or []):
        if b.get("crbb7_year") == year:
            t     = b.get("crbb7_territory", "")
            month = b.get("crbb7_month")
            amt   = float(b.get("crbb7_amount") or 0)
            if t not in budget_map:
                budget_map[t] = {"months": {}, "total": 0.0}
            if month:
                budget_map[t]["months"][str(month)] = amt
                budget_map[t]["total"] = round(budget_map[t]["total"] + amt, 2)

    from collections import defaultdict
    by_territory = defaultdict(list)

    for c in consultants:
        uid       = c["systemuserid"]
        territory = _territory_name(c.get("_territoryid_value"))
        if not territory:
            continue
        ov = override_map.get(uid, {})
        # Note: hidden flag is intentionally NOT checked here — analytics shows everyone.
        # crbb7_ishidden only suppresses users from the weekly report (build_report).

        team = ov.get("crbb7_team") or _default_team(uid, territory, team_map or {})
        role = _clean_role(c.get("title") or "")
        ccy  = CCY.get(territory, "GBP")

        is_active = not c.get("isdisabled", False)

        # Check for a historical territory/team move
        dj_str        = ov.get("crbb7_datejoinedteam")
        prev_territory = ov.get("crbb7_previousterritory") or ""
        prev_team_name = ov.get("crbb7_previousteam") or ""
        move_date = None
        if dj_str:
            try:
                move_date = parse_date(dj_str)
            except Exception:
                pass

        if move_date and prev_territory:
            # ── Current territory: placements from move_date onwards ──────────
            m_this_cur = compute_monthly_breakdown(uid, placements_this, ccy, year,     to_gbp, to_usd, after_date=move_date)
            m_last_cur = compute_monthly_breakdown(uid, placements_last, ccy, year - 1, to_gbp, to_usd, after_date=move_date)
            tot_this_cur = sum(m_this_cur.values())
            tot_last_cur = sum(m_last_cur.values())
            if is_active or tot_this_cur > 0 or tot_last_cur > 0:
                by_territory[territory].append({
                    "uid":              uid,
                    "name":             c.get("fullname", ""),
                    "role":             role,
                    "team":             team,
                    "createdon":        c.get("createdon", ""),
                    "active":           is_active,
                    "sym":              "£" if ccy == "GBP" else "$",
                    "months":           m_this_cur,
                    "last_year_months": m_last_cur,
                    "total":            round(tot_this_cur, 2),
                    "last_year_total":  round(tot_last_cur, 2),
                    "note":             None,
                })

            # ── Previous territory: placements before move_date ──────────────
            prev_ccy  = CCY.get(prev_territory, "GBP")
            prev_sym  = "£" if prev_ccy == "GBP" else "$"
            m_this_prev = compute_monthly_breakdown(uid, placements_this, prev_ccy, year,     to_gbp, to_usd, before_date=move_date)
            m_last_prev = compute_monthly_breakdown(uid, placements_last, prev_ccy, year - 1, to_gbp, to_usd, before_date=move_date)
            tot_this_prev = sum(m_this_prev.values())
            tot_last_prev = sum(m_last_prev.values())
            if tot_this_prev > 0 or tot_last_prev > 0:
                by_territory[prev_territory].append({
                    "uid":              uid + "__hist",
                    "name":             c.get("fullname", ""),
                    "role":             role,
                    "team":             prev_team_name or team,
                    "createdon":        c.get("createdon", ""),
                    "active":           False,
                    "sym":              prev_sym,
                    "months":           m_this_prev,
                    "last_year_months": m_last_prev,
                    "total":            round(tot_this_prev, 2),
                    "last_year_total":  round(tot_last_prev, 2),
                    "note":             f"now in {territory}",
                })
        else:
            # ── No move — use all placements ─────────────────────────────────
            months_this = compute_monthly_breakdown(uid, placements_this, ccy, year,     to_gbp, to_usd)
            months_last = compute_monthly_breakdown(uid, placements_last, ccy, year - 1, to_gbp, to_usd)
            total_this  = sum(months_this.values())
            total_last  = sum(months_last.values())

            if not is_active and total_this == 0 and total_last == 0:
                continue

            by_territory[territory].append({
                "uid":              uid,
                "name":             c.get("fullname", ""),
                "role":             role,
                "team":             team,
                "createdon":        c.get("createdon", ""),
                "active":           is_active,
                "sym":              "£" if ccy == "GBP" else "$",
                "months":           months_this,
                "last_year_months": months_last,
                "total":            round(total_this, 2),
                "last_year_total":  round(total_last, 2),
                "note":             None,
            })

    report = {}
    for territory, members in by_territory.items():
        order = TEAM_ORDER.get(territory)
        ccy   = CCY.get(territory, "GBP")
        sym   = "£" if ccy == "GBP" else "$"

        # Territory-level monthly totals (this year and last year)
        t_months      = {str(m): 0.0 for m in range(1, 13)}
        t_last_months = {str(m): 0.0 for m in range(1, 13)}
        t_last        = 0.0
        for member in members:
            for m_str, v in member["months"].items():
                t_months[m_str] = round(t_months[m_str] + v, 2)
            for m_str, v in member.get("last_year_months", {}).items():
                t_last_months[m_str] = round(t_last_months[m_str] + v, 2)
            t_last += member.get("last_year_total", 0)
        t_total = sum(t_months.values())

        if order:
            members.sort(key=lambda m: (
                order.index(m["team"]) if m["team"] in order else 99,
                m.get("createdon", "")
            ))
            groups = []
            for m in members:
                existing = next((g for g in groups if g["team"] == m["team"]), None)
                if not existing:
                    existing = {"team": m["team"], "members": []}
                    groups.append(existing)
                existing["members"].append(m)
            result = {"type": "teams", "groups": groups}
        else:
            members.sort(key=lambda m: m.get("createdon", ""))
            result = {"type": "flat", "members": members}

        result.update({
            "sym":                      sym,
            "territory_months":         t_months,
            "territory_last_year_months": t_last_months,
            "territory_total":          round(t_total, 2),
            "territory_last_year":      round(t_last, 2),
            "budget":                   budget_map.get(territory, {"months": {}, "total": 0.0}),
        })
        report[territory] = result

    # ── "Other" placements: those where no tracked territory consultant is an owner ──
    _OWNER_FIELDS = [
        "_mercury_clientrelationshipowner_value",
        "_crimson_consultant_value",
        "_mercury_assignmentowner_value",
        "_mercury_contractorrelationship_userid_value",
    ]
    tracked_uids = {c["systemuserid"] for c in consultants}

    def _any_tracked(p):
        return any(p.get(f) in tracked_uids for f in _OWNER_FIELDS)

    other_this_pl = [p for p in placements_this if not _any_tracked(p)]
    other_last_pl = [p for p in placements_last if not _any_tracked(p)]

    other_monthly_gbp      = {str(m): 0.0 for m in range(1, 13)}
    other_last_monthly_gbp = {str(m): 0.0 for m in range(1, 13)}
    other_total_gbp        = 0.0
    other_last_total_gbp   = 0.0
    other_drilldown        = []

    for p in other_this_pl:
        gp    = p.get("recruit_truegrossprofit") or 0.0
        ccy   = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode", "GBP")
        gbp   = gp * to_gbp.get(ccy, 1.0)
        d     = parse_date(p.get("crimson_startdate", f"{year}-01-01"))
        m_str = str(d.month)
        other_monthly_gbp[m_str] = round(other_monthly_gbp[m_str] + gbp, 2)
        other_total_gbp += gbp
        other_drilldown.append({
            "title":            p.get("crimson_name") or "",
            "client":           (p.get("crimson_clientname") or {}).get("name") or "",
            "fee":              round(gp, 2),
            "currency":         ccy,
            "fee_gbp":          round(gbp, 2),
            "cro":              (p.get("mercury_clientrelationshipowner") or {}).get("fullname") or "",
            "consultant":       (p.get("crimson_consultant") or {}).get("fullname") or "",
            "assignment_owner": (p.get("mercury_assignmentowner") or {}).get("fullname") or "",
            "start_date":       (p.get("crimson_startdate") or "")[:10],
        })

    for p in other_last_pl:
        gp    = p.get("recruit_truegrossprofit") or 0.0
        ccy   = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode", "GBP")
        gbp   = gp * to_gbp.get(ccy, 1.0)
        d     = parse_date(p.get("crimson_startdate", f"{year - 1}-01-01"))
        m_str = str(d.month)
        other_last_monthly_gbp[m_str] = round(other_last_monthly_gbp[m_str] + gbp, 2)
        other_last_total_gbp += gbp

    other_drilldown.sort(key=lambda p: p["start_date"], reverse=True)

    # Grand totals (territory rows + Other), all converted to GBP
    usd_to_gbp = to_gbp.get("USD", TO_GBP["USD"])
    USD_TERRITORIES = {"Chicago", "New York", "Chicago Contract"}
    grand_gbp              = 0.0
    grand_gbp_last         = 0.0
    grand_monthly_gbp      = {str(m): 0.0 for m in range(1, 13)}
    grand_monthly_last_gbp = {str(m): 0.0 for m in range(1, 13)}
    grand_budget_monthly   = {str(m): 0.0 for m in range(1, 13)}
    grand_budget_total     = 0.0
    for t, tdata in report.items():
        factor = usd_to_gbp if t in USD_TERRITORIES else 1.0
        grand_gbp      += tdata["territory_total"]     * factor
        grand_gbp_last += tdata["territory_last_year"] * factor
        for m_str, v in tdata["territory_months"].items():
            grand_monthly_gbp[m_str] = round(grand_monthly_gbp[m_str] + v * factor, 2)
        for m_str, v in tdata["territory_last_year_months"].items():
            grand_monthly_last_gbp[m_str] = round(grand_monthly_last_gbp[m_str] + v * factor, 2)
        budget_mths = tdata.get("budget", {}).get("months", {})
        for m_str, v in budget_mths.items():
            grand_budget_monthly[m_str] = round(grand_budget_monthly[m_str] + v * factor, 2)
        grand_budget_total = round(grand_budget_total + tdata.get("budget", {}).get("total", 0.0) * factor, 2)

    # Include Other in grand totals
    grand_gbp      = round(grand_gbp      + other_total_gbp,      2)
    grand_gbp_last = round(grand_gbp_last + other_last_total_gbp, 2)
    for m_str, v in other_monthly_gbp.items():
        grand_monthly_gbp[m_str] = round(grand_monthly_gbp[m_str] + v, 2)
    for m_str, v in other_last_monthly_gbp.items():
        grand_monthly_last_gbp[m_str] = round(grand_monthly_last_gbp[m_str] + v, 2)

    return {
        "year":                    year,
        "territories":             report,
        "other": {
            "total_gbp":       round(other_total_gbp, 2),
            "last_year_gbp":   round(other_last_total_gbp, 2),
            "monthly_gbp":     other_monthly_gbp,
            "last_monthly_gbp": other_last_monthly_gbp,
            "placements":      other_drilldown,
        },
        "grand_total_gbp":         round(grand_gbp, 2),
        "grand_total_last_gbp":    round(grand_gbp_last, 2),
        "grand_monthly_gbp":       grand_monthly_gbp,
        "grand_monthly_last_gbp":  grand_monthly_last_gbp,
        "grand_budget_monthly_gbp": grand_budget_monthly,
        "grand_budget_total_gbp":   grand_budget_total,
    }


def build_report(
    consultants: list[dict],
    placements: list[dict],
    overrides: list[dict],
    today: date,
    team_map: dict = None,
    live_contracts: list = None,
    fx_rates: dict = None,
) -> dict:
    """
    Assembles the full report structure.

    consultants: list from Dataverse systemusers
    placements:  list from Dataverse crimson_placements
    overrides:   list from crbb7_useroverrides
    today:       report date

    Returns a dict keyed by territory name, each value a list of team groups.
    """
    live_contracts = live_contracts or []
    to_gbp, to_usd = _build_fx_tables(fx_rates) if fx_rates else (TO_GBP, TO_USD)

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
        "Cameron Scott":    "GBP",
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

        team = ov.get("crbb7_team") or _default_team(uid, territory, team_map or {})
        role = _clean_role(c.get("title") or "")
        ccy  = CCY.get(territory, "GBP")

        metrics = compute_metrics(uid, placements, ccy, today, to_gbp, to_usd)
        wnf     = compute_wnf(uid, live_contracts, ccy, to_gbp, to_usd)

        by_territory[territory].append({
            "uid":              uid,
            "name":             c.get("fullname", ""),
            "role":             role,
            "team":             team,
            "createdon":        c.get("createdon", ""),
            "sym":              "£" if ccy == "GBP" else "$",
            "wnf":              wnf,
            "margin_ytd":       ov.get("crbb7_marginytd"),
            "contract_last12m": ov.get("crbb7_contractlast12m"),
            "rolling_3m":       ov.get("crbb7_rolling3m"),
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


def _default_team(uid: str, territory: str, team_map: dict) -> str:
    """Returns the team name from the pre-fetched Mercury team membership map."""
    return team_map.get(uid, "")


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
