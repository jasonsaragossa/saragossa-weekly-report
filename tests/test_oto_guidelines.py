"""Bristol's weekly guidelines: one set for the desk, set by James or Jason."""
import json

import pytest

import function_app as F


class Req:
    def __init__(self, body=None):
        self.method, self.params, self._body = "POST", {}, body

    def get_json(self):
        return self._body


@pytest.fixture
def store(monkeypatch):
    state = {"email": "james@saragossa.io", "saved": {}}
    monkeypatch.setattr(F, "require_auth", lambda req: (state["email"], None))

    def upsert(uid, values):
        state["saved"].setdefault(uid, {}).update(values)
    monkeypatch.setattr("shared.dataverse.upsert_mbr_targets", upsert)
    monkeypatch.setattr("shared.dataverse.get_mbr_targets",
                        lambda uid=None: {uid: state["saved"].get(uid, {})})
    return state


def post(body):
    r = F.one_to_one_guidelines(Req(body))
    return r.status_code, json.loads(r.get_body())


def test_the_loops_four_activities_and_starting_guidelines(store):
    rows = F._oto_key_inputs("bristol")
    assert [(r["label"], r["guide"]) for r in rows] == [
        ("Total BD Actions", 75), ("Client Meetings", 2), ("Candidate Calls", 25), ("Leads Gained", 3)]


def test_james_and_jason_can_change_them_for_the_whole_desk(store):
    for who in ("james@saragossa.io", "Jason@saragossa.io"):
        store["email"] = who
        status, out = post({"template": "bristol", "values": {"bd_actions": 80}})
        assert status == 200 and out["key_inputs"][0]["guide"] == 80
    # Everyone's 1:1 reads the one desk-wide figure
    assert F._oto_key_inputs("bristol")[0]["guide"] == 80


def test_nobody_else_can(store):
    for who in ("sion@saragossa.io", "jakec@saragossa.io", "joshua@saragossa.io"):
        store["email"] = who
        assert post({"template": "bristol", "values": {"bd_actions": 1}})[0] == 403
    assert store["saved"] == {}


def test_only_the_desks_own_key_inputs_and_only_numbers(store):
    assert post({"template": "bristol", "values": {"deals": 5}})[0] == 400
    assert post({"template": "bristol", "values": {"leads": "lots"}})[0] == 400
    assert post({"template": "bristol", "values": {"leads": -1}})[0] == 400
    assert post({"template": "snoz", "values": {"leads": 3}})[0] == 403      # Snoz has none


def test_a_1_1_save_no_longer_carries_guidelines():
    assert "guidelines" not in F._OTO_KEEP["loop"]
