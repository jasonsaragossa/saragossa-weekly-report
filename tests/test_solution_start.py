"""
Deploy & Consult only counts toward PERM consultants' figures from April 2026.

Contract desks are unaffected — it has always been part of their margin.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared.calc import (SOLUTION_PERM_START, solution_manual_metrics,  # noqa: E402
                         solution_quarters, solution_year_total)

# A full year in the ledger, straddling the April start. Today is 7 Sep 2026,
# and the ledger runs a month behind, so every window ends with August.
TODAY = date(2026, 9, 7)
LEDGER = {
    "2025-10": 500, "2025-11": 500, "2025-12": 500,
    "2026-1": 1000, "2026-2": 1000, "2026-3": 1000,   # before the start
    "2026-4": 2000, "2026-5": 2000, "2026-6": 2000,   # from the start
    "2026-7": 3000, "2026-8": 3000,
    "2026-9": 9999,                                    # current month — excluded
}
BEFORE = 3000     # Jan-Mar 2026
AFTER  = 12000    # Apr-Aug 2026


def test_the_start_is_april_2026():
    assert SOLUTION_PERM_START == (2026, 4)


def test_perm_ytd_starts_at_april():
    m = solution_manual_metrics(LEDGER, TODAY, since_start=True)
    assert m["solution_ytd"] == AFTER


def test_contract_ytd_keeps_the_whole_year():
    m = solution_manual_metrics(LEDGER, TODAY, since_start=False)
    assert m["solution_ytd"] == BEFORE + AFTER


def test_perm_rolling_12m_drops_the_months_before_april():
    """The window reaches back to Sep 25, but nothing before April counts."""
    m = solution_manual_metrics(LEDGER, TODAY, since_start=True)
    assert m["solution_roll12"] == AFTER


def test_contract_rolling_12m_includes_last_year():
    m = solution_manual_metrics(LEDGER, TODAY, since_start=False)
    assert m["solution_roll12"] == BEFORE + AFTER + 1500   # + Oct-Dec 25


def test_hpb_quarters_only_count_from_april():
    """HPB is a perm bonus, so Q1 contributes nothing."""
    q = solution_quarters(LEDGER, 2026)
    assert q["1"] == 0
    assert q["2"] == 6000        # Apr+May+Jun
    assert q["3"] == 15999       # Jul+Aug+Sep
    assert q["4"] == 0


def test_hpb_quarters_can_still_be_asked_for_the_whole_year():
    q = solution_quarters(LEDGER, 2026, since_start=False)
    assert q["1"] == 3000


def test_the_analytics_column_still_reports_everything_booked():
    """
    Solution Revenue on Analytics is a report of what was booked, kept out of
    perm written totals and budgets — so it is not cut off at April.
    """
    assert solution_year_total(LEDGER, 2026) == BEFORE + AFTER + 9999


@pytest.mark.parametrize("entries", [None, {}])
def test_an_empty_ledger_is_safe(entries):
    m = solution_manual_metrics(entries, TODAY, since_start=True)
    assert m == {"solution_ytd": 0, "solution_roll12": 0}
