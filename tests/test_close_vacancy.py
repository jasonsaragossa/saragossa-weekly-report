"""
Closing a job from the 1:1 — the guard rails, not the happy path.

This writes into Mercury, so what matters is everything it refuses: a reason
that isn't a closing reason, a vacancy on someone else's desk, and a job that
is already closed.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared import dataverse as D  # noqa: E402

MINE = "11111111-1111-1111-1111-111111111111"
THEIRS = "22222222-2222-2222-2222-222222222222"
VAC = "33333333-3333-3333-3333-333333333333"


# ── The reason list ───────────────────────────────────────────────────────────

def test_the_offered_reasons_are_the_lost_and_cancelled_ones():
    labels = [lb for _, lb in D.VACANCY_CLOSE_REASONS]
    assert labels == ["Lost - competitor placed", "Lost - filled internally",
                      "Lost - project cancelled", "Lost - other reason", "Cancelled"]


def test_won_is_not_offered_because_a_win_comes_from_a_placement():
    """Marking a vacancy won with no placement behind it would show a win the
    placement figures never see."""
    assert 143570000 not in D.VACANCY_CLOSE_CODES      # Won - all positions filled
    assert 2 not in D.VACANCY_CLOSE_CODES              # Won - part filled vacancy


def test_closing_writes_inactive_plus_the_reason(monkeypatch):
    sent = {}
    monkeypatch.setattr(D, "odata_patch", lambda path, body: sent.update(path=path, body=body))
    D.close_vacancy(VAC, 939310000)
    assert sent["path"] == f"crimson_vacancies({VAC})"
    assert sent["body"] == {"statecode": 1, "statuscode": 939310000}


@pytest.mark.parametrize("bad", [143570000, 2, 0, 1, 999, 143570004])
def test_a_reason_that_is_not_a_closing_reason_is_refused(monkeypatch, bad):
    monkeypatch.setattr(D, "odata_patch",
                        lambda *a, **k: pytest.fail("must not write"))
    with pytest.raises(ValueError):
        D.close_vacancy(VAC, bad)


# ── The endpoint's guards ─────────────────────────────────────────────────────

@pytest.fixture
def api(monkeypatch):
    import function_app as F

    state = {"vacancy": {"crimson_vacancyid": VAC, "crimson_jobtitle": "Contract DBA",
                         "statecode": 0, "_crimson_deliveryownerid_value": MINE},
             "closed": []}
    monkeypatch.setattr(F, "require_auth", lambda req: ("connor@saragossa.io", None))
    monkeypatch.setattr("shared.oto_templates.templates_for",
                        lambda email, is_admin: [{"people": [{"systemuserid": MINE}]}])
    monkeypatch.setattr("shared.dataverse.get_vacancy", lambda vid: state["vacancy"])
    monkeypatch.setattr("shared.dataverse.close_vacancy",
                        lambda vid, code: state["closed"].append((vid, code)))
    return F, state


class Req:
    def __init__(self, body):
        self._body = body

    def get_json(self):
        return self._body


def call(F, body):
    resp = F.close_vacancy_route(Req(body))
    import json
    return resp.status_code, json.loads(resp.get_body())


def test_a_job_on_your_own_desk_closes(api):
    F, state = api
    status, out = call(F, {"vacancy_id": VAC, "statuscode": 939310000})
    assert status == 200 and out["ok"]
    assert state["closed"] == [(VAC, 939310000)]


def test_someone_elses_job_is_refused(api):
    F, state = api
    state["vacancy"]["_crimson_deliveryownerid_value"] = THEIRS
    status, out = call(F, {"vacancy_id": VAC, "statuscode": 939310000})
    assert status == 403 and not out["ok"]
    assert state["closed"] == []


def test_an_already_closed_job_is_not_reclosed(api):
    """Otherwise a second click would overwrite the reason already recorded."""
    F, state = api
    state["vacancy"]["statecode"] = 1
    status, out = call(F, {"vacancy_id": VAC, "statuscode": 143570003})
    assert status == 409 and state["closed"] == []


def test_a_bogus_reason_never_reaches_mercury(api):
    F, state = api
    status, _ = call(F, {"vacancy_id": VAC, "statuscode": 143570000})   # Won
    assert status == 400 and state["closed"] == []


def test_a_bad_vacancy_id_is_refused_before_any_lookup(api):
    F, state = api
    status, _ = call(F, {"vacancy_id": "not-a-guid", "statuscode": 939310000})
    assert status == 400 and state["closed"] == []


def test_someone_on_no_team_cannot_close_anything(api, monkeypatch):
    F, state = api
    monkeypatch.setattr("shared.oto_templates.templates_for", lambda email, is_admin: [])
    status, _ = call(F, {"vacancy_id": VAC, "statuscode": 939310000})
    assert status == 403 and state["closed"] == []


# ── The contract 1:1 opens on last week ───────────────────────────────────────

def test_the_contract_1_1_defaults_to_the_week_just_finished():
    """Jim's desk meets on a Monday, so a 1:1 opened with no week asked for
    shows the week that finished, not one a few hours old."""
    from datetime import date
    from shared.oneonone import default_week
    # Monday, mid-week and Sunday all land on the same finished week
    for today in (date(2026, 9, 21), date(2026, 9, 24), date(2026, 9, 27)):
        assert default_week("contract", today) == date(2026, 9, 14)


def test_the_perm_1_1_still_opens_on_the_current_week():
    from datetime import date
    from shared.oneonone import default_week
    assert default_week("perm", date(2026, 9, 24)) == date(2026, 9, 21)


def test_the_default_week_is_always_a_monday():
    from datetime import date, timedelta
    from shared.oneonone import default_week
    day = date(2026, 1, 1)
    for _ in range(400):
        for kind in ("contract", "perm"):
            assert default_week(kind, day).weekday() == 0
        day += timedelta(days=1)
