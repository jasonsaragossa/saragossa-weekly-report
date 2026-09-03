"""
Weekly 1:1 — derived inputs for the Team Snoz template.

Mirrors "Weekly 1 to 1 template - updated September 2026": the Key Inputs table
and the Live Jobs / meetings lists come from Mercury; everything else on the
form is judgement and is typed by the consultant.

Mappings agreed with Jason (Sept 2026) are recorded next to each metric.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from shared.calc import parse_date
from shared.dataverse import (active_or_rebated_filter, odata_get_all, odata_str)
from shared.mbr_registry import CANDIDATE_CALL_PURPOSES

PERM_TYPE = 143570000

# Purpose families for the Key Inputs table
NEW_CLIENT_MEETING = {
    "92fcaab8-9a50-ee11-be6f-0022481b503e",   # New Client Meeting
    "bdf76a79-e9f0-ee11-904c-6045bdd19e21",   # Subsequent New Client Meeting
}
EXISTING_CLIENT_MEETING = {
    "28103947-f1aa-ee11-be37-002248c7244c",   # Existing Client Meeting
    "94fcaab8-9a50-ee11-be6f-0022481b503e",   # Client Presentation
    "11350f1f-1e4e-f111-bec6-002248433928",   # Solution Cross-Sell Meeting
}
PITCH = {"45e272c6-a769-ee11-94f7-000d3ad6abf9"}          # BD Cold Call - Pitch Delivered
CANDIDATE_MEETING = {
    "46e272c6-a769-ee11-94f7-000d3ad6abf9",   # Candidate Meeting
    "90fcaab8-9a50-ee11-be6f-0022481b503e",   # Candidate Meeting (duplicate id in Mercury)
    "403d3f07-29ab-ee11-be37-002248c7244c",   # Candidate Flip Meeting
}
# "BD emails" per Jason: sales messages plus the spec-CV family
BD_EMAIL = {
    "4be272c6-a769-ee11-94f7-000d3ad6abf9",   # Intro Sales Message
    "4ee272c6-a769-ee11-94f7-000d3ad6abf9",   # Follow Up Sales Message
    "4de272c6-a769-ee11-94f7-000d3ad6abf9",   # Marketing Message
    "47e272c6-a769-ee11-94f7-000d3ad6abf9",   # Spec CV
    "573fc500-5f8e-f011-b4cb-7c1e52656983",   # Spec CV Follow Up Email
    "4cf063c0-de38-f111-88b5-7c1e5209a533",   # Spec CV Follow Up Call
}
LEADS = {
    "d59958b7-98c6-ee11-9079-002248c7244c",   # Lead Gained from Candidate
    "b6e30f54-40cb-ee11-9079-6045bd0c1c1b",   # Manager Referral
}
ALL_CLIENT_MEETINGS = NEW_CLIENT_MEETING | EXISTING_CLIENT_MEETING

# Vacancy statuses that are closed — "live jobs" is everything else, still active
CLOSED_VACANCY_STATUS = {
    143570007,  # Placement
    2,          # Won - part filled
    143570000,  # Won - all positions filled
    143570001, 143570002, 939310002, 939310000,   # Lost - various
    143570003,  # Cancelled
    975310002,  # Rejected
}
PRIORITY_LABEL = {939310000: "High", 939310001: "Medium", 939310002: "Low", 939310003: "On Hold"}
PRIORITY_ORDER = {939310000: 0, 939310001: 1, 939310002: 2, 939310003: 3, None: 4}


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


QUARTER_LABELS = {1: "Jan–Mar", 2: "Apr–Jun", 3: "Jul–Sep", 4: "Oct–Dec"}


def quarter_of(d: date) -> int:
    return (d.month - 1) // 3 + 1


def quarter_weeks(d: date) -> dict:
    """
    Every week in the calendar quarter containing `d`, so a quarter's worth of
    1:1s sits on one page (Jason, Sept 2026).
    """
    q = quarter_of(d)
    start = date(d.year, 3 * (q - 1) + 1, 1)
    end = date(d.year + (1 if q == 4 else 0), 1 if q == 4 else 3 * q + 1, 1)
    weeks, wk = [], week_start(start)
    while wk < end:
        weeks.append(wk.isoformat())
        wk += timedelta(days=7)
    return {"year": d.year, "quarter": q, "label": f"{QUARTER_LABELS[q]} {d.year}",
            "weeks": weeks}


def _activities(entity: str, datefield: str, uid: str, start: date, end: date) -> list:
    return odata_get_all(entity, params={
        "$select": f"activityid,_mercury_purpose_value,{datefield},subject",
        "$filter": (f"_ownerid_value eq '{odata_str(uid)}'"
                    f" and {datefield} ge {start.isoformat()}"
                    f" and {datefield} lt {end.isoformat()}"),
        "$expand": "regardingobjectid_account($select=name)",
    })


def _shortlists(uid: str, start: date, end: date) -> list:
    s, e = start.isoformat(), end.isoformat()
    return odata_get_all("crimson_vacancycandidates", params={
        "$select": ("crimson_vacancycandidateid,new_statussubmitteddate,"
                    "mercury_firstinterviewdate"),
        "$filter": (f"_owninguser_value eq '{odata_str(uid)}' and ("
                    f"(new_statussubmitteddate ge {s} and new_statussubmitteddate lt {e}) or "
                    f"(mercury_firstinterviewdate ge {s} and mercury_firstinterviewdate lt {e}))"),
    })


def _placements_created(uid: str, start: date, end: date) -> list:
    """Deals done in the week = placements CREATED, which is what the consultant did."""
    return odata_get_all("crimson_placements", params={
        "$select": "crimson_placementid,createdon",
        "$filter": (f"createdon ge {start.isoformat()}T00:00:00Z"
                    f" and createdon lt {end.isoformat()}T00:00:00Z"
                    f" and {active_or_rebated_filter()}"
                    f" and (_crimson_consultant_value eq '{odata_str(uid)}'"
                    f" or _mercury_assignmentowner_value eq '{odata_str(uid)}')"),
    })


# Shortlist statuses that are no longer live with the client
DEAD_SHORTLIST_STATUS = {143570004, 2}      # Rejected, Inactive


def _live_cvs_by_job(uid: str, vacancy_ids: list) -> dict:
    """
    {vacancy_id: count} — CVs this person submitted that are still active.
    Deliberately not the vacancy's mercury_totalsubmitted rollup: that counts
    every consultant's submissions and keeps rejected ones, which overstated
    a job by 34 vs 21 in testing (Jason's call, Sept 2026).
    """
    out = {v: 0 for v in vacancy_ids}
    for i in range(0, len(vacancy_ids), 20):
        chunk = vacancy_ids[i:i + 20]
        or_f = " or ".join(f"_crimson_vacancyid_value eq '{v}'" for v in chunk)
        for s in odata_get_all("crimson_vacancycandidates", params={
            "$select": "_crimson_vacancyid_value,statuscode,new_statussubmitteddate",
            "$filter": f"({or_f}) and _owninguser_value eq '{odata_str(uid)}'",
        }):
            if (s.get("new_statussubmitteddate")
                    and s.get("statuscode") not in DEAD_SHORTLIST_STATUS):
                out[s["_crimson_vacancyid_value"]] = out.get(s["_crimson_vacancyid_value"], 0) + 1
    return out


def _live_jobs(uid: str) -> list:
    """Any active vacancy where this person is the delivery owner (Jason, Sept 2026)."""
    rows = odata_get_all("crimson_vacancies", params={
        "$select": ("crimson_vacancyid,crimson_jobtitle,crimson_name,statuscode,"
                    "mercury_priority,createdon"),
        "$filter": (f"_crimson_deliveryownerid_value eq '{odata_str(uid)}'"
                    f" and statecode eq 0"),
        "$expand": "crimson_clientid($select=name)",
    })
    live = [v for v in rows if v.get("statuscode") not in CLOSED_VACANCY_STATUS]
    live.sort(key=lambda v: (PRIORITY_ORDER.get(v.get("mercury_priority"), 4),
                             v.get("createdon") or ""))
    cvs = _live_cvs_by_job(uid, [v["crimson_vacancyid"] for v in live])
    return [{
        "client":   (v.get("crimson_clientid") or {}).get("name") or "(client)",
        "job":      v.get("crimson_jobtitle") or v.get("crimson_name") or "",
        "priority": PRIORITY_LABEL.get(v.get("mercury_priority"), "—"),
        "cvs_out":  cvs.get(v["crimson_vacancyid"], 0),
        "id":       v["crimson_vacancyid"],
    } for v in live]


def _count(rows, purposes):
    return sum(1 for r in rows if r.get("_mercury_purpose_value") in purposes)


def _meeting_rows(appts, purposes):
    out = []
    for a in appts:
        if a.get("_mercury_purpose_value") not in purposes:
            continue
        out.append({
            "client": (a.get("regardingobjectid_account") or {}).get("name")
                      or (a.get("subject") or "(meeting)"),
            "when": (a.get("scheduledstart") or "")[:10],
            "subject": a.get("subject") or "",
        })
    return sorted(out, key=lambda x: x["when"])


def build_one_to_one(uid: str, week: date = None) -> dict:
    """Derived half of the 1:1: key inputs, live jobs, and the meeting lists."""
    week = week_start(week or date.today())
    next_week = week + timedelta(days=7)
    last_week = week - timedelta(days=7)
    month_start = date(week.year, week.month, 1)

    with ThreadPoolExecutor(max_workers=8) as pool:
        f = {
            "sl_last":  pool.submit(_shortlists, uid, last_week, week),
            "sl_month": pool.submit(_shortlists, uid, month_start, next_week),
            "ca_last":  pool.submit(_activities, "phonecalls", "createdon", uid, last_week, week),
            "ca_month": pool.submit(_activities, "phonecalls", "createdon", uid, month_start, next_week),
            "ap_last":  pool.submit(_activities, "appointments", "scheduledstart", uid, last_week, week),
            "ap_month": pool.submit(_activities, "appointments", "scheduledstart", uid, month_start, next_week),
            "ap_this":  pool.submit(_activities, "appointments", "scheduledstart", uid, week, next_week),
            "pl_last":  pool.submit(_placements_created, uid, last_week, week),
            "pl_month": pool.submit(_placements_created, uid, month_start, next_week),
            "jobs":     pool.submit(_live_jobs, uid),
        }
        r = {k: v.result() for k, v in f.items()}

    def inputs(sl, calls, appts, pls):
        return {
            "cvs":                sum(1 for s in sl if s.get("new_statussubmitteddate")),
            "interviews":         sum(1 for s in sl if s.get("mercury_firstinterviewdate")),
            "client_meetings_new":      _count(appts, NEW_CLIENT_MEETING),
            "client_meetings_existing": _count(appts, EXISTING_CLIENT_MEETING),
            "deals":              len(pls),
            "pitches":            _count(calls, PITCH),
            "bd_emails":          _count(calls, BD_EMAIL) + _count(appts, BD_EMAIL),
            "candidate_meets":    _count(appts, CANDIDATE_MEETING) + _count(calls, CANDIDATE_MEETING),
            "candidate_calls":    _count(calls, set(CANDIDATE_CALL_PURPOSES)),
            "leads":              _count(calls, LEADS),
        }

    return {
        "week_start": week.isoformat(),
        "last_week":  inputs(r["sl_last"], r["ca_last"], r["ap_last"], r["pl_last"]),
        "month":      inputs(r["sl_month"], r["ca_month"], r["ap_month"], r["pl_month"]),
        "live_jobs":  r["jobs"],
        "meetings_last_week": _meeting_rows(r["ap_last"], ALL_CLIENT_MEETINGS),
        "meetings_this_week": _meeting_rows(r["ap_this"], ALL_CLIENT_MEETINGS),
    }


INPUT_ROWS = [
    ("cvs",                      "CVs"),
    ("interviews",               "Interviews"),
    ("client_meetings_new",      "Client meetings (new)"),
    ("client_meetings_existing", "Client meetings (existing)"),
    ("deals",                    "Deals"),
    ("pitches",                  "Pitches / client conversations"),
    ("bd_emails",                "BD emails"),
    ("candidate_meets",          "Senior candidate meets"),
    ("candidate_calls",          "Candidate calls"),
    ("leads",                    "Leads"),
]
