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
        assert f'id="{field}"' in page, field


def test_the_week_strip_follows_the_desk_locale():
    """The dates you see first. It was hand-built as day/month for everyone."""
    assert "${dt.getDate()}/${dt.getMonth() + 1}</button>" not in JS
    assert "${shortDay(dt)}</button>" in JS


def test_team_snoz_week_strip_is_exactly_as_it_was():
    """UK desk keeps 14/9 — the locale formatter would have padded it to 14/09."""
    body = _body("shortDay")
    assert "`${dt.getDate()}/${dt.getMonth() + 1}`" in body


def test_the_week_review_is_saved_from_both_boxes():
    assert 'week_consultant: document.getElementById("f-week_consultant").value' in JS
    assert 'week_manager: document.getElementById("f-week_manager").value' in JS
