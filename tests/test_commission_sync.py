"""Picking the right workbook out of a month folder, and when the sync runs."""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared.commission_import import month_from_filename  # noqa: E402
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


def test_the_folders_own_month_beats_a_stray_from_another():
    """The Apr-26 folder holds both 'Apr 26' and a leftover 'May 26'."""
    picked = pick_files([
        _f("Deploy & Component Summary - Apr 26.xlsx"),
        _f("Deploy & Component Summary - May 26.xlsx"),
    ], month=4)
    assert picked["chosen"]["solution"]["name"].endswith("Apr 26.xlsx")
    assert not picked["ambiguous"]


def test_actual_still_decides_once_the_month_matches():
    """Both May files name May, so the '- Actual' rule settles it."""
    picked = pick_files([
        _f("Deploy & Component Summary - May 26.xlsx"),
        _f("Deploy & Component Summary - May 26 - Actual.xlsx"),
    ], month=5)
    assert picked["chosen"]["solution"]["name"].endswith("- Actual.xlsx")


def test_a_lone_stray_is_not_promoted_by_the_month_rule():
    """
    With nothing named for this folder's month, the stray is still the only
    candidate — sync_year's conflict check is what rejects it, not this.
    """
    picked = pick_files([_f("Deploy & Component Summary - May 26.xlsx")], month=4)
    assert picked["chosen"]["solution"]["name"].endswith("May 26.xlsx")


def test_two_equal_candidates_are_reported_not_guessed():
    picked = pick_files([
        _f("Contract Commission - Jun 26.xlsx"),
        _f("Contract Commission Report - June 26.xlsx"),
    ])
    assert "contract" not in picked["chosen"]
    assert len(picked["ambiguous"]["contract"]) == 2


def test_a_filename_that_disagrees_with_its_folder_is_a_conflict():
    """
    The Apr-26 folder has held 'Deploy & Component Summary - May 26.xlsx', which
    really was May's data. Trusting the folder files May under April; trusting
    the name leaves April empty. sync_year must refuse rather than pick one.
    """
    assert folder_month("4. Apr-26") == 4
    assert month_from_filename("Deploy & Component Summary - May 26.xlsx") == (2026, 5)


@pytest.mark.parametrize("folder,filename", [
    ("3. Mar-26",    "Contract Commission - March 26.xlsx"),
    ("8. August-26", "Contract Commission Report - August 26.xlsx"),
    ("5. May-26",    "Deploy & Component Summary - May 26 - Actual.xlsx"),
    ("7. July-26",   "Deploy & Component Summary - July 26.xlsx"),
])
def test_finances_real_filenames_agree_with_their_folders(folder, filename):
    """Inconsistent naming is fine as long as it still resolves to the same month."""
    assert month_from_filename(filename)[1] == folder_month(folder)


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
