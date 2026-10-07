"""Who can see and change the contract MBR."""
import json

import pytest

import function_app as F

DESK = "London Contract"
LOUIS, JUNAID, OTHER = "louis", "junaid", "elsewhere"


class Req:
    def __init__(self, method="GET", params=None, body=None):
        self.method, self.params, self._body = method, params or {}, body

    def get_json(self):
        return self._body


@pytest.fixture
def desk(monkeypatch):
    """Louis and Junaid on the desk; access set per test."""
    state = {"email": "louis@saragossa.io", "visible": {LOUIS}, "team": False, "edit": False,
             "saved": None, "built": None}
    monkeypatch.setattr(F, "require_auth", lambda req: (state["email"], None))
    monkeypatch.setattr(F, "_mbr_contract_access",
                        lambda email, desk: (state["visible"], state["team"], state["edit"]))
    monkeypatch.setattr("shared.dataverse.get_mbr_targets", lambda uid=None: {})
    monkeypatch.setattr("shared.dataverse.upsert_mbr_targets",
                        lambda uid, values: state.update(saved=(uid, values)))
    monkeypatch.setattr("shared.dataverse.odata_get_all",
                        lambda ent, params=None: [{"systemuserid": LOUIS}])

    def build(desk_, year, view, inputs, today=None, data=None):
        state["built"] = view
        return {"desk": desk_, "year": year, "view": view, "columns": [], "values": {},
                "measures": [], "people": [{"uid": LOUIS, "name": "Louis", "active": True},
                                           {"uid": JUNAID, "name": "Junaid", "active": True}]}
    monkeypatch.setattr("shared.mbr_contract.build_view", build)
    return state


def call(**kw):
    resp = F.mbr_contract(Req(**kw))
    return resp.status_code, json.loads(resp.get_body())


def test_a_consultant_lands_on_their_own_figures(desk):
    status, out = call(params={"desk": DESK})
    assert status == 200 and out["view"] == LOUIS
    assert [p["uid"] for p in out["people"]] == [LOUIS]       # no one else in the picker


def test_a_consultant_asking_for_the_team_gets_only_their_own(desk):
    """Never the team's figures — they're quietly given their own instead."""
    status, out = call(params={"desk": DESK, "view": "team"})
    assert desk["built"] == LOUIS
    assert status == 200 and out["view"] == LOUIS and not out["can_team"]


def test_a_consultant_cannot_open_a_colleague(desk):
    status, _ = call(params={"desk": DESK, "view": JUNAID})
    assert desk["built"] in (None, LOUIS)                     # never builds Junaid's
    assert status in (200, 403)
    if status == 200:
        assert desk["built"] == LOUIS


def test_the_director_opens_the_team_by_default(desk):
    desk.update(email="jonny@saragossa.io", visible={LOUIS, JUNAID}, team=True, edit=True)
    status, out = call(params={"desk": DESK})
    assert status == 200 and out["view"] == "team" and out["can_edit"]


def test_only_editors_can_save(desk):
    status, _ = call(method="POST", body={"desk": DESK, "year": 2026, "values": {"gp_month:2026-09": 1}})
    assert status == 403 and desk["saved"] is None


def test_saves_go_to_the_desk_not_a_person(desk):
    desk.update(email="jonny@saragossa.io", team=True, edit=True)
    status, out = call(method="POST", body={"desk": DESK, "year": 2026,
                                            "values": {"gp_month:2026-09": "453219", "gp_budget:2026-10": ""}})
    assert status == 200
    assert desk["saved"] == ("desk:London Contract", {"gp_month:2026-09": 453219.0, "gp_budget:2026-10": None})


@pytest.mark.parametrize("bad", ["wgp_running:2026-01", "gp_month:2025-01", "gp_month:2026-13", "gp_month"])
def test_only_the_typed_inputs_can_be_written(desk, bad):
    """Mercury-derived figures can never be overwritten by hand."""
    desk.update(email="jonny@saragossa.io", team=True, edit=True)
    status, _ = call(method="POST", body={"desk": DESK, "year": 2026, "values": {bad: 1}})
    assert status == 400 and desk["saved"] is None


def test_an_unknown_desk_is_refused(desk):
    status, _ = call(params={"desk": "Narnia"})
    assert status == 400


@pytest.mark.parametrize("good", ["gp_month:2026-Q1", "gp_budget:2026-H2", "carried_a:2026-03", "carried_b:2026-Q3"])
def test_period_cells_and_carried_in_can_be_typed(desk, good):
    desk.update(email="jonny@saragossa.io", team=True, edit=True)
    status, _ = call(method="POST", body={"desk": DESK, "year": 2026, "values": {good: 5}})
    assert status == 200 and desk["saved"][1] == {good: 5.0}
