"""
Performance Stats — contract desk dashboard (pilot).

Scoped to the Chicago Contract desk: a placement counts if its Consultant or
Assignment Owner sits in that territory. Money is USD (the desk's currency).

"Runner" = a live contract/temp placement. Point-in-time metrics are evaluated
on a given date so the same function serves both this week and the 12-month
trend.
"""
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from shared.calc import TO_USD, _build_fx_tables, parse_date
from shared.dataverse import (TERRITORY_IDS, get_fx_rates, odata_get_all, odata_str)
from shared.mbr_registry import (BD_CALL_PURPOSES, BD_NO_PITCH_PURPOSE,
                                 CANDIDATE_CALL_PURPOSES, CLIENT_MEETING_PURPOSES)

DESK_TERRITORY = "Chicago Contract"
CONTRACT_TYPES = (143570001, 143570002)      # Contract, Temporary
CANCEL_CODES = (143570009, 143570010, 939310015, 939310016, 975310000)

# A "connect" is a call where someone was actually reached — cold calls that
# went unanswered or without a pitch don't count.
CONNECT_SALES = {k for k in BD_CALL_PURPOSES if k != BD_NO_PITCH_PURPOSE}
CONNECT_RECRUITING = set(CANDIDATE_CALL_PURPOSES)


def week_start(d: date) -> date:
    """Monday of that week."""
    return d - timedelta(days=d.weekday())


def month_starts(today: date, count: int = 12) -> list:
    """The first of each of the last `count` months, oldest first."""
    out, y, m = [], today.year, today.month
    for _ in range(count):
        out.append(date(y, m, 1))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


def _desk_user_ids() -> set:
    tid = TERRITORY_IDS[DESK_TERRITORY]
    return {u["systemuserid"] for u in odata_get_all("systemusers", params={
        "$select": "systemuserid",
        "$filter": f"_territoryid_value eq '{tid}'",
    })}


def _owned_by_desk(p: dict, desk: set) -> bool:
    return (p.get("_crimson_consultant_value") in desk
            or p.get("_mercury_assignmentowner_value") in desk)


def _contract_placements(since: date) -> list:
    """Every non-cancelled contract/temp placement that could still be running."""
    type_filter = " or ".join(f"crimson_type eq {t}" for t in CONTRACT_TYPES)
    cancel_filter = " and ".join(f"statuscode ne {c}" for c in CANCEL_CODES)
    return odata_get_all("crimson_placements", params={
        "$select": ("crimson_placementid,crimson_name,crimson_type,crimson_startdate,"
                    "crimson_enddate,crimson_actualenddate,mercury_hoursperweek,"
                    "recruit_trueweeklygrossprofit,mercury_marginpercent,"
                    "_crimson_clientname_value,_crimson_consultant_value,"
                    "_mercury_assignmentowner_value"),
        "$filter": (f"({type_filter}) and statecode eq 0 and {cancel_filter}"
                    f" and crimson_enddate ge {since.isoformat()}"),
        "$expand": ("crimson_clientname($select=name),"
                    "recruit_trueweeklygrossprofitcurrency($select=isocurrencycode)"),
    })


def _is_running_on(p: dict, when: date) -> bool:
    try:
        start = parse_date(p["crimson_startdate"])
        end = parse_date(p.get("crimson_actualenddate") or p["crimson_enddate"])
    except Exception:
        return False
    return start <= when <= end


def _owner_filter(desk: set) -> str:
    """OData OR across the desk's owners — filter server-side, not in Python:
    a year of org-wide phone calls is tens of thousands of rows."""
    return " or ".join(f"_ownerid_value eq '{odata_str(u)}'" for u in desk)


def _activities(entity: str, datefield: str, desk: set, start: date, end: date) -> list:
    if not desk:
        return []
    return odata_get_all(entity, params={
        "$select": f"activityid,_mercury_purpose_value,_ownerid_value,{datefield}",
        "$filter": (f"({_owner_filter(desk)})"
                    f" and {datefield} ge {start.isoformat()}"
                    f" and {datefield} lt {end.isoformat()}"),
    })


def build_performance_stats(today: date = None) -> dict:
    today = today or date.today()
    this_week = week_start(today)
    last_week = this_week - timedelta(days=7)
    year_ago = date(today.year - 1, today.month, 1)

    try:
        _, usd = _build_fx_tables(get_fx_rates())
    except Exception:
        usd = TO_USD

    with ThreadPoolExecutor(max_workers=6) as pool:
        f_desk = pool.submit(_desk_user_ids)
        desk = f_desk.result()
        f_pl   = pool.submit(_contract_placements, year_ago)
        f_sl   = pool.submit(_shortlists_for_desk, desk, this_week, this_week + timedelta(days=7))
        f_call = pool.submit(_activities, "phonecalls", "createdon", desk,
                             month_starts(today)[0], today + timedelta(days=1))
        f_appt = pool.submit(_activities, "appointments", "scheduledstart", desk,
                             this_week, this_week + timedelta(days=7))
        f_vac  = pool.submit(_vacancies, desk, month_starts(today)[0], today + timedelta(days=1))
        placements = [p for p in f_pl.result() if _owned_by_desk(p, desk)]
        shortlists, calls, appts, vacancies = (f_sl.result(), f_call.result(),
                                               f_appt.result(), f_vac.result())

    def weekly_gp(p):
        ccy = (p.get("recruit_trueweeklygrossprofitcurrency") or {}).get("isocurrencycode")
        return (p.get("recruit_trueweeklygrossprofit") or 0.0) * usd.get(ccy, 1.0)

    def weekly_revenue(p):
        # mercury_charge_mc is a RATE at mixed frequencies (hourly, daily,
        # monthly) so it can't be summed. Weekly GP is normalised, so derive
        # revenue from it and the margin — verified against live rows.
        margin = p.get("mercury_marginpercent") or 0
        return weekly_gp(p) / (margin / 100.0) if margin else 0.0

    def snapshot(when: date) -> dict:
        live = [p for p in placements if _is_running_on(p, when)]
        return {
            "runners": len(live),
            "gp":      round(sum(weekly_gp(p) for p in live), 2),
            "revenue": round(sum(weekly_revenue(p) for p in live), 2),
            "hours":   round(sum(p.get("mercury_hoursperweek") or 0 for p in live), 1),
        }

    now_snap  = snapshot(today)
    last_snap = snapshot(today - timedelta(days=7))

    # 12-month trend, each point taken on the last day of that month (or today)
    trend = []
    for first in month_starts(today):
        nxt = date(first.year + (1 if first.month == 12 else 0),
                   1 if first.month == 12 else first.month + 1, 1)
        point = min(nxt - timedelta(days=1), today)
        s = snapshot(point)
        month_calls = [c for c in calls
                       if first.isoformat() <= (c.get("createdon") or "")[:10] < nxt.isoformat()]
        trend.append({
            "month": f"{first.year}-{first.month:02d}",
            "runners": s["runners"], "gp": s["gp"], "revenue": s["revenue"], "hours": s["hours"],
            "job_orders": len([v for v in vacancies
                               if first.isoformat() <= (v.get("createdon") or "")[:10] < nxt.isoformat()]),
            "connects": len([c for c in month_calls
                             if c.get("_mercury_purpose_value") in CONNECT_SALES | CONNECT_RECRUITING]),
        })

    # Clients
    live_now = [p for p in placements if _is_running_on(p, today)]
    per_client = Counter(p.get("_crimson_clientname_value") for p in live_now
                         if p.get("_crimson_clientname_value"))
    names = {p.get("_crimson_clientname_value"): (p.get("crimson_clientname") or {}).get("name")
             for p in placements}
    multi = sorted(((names.get(c) or "(client)", n) for c, n in per_client.items() if n > 1),
                   key=lambda x: -x[1])
    billed_12m = {p.get("_crimson_clientname_value") for p in placements
                  if p.get("_crimson_clientname_value")
                  and any(_is_running_on(p, d) for d in
                          (year_ago, today, parse_date(p["crimson_startdate"])))}

    # This week's activity
    wk_end = this_week + timedelta(days=7)
    def in_week(raw):
        return bool(raw) and this_week.isoformat() <= raw[:10] < wk_end.isoformat()

    week_calls = [c for c in calls if in_week(c.get("createdon"))]
    starting_week = [p for p in placements if in_week(p.get("crimson_startdate"))]
    ending_week   = [p for p in placements
                     if in_week(p.get("crimson_actualenddate") or p.get("crimson_enddate"))]
    future_start  = [p for p in placements
                     if (p.get("crimson_startdate") or "")[:10] >= wk_end.isoformat()]
    in_30 = (today + timedelta(days=30)).isoformat()
    future_ends = [p for p in placements if _is_running_on(p, today)
                   and today.isoformat() < (p.get("crimson_actualenddate")
                                            or p.get("crimson_enddate") or "")[:10] <= in_30]

    return {
        "desk": DESK_TERRITORY, "as_of": today.isoformat(), "sym": "$",
        "week_start": this_week.isoformat(),
        "now": now_snap, "last_week": last_snap,
        "trend": trend,
        "billed_clients_12m": len(billed_12m),
        "clients_multi_runners": [{"client": c, "runners": n} for c, n in multi],
        "week": {
            "interviews": sum(1 for s in shortlists if s["_iv"]),
            "cvs": sum(1 for s in shortlists if s["_cv"]),
            "client_visits": len([a for a in appts
                                  if a.get("_mercury_purpose_value") in CLIENT_MEETING_PURPOSES]),
            "connects": len([c for c in week_calls
                             if c.get("_mercury_purpose_value") in CONNECT_SALES | CONNECT_RECRUITING]),
            "connects_sales": len([c for c in week_calls
                                   if c.get("_mercury_purpose_value") in CONNECT_SALES]),
            "connects_recruiting": len([c for c in week_calls
                                        if c.get("_mercury_purpose_value") in CONNECT_RECRUITING]),
            "starting": [_runner_row(p, names) for p in starting_week],
            "ending":   [_runner_row(p, names) for p in ending_week],
        },
        "future_starts": [_runner_row(p, names) for p in
                          sorted(future_start, key=lambda x: x.get("crimson_startdate") or "")],
        "future_ends_30d": [_runner_row(p, names) for p in
                            sorted(future_ends, key=lambda x: (x.get("crimson_actualenddate")
                                                               or x.get("crimson_enddate") or ""))],
    }


def _runner_row(p: dict, names: dict) -> dict:
    return {
        "role":   p.get("crimson_name") or "",
        "client": names.get(p.get("_crimson_clientname_value")) or "(client)",
        "start":  (p.get("crimson_startdate") or "")[:10],
        "end":    (p.get("crimson_actualenddate") or p.get("crimson_enddate") or "")[:10],
        "hours":  p.get("mercury_hoursperweek") or 0,
    }


def _shortlists_for_desk(desk: set, start: date, end: date) -> list:
    s, e = start.isoformat(), end.isoformat()
    rows = odata_get_all("crimson_vacancycandidates", params={
        "$select": ("crimson_vacancycandidateid,new_statussubmitteddate,_owninguser_value,"
                    "mercury_firstinterviewdate,mercury_furtherinterviewdate,"
                    "mercury_finalinterviewdate"),
        "$filter": (f"(new_statussubmitteddate ge {s} and new_statussubmitteddate lt {e}) or "
                    f"(mercury_firstinterviewdate ge {s} and mercury_firstinterviewdate lt {e}) or "
                    f"(mercury_furtherinterviewdate ge {s} and mercury_furtherinterviewdate lt {e}) or "
                    f"(mercury_finalinterviewdate ge {s} and mercury_finalinterviewdate lt {e})"),
    })
    out = []
    for r in rows:
        if r.get("_owninguser_value") not in desk:
            continue
        iv = any((r.get(f) or "")[:10] and s <= (r.get(f) or "")[:10] < e
                 for f in ("mercury_firstinterviewdate", "mercury_furtherinterviewdate",
                           "mercury_finalinterviewdate"))
        cv = bool((r.get("new_statussubmitteddate") or "")[:10]
                  and s <= (r["new_statussubmitteddate"])[:10] < e)
        out.append({"_iv": iv, "_cv": cv})
    return out


def _vacancies(desk: set, start: date, end: date) -> list:
    if not desk:
        return []
    return odata_get_all("crimson_vacancies", params={
        "$select": "crimson_vacancyid,createdon,_ownerid_value",
        "$filter": (f"({_owner_filter(desk)})"
                    f" and createdon ge {start.isoformat()}T00:00:00Z"
                    f" and createdon lt {end.isoformat()}T00:00:00Z"),
    })
