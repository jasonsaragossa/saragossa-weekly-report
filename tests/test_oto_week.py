"""Which week a 1:1 opens on, and that nothing quietly overrides it."""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

JS = io.open(os.path.join(os.path.dirname(__file__), "..", "public", "121.js"),
             encoding="utf-8").read()


# ── The contract 1:1 opens on last week ───────────────────────────────────────

def test_the_contract_1_1_defaults_to_the_week_just_finished():
    """Jim's desk meets on a Monday, so a 1:1 opened with no week asked for
    shows the week that finished, not one a few hours old."""
    from datetime import date
    from shared.oneonone import default_week
    # Monday, mid-week and Sunday all land on the same finished week
    for today in (date(2026, 9, 21), date(2026, 9, 24), date(2026, 9, 27)):
        assert default_week("contract", today) == date(2026, 9, 14)


def test_the_perm_1_1_still_opens_on_the_current_week():
    from datetime import date
    from shared.oneonone import default_week
    assert default_week("perm", date(2026, 9, 24)) == date(2026, 9, 21)


def test_the_default_week_is_always_a_monday():
    from datetime import date, timedelta
    from shared.oneonone import default_week
    day = date(2026, 1, 1)
    for _ in range(400):
        for kind in ("contract", "perm"):
            assert default_week(kind, day).weekday() == 0
        day += timedelta(days=1)

# ── The page must not override the server's choice ────────────────────────────
# It used to: the picker was pre-filled with the CURRENT Monday and sent on
# every load, so the contract desk kept landing on a week a few hours old
# however the server was configured. Guard the shape of the fix.

def test_the_page_does_not_pre_fill_the_week_picker():
    assert 'document.getElementById("oto-week").value = monday' not in JS
    assert "const monday = new Date(d.setDate" not in JS


def test_the_first_load_asks_the_server_which_week():
    assert 'week ? `week=${encodeURIComponent(week)}` : ""' in JS


def test_the_picker_is_set_from_the_week_the_server_returned():
    assert 'if (d.week_start) document.getElementById("oto-week").value = d.week_start;' in JS
