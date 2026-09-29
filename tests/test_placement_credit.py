"""Ownership credit: 0.5 Consultant + 0.5 AO on a 3-way deal, 0.25 each on a 4-way (CONRO) deal."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared.calc import placement_credit, placement_credit_slots, split_factor  # noqa: E402


def deal(con="c", ao="a", cro="r", conro=None):
    return {"_crimson_consultant_value": con, "_mercury_assignmentowner_value": ao,
            "_mercury_clientrelationshipowner_value": cro,
            "_mercury_contractorrelationship_userid_value": conro}


def test_three_way_credit_and_money():
    p = deal()
    assert [placement_credit(p, u) for u in "car"] == [0.5, 0.5, 0.0]
    assert [split_factor(p, u) for u in "car"] == pytest.approx([1 / 3] * 3)


def test_four_way_credit_and_money():
    p = deal(conro="n")
    assert [placement_credit(p, u) for u in "carn"] == [0.25] * 4
    assert [split_factor(p, u) for u in "carn"] == [0.25] * 4


def test_one_person_holding_two_roles_gets_both_shares():
    assert placement_credit(deal(con="x", ao="x"), "x") == 1.0
    assert placement_credit(deal(con="x", cro="x", conro="n"), "x") == 0.5


def test_credit_always_sums_to_one_placement():
    for p in (deal(), deal(conro="n")):
        assert sum(placement_credit_slots(p).values()) == 1.0
