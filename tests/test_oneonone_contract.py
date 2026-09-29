"""The Contract USA 1:1's derived figures, on a small synthetic desk."""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared import oneonone_contract as C  # noqa: E402

ME, OTHER = "me", "other"
WEEK = date(2026, 9, 14)          # the 1:1 covers 14–20 Sep 2026


def P(pid, created, start, end, wnf=500, roles=("ao",), status=143570000, parent=None, actual_end=None):
    """A contract placement with `roles` held by ME: ao / con / cro / conro."""
    p = {"crimson_placementid": pid, "crimson_name": pid, "createdon": created + "T10:00:00",
         "crimson_startdate": start + "T00:00:00", "crimson_enddate": end + "T00:00:00",
         "crimson_actualenddate": (actual_end + "T00:00:00") if actual_end else None,
         "statuscode": status, "recruit_trueweeklygrossprofit": wnf,
         "crimson_extension": 0, "crimson_placementidcode": f"{pid}/00/00",
         "_mercury_parentplacementid_value": parent,
         "_mercury_assignmentowner_value": ME if "ao" in roles else OTHER,
         "_crimson_consultant_value": ME if "con" in roles else OTHER,
         "_mercury_clientrelationshipowner_value": ME if "cro" in roles else OTHER,
         "_mercury_contractorrelationship_userid_value": ME if "conro" in roles else None,
         "crimson_clientname": {"name": "Client"}}
    return p


DESK = [
    # Placed this week, starts next month: counts as a placement, not a starter
    P("new-week", "2026-09-15", "2026-10-05", "2027-04-01", wnf=600, roles=("ao",)),
    # Placed earlier this month with all three roles — full credit
    P("new-month", "2026-09-03", "2026-09-07", "2027-03-01", wnf=900, roles=("ao", "con", "cro")),
    # Cancelled — never counts
    P("cancelled", "2026-09-10", "2026-09-21", "2027-03-01", status=143570009),
    # Long-running, finishes this week, no extension
    P("finisher", "2025-06-01", "2025-06-15", "2026-09-18"),
    # Would finish this month but has an extension — not a finisher
    P("extended", "2025-08-01", "2025-08-10", "2026-09-25"),
    P("extended/01", "2026-09-01", "2026-09-26", "2027-03-01", parent="extended"),
    # Live throughout
    P("live", "2026-01-05", "2026-01-12", "2027-01-12"),
    # Finished in March — inside the rolling year, outside the month
    P("old-finisher", "2025-02-01", "2025-03-01", "2026-03-31"),
]


@pytest.fixture(autouse=True)
def fake_sources(monkeypatch):
    monkeypatch.setattr(C, "_contracts", lambda uid, since: DESK)
    monkeypatch.setattr(C, "get_live_contract_placements", lambda today: [])
    monkeypatch.setattr(C, "get_fx_rates", lambda: None)
    monkeypatch.setattr(C, "_activities", lambda *a, **k: [])
    # The desk works only its graded roles — record what the build asks for.
    asked = {}
    monkeypatch.setattr(C, "_live_jobs", lambda uid, grades=None: asked.__setitem__("grades", grades) or [])
    monkeypatch.setattr(C, "_asked_grades", asked, raising=False)
    monkeypatch.setattr(C, "_company_names", lambda acts: {})
    monkeypatch.setattr(C.date, "today", classmethod(lambda cls: date(2026, 9, 17))) \
        if False else None


def fig(d, key):
    return next(f for f in d["figures"] if f["key"] == key)


def test_placements_are_split_credited(monkeypatch):
    d = C.build_contract_one_to_one(ME, WEEK)
    # Placement credit (not the money split): AO-only on a 3-way deal = 0.5;
    # Consultant + AO + CRO = 0.5 + 0.5 + 0 = 1.0
    assert fig(d, "placements")["week"] == pytest.approx(0.5, abs=0.01)
    assert fig(d, "placements")["month"] == pytest.approx(0.5 + 1.0, abs=0.01)


def test_wnfi_added_follows_the_same_split():
    d = C.build_contract_one_to_one(ME, WEEK)
    assert fig(d, "wnfi_added")["week"] == pytest.approx(600 / 3, abs=0.01)
    assert fig(d, "wnfi_added")["month"] == pytest.approx(600 / 3 + 900, abs=0.01)


def test_starters_count_whole_and_ignore_cancellations():
    d = C.build_contract_one_to_one(ME, WEEK)
    assert fig(d, "starters")["week"] == 0                 # nothing starts 14–20 Sep
    assert fig(d, "starters")["month"] == 1                # new-month; cancelled excluded


def test_finishers_exclude_anyone_extended():
    d = C.build_contract_one_to_one(ME, WEEK)
    assert fig(d, "finishers")["week"] == 1                # finisher, 18 Sep
    assert fig(d, "finishers")["month"] == 1               # extended is not a finisher
    assert [r["role"] for r in fig(d, "finishers")["detail_month"]] == ["finisher"]


def test_attrition_is_finishers_over_those_live_at_the_start():
    d = C.build_contract_one_to_one(ME, WEEK)
    a = d["attrition"]
    # Live at 1 Sep: finisher, extended, live  → 3; one finished → 33.3%
    assert a["month_base"] == 3 and a["month_finishers"] == 1
    assert a["month"] == pytest.approx(33.3, abs=0.1)
    # Rolling year: everyone live at ANY point Sep 25–Sep 26 — finisher,
    # extended (+ its extension, one contractor), live, old-finisher,
    # new-month → 5; two finished
    assert a["rolling_finishers"] == 2
    assert a["rolling_base"] == 5
    assert a["rolling_12m"] == pytest.approx(40.0, abs=0.1)


def test_rolling_attrition_is_not_inflated_by_turnover_inside_the_year(monkeypatch):
    """
    A desk with one contractor a year ago that has since placed and finished
    six more is not at 600% attrition: all seven were live during the year,
    six left → 85.7%. It can never exceed 100%.
    """
    churn = [P("anchor", "2025-01-01", "2025-01-06", "2027-01-01")]
    for i in range(6):
        churn.append(P(f"c{i}", f"2025-{10 + i // 3:02d}-01", f"2025-{10 + i // 3:02d}-06",
                       f"2026-0{1 + i:d}-20"))
    monkeypatch.setattr(C, "_contracts", lambda uid, since: churn)
    a = C.build_contract_one_to_one(ME, WEEK)["attrition"]
    assert a["rolling_finishers"] == 6 and a["rolling_base"] == 7
    assert a["rolling_12m"] == pytest.approx(85.7, abs=0.1)


def test_no_base_means_no_rate_rather_than_a_crash(monkeypatch):
    monkeypatch.setattr(C, "_contracts", lambda uid, since: [])
    d = C.build_contract_one_to_one(ME, WEEK)
    assert d["attrition"]["month"] is None
    assert all(f["week"] == 0 and f["month"] == 0 for f in d["figures"])


def test_only_graded_a_b_c_o_vacancies_are_used():
    """Grade F alone outnumbers A+B+C on the desk nearly three to one."""
    C.build_contract_one_to_one(ME, WEEK)
    assert C._asked_grades["grades"] == ("A", "B", "C", "O")


def test_a_week_straddling_a_month_end_belongs_to_the_month_it_started_in(monkeypatch):
    """
    28 Sep – 4 Oct is a September week: the 1:1 reviews the month that week was
    worked in, not the two days it spills into October (Jason, Sep 2026).
    """
    d = C.build_contract_one_to_one(ME, date(2026, 9, 28))
    assert d["month_label"] == "September"
    # new-month (created 3 Sep) is in that month; a week-end anchor would have
    # given October and lost it
    assert fig(d, "placements")["month"] == pytest.approx(0.5 + 1.0, abs=0.01)


def test_a_week_wholly_inside_a_month_is_unaffected():
    d = C.build_contract_one_to_one(ME, WEEK)
    assert d["month_label"] == "September"


def test_the_month_follows_the_week_not_today(monkeypatch):
    """Opening an older 1:1 shows that week's month, not the current one."""
    d = C.build_contract_one_to_one(ME, date(2026, 3, 2))
    assert d["month_label"] == "March"


# ── Real-shaped extensions: no parent link ────────────────────────────────────
# None of the 232 contract extensions in the year to Sep 2026 has its parent
# link set in Mercury. The fixtures above do, which is how this was missed.
# Codes follow the real pattern: original 004749/00/06, extension 004749/01/00.

def real(pid, code, created, start, end, **kw):
    p = P(pid, created, start, end, **kw)
    p["crimson_placementidcode"] = code
    p["_mercury_parentplacementid_value"] = None
    p["crimson_extension"] = 1 if code.split("/")[1] != "00" else 0
    return p


REAL_DESK = [
    # Original ends 18 Sep, extension picks up the next day — NOT a finisher
    real("orig", "004749/00/06", "2026-03-01", "2026-03-09", "2026-09-18"),
    real("ext", "004749/01/00", "2026-09-10", "2026-09-19", "2027-03-19"),
    # Genuinely finished 17 Sep, never extended
    real("done", "004801/00/02", "2026-02-01", "2026-02-09", "2026-09-17"),
    # Two other live runners
    real("r1", "004900/00/01", "2026-05-01", "2026-05-04", "2027-05-04"),
    real("r2", "004901/00/01", "2026-06-01", "2026-06-08", "2027-06-08"),
]


@pytest.fixture
def real_desk(monkeypatch):
    monkeypatch.setattr(C, "_contracts", lambda uid, since: REAL_DESK)


def test_an_extended_contract_is_not_a_finisher_without_a_parent_link(real_desk):
    d = C.build_contract_one_to_one(ME, WEEK)
    assert [r["role"] for r in fig(d, "finishers")["detail_week"]] == ["done"]
    assert fig(d, "finishers")["month"] == 1


def test_a_contract_and_its_extension_are_one_contractor_in_the_rolling_base(real_desk):
    # orig+ext, done, r1, r2 → 4 contractors, not 5
    assert C.build_contract_one_to_one(ME, WEEK)["attrition"]["rolling_base"] == 4


def test_runners_are_contractors_out_today_counted_as_people(real_desk, monkeypatch):
    """Today 29 Sep: ext, r1, r2 are out — orig and done have ended."""
    monkeypatch.setattr(C, "date", _FixedDate)
    assert C.build_contract_one_to_one(ME, WEEK)["runners"] == 3


def test_runners_count_whole_not_split(monkeypatch):
    """A runner is a person: AO-only (a third of the credit) still counts as 1."""
    monkeypatch.setattr(C, "date", _FixedDate)
    monkeypatch.setattr(C, "_contracts", lambda uid, since: [
        real("ao", "005000/00/01", "2026-05-01", "2026-05-04", "2027-05-04", roles=("ao",))])
    assert C.build_contract_one_to_one(ME, WEEK)["runners"] == 1


def test_a_contract_overlapping_its_own_extension_is_still_one_runner(monkeypatch):
    monkeypatch.setattr(C, "date", _FixedDate)
    monkeypatch.setattr(C, "_contracts", lambda uid, since: [
        real("o", "005100/00/01", "2026-01-01", "2026-01-05", "2026-10-31"),
        real("e", "005100/01/00", "2026-09-01", "2026-09-28", "2027-03-31")])
    assert C.build_contract_one_to_one(ME, WEEK)["runners"] == 1


class _FixedDate(date):
    @classmethod
    def today(cls):
        return date(2026, 9, 29)
