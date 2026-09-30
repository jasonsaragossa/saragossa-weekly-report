"""Performance Stats → Clients: "Clients w/ Multiple Potential" (Jim, Sep 2026)
lists the clients with exactly one runner live now."""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared import perfstats as P  # noqa: E402

TODAY = date(2026, 9, 30)
DESK = {"connor"}


def run(pid, code, client, role, start="2026-06-01", end="2027-03-01"):
    return {"crimson_placementid": pid, "crimson_placementidcode": code, "crimson_name": role,
            "crimson_startdate": start + "T00:00:00", "crimson_enddate": end + "T00:00:00",
            "crimson_actualenddate": None, "_crimson_clientname_value": client,
            "crimson_clientname": {"name": client.title()},
            "_crimson_consultant_value": "connor", "_mercury_assignmentowner_value": "connor",
            "recruit_trueweeklygrossprofit": 500.0, "mercury_marginpercent": 20.0,
            "mercury_hoursperweek": 40, "recruit_trueweeklygrossprofitcurrency": {"isocurrencycode": "USD"}}


@pytest.fixture
def desk(monkeypatch):
    def with_placements(rows):
        monkeypatch.setattr(P, "_desk_user_ids", lambda: DESK)
        monkeypatch.setattr(P, "_contract_placements", lambda since: rows)
        monkeypatch.setattr(P, "_shortlists_for_desk", lambda *a, **k: [])
        monkeypatch.setattr(P, "_activities", lambda *a, **k: [])
        monkeypatch.setattr(P, "_vacancies", lambda *a, **k: [])
        monkeypatch.setattr(P, "get_fx_rates", lambda: None)
        return P.build_performance_stats(TODAY)["clients_single_runner"]
    return with_placements


def test_only_clients_with_exactly_one_runner_are_listed(desk):
    got = desk([
        run("a", "001/00/01", "acme", "DBA"),
        run("b", "002/00/01", "globex", "PM"), run("c", "003/00/01", "globex", "BA"),
        run("d", "004/00/01", "initech", "Dev"),
    ])
    assert got == [{"client": "Acme", "role": "DBA"}, {"client": "Initech", "role": "Dev"}]


def test_a_contract_and_its_overlapping_extension_are_one_runner(desk):
    """Counted as records, this client would have 'two runners' and vanish
    from a list about having only one."""
    got = desk([run("o", "005/00/01", "umbrella", "DBA", end="2026-10-31"),
                run("e", "005/01/00", "umbrella", "DBA", start="2026-09-28")])
    assert got == [{"client": "Umbrella", "role": "DBA"}]


def test_runners_that_have_finished_do_not_count(desk):
    got = desk([run("x", "006/00/01", "hooli", "Dev"),
                run("y", "007/00/01", "hooli", "QA", end="2026-08-31")])
    assert got == [{"client": "Hooli", "role": "Dev"}]


def test_listed_alphabetically(desk):
    got = desk([run("z", "008/00/01", "zeta", "A"), run("b", "009/00/01", "beta", "B")])
    assert [c["client"] for c in got] == ["Beta", "Zeta"]


def test_the_page_uses_the_new_headline():
    js = open(os.path.join(os.path.dirname(__file__), "..", "public", "performance.js"),
              encoding="utf-8").read()
    assert "Clients w/ Multiple Potential" in js
    assert "clients_multi_runners" not in js
