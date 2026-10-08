"""
Contract MBR: the London Contract desk, month by month (Jason, Oct 2026).

Replaces Jonny Demko's director spreadsheet and his consultants' MBR sheets.
The rules were settled with Jason measure by measure; the map is
https://claude.ai/artifact/D1DfUjhNTNEQP7BjqbPf6K and the answers are in the
module notes below. In short:

  * P1–P12 are calendar months; quarter and half-year columns are monthly
    averages ("Q1 Avg"), except money that is summed and ratios, which are
    worked from the period's totals rather than averaging monthly ratios.
  * Money is GBP weekly gross profit (WGP), credited by the weekly report's
    split rules; deal counts use placement credit (0.25 on four-way deals).
  * Runners are shown two ways: whole (every contractor the people touch) and
    by split.
  * Deals are dated by when they were made (createdon), not start date.
  * "Unique interviews" are first interviews. A JMI is a job with more than one
    interview against it in the month.
  * A new customer is one never placed with before.
  * Extension % is, of contracts finishing in the month, the share that already
    have an extension against them.
  * Job ratios all read jobs per placement; a job belongs to its delivery owner.
  * GP for the month is typed in by Jonny; budgets are imported from his sheet.

One function, `compute`, works the measures out for ANY set of people — a
consultant on their own, or the whole desk — so team figures handle shared
work properly: a deal split between two desk members counts once for the team,
and a client two consultants both placed with is one client.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta

from shared.calc import parse_date, placement_credit, split_factor
from shared.dataverse import CANCEL_CODES
from shared.mbr_registry import (BD_CALL_PURPOSES, BD_PITCH_PURPOSE, CANDIDATE_CALL_PURPOSES,
                                 CLIENT_MEETING_PURPOSES)

# ── Mercury identifiers ───────────────────────────────────────────────────────

GRADES = {
    "6973f0fc-9a50-ee11-be6f-0022481b503e": "A",
    "6b73f0fc-9a50-ee11-be6f-0022481b503e": "B",
    "6d73f0fc-9a50-ee11-be6f-0022481b503e": "C",
    "758d799d-96c6-ee11-9079-002248c7244c": "F",
    "ee8d799d-96c6-ee11-9079-002248c7244c": "P",
    "3e2642d0-9767-ee11-9ae6-002248c7244c": "S",          # Speculative
}
TERMINATED = {143570007, 143570008}   # contractor / client served notice

BD_FOLLOW_UP = "cca8257a-2895-ee11-be37-002248c7244c"
PITCH_PURPOSES = {BD_PITCH_PURPOSE, BD_FOLLOW_UP}      # Jason: follow-ups count
CONTRACTOR_LEAD = "d59958b7-98c6-ee11-9079-002248c7244c"   # Lead Gained from Candidate
MANAGER_REFERRAL = "b6e30f54-40cb-ee11-9079-6045bd0c1c1b"
REFERENCE_GAINED = "d29dda22-3ed2-ee11-9079-6045bdf139f0"  # Contractor Reference Gained
CANDIDATE_MEETINGS = {"46e272c6-a769-ee11-94f7-000d3ad6abf9",   # Candidate Meeting
                      "403d3f07-29ab-ee11-be37-002248c7244c"}   # Candidate Flip Meeting

ROLE_FIELDS = ("_mercury_assignmentowner_value", "_crimson_consultant_value",
               "_mercury_clientrelationshipowner_value",
               "_mercury_contractorrelationship_userid_value")

# ── Measures ──────────────────────────────────────────────────────────────────
# (key, label, section, level, unit, period rule)
#   level: "both" | "team" | "consultant"
#   unit:  count | money | pct | ratio | weeks
#   rule:  "avg" (monthly average), "sum", or ("ratio", numerator, denominator)

MEASURES = [
    # Targets: Jonny's top block, each actual beside its budget
    ("gp_month", "GP (month)", "Targets", "team", "money", "sum"),
    ("gp_budget", "GP budget", "Targets", "team", "money", "sum"),
    ("gp_achievement", "% achievement", "Targets", "team", "pct", ("ratio", "gp_month", "gp_budget")),
    ("runners_split", "Runners out (by split)", "Targets", "both", "count", "avg"),
    ("runners_budget", "Runners out budget", "Targets", "team", "count", "avg"),
    ("gp_per_head", "GP per fee earner", "Targets", "team", "money", ("ratio", "gp_month", "headcount")),
    ("gp_per_head_budget", "GP per fee earner budget", "Targets", "team", "money", "avg"),
    # Book
    ("headcount", "Headcount", "Book", "team", "count", "avg"),
    ("runners", "Runners (whole)", "Book", "both", "count", "avg"),
    ("wgp_running", "Running WGP at month end", "Book", "both", "money", "avg"),
    ("wgp_per_head", "Running WGP per head", "Book", "team", "money", ("ratio", "wgp_running", "headcount")),
    ("wgp_avg_runner", "Average WGP of runner book", "Book", "both", "money",
     ("ratio", "wgp_running", "runners_split")),
    ("extension_pct", "Extension % in month", "Book", "team", "pct", ("ratio", "_due_extended", "_due")),
    ("terminations", "Terminations", "Book", "team", "count", "avg"),
    ("terminations_wgp", "Value of terminations", "Book", "team", "money", "avg"),
    # Prediction
    ("wgp_predicted", "Predicted running WGP", "WGP prediction", "both", "money", "avg"),
    ("starters_next", "Starters next month", "WGP prediction", "both", "count", "avg"),
    ("starters_next_wgp", "Starters' WGP", "WGP prediction", "both", "money", "avg"),
    ("finishers_next", "Finishers next month", "WGP prediction", "team", "count", "avg"),
    ("finishers_next_wgp", "Finishers' WGP", "WGP prediction", "team", "money", "avg"),
    ("expected_finishers_wgp", "Expected finishers' WGP", "WGP prediction", "both", "money", "avg"),
    ("finishers", "Actual finishers in month", "WGP prediction", "team", "count", "avg"),
    ("finishers_wgp", "Actual finishers' WGP", "WGP prediction", "team", "money", "avg"),
    ("extension_pct_next", "Extension % in coming month", "WGP prediction", "team", "pct",
     ("ratio", "_next_extended", "finishers_next")),
    ("finisher_pct", "Finisher %", "WGP prediction", "team", "pct", ("ratio", "finishers_wgp", "wgp_running")),
    # Deals
    ("deals", "Deals", "Deals", "both", "count", "avg"),
    ("deals_wgp", "New deal WGP", "Deals", "both", "money", "avg"),
    ("deals_avg_wgp", "Average WGP of new deals", "Deals", "both", "money", ("ratio", "deals_wgp", "deals")),
    ("deals_per_head", "Deals per head", "Deals", "team", "ratio", ("ratio", "deals", "headcount")),
    ("deals_wgp_per_head", "New deal WGP per head", "Deals", "team", "money", ("ratio", "deals_wgp", "headcount")),
    ("deals_avg_margin", "Average margin of new deals", "Deals", "team", "pct",
     ("ratio", "_margin_sum", "_priced_n")),
    ("deals_avg_weeks", "Average contract length (weeks)", "Deals", "both", "weeks",
     ("ratio", "_weeks_sum", "_deal_n")),
    ("clients_placed", "Clients placed with", "Deals", "both", "count", "avg"),
    # Interviews
    ("interviews", "Interviews", "Interviews", "both", "count", "avg"),
    ("interviews_first", "First interviews", "Interviews", "both", "count", "avg"),
    ("jmis", "JMIs (jobs with more than one interview)", "Interviews", "both", "count", "avg"),
    ("iv_per_placement", "Interviews per placement", "Interviews", "both", "ratio", ("ratio", "interviews", "deals")),
    ("first_iv_per_placement", "First interviews per placement", "Interviews", "both", "ratio",
     ("ratio", "interviews_first", "deals")),
    ("cvs_per_interview", "CVs per first interview", "Interviews", "team", "ratio",
     ("ratio", "cvs", "interviews_first")),
    ("jobs_with_iv", "Jobs with interviews", "Interviews", "both", "count", "avg"),
    ("clients_with_iv", "Clients with interviews", "Interviews", "both", "count", "avg"),
    ("cvs", "CV submissions", "Interviews", "both", "count", "avg"),
    # Jobs
    ("jobs_a", "A jobs added", "Jobs", "both", "count", "avg"),
    ("jobs_b", "B jobs added", "Jobs", "both", "count", "avg"),
    ("jobs_c", "C jobs added", "Jobs", "both", "count", "avg"),
    ("jobs_added", "Jobs added (A–C)", "Jobs", "both", "count", "avg"),
    ("clients_with_jobs", "Clients with jobs", "Jobs", "team", "count", "avg"),
    ("ab_share", "A + B share of jobs", "Jobs", "both", "pct", ("ratio", "_ab", "jobs_added")),
    ("jobs_per_head", "Jobs per head", "Jobs", "team", "ratio", ("ratio", "jobs_added", "headcount")),
    ("jobs_per_placement", "Jobs per placement", "Jobs", "both", "ratio", ("ratio", "jobs_added", "deals")),
    ("a_jobs_per_placement", "A jobs per A placement", "Jobs", "both", "ratio", ("ratio", "jobs_a", "filled_a")),
    ("b_jobs_per_placement", "B jobs per B placement", "Jobs", "both", "ratio", ("ratio", "jobs_b", "filled_b")),
    ("c_jobs_per_placement", "C jobs per C placement", "Jobs", "consultant", "ratio", ("ratio", "jobs_c", "filled_c")),
    ("jobs_f", "F jobs added", "Jobs", "both", "count", "avg"),
    ("jobs_p", "P jobs added", "Jobs", "both", "count", "avg"),
    ("jobs_pipelined", "Total pipelined (F + P)", "Jobs", "both", "count", "avg"),
    ("jobs_spec", "Speculative jobs added", "Jobs", "consultant", "count", "avg"),
    ("jobs_spec_covered", "Speculative jobs covered", "Jobs", "consultant", "count", "avg"),
    ("jobs_spec_pct", "% speculative covered", "Jobs", "consultant", "pct",
     ("ratio", "jobs_spec_covered", "jobs_spec")),
    ("filled_a", "A jobs filled", "Jobs", "both", "count", "avg"),
    ("filled_b", "B jobs filled", "Jobs", "both", "count", "avg"),
    ("filled_c", "C jobs filled", "Jobs", "consultant", "count", "avg"),
    ("filled_a_share", "A jobs % of placements", "Jobs", "both", "pct", ("ratio", "filled_a", "deals")),
    ("filled_b_share", "B jobs % of placements", "Jobs", "both", "pct", ("ratio", "filled_b", "deals")),
    ("filled_c_share", "C jobs % of placements", "Jobs", "consultant", "pct", ("ratio", "filled_c", "deals")),
    ("carried_a", "A jobs carried into month", "Jobs", "both", "count", "avg"),
    ("carried_b", "B jobs carried into month", "Jobs", "both", "count", "avg"),
    ("carried_c", "C jobs carried into month", "Jobs", "consultant", "count", "avg"),
    ("carried_total", "Jobs carried into month", "Jobs", "both", "count", "avg"),
    # Meetings
    ("client_meetings", "Client meetings", "Meetings", "both", "count", "avg"),
    ("client_meetings_per_head", "Client meetings per head", "Meetings", "team", "ratio",
     ("ratio", "client_meetings", "headcount")),
    ("client_meetings_own", "Client meetings, Jonny's own", "Meetings", "team", "count", "avg"),
    ("candidate_meetings", "Candidate meetings", "Meetings", "consultant", "count", "avg"),
    # Activity
    ("candidate_calls", "Candidate calls", "Activity", "both", "count", "avg"),
    ("contractor_leads", "Contractor leads", "Activity", "both", "count", "avg"),
    ("manager_referrals", "Manager referrals", "Activity", "both", "count", "avg"),
    ("intel_pct", "Intel gained %", "Activity", "both", "pct", ("ratio", "_intel", "candidate_calls")),
    ("bd_calls", "BD calls", "Activity", "both", "count", "avg"),
    ("pitches", "Pitches delivered", "Activity", "both", "count", "avg"),
    ("pitch_pct", "BD calls that became pitches", "Activity", "team", "pct", ("ratio", "pitches", "bd_calls")),
    ("bd_emails", "BD emails", "Activity", "both", "count", "avg"),
    ("reference_calls", "Reference calls", "Activity", "consultant", "count", "avg"),
    # Customers — summed over a period: each is a separate new customer
    ("new_customers_placed", "New customers placed with", "Customers", "both", "count", "sum"),
    ("new_customers_jobs", "New customers with jobs added", "Customers", "both", "count", "sum"),
    ("new_customers_meetings", "New customers with meetings", "Customers", "both", "count", "sum"),
]
MEASURE = {m[0]: m for m in MEASURES}
TYPED = ("gp_month",)                                       # Jonny types these
IMPORTED = ("gp_budget", "runners_budget", "gp_per_head_budget")   # from his sheet
# Typed for the desk in every column, months and periods alike (Jason: "if in
# any row there's a typed metric they should all be typed"). Jobs carried in
# joins them: Mercury can't rebuild it reliably, so Jonny's own figures stand
# and he keeps them up; Mercury's estimate shows greyed in an empty box.
DESK_INPUTS = TYPED + IMPORTED + ("carried_a", "carried_b")
# How each row is coloured, after Jonny's sheet: actuals blue, targets gold
TONE = {"gp_month": "actual", "runners_split": "actual", "gp_per_head": "actual",
        "gp_budget": "budget", "gp_achievement": "budget", "runners_budget": "budget",
        "gp_per_head_budget": "budget"}

# ── Small helpers ─────────────────────────────────────────────────────────────


def _d(raw):
    try:
        return parse_date(raw) if raw else None
    except Exception:
        return None


def month_range(year: int, month: int) -> tuple:
    start = date(year, month, 1)
    return start, date(year + (month == 12), month % 12 + 1, 1)


def _end(p) -> date | None:
    """Effective end: the actual end if recorded, else the contract end."""
    return _d(p.get("crimson_actualenddate")) or _d(p.get("crimson_enddate"))


def contractor_key(p) -> str:
    """A contract and its extensions share the first part of the placement
    code (004749/00/06, 004749/01/00); the parent link is never filled in."""
    code = (p.get("crimson_placementidcode") or "").split("/")[0].strip()
    return code or p["crimson_placementid"]


def _is_extension(p) -> bool:
    parts = (p.get("crimson_placementidcode") or "").split("/")
    return bool(p.get("crimson_extension")) or (len(parts) >= 2 and parts[1] != "00")


def _wgp(p, fx) -> float:
    ccy = (p.get("recruit_trueweeklygrossprofitcurrency") or {}).get("isocurrencycode")
    return (p.get("recruit_trueweeklygrossprofit") or 0.0) * fx.get(ccy, 1.0)


def _share(p, people) -> float:
    return sum(split_factor(p, u) for u in people)


def _credit(p, people) -> float:
    return sum(placement_credit(p, u) for u in people)


def _touches(p, people) -> bool:
    return any(p.get(f) in people for f in ROLE_FIELDS)


# ── The calculation ───────────────────────────────────────────────────────────


def compute(people: set, year: int, month: int, data: dict, fx: dict,
            director: str | None = None, book: set | None = None) -> dict:
    """
    Every Mercury-derived measure for `people` (one consultant, or the desk)
    in one month. `data` holds the desk's year, fetched once:
      placements, shortlists, vacancies, calls, appointments, emails,
      first_placed {client_id: date}, presence {uid: [(from, to)]}
    Typed and imported values are added by the caller.

    `book` is whose contracts make up the book, deals and jobs filled. For a
    consultant it is just them; for the desk it also takes in the house account
    and the director, as Jonny's sheet does (his team book only reconciles with
    them in). Activity, headcount and per-head figures use `people`.
    """
    book = book or people
    m_start, m_end = month_range(year, month)
    n_start, n_end = month_range(m_end.year, m_end.month)
    last_day = m_end - timedelta(days=1)

    contracts = [p for p in data["placements"]
                 if p.get("statuscode") not in CANCEL_CODES and _touches(p, book)]
    # A contractor counts as extended if any later record shares its code
    latest = {}
    for p in data["placements"]:
        if p.get("statuscode") in CANCEL_CODES:
            continue
        s = _d(p.get("crimson_startdate"))
        if s:
            k = contractor_key(p)
            latest[k] = max(latest.get(k, s), s)

    def extended(p):
        s = _d(p.get("crimson_startdate"))
        return bool(p.get("_mercury_extendedplacementid_value")) or (
            s is not None and latest.get(contractor_key(p), s) > s)

    def live_on(p, day):
        s, e = _d(p.get("crimson_startdate")), _end(p)
        return s is not None and e is not None and s <= day <= e

    out = {}

    # Book, at the last day of the month
    live = [p for p in contracts if live_on(p, last_day)]
    out["runners"] = len({contractor_key(p) for p in live})
    # Runners count by placement credit (0.5 each to Consultant and AO, a
    # quarter each when there's a CONRO), so a split runner is a half or a
    # quarter, never a third: money splits in thirds, runners don't (Jason, Oct 2026)
    out["runners_split"] = round(sum(_credit(p, book) for p in live), 2)
    out["wgp_running"] = round(sum(_wgp(p, fx) * _share(p, book) for p in live), 2)

    due = [p for p in contracts if (e := _end(p)) and m_start <= e < m_end]
    out["_due"] = len(due)
    out["_due_extended"] = sum(1 for p in due if extended(p))
    term = [p for p in due if p.get("statuscode") in TERMINATED]
    out["terminations"] = len(term)
    out["terminations_wgp"] = round(sum(_wgp(p, fx) * _share(p, book) for p in term), 2)

    finished = [p for p in due if not extended(p)]
    out["finishers"] = len(finished)
    out["finishers_wgp"] = round(sum(_wgp(p, fx) * _share(p, book) for p in finished), 2)

    # Next month
    starters = [p for p in contracts if not _is_extension(p)
                and (s := _d(p.get("crimson_startdate"))) and n_start <= s < n_end]
    out["starters_next"] = len(starters)
    out["starters_next_wgp"] = round(sum(_wgp(p, fx) * _share(p, book) for p in starters), 2)
    due_next = [p for p in contracts if (e := _end(p)) and n_start <= e < n_end]
    out["finishers_next"] = len(due_next)
    out["finishers_next_wgp"] = round(sum(_wgp(p, fx) * _share(p, book) for p in due_next), 2)
    out["_next_extended"] = sum(1 for p in due_next if extended(p))
    out["expected_finishers_wgp"] = round(sum(_wgp(p, fx) * _share(p, book)
                                              for p in due_next if not extended(p)), 2)
    out["wgp_predicted"] = round(out["wgp_running"] + out["starters_next_wgp"]
                                 - out["expected_finishers_wgp"], 2)

    # Deals: new contracts made in the month
    deals = [p for p in contracts if not _is_extension(p)
             and (c := _d(p.get("createdon"))) and m_start <= c < m_end]
    out["deals"] = round(sum(_credit(p, book) for p in deals), 2)
    out["deals_wgp"] = round(sum(_wgp(p, fx) * _share(p, book) for p in deals), 2)
    out["_deal_n"] = len(deals)
    # A margin-only deal reads as 100% margin and would swamp the average
    priced = [p for p in deals if not p.get("mercury_ismarginonly")
              and (p.get("mercury_marginpercent") or 0) < 100]
    out["_priced_n"] = len(priced)
    out["_margin_sum"] = round(sum((p.get("mercury_marginpercent") or 0) / 100 for p in priced), 4)
    # Length as agreed: the contract end, not an early actual end
    out["_weeks_sum"] = round(sum(((_d(p.get("crimson_enddate")) or _d(p.get("crimson_startdate")))
                                   - _d(p.get("crimson_startdate"))).days / 7
                                  for p in deals if _d(p.get("crimson_startdate"))), 2)
    placed_clients = {p.get("_crimson_clientname_value") for p in deals} - {None}
    out["clients_placed"] = len(placed_clients)

    # Jobs filled, by grade of the job the deal came from
    vac_grade = {v["crimson_vacancyid"]: GRADES.get(v.get("_mercury_vacancytype_value"))
                 for v in data["vacancies"]}
    for g in "abc":
        out[f"filled_{g}"] = round(sum(_credit(p, book) for p in deals
                                       if vac_grade.get(p.get("_crimson_vacancy_value")) == g.upper()), 2)

    # Interviews and CVs, on shortlists the people own
    sl = [s for s in data["shortlists"] if s.get("_owninguser_value") in people]

    def in_month(raw):
        d = _d(raw)
        return d is not None and m_start <= d < m_end

    iv_by_job = defaultdict(int)
    iv_clients, firsts, interviews = set(), 0, 0
    for s in sl:
        n = sum(1 for f in ("mercury_firstinterviewdate", "mercury_furtherinterviewdate",
                            "mercury_finalinterviewdate") if in_month(s.get(f)))
        if n:
            interviews += n
            iv_by_job[s.get("_crimson_vacancyid_value")] += n
            if s.get("_crimson_clientid_value"):
                iv_clients.add(s["_crimson_clientid_value"])
        if in_month(s.get("mercury_firstinterviewdate")):
            firsts += 1
    out["interviews"] = interviews
    out["interviews_first"] = firsts
    out["jmis"] = sum(1 for j, n in iv_by_job.items() if j and n > 1)
    out["jobs_with_iv"] = len([j for j in iv_by_job if j])
    out["clients_with_iv"] = len(iv_clients)
    out["cvs"] = sum(1 for s in sl if in_month(s.get("new_statussubmitteddate")))

    # Jobs added, by grade, on jobs the people deliver
    mine = [v for v in data["vacancies"] if v.get("_crimson_deliveryownerid_value") in people]
    added = [v for v in mine if in_month(v.get("createdon"))]
    by = defaultdict(int)
    for v in added:
        by[GRADES.get(v.get("_mercury_vacancytype_value"))] += 1
    for g in "abcfp":
        out[f"jobs_{g}"] = by[g.upper()]
    out["jobs_added"] = by["A"] + by["B"] + by["C"]
    out["_ab"] = by["A"] + by["B"]
    out["jobs_pipelined"] = by["F"] + by["P"]
    out["jobs_spec"] = by["S"]
    spec = [v for v in added if GRADES.get(v.get("_mercury_vacancytype_value")) == "S"]
    cv_jobs = {s.get("_crimson_vacancyid_value") for s in data["shortlists"]
               if s.get("new_statussubmitteddate")}
    out["jobs_spec_covered"] = sum(1 for v in spec if v["crimson_vacancyid"] in cv_jobs)
    out["clients_with_jobs"] = len({v.get("_crimson_clientid_value") for v in added} - {None})

    # Carried in: graded jobs open on the 1st. A closing date is stamped on
    # only about half of closed jobs (crbb7_closedon, else recruit_closeddate);
    # without one, a job counts as open until it was last changed. Marked as
    # an estimate on the page.
    for g in "abc":
        out[f"carried_{g}"] = 0
    for v in mine:
        g = GRADES.get(v.get("_mercury_vacancytype_value"))
        created = _d(v.get("createdon"))
        if g not in ("A", "B", "C") or not created or created >= m_start:
            continue
        closed_by = None if v.get("statecode") == 0 else (
            _d(v.get("crbb7_closedon")) or _d(v.get("recruit_closeddate")) or _d(v.get("modifiedon")))
        if closed_by is None or closed_by >= m_start:
            out[f"carried_{g.lower()}"] += 1
    out["carried_total"] = out["carried_a"] + out["carried_b"] + out["carried_c"]

    # Activity, owned by the people
    calls = [c for c in data["calls"] if c.get("_ownerid_value") in people
             and in_month(c.get("createdon"))]
    appts = [a for a in data["appointments"] if a.get("_ownerid_value") in people
             and in_month(a.get("scheduledstart"))]

    def count(rows, purposes):
        return sum(1 for r in rows if r.get("_mercury_purpose_value") in purposes)

    meetings = [a for a in appts + calls if a.get("_mercury_purpose_value") in CLIENT_MEETING_PURPOSES]
    out["client_meetings"] = len(meetings)
    out["candidate_meetings"] = count(appts, CANDIDATE_MEETINGS)
    out["candidate_calls"] = count(calls, CANDIDATE_CALL_PURPOSES)
    out["contractor_leads"] = count(calls, {CONTRACTOR_LEAD})
    out["manager_referrals"] = count(calls, {MANAGER_REFERRAL})
    out["_intel"] = out["contractor_leads"] + out["manager_referrals"]
    out["bd_calls"] = count(calls, BD_CALL_PURPOSES)
    out["pitches"] = count(calls, PITCH_PURPOSES)
    out["reference_calls"] = count(calls, {REFERENCE_GAINED})
    out["bd_emails"] = sum(1 for e in data["emails"] if e.get("owner") in people
                           and in_month(e.get("createdon")))
    if director:
        own = [a for a in data["appointments"] + data["calls"]
               if a.get("_ownerid_value") == director
               and in_month(a.get("scheduledstart") or a.get("createdon"))
               and a.get("_mercury_purpose_value") in CLIENT_MEETING_PURPOSES]
        out["client_meetings_own"] = len(own)

    # New customers: never placed with before this month
    first = data["first_placed"]

    def never_before(cid):
        f = first.get(cid)
        return cid is not None and (f is None or f >= m_start)

    out["new_customers_placed"] = sum(1 for c in placed_clients
                                      if first.get(c) and m_start <= first[c] < m_end)
    out["new_customers_jobs"] = len({v.get("_crimson_clientid_value") for v in added
                                     if never_before(v.get("_crimson_clientid_value"))})
    out["new_customers_meetings"] = len({m.get("client") for m in meetings
                                         if never_before(m.get("client"))})

    # Headcount: share of the month each person was on the desk
    days = (m_end - m_start).days
    hc = 0.0
    for u in people:
        for since, until in data["presence"].get(u, []):
            lo, hi = max(since, m_start), min(until, last_day)
            if hi >= lo:
                hc += ((hi - lo).days + 1) / days
    out["headcount"] = round(hc, 2)
    return out


# ── Ratios and period columns ─────────────────────────────────────────────────


def _ratio(n, d):
    return None if n is None or not d else n / d


def finish(raw: dict) -> dict:
    """Fill in ratio measures from a month's (or a period's) raw totals."""
    out = dict(raw)
    for key, _l, _s, _lv, _u, rule in MEASURES:
        if isinstance(rule, tuple):
            out[key] = _ratio(raw.get(rule[1]), raw.get(rule[2]))
    return out


def period(months: list) -> dict:
    """
    A quarter or half-year column from its months (only those that have
    happened). Monthly average for most measures, as the sheets' "Q1 Avg";
    summed where the rule says so; ratios worked from the totals.
    """
    months = [m for m in months if m]
    if not months:
        return {}
    keys = set().union(*months)
    totals = {k: sum((m.get(k) or 0) for m in months) for k in keys}
    out = {}
    for key, _l, _s, _lv, _u, rule in MEASURES:
        if rule == "sum":
            # A period where nothing was recorded is blank, not zero
            has = any(m.get(key) is not None for m in months)
            out[key] = totals.get(key) if has else None
        elif rule == "avg":
            vals = [m[key] for m in months if m.get(key) is not None]
            out[key] = sum(vals) / len(vals) if vals else None
    for k in keys:                                  # raw parts, for the ratios
        if k.startswith("_"):
            out[k] = totals[k]
    # Ratios use the period's totals, not an average of the monthly ratios
    for key, _l, _s, _lv, _u, rule in MEASURES:
        if isinstance(rule, tuple):
            out[key] = _ratio(totals.get(rule[1]), totals.get(rule[2]))
    return out


PERIODS = [("Q1", (1, 2, 3)), ("Q2", (4, 5, 6)), ("H1", (1, 2, 3, 4, 5, 6)),
           ("Q3", (7, 8, 9)), ("Q4", (10, 11, 12)), ("H2", (7, 8, 9, 10, 11, 12))]


# ── Fetching a desk's year ────────────────────────────────────────────────────
# Everything for the desk comes back in a handful of bulk queries, then every
# month and person is worked out in memory — fast, and well inside Azure's
# 45-second limit for a request.

DESKS = {
    # desk -> (territory, director's email)
    "London Contract": ("London Contract", "jonny@saragossa.io"),
}
DESK_KEY = "desk:{desk}"           # crbb7_mbrtarget user id for desk-level inputs


def _or(field, values):
    from shared.dataverse import odata_str
    return "(" + " or ".join(f"{field} eq '{odata_str(v)}'" for v in values) + ")"


def fetch_year(desk: str, year: int, today: date | None = None) -> dict:
    from concurrent.futures import ThreadPoolExecutor
    from shared.calc import TO_GBP, _build_fx_tables
    from shared.dataverse import (TERRITORY_IDS, get_all_territory_consultants, get_fx_rates,
                                  get_first_placement_dates, get_overrides, odata_get_all,
                                  odata_str)
    from shared.mbr_registry import BD_EMAIL_PURPOSES

    today = today or date.today()
    territory, director_email = DESKS[desk]
    tid = TERRITORY_IDS[territory]
    # The generic house account owns work but isn't a person on the desk;
    # its contracts still belong to the desk's book.
    on_desk = odata_get_all("systemusers", params={
        "$select": "systemuserid,fullname", "$filter": f"_territoryid_value eq '{tid}'"})
    house = [u["systemuserid"] for u in on_desk
             if (u.get("fullname") or "").lower().startswith("saragossa house")]
    members = [c for c in get_all_territory_consultants() if c.get("_territoryid_value") == tid
               and c["systemuserid"] not in house]
    people = [c["systemuserid"] for c in members]
    director = next((u["systemuserid"] for u in odata_get_all("systemusers", params={
        "$select": "systemuserid",
        "$filter": f"internalemailaddress eq '{odata_str(director_email)}'"})), None)
    owners = people + ([director] if director else [])
    book_owners = owners + house
    y0, y1, y2 = f"{year}-01-01", f"{year + 1}-01-01", f"{year + 1}-02-01"

    roles = " or ".join(_or(f, book_owners) for f in ROLE_FIELDS)
    q = {
        "placements": ("crimson_placements", {
            "$select": ("crimson_placementid,crimson_name,crimson_placementidcode,crimson_extension,"
                        "crimson_startdate,crimson_enddate,crimson_actualenddate,createdon,statuscode,"
                        "recruit_trueweeklygrossprofit,mercury_marginpercent,mercury_ismarginonly,"
                        "_crimson_clientname_value,"
                        "_crimson_vacancy_value,_mercury_extendedplacementid_value," + ",".join(ROLE_FIELDS)),
            "$filter": (f"(crimson_type eq 143570001 or crimson_type eq 143570002) and ({roles})"
                        f" and (crimson_enddate ge {y0} or createdon ge {y0})"
                        f" and crimson_startdate lt {y2}"),
            "$expand": "recruit_trueweeklygrossprofitcurrency($select=isocurrencycode)"}),
        "shortlists": ("crimson_vacancycandidates", {
            "$select": ("crimson_vacancycandidateid,_owninguser_value,_crimson_vacancyid_value,"
                        "_crimson_clientid_value,new_statussubmitteddate,mercury_firstinterviewdate,"
                        "mercury_furtherinterviewdate,mercury_finalinterviewdate"),
            "$filter": (f"{_or('_owninguser_value', people)} and ("
                        f"(new_statussubmitteddate ge {y0} and new_statussubmitteddate lt {y1}) or "
                        f"(mercury_firstinterviewdate ge {y0} and mercury_firstinterviewdate lt {y1}) or "
                        f"(mercury_furtherinterviewdate ge {y0} and mercury_furtherinterviewdate lt {y1}) or "
                        f"(mercury_finalinterviewdate ge {y0} and mercury_finalinterviewdate lt {y1}))")}),
        "vacancies": ("crimson_vacancies", {
            "$select": ("crimson_vacancyid,_mercury_vacancytype_value,_crimson_clientid_value,"
                        "_crimson_deliveryownerid_value,createdon,modifiedon,statecode,"
                        "crbb7_closedon,recruit_closeddate"),
            "$filter": (f"{_or('_crimson_deliveryownerid_value', people)}"
                        f" and createdon lt {y1} and (statecode eq 0 or modifiedon ge {y0})")}),
        # 5,000+ calls a year: fetched lean (no "who with"), a quarter at a
        # time in parallel. Only client-meeting calls need the client, and
        # those come separately below.
        "calls": ("phonecalls", {
            "$select": "activityid,_ownerid_value,_mercury_purpose_value,createdon",
            "$filter": f"{_or('_ownerid_value', owners)} and createdon ge {{lo}} and createdon lt {{hi}}"}),
        "meeting_calls": ("phonecalls", {
            "$select": "activityid,_ownerid_value,_mercury_purpose_value,createdon",
            "$filter": (f"{_or('_ownerid_value', owners)} and {_or('_mercury_purpose_value', CLIENT_MEETING_PURPOSES)}"
                        f" and createdon ge {y0} and createdon lt {y1}"),
            "$expand": ("regardingobjectid_account($select=accountid),"
                        "regardingobjectid_contact($select=_parentcustomerid_value)")}),
        "appointments": ("appointments", {
            "$select": "activityid,_ownerid_value,_mercury_purpose_value,scheduledstart",
            "$filter": (f"{_or('_ownerid_value', owners)}"
                        f" and scheduledstart ge {y0} and scheduledstart lt {y1}"),
            "$expand": ("regardingobjectid_account($select=accountid),"
                        "regardingobjectid_contact($select=_parentcustomerid_value)")}),
        "emails": ("emails", {
            "$select": "activityid,_ownerid_value,createdon",
            "$filter": (f"{_or('_recruit_purpose_value', BD_EMAIL_PURPOSES)}"
                        f" and {_or('_ownerid_value', people)}"
                        f" and createdon ge {{lo}} and createdon lt {{hi}}")}),
    }
    # The two big ones are split into quarters and fetched side by side
    quarters = [(f"{year}-{a:02d}-01", f"{year}-{b:02d}-01" if b <= 12 else y1)
                for a, b in ((1, 4), (4, 7), (7, 10), (10, 13))]
    SPLIT = {"calls", "emails"}
    with ThreadPoolExecutor(max_workers=14) as pool:
        futs = {}
        for k, (ent, params) in q.items():
            if k in SPLIT:
                futs[k] = [pool.submit(odata_get_all, ent, {
                    **params, "$filter": params["$filter"].replace("{lo}", lo).replace("{hi}", hi)})
                    for lo, hi in quarters]
            else:
                futs[k] = [pool.submit(odata_get_all, ent, params)]
        f_fx = pool.submit(get_fx_rates)
        f_ov = pool.submit(get_overrides)
        data = {k: [row for f in fs for row in f.result()] for k, fs in futs.items()}
        try:
            fx = _build_fx_tables(f_fx.result())[0]
        except Exception:
            fx = TO_GBP
        overrides = {o["crbb7_userid"]: o for o in f_ov.result()}

    # Meeting calls carry the client; fold them back over their lean copies
    by_id = {c["activityid"]: c for c in data.pop("meeting_calls")}
    data["calls"] = [by_id.get(c["activityid"], c) for c in data["calls"]]

    # The client a meeting was about: the account, or the contact's company
    for a in data["calls"] + data["appointments"]:
        acc = (a.get("regardingobjectid_account") or {}).get("accountid")
        con = (a.get("regardingobjectid_contact") or {}).get("_parentcustomerid_value")
        a["client"] = acc or con
    data["emails"] = [{"owner": e.get("_ownerid_value"), "createdon": e.get("createdon")}
                      for e in data["emails"]]

    clients = ({p.get("_crimson_clientname_value") for p in data["placements"]}
               | {v.get("_crimson_clientid_value") for v in data["vacancies"]}
               | {a["client"] for a in data["calls"] + data["appointments"]
                  if a.get("_mercury_purpose_value") in CLIENT_MEETING_PURPOSES}) - {None}
    data["first_placed"] = {c: _d(v) for c, v in get_first_placement_dates(list(clients)).items()}

    # When each person was on the desk. Joining: the team-move date if they
    # moved here, else when their Mercury account was made. Leaving: Mercury
    # records no leaving date, so a disabled account counts until the last
    # activity it owns: an estimate, flagged on the page.
    last_seen = {}
    for rows, f in ((data["calls"], "createdon"), (data["appointments"], "scheduledstart")):
        for r in rows:
            d, u = _d(r.get(f)), r.get("_ownerid_value")
            if d and (u not in last_seen or d > last_seen[u]):
                last_seen[u] = d
    presence = {}
    for c in members:
        uid = c["systemuserid"]
        ov = overrides.get(uid, {})
        moved = _d(ov.get("crbb7_datejoinedteam")) if ov.get("crbb7_previousterritory") else None
        since = moved or _d(c.get("createdon")) or date(year, 1, 1)
        until = today if not c.get("isdisabled") else (last_seen.get(uid) or since)
        presence[uid] = [(since, until)]
    data["presence"] = presence

    data["people"] = [{"uid": c["systemuserid"], "name": c.get("fullname", ""),
                       "active": not c.get("isdisabled")} for c in members]
    data["director"] = director
    data["book"] = set(book_owners)
    data["fx"] = fx
    return data


def build_year(desk: str, year: int, today: date | None = None, data: dict | None = None,
               inputs: dict | None = None) -> dict:
    """
    The whole year for a desk: the team and every consultant, P1 to the
    current month, with quarter and half-year columns. `inputs` holds the
    desk-level typed and imported values, keyed "gp_month:2026-01" and so on.
    """
    today = today or date.today()
    data = data or fetch_year(desk, year, today)
    inputs = inputs or {}
    through = 12 if year < today.year else today.month
    team_ids = {p["uid"] for p in data["people"]}

    def one(people, director=None, desk_inputs=False, book=None):
        months = {}
        for m in range(1, through + 1):
            raw = compute(people, year, m, data, data["fx"], director, book)
            if desk_inputs:
                for k in TYPED + IMPORTED:
                    raw[k] = inputs.get(f"{k}:{year}-{m:02d}")
            months[m] = finish(raw)
        cols = {f"P{m}": months[m] for m in months}
        for name, ms in PERIODS:
            got = [months[m] for m in ms if m in months]
            if got:
                cols[name] = period(got)
        return cols

    team = one(team_ids, data["director"], desk_inputs=True, book=data.get("book"))
    consultants = [{"uid": p["uid"], "name": p["name"], "active": p["active"],
                    "columns": one({p["uid"]})} for p in data["people"]]
    return {"desk": desk, "year": year, "through": through, "team": team,
            "consultants": sorted(consultants, key=lambda c: (not c["active"], c["name"])),
            "measures": [{"key": k, "label": lb, "section": s, "level": lv, "unit": u}
                         for k, lb, s, lv, u, _r in MEASURES]}


# ── One view at a time, for the page ──────────────────────────────────────────

def _fetch_cached(desk: str, year: int, today: date) -> dict:
    """The desk's year, kept ten minutes so moving between people and back is
    quick. The engine never changes the data it's given, so no copy is made."""
    from shared.dataverse import ttl_cached
    global _CACHED_FETCH
    if _CACHED_FETCH is None:
        _CACHED_FETCH = ttl_cached(600, copy=False)(fetch_year)
    return _CACHED_FETCH(desk, year, today)


_CACHED_FETCH = None

COLUMN_ORDER = ["P1", "P2", "P3", "Q1", "P4", "P5", "P6", "Q2", "H1",
                "P7", "P8", "P9", "Q3", "P10", "P11", "P12", "Q4", "H2", "YTD"]


def build_view(desk: str, year: int, view: str, inputs: dict, today: date | None = None,
               data: dict | None = None, snapshots: dict | None = None) -> dict:
    """
    One view of a desk's year: "team", or a consultant's systemuserid.
    Only that view is worked out, so a page load costs a fraction of the year.

    `snapshots` is {month: {"raw", "taken_at", "late"}} from shared.mbr_snapshot:
    a month frozen at 23:59 on its last day shows as it was then, not as
    Mercury has it now (Jason, Oct 2026).
    """
    today = today or date.today()
    data = data or _fetch_cached(desk, year, today)
    through = 12 if year < today.year else today.month
    team_ids = {p["uid"] for p in data["people"]}
    is_team = view == "team"
    if not is_team and view not in team_ids:
        raise KeyError(view)
    people = team_ids if is_team else {view}
    snapshots = snapshots or {}

    months, estimate, frozen = {}, {}, {}
    for m in range(1, through + 1):
        snap = snapshots.get(m)
        if snap and snap.get("raw"):
            raw = dict(snap["raw"])
            frozen[f"P{m}"] = {"taken_at": snap.get("taken_at"), "late": bool(snap.get("late"))}
        else:
            raw = compute(people, year, m, data, data["fx"],
                          data["director"] if is_team else None,
                          data.get("book") if is_team else None)
        if is_team:
            for k in DESK_INPUTS:
                estimate[(k, f"P{m}")] = raw.get(k)          # Mercury's own figure, as a guide
                raw[k] = inputs.get(f"{k}:{year}-{m:02d}")
        months[m] = finish(raw)
    cols = {f"P{m}": months[m] for m in months}

    def typed_ratios(name, got):
        # Ratios built on typed figures follow what was typed. The other side
        # is the period's total (not its monthly average): Q1 GP per fee
        # earner is Q1's GP over Q1's person-months.
        def total(k):
            if k in DESK_INPUTS:
                return cols[name].get(k)
            vals = [mo.get(k) for mo in got if mo.get(k) is not None]
            return sum(vals) if vals else None
        for key, _l, _s, _lv, _u, rule in MEASURES:
            if isinstance(rule, tuple) and (rule[1] in DESK_INPUTS or rule[2] in DESK_INPUTS):
                cols[name][key] = _ratio(total(rule[1]), total(rule[2]))

    for name, ms in PERIODS:
        got = [months[m] for m in ms if m in months]
        if got:
            cols[name] = period(got)
            if is_team:
                for k in DESK_INPUTS:
                    estimate[(k, name)] = cols[name].get(k)
                    cols[name][k] = inputs.get(f"{k}:{year}-{name}")
                typed_ratios(name, got)

    # Year to date, over every month so far. Typed rows follow their typed
    # months (GP summed, budgets and carried-in averaged) and aren't typed here.
    got = [months[m] for m in sorted(months)]
    cols["YTD"] = period(got)
    if is_team:
        for k in DESK_INPUTS:
            vals = [mo.get(k) for mo in got if mo.get(k) is not None]
            rule = MEASURE[k][5]
            cols["YTD"][k] = (sum(vals) if rule == "sum" else sum(vals) / len(vals)) if vals else None
        typed_ratios("YTD", got)
    if is_team:
        for c in cols.values():                      # total carried follows its typed parts
            a, b = c.get("carried_a"), c.get("carried_b")
            c["carried_total"] = None if a is None and b is None else (a or 0) + (b or 0)

    shown = ("team", "both") if is_team else ("consultant", "both")
    # The month still running is shown, but marked, and isn't the default focus
    partial = f"P{through}" if (year == today.year and through == today.month) else None
    complete = [m for m in months if f"P{m}" != partial]
    return {
        "desk": desk, "year": year, "through": through, "view": view,
        "partial": partial,
        "focus": f"P{max(complete)}" if complete else f"P{through}",
        # Months shown as frozen at 23:59 on their last day, and when
        "frozen": frozen,
        "columns": [c for c in COLUMN_ORDER if c in cols],
        "values": {c: {k: cols[c].get(k) for k, *_ in MEASURES} for c in cols},
        "measures": [{"key": k, "label": lb, "section": sec, "unit": u,
                      "input": is_team and k in DESK_INPUTS,
                      "tone": TONE.get(k) if is_team else None,
                      "estimate": (k == "headcount") or (not is_team and k.startswith("carried_"))}
                     for k, lb, sec, lv, u, _r in MEASURES if lv in shown],
        # Mercury's figure for each typed cell, shown greyed when it's empty
        "estimates": {f"{k}|{c}": v for (k, c), v in estimate.items() if v is not None},
        "people": [{"uid": p["uid"], "name": p["name"], "active": p["active"]}
                   for p in sorted(data["people"], key=lambda p: (not p["active"], p["name"]))],
    }
