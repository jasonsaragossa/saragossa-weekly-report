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


# NB-uplift qualification thresholds (overridable via the crbb7_nbconfig table).
# Applied in the placement's own currency; percentages are whole numbers.
NB_UPLIFT_DEFAULTS = {
    "perm_fee_pct":        18.0,
    "perm_min_value":      8000.0,
    "contract_margin_pct": 15.0,
    "contract_min_margin": 75.0,
}


def _nb_qualifies(p: dict, th: dict) -> bool:
    """Does this placement clear the new-business uplift thresholds?"""
    if p.get("crimson_type") == 143570000:  # Permanent
        fee_pct = p.get("crimson_permanentfeepercent")
        gp      = p.get("recruit_truegrossprofit") or 0.0
        return fee_pct is not None and fee_pct >= th["perm_fee_pct"] and gp >= th["perm_min_value"]
    # Contract / Temporary
    margin_pct = p.get("mercury_marginpercent")
    wk_margin  = p.get("recruit_weeklymarginvalue_mc") or 0.0
    return margin_pct is not None and margin_pct >= th["contract_margin_pct"] and wk_margin >= th["contract_min_margin"]


def compute_metrics(uid: str, placements: list[dict], display_ccy: str, today: date,
                    to_gbp: dict = None, to_usd: dict = None, thresholds: dict = None,
                    contract_placements: list = None, manual_clients: list = None) -> dict:
    """
    Returns YTD, Written, Year Prediction, and Rolling 12M for a single user.
    Financial figures are perm-only; the NB-client count spans perm + contract.
    """
    thresholds = thresholds or NB_UPLIFT_DEFAULTS
    ytd_start    = date(today.year, 1, 1)
    written_end  = date(today.year, 12, 31)
    roll12_start = date(today.year - 1, today.month, today.day + 1
                        if today.day < 28 else today.day)

    # ISO week number for year prediction
    week_no = today.isocalendar()[1]

    fx = (to_gbp or TO_GBP) if display_ccy == "GBP" else (to_usd or TO_USD)

    ytd = written = roll12_base = roll12_uplift = 0.0
    nb_clients = {}   # client_id -> client name (unique NB clients won as CRO, rolling 12m)

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
            roll12_base += val
            # New-business uplift is earned only by the CRO (the person who won
            # the business) — 50% of their own contribution, not split to others.
            is_nb  = "new business" in (p.get("crimson_specialinstructionsclient") or "").lower()
            is_cro = p.get("_mercury_clientrelationshipowner_value") == uid
            if is_nb and is_cro:
                client_id = p.get("_crimson_clientname_value")
                if client_id:
                    nb_clients[client_id] = (p.get("crimson_clientname") or {}).get("name") or "(unknown client)"
                if _nb_qualifies(p, thresholds):
                    roll12_uplift += val * 0.5

    # NB-client count also spans contract/temp placements (this metric only)
    for p in (contract_placements or []):
        if p.get("_mercury_clientrelationshipowner_value") != uid:
            continue
        try:
            d = parse_date(p["crimson_startdate"])
        except Exception:
            continue
        if roll12_start <= d <= today and "new business" in (p.get("crimson_specialinstructionsclient") or "").lower():
            cid = p.get("_crimson_clientname_value")
            if cid:
                nb_clients[cid] = (p.get("crimson_clientname") or {}).get("name") or "(unknown client)"

    # Admin-added NB clients (manual credit, e.g. a contract that wouldn't auto-count)
    for c in (manual_clients or []):
        if c.get("id"):
            nb_clients[c["id"]] = c.get("name") or "(client)"

    year_pred = (written / week_no) * 52 if written > 0 else 0.0

    return {
        "ytd":          round(ytd, 2),
        "written":      round(written, 2),
        "year_pred":    round(year_pred, 2),
        "roll12":       round(roll12_base, 2),
        "roll12_uplift": round(roll12_uplift, 2),
        "roll12_total": round(roll12_base + roll12_uplift, 2),
        "nb_clients":   len(nb_clients),
        "nb_client_names": sorted(nb_clients.values()),
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


def _consultant_placement_details(
    uid: str, placements: list, display_ccy: str, year: int,
    to_gbp: dict = None, to_usd: dict = None,
    after_date=None, before_date=None,
) -> list:
    """
    Returns per-placement contribution details for a consultant in the given year.
    Used for the monthly drilldown click-through in the admin analytics UI.
    Each entry: {month, title, client, own_fee, full_fee, currency, start_date}
    own_fee / full_fee are in display_ccy (converted).
    """
    fx = (to_gbp or TO_GBP) if display_ccy == "GBP" else (to_usd or TO_USD)
    details = []
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
        gp    = p.get("recruit_truegrossprofit") or 0.0
        p_ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode", display_ccy)
        rate  = fx.get(p_ccy, 1.0)
        details.append({
            "month":      d.month,
            "title":      p.get("crimson_name") or "",
            "client":     (p.get("crimson_clientname") or {}).get("name") or "",
            "own_fee":    round(gp * factor * rate, 2),
            "full_fee":   round(gp * rate, 2),
            "currency":   p_ccy,
            "start_date": p["crimson_startdate"][:10],
        })
    details.sort(key=lambda x: x["start_date"])
    return details


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


def compute_written_by_created(
    uid: str, placements: list, display_ccy: str, year: int,
    created_cutoff: date, to_gbp: dict = None, to_usd: dict = None,
    after_date: date = None, before_date: date = None,
) -> float:
    """
    Sum of GP (split + FX) for placements with a start date in `year` that were
    *created* on or before `created_cutoff` (inclusive).

    Used for the "Full Year Written Last YTD" column: last year's whole-year
    book exactly as it stood at this same point in the year — i.e. everything
    starting in the year that had already been written by this date.
    """
    fx = (to_gbp or TO_GBP) if display_ccy == "GBP" else (to_usd or TO_USD)
    total = 0.0
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
        created = p.get("createdon")
        if not created or parse_date(created) > created_cutoff:
            continue
        gp  = p.get("recruit_truegrossprofit") or 0.0
        ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode")
        total += gp * factor * fx.get(ccy, 1.0)
    return round(total, 2)


# ── High Performance Bonus (US perm) ──────────────────────────────────────────
# Quarterly invoiced billings (= gross profit, USD) vs role target. US perm only.
HPB_TERRITORIES   = {"Chicago", "New York"}
HPB_TEAM_LEAD_CAP = 75000   # max of a team lead's own billings counted toward team

# 100% targets in USD; 150% = 1.5x, 200% = 2x.
HPB_TARGETS = {
    "associate":    30000,   # no individual bonus, but counts toward the team
    "consultant":   60000,
    "senior":       90000,
    "principal":   100000,
    "team_lead":   100000,
    "eic":         100000,
    "sales_leader":100000,
}
# Grades that earn an individual bonus (associate / unmapped do not)
HPB_INDIVIDUAL_GRADES = {"consultant", "senior", "principal", "team_lead", "eic", "sales_leader"}
# User-facing job titles (the figure is driven by the title held each quarter)
HPB_GRADE_LABELS = {
    "associate": "Associate Consultant", "consultant": "Consultant",
    "senior": "Senior Consultant", "principal": "Principal Consultant",
    "team_lead": "Team Lead", "eic": "EIC", "sales_leader": "Sales Leader",
    "none": "—",
}


def _hpb_grade(title: str, override_grade) -> str:
    """Resolve a consultant's HPB grade from an explicit override, else their title."""
    if override_grade:
        g = str(override_grade).strip().lower()
        if g and g != "auto":
            return g
    t = (title or "").lower()
    if "team lead" in t:  return "team_lead"
    if "associate" in t:  return "associate"
    if "senior" in t:     return "senior"
    if "principal" in t:  return "principal"
    if "consultant" in t: return "consultant"
    return "none"


def _started_by(start_date, point: date) -> bool:
    """True if employment start is on/before `point` (or unknown — then assume started)."""
    if not start_date:
        return True
    try:
        return parse_date(start_date) <= point
    except Exception:
        return True


def _hpb_quarter_billings(uid: str, placements: list, to_usd: dict, today: date, year: int) -> dict:
    """
    Per-quarter USD billings for a consultant — all placements with a start date
    in the quarter, whether started yet or not (full-year projection).
    """
    q = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
    for p in placements:
        factor = split_factor(p, uid)
        if factor == 0:
            continue
        d = parse_date(p["crimson_startdate"])
        if d.year != year:
            continue
        gp  = p.get("recruit_truegrossprofit") or 0.0
        ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode")
        q[(d.month - 1) // 3 + 1] += gp * factor * to_usd.get(ccy, 1.0)
    return {str(k): round(v, 2) for k, v in q.items()}


def build_hpb(consultants: list, placements: list, override_map: dict,
              team_map: dict, to_usd: dict, today: date, bob_titles: dict = None) -> dict:
    """
    US perm High Performance Bonus: per-quarter billings vs job-title target, plus
    a team total for team leads (their own billings capped at HPB_TEAM_LEAD_CAP).

    Job title per quarter resolves: manual override -> Bob -> Mercury title.
    """
    from collections import defaultdict
    bob_titles      = bob_titles or {}
    year            = today.year
    current_quarter = (today.month - 1) // 3 + 1
    people          = []
    for c in consultants:
        if c.get("isdisabled", False):
            continue
        territory = _territory_name(c.get("_territoryid_value"))
        if territory not in HPB_TERRITORIES:
            continue
        uid        = c["systemuserid"]
        ov         = override_map.get(uid, {})
        title      = c.get("title") or ""
        auto_grade = _hpb_grade(title, None)   # grade implied by current Mercury title
        team       = ov.get("crbb7_team") or team_map.get(uid, "")
        tl_ov      = ov.get("crbb7_isteamlead")
        is_lead    = bool(tl_ov) if tl_ov is not None else ("team lead" in title.lower())

        bob          = bob_titles.get((c.get("internalemailaddress") or "").lower()) or {}
        bob_quarters = bob.get("quarters") or {}

        # Job title can differ per quarter (title at the start of each quarter).
        # Resolution per quarter: manual override -> Bob -> current Mercury title.
        q_grades = {}
        for q in ("1", "2", "3", "4"):
            ovg = ov.get("crbb7_hpbgradeq" + q)
            ovg = ovg.strip().lower() if isinstance(ovg, str) else ""
            bob_q = bob_quarters.get(q)
            if ovg and ovg != "auto":
                q_grades[q] = ovg
            elif bob_q and bob_q != "none":
                q_grades[q] = bob_q
            else:
                q_grades[q] = auto_grade
        q_targets = {
            q: (HPB_TARGETS[g] if g in HPB_INDIVIDUAL_GRADES else None)
            for q, g in q_grades.items()
        }
        # Display title = current Bob title, else current Mercury title.
        bob_current   = bob.get("current")
        display_grade = bob_current if (bob_current and bob_current != "none") else auto_grade
        people.append({
            "uid":          uid,
            "name":         c.get("fullname", ""),
            "territory":    territory,
            "grade":        display_grade,
            "grade_label":  HPB_GRADE_LABELS.get(display_grade, "—"),
            "team":         team,
            "is_team_lead": is_lead,
            "start_date":   bob.get("start") or ov.get("crbb7_datejoined") or None,
            "q_grades":     q_grades,
            "q_targets":    q_targets,
            "quarters":     _hpb_quarter_billings(uid, placements, to_usd, today, year),
        })

    by_team = defaultdict(list)
    for p in people:
        if p["team"]:
            by_team[p["team"]].append(p)

    for lead in people:
        if not lead["is_team_lead"]:
            lead["team_quarters"]    = None
            lead["team_q_targets"]   = None
            continue
        members = [m for m in by_team.get(lead["team"], []) if m["uid"] != lead["uid"]]
        tq, ttarg = {}, {}
        for q in ("1", "2", "3", "4"):
            qstart = date(year, 3 * (int(q) - 1) + 1, 1)
            # Members who hadn't started by the quarter start don't count toward
            # the team's billings or target for that quarter.
            active = [m for m in members if _started_by(m.get("start_date"), qstart)]
            member_sum  = sum(m["quarters"][q] for m in active)
            lead_capped = min(lead["quarters"][q], HPB_TEAM_LEAD_CAP)
            tq[q] = round(member_sum + lead_capped, 2)
            # Team target uses each active member's grade at the start of that quarter.
            member_target = sum(HPB_TARGETS.get(m["q_grades"][q], 0) for m in active)
            lead_target   = HPB_TARGETS.get(lead["q_grades"][q], 100000)
            ttarg[q] = member_target + lead_target
        lead["team_quarters"]     = tq
        lead["team_q_targets"]    = ttarg
        lead["team_member_count"] = len(members)

    people.sort(key=lambda p: (p["team"] or "zzzz", not p["is_team_lead"], p["name"]))
    return {
        "people":          people,
        "team_lead_cap":   HPB_TEAM_LEAD_CAP,
        "current_quarter": current_quarter,
        "year":            year,
    }


def build_admin_report(
    consultants: list,
    placements_this: list,
    placements_last: list,
    overrides: list,
    today: date,
    team_map: dict = None,
    budgets: list = None,
    fx_rates: dict = None,
    bob_titles: dict = None,
) -> dict:
    """
    Builds the admin analytics report: monthly breakdown per consultant,
    territory totals, YoY comparison, and budget figures.
    """
    year = today.year
    to_gbp, to_usd = _build_fx_tables(fx_rates) if fx_rates else (TO_GBP, TO_USD)
    override_map = {o["crbb7_userid"]: o for o in overrides}

    # "Full Year Written Last YTD" cut-off: the same calendar date one year ago.
    # A placement created on this date last year counts; the day after does not.
    try:
        last_ytd_cutoff = date(year - 1, today.month, today.day)
    except ValueError:  # 29 Feb in a non-leap previous year
        last_ytd_cutoff = date(year - 1, today.month, 28)

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
                    "last_year_ytd":    compute_written_by_created(uid, placements_last, ccy, year - 1, last_ytd_cutoff, to_gbp, to_usd, after_date=move_date),
                    "note":             None,
                    "target":           round(float(ov["crbb7_target"]), 2) if ov.get("crbb7_target") is not None else None,
                    "placements":       _consultant_placement_details(uid, placements_this, ccy, year,     to_gbp, to_usd, after_date=move_date),
                    "last_placements":  _consultant_placement_details(uid, placements_last, ccy, year - 1, to_gbp, to_usd, after_date=move_date),
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
                    "last_year_ytd":    compute_written_by_created(uid, placements_last, prev_ccy, year - 1, last_ytd_cutoff, to_gbp, to_usd, before_date=move_date),
                    "note":             f"now in {territory}",
                    "target":           round(float(ov["crbb7_target"]), 2) if ov.get("crbb7_target") is not None else None,
                    "placements":       _consultant_placement_details(uid, placements_this, prev_ccy, year,     to_gbp, to_usd, before_date=move_date),
                    "last_placements":  _consultant_placement_details(uid, placements_last, prev_ccy, year - 1, to_gbp, to_usd, before_date=move_date),
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
                "last_year_ytd":    compute_written_by_created(uid, placements_last, ccy, year - 1, last_ytd_cutoff, to_gbp, to_usd),
                "note":             None,
                "target":           round(float(ov["crbb7_target"]), 2) if ov.get("crbb7_target") is not None else None,
                "placements":       _consultant_placement_details(uid, placements_this, ccy, year,     to_gbp, to_usd),
                "last_placements":  _consultant_placement_details(uid, placements_last, ccy, year - 1, to_gbp, to_usd),
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
        t_last_ytd    = 0.0
        for member in members:
            for m_str, v in member["months"].items():
                t_months[m_str] = round(t_months[m_str] + v, 2)
            for m_str, v in member.get("last_year_months", {}).items():
                t_last_months[m_str] = round(t_last_months[m_str] + v, 2)
            t_last     += member.get("last_year_total", 0)
            t_last_ytd += member.get("last_year_ytd", 0)
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
            "territory_last_year_ytd":  round(t_last_ytd, 2),
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
    other_last_ytd_gbp     = 0.0
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
        created = p.get("createdon")
        if created and parse_date(created) <= last_ytd_cutoff:
            other_last_ytd_gbp += gbp

    other_drilldown.sort(key=lambda p: p["start_date"], reverse=True)

    # ── Retained Business — placements whose candidate contact is RETAINER CANDIDATE ──
    from shared.dataverse import RETAINER_CANDIDATE_CONTACT_ID as _RETAINER_ID
    def _is_retainer(p):
        return p.get("_recruit_candidatecontact_value") == _RETAINER_ID

    retained_this = [p for p in placements_this if _is_retainer(p)]
    retained_last = [p for p in placements_last if _is_retainer(p)]

    retained_count      = len(retained_this)
    retained_count_last = len(retained_last)
    retained_total_gbp  = 0.0
    retained_last_gbp   = 0.0
    for p in retained_this:
        gp  = p.get("recruit_truegrossprofit") or 0.0
        ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode", "GBP")
        retained_total_gbp += gp * to_gbp.get(ccy, 1.0)
    for p in retained_last:
        gp  = p.get("recruit_truegrossprofit") or 0.0
        ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode", "GBP")
        retained_last_gbp += gp * to_gbp.get(ccy, 1.0)

    # Grand totals (territory rows + Other), all converted to GBP
    usd_to_gbp = to_gbp.get("USD", TO_GBP["USD"])
    USD_TERRITORIES = {"Chicago", "New York", "Chicago Contract"}
    grand_gbp              = 0.0
    grand_gbp_last         = 0.0
    grand_gbp_last_ytd     = 0.0
    grand_monthly_gbp      = {str(m): 0.0 for m in range(1, 13)}
    grand_monthly_last_gbp = {str(m): 0.0 for m in range(1, 13)}
    grand_budget_monthly   = {str(m): 0.0 for m in range(1, 13)}
    grand_budget_total     = 0.0
    for t, tdata in report.items():
        factor = usd_to_gbp if t in USD_TERRITORIES else 1.0
        grand_gbp          += tdata["territory_total"]         * factor
        grand_gbp_last     += tdata["territory_last_year"]     * factor
        grand_gbp_last_ytd += tdata["territory_last_year_ytd"] * factor
        for m_str, v in tdata["territory_months"].items():
            grand_monthly_gbp[m_str] = round(grand_monthly_gbp[m_str] + v * factor, 2)
        for m_str, v in tdata["territory_last_year_months"].items():
            grand_monthly_last_gbp[m_str] = round(grand_monthly_last_gbp[m_str] + v * factor, 2)
        budget_mths = tdata.get("budget", {}).get("months", {})
        for m_str, v in budget_mths.items():
            grand_budget_monthly[m_str] = round(grand_budget_monthly[m_str] + v * factor, 2)
        grand_budget_total = round(grand_budget_total + tdata.get("budget", {}).get("total", 0.0) * factor, 2)

    # Include Other in grand totals
    grand_gbp          = round(grand_gbp          + other_total_gbp,      2)
    grand_gbp_last     = round(grand_gbp_last     + other_last_total_gbp, 2)
    grand_gbp_last_ytd = round(grand_gbp_last_ytd + other_last_ytd_gbp,   2)
    for m_str, v in other_monthly_gbp.items():
        grand_monthly_gbp[m_str] = round(grand_monthly_gbp[m_str] + v, 2)
    for m_str, v in other_last_monthly_gbp.items():
        grand_monthly_last_gbp[m_str] = round(grand_monthly_last_gbp[m_str] + v, 2)

    return {
        "year":                    year,
        "usd_to_gbp":              round(usd_to_gbp, 6),
        "territories":             report,
        "other": {
            "total_gbp":         round(other_total_gbp, 2),
            "last_year_gbp":     round(other_last_total_gbp, 2),
            "last_year_ytd_gbp": round(other_last_ytd_gbp, 2),
            "monthly_gbp":     other_monthly_gbp,
            "last_monthly_gbp": other_last_monthly_gbp,
            "placements":      other_drilldown,
        },
        "grand_total_gbp":         round(grand_gbp, 2),
        "grand_total_last_gbp":    round(grand_gbp_last, 2),
        "grand_total_last_ytd_gbp": round(grand_gbp_last_ytd, 2),
        "grand_monthly_gbp":       grand_monthly_gbp,
        "grand_monthly_last_gbp":  grand_monthly_last_gbp,
        "grand_budget_monthly_gbp": grand_budget_monthly,
        "grand_budget_total_gbp":   grand_budget_total,
        "retained": {
            "count":      retained_count,
            "total_gbp":  round(retained_total_gbp, 2),
            "count_last": retained_count_last,
            "last_gbp":   round(retained_last_gbp, 2),
        },
        "hpb": build_hpb(consultants, placements_this, override_map, team_map or {}, to_usd, today, bob_titles),
    }


def build_report(
    consultants: list[dict],
    placements: list[dict],
    overrides: list[dict],
    today: date,
    team_map: dict = None,
    live_contracts: list = None,
    fx_rates: dict = None,
    nb_thresholds: dict = None,
    contract_placements: list = None,
    manual_nb_clients: dict = None,
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

        metrics = compute_metrics(uid, placements, ccy, today, to_gbp, to_usd, nb_thresholds,
                                  contract_placements, (manual_nb_clients or {}).get(uid, []))
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
