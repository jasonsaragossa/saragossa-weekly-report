"""The five-minute memory for staff lists."""
from shared import dataverse as D


def counter():
    calls = {"n": 0}

    @D.ttl_cached(300)
    def fetch(*args):
        calls["n"] += 1
        return [{"name": "Junaid", "args": list(args)}]
    return fetch, calls


def test_a_second_ask_inside_the_window_doesnt_go_back_to_mercury():
    fetch, calls = counter()
    fetch(); fetch(); fetch()
    assert calls["n"] == 1


def test_each_caller_gets_its_own_copy():
    """A page that edits the list it was handed can't change anyone else's."""
    fetch, _ = counter()
    first = fetch()
    first[0]["name"] = "changed"
    first.append({"name": "extra"})
    assert fetch() == [{"name": "Junaid", "args": []}]


def test_it_expires(monkeypatch):
    fetch, calls = counter()
    now = [1000.0]
    monkeypatch.setattr(D._time, "time", lambda: now[0])
    fetch()
    now[0] += 299
    fetch()
    assert calls["n"] == 1
    now[0] += 2                      # past five minutes
    fetch()
    assert calls["n"] == 2


def test_different_arguments_are_remembered_separately():
    fetch, calls = counter()
    assert fetch("London Contract")[0]["args"] == ["London Contract"]
    assert fetch("Chicago Contract")[0]["args"] == ["Chicago Contract"]
    assert calls["n"] == 2


def test_settings_data_is_not_cached():
    """Overrides and MBR grants are edited in the app — a change must show at once."""
    assert not hasattr(D.get_overrides, "__wrapped__")
    assert not hasattr(D.get_mbr_scopes, "__wrapped__")
    assert hasattr(D.get_all_territory_consultants, "__wrapped__")
    assert hasattr(D.get_team_membership_map, "__wrapped__")
