"""The board-commentary reminder: one nudge per period, and never once written."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared import board_schedule as S  # noqa: E402
from shared.board import board_note_period  # noqa: E402

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)


def sched(hours_ahead, created_by="jason@saragossa.io"):
    when = NOW + timedelta(hours=hours_ahead)
    return {"id": f"s{hours_ahead}", "send_at": when.isoformat(), "send_at_dt": when,
            "recipients": [], "created_by": created_by, "sent_on": None, "label": ""}


@pytest.fixture
def mailbox(monkeypatch):
    """Fake the note store and the mailer; return what each saw."""
    sent, notes = [], {}

    def fake_get(period):
        return dict(notes.get(period) or {})

    def fake_upsert(period, body, email):
        notes[period] = {"body": body, "updated_by": email, "updated_on": NOW.isoformat()}

    monkeypatch.setattr("shared.dataverse.get_board_note", fake_get)
    monkeypatch.setattr("shared.dataverse.upsert_board_note", fake_upsert)
    monkeypatch.setattr("shared.dataverse.graph_send_mail",
                        lambda s, to, subj, text, **kw: sent.append((to, subj)))
    monkeypatch.setenv("BOARD_NOTE_REMIND", "")
    return sent, notes


def test_period_is_the_previous_full_month():
    assert board_note_period(NOW.date()) == "2026-09"
    assert board_note_period(datetime(2026, 1, 9).date()) == "2025-12"


def test_one_reminder_per_period_then_silence(mailbox):
    sent, notes = mailbox
    assert S._remind_if_note_missing([sched(20)], "alerts@saragossa.io") == 1
    assert "September 2026" in sent[0][1]
    assert sent[0][0] == ["jason@saragossa.io"]          # falls back to the scheduler
    # The stamp it leaves means the next tick stays quiet
    assert S._remind_if_note_missing([sched(20)], "alerts@saragossa.io") == 0
    assert len(sent) == 1
    assert notes["2026-09"]["body"] == ""                # and no commentary invented


def test_written_commentary_is_never_nudged(mailbox):
    sent, notes = mailbox
    notes["2026-09"] = {"body": "Shipped the MBR module.", "updated_by": "jason@saragossa.io"}
    assert S._remind_if_note_missing([sched(20)], "alerts@saragossa.io") == 0
    assert sent == []


def test_clearing_the_commentary_earns_a_fresh_nudge(mailbox):
    sent, notes = mailbox
    notes["2026-09"] = {"body": "   ", "updated_by": "jason@saragossa.io"}
    assert S._remind_if_note_missing([sched(20)], "alerts@saragossa.io") == 1


def test_explicit_recipients_win_over_the_scheduler(mailbox, monkeypatch):
    sent, _ = mailbox
    monkeypatch.setenv("BOARD_NOTE_REMIND", "jason@saragossa.io, board@saragossa.io")
    S._remind_if_note_missing([sched(20)], "alerts@saragossa.io")
    assert sent[0][0] == ["jason@saragossa.io", "board@saragossa.io"]


def test_only_sends_that_are_inside_the_horizon_are_nudged(monkeypatch, mailbox):
    sent, _ = mailbox
    # A send 40 hours out is outside the 24-hour horizon; 3 hours is inside.
    monkeypatch.setattr("shared.dataverse.get_board_schedules",
                        lambda include_sent=True: [sched(40), sched(3)])
    monkeypatch.setattr("shared.dataverse.mark_board_schedule_sent", lambda *a, **k: None)
    monkeypatch.setenv("ALERT_SENDER", "alerts@saragossa.io")

    class _FrozenNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(S, "datetime", _FrozenNow)
    out = S.run_due_schedules()
    assert out["reminded"] == 1 and out["sent"] == 0
    assert len(sent) == 1


# ── Who may write the commentary ──────────────────────────────────────────────

def _app(monkeypatch):
    import function_app as F
    return F


@pytest.mark.parametrize("who,allowed", [
    ("jason@saragossa.io", True),
    ("Jason@Saragossa.io", True),        # the identity header's casing varies
    ("becky@saragossa.io", False),       # Director + Finance: admin, but not here
    ("erin@saragossa.io", False),        # Finance team by membership drift
    ("stephen.herniman@saragossa.io", False),   # the always-allow list too
    ("", False),
])
def test_only_the_named_author_may_touch_the_commentary(monkeypatch, who, allowed):
    F = _app(monkeypatch)
    monkeypatch.setattr(F, "require_auth", lambda req: (who, None))
    # Nobody should reach the admin rule at all — it is far too wide for this.
    monkeypatch.setattr(F, "require_admin",
                        lambda req: pytest.fail("board-note must not use require_admin"))
    email, err = F._require_board_note_author(object())
    if allowed:
        assert err is None and email == who
    else:
        assert err is not None and err.status_code == 403


# ── Three sections ────────────────────────────────────────────────────────────

from shared.board import NOTE_SECTIONS, parse_note, serialise_note  # noqa: E402

KEYS = [k for k, _ in NOTE_SECTIONS]


def test_the_three_sections_are_the_ones_asked_for():
    assert [lb for _, lb in NOTE_SECTIONS] == [
        "New AI Developments", "General AI News", "Concerns / Issues"]


def test_sections_survive_a_round_trip():
    written = {"new_developments": "Shipped the MBR module.",
               "general_news": "Opus 5 landed.", "concerns": "Graph consent is slow."}
    assert parse_note(serialise_note(written)) == written


def test_partly_filled_keeps_the_blanks_blank():
    out = parse_note(serialise_note({"concerns": "Only this one."}))
    assert out["concerns"] == "Only this one."
    assert out["new_developments"] == "" and out["general_news"] == ""


def test_all_blank_stores_as_empty_so_the_reminder_still_fires():
    assert serialise_note({k: "  " for k in KEYS}) == ""
    assert serialise_note({}) == ""


def test_a_note_written_before_the_split_is_kept_not_lost():
    """Free text from the single-box version lands under the first heading."""
    out = parse_note("Wrote this when there was one box.")
    assert out["new_developments"] == "Wrote this when there was one box."
    assert out["general_news"] == "" and out["concerns"] == ""


def test_unknown_keys_are_dropped_rather_than_stored():
    stored = serialise_note({"new_developments": "kept", "sneaky": "dropped"})
    assert "sneaky" not in stored
    assert set(parse_note(stored)) == set(KEYS)


# ── How it renders in the email ───────────────────────────────────────────────

from shared.board import commentary_html  # noqa: E402


def note_of(**sections):
    return {"body": serialise_note(sections)}


def test_each_written_section_gets_its_heading():
    h = commentary_html(note_of(new_developments="Shipped the MBR module.",
                                general_news="Opus 5 landed.",
                                concerns="Graph consent is slow."))
    for _, label in NOTE_SECTIONS:
        assert label in h
    assert h.index("New AI Developments") < h.index("General AI News") < h.index("Concerns / Issues")


def test_an_empty_section_leaves_no_heading_behind():
    h = commentary_html(note_of(new_developments="Only this."))
    assert "New AI Developments" in h
    assert "General AI News" not in h and "Concerns / Issues" not in h


def test_nothing_written_renders_nothing():
    assert commentary_html(note_of()) == ""
    assert commentary_html({}) == "" and commentary_html(None) == ""
    assert commentary_html({"body": ""}) == ""


def test_blank_lines_make_paragraphs_and_single_newlines_make_breaks():
    h = commentary_html(note_of(general_news="One.\n\nTwo.\nStill two."))
    assert h.count("<p ") == 2 and "<br>" in h


def test_angle_brackets_are_escaped_not_rendered():
    h = commentary_html(note_of(concerns="<script>alert(1)</script> & co"))
    assert "<script>" not in h and "&lt;script&gt;" in h and "&amp;" in h
