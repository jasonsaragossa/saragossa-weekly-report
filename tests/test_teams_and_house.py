"""Teams found in Mercury on their own, and house accounts for Directors only."""
import function_app as F
from shared import calc
from shared import dataverse as D


def test_preferred_team_wins_over_the_rest():
    # James Batt sits in Team Batt, Team Charlie and Team Ed
    assert D.pick_team(["Team Ed", "Team Charlie", "Team Batt"], {"Team Ed": 1}) == "Team Batt"


def test_smallest_new_team_wins_so_a_desk_wide_team_only_takes_the_rest():
    sizes = {"Team Jim": 8, "Team Connor": 2}
    assert D.pick_team(["Team Jim", "Team Connor"], sizes) == "Team Connor"
    assert D.pick_team(["Team Jim"], sizes) == "Team Jim"
    assert D.pick_team([], sizes) == ""


def test_membership_map_finds_every_team(monkeypatch):
    teams = [{"teamid": "1", "name": "Team Jim"}, {"teamid": "2", "name": "Team Connor"},
             {"teamid": "3", "name": "Team Adam B"}]
    rosters = {"1": ["a", "b", "c"], "2": ["a", "b"], "3": ["d"]}

    def fake(path, params=None):
        if path == "teams":
            assert "startswith(name,'Team ')" in params["$filter"]
            return teams
        tid = path.split("(")[1].split(")")[0]
        return [{"systemuserid": u, "isdisabled": False} for u in rosters[tid]]

    monkeypatch.setattr(D, "odata_get_all", fake)
    got = D.get_team_membership_map.__wrapped__()
    assert got == {"a": "Team Connor", "b": "Team Connor", "c": "Team Jim", "d": "Team Adam B"}


def test_a_desk_splits_once_it_has_two_teams():
    one = [{"team": "Team Jonny"}, {"team": "Team Jonny"}]
    two = [{"team": "Team Ryan"}, {"team": "Team Adam B"}]
    assert not calc.splits_into_teams("London Contract", one)
    assert calc.splits_into_teams("New York", two)
    assert calc.splits_into_teams("Bristol", [{"team": ""}])


def test_team_order_listed_then_new_then_none():
    teams = ["", "Team Jake", "Team Charlie", "Team Batt"]
    teams.sort(key=lambda t: calc.team_sort_key("Bristol", t))
    assert teams == ["Team Batt", "Team Charlie", "Team Jake", ""]


def test_house_accounts_come_out_of_the_report():
    report = {
        "Bristol": {"type": "teams", "groups": [
            {"team": "Team Batt", "members": [{"name": "Jade Moger"}]},
            {"team": "", "members": [{"name": "Saragossa House Bristol"}]}]},
        "London": {"type": "flat", "members": [{"name": "Saragossa House London"},
                                               {"name": "Emily Hawkins"}]},
    }
    out = F._without_house_accounts(report)
    assert [g["team"] for g in out["Bristol"]["groups"]] == ["Team Batt"]
    assert [m["name"] for m in out["London"]["members"]] == ["Emily Hawkins"]
    # The shared report is left alone
    assert len(report["Bristol"]["groups"]) == 2


def test_team_lead_sees_the_team_set_in_settings_not_mercurys(monkeypatch):
    # Adam is still in Team Ryan in Mercury, but leads Team Adam B in the app
    ny = D.TERRITORY_IDS["New York"]
    people = [{"systemuserid": u, "fullname": u, "_territoryid_value": ny}
              for u in ("adam", "jack", "ryan", "peter")]
    monkeypatch.setattr(D, "get_all_territory_consultants", lambda: people)
    monkeypatch.setattr(D, "get_team_membership_map", lambda: {
        "adam": "Team Ryan", "jack": "Team Adam B", "ryan": "Team Ryan", "peter": "Team Ryan"})
    monkeypatch.setattr(D, "get_overrides", lambda: [
        {"crbb7_userid": "adam", "crbb7_team": "Team Adam B", "crbb7_isteamlead": True}])
    monkeypatch.setattr(D, "get_mbr_scopes", lambda: {})
    monkeypatch.setattr(D, "odata_get_all", lambda *a, **k: [people[0]])
    seen, _ = F._mbr_visible_people_all("adam@saragossa.io")
    assert sorted(p["systemuserid"] for p in seen) == ["adam", "jack"]


def test_the_chairman_ranks_as_a_director():
    assert D.is_director_title("Regional Director - Bristol")
    assert D.is_director_title("Chairman")
    assert not D.is_director_title("Chief Financial Officer")
    assert not D.is_director_title("Principal Consultant")


def test_mbr_people_drop_house_accounts_unless_a_director(monkeypatch):
    people = [{"fullname": "Saragossa House Bristol", "_territoryid_value": D.TERRITORY_IDS["Bristol"]},
              {"fullname": "Jade Moger", "_territoryid_value": D.TERRITORY_IDS["Bristol"]}]
    monkeypatch.setattr(F, "_mbr_visible_people_all", lambda e: (list(people), False))
    monkeypatch.setattr(D, "is_director", lambda e: e == "boss@saragossa.io")
    names = lambda e: [p["fullname"] for p in F._mbr_visible_people(e)[0]]
    assert names("harry@saragossa.io") == ["Jade Moger"]
    assert names("boss@saragossa.io") == ["Saragossa House Bristol", "Jade Moger"]
