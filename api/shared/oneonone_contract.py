"""
The derived half of a Contract USA 1:1 (Jim Jeffers' desk, Sep 2026).

A contract desk is measured on contractors rather than deals: what was placed
and how much weekly margin it added, who started, who finished and whether
they were replaced, and what is live right now. Everything here comes from
contract placements the person has a role on. Money (WGP, weekly gross profit) is split a third
each 3-way or a quarter each 4-way (split_factor); the placement count uses
placement_credit (0.5 Consultant + 0.5 AO, or 0.25 each on a 4-way deal).
Starters and finishers are people, so they count whole.

  Placements in month     placements CREATED in the month, split-credited
  WGP added               their weekly gross profit, split-credited, in USD
  Starters in month       start date in the month, not cancelled
  Finishers in month      effective end in the month, started, no extension
  Attrition               month: finishers ÷ contractors live at the start
                          rolling 12m: finishers ÷ every contractor live at
                          ANY point in the year (Jason, Sep 2026) — a year-old
                          snapshot would miss everyone who both started and
                          finished inside it, most of a contract desk's churn
  Current WGP             the weekly report's WGP figure for the person
  Client meetings         appointments this week, new business vs process
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from shared.calc import (TO_USD, _build_fx_tables, _is_extension, compute_wnf,
                         parse_date, placement_credit, split_factor)
from shared.dataverse import (CANCEL_CODES, CONTRACT_TYPES, get_fx_rates,
                              get_live_contract_placements, odata_get_all, odata_str)
from shared.mbr_registry import CANDIDATE_CALL_PURPOSES, CLIENT_MEETING_PURPOSES
from shared.oneonone import (LEADS, VACANCY_GRADES, _activities, _activity_row, _company_names,
                             _live_jobs, _shortlist_row, _shortlists, _sorted, week_start)

# The activity section (Jason, Oct 2026): inputs, the leading input, outputs.
# Spec sends are first sends only — follow-up emails don't count (Jason, Oct 2026).
# Senior candidate networking calls and B managers are typed on the page, not
# counted here: the desk doesn't log them in a way Mercury can see.
SPEC_CV = "47e272c6-a769-ee11-94f7-000d3ad6abf9"            # Spec CV — logged as an email
_GRADE_BY_ID = {v: k for k, v in VACANCY_GRADES.items()}


def _spec_sends(uid: str, start: date, end: date) -> list:
    """Spec CVs sent. Emails tag their purpose in _recruit_purpose_value."""
    return odata_get_all("emails", params={
        "$select": "activityid,subject,createdon",
        "$filter": (f"_recruit_purpose_value eq '{SPEC_CV}' and _ownerid_value eq '{odata_str(uid)}'"
                    f" and createdon ge {start.isoformat()} and createdon lt {end.isoformat()}"),
        "$expand": ("regardingobjectid_account($select=name),"
                    "regardingobjectid_contact($select=fullname,jobtitle,_parentcustomerid_value)"),
    })


def _jobs_pulled(uid: str, start: date, end: date) -> list:
    """Vacancies brought in: created in the period, this person the delivery owner."""
    return odata_get_all("crimson_vacancies", params={
        "$select": "crimson_vacancyid,crimson_jobtitle,crimson_name,createdon,_mercury_vacancytype_value",
        "$filter": (f"_crimson_deliveryownerid_value eq '{odata_str(uid)}'"
                    f" and createdon ge {start.isoformat()}T00:00:00Z"
                    f" and createdon lt {end.isoformat()}T00:00:00Z"),
        "$expand": "crimson_clientid($select=name)",
    })


def _job_row(v: dict) -> dict:
    grade = _GRADE_BY_ID.get(v.get("_mercury_vacancytype_value"), "")
    return {"contact": "", "client": (v.get("crimson_clientid") or {}).get("name") or "",
            "subject": (v.get("crimson_jobtitle") or v.get("crimson_name") or "")
                       + (f" · Grade {grade}" if grade else ""),
            "when": (v.get("createdon") or "")[:10]}

# The purposes that mean new business rather than running a process.
NB_MEETING_PURPOSES = {
    "92fcaab8-9a50-ee11-be6f-0022481b503e",   # New Client Meeting
    "bdf76a79-e9f0-ee11-904c-6045bdd19e21",   # Subsequent New Client Meeting
    "94fcaab8-9a50-ee11-be6f-0022481b503e",   # Client Presentation
    "11350f1f-1e4e-f111-bec6-002248433928",   # Solution Cross-Sell Meeting
}

_OWNER_FIELDS = ("_mercury_clientrelationshipowner_value", "_crimson_consultant_value",
                 "_mercury_assignmentowner_value", "_mercury_contractorrelationship_userid_value")


def _month_bounds(anchor: date) -> tuple:
    start = date(anchor.year, anchor.month, 1)
    end = date(anchor.year + (anchor.month == 12), anchor.month % 12 + 1, 1)
    return start, end


def _contracts(uid: str, since: date) -> list:
    """Every contract placement this person has a role on, from `since`."""
    types = " or ".join(f"crimson_type eq {t}" for t in CONTRACT_TYPES)
    owner = " or ".join(f"{f} eq '{odata_str(uid)}'" for f in _OWNER_FIELDS)
    return odata_get_all("crimson_placements", params={
        "$select": ("crimson_placementid,crimson_name,createdon,crimson_startdate,"
                    "crimson_enddate,crimson_actualenddate,statuscode,"
                    "recruit_trueweeklygrossprofit,crimson_extension,"
                    "crimson_placementidcode,_mercury_parentplacementid_value,"
                    + ",".join(_OWNER_FIELDS)),
        "$filter": (f"({types}) and ({owner})"
                    f" and (createdon ge {since.isoformat()}"
                    f" or crimson_enddate ge {since.isoformat()}"
                    f" or crimson_actualenddate ge {since.isoformat()})"),
        "$expand": ("crimson_clientname($select=name),"
                    "recruit_trueweeklygrossprofitcurrency($select=isocurrencycode)"),
    })


def _d(value) -> date | None:
    try:
        return parse_date(value) if value else None
    except Exception:
        return None


def _effective_end(p: dict) -> date | None:
    ends = [d for d in (_d(p.get("crimson_actualenddate")), _d(p.get("crimson_enddate"))) if d]
    return min(ends) if ends else None


def _cancelled(p: dict) -> bool:
    return p.get("statuscode") in CANCEL_CODES


def _contractor_key(p: dict) -> str:
    """
    One contractor across a contract and all its extensions. The first part of
    the placement code is shared by both (004749/00/06 and 004749/01/00) and,
    unlike the parent link, is always filled in.
    """
    code = (p.get("crimson_placementidcode") or "").split("/")[0].strip()
    return code or p.get("_mercury_parentplacementid_value") or p["crimson_placementid"]


def _row(p: dict, uid: str) -> dict:
    return {"client": (p.get("crimson_clientname") or {}).get("name") or "",
            "role": p.get("crimson_name") or "",
            "start": (p.get("crimson_startdate") or "")[:10],
            "end": (_effective_end(p) or "").isoformat() if _effective_end(p) else "",
            "wnfi": round((p.get("recruit_trueweeklygrossprofit") or 0) * split_factor(p, uid), 2),
            "share": round(split_factor(p, uid), 2)}


def build_contract_one_to_one(uid: str, week: date = None) -> dict:
    week = week_start(week or date.today())
    next_week = week + timedelta(days=7)
    today = date.today()
    # Month = the month the week BEGINS in. A week straddling a month end
    # belongs to the month it started in: the 1:1 reviews what happened and
    # plans from there, so the useful month column is the one that week was
    # worked in, not the one it spills a day or two into (Jason, Sep 2026).
    # Unlike the perm template it is NOT cut at today: a contractor due to
    # finish on the 28th is a finisher this month, and a start booked for the
    # 25th is a starter. Placements are dated by creation, which cannot be in
    # the future, so they come out the same.
    m_start, m_end = _month_bounds(week)
    r12_start = date(m_start.year - 1, m_start.month, 1)

    with ThreadPoolExecutor(max_workers=12) as pool:
        f = {
            "contracts": pool.submit(_contracts, uid, r12_start - timedelta(days=400)),
            "live":      pool.submit(get_live_contract_placements, today.isoformat()),
            "fx":        pool.submit(get_fx_rates),
            "meetings":  pool.submit(_activities, "appointments", "scheduledstart", uid, week, next_week),
            "jobs":      pool.submit(_live_jobs, uid, ("A", "B", "C", "O")),   # graded roles only
            # The activity section, for the week and its month
            "calls_w":   pool.submit(_activities, "phonecalls", "createdon", uid, week, next_week),
            "calls_m":   pool.submit(_activities, "phonecalls", "createdon", uid, m_start, m_end),
            "appts_m":   pool.submit(_activities, "appointments", "scheduledstart", uid, m_start, m_end),
            "spec_w":    pool.submit(_spec_sends, uid, week, next_week),
            "spec_m":    pool.submit(_spec_sends, uid, m_start, m_end),
            "sl_w":      pool.submit(_shortlists, uid, week, next_week),
            "sl_m":      pool.submit(_shortlists, uid, m_start, m_end),
            "pulled_w":  pool.submit(_jobs_pulled, uid, week, next_week),
            "pulled_m":  pool.submit(_jobs_pulled, uid, m_start, m_end),
        }
        r = {}
        for k, v in f.items():
            try:
                r[k] = v.result()
            except Exception:
                if k != "fx":
                    raise
                r[k] = None

    contracts = r["contracts"]
    # A contract is "extended" if the same contractor has a later record. This
    # can't use the parent link: none of the 232 contract extensions in the
    # year to Sep 2026 has it set, so every extended contractor was showing as
    # a finisher. The placement code's first part is always there.
    latest = {}
    for p in contracts:
        if _cancelled(p):
            continue
        k, s = _contractor_key(p), _d(p.get("crimson_startdate"))
        if s and (k not in latest or s > latest[k]):
            latest[k] = s
    extended = {p["crimson_placementid"] for p in contracts
                if (s := _d(p.get("crimson_startdate"))) and s < latest.get(_contractor_key(p), s)}

    def created_in(start, end):
        return [p for p in contracts if not _cancelled(p) and not _is_extension(p)
                and (c := _d(p.get("createdon"))) and start <= c < end]

    def starters_in(start, end):
        return [p for p in contracts if not _cancelled(p) and not _is_extension(p)
                and (s := _d(p.get("crimson_startdate"))) and start <= s < end]

    def finishers_in(start, end):
        out = []
        for p in contracts:
            if _cancelled(p) or p["crimson_placementid"] in extended:
                continue
            s, e = _d(p.get("crimson_startdate")), _effective_end(p)
            if s and e and s < e and start <= e < end and s < end:
                out.append(p)
        return out

    def live_at(day):
        """Contractors on the books at the start of `day`."""
        return [p for p in contracts if not _cancelled(p)
                and (s := _d(p.get("crimson_startdate"))) and s < day
                and (e := _effective_end(p)) and e >= day]

    def split_count(rows):
        return round(sum(placement_credit(p, uid) for p in rows), 2)

    def wnfi(rows):
        return round(sum((p.get("recruit_trueweeklygrossprofit") or 0) * split_factor(p, uid)
                         for p in rows), 2)

    def attrition(finishers, base_count):
        return round(len(finishers) / base_count * 100, 1) if base_count else None

    def live_during(start, end):
        """Distinct contractors on the books at any point in [start, end).
        A contract and its extension are one contractor."""
        roots = set()
        for p in contracts:
            if _cancelled(p):
                continue
            s, e = _d(p.get("crimson_startdate")), _effective_end(p)
            if s and e and s < end and e >= start:
                roots.add(_contractor_key(p))
        return len(roots)

    placed_w, placed_m = created_in(week, next_week), created_in(m_start, m_end)
    start_w, start_m = starters_in(week, next_week), starters_in(m_start, m_end)
    fin_w, fin_m = finishers_in(week, next_week), finishers_in(m_start, m_end)
    fin_12 = finishers_in(r12_start, m_end)
    base_m = len(live_at(m_start))
    base_12 = live_during(r12_start, m_end)

    # USD is the desk's currency; the live-contract WGP helper handles the FX.
    to_usd = _build_fx_tables(r["fx"])[1] if r["fx"] else TO_USD
    current_wnfi = compute_wnf(uid, r["live"], "USD", None, to_usd)

    companies = _company_names(r["meetings"])
    meetings = []
    for a in sorted(r["meetings"], key=lambda a: a.get("scheduledstart") or ""):
        purpose = a.get("_mercury_purpose_value")
        if purpose not in CLIENT_MEETING_PURPOSES:
            continue
        row = _activity_row(a, "scheduledstart", companies)
        row["kind"] = "New business" if purpose in NB_MEETING_PURPOSES else "Process"
        row["id"] = a.get("activityid")
        meetings.append(row)

    # ── Activity: inputs, the leading input, outputs ──────────────────────────
    act_companies = _company_names(r["calls_m"] + r["appts_m"] + r["meetings"] + r["spec_m"])

    def acts(rows, purposes, datefield):
        return _sorted([_activity_row(a, datefield, act_companies) for a in rows
                        if a.get("_mercury_purpose_value") in purposes])

    def cvs(sl):
        return _sorted([_shortlist_row(s, "new_statussubmitteddate") for s in sl
                        if s.get("new_statussubmitteddate")])

    def in_range(rows, start, end):
        return [x for x in rows if x["when"] and start.isoformat() <= x["when"] < end.isoformat()]

    def measure(key, group, label, week_rows, month_rows, note=""):
        return {"key": key, "group": group, "label": label, "note": note,
                "week": len(week_rows), "month": len(month_rows),
                "detail_week": week_rows, "detail_month": month_rows}

    cand = set(CANDIDATE_CALL_PURPOSES)
    meet_w = acts(r["meetings"], CLIENT_MEETING_PURPOSES, "scheduledstart")
    activity = [
        measure("candidate_calls", "Inputs", "Candidate calls",
                acts(r["calls_w"], cand, "createdon"), acts(r["calls_m"], cand, "createdon")),
        measure("spec_sends", "Inputs", "Spec sends",
                _sorted([_activity_row(e, "createdon", act_companies) for e in r["spec_w"]]),
                _sorted([_activity_row(e, "createdon", act_companies) for e in r["spec_m"]]),
                "spec CV emails"),
        measure("resumes", "Inputs", "Resumes to jobs",
                in_range(cvs(r["sl_w"]), week, next_week), in_range(cvs(r["sl_m"]), m_start, m_end),
                "CVs submitted to live roles"),
        measure("leads", "Inputs", "Leads gained",
                acts(r["calls_w"], LEADS, "createdon"), acts(r["calls_m"], LEADS, "createdon"),
                "lead gained from a candidate, or a manager referral"),
        measure("client_meetings", "Leading input", "Client meetings",
                meet_w, acts(r["appts_m"], CLIENT_MEETING_PURPOSES, "scheduledstart")),
        measure("jobs_pulled", "Outputs", "Jobs pulled",
                _sorted([_job_row(v) for v in r["pulled_w"]]),
                _sorted([_job_row(v) for v in r["pulled_m"]]),
                "new roles where you're the delivery owner"),
    ]

    rows = lambda ps: [_row(p, uid) for p in ps]
    live_now = live_at(today + timedelta(days=1))
    return {
        "week_start": week.isoformat(),
        "month_label": m_start.strftime("%B"),
        "figures": [
            {"key": "placements", "label": "Placements", "week": split_count(placed_w),
             "month": split_count(placed_m), "detail_week": rows(placed_w), "detail_month": rows(placed_m),
             "note": "split-credited"},
            {"key": "wnfi_added", "label": "WGP added", "week": wnfi(placed_w),
             "month": wnfi(placed_m), "money": True, "detail_week": rows(placed_w),
             "detail_month": rows(placed_m), "note": "weekly margin of placements made, split-credited"},
            {"key": "starters", "label": "Starters", "week": len(start_w), "month": len(start_m),
             "detail_week": rows(start_w), "detail_month": rows(start_m)},
            {"key": "finishers", "label": "Finishers", "week": len(fin_w), "month": len(fin_m),
             "detail_week": rows(fin_w), "detail_month": rows(fin_m),
             "note": "ended without an extension"},
        ],
        "attrition": {
            "month": attrition(fin_m, base_m), "month_finishers": len(fin_m),
            "month_base": base_m,
            "rolling_12m": attrition(fin_12, base_12), "rolling_finishers": len(fin_12),
            "rolling_base": base_12,
            "definition": ("month: finishers without extension ÷ live at the start of the month; "
                           "rolling 12m: ÷ every contractor live at any point in the year"),
        },
        "current_wnfi": current_wnfi,
        "live_contracts": rows(live_now),
        # Runners = contractors out on assignment today, counted as people:
        # whole, not split, and a contract with its extension is one runner.
        "runners": len({_contractor_key(p) for p in live_now}),
        "meetings": meetings,
        "live_jobs": r["jobs"],
        "activity": activity,
    }
