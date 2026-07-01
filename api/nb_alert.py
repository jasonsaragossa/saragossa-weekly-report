"""
Daily NB-client alert.

Emails the configured recipients (finance + Jason) when a consultant reaches
NB_ALERT_THRESHOLD unique new-business clients in the rolling 12 months.
Fires once on crossing; re-arms automatically if they later drop below.

Run by GitHub Actions (Azure SWA managed Functions are HTTP-only, so this
can't be a timer function in the app itself). Requires these env vars:
  DATAVERSE_URL, DATAVERSE_TENANT_ID, DATAVERSE_CLIENT_ID, DATAVERSE_CLIENT_SECRET
  ALERT_SENDER       — mailbox to send from (needs Graph Mail.Send consent)
  ALERT_RECIPIENTS   — comma-separated recipient emails
"""
import os
from datetime import date

NB_ALERT_THRESHOLD = 5
_REQUIRED_ENV = ("DATAVERSE_URL", "DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET")


def _logo_bytes():
    """The white Saragossa logo (public/logo.png), embedded inline in the email."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "public", "logo.png")
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _email_html(people: list, threshold: int, has_logo: bool) -> str:
    """Branded HTML body matching the Saragossa email template (dark header,
    cream background, eyebrow, heading, confidential footer)."""
    from html import escape

    if len(people) == 1:
        heading = f"{escape(people[0]['name'])} has reached {threshold} NB clients"
    else:
        heading = f"{len(people)} consultants have reached {threshold} NB clients"

    blocks = []
    for p in people:
        clients = "".join(
            f'<li style="padding:2px 0;">{escape(c)}</li>' for c in (p.get("clients") or [])
        )
        blocks.append(
            f'<p style="margin:0 0 6px;font-size:14px;color:#3c4448;line-height:1.6;">'
            f'<strong style="color:#101820;">{escape(p["name"])}</strong> — '
            f'{p["count"]} unique new-business clients in the rolling 12 months.</p>'
            + (f'<ul style="margin:0 0 18px;padding-left:20px;font-size:13px;color:#5a6468;">{clients}</ul>'
               if clients else "")
        )

    header_inner = (
        '<img src="cid:saragossa-logo" alt="Saragossa" height="26" style="display:block;">'
        if has_logo else
        '<span style="color:#ffffff;font-size:15px;letter-spacing:5px;font-weight:600;">SARAGOSSA</span>'
    )

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f2eee5;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2eee5;">
  <tr><td align="center" style="padding:28px 12px;">
    <table role="presentation" width="560" cellpadding="0" cellspacing="0"
           style="background:#ffffff;border-radius:4px;overflow:hidden;font-family:Arial,Helvetica,sans-serif;max-width:560px;width:100%;">
      <tr><td style="background:#101820;padding:22px 32px;">{header_inner}</td></tr>
      <tr><td style="padding:30px 32px 0;">
        <div style="font-size:11px;letter-spacing:2px;color:#5a6b6e;text-transform:uppercase;
                    padding-bottom:12px;border-bottom:1px solid #e5e0d5;">New business milestone</div>
      </td></tr>
      <tr><td style="padding:20px 32px 4px;">
        <div style="font-size:23px;font-weight:600;color:#101820;line-height:1.3;">{heading}</div>
      </td></tr>
      <tr><td style="padding:14px 32px 24px;">{''.join(blocks)}</td></tr>
      <tr><td style="padding:16px 32px;border-top:1px solid #e5e0d5;font-size:11px;color:#9aa0a6;">
        Saragossa &middot; Private &amp; confidential. Sent automatically by the Weekly Report.
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def _all_members(report: dict):
    for tdata in report.values():
        if tdata.get("type") == "teams":
            for g in tdata.get("groups", []):
                yield from g.get("members", [])
        else:
            yield from tdata.get("members", [])


def main() -> None:
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        print(f"Skipping NB alert — missing env: {missing}. Add the GitHub secrets to enable.")
        return

    # Imported here so a missing-config run exits cleanly (dataverse reads env at import)
    from shared.dataverse import (
        get_active_consultants, get_placements, get_contract_placements, get_overrides,
        get_team_membership_map, get_live_contract_placements, get_fx_rates,
        get_nb_thresholds, get_nb_alerted_uids, add_nb_alerted, remove_nb_alerted,
        graph_send_mail,
    )
    from shared.calc import build_report

    today = date.today()
    start = date(today.year - 1, today.month, 1).isoformat()
    end   = date(today.year, 12, 31).isoformat()

    consultants    = get_active_consultants()
    placements     = get_placements(start, end)
    contract_pl    = get_contract_placements(start, end)
    overrides      = get_overrides()
    team_map       = get_team_membership_map()
    live_contracts = get_live_contract_placements(today.isoformat())
    nb_thresholds  = get_nb_thresholds()
    try:
        fx_rates = get_fx_rates()
    except Exception:
        fx_rates = None

    report = build_report(consultants, placements, overrides, today, team_map,
                          live_contracts, fx_rates, nb_thresholds, contract_pl)

    # Current count per consultant
    current = {}
    for m in _all_members(report):
        uid = m.get("uid")
        if uid:
            current[uid] = {
                "name":    m.get("name", ""),
                "count":   m.get("nb_clients", 0),
                "clients": m.get("nb_client_names", []),
            }

    alerted = get_nb_alerted_uids()

    to_alert = [uid for uid, v in current.items()
                if v["count"] >= NB_ALERT_THRESHOLD and uid not in alerted]
    # Re-arm: clear anyone who has dropped below the threshold (or left)
    to_clear = [uid for uid in alerted
                if uid not in current or current[uid]["count"] < NB_ALERT_THRESHOLD]

    for uid in to_clear:
        remove_nb_alerted(uid)

    if not to_alert:
        print(f"No new crossings. (cleared {len(to_clear)})")
        return

    sender     = os.environ.get("ALERT_SENDER")
    recipients = [r.strip() for r in os.environ.get("ALERT_RECIPIENTS", "").split(",") if r.strip()]
    names = [f"{current[uid]['name']} — {current[uid]['count']} NB clients" for uid in to_alert]

    if not sender or not recipients:
        print("ALERT_SENDER / ALERT_RECIPIENTS not configured — not sending. Would alert:")
        print("\n".join(names))
        return  # leave state unchanged so it alerts once email is configured

    people  = [current[uid] for uid in to_alert]
    subject = (f"{people[0]['name']} has reached {NB_ALERT_THRESHOLD} NB clients"
               if len(people) == 1
               else f"{len(people)} consultants have reached {NB_ALERT_THRESHOLD} NB clients")
    body = (
        f"The following consultant(s) have reached {NB_ALERT_THRESHOLD} or more unique "
        f"new-business clients in the rolling 12 months:\n\n  "
        + "\n  ".join(names)
        + "\n\nSaragossa Weekly Report"
    )
    logo = _logo_bytes()
    graph_send_mail(
        sender, recipients, subject, body,
        body_html=_email_html(people, NB_ALERT_THRESHOLD, has_logo=logo is not None),
        inline_images={"saragossa-logo": logo} if logo else None,
    )
    for uid in to_alert:
        add_nb_alerted(uid)
    print(f"Alerted {len(to_alert)} consultant(s); cleared {len(to_clear)}.")


if __name__ == "__main__":
    main()
