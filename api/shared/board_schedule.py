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

    due, stale = [], []
    for s in get_board_schedules(include_sent=False):
        when = s.get("send_at_dt")
        if not when or when > now:
            continue
        (due if when >= cutoff else stale).append(s)

    for s in stale:
        logging.warning("Board schedule %s missed its window (due %s) — marking sent",
                        s["id"], s["send_at"])
        mark_board_schedule_sent(s["id"], note="skipped - missed window")

    if not due:
        return {"sent": 0, "skipped": len(stale), "checked_at": now.isoformat(timespec="seconds")}

    # Build once even when several schedules come due in the same tick
    subject, text, html, images = compose_board_email(build_admin_report)
    sent = 0
    for s in due:
        recipients = s.get("recipients") or default_recipients
        if not recipients:
            logging.warning("Board schedule %s has no recipients and no default", s["id"])
            mark_board_schedule_sent(s["id"], note="skipped - no recipients")
            continue
        graph_send_mail(sender, recipients, subject, text, body_html=html,
                        inline_images=images)
        mark_board_schedule_sent(s["id"])
        sent += 1
        logging.info("Sent board schedule %s to %s", s["id"], ", ".join(recipients))

    return {"sent": sent, "skipped": len(stale), "subject": subject,
            "checked_at": now.isoformat(timespec="seconds")}
