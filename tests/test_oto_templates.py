"""Who may see whose 1:1, per template."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared import oto_templates as T  # noqa: E402
from shared.dataverse import TERRITORY_IDS  # noqa: E402


def _u(uid, name, email):
    return {"systemuserid": uid, "fullname": name, "internalemailaddress": email, "isdisabled": False}


CHICAGO = [
    _u("jim",     "Jim Jeffers",       "jim@saragossa.io"),
    _u("connor",  "Connor Newhouse",   "connor@saragossa.io"),
    _u("brandon", "Brandon Herron",    "brandon@saragossa.io"),
    _u("mak",     "Makenzie Thompson", "makenzie@saragossa.io"),
    _u("cate",    "Cate Seward",       "cate@saragossa.io"),
    _u("mike",    "Michael Beneke",    "michaelb@saragossa.io"),
    _u("lily",    "Lily Hautau",       "lilyh@saragossa.io"),
    _u("reid",    "Reid Millikan",     "reid@saragossa.io"),
    _u("house",   "Saragossa House Contract USA", None),
]
SNOZ = [
    _u("harry", "Harry Snozwell", "harrysnozwell@saragossa.io"),
    _u("clara", "Clara Rapley",   "clara@saragossa.io"),
]
BRISTOL = [
    _u("james",  "James Batt",     "james@saragossa.io"),
    _u("sion",   "Sion Johnson",   "sion@saragossa.io"),
    _u("megan",  "Megan Christie", "megan@saragossa.io"),
    _u("jake",   "Jake Cogzell",   "Jakec@saragossa.io"),
    _u("joshua", "Joshua Rimmer",  "joshua@saragossa.io"),
    _u("bhouse", "Saragossa House Bristol", None),
]
# As Mercury has them: Jake is still in Team Sion there; Settings moves him
BRISTOL_TEAMS = {
    "Team Sion": [BRISTOL[1], BRISTOL[2], BRISTOL[3]],
    "Team Jake": [BRISTOL[4]],
}
TEAMS = {
    "Team Snoz":     SNOZ,
    "Team Connor":   [CHICAGO[1], CHICAGO[2]],
    "Team Makenzie": [CHICAGO[3], CHICAGO[4]],
    "Team Mike B":   [CHICAGO[5], CHICAGO[6]],
}


@pytest.fixture(autouse=True)
def fake_dataverse(monkeypatch):
    """Answer the two shapes of query the module makes, from the fixtures."""
    def odata_get_all(path, params=None):
        f = (params or {}).get("$filter", "")
        if path == "teams":
            name = f.split("'")[1]
            return [{"teamid": name}] if name in TEAMS else []
        if path.startswith("teams("):
            return TEAMS[path[6:].split(")")[0]]
        if path == "systemusers" and TERRITORY_IDS["Chicago Contract"] in f:
            return CHICAGO
        if path == "systemusers" and TERRITORY_IDS["Bristol"] in f:
            return BRISTOL
        return []
    monkeypatch.setattr(T, "odata_get_all", odata_get_all)
    # Sub-team leads go by the team the report shows: Mercury's, unless one is
    # set in Settings
    from shared import dataverse as D
    mercury = {p["systemuserid"]: team for team, ps in {**TEAMS, **BRISTOL_TEAMS}.items() for p in ps}
    monkeypatch.setattr(D, "get_team_membership_map", lambda: mercury)
    monkeypatch.setattr(D, "get_overrides", lambda: [{"crbb7_userid": "jake", "crbb7_team": "Team Jake"}])


def names(people):
    return sorted(p["fullname"] for p in people)


def test_the_admin_sees_every_template_and_everyone():
    tpls = T.templates_for("jason@saragossa.io", is_admin=True)
    assert [t["id"] for t in tpls] == ["snoz", "contract_usa", "bristol"]
    assert all(t["is_lead"] for t in tpls)
    assert "Saragossa House Contract USA" not in names(tpls[1]["people"])
    assert "Jim Jeffers" not in names(tpls[1]["people"])


def test_jim_and_andrew_see_the_whole_contract_desk_and_nothing_else():
    for who in ("jim@saragossa.io", "andrewt@saragossa.io"):
        tpls = T.templates_for(who, is_admin=False)
        assert [t["id"] for t in tpls] == ["contract_usa"], who
        assert tpls[0]["is_lead"]
        assert len(tpls[0]["people"]) == 7   # not the house account, and not Jim


def test_a_sub_team_lead_sees_only_their_own_team():
    people, lead = T.visible_people("contract_usa", "connor@saragossa.io", is_admin=False)
    assert lead and names(people) == ["Brandon Herron", "Connor Newhouse"]
    people, lead = T.visible_people("contract_usa", "makenzie@saragossa.io", is_admin=False)
    assert lead and names(people) == ["Cate Seward", "Makenzie Thompson"]
    people, lead = T.visible_people("contract_usa", "michaelb@saragossa.io", is_admin=False)
    assert lead and names(people) == ["Lily Hautau", "Michael Beneke"]


def test_a_consultant_sees_only_themselves():
    people, lead = T.visible_people("contract_usa", "brandon@saragossa.io", is_admin=False)
    assert not lead and names(people) == ["Brandon Herron"]


def test_someone_in_no_sub_team_is_seen_by_the_desk_lead_only():
    """Reid and Austin have no Mercury sub-team — Jim, Andrew and admins only."""
    people, _ = T.visible_people("contract_usa", "reid@saragossa.io", is_admin=False)
    assert names(people) == ["Reid Millikan"]
    people, _ = T.visible_people("contract_usa", "connor@saragossa.io", is_admin=False)
    assert "Reid Millikan" not in names(people)


def test_harry_sees_his_team_and_not_the_contract_desk():
    tpls = T.templates_for("harrysnozwell@saragossa.io", is_admin=False)
    assert [t["id"] for t in tpls] == ["snoz"]
    assert names(tpls[0]["people"]) == ["Clara Rapley", "Harry Snozwell"]


def test_the_contract_desk_cannot_see_harrys_team():
    assert T.visible_people("snoz", "jim@saragossa.io", is_admin=False) == ([], False)


def test_an_outsider_sees_nothing():
    assert T.templates_for("someone@saragossa.io", is_admin=False) == []


def test_jim_runs_the_1_1s_rather_than_sitting_in_one():
    """He leads the desk, so he sees everyone — but has no 1:1 of his own
    (Jason, Sep 2026)."""
    people, lead = T.visible_people("contract_usa", "jim@saragossa.io", is_admin=False)
    assert lead
    assert "Jim Jeffers" not in names(people)
    # And nobody else can open one for him either
    for who, admin in (("andrewt@saragossa.io", False), ("jason@saragossa.io", True),
                       ("connor@saragossa.io", False)):
        seen, _ = T.visible_people("contract_usa", who, is_admin=admin)
        assert "Jim Jeffers" not in names(seen), who


# ── Bristol ───────────────────────────────────────────────────────────────────

def test_james_sees_all_of_bristol_but_has_no_1_1_himself():
    people, lead = T.visible_people("bristol", "james@saragossa.io", is_admin=False)
    assert lead
    assert names(people) == ["Jake Cogzell", "Joshua Rimmer", "Megan Christie", "Sion Johnson"]


def test_a_bristol_team_lead_sees_the_team_settings_gives_them():
    # Jake leads Team Jake (set in Settings) though Mercury still has him in Sion's
    people, lead = T.visible_people("bristol", "jakec@saragossa.io", is_admin=False)
    assert lead and names(people) == ["Jake Cogzell", "Joshua Rimmer"]
    people, lead = T.visible_people("bristol", "sion@saragossa.io", is_admin=False)
    assert lead and names(people) == ["Megan Christie", "Sion Johnson"]


def test_a_bristol_consultant_sees_only_themselves():
    people, lead = T.visible_people("bristol", "joshua@saragossa.io", is_admin=False)
    assert not lead and names(people) == ["Joshua Rimmer"]


# ── Career ladder ─────────────────────────────────────────────────────────────

def test_the_ladder_is_the_one_jason_gave():
    assert T.CAREER_LADDER == ("Associate", "Consultant", "Senior Consultant",
                               "Lead Consultant", "Principal Consultant", "EIC")


def test_the_real_mercury_titles_on_the_desk_map_to_a_rung():
    """The titles actually on the Chicago Contract desk, read 29 Sep 2026."""
    assert T.rung("Associate Consultant") == "Associate"      # Lily, Cate
    assert T.rung("Consultant") == "Consultant"               # Brandon, Austin
    assert T.rung("Senior Consultant") == "Senior Consultant"  # Reid, Makenzie
    assert T.rung("Principal Consultant") == "Principal Consultant"   # Michael B


def test_a_title_that_is_not_on_the_ladder_gives_no_rung():
    """Better an unlit strip than a guessed rung in a progression talk."""
    assert T.rung("Team Lead - Contract") is None             # Connor
    assert T.rung("Contract Sales Director") is None          # Jim
    assert T.rung("") is None and T.rung(None) is None


def test_matching_ignores_case_and_stray_spacing():
    assert T.rung("  senior CONSULTANT ") == "Senior Consultant"


def test_every_rung_is_reachable_from_some_title():
    """A rung nothing can map to would sit permanently unlit."""
    reachable = {T.rung(t) for t in T._TITLE_TO_RUNG}
    assert reachable == set(T.CAREER_LADDER)


def test_the_us_desk_gets_us_dates_and_the_uk_desk_uk_ones():
    assert T.TEMPLATES["contract_usa"]["locale"] == "en-US"
    assert T.TEMPLATES["snoz"]["locale"] == "en-GB"
