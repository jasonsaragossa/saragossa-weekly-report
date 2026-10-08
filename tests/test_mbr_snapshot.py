"""Month-end snapshots: each month frozen at 23:59 London time on its last day."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from shared import mbr_contract as M
from shared import mbr_snapshot as S
from test_mbr_contract import A, data, pl

UTC = ZoneInfo("UTC")


def at(s):
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def test_due_at_2359_london_on_the_last_day():
    # 30 Sep is in British Summer Time: 23:59 London is 22:59 UTC
    assert S.month_due(at("2026-09-30T22:59:00")) == (2026, 9, False)
    assert S.month_due(at("2026-09-30T22:58:00")) is None          # a minute early
    assert S.month_due(at("2026-09-29T22:59:00")) is None          # not the last day
    # 31 Dec is GMT: 23:59 London is 23:59 UTC
    assert S.month_due(at("2026-12-31T23:59:00")) == (2026, 12, False)


def test_a_missed_2359_is_caught_up_marked_late_then_given_up():
    assert S.month_due(at("2026-10-01T02:00:00")) == (2026, 9, True)      # 03:00 London
    assert S.month_due(at("2026-10-01T06:00:00")) is None                 # too late to call month end
    assert S.month_due(at("2027-01-01T00:30:00")) == (2026, 12, True)     # across the year


def test_a_frozen_month_ignores_what_mercury_did_afterwards():
    contract = pl("p1", "001/00/01", "2026-01-05", "2026-12-31", roles=(A, A, A), wgp=500.0)
    before = data(placements=[contract])
    raw_at_month_end = M.compute({A}, 2026, 3, before, before["fx"], None, None)

    # Since then the contract was cancelled in Mercury
    after = data(placements=[{**contract, "statuscode": 939310015}])
    live = M.build_view("London Contract", 2026, A, {}, today=date(2026, 4, 15), data=after)
    frozen = M.build_view("London Contract", 2026, A, {}, today=date(2026, 4, 15), data=after,
                          snapshots={3: {"raw": raw_at_month_end, "taken_at": "2026-03-31T23:59:00+01:00"}})

    assert live["values"]["P3"]["runners"] == 0                 # live: it's gone
    assert frozen["values"]["P3"]["runners"] == 1               # month end: as it stood
    assert frozen["values"]["P3"]["wgp_running"] == 500
    assert frozen["values"]["P2"]["runners"] == 0               # unfrozen months stay live
    assert set(frozen["frozen"]) == {"P3"}


def test_typed_figures_stay_editable_in_a_frozen_month():
    d = data(placements=[])
    raw = M.compute({A}, 2026, 3, d, d["fx"], None, None)
    out = M.build_view("London Contract", 2026, "team", {"gp_month:2026-03": 250000},
                       today=date(2026, 4, 15), data=d,
                       snapshots={3: {"raw": raw, "taken_at": "2026-03-31T23:59:00+01:00"}})
    assert out["values"]["P3"]["gp_month"] == 250000


def test_taking_a_snapshot_stores_the_team_and_every_consultant(monkeypatch):
    stored = []
    monkeypatch.setattr(M, "fetch_year", lambda desk, year, today: data(
        placements=[pl("p1", "001/00/01", "2026-01-05", "2026-12-31")]))
    monkeypatch.setattr(S, "_store", lambda desk, view, y, m, payload: stored.append((view, payload)))
    out = S.take("London Contract", 2026, 9, now_utc=at("2026-09-30T22:59:00"))
    assert out["views"] == 3 and [v for v, _ in stored] == ["team", "alice", "bob"]
    team = stored[0][1]
    assert team["taken_at"] == "2026-09-30T23:59:00+01:00" and not team["late"]
    assert team["raw"]["runners"] == 1


def test_run_due_leaves_a_frozen_month_alone(monkeypatch):
    taken = []
    monkeypatch.setattr(S, "exists", lambda desk, y, m: True)
    monkeypatch.setattr(S, "take", lambda *a, **k: taken.append(a))
    assert S.run_due(at("2026-09-30T22:59:00")) == [] and taken == []
    assert S.run_due(at("2026-09-15T12:00:00")) == []
