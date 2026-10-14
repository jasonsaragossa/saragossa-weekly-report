"""MBR live jobs: brought in, live now, and where each job stood on the 1st."""
from datetime import date

import pytest

from shared import mbr_jobs as J
from shared.oneonone import VACANCY_GRADES

A, B = VACANCY_GRADES["A"], VACANCY_GRADES["B"]
TODAY = date(2026, 10, 14)


def vac(vid, created, status=143570004, state=0, grade=A, closed=None, modified=None):
    return {"crimson_vacancyid": vid, "crimson_jobtitle": f"Job {vid}", "statuscode": status,
            "statecode": state, "_mercury_vacancytype_value": grade, "createdon": created,
            "modifiedon": modified or created, "crbb7_closedon": closed,
            "crimson_clientid": {"name": f"Client {vid}"}}


def cand(vid, **dates):
    return {"_crimson_vacancyid_value": vid, **dates}


@pytest.fixture
def mercury(monkeypatch):
    m = {"vacs": [], "cands": []}
    monkeypatch.setattr(J, "_vacancies", lambda uid, since, until: m["vacs"])
    monkeypatch.setattr(J, "_shortlists", lambda ids: [c for c in m["cands"]
                                                      if c["_crimson_vacancyid_value"] in ids])
    return m


def test_brought_in_added_closed_and_live_reconcile(mercury):
    mercury["vacs"] = [
        vac("old", "2026-03-01"),                                     # open all along
        vac("lost", "2026-06-01", status=143570001, state=1, closed="2026-09-10"),
        vac("gone", "2026-05-01", status=143570003, state=1, closed="2026-08-20"),  # closed before
        vac("new", "2026-09-15", grade=B),
    ]
    out = J.build("u", 2026, 9, today=TODAY)
    assert out["now"] and out["as_of"] == "2026-10-14"
    assert out["brought_in"] == {"count": 2, "by_grade": {"A": 2}}
    assert out["added"] == 1 and out["closed"] == 1
    assert out["live"] == {"count": 2, "by_grade": {"A": 1, "B": 1}}
    assert out["outcomes"] == {"Still live": 1, "Filled": 0, "Lost or cancelled": 1}
    lost = next(r for r in out["brought_jobs"] if r["id"] == "lost")
    assert lost["now"] == "Lost — competitor placed" and not lost["live"]


def test_the_1st_reads_recent_activity_not_old_history(mercury):
    mercury["vacs"] = [vac("busy", "2025-01-01"), vac("stale", "2025-01-01"),
                       vac("empty", "2026-08-01")]
    mercury["cands"] = [
        cand("busy", new_statussubmitteddate="2026-08-10", mercury_firstinterviewdate="2026-08-20"),
        cand("busy", mercury_firstinterviewdate="2026-09-05"),            # after the 1st
        cand("stale", new_statusoffermadedate="2025-11-01"),              # an old offer
    ]
    out = J.build("u", 2026, 9, today=TODAY)
    by = {r["id"]: r for r in out["brought_jobs"]}
    assert by["busy"]["stage_on_first"] == "First interview"
    assert by["busy"]["interviews_in_month"] == 1 and by["busy"]["cvs_before"] == 1
    assert by["stale"]["stage_on_first"] == J.QUIET
    assert by["stale"]["last_activity_before"] == "2025-11-01"
    assert by["empty"]["stage_on_first"] == "No CVs yet"
    assert by["empty"]["days_open_on_first"] == 31
    stages = {s["stage"]: s["count"] for s in out["stages_on_first"]}
    assert stages["First interview"] == 1 and stages[J.QUIET] == 1 and stages["No CVs yet"] == 1


def test_an_older_month_shows_its_month_end_not_today(mercury):
    mercury["vacs"] = [vac("since-closed", "2026-01-01", status=143570000, state=1,
                           closed="2026-05-10")]
    out = J.build("u", 2026, 3, today=TODAY)
    assert not out["now"] and out["as_of"] == "2026-03-31"
    assert out["live"]["count"] == 1                     # it was still open on 31 March
    assert out["brought_jobs"][0]["live"]


def test_a_closed_job_without_a_closing_date_counts_open_until_last_changed(mercury):
    mercury["vacs"] = [vac("x", "2026-01-01", status=143570002, state=1, modified="2026-09-03")]
    out = J.build("u", 2026, 9, today=TODAY)
    assert out["brought_in"]["count"] == 1 and out["closed"] == 1
