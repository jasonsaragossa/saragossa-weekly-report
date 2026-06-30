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
            current[uid] = {"name": m.get("name", ""), "count": m.get("nb_clients", 0)}

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

    subject = f"NB client alert — {len(to_alert)} consultant(s) reached {NB_ALERT_THRESHOLD}"
    body = (
        f"The following consultant(s) have reached {NB_ALERT_THRESHOLD} or more unique "
        f"new-business clients in the rolling 12 months:\n\n  "
        + "\n  ".join(names)
        + "\n\nSaragossa Weekly Report"
    )
    graph_send_mail(sender, recipients, subject, body)
    for uid in to_alert:
        add_nb_alerted(uid)
    print(f"Alerted {len(to_alert)} consultant(s); cleared {len(to_clear)}.")


if __name__ == "__main__":
    main()
