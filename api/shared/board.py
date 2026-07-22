"""
Board report — assembles the figures Jason presents ~3×/month and renders the
branded email: monthly P&L splits table, notes (deals / new clients /
cancellations), regional perm totals, placement forecast, and Tech ROI.

Counting rules (verified against the June 2026 board slide):
  * A placement credits 0.5 to the Consultant slot's bucket and 0.5 to the AO
    slot's bucket, bucketed by the owner's territory (Consult and Deploy are
    real Mercury territories). Owners with no territory are excluded.
  * Retainer-candidate placements are excluded from the deal counts and shown
    on their own row.
  * Contract counts cover initial contracts only (extensions excluded).
  * Written £ = created-in-month perm GP; Invoiced £ = started-in-month perm
    GP — both distributed by the standard ownership split, in GBP.
"""
import os
import logging
from datetime import date

from shared.calc import (
    _build_fx_tables, TO_GBP, TO_USD, split_factor, parse_date,
    _is_extension, _CONTRACT_TYPE_CODES, _PERM_TYPE_CODE,
)
from shared.dataverse import (
    RETAINER_CANDIDATE_CONTACT_ID,
    get_all_territory_consultants, get_overrides, get_team_membership_map,
    get_placements_full_year, get_placements_created_in_year, get_budgets,
    get_fx_rates, get_user_territory_map,
    get_cancel_log, sync_cancel_log, fetch_roi_summary, get_latest_forecast,
    get_first_placement_dates,
)

BUCKET_BY_TERRITORY = {
    "Bristol":          "Bristol",
    "London":           "London Perm",
    "Chicago":          "Chicago",
    "New York":         "NYC",
    "London Contract":  "London Contract",
    "Chicago Contract": "Chicago Contract",
    "Consult":          "Consult",
    "Deploy":           "Deploy",
    "Cameron Scott":    "Cameron",
}
BUCKET_ORDER = ["Bristol", "London Perm", "Chicago", "NYC", "London Contract",
                "Chicago Contract", "Consult", "Deploy", "Cameron", "House/Misc"]
PENDING_STATUS = 143570001
_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"]

_OWNER_SLOTS = ("_crimson_consultant_value", "_mercury_assignmentowner_value")
_ALL_OWNER_FIELDS = (
    "_mercury_clientrelationshipowner_value", "_crimson_consultant_value",
    "_mercury_assignmentowner_value", "_mercury_contractorrelationship_userid_value",
)

_SOLUTION_LABELS = {
    "cp": "Connect Perm", "cc": "Connect Contract", "con": "Consult",
    "dep": "Deploy", "perm": "Connect Perm", "contract": "Connect Contract",
}


def _bucket_for(terr: str):
    """Bucket for an owner's territory; None = excluded (no territory)."""
    if not terr:
        return None
    return BUCKET_BY_TERRITORY.get(terr, "House/Misc")


def _is_retainer(p) -> bool:
    return p.get("_recruit_candidatecontact_value") == RETAINER_CANDIDATE_CONTACT_ID


def _month_stats(created, started_perm, user_terr, to_gbp, y, m):
    """P&L buckets + notes data for calendar month (y, m)."""
    buckets = {b: {"perm": 0.0, "contract": 0.0, "written": 0.0, "invoiced": 0.0}
               for b in BUCKET_ORDER}
    stats = {
        "buckets": buckets, "perm_deals": 0, "contract_deals": 0,
        "perm_pending": 0, "contract_pending": 0,
        "retainer_count": 0, "retainer_invoiced": 0.0,
        "nb_perm": {}, "nb_contract": {},   # {client_id: name}, NB-flagged
        "written_total": 0.0, "invoiced_total": 0.0,
    }

    for p in (created or []):
        try:
            d = parse_date(p.get("createdon") or "")
        except Exception:
            continue
        if d.year != y or d.month != m:
            continue
        ptype = p.get("crimson_type")
        if ptype == _PERM_TYPE_CODE:
            if _is_retainer(p):
                stats["retainer_count"] += 1
                continue
            kind = "perm"
        elif ptype in _CONTRACT_TYPE_CODES:
            if _is_extension(p):
                continue
            kind = "contract"
        else:
            continue

        stats[f"{kind}_deals"] += 1
        if p.get("statuscode") == PENDING_STATUS:
            stats[f"{kind}_pending"] += 1
        if "new business" in (p.get("crimson_specialinstructionsclient") or "").lower():
            cid    = p.get("_crimson_clientname_value")
            client = (p.get("crimson_clientname") or {}).get("name")
            if cid and client:
                stats[f"nb_{kind}"][cid] = client

        # Placement counts: 0.5 to the Consultant slot, 0.5 to the AO slot
        for slot in _OWNER_SLOTS:
            b = _bucket_for(user_terr.get(p.get(slot)))
            if b:
                buckets[b][kind] += 0.5

        # Written £ (perm only): full GP distributed by the standard split
        if kind == "perm":
            gp  = p.get("recruit_truegrossprofit") or 0.0
            ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode")
            gbp = gp * to_gbp.get(ccy, 1.0)
            stats["written_total"] += gbp
            for uid in {p.get(f) for f in _ALL_OWNER_FIELDS if p.get(f)}:
                share = split_factor(p, uid)
                if share <= 0:
                    continue
                b = _bucket_for(user_terr.get(uid))
                if b:
                    buckets[b]["written"] += gbp * share

    # Invoiced £ (perm placements STARTED in the month)
    for p in (started_perm or []):
        try:
            d = parse_date(p.get("crimson_startdate") or "")
        except Exception:
            continue
        if d.year != y or d.month != m:
            continue
        gp  = p.get("recruit_truegrossprofit") or 0.0
        ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode")
        gbp = gp * to_gbp.get(ccy, 1.0)
        if _is_retainer(p):
            stats["retainer_invoiced"] += gbp
            continue
        stats["invoiced_total"] += gbp
        for uid in {p.get(f) for f in _ALL_OWNER_FIELDS if p.get(f)}:
            share = split_factor(p, uid)
            if share <= 0:
                continue
            b = _bucket_for(user_terr.get(uid))
            if b:
                buckets[b]["invoiced"] += gbp * share

    return stats


def _cancelled_in_month(cancel_log, y, m):
    prefix = f"{y}-{m:02d}"
    out = {}
    for e in cancel_log:
        if (e.get("detected") or "").startswith(prefix):
            out[e.get("ptype") or "Other"] = out.get(e.get("ptype") or "Other", 0) + 1
    return out


def _regional_totals(report):
    """2026 vs 2025-to-date perm totals + % change, matching the Summary tab."""
    usd_to_gbp = report.get("usd_to_gbp") or 0.79
    rows, sum_this, sum_last = [], 0.0, 0.0
    for terr, label in (("Bristol", "Bristol"), ("London", "London"),
                        ("Chicago", "Chicago"), ("New York", "New York")):
        td = (report.get("territories") or {}).get(terr)
        if not td:
            continue
        f = usd_to_gbp if terr in ("Chicago", "New York") else 1.0
        this = (td.get("territory_total") or 0) * f
        last = (td.get("territory_last_year_ytd") or 0) * f
        rows.append({"label": label, "this": this, "last": last,
                     "pct": (this - last) / last * 100 if last > 0 else None})
        sum_this += this
        sum_last += last
    g_this = report.get("grand_total_gbp") or 0
    g_last = report.get("grand_total_last_ytd_gbp") or 0
    rows.append({"label": "Others", "this": g_this - sum_this,
                 "last": g_last - sum_last, "pct": None})
    rows.append({"label": "Global", "this": g_this, "last": g_last,
                 "pct": (g_this - g_last) / g_last * 100 if g_last > 0 else None})
    return rows


def _sol_label(code):
    return _SOLUTION_LABELS.get((code or "").lower(), code or "?")


def compose_board_email(build_admin_report_fn) -> tuple:
    """
    Gathers everything and returns (subject, text_fallback, html).
    build_admin_report_fn: shared.calc.build_admin_report (passed in to avoid
    a circular import).
    """
    today = date.today()
    year  = today.year
    # Previous full month
    py, pm = (year, today.month - 1) if today.month > 1 else (year - 1, 12)

    try:
        sync_cancel_log(today.isoformat())
    except Exception:
        logging.warning("cancel-log sync failed", exc_info=True)

    consultants     = get_all_territory_consultants()
    overrides       = get_overrides()
    team_map        = get_team_membership_map()
    placements_this = get_placements_full_year(year)
    placements_last = get_placements_full_year(year - 1)
    created_this    = get_placements_created_in_year(year)
    created_prev    = created_this if py == year else get_placements_created_in_year(py)
    started_prev    = placements_this if py == year else placements_last
    budgets         = get_budgets()
    user_terr       = get_user_territory_map()
    cancel_log      = get_cancel_log()
    try:
        fx_rates = get_fx_rates()
    except Exception:
        fx_rates = None
    to_gbp, _ = _build_fx_tables(fx_rates) if fx_rates else (TO_GBP, TO_USD)

    report = build_admin_report_fn(
        consultants, placements_this, placements_last, overrides, today,
        team_map=team_map, budgets=budgets, fx_rates=fx_rates,
        created_this=created_this,
        created_last=get_placements_created_in_year(year - 1),
    )

    prev_stats = _month_stats(created_prev, started_prev, user_terr, to_gbp, py, pm)
    curr_stats = _month_stats(created_this, placements_this, user_terr, to_gbp, year, today.month)

    # "New client" = a client whose FIRST-EVER placement was created in that
    # month — NB-flagged repeat business at an existing client doesn't count.
    cand_ids = (set(prev_stats["nb_perm"]) | set(prev_stats["nb_contract"])
                | set(curr_stats["nb_perm"]) | set(curr_stats["nb_contract"]))
    first_dates = get_first_placement_dates(list(cand_ids))

    def _truly_new(nb_map, y, m):
        prefix = f"{y}-{m:02d}"
        return sorted(name for cid, name in nb_map.items()
                      if (first_dates.get(cid) or "").startswith(prefix))

    prev_stats["nb_perm"]     = _truly_new(prev_stats["nb_perm"], py, pm)
    prev_stats["nb_contract"] = _truly_new(prev_stats["nb_contract"], py, pm)
    curr_stats["nb_perm"]     = _truly_new(curr_stats["nb_perm"], year, today.month)
    curr_stats["nb_contract"] = _truly_new(curr_stats["nb_contract"], year, today.month)

    prev_cancel = _cancelled_in_month(cancel_log, py, pm)
    curr_cancel = _cancelled_in_month(cancel_log, year, today.month)
    regional    = _regional_totals(report)
    forecast    = get_latest_forecast()
    roi         = fetch_roi_summary()

    from datetime import datetime
    stamp = datetime.utcnow().strftime("%d %b %H:%M")
    subject = f"Board figures · {_MONTHS[pm - 1]} {py} + {_MONTHS[today.month - 1]} to date · {stamp}"
    html = _render_html(today, py, pm, prev_stats, curr_stats,
                        prev_cancel, curr_cancel, regional, forecast, roi)
    text = f"Board figures for {_MONTHS[pm - 1]} {py} — open in an HTML mail client."
    return subject, text, html


# ── Rendering ─────────────────────────────────────────────────────────────────

def _money(n):
    return f"£{n:,.0f}" if n else "—"


def _num(n):
    if not n:
        return "0"
    return f"{n:g}"


def _render_html(today, py, pm, prev, curr, prev_cancel, curr_cancel,
                 regional, forecast, roi):
    from html import escape
    prev_label = f"{_MONTHS[pm - 1]} {py}"
    curr_label = f"{_MONTHS[today.month - 1]} {today.year}"

    th = ('style="text-align:right;padding:7px 10px;font-size:11px;color:#5a6b6e;'
          'text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #101820;"')
    thl = th.replace("text-align:right", "text-align:left")
    td = 'style="text-align:right;padding:7px 10px;font-size:13px;color:#3c4448;border-bottom:1px solid #e5e0d5;"'
    tdl = td.replace("text-align:right", "text-align:left")
    tdb = td.replace("color:#3c4448", "color:#101820;font-weight:700")
    tdlb = tdl.replace("color:#3c4448", "color:#101820;font-weight:700")

    # ── P&L table ──
    rows_html = ""
    tot = {"perm": 0.0, "contract": 0.0, "written": 0.0, "invoiced": 0.0}
    for b in BUCKET_ORDER:
        v = prev["buckets"][b]
        if not any(v.values()):
            continue
        for k in tot:
            tot[k] += v[k]
        rows_html += (f'<tr><td {tdl}><strong>{escape(b)}</strong></td>'
                      f'<td {td}>{_num(v["perm"])}</td><td {td}>{_num(v["contract"])}</td>'
                      f'<td {td}>{_money(v["written"])}</td><td {td}>{_money(v["invoiced"])}</td></tr>')
    rows_html += (f'<tr><td {tdlb}>Total</td>'
                  f'<td {tdb}>{_num(tot["perm"])}</td><td {tdb}>{_num(tot["contract"])}</td>'
                  f'<td {tdb}>{_money(tot["written"])}</td><td {tdb}>{_money(tot["invoiced"])}</td></tr>')
    rows_html += (f'<tr><td {tdl}>Retainer</td><td {td}>{prev["retainer_count"] or "—"}</td>'
                  f'<td {td}>—</td><td {td}>—</td><td {td}>{_money(prev["retainer_invoiced"])}</td></tr>')
    pnl_table = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
                 f'<tr><th {thl}></th><th {th}>Perm</th><th {th}>Contract</th>'
                 f'<th {th}>Perm Written GBP</th><th {th}>Perm Invoiced GBP</th></tr>{rows_html}</table>')

    # ── Notes ──
    def notes_block(label, s, cancel):
        deals = s["perm_deals"] + s["contract_deals"]
        pend  = s["perm_pending"] + s["contract_pending"]
        nb_p  = ", ".join(escape(c) for c in s["nb_perm"]) or "none"
        nb_c  = ", ".join(escape(c) for c in s["nb_contract"]) or "none"
        cx    = ", ".join(f"{n} {escape(t.lower())}" for t, n in sorted(cancel.items())) or "none"
        pend_note = f" (of which {pend} at Pending)" if pend else ""
        return (f'<p style="margin:0 0 4px;font-size:14px;color:#101820;"><strong>{escape(label)} — '
                f'{deals} deals{pend_note}</strong></p>'
                f'<p style="margin:0 0 2px;font-size:13px;color:#3c4448;">Perm: {s["perm_deals"]} · '
                f'New clients: {len(s["nb_perm"])} ({nb_p})</p>'
                f'<p style="margin:0 0 2px;font-size:13px;color:#3c4448;">Contract: {s["contract_deals"]} · '
                f'New clients: {len(s["nb_contract"])} ({nb_c})</p>'
                f'<p style="margin:0 0 14px;font-size:13px;color:#3c4448;">Cancelled placements: {cx}</p>')

    notes = notes_block(f"{_MONTHS[pm - 1]}", prev, prev_cancel) \
          + notes_block(f"{_MONTHS[today.month - 1]} to date ({today.day}{_ordinal(today.day)})",
                        curr, curr_cancel)

    # ── Regional totals ──
    reg_rows = ""
    for r in regional:
        pct = f'{r["pct"]:+.1f}%' if r["pct"] is not None else "—"
        bold = r["label"] == "Global"
        l, c = (tdlb, tdb) if bold else (tdl, td)
        reg_rows += (f'<tr><td {l}>{escape(r["label"])}</td><td {c}>{_money(r["last"])}</td>'
                     f'<td {c}>{_money(r["this"])}</td><td {c}>{pct}</td></tr>')
    reg_table = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
                 f'<tr><th {thl}></th><th {th}>{today.year - 1} (same point)</th>'
                 f'<th {th}>{today.year}</th><th {th}>% Change</th></tr>{reg_rows}</table>')

    # ── Forecast ──
    fc_html = '<p style="margin:0;font-size:13px;color:#8a8f94;">No forecast snapshot available.</p>'
    if forecast.get("current") or forecast.get("next"):
        def line(rows, label):
            if not rows:
                return ""
            exp = sum(r["expected"] for r in rows)
            conf = sum(r["confirmed"] for r in rows)
            bits = " · ".join(f'{escape(_sol_label(r["solution"]))} {r["expected"]:g}'
                              for r in sorted(rows, key=lambda x: -x["expected"]))
            return (f'<p style="margin:0 0 6px;font-size:13px;color:#3c4448;"><strong>{label}</strong>: '
                    f'xP {exp:.1f} ({conf:g} confirmed so far) — {bits}</p>')
        fc_html = line(forecast["current"], f"{_MONTHS[today.month - 1]}") \
                + line(forecast["next"], f"{_MONTHS[today.month % 12]}")
        if forecast.get("snapshot_date"):
            fc_html += (f'<p style="margin:0;font-size:11px;color:#8a8f94;">Snapshot '
                        f'{escape(forecast["snapshot_date"])} · Placement Predictor (still learning)</p>')

    # ── Tech ROI ──
    roi_html = '<p style="margin:0;font-size:13px;color:#8a8f94;">ROI tracker unavailable.</p>'
    if roi.get("rows"):
        yr_pct = round(today.timetuple().tm_yday / 365 * 100)
        rr = ""
        for r in roi["rows"]:
            rr += (f'<tr><td {tdl}>{escape(r["group"])}</td><td {td}>{_money(r["target"])}</td>'
                   f'<td {td}>{_money(r["achieved"])}</td><td {td}>{r["pct"]:.1f}%</td></tr>')
        roi_html = (f'<p style="margin:0 0 8px;font-size:12px;color:#5a6b6e;">{yr_pct}% through the year</p>'
                    f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
                    f'<tr><th {thl}></th><th {th}>Target</th><th {th}>ROI</th><th {th}>% Target</th></tr>{rr}</table>')

    def section(title, inner):
        return (f'<tr><td style="padding:22px 32px 0;">'
                f'<div style="font-size:11px;letter-spacing:2px;color:#5a6b6e;text-transform:uppercase;'
                f'padding-bottom:10px;border-bottom:1px solid #e5e0d5;margin-bottom:12px;">{title}</div>'
                f'{inner}</td></tr>')

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#f2eee5;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2eee5;">
  <tr><td align="center" style="padding:28px 12px;">
    <table role="presentation" width="640" cellpadding="0" cellspacing="0"
           style="background:#ffffff;border-radius:4px;overflow:hidden;font-family:Arial,Helvetica,sans-serif;max-width:640px;width:100%;">
      <tr><td style="background:#101820;padding:22px 32px;">
        <span style="color:#ffffff;font-size:15px;letter-spacing:5px;font-weight:600;">SARAGOSSA</span>
      </td></tr>
      <tr><td style="padding:26px 32px 0;">
        <div style="font-size:22px;font-weight:600;color:#101820;">Board figures — {prev_label}</div>
        <div style="font-size:12px;color:#8a8f94;margin-top:4px;">plus {curr_label} to date · generated {today.isoformat()}</div>
      </td></tr>
      {section(f'P&amp;L — deals &amp; perm revenue ({prev_label})', pnl_table)}
      {section('Notes', notes)}
      {section('Regional perm totals', reg_table)}
      {section('Placement forecast', fc_html)}
      {section('Tech ROI', roi_html)}
      <tr><td style="padding:20px 32px 16px;"></td></tr>
      <tr><td style="padding:14px 32px;border-top:1px solid #e5e0d5;font-size:11px;color:#9aa0a6;">
        Saragossa &middot; Private &amp; confidential. Sent automatically by the Weekly Report.
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def _ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
