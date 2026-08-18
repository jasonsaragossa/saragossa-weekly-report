"""
Board figures email — scheduled sender.

Runs on a GitHub Actions cron (see .github/workflows/board-schedule.yml) and
sends any schedule whose send-at time has passed and that hasn't been sent yet.
Schedules are created from the Analytics page and stored in Dataverse.

Because cron runs are periodic (and GitHub can delay them under load), a
schedule fires on the first run at or after its time. Anything older than
GRACE_HOURS is skipped rather than sent very late.

Env: the same as board_report.py.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

_REQUIRED_ENV = ("DATAVERSE_URL", "DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET")

GRACE_HOURS = 6   # don't send a schedule that's been missed by longer than this


def main() -> None:
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        sys.exit(f"Missing env: {missing}")
    sender = os.environ.get("ALERT_SENDER")
    if not sender:
        sys.exit("ALERT_SENDER not configured")
    default_recipients = [r.strip() for r in
                          os.environ.get("BOARD_REPORT_RECIPIENTS", "").split(",") if r.strip()]

    from shared.board import compose_board_email
    from shared.calc import build_admin_report
    from shared.dataverse import (get_board_schedules, graph_send_mail,
                                  mark_board_schedule_sent)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=GRACE_HOURS)

    due, stale = [], []
    for s in get_board_schedules(include_sent=False):
        when = s.get("send_at_dt")
        if not when:
            continue
        if when > now:
            continue
        (due if when >= cutoff else stale).append(s)

    for s in stale:
        print(f"Skipping stale schedule {s['id']} (was due {s['send_at']}) — marking sent")
        mark_board_schedule_sent(s["id"], note="skipped — missed window")

    if not due:
        print(f"No board schedules due at {now.isoformat(timespec='minutes')}")
        return

    # Build once even if several schedules are due in the same run
    subject, text, html = compose_board_email(build_admin_report)
    for s in due:
        recipients = s.get("recipients") or default_recipients
        if not recipients:
            print(f"Schedule {s['id']} has no recipients and no default — skipping")
            continue
        graph_send_mail(sender, recipients, subject, text, body_html=html)
        mark_board_schedule_sent(s["id"])
        print(f"Sent '{subject}' to {', '.join(recipients)} (schedule {s['send_at']})")


if __name__ == "__main__":
    main()
