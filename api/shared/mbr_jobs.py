"""
Live jobs on the MBR (Bristol, Oct 2026): the jobs a consultant brought into
the month, what's live now, and where the brought-in jobs stood on the 1st.

A job is the consultant's when they are its delivery owner, any grade — the
same jobs their 1:1 lists as live.

"Open on a day" follows the carried-in rule of the contract MBR: created
before that day and not closed by it. Only about half of closed jobs carry a
closing date (crbb7_closedon, else recruit_closeddate); without one, a job
counts as open until it was last changed.

Mercury keeps only a job's current stage, not its history, so the position on
the 1st is rebuilt from the candidates on the job: the furthest any of them
had got (CV sent, first / further / final interview, offer) before the 1st.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from shared.calc import parse_date
from shared.dataverse import odata_get_all, odata_str
from shared.oneonone import CLOSED_VACANCY_STATUS, _GRADE_BY_ID

# Mercury's vacancy stages (statuscode), as Mercury labels them
STAGE_LABEL = {
    975310000: "Pending approval", 975310001: "Client approved", 1: "Require CVs",
    143570004: "Shortlist", 143570005: "Interview", 143570008: "Interview further",
    939310001: "Interview final", 143570006: "Offer", 143570007: "Placement",
    975310002: "Rejected",
}
# What became of a job that has closed
OUTCOME_LABEL = {
    143570007: "Filled", 143570000: "Filled", 2: "Part filled",
    143570001: "Lost — competitor placed", 143570002: "Lost — filled internally",
    939310002: "Lost — project cancelled", 939310000: "Lost — other reason",
    143570003: "Cancelled",
}
# The position on the 1st, furthest first. Many jobs stay open for a year or
# more, so it's the furthest stage reached in the RECENT window before the 1st
# — an offer from last spring says nothing about where a job stands today.
RECENT_DAYS = 60
QUIET = f"Quiet — nothing in {RECENT_DAYS} days"
STAGES_ON_FIRST = ("Offer made", "Final interview", "Further interview",
                   "First interview", "CVs sent", QUIET, "No CVs yet")
_STAGE_FIELDS = (("new_statusoffermadedate", "Offer made"),
                 ("mercury_finalinterviewdate", "Final interview"),
                 ("mercury_furtherinterviewdate", "Further interview"),
                 ("mercury_firstinterviewdate", "First interview"),
                 ("new_statussubmitteddate", "CVs sent"))
_IV_FIELDS = ("mercury_firstinterviewdate", "mercury_furtherinterviewdate",
              "mercury_finalinterviewdate")


def _d(raw):
    try:
        return parse_date(raw) if raw else None
    except Exception:
        return None


def _is_live(v) -> bool:
    return v.get("statecode") == 0 and v.get("statuscode") not in CLOSED_VACANCY_STATUS


def _closed_by(v):
    """The day a job closed, or None while it's live."""
    if _is_live(v):
        return None
    return _d(v.get("crbb7_closedon")) or _d(v.get("recruit_closeddate")) or _d(v.get("modifiedon"))


def _open_on(v, day: date) -> bool:
    created = _d(v.get("createdon"))
    closed = _closed_by(v)
    return bool(created) and created < day and (closed is None or closed >= day)


def _vacancies(uid: str, since: date, until: date) -> list:
    """Jobs this person delivers that could be open at some point in [since, until)."""
    return odata_get_all("crimson_vacancies", params={
        "$select": ("crimson_vacancyid,crimson_jobtitle,crimson_name,statuscode,statecode,"
                    "_mercury_vacancytype_value,createdon,modifiedon,crbb7_closedon,"
                    "recruit_closeddate"),
        "$filter": (f"_crimson_deliveryownerid_value eq '{odata_str(uid)}'"
                    f" and createdon lt {until.isoformat()}"
                    f" and (statecode eq 0 or modifiedon ge {since.isoformat()})"),
        "$expand": "crimson_clientid($select=name)",
    })


def _shortlists(vacancy_ids: list) -> list:
    """Every candidate on these jobs, whoever put them forward."""
    def chunk(ids):
        return odata_get_all("crimson_vacancycandidates", params={
            "$select": ("_crimson_vacancyid_value,new_statussubmitteddate,"
                        "mercury_firstinterviewdate,mercury_furtherinterviewdate,"
                        "mercury_finalinterviewdate,new_statusoffermadedate"),
            "$filter": " or ".join(f"_crimson_vacancyid_value eq '{odata_str(v)}'" for v in ids),
        })
    chunks = [vacancy_ids[i:i + 15] for i in range(0, len(vacancy_ids), 15)]
    if not chunks:
        return []
    with ThreadPoolExecutor(max_workers=4) as pool:
        return [s for rows in pool.map(chunk, chunks) for s in rows]


def _by_grade(jobs) -> dict:
    out = {}
    for v in jobs:
        g = _GRADE_BY_ID.get(v.get("_mercury_vacancytype_value")) or "Ungraded"
        out[g] = out.get(g, 0) + 1
    order = ["A", "B", "C", "O", "F", "P", "S"]          # then anything else, ungraded last
    return dict(sorted(out.items(), key=lambda kv: (order.index(kv[0]) if kv[0] in order
                                                     else len(order), kv[0] == "Ungraded")))


def build(uid: str, year: int, month: int, today: date = None) -> dict:
    today = today or date.today()
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    # "Live now" while the month is being reviewed (it or the month after);
    # an older MBR shows the jobs live at its month end instead
    recent = end > today - timedelta(days=31)
    as_of = today if recent else end - timedelta(days=1)
    upto = as_of + timedelta(days=1)          # open "at the end of" as_of

    vacs = _vacancies(uid, start, upto)
    brought = [v for v in vacs if _open_on(v, start)]
    live = ([v for v in vacs if _is_live(v)] if recent
            else [v for v in vacs if _open_on(v, upto)])
    added = [v for v in vacs if start <= (_d(v.get("createdon")) or date.min) < upto]
    ids = {v["crimson_vacancyid"] for v in brought + live}
    shortlists = _shortlists(sorted(ids))

    by_job = {}
    for s in shortlists:
        by_job.setdefault(s.get("_crimson_vacancyid_value"), []).append(s)

    def count(job_id, fields, lo, hi):
        return sum(1 for s in by_job.get(job_id, []) for f in fields
                   if (d := _d(s.get(f))) and lo <= d < hi)

    window = start - timedelta(days=RECENT_DAYS)

    def stage_on_first(job_id):
        cands = by_job.get(job_id, [])
        for field, label in _STAGE_FIELDS:
            if any((d := _d(s.get(field))) and window <= d < start for s in cands):
                return label
        return QUIET if last_before(job_id) else "No CVs yet"

    def last_before(job_id):
        days = [d for s in by_job.get(job_id, []) for f, _ in _STAGE_FIELDS
                if (d := _d(s.get(f))) and d < start]
        return max(days) if days else None

    def now_of(v):
        if (_is_live(v) if recent else _open_on(v, upto)):
            return "Live — " + STAGE_LABEL.get(v.get("statuscode"), "open")
        return OUTCOME_LABEL.get(v.get("statuscode"), "Closed")

    def row(v, brought_in):
        jid = v["crimson_vacancyid"]
        created = _d(v.get("createdon"))
        return {
            "id": jid,
            "client": (v.get("crimson_clientid") or {}).get("name") or "(no client on job)",
            "job": v.get("crimson_jobtitle") or v.get("crimson_name") or "",
            "grade": _GRADE_BY_ID.get(v.get("_mercury_vacancytype_value"), ""),
            "created": created.isoformat() if created else None,
            "brought_in": brought_in,
            "days_open_on_first": (start - created).days if brought_in and created else None,
            "stage_on_first": stage_on_first(jid) if brought_in else None,
            "last_activity_before": (lambda d: d.isoformat() if d else None)(last_before(jid)),
            "cvs_before": count(jid, ("new_statussubmitteddate",), date.min, start),
            "interviews_before": count(jid, _IV_FIELDS, date.min, start),
            "cvs_in_month": count(jid, ("new_statussubmitteddate",), start, upto),
            "interviews_in_month": count(jid, _IV_FIELDS, start, upto),
            "now": now_of(v),
            "live": (_is_live(v) if recent else _open_on(v, upto)),
        }

    brought_rows = sorted((row(v, True) for v in brought),
                          key=lambda r: (STAGES_ON_FIRST.index(r["stage_on_first"]), r["client"]))
    live_rows = sorted((row(v, v["crimson_vacancyid"] in {b["crimson_vacancyid"] for b in brought})
                        for v in live), key=lambda r: r["created"] or "", reverse=True)

    stages = {s: 0 for s in STAGES_ON_FIRST}
    for r in brought_rows:
        stages[r["stage_on_first"]] += 1
    outcomes = {"Still live": 0, "Filled": 0, "Lost or cancelled": 0}
    for r in brought_rows:
        key = ("Still live" if r["live"] else "Filled" if r["now"] in ("Filled", "Part filled")
               else "Lost or cancelled")
        outcomes[key] += 1

    return {
        "start": start.isoformat(), "as_of": as_of.isoformat(), "now": recent,
        "recent_days": RECENT_DAYS,
        "brought_in": {"count": len(brought), "by_grade": _by_grade(brought)},
        "live": {"count": len(live), "by_grade": _by_grade(live)},
        "added": len(added),
        "closed": len([v for v in brought + added if not (
            _is_live(v) if recent else _open_on(v, upto))]),
        "stages_on_first": [{"stage": s, "count": n} for s, n in stages.items()],
        "outcomes": outcomes,
        "brought_jobs": brought_rows,
        "live_jobs": live_rows,
    }
