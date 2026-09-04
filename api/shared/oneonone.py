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


ROLLING_WEEKS = 13          # a rolling quarter, not a calendar one


def quarter_weeks(d: date, count: int = ROLLING_WEEKS) -> dict:
    """
    The rolling 13 weeks ending at `d` — so crossing into a new calendar quarter
    doesn't hide the weeks either side of it (Jason, Sept 2026). Nothing is ever
    deleted: older weeks stay in Dataverse and are reachable by paging back.
    """
    end = week_start(d)
    weeks = [(end - timedelta(days=7 * i)).isoformat() for i in range(count - 1, -1, -1)]
    first = date.fromisoformat(weeks[0])
    fmt = "%b %Y" if first.year != end.year else "%b"
    return {
        "label": f"{first.strftime(fmt)} – {end.strftime('%b %Y')}",
        "weeks": weeks,
        "prev": (end - timedelta(days=7 * count)).isoformat(),
        "next": (end + timedelta(days=7 * count)).isoformat(),
    }


def _activities(entity: str, datefield: str, uid: str, start: date, end: date) -> list:
    return odata_get_all(entity, params={
        "$select": f"activityid,_mercury_purpose_value,{datefield},subject",
        "$filter": (f"_ownerid_value eq '{odata_str(uid)}'"
                    f" and {datefield} ge {start.isoformat()}"
                    f" and {datefield} lt {end.isoformat()}"),
        "$expand": ("regardingobjectid_account($select=name),"
                    "regardingobjectid_contact($select=fullname,jobtitle,_parentcustomerid_value)"),
    })


def _emails(uid: str, start: date, end: date) -> list:
    """
    Sales emails. NB: the email entity tags its purpose with
    _recruit_purpose_value, NOT the _mercury_purpose_value used by calls and
    appointments — checking only the latter made BD emails read as zero.
    """
    f = " or ".join(f"_recruit_purpose_value eq '{p}'" for p in BD_EMAIL)
    return odata_get_all("emails", params={
        "$select": "activityid,_recruit_purpose_value,subject,createdon",
        "$filter": (f"({f}) and _ownerid_value eq '{odata_str(uid)}'"
                    f" and createdon ge {start.isoformat()}"
                    f" and createdon lt {end.isoformat()}"),
        "$expand": ("regardingobjectid_account($select=name),"
                    "regardingobjectid_contact($select=fullname,jobtitle,_parentcustomerid_value)"),
    })


def _shortlists(uid: str, start: date, end: date) -> list:
    s, e = start.isoformat(), end.isoformat()
    return odata_get_all("crimson_vacancycandidates", params={
        "$select": ("crimson_vacancycandidateid,new_statussubmitteddate,"
                    "mercury_firstinterviewdate,crimson_name"),
        "$filter": (f"_owninguser_value eq '{odata_str(uid)}' and ("
                    f"(new_statussubmitteddate ge {s} and new_statussubmitteddate lt {e}) or "
                    f"(mercury_firstinterviewdate ge {s} and mercury_firstinterviewdate lt {e}))"),
        "$expand": ("recruit_candidatecontact($select=fullname),"
                    "crimson_clientid($select=name),"
                    "crimson_vacancyid($select=crimson_jobtitle)"),
    })


def _placements_created(uid: str, start: date, end: date) -> list:
    """Deals done in the week = placements CREATED, which is what the consultant did."""
    return odata_get_all("crimson_placements", params={
        "$select": "crimson_placementid,createdon,crimson_name",
        "$filter": (f"createdon ge {start.isoformat()}T00:00:00Z"
                    f" and createdon lt {end.isoformat()}T00:00:00Z"
                    f" and {active_or_rebated_filter()}"
                    f" and (_crimson_consultant_value eq '{odata_str(uid)}'"
                    f" or _mercury_assignmentowner_value eq '{odata_str(uid)}')"),
        "$expand": ("recruit_candidatecontact($select=fullname),"
                    "crimson_clientname($select=name)"),
    })


# ── Drill-down rows ───────────────────────────────────────────────────────────
# Every key input is clickable, so each count carries the records behind it:
# contact, client and (for meetings) the subject.

def _company_names(activities: list) -> dict:
    """
    {account_id: name} for the companies on the contacts we met or called.
    Meetings are usually "regarding" the contact, not the account, so the
    company has to come off the contact's own record (Jason, Sept 2026).
    """
    ids = {(a.get("regardingobjectid_contact") or {}).get("_parentcustomerid_value")
           for a in activities}
    ids.discard(None)
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 20):
        or_f = " or ".join(f"accountid eq '{a}'" for a in ids[i:i + 20])
        for acc in odata_get_all("accounts", params={
                "$select": "accountid,name", "$filter": f"({or_f})"}):
            out[acc["accountid"]] = acc.get("name") or ""
    return out


def _activity_row(a: dict, datefield: str, companies: dict = None) -> dict:
    contact_rec = a.get("regardingobjectid_contact") or {}
    contact = contact_rec.get("fullname") or ""
    client = ((a.get("regardingobjectid_account") or {}).get("name")
              or (companies or {}).get(contact_rec.get("_parentcustomerid_value")) or "")
    return {"contact": contact, "job_title": contact_rec.get("jobtitle") or "",
            "client": client, "subject": a.get("subject") or "",
            "when": (a.get(datefield) or "")[:10]}


def _shortlist_row(s: dict, datefield: str) -> dict:
    return {
        "contact": (s.get("recruit_candidatecontact") or {}).get("fullname") or "",
        "client":  (s.get("crimson_clientid") or {}).get("name") or "",
        "subject": (s.get("crimson_vacancyid") or {}).get("crimson_jobtitle") or "",
        "when":    (s.get(datefield) or "")[:10],
    }


def _placement_row(p: dict) -> dict:
    return {
        "contact": (p.get("recruit_candidatecontact") or {}).get("fullname") or "",
        "client":  (p.get("crimson_clientname") or {}).get("name") or "",
        "subject": p.get("crimson_name") or "",
        "when":    (p.get("createdon") or "")[:10],
    }


def _sorted(rows: list) -> list:
    return sorted(rows, key=lambda r: r.get("when") or "", reverse=True)


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
    # Newest job first (Jason, Sept 2026). The Mercury priority field is unset
    # across the board, so ordering by it would be arbitrary; it's still shown
    # on the row for the jobs where someone has set it.
    live = [v for v in rows if v.get("statuscode") not in CLOSED_VACANCY_STATUS]
    live.sort(key=lambda v: v.get("createdon") or "", reverse=True)
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


def _meeting_rows(appts, purposes, companies=None):
    """Who is being met, at which company, and what the meeting is called."""
    rows = [_activity_row(a, "scheduledstart", companies) for a in appts
            if a.get("_mercury_purpose_value") in purposes]
    return sorted(rows, key=lambda x: x["when"])


def build_one_to_one(uid: str, week: date = None) -> dict:
    """Derived half of the 1:1: key inputs, live jobs, and the meeting lists."""
    week = week_start(week or date.today())
    next_week = week + timedelta(days=7)
    last_week = week - timedelta(days=7)

    # "Month so far" is the calendar month this 1:1 sits in, to date — anchored
    # on the day the 1:1 covers (the end of the week) so a week straddling a
    # month boundary belongs to the month it mostly falls in, and NEVER spilling
    # into the next month (Jason, Sept 2026).
    anchor = min(week + timedelta(days=6), date.today())
    if anchor < week:                      # a future week — anchor on its own month
        anchor = week
    month_start = date(anchor.year, anchor.month, 1)
    month_end = date(anchor.year + (1 if anchor.month == 12 else 0),
                     1 if anchor.month == 12 else anchor.month + 1, 1)
    # ...and never past today, so "so far" doesn't claim days that haven't happened
    month_cut = min(month_end, next_week, date.today() + timedelta(days=1))
    month_cut = max(month_cut, month_start + timedelta(days=1))

    with ThreadPoolExecutor(max_workers=8) as pool:
        f = {
            "sl_last":  pool.submit(_shortlists, uid, last_week, week),
            "sl_month": pool.submit(_shortlists, uid, month_start, month_cut),
            "ca_last":  pool.submit(_activities, "phonecalls", "createdon", uid, last_week, week),
            "ca_month": pool.submit(_activities, "phonecalls", "createdon", uid, month_start, month_cut),
            "ap_last":  pool.submit(_activities, "appointments", "scheduledstart", uid, last_week, week),
            "ap_month": pool.submit(_activities, "appointments", "scheduledstart", uid, month_start, month_cut),
            "ap_this":  pool.submit(_activities, "appointments", "scheduledstart", uid, week, next_week),
            "pl_last":  pool.submit(_placements_created, uid, last_week, week),
            "pl_month": pool.submit(_placements_created, uid, month_start, month_cut),
            "em_last":  pool.submit(_emails, uid, last_week, week),
            "em_month": pool.submit(_emails, uid, month_start, month_cut),
            "jobs":     pool.submit(_live_jobs, uid),
        }
        r = {k: v.result() for k, v in f.items()}

    companies = _company_names(r["ca_month"] + r["ap_month"] + r["ap_this"] + r["em_month"])

    def detail(sl, calls, appts, pls, emails):
        """The records behind each count, so every key input drills down."""
        def acts(purposes):
            return _sorted([_activity_row(c, "createdon", companies) for c in calls
                            if c.get("_mercury_purpose_value") in purposes]
                           + [_activity_row(a, "scheduledstart", companies) for a in appts
                              if a.get("_mercury_purpose_value") in purposes])
        return {
            "cvs": _sorted([_shortlist_row(s, "new_statussubmitteddate") for s in sl
                            if s.get("new_statussubmitteddate")]),
            "interviews": _sorted([_shortlist_row(s, "mercury_firstinterviewdate") for s in sl
                                   if s.get("mercury_firstinterviewdate")]),
            "client_meetings_new":      acts(NEW_CLIENT_MEETING),
            "client_meetings_existing": acts(EXISTING_CLIENT_MEETING),
            "deals":                    _sorted([_placement_row(p) for p in pls]),
            "pitches":                  acts(PITCH),
            "bd_emails": _sorted(acts(BD_EMAIL)
                                 + [_activity_row(e, "createdon", companies) for e in emails]),
            "candidate_meets":          acts(CANDIDATE_MEETING),
            "candidate_calls":          acts(set(CANDIDATE_CALL_PURPOSES)),
            "leads":                    acts(LEADS),
        }

    def inputs(det):
        return {k: len(v) for k, v in det.items()}

    det_last  = detail(r["sl_last"],  r["ca_last"],  r["ap_last"],  r["pl_last"],  r["em_last"])
    det_month = detail(r["sl_month"], r["ca_month"], r["ap_month"], r["pl_month"], r["em_month"])

    return {
        "week_start": week.isoformat(),
        "month_label": month_start.strftime("%B"),
        "month_to": (month_cut - timedelta(days=1)).isoformat(),
        "last_week":  inputs(det_last),
        "month":      inputs(det_month),
        "detail":     {"last_week": det_last, "month": det_month},
        "live_jobs":  r["jobs"],
        "meetings_last_week": _meeting_rows(r["ap_last"], ALL_CLIENT_MEETINGS, companies),
        "meetings_this_week": _meeting_rows(r["ap_this"], ALL_CLIENT_MEETINGS, companies),
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
