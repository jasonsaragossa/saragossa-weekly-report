"""
A contract extension is the same win continuing, not new business.

Extensions inherit their parent's "New Business" note in Mercury, and the
uplift used to be paid on them again — e.g. STRYDER CISO 004749/00/06 then
its extension 004749/01/00. Modelled on those two real records (Sep 2026).
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared.calc import compute_metrics  # noqa: E402

CRO = "flynn"
TODAY = date(2026, 9, 29)


def contract(code, start, gp, **over):
    p = {
        "crimson_placementid": code,
        "crimson_name": "CISO",
        "crimson_type": 143570001,
        "crimson_startdate": start,
        "crimson_placementidcode": code,
        "crimson_extension": 0,
        "recruit_truegrossprofit": gp,
        "recruit_truegrossprofitcurrency": {"isocurrencycode": "GBP"},
        "mercury_marginpercent": 20.0,
        "recruit_weeklymarginvalue_mc": 1250.0,
        "crimson_specialinstructionsclient": "New Business",
        "crimson_clientname": {"name": "STRYDER"},
        "_crimson_clientname_value": "stryder",
        "_mercury_clientrelationshipowner_value": CRO,
        "_crimson_consultant_value": CRO,
        "_mercury_assignmentowner_value": CRO,
    }
    p.update(over)
    return p


ORIGINAL = contract("004749/00/06", "2026-06-15", 12000.0)
EXTENSION = contract("004749/01/00", "2026-09-17", 16500.0, crimson_extension=1)


def metrics(contracts):
    return compute_metrics(CRO, [], "GBP", TODAY, contract_placements=contracts)


def test_the_original_contract_earns_the_uplift():
    m = metrics([ORIGINAL])
    assert m["roll12_uplift"] == pytest.approx(12000 * 0.5)
    assert m["nb_clients"] == 1


def test_the_extension_earns_no_second_uplift():
    m = metrics([ORIGINAL, EXTENSION])
    assert m["roll12_uplift"] == pytest.approx(12000 * 0.5)     # not + 16,500 × 0.5


def test_the_client_still_counts_once():
    assert metrics([ORIGINAL, EXTENSION])["nb_clients"] == 1


@pytest.mark.parametrize("how", [
    {"crimson_extension": 1},                                   # the counter
    {"crimson_placementidcode": "004749/01/00"},                # the id code alone
    {"_mercury_parentplacementid_value": "parent-guid"},        # the parent link
])
def test_every_way_mercury_marks_an_extension_is_caught(how):
    """Neither real extension has its parent link set — the counter and the
    id code are what identify them, so all three routes must work."""
    ext = contract("x", "2026-09-17", 16500.0, crimson_placementidcode="004749/00/00")
    ext.update(how)
    assert metrics([ext])["roll12_uplift"] == 0


def test_an_original_whose_code_ends_non_zero_is_not_an_extension():
    """Real originals are coded 004749/00/06 — the LAST segment isn't the
    extension counter, the middle one is."""
    assert metrics([ORIGINAL])["roll12_uplift"] > 0


def test_an_extension_alone_does_not_make_an_old_client_new():
    """If the original has rolled out of the year, its extension must not
    keep the client counting as a new-business win."""
    m = metrics([EXTENSION])
    assert m["nb_clients"] == 0 and m["roll12_uplift"] == 0
