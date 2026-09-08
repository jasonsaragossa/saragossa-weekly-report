"""
Ledger windows end at the newest month whose figures are actually in.

A month is paid, and entered, in the month after it, arriving on the second
Friday. Running one month behind regardless meant that in early September the
window took in an empty August while dropping August last year — eleven months
of data reported as twelve.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared.calc import (contract_manual_metrics,  # noqa: E402
                         last_complete_ledger_month, second_friday,
                         solution_manual_metrics)


@pytest.mark.parametrize("year,month,day", [
    (2026, 9, 11), (2026, 10, 9), (2026, 5, 8), (2026, 1, 9), (2026, 12, 11),
])
def test_second_friday(year, month, day):
    got = second_friday(year, month)
    assert got == date(year, month, day)
    assert got.weekday() == 4
    assert 8 <= got.day <= 14


@pytest.mark.parametrize("today,expected", [
    # Before September's second Friday (11th): August is not in yet.
    (date(2026, 9, 1),  (2026, 7)),
    (date(2026, 9, 8),  (2026, 7)),
    (date(2026, 9, 10), (2026, 7)),
    # On and after it, August is complete.
    (date(2026, 9, 11), (2026, 8)),
    (date(2026, 9, 30), (2026, 8)),
    # Year boundaries.
    (date(2026, 1, 5),  (2025, 11)),
    (date(2026, 1, 9),  (2025, 12)),
    (date(2026, 2, 3),  (2025, 12)),
])
def test_the_newest_complete_month(today, expected):
    assert last_complete_ledger_month(today) == expected


# 24 months, every one worth 100 — so a window's total is its month count.
LEDGER = {f"{y}-{m}": 100 for y in (2025, 2026) for m in range(1, 13)}


def test_the_rolling_year_keeps_twelve_real_months_before_the_second_friday():
    """This is the bug: August 26 empty and August 25 dropped left eleven."""
    early = dict(LEDGER)
    del early["2026-8"]                       # August not filed yet
    m = contract_manual_metrics(early, date(2026, 9, 8))
    assert m["contract_last12m"] == 1200      # Aug 25 .. Jul 26, all twelve
    assert m["rolling_3m"] == 300


def test_the_window_rolls_forward_on_the_second_friday():
    m = contract_manual_metrics(LEDGER, date(2026, 9, 11))
    assert m["contract_last12m"] == 1200      # Sep 25 .. Aug 26
    assert m["rolling_3m"] == 300             # Jun, Jul, Aug


def test_ytd_stops_at_the_newest_complete_month():
    before = contract_manual_metrics(LEDGER, date(2026, 9, 8))
    after  = contract_manual_metrics(LEDGER, date(2026, 9, 11))
    assert before["margin_ytd"] == 700        # Jan..Jul
    assert after["margin_ytd"] == 800         # Jan..Aug


def test_ytd_is_zero_when_no_month_of_this_year_is_complete():
    """Early January: the newest complete month is still last year."""
    assert contract_manual_metrics(LEDGER, date(2026, 1, 5))["margin_ytd"] == 0


def test_the_solution_ledger_uses_the_same_window():
    early = dict(LEDGER)
    del early["2026-8"]
    m = solution_manual_metrics(early, date(2026, 9, 8))
    assert m["solution_roll12"] == 1200
    assert m["solution_ytd"] == 700


@pytest.mark.parametrize("entries", [None, {}])
def test_empty_ledgers_stay_safe(entries):
    assert contract_manual_metrics(entries, date(2026, 9, 8)) == {
        "margin_ytd": 0, "contract_last12m": 0, "rolling_3m": 0}
