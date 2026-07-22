"""
Board figures email — manual/scheduled sender.

Run from GitHub Actions (workflow_dispatch) with the same env as nb_alert.py:
  DATAVERSE_URL, DATAVERSE_TENANT_ID, DATAVERSE_CLIENT_ID, DATAVERSE_CLIENT_SECRET
  ALERT_SENDER              — mailbox to send from
  BOARD_REPORT_RECIPIENTS   — comma-separated recipients
  ROI_TRACKER_URL / ROI_TRACKER_API_KEY — Tech ROI section (optional)
"""
import os
import sys

_REQUIRED_ENV = ("DATAVERSE_URL", "DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET")


def main() -> None:
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        sys.exit(f"Missing env: {missing}")
    sender     = os.environ.get("ALERT_SENDER")
    recipients = [r.strip() for r in os.environ.get("BOARD_REPORT_RECIPIENTS", "").split(",") if r.strip()]
    if not sender or not recipients:
        sys.exit("ALERT_SENDER / BOARD_REPORT_RECIPIENTS not configured")

    from shared.board import compose_board_email
    from shared.calc import build_admin_report
    from shared.dataverse import graph_send_mail

    subject, text, html = compose_board_email(build_admin_report)
    graph_send_mail(sender, recipients, subject, text, body_html=html)
    print(f"Sent '{subject}' to {', '.join(recipients)}")


if __name__ == "__main__":
    main()
