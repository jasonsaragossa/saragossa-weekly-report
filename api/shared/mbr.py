"""
MBR computation: every registry metric for one consultant for one month,
with last-month and quarter-to-date comparators.

Everything here is derived from Mercury. Judgement fields and actions live in
crbb7_mbr / crbb7_mbraction and never come near this module.
"""
import logging
from datetime import date
from concurrent.futures import ThreadPoolExecutor

from shared.calc import TO_GBP, _build_fx_tables, split_factor, parse_date, rebate_of
from shared.dataverse import (odata_get_all, odata_str, active_or_rebated_filter,
                              get_fx_rates)
from shared.mbr_registry import (BD_CALL_PURPOSES, BD_NO_PITCH_PURPOSE, BD_PITCH_PURPOSE,
                                 CANDIDATE_CALL_PURPOSES, CLIENT_MEETING_PURPOSES,
                                 LEAD_PURPOSES, REGISTRY, SPEC_CV_PURPOSES)

PERM_TYPE = 143570000
RETAINER_CONTACT = "7aa8cfa4-d1f2-f011-8406-7c1e52796145"


def month_bounds(year: int, month: int) -> tuple:
    start = date(year, month, 1)
    end = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
    return start, end


def previous_month(year: int, month: int) -> tuple:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def quarter_months(year: int, month: int) -> list:
    """Months of the quarter up to and including this one."""
    q_start = 3 * ((month - 1) // 3) + 1
    return [(year, m) for m in range(q_start, month + 1)]


# ── Raw fetches ───────────────────────────────────────────────────────────────

def _placements(uid: str, start: date, end: date) -> list:
    return odata_get_all("crimson_placements", params={
        "$select": ("crimson_placementid,crimson_name,crimson_type,crimson_startdate,"
                    "recruit_truegrossprofit,crimson_specialinstructionsclient,statuscode,"
                    "recruit_rebateamount,recruit_rebatedon,_recruit_candidatecontact_value,"
                    "_crimson_clientname_value,_mercury_clientrelationshipowner_value,"
                    "_crimson_consultant_value,_mercury_assignmentowner_value,"
                    "_mercury_contractorrelationship_userid_value,crimson_extension,"
                    "crimson_placementidcode,_mercury_parentplacementid_value"),
        "$filter": (f"crimson_type eq {PERM_TYPE}"
                    f" and crimson_startdate ge {start.isoformat()}"
                    f" and crimson_startdate lt {end.isoformat()}"
                    f" and {active_or_rebated_filter()}"
                    f" and (_crimson_consultant_value eq '{odata_str(uid)}'"
                    f" or _mercury_assignmentowner_value eq '{odata_str(uid)}'"
                    f" or _mercury_clientrelationshipowner_value eq '{odata_str(uid)}'"
                    f" or _mercury_contractorrelationship_userid_value eq '{odata_str(uid)}')"),
        "$expand": "recruit_truegrossprofitcurrency($select=isocurrencycode)",
    })


def _shortlists(uid: str, start: date, end: date) -> list:
    """Shortlist rows touched in the window — dates are filtered per metric below."""
    s, e = start.isoformat(), end.isoformat()
    return odata_get_all("crimson_vacancycandidates", params={
        "$select": ("crimson_vacancycandidateid,new_statussubmitteddate,"
                    "mercury_firstinterviewdate,mercury_furtherinterviewdate,"
                    "mercury_finalinterviewdate,new_statusoffermadedate"),
        "$filter": (f"_owninguser_value eq '{odata_str(uid)}' and ("
                    f"(new_statussubmitteddate ge {s} and new_statussubmitteddate lt {e}) or "
                    f"(mercury_firstinterviewdate ge {s} and mercury_firstinterviewdate lt {e}) or "
                    f"(mercury_furtherinterviewdate ge {s} and mercury_furtherinterviewdate lt {e}) or "
                    f"(mercury_finalinterviewdate ge {s} and mercury_finalinterviewdate lt {e}) or "
                    f"(new_statusoffermadedate ge {s} and new_statusoffermadedate lt {e}))"),
    })


def _activities(entity: str, datefield: str, uid: str, start: date, end: date) -> list:
    return odata_get_all(entity, params={
        "$select": f"activityid,_mercury_purpose_value,{datefield}",
        "$filter": (f"_ownerid_value eq '{odata_str(uid)}'"
                    f" and {datefield} ge {start.isoformat()}"
                    f" and {datefield} lt {end.isoformat()}"),
    })


# ── Metric computation ────────────────────────────────────────────────────────

def _in(raw, start: date, end: date) -> bool:
    if not raw:
        return False
    try:
        d = parse_date(raw)
    except Exception:
        return False
    return start <= d < end


def compute_month(uid: str, year: int, month: int, to_gbp: dict = None) -> dict:
    """{metric_key: value} for one consultant in one month."""
    start, end = month_bounds(year, month)
    fx = to_gbp or TO_GBP

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_pl = pool.submit(_placements, uid, start, end)
        f_sl = pool.submit(_shortlists, uid, start, end)
        f_ca = pool.submit(_activities, "phonecalls", "createdon", uid, start, end)
        f_ap = pool.submit(_activities, "appointments", "scheduledstart", uid, start, end)
        placements, shortlists, calls, appts = f_pl.result(), f_sl.result(), f_ca.result(), f_ap.result()

    # Revenue
    gp = deals = 0.0
    clients = set()
    for p in placements:
        if p.get("_recruit_candidatecontact_value") == RETAINER_CONTACT:
            continue
        factor = split_factor(p, uid)
        amount = (p.get("recruit_truegrossprofit") or 0.0) - rebate_of(p)[0]
        ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode")
        gp += amount * factor * fx.get(ccy, 1.0)
        if p.get("_crimson_consultant_value") == uid:
            deals += 0.5
        if p.get("_mercury_assignmentowner_value") == uid:
            deals += 0.5
        if (p.get("_mercury_clientrelationshipowner_value") == uid
                and "new business" in (p.get("crimson_specialinstructionsclient") or "").lower()):
            if p.get("_crimson_clientname_value"):
                clients.add(p["_crimson_clientname_value"])

    # Funnel
    cvs   = sum(1 for s in shortlists if _in(s.get("new_statussubmitteddate"), start, end))
    iv1   = sum(1 for s in shortlists if _in(s.get("mercury_firstinterviewdate"), start, end))
    ivf   = sum(1 for s in shortlists
                if _in(s.get("mercury_furtherinterviewdate"), start, end)
                or _in(s.get("mercury_finalinterviewdate"), start, end))
    offers = sum(1 for s in shortlists if _in(s.get("new_statusoffermadedate"), start, end))

    # Activity
    def count(rows, purposes):
        return sum(1 for r in rows if r.get("_mercury_purpose_value") in purposes)

    bd        = count(calls, BD_CALL_PURPOSES)
    pitched   = count(calls, {BD_PITCH_PURPOSE})
    no_pitch  = count(calls, {BD_NO_PITCH_PURPOSE})
    cand_call = count(calls, CANDIDATE_CALL_PURPOSES)
    meetings  = count(appts, CLIENT_MEETING_PURPOSES) + count(calls, CLIENT_MEETING_PURPOSES)
    leads     = count(calls, LEAD_PURPOSES)
    spec      = count(calls, SPEC_CV_PURPOSES) + count(appts, SPEC_CV_PURPOSES)

    return {
        "perm_gp":            round(gp, 2),
        "deals":              round(deals, 1),
        "new_clients":        len(clients),
        "cvs_sent":           cvs,
        "interviews_first":   iv1,
        "interviews_further": ivf,
        "offers":             offers,
        "cv_to_interview":    round(iv1 / cvs, 2) if cvs else None,
        "bd_calls":           bd,
        "bd_pitch_rate":      round(pitched / (pitched + no_pitch) * 100, 1) if (pitched + no_pitch) else None,
        "client_meetings":    meetings,
        "spec_cvs":           spec,
        "leads_gained":       leads,
        "candidate_calls":    cand_call,
    }


def compute_ytd_headline(uid: str, year: int, month: int, to_gbp: dict = None) -> dict:
    """
    Year-to-date revenue, deals and distinct new-business clients — the three
    figures everyone carries at the top of the MBR regardless of team config.
    One placement query for the whole year rather than twelve monthly ones.
    """
    fx = to_gbp or TO_GBP
    start = date(year, 1, 1)
    _, end = month_bounds(year, month)          # through the end of the MBR month

    gp = deals = 0.0
    clients = set()
    for p in _placements(uid, start, end):
        if p.get("_recruit_candidatecontact_value") == RETAINER_CONTACT:
            continue
        amount = (p.get("recruit_truegrossprofit") or 0.0) - rebate_of(p)[0]
        ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode")
        gp += amount * split_factor(p, uid) * fx.get(ccy, 1.0)
        if p.get("_crimson_consultant_value") == uid:
            deals += 0.5
        if p.get("_mercury_assignmentowner_value") == uid:
            deals += 0.5
        if (p.get("_mercury_clientrelationshipowner_value") == uid
                and "new business" in (p.get("crimson_specialinstructionsclient") or "").lower()
                and p.get("_crimson_clientname_value")):
            clients.add(p["_crimson_clientname_value"])
    return {"revenue": round(gp, 2), "deals": round(deals, 1), "new_clients": len(clients)}


def build_mbr_metrics(uid: str, year: int, month: int) -> dict:
    """
    Metrics for the month, the month before, and quarter-to-date, shaped for the
    form: [{key, name, family, value, previous, change_pct, target, direction, …}]
    """
    try:
        to_gbp, _ = _build_fx_tables(get_fx_rates())
    except Exception:
        to_gbp = TO_GBP

    py, pm = previous_month(year, month)
    q_months = quarter_months(year, month)

    with ThreadPoolExecutor(max_workers=8) as pool:
        f_now  = pool.submit(compute_month, uid, year, month, to_gbp)
        f_prev = pool.submit(compute_month, uid, py, pm, to_gbp)
        f_ytd  = pool.submit(compute_ytd_headline, uid, year, month, to_gbp)
        # QTD = the quarter's months excluding the current one (already in f_now)
        f_q = [pool.submit(compute_month, uid, y, m, to_gbp)
               for (y, m) in q_months if (y, m) != (year, month)]
        now, prev = f_now.result(), f_prev.result()
        headline = f_ytd.result()
        earlier = [f.result() for f in f_q]

    qtd = {}
    for key in now:
        vals = [d.get(key) for d in earlier + [now] if d.get(key) is not None]
        # Ratios don't sum; show the current month's figure instead
        qtd[key] = round(sum(vals), 2) if vals and key not in ("cv_to_interview", "bd_pitch_rate") \
            else now.get(key)

    rows = []
    for m in REGISTRY:
        key = m["key"]
        val, was = now.get(key), prev.get(key)
        change = None
        if isinstance(val, (int, float)) and isinstance(was, (int, float)) and was:
            change = round((val - was) / was * 100, 1)
        rows.append({
            "key": key, "name": m["name"], "family": m["family"],
            "definition": m["definition"], "direction": m["direction"],
            "format": m["format"], "target_key": m["target_key"],
            "prompt_context": m["prompt_context"],
            "value": val, "previous": was, "qtd": qtd.get(key), "change_pct": change,
        })
    return {"metrics": rows, "month": f"{year}-{month:02d}",
            "previous_month": f"{py}-{pm:02d}", "ytd": headline}
