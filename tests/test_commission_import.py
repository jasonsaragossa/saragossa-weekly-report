"""Parsing finance's monthly commission workbooks."""
import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from shared.commission_import import (  # noqa: E402
    NO_CONSULTANT, match_to_users, month_from_filename, normalise_name, parse_workbook)

openpyxl = pytest.importorskip("openpyxl")

CONTRACT_HEADER = ["Consultant", "Consultant Label", "Client", "Contractor", "Period End",
                   "Units", "Bill Amount", "Pay Amount", "Currency Margin", "Margin %",
                   "Per Day", "Split %", "Commission", "Contribution"]
DEPLOY_HEADER = ["Consultant", "Consultant Label", "Client", "Invoice", "Consultant",
                 "Month", "Bill Amount", "Pay Amount", "Margin", "Margin %", "Split",
                 "Split %", "Commission", "Contribution"]


def _book(sheets: dict) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _contract_row(name, contribution):
    return [name, "Client Owner", "AWP", "A Contractor", "04/01/2026", 28,
            5040, 3360, 1680, 0.33, 60, 0.15, 252, contribution]


def _deploy_row(owner, contractor, contribution):
    return [owner, "Client Owner", "Softbank", "", contractor, "2026-01-01",
            12812, 6270, 6541, 0.51, "", 0.05, contribution / 5, contribution]


def test_contract_sums_a_consultants_rows():
    data = _book({"Commission Report": [
        CONTRACT_HEADER,
        _contract_row("Phin Smith", 1000.0),
        _contract_row("Phin Smith", 500.5),
        _contract_row("Clara Rapley", 200.0),
    ]})
    out = parse_workbook(data)
    assert out["kind"] == "contract"
    assert out["totals"] == {"Phin Smith": 1500.5, "Clara Rapley": 200.0}
    assert out["rows"] == 3


def test_territory_sheets_are_not_double_counted():
    """They are slices of the master sheet, so only the master is read."""
    rows = [CONTRACT_HEADER, _contract_row("Phin Smith", 1000.0)]
    out = parse_workbook(_book({"Commission Report": rows, "Chicago Contract": rows}))
    assert out["totals"] == {"Phin Smith": 1000.0}
    assert out["sheets_skipped"] == ["Chicago Contract"]


def test_deploy_reads_repeated_headers_and_credits_the_owner():
    """Each consultant's block repeats the header; column 5 is the contractor."""
    data = _book({"Deploy & Component": [
        DEPLOY_HEADER,
        ["January Commission"],
        _deploy_row("Jake Cogzell", "Vasileios Macharidis", 1635.47),
        [],
        DEPLOY_HEADER,
        ["January Commission"],
        _deploy_row("Jono Paisley", "Jacob Ramroop", 1043.21),
    ]})
    out = parse_workbook(data)
    assert out["kind"] == "solution"
    assert out["totals"] == {"Jake Cogzell": 1635.47, "Jono Paisley": 1043.21}


def test_uk_and_us_deploy_sheets_are_combined():
    out = parse_workbook(_book({
        "Deploy & Component":    [DEPLOY_HEADER, _deploy_row("Adam Woolley", "X", 100.0)],
        "Deploy & Component US": [DEPLOY_HEADER, _deploy_row("Adam Woolley", "Y", 430.41)],
    }))
    assert out["totals"] == {"Adam Woolley": 530.41}


def test_a_contract_row_with_no_owner_is_kept_and_labelled():
    """The contract sheet carries rows whose consultant cell is a single space."""
    out = parse_workbook(_book({"Commission Report": [
        CONTRACT_HEADER, _contract_row(" ", 559.44), _contract_row(None, 10.0)]}))
    assert out["totals"] == {NO_CONSULTANT: 569.44}


def test_deploy_block_subtotals_are_not_counted_as_rows():
    """
    Each deploy block closes with a 'Commission Payable' line repeating the
    block's contribution against a blank consultant. Counting those doubles
    the workbook, so on the deploy sheets a blank owner is skipped.
    """
    subtotal = ["", "", "", "", "", "", "", "", "", "", "Commission Payable", "", 200.0, 1000.0]
    unlabelled = ["", "", "", "", "", "", "", "", "", "", "", "", 200.0, 1000.0]
    out = parse_workbook(_book({"Deploy & Component": [
        DEPLOY_HEADER,
        ["January Commission"],
        _deploy_row("Jake Cogzell", "V M", 1000.0),
        subtotal,
        unlabelled,
    ]}))
    assert out["totals"] == {"Jake Cogzell": 1000.0}


def test_unknown_workbook_is_rejected():
    with pytest.raises(ValueError, match="Unrecognised workbook"):
        parse_workbook(_book({"Balance Sheet": [["a", "b"], [1, 2]]}))


def test_a_workbook_with_no_figures_is_rejected():
    with pytest.raises(ValueError, match="No Contribution figures"):
        parse_workbook(_book({"Commission Report": [CONTRACT_HEADER]}))


@pytest.mark.parametrize("filename,expected", [
    ("Contract Commission - Jan 26.xlsx", (2026, 1)),
    ("Deploy & Component Summary - Jan 26.xlsx", (2026, 1)),
    ("Contract Commission - Dec 25.xlsx", (2025, 12)),
    ("contract commission september 2025.xlsx", (2025, 9)),
    ("Contract Commission.xlsx", None),
])
def test_month_comes_from_the_filename(filename, expected):
    assert month_from_filename(filename) == expected


def test_names_match_through_punctuation_and_spacing():
    assert normalise_name("Liam Mustoe- Linnane") == normalise_name("Liam Mustoe-Linnane")


USERS = [
    {"systemuserid": "u1", "fullname": "Phin Smith", "isdisabled": False},
    {"systemuserid": "u2", "fullname": "Jono Paisley", "isdisabled": True},
]


def test_leavers_still_get_their_contribution():
    m = match_to_users({"Jono Paisley": 1043.21}, USERS)
    assert m["matched"] == [{"uid": "u2", "name": "Jono Paisley",
                             "sheet_name": "Jono Paisley", "amount": 1043.21,
                             "disabled": True}]


def test_a_name_with_no_mercury_user_is_reported_not_dropped():
    m = match_to_users({"Phin Smith": 10.0, "Ex Employee": 1754.91}, USERS)
    assert [r["uid"] for r in m["matched"]] == ["u1"]
    assert m["unmatched"] == [{"name": "Ex Employee", "amount": 1754.91}]


def test_an_active_account_wins_over_a_disabled_namesake():
    users = [{"systemuserid": "old", "fullname": "Jamie Smith", "isdisabled": True},
             {"systemuserid": "new", "fullname": "Jamie Smith", "isdisabled": False}]
    for order in (users, list(reversed(users))):
        m = match_to_users({"Jamie Smith": 1.0}, order)
        assert m["matched"][0]["uid"] == "new"
