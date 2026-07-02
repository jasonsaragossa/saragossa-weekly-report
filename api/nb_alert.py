"""
Daily NB-client alert.

Emails the configured recipients (finance + Jason) when a consultant has
NB_ALERT_THRESHOLD unique new-business clients that haven't featured in a
previous alert. Each alert "consumes" the clients it announced, so the next
alert needs 5 genuinely new clients — old clients dropping out of the rolling
12-month window never re-trigger it.

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
        heading = f"{escape(people[0]['name'])} has reached {people[0]['count']} NB clients"
    else:
        heading = f"{len(people)} consultants have reached an NB client milestone"

    blocks = []
    for p in people:
        clients = "".join(
            f'<li style="padding:2px 0;">{escape(c)}</li>' for c in (p.get("clients") or [])
        )
        summary = (
            f'{p["count"]} unique new-business clients in the rolling 12 months.'
            if p.get("first")
            else f'{p["new_count"]} new NB clients since their last alert '
                 f'({p["count"]} in the rolling 12 months).'
        )
        blocks.append(
            f'<p style="margin:0 0 6px;font-size:14px;color:#3c4448;line-height:1.6;">'
            f'<strong style="color:#101820;">{escape(p["name"])}</strong> — {summary}</p>'
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
        get_nb_thresholds, get_nb_alert_state, upsert_nb_alert_state,
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

    # Current NB clients per consultant (id -> name)
    current = {}
    for m in _all_members(report):
        uid = m.get("uid")
        if uid:
            current[uid] = {
                "name":  m.get("name", ""),
                "count": m.get("nb_clients", 0),
                "map":   m.get("nb_client_map", {}) or {},
            }

    state = get_nb_alert_state()

    people = []      # alerts to send
    migrated = 0
    for uid, v in current.items():
        ids = set(v["map"].keys())
        st  = state.get(uid)
        consumed = st["client_ids"] if st else set()

        # Migration: rows written before per-client tracking have no client ids.
        # Treat the consultant's current clients as already announced.
        if st and not consumed:
            upsert_nb_alert_state(uid, ids, st["rowid"])
            migrated += 1
            continue

        new_ids = ids - consumed
        if len(new_ids) >= NB_ALERT_THRESHOLD:
            people.append({
                "uid":       uid,
                "rowid":     st["rowid"] if st else None,
                "name":      v["name"],
                "count":     v["count"],
                "new_count": len(new_ids),
                "clients":   sorted(v["map"][i] for i in new_ids),
                "first":     st is None,
                "all_ids":   ids | consumed,
            })

    if not people:
        print(f"No new milestones. (migrated {migrated})")
        return

    sender     = os.environ.get("ALERT_SENDER")
    recipients = [r.strip() for r in os.environ.get("ALERT_RECIPIENTS", "").split(",") if r.strip()]
    names = [f"{p['name']} — {p['new_count']} new NB clients ({p['count']} rolling total)" for p in people]

    if not sender or not recipients:
        print("ALERT_SENDER / ALERT_RECIPIENTS not configured — not sending. Would alert:")
        print("\n".join(names))
        return  # leave state unchanged so it alerts once email is configured

    subject = (f"{people[0]['name']} has reached {people[0]['count']} NB clients"
               if len(people) == 1
               else f"{len(people)} consultants have reached an NB client milestone")
    body = (
        "The following consultant(s) have reached an NB client milestone "
        f"({NB_ALERT_THRESHOLD} new unique new-business clients):\n\n  "
        + "\n  ".join(names)
        + "\n\nSaragossa Weekly Report"
    )
    logo = _logo_bytes()
    graph_send_mail(
        sender, recipients, subject, body,
        body_html=_email_html(people, NB_ALERT_THRESHOLD, has_logo=logo is not None),
        inline_images={"saragossa-logo": logo} if logo else None,
    )
    # Consume the announced clients so the next alert needs 5 genuinely new ones
    for p in people:
        upsert_nb_alert_state(p["uid"], p["all_ids"], p["rowid"])
    print(f"Alerted {len(people)} consultant(s); migrated {migrated}.")


if __name__ == "__main__":
    main()
