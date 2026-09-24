"""
Fire board-report schedules that have fallen due.

Shared by two triggers, both safe to run together because a schedule is
stamped sent the moment it goes out:
  - the Logic App scheduler (every minute, punctual) via /api/board-schedule-run
  - the GitHub Actions cron (every 15 minutes, best-effort) as a backup
"""
import logging
import os
from datetime import datetime, timedelta, timezone

# Don't send a schedule that was missed by longer than this — a board pack
# arriving hours late is worse than one that didn't arrive.
GRACE_HOURS = 6

# How far ahead of a send we nudge about missing commentary. A day gives time
# to write it without the reminder landing so early it's forgotten.
REMIND_HOURS = 24

# A note row whose body is still empty but was written by this marks a period
# already nudged — so the reminder goes out once per period, not every minute.
REMINDED_BY = "reminder"


def _remind_if_note_missing(due_soon: list, sender: str) -> int:
    """
    One nudge per board period when commentary hasn't been written yet.

    The guard is the note row itself: an empty body stamped REMINDED_BY means
    we've already asked. Writing the commentary replaces that stamp; clearing
    it again earns a fresh nudge next time a send comes round.
    """
    from shared.board import _MONTHS, board_note_period
    from shared.dataverse import get_board_note, graph_send_mail, upsert_board_note

    site = os.environ.get("SITE_URL", "https://weeklyreport.saragossa.io").rstrip("/")
    reminded = 0
    for period in sorted({board_note_period(s["send_at_dt"].date()) for s in due_soon}):
        note = get_board_note(period)
        if (note.get("body") or "").strip() or note.get("updated_by") == REMINDED_BY:
            continue
        to = [r.strip() for r in os.environ.get("BOARD_NOTE_REMIND", "").split(",") if r.strip()]
        if not to:
            to = sorted({s["created_by"] for s in due_soon if s.get("created_by")})
        if not to:
            logging.warning("No commentary for %s and nobody to remind", period)
            continue
        y, m = int(period[:4]), int(period[5:])
        label = f"{_MONTHS[m - 1]} {y}"
        text = (f"The board report for {label} goes out within {REMIND_HOURS} hours and "
                f"there's no AI commentary on it yet.\n\n"
                f"Add it here: {site}/index.html#analytics\n\n"
                f"Leave it blank and the email simply goes without that section.")
        html = (f'<p style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;">'
                f'The board report for <b>{label}</b> goes out within {REMIND_HOURS} hours '
                f'and there is no commentary on it yet.</p>'
                f'<p style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;">'
                f'<a href="{site}/index.html#analytics">Add your commentary</a> — or leave '
                f'it blank and the email goes without that section.</p>')
        try:
            graph_send_mail(sender, to, f"Board commentary for {label} — not written yet",
                            text, body_html=html)
            upsert_board_note(period, "", REMINDED_BY)
            reminded += 1
            logging.info("Reminded %s about board commentary for %s", ", ".join(to), period)
        except Exception:
            logging.exception("Could not send the board commentary reminder for %s", period)
    return reminded


def run_due_schedules() -> dict:
    """Sends anything due. Returns a small summary for the caller's logs."""
    from shared.board import compose_board_email
    from shared.calc import build_admin_report
    from shared.dataverse import (get_board_schedules, graph_send_mail,
                                  mark_board_schedule_sent)

    sender = os.environ.get("ALERT_SENDER")
    if not sender:
        return {"sent": 0, "skipped": 0, "error": "ALERT_SENDER not configured"}
    default_recipients = [r.strip() for r in
                          os.environ.get("BOARD_REPORT_RECIPIENTS", "").split(",") if r.strip()]

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=GRACE_HOURS)

    horizon = now + timedelta(hours=REMIND_HOURS)

    due, stale, soon = [], [], []
    for s in get_board_schedules(include_sent=False):
        when = s.get("send_at_dt")
        if not when:
            continue
        if when > now:
            if when <= horizon:
                soon.append(s)
            continue
        (due if when >= cutoff else stale).append(s)

    # Nudge about missing commentary before the pack goes, not after.
    reminded = _remind_if_note_missing(soon, sender) if soon else 0

    for s in stale:
        logging.warning("Board schedule %s missed its window (due %s) — marking sent",
                        s["id"], s["send_at"])
        mark_board_schedule_sent(s["id"], note="skipped - missed window")

    if not due:
        return {"sent": 0, "skipped": len(stale), "reminded": reminded,
                "checked_at": now.isoformat(timespec="seconds")}

    # Build once even when several schedules come due in the same tick
    subject, text, html, images = compose_board_email(build_admin_report)
    sent = failed = 0
    for s in due:
        recipients = s.get("recipients") or default_recipients
        if not recipients:
            # A missing default list is a config fault, not a finished send.
            # Leave the schedule pending so it goes out once the config is
            # fixed (inside the grace window) instead of vanishing silently.
            logging.error("Board schedule %s due %s has no recipients and "
                          "BOARD_REPORT_RECIPIENTS is unset — leaving it pending",
                          s["id"], s["send_at"])
            failed += 1
            continue
        graph_send_mail(sender, recipients, subject, text, body_html=html,
                        inline_images=images)
        mark_board_schedule_sent(s["id"])
        sent += 1
        logging.info("Sent board schedule %s to %s", s["id"], ", ".join(recipients))

    return {"sent": sent, "skipped": len(stale), "failed": failed, "reminded": reminded,
            "subject": subject,
            "checked_at": now.isoformat(timespec="seconds")}
