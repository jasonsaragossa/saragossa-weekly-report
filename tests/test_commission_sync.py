"""Picking the right workbook out of a month folder, and when the sync runs."""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared.commission_sync import folder_month, is_second_friday, pick_files  # noqa: E402


def _f(name):
    return {"name": name, "file": {}}


@pytest.mark.parametrize("folder,expected", [
    ("1. Jan-26", 1),
    ("3. Mar-26", 3),
    ("7. July-26", 7),
    ("8. August-26", 8),
    ("Illustrations", None),
])
def test_month_comes_from_the_folder_name(folder, expected):
    assert folder_month(folder) == expected


def test_one_file_of_each_kind_is_chosen():
    picked = pick_files([
        _f("Contract Commission - Jan 26.xlsx"),
        _f("Deploy & Component Summary - Jan 26.xlsx"),
        _f("TimesheetPortal-Report-202602051409.xls"),
        _f("US Commission Report - Jan 26.xlsx"),
    ])
    assert set(picked["chosen"]) == {"contract", "solution"}
    assert picked["chosen"]["contract"]["name"].startswith("Contract Commission")
    assert not picked["ambiguous"]


def test_actual_wins_over_the_earlier_draft():
    """The May folder holds both 'May 26' and 'May 26 - Actual'."""
    picked = pick_files([
        _f("Deploy & Component Summary - May 26.xlsx"),
        _f("Deploy & Component Summary - May 26 - Actual.xlsx"),
    ])
    assert picked["chosen"]["solution"]["name"].endswith("- Actual.xlsx")
    assert not picked["ambiguous"]


def test_two_equal_candidates_are_reported_not_guessed():
    picked = pick_files([
        _f("Contract Commission - Jun 26.xlsx"),
        _f("Contract Commission Report - June 26.xlsx"),
    ])
    assert "contract" not in picked["chosen"]
    assert len(picked["ambiguous"]["contract"]) == 2


def test_the_misfiled_month_takes_the_folders_month_not_the_filename():
    """The Apr-26 folder has held a file named 'May 26'; the folder decides."""
    picked = pick_files([_f("Deploy & Component Summary - May 26.xlsx")])
    assert picked["chosen"]["solution"]["name"].endswith("May 26.xlsx")
    assert folder_month("4. Apr-26") == 4


def test_folders_are_not_mistaken_for_files():
    picked = pick_files([{"name": "Contract Commission - old", "folder": {}}])
    assert not picked["chosen"]


@pytest.mark.parametrize("day,expected", [
    (date(2026, 9, 11), True),    # second Friday
    (date(2026, 9, 4),  False),   # first Friday
    (date(2026, 9, 18), False),   # third Friday
    (date(2026, 9, 10), False),   # Thursday
    (date(2026, 10, 9), True),
    (date(2026, 5, 8),  True),
])
def test_only_fires_on_the_second_friday(day, expected):
    assert is_second_friday(day) is expected
