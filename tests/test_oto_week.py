"""Which week a 1:1 opens on, and that nothing quietly overrides it."""
import io

import pytest
from datetime import date
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

JS = io.open(os.path.join(os.path.dirname(__file__), "..", "public", "121.js"),
             encoding="utf-8").read()


# ── The contract 1:1 opens on last week ───────────────────────────────────────

# From Thursday every 1:1 opens on the one for NEXT Monday's meeting. Week of
# Mon 28 Sep 2026 → Sun 4 Oct; the next meeting after it is Mon 5 Oct.
WEEK_OF_28_SEP = {
    "Mon": date(2026, 9, 28), "Tue": date(2026, 9, 29), "Wed": date(2026, 9, 30),
    "Thu": date(2026, 10, 1), "Fri": date(2026, 10, 2), "Sat": date(2026, 10, 3),
    "Sun": date(2026, 10, 4),
}


@pytest.mark.parametrize("day,expected", [
    ("Mon", "2026-09-21"), ("Tue", "2026-09-21"), ("Wed", "2026-09-21"),
    ("Thu", "2026-09-28"), ("Fri", "2026-09-28"), ("Sat", "2026-09-28"),
    ("Sun", "2026-09-28"),
])
def test_contract_usa_rolls_forward_on_thursday(day, expected):
    """Mon–Wed: the week being reviewed. Thu on: this week, reviewed next Monday."""
    from shared.oneonone import default_week
    assert default_week("contract", WEEK_OF_28_SEP[day]).isoformat() == expected


@pytest.mark.parametrize("day,expected", [
    ("Mon", "2026-09-28"), ("Tue", "2026-09-28"), ("Wed", "2026-09-28"),
    ("Thu", "2026-10-05"), ("Fri", "2026-10-05"), ("Sat", "2026-10-05"),
    ("Sun", "2026-10-05"),
])
def test_team_snoz_rolls_forward_on_thursday(day, expected):
    """Snoz files a 1:1 under the week it happens in, so from Thursday it opens
    on next week's."""
    from shared.oneonone import default_week
    assert default_week("perm", WEEK_OF_28_SEP[day]).isoformat() == expected


def test_both_teams_open_on_the_same_meeting():
    """Whatever week each files it under, it is always next Monday's 1:1 —
    contract one week behind perm."""
    from datetime import timedelta
    from shared.oneonone import default_week
    for d in WEEK_OF_28_SEP.values():
        assert default_week("contract", d) == default_week("perm", d) - timedelta(days=7)


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


# ── Dates, the ladder and the week review on the page ─────────────────────────

def test_no_date_is_hard_coded_to_a_uk_locale_any_more():
    """Every date on the page goes through the team's locale, so the US desk
    reads 9/14/2026 rather than 14/09/2026."""
    import re
    # The only en-GB left should be the fallback default and the response read
    leftovers = [ln.strip() for ln in JS.splitlines()
                 if 'toLocaleDateString("en-GB"' in ln or 'toLocaleTimeString("en-GB"' in ln]
    assert leftovers == []


def test_the_page_takes_its_locale_from_the_template():
    assert 'OTO_LOCALE = d.locale || "en-GB";' in JS
    assert "function fmtDate(" in JS


def test_the_ladder_lights_only_the_matched_rung():
    assert 'const at = rungs.indexOf((d.person || {}).rung);' in JS
    assert 'i < at ? "done" : i === at ? "now" : "todo"' in JS


def _body(name):
    """The source of one top-level function in 121.js, up to the next one."""
    start = JS.index(f"function {name}(")
    ends = [i for i in (JS.find("\nfunction ", start + 1),
                        JS.find("\nasync function ", start + 1)) if i != -1]
    return JS[start:min(ends)] if ends else JS[start:]


def test_the_week_review_is_on_the_contract_page():
    """It was once added to Team Snoz's page by mistake, and the contract
    save then failed on the missing boxes. Placement, not presence."""
    assert 'id="f-week_consultant"' in _body("renderContract")
    assert 'id="f-week_manager"' in _body("renderContract")


def test_team_snoz_does_not_get_the_week_review():
    assert "f-week_consultant" not in _body("renderPerm")
    assert "f-week_manager" not in _body("renderPerm")
    assert "week_consultant" not in _body("savePerm")


def test_the_week_review_sits_just_above_the_actions():
    body = _body("renderContract")
    assert body.index("How did ") < body.index("Actions from this 1:1")


def test_every_field_the_contract_save_reads_is_on_the_contract_page():
    """A save that reads a box the page never drew throws, and nothing saves."""
    import re
    save, page = _body("saveContract"), _body("renderContract")
    for field in re.findall(r'getElementById\("(f-[a-z_]+)"\)', save):
        # Drawn literally, or by the activity section's typed-figure helpers
        assert (f'id="{field}"' in page or f'typedRow("{field[2:]}"' in page
                or f'numBox("{field}"' in page), field


def test_the_week_strip_follows_the_desk_locale():
    """The dates you see first. It was hand-built as day/month for everyone."""
    assert "${dt.getDate()}/${dt.getMonth() + 1}</button>" not in JS
    # The contract desk's strip names a 1:1 by the Monday it's held (Oct 2026)
    assert "${shortDay(heldMonday ? held : dt)}</button>" in JS


def test_team_snoz_week_strip_is_exactly_as_it_was():
    """UK desk keeps 14/9 — the locale formatter would have padded it to 14/09."""
    body = _body("shortDay")
    assert "`${dt.getDate()}/${dt.getMonth() + 1}`" in body


def test_the_week_review_is_saved_from_both_boxes():
    assert 'week_consultant: document.getElementById("f-week_consultant").value' in JS
    assert 'week_manager: document.getElementById("f-week_manager").value' in JS


def test_runners_card_is_on_the_contract_page_only():
    assert "Runners out" in _body("renderContract")
    assert "Runners out" not in _body("renderPerm")


def test_runners_card_sits_in_key_figures():
    body = _body("renderContract")
    assert body.index("<h2>Key figures</h2>") < body.index("Runners out") \
        < body.index("Committed business")


# ── Contract USA starts at w/c 21 Sep 2026 ────────────────────────────────────

def test_the_strip_shows_nothing_before_the_start_week():
    from datetime import date
    from shared.oneonone import quarter_weeks
    q = quarter_weeks(date(2026, 9, 21), since=date(2026, 9, 21))
    assert q["weeks"] == ["2026-09-21"]
    assert q["prev"] is None                      # nowhere earlier to go


def test_the_strip_grows_week_by_week_from_the_start():
    from datetime import date
    from shared.oneonone import quarter_weeks
    q = quarter_weeks(date(2026, 10, 12), since=date(2026, 9, 21))
    assert q["weeks"] == ["2026-09-21", "2026-09-28", "2026-10-05", "2026-10-12"]
    assert q["prev"] is None


def test_once_the_desk_has_more_than_13_weeks_it_can_page_back_to_the_start():
    from datetime import date
    from shared.oneonone import quarter_weeks
    q = quarter_weeks(date(2027, 1, 4), since=date(2026, 9, 21))
    assert len(q["weeks"]) == 13 and q["weeks"][0] == "2026-10-12"
    # Paging back lands on the page ending 5 Oct, which starts at 21 Sep and
    # goes no further
    back = quarter_weeks(date.fromisoformat(q["prev"]), since=date(2026, 9, 21))
    assert back["weeks"] == ["2026-09-21", "2026-09-28", "2026-10-05"]
    assert back["prev"] is None


def test_team_snoz_keeps_its_full_history():
    from datetime import date
    from shared.oneonone import quarter_weeks
    q = quarter_weeks(date(2026, 9, 21))
    assert len(q["weeks"]) == 13 and q["prev"] == "2026-06-22"


def test_contract_usa_starts_on_21_sep_and_snoz_has_no_start():
    from shared.oto_templates import TEMPLATES
    assert TEMPLATES["contract_usa"]["start_week"] == "2026-09-21"
    assert "start_week" not in TEMPLATES["snoz"]


def test_the_back_arrow_is_disabled_at_the_start():
    assert "disabled title=\"1:1s started here\"" in _body("quarterStrip")


# ── Nobody sees into the future ───────────────────────────────────────────────
# The latest reachable 1:1 is the one currently open — the upcoming one only
# from the Thursday before it (Jason, Sep 2026).

def test_the_strip_cannot_page_past_the_open_1_1():
    from shared.oneonone import quarter_weeks
    q = quarter_weeks(date(2026, 9, 28), until=date(2026, 9, 28))
    assert q["next"] is None


def test_from_an_older_page_next_stops_at_the_open_1_1():
    from shared.oneonone import quarter_weeks
    q = quarter_weeks(date(2026, 6, 1), until=date(2026, 9, 28))
    assert q["next"] == "2026-08-31"                 # a normal page on…
    q = quarter_weeks(date(2026, 8, 31), until=date(2026, 9, 28))
    assert q["next"] == "2026-09-28"                 # …but never beyond the open one


def test_on_wednesday_next_weeks_snoz_1_1_is_not_reachable():
    from shared.oneonone import default_week, quarter_weeks
    wed = WEEK_OF_28_SEP["Wed"]
    latest = default_week("perm", wed)
    assert latest == date(2026, 9, 28)
    assert quarter_weeks(latest, until=latest)["next"] is None


def test_on_thursday_it_opens_and_is_the_furthest_you_can_go():
    from shared.oneonone import default_week, quarter_weeks
    thu = WEEK_OF_28_SEP["Thu"]
    for kind, opens in (("perm", date(2026, 10, 5)), ("contract", date(2026, 9, 28))):
        latest = default_week(kind, thu)
        assert latest == opens
        assert quarter_weeks(latest, until=latest)["next"] is None


def test_the_server_caps_every_request_at_the_open_1_1():
    """View and save alike: the week is capped before the save branch runs."""
    src = io.open(os.path.join(os.path.dirname(__file__), "..", "api", "function_app.py"),
                  encoding="utf-8").read()
    body = src[src.index("def one_to_one("):]
    body = body[:body.index("@app.route")]
    cap = body.index("if wk > latest:")
    assert "wk = latest" in body[cap:cap + 60]
    assert cap < body.index('if req.method == "POST":')


def test_the_forward_arrow_is_disabled_at_the_open_1_1():
    assert 'disabled title="The next 1:1 opens on Thursday"' in _body("quarterStrip")


# ── Each team's own clock (Oct 2026) ─────────────────────────────────────────

def test_the_next_1_1_opens_on_thursday_in_the_teams_own_time_zone():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from shared.oneonone import default_week
    from shared.oto_templates import local_today
    utc = ZoneInfo("UTC")
    # 04:00 UTC on Thursday 8 Oct is still Wednesday evening in Chicago...
    early = datetime(2026, 10, 8, 4, 0, tzinfo=utc)
    assert local_today("contract_usa", early).isoformat() == "2026-10-07"
    assert default_week("contract", local_today("contract_usa", early)).isoformat() == "2026-09-28"
    # ...and Thursday morning in London, so the UK teams have moved on
    assert local_today("snoz", early).isoformat() == "2026-10-08"
    assert default_week("perm", local_today("bristol", early)).isoformat() == "2026-10-12"
    # Once it's Thursday in Chicago, the US desk moves on too
    later = datetime(2026, 10, 8, 6, 0, tzinfo=utc)          # 01:00 Thursday, Chicago
    assert default_week("contract", local_today("contract_usa", later)).isoformat() == "2026-10-05"
