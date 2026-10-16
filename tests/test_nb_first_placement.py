"""
A new-business client counts only from its FIRST New Business placement
(Jason, Oct 2026). Charlie places with client X in Sep 2025 and again in Nov
2025: only September wins the client, so once September rolls out of the
twelve months, X stops counting — November doesn't win it again. The 50%
uplift still pays on every qualifying NB placement.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared.calc import compute_metrics, first_nb_wins, nb_win_counts  # noqa: E402

CHARLIE, EMMA = "charlie", "emma"
TODAY = date(2026, 10, 16)                  # window: 17 Oct 2025 – 16 Oct 2026


def perm(pid, start, client="x", cro=CHARLIE, **over):
    p = {"crimson_placementid": pid, "crimson_name": "Quant", "crimson_type": 143570000,
         "crimson_startdate": start, "recruit_truegrossprofit": 30000.0,
         "recruit_truegrossprofitcurrency": {"isocurrencycode": "GBP"},
         "crimson_permanentfeepercent": 25.0,
         "crimson_specialinstructionsclient": "New Business",
         "crimson_clientname": {"name": client.upper()}, "_crimson_clientname_value": client,
         "_mercury_clientrelationshipowner_value": cro, "_crimson_consultant_value": cro,
         "_mercury_assignmentowner_value": cro}
    p.update(over)
    return p


def metrics(placements, uid=CHARLIE):
    return compute_metrics(uid, placements, "GBP", TODAY, first_nb=first_nb_wins(placements))


def test_a_later_nb_placement_does_not_win_the_client_again():
    sep, nov = perm("a", "2025-09-10"), perm("b", "2025-11-03")
    m = metrics([sep, nov])
    assert m["nb_clients"] == 0                                 # September has rolled out
    assert m["roll12_uplift"] == pytest.approx(30000 * 0.5)     # November still earns its uplift


def test_the_first_nb_placement_in_the_window_wins_the_client():
    m = metrics([perm("a", "2026-02-01"), perm("b", "2026-06-01")])
    assert m["nb_clients"] == 1


def test_a_client_someone_else_won_first_is_not_won_again():
    m = metrics([perm("a", "2026-03-01", cro=EMMA), perm("b", "2026-05-01")])
    assert m["nb_clients"] == 0
    assert metrics([perm("a", "2026-03-01", cro=EMMA), perm("b", "2026-05-01")], uid=EMMA)["nb_clients"] == 1


def test_two_firsts_on_the_same_day_both_count_for_their_own_cros():
    rows = [perm("a", "2026-03-01"), perm("b", "2026-03-01", cro=EMMA)]
    assert metrics(rows)["nb_clients"] == 1 and metrics(rows, uid=EMMA)["nb_clients"] == 1


def test_a_contract_extension_is_never_the_first_win():
    ext = perm("e", "2025-08-01", crimson_type=143570001, crimson_extension=1)
    first = first_nb_wins([ext, perm("a", "2026-01-05")])
    assert first["x"][0] == date(2026, 1, 5)


def test_without_the_lookup_every_nb_placement_counts_as_before():
    assert nb_win_counts(None, "x", CHARLIE, "2025-11-03")
    m = compute_metrics(CHARLIE, [perm("a", "2025-09-10"), perm("b", "2025-11-03")], "GBP", TODAY)
    assert m["nb_clients"] == 1
