"""
Board figures email — scheduled sender (backup trigger).

The punctual trigger is the Azure Logic App calling /api/board-schedule-run
every minute. This GitHub Actions cron runs every 15 minutes as a safety net
in case the Logic App is stopped or the app is unreachable; whichever fires
first sends, because a schedule is stamped sent as it goes out.

Env: the same as board_report.py.
"""
import os
import sys

_REQUIRED_ENV = ("DATAVERSE_URL", "DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET")


def main() -> None:
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        sys.exit(f"Missing env: {missing}")
    if not os.environ.get("ALERT_SENDER"):
        sys.exit("ALERT_SENDER not configured")

    from shared.board_schedule import run_due_schedules

    result = run_due_schedules()
    if result.get("error"):
        sys.exit(result["error"])
    print(f"Board schedules — sent {result['sent']}, skipped {result['skipped']}, "
          f"failed {result.get('failed', 0)} (checked {result.get('checked_at')})")
    if result.get("failed"):
        sys.exit("A due schedule could not be sent — see the log above")


if __name__ == "__main__":
    main()
