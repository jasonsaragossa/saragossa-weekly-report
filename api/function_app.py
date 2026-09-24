"""
Azure Functions V2 — all API endpoints for the Saragossa weekly report.

Routes:
  GET  /api/report-data   → full report JSON (all authenticated users)
  GET  /api/settings      → override list + Mercury user list (admin only)
  POST /api/settings      → upsert an override (admin only)
  DELETE /api/settings/{id} → remove an override (admin only)
"""
import json, logging, os, re
from datetime import date, datetime, timedelta, timezone

import azure.functions as func

from shared.auth import require_auth, require_admin
from shared.dataverse import (
    get_active_consultants, get_placements, get_contract_placements, get_overrides,
    get_team_membership_map, get_live_contract_placements, get_fx_rates,
    get_placements_full_year, get_placements_created_in_year, get_budgets, upsert_monthly_budgets,
    get_all_territory_consultants, get_all_active_users, get_finance_team_members,
    upsert_override, delete_override, is_guid, TERRITORY_IDS,
    get_nb_thresholds, upsert_nb_thresholds,
    get_contract_entries, upsert_contract_entries,
    get_solution_entries, upsert_solution_entries,
    get_manual_nb_clients, add_manual_nb_client, remove_manual_nb_client, search_accounts,
    get_nb_clients_for_cro, get_nb_alert_state, upsert_nb_alert_state, delete_nb_alert_state,
)
from shared.calc import build_report, build_admin_report

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def _server_error() -> func.HttpResponse:
    """Generic 500 — full detail is logged server-side, never returned to the client."""
    return func.HttpResponse(
        json.dumps({"ok": False, "error": "Internal server error"}),
        mimetype="application/json",
        status_code=500,
    )


def _bad_request(message: str) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps({"ok": False, "error": message}),
        mimetype="application/json",
        status_code=400,
    )


# ── /api/report-data ──────────────────────────────────────────────────────────

def _load_report(today: date) -> tuple:
    """
    Fetch everything the weekly report needs and build it.
    Returns (report, fetch_ms, build_ms). Shared by the report page and the
    contract screen, so the two can never disagree about a figure.
    """
    import time
    t0 = time.monotonic()

    # Date window: placements from 12 months ago through end of this year
    start = date(today.year - 1, today.month, 1).isoformat()
    end   = date(today.year, 12, 31).isoformat()

    # Twelve independent reads of Dataverse. Run one after another they add
    # up to most of the page's load time, and on a cold start they used to
    # reach the 45-second gateway limit; none of them depends on another.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = {
            "consultants":      pool.submit(get_active_consultants),
            "placements":       pool.submit(get_placements, start, end),
            "contract_pl":      pool.submit(get_contract_placements, start, end),
            "overrides":        pool.submit(get_overrides),
            "team_map":         pool.submit(get_team_membership_map),
            "live_contracts":   pool.submit(get_live_contract_placements, today.isoformat()),
            "nb_thresholds":    pool.submit(get_nb_thresholds),
            "manual_nb":        pool.submit(get_manual_nb_clients),
            "alert_state":      pool.submit(get_nb_alert_state),
            "fx_rates":         pool.submit(get_fx_rates),
            "contract_entries": pool.submit(get_contract_entries),
            "solution_entries": pool.submit(get_solution_entries),
        }
        got = {}
        for name, fut in futs.items():
            try:
                got[name] = fut.result()
            except Exception:
                # FX and the alert state each have a working fallback; the
                # rest are load-bearing and must surface as a failure.
                if name not in ("fx_rates", "alert_state"):
                    raise
                logging.warning("report: %s unavailable, using fallback", name)
                got[name] = None

    fetch_ms = round((time.monotonic() - t0) * 1000)
    alert_state = {u: s["client_ids"] for u, s in (got["alert_state"] or {}).items()}

    report = build_report(got["consultants"], got["placements"], got["overrides"],
                          today, got["team_map"], got["live_contracts"],
                          got["fx_rates"], got["nb_thresholds"], got["contract_pl"],
                          got["manual_nb"],
                          nb_alert_state=alert_state,
                          contract_entries=got["contract_entries"],
                          solution_entries=got["solution_entries"])
    total_ms = round((time.monotonic() - t0) * 1000)
    return report, fetch_ms, total_ms - fetch_ms


@app.route(route="report-data", methods=["GET"])
def report_data(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_auth(req)
    if err:
        return err
    try:
        today = date.today()
        report, fetch_ms, build_ms = _load_report(today)
        # Where the time went, so a slow load can be diagnosed from the payload
        # rather than guessed at: fetch is Dataverse, build is our own maths.
        logging.info("report-data: fetch %dms, build %dms", fetch_ms, build_ms)
        return func.HttpResponse(
            json.dumps({"ok": True, "report": report, "as_of": today.isoformat(),
                        "ms": {"fetch": fetch_ms, "build": build_ms,
                               "total": fetch_ms + build_ms}}),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as e:
        logging.exception("report-data error")
        return _server_error()


# ── /api/contract-screen (GET) — the contract desks, for a wall screen ────────
# Shown through OneUp, which cannot sign in, so the route is anonymous and
# guarded by a key carried in the screen's own URL. The figures are the weekly
# report's, cached for a few minutes so a screen polling every five does not
# rebuild the whole report each time.

_SCREEN_CACHE = {"at": 0.0, "body": None}
_SCREEN_TTL_S = 300


@app.route(route="contract-screen", methods=["GET"])
def contract_screen(req: func.HttpRequest) -> func.HttpResponse:
    import hmac, time
    expected = os.environ.get("SCREEN_KEY") or ""
    supplied = req.params.get("key") or req.headers.get("x-screen-key") or ""
    if not expected or not hmac.compare_digest(expected, supplied):
        return func.HttpResponse("Forbidden", status_code=403)
    try:
        now = time.monotonic()
        if _SCREEN_CACHE["body"] and now - _SCREEN_CACHE["at"] < _SCREEN_TTL_S:
            return func.HttpResponse(_SCREEN_CACHE["body"],
                                     mimetype="application/json", status_code=200)

        today = date.today()
        report, _, _ = _load_report(today)

        def desk(territory, label):
            tdata = report.get(territory) or {}
            members = (tdata.get("members") or []) if tdata.get("type") == "flat" else \
                      [m for g in tdata.get("groups", []) for m in g["members"]]
            rows = []
            for m in members:
                if str(m["uid"]).endswith("__hist"):
                    continue
                # Everyone on the desk is shown, zeros included — a new starter
                # belongs on the wall with the team. Directors are not, and
                # the house accounts are not people.
                if "director" in (m.get("role") or "").lower():
                    continue
                if (m.get("name") or "").lower().startswith("saragossa house"):
                    continue
                wnf = m.get("wnf") or 0
                ytd = m.get("margin_ytd") or 0
                l12 = m.get("contract_last12m") or 0
                rows.append({"name": m.get("name"), "wnf": round(wnf, 2),
                             "ytd": round(ytd, 2), "l12": round(l12, 2)})
            # Highest WNF at the top; ties settle on YTD so the order is stable.
            rows.sort(key=lambda r: (-r["wnf"], -r["ytd"]))
            return {
                "label": label,
                "currency": "GBP" if territory == "London Contract" else "USD",
                "sym": "£" if territory == "London Contract" else "$",
                "rows": rows,
                "totals": {k: round(sum(r[k] for r in rows), 2) for k in ("wnf", "ytd", "l12")},
            }

        body = json.dumps({
            "ok": True,
            "as_of": today.isoformat(),
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "desks": [desk("London Contract", "Contract UK"),
                      desk("Chicago Contract", "Contract USA")],
        })
        _SCREEN_CACHE.update(at=now, body=body)
        return func.HttpResponse(body, mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("contract-screen error")
        return _server_error()


# ── /api/settings (GET) ───────────────────────────────────────────────────────

@app.route(route="settings", methods=["GET"])
def settings_get(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err

    try:
        consultants    = get_active_consultants()
        overrides      = get_overrides()
        all_users      = get_all_active_users()
        finance_uids   = get_finance_team_members()

        # Build a simple territory name lookup
        tid_to_name = {v: k for k, v in TERRITORY_IDS.items()}

        users = [
            {
                "uid":       c["systemuserid"],
                "name":      c.get("fullname", ""),
                "role":      c.get("title", ""),
                "territory": tid_to_name.get(c.get("_territoryid_value"), "Unknown"),
                "createdon": c.get("createdon", ""),
            }
            for c in consultants
        ]

        return func.HttpResponse(
            json.dumps({"ok": True, "users": users, "overrides": overrides,
                        "all_active_users": all_users, "finance_member_uids": finance_uids,
                        "nb_thresholds": get_nb_thresholds(),
                        "manual_nb_clients": get_manual_nb_clients()}),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as e:
        logging.exception("settings GET error")
        return _server_error()


# ── /api/settings (POST) ──────────────────────────────────────────────────────

@app.route(route="settings", methods=["POST"])
def settings_post(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err

    try:
        body = req.get_json()
        if not body or not body.get("userid"):
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "userid is required"}),
                mimetype="application/json",
                status_code=400,
            )

        result = upsert_override(body, updated_by=email)
        return func.HttpResponse(
            json.dumps({"ok": True, "override": result}),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as e:
        logging.exception("settings POST error")
        return _server_error()


# ── /api/clients (GET) — search client accounts for the NB-client picker ──────

@app.route(route="clients", methods=["GET"])
def clients_search(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    q = (req.params.get("q") or "").strip()
    if len(q) < 2:
        return func.HttpResponse(
            json.dumps({"ok": True, "results": []}),
            mimetype="application/json", status_code=200,
        )
    try:
        return func.HttpResponse(
            json.dumps({"ok": True, "results": search_accounts(q)}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("clients search error")
        return _server_error()


# ── /api/nb-clients (POST add / DELETE remove) — manual NB client credit ───────

@app.route(route="nb-clients", methods=["POST"])
def nb_clients_post(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    try:
        body = req.get_json() or {}
        uid, cid, cname = body.get("userid"), body.get("client_id"), body.get("client_name")
        if not is_guid(uid) or not is_guid(cid):
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "userid and client_id must be valid ids"}),
                mimetype="application/json", status_code=400,
            )
        add_manual_nb_client(uid, cid, cname or "")
        return func.HttpResponse(
            json.dumps({"ok": True, "manual_nb_clients": get_manual_nb_clients()}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("nb-clients POST error")
        return _server_error()


@app.route(route="nb-clients/{rowid}", methods=["DELETE"])
def nb_clients_delete(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    rowid = req.route_params.get("rowid")
    if not rowid or not is_guid(rowid):
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "valid rowid required"}),
            mimetype="application/json", status_code=400,
        )
    try:
        remove_manual_nb_client(rowid)
        return func.HttpResponse(
            json.dumps({"ok": True, "manual_nb_clients": get_manual_nb_clients()}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("nb-clients DELETE error")
        return _server_error()


# ── /api/nb-alert-clients — per-consultant alert credit management ─────────────
# GET  ?uid=…  → their rolling NB clients with consumed (already-alerted) flags
# POST {userid, consumed_client_ids} → mark clients as counted by a past alert

def _nb_rolling_window():
    """Same rolling-12-month window compute_metrics uses."""
    today = date.today()
    start = date(today.year - 1, today.month, today.day + 1 if today.day < 28 else today.day)
    return start.isoformat(), today.isoformat()


def _nb_current_clients(uid: str) -> dict:
    """{client_id: name} for a consultant — placements as CRO + manual additions."""
    start, end = _nb_rolling_window()
    clients = get_nb_clients_for_cro(uid, start, end)
    for c in get_manual_nb_clients().get(uid, []):
        if c.get("id"):
            clients[c["id"]] = c.get("name") or "(client)"
    return clients


@app.route(route="nb-alert-clients", methods=["GET"])
def nb_alert_clients_get(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    uid = req.params.get("uid")
    if not uid or not is_guid(uid):
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "valid uid required"}),
            mimetype="application/json", status_code=400,
        )
    try:
        clients  = _nb_current_clients(uid)
        state    = get_nb_alert_state().get(uid)
        consumed = state["client_ids"] if state else set()
        out = [{"id": cid, "name": name, "consumed": cid in consumed}
               for cid, name in sorted(clients.items(), key=lambda kv: kv[1].lower())]
        return func.HttpResponse(
            json.dumps({"ok": True, "clients": out}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("nb-alert-clients GET error")
        return _server_error()


@app.route(route="nb-alert-clients", methods=["POST"])
def nb_alert_clients_post(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    try:
        body = req.get_json() or {}
        uid  = body.get("userid")
        if not uid or not is_guid(uid):
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "valid userid required"}),
                mimetype="application/json", status_code=400,
            )
        posted  = {c for c in (body.get("consumed_client_ids") or []) if c}
        clients = _nb_current_clients(uid)
        state   = get_nb_alert_state().get(uid)
        existing = state["client_ids"] if state else set()
        # Keep consumed ids that have aged out of the window; only edit current ones
        preserved    = existing - set(clients.keys())
        new_consumed = preserved | (posted & set(clients.keys()))
        if new_consumed:
            upsert_nb_alert_state(uid, new_consumed, state["rowid"] if state else None)
        elif state:
            delete_nb_alert_state(state["rowid"])
        return func.HttpResponse(
            json.dumps({"ok": True}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("nb-alert-clients POST error")
        return _server_error()


# ── /api/contract-entries (POST) — manual monthly contract ledger ─────────────

@app.route(route="contract-entries", methods=["POST"])
def contract_entries_post(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    try:
        body = req.get_json() or {}
        uid  = body.get("userid")
        rows = body.get("entries") or []
        if not uid or not is_guid(uid):
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "valid userid required"}),
                mimetype="application/json", status_code=400,
            )
        clean = []
        for e in rows:
            try:
                year, month = int(e["year"]), int(e["month"])
                if not (1 <= month <= 12) or not (2000 <= year <= 2100):
                    raise ValueError
                amount = e.get("amount")
                clean.append({"year": year, "month": month,
                              "amount": float(amount) if amount is not None else None})
            except (KeyError, TypeError, ValueError):
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "entries need valid year/month/amount"}),
                    mimetype="application/json", status_code=400,
                )
        upsert_contract_entries(uid, clean)
        return func.HttpResponse(
            json.dumps({"ok": True, "contract_entries": get_contract_entries()}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("contract-entries POST error")
        return _server_error()


# ── /api/solution-entries (POST) — Deploy & Consult monthly ledger ───────────

@app.route(route="solution-entries", methods=["POST"])
def solution_entries_post(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    try:
        body = req.get_json() or {}
        uid  = body.get("userid")
        rows = body.get("entries") or []
        if not uid or not is_guid(uid):
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "valid userid required"}),
                mimetype="application/json", status_code=400,
            )
        clean = []
        for e in rows:
            try:
                year, month = int(e["year"]), int(e["month"])
                if not (1 <= month <= 12) or not (2000 <= year <= 2100):
                    raise ValueError
                amount = e.get("amount")
                clean.append({"year": year, "month": month,
                              "amount": float(amount) if amount is not None else None})
            except (KeyError, TypeError, ValueError):
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "entries need valid year/month/amount"}),
                    mimetype="application/json", status_code=400,
                )
        upsert_solution_entries(uid, clean)
        return func.HttpResponse(
            json.dumps({"ok": True, "solution_entries": get_solution_entries()}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("solution-entries POST error")
        return _server_error()


# ── /api/commission-import (POST) — load finance's monthly workbook ───────────
# Two passes: "preview" parses and matches names but writes nothing, so the
# figures can be eyeballed first; "commit" replaces that month outright.

@app.route(route="commission-import", methods=["POST"])
def commission_import_post(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    try:
        import base64
        from shared.commission_import import (
            parse_workbook, match_to_users, month_from_filename)
        from shared.dataverse import (get_all_named_users,
                                      get_all_territory_consultants,
                                      replace_month_entries)

        body = req.get_json() or {}
        filename = str(body.get("filename") or "")
        try:
            data = base64.b64decode(body.get("file") or "", validate=True)
        except Exception:
            data = b""
        if not data:
            return _bad_request("no file uploaded")

        try:
            parsed = parse_workbook(data)
        except ValueError as exc:
            return _bad_request(str(exc))

        detected = month_from_filename(filename)
        year, month = body.get("year"), body.get("month")
        if year and month:
            year, month = int(year), int(month)
        elif detected:
            year, month = detected
        else:
            return _bad_request(
                "Could not tell which month this workbook covers from its name — "
                "pick the month and try again.")
        if not (1 <= month <= 12) or not (2000 <= year <= 2100):
            return _bad_request("invalid year/month")

        # Names are matched against every Mercury user, but only people the
        # weekly report actually shows are imported — the rest (the generic
        # Saragossa House account, leavers whose territory was cleared) are
        # listed as ignored so the shortfall against the sheet total is visible.
        m = match_to_users(parsed["totals"], get_all_named_users())
        shown = {c["systemuserid"] for c in get_all_territory_consultants()}
        # The ledger page sends the consultants it actually has a row for, which
        # is narrower than territory membership (a leaver only appears on the
        # report if they wrote something) and keeps a contract workbook from
        # writing against a perm desk. Intersected, never widened.
        on_page = body.get("allowed_uids")
        if isinstance(on_page, list) and on_page:
            shown &= {u for u in on_page if isinstance(u, str)}
        matched = [r for r in m["matched"] if r["uid"] in shown]
        ignored = [{"name": r["name"], "amount": r["amount"]}
                   for r in m["matched"] if r["uid"] not in shown]
        result = {
            "ok": True, "kind": parsed["kind"], "year": year, "month": month,
            "detected_month": bool(detected), "rows": parsed["rows"],
            "sheets_used": parsed["sheets_used"],
            "sheets_skipped": parsed["sheets_skipped"],
            "matched": matched, "unmatched": m["unmatched"], "ignored": ignored,
            "total": round(sum(parsed["totals"].values()), 2),
            "matched_total": round(sum(r["amount"] for r in matched), 2),
        }

        if body.get("mode") == "commit":
            # One row per consultant; a name appearing twice in Mercury is
            # already collapsed to a single user id by match_to_users.
            amounts = {}
            for row in matched:
                amounts[row["uid"]] = amounts.get(row["uid"], 0) + row["amount"]
            counts = replace_month_entries(parsed["kind"], year, month, amounts)
            logging.info("commission import by %s: %s %s-%02d %s",
                         email, parsed["kind"], year, month, counts)
            result.update(committed=True, **counts)
        else:
            result["committed"] = False
        return func.HttpResponse(json.dumps(result),
                                 mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("commission-import error")
        return _server_error()


# ── /api/board-note (GET/POST) — commentary for the board email ───────────────
# What has happened since the last board meeting, in Jason's words. Keyed by
# the month the board report covers, which is the previous full month.
#
# Narrower than admin on purpose: admin is every Director plus the whole
# Bristol Finance and Compliance team, ~22 people, any of whom could rewrite
# or wipe the commentary with no record of who did. This is one person's voice
# in the board pack, so the list is explicit (Jason, Sep 2026).

BOARD_NOTE_AUTHORS = {"jason@saragossa.io"}


def _require_board_note_author(req: func.HttpRequest):
    email, err = require_auth(req)
    if err:
        return None, err
    if (email or "").lower() not in BOARD_NOTE_AUTHORS:
        return None, func.HttpResponse("Forbidden — board commentary is restricted",
                                       status_code=403)
    return email, None


def _board_note_period(today: date = None) -> str:
    from shared.board import board_note_period
    return board_note_period(today)


@app.route(route="board-note", methods=["GET", "POST"])
def board_note(req: func.HttpRequest) -> func.HttpResponse:
    email, err = _require_board_note_author(req)
    if err:
        return err
    from shared.board import NOTE_SECTIONS, parse_note, serialise_note
    from shared.dataverse import get_board_note, upsert_board_note
    try:
        body = req.get_json() if req.method == "POST" else {}
    except ValueError:
        body = {}
    try:
        period = ((body or {}).get("period") or req.params.get("period")
                  or _board_note_period())
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            return _bad_request("period must be YYYY-MM")
        if req.method == "POST":
            # "sections" is what the page sends; "body" is the older single-box
            # shape, still accepted so an old tab left open can't wipe a note.
            sent = (body or {}).get("sections")
            if sent is None:
                sent = parse_note((body or {}).get("body") or "")
            if not isinstance(sent, dict):
                return _bad_request("sections must be an object")
            upsert_board_note(period, serialise_note(sent), email)
        note = get_board_note(period)
        y, m = int(period[:4]), int(period[5:])
        return func.HttpResponse(json.dumps({
            "ok": True, "period": period,
            "period_label": f"{date(y, m, 1):%B %Y}",
            "sections": parse_note(note.get("body")),
            "labels": [{"key": k, "label": lb} for k, lb in NOTE_SECTIONS],
            **note,
        }), mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("board-note error")
        return _server_error()


# ── /api/board-report (POST) — email the board figures to the requester ───────

@app.route(route="board-report", methods=["POST"])
def board_report_post(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    try:
        from shared.board import compose_board_email
        from shared.calc import build_admin_report as _bar
        from shared.dataverse import graph_send_mail
        sender = os.environ.get("ALERT_SENDER")
        if not sender:
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "ALERT_SENDER not configured"}),
                mimetype="application/json", status_code=500,
            )
        subject, text, html, images = compose_board_email(_bar)
        # Always copy in the standing board recipients alongside the requester
        extras = [e.strip() for e in
                  os.environ.get("BOARD_REPORT_EXTRA_RECIPIENTS", "").split(",") if e.strip()]
        recipients = list(dict.fromkeys([email] + extras))
        graph_send_mail(sender, recipients, subject, text, body_html=html,
                        inline_images=images)
        return func.HttpResponse(
            json.dumps({"ok": True, "sent_to": ", ".join(recipients)}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("board-report error")
        return _server_error()


# ── /api/board-schedule — plan future board sends (admin only) ────────────────
# GET    → upcoming + recently sent schedules
# POST   {send_at: ISO-8601 UTC, recipients?: [..]} → add
# DELETE ?id=…  → cancel a pending schedule

@app.route(route="board-schedule", methods=["GET", "POST", "DELETE"])
def board_schedule(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    from shared.dataverse import (add_board_schedule, delete_board_schedule,
                                  get_board_schedules, is_guid)
    try:
        if req.method == "GET":
            return func.HttpResponse(
                json.dumps({"ok": True, "schedules": [
                    {k: v for k, v in s.items() if k != "send_at_dt"}
                    for s in get_board_schedules()
                ]}),
                mimetype="application/json", status_code=200,
            )

        if req.method == "POST":
            body = req.get_json() or {}
            raw = (body.get("send_at") or "").strip()
            try:
                when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "Invalid send_at — expected ISO 8601"}),
                    mimetype="application/json", status_code=400,
                )
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            when = when.astimezone(timezone.utc)
            if when <= datetime.now(timezone.utc):
                return func.HttpResponse(
                    json.dumps({"ok": False, "error": "That time is in the past"}),
                    mimetype="application/json", status_code=400,
                )
            recipients = [str(r).strip() for r in (body.get("recipients") or []) if str(r).strip()]
            for r in recipients:
                if not r.lower().endswith("@saragossa.io"):
                    return func.HttpResponse(
                        json.dumps({"ok": False, "error": f"Not a Saragossa address: {r}"}),
                        mimetype="application/json", status_code=400,
                    )
            add_board_schedule(when.strftime("%Y-%m-%dT%H:%M:%SZ"), recipients, email)
            return func.HttpResponse(
                json.dumps({"ok": True, "schedules": [
                    {k: v for k, v in s.items() if k != "send_at_dt"}
                    for s in get_board_schedules()
                ]}),
                mimetype="application/json", status_code=200,
            )

        rowid = req.params.get("id") or ""
        if not is_guid(rowid):
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "Invalid id"}),
                mimetype="application/json", status_code=400,
            )
        delete_board_schedule(rowid)
        return func.HttpResponse(
            json.dumps({"ok": True, "schedules": [
                {k: v for k, v in s.items() if k != "send_at_dt"}
                for s in get_board_schedules()
            ]}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("board-schedule error")
        return _server_error()


# ── /api/feedback (POST) — send pilot feedback to Jason ───────────────────────
# Any authenticated Saragossa user can send; the sender is taken from their
# login rather than typed, so feedback can't be attributed to someone else.

@app.route(route="feedback", methods=["POST"])
def feedback(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_auth(req)
    if err:
        return err
    try:
        body = req.get_json() or {}
    except ValueError:
        body = {}
    message = (body.get("message") or "").strip()
    if not message:
        return func.HttpResponse(json.dumps({"ok": False, "error": "Please write something first."}),
                                 mimetype="application/json", status_code=400)
    if len(message) > 8000:
        message = message[:8000] + "…"

    sender = os.environ.get("ALERT_SENDER")
    to = [r.strip() for r in
          os.environ.get("FEEDBACK_RECIPIENT", "jason@saragossa.io").split(",") if r.strip()]
    if not sender or not to:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "Feedback email is not configured."}),
            mimetype="application/json", status_code=500)

    from html import escape
    from shared.dataverse import graph_send_mail
    page = (body.get("page") or "the app")[:80]
    context = (body.get("context") or "")[:200]
    try:
        subject = f"App feedback · {page} · {email}"
        text = f"From: {email}\nPage: {page}\n{context}\n\n{message}"
        html = (
            '<div style="font-family:Arial,Helvetica,sans-serif;color:#101820;">'
            f'<p style="margin:0 0 4px;font-size:12px;color:#5a6b6e;">'
            f'Feedback from <strong>{escape(email)}</strong> · {escape(page)}'
            + (f' · {escape(context)}' if context else "") + '</p>'
            f'<div style="white-space:pre-wrap;font-size:14px;border-left:3px solid #c8a84b;'
            f'padding:8px 0 8px 12px;margin-top:12px;">{escape(message)}</div></div>')
        graph_send_mail(sender, to, subject, text, body_html=html)
        return func.HttpResponse(json.dumps({"ok": True}),
                                 mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("feedback error")
        return _server_error()


# ── Weekly 1:1 (pilot — Team Snoz) ────────────────────────────────────────────
# ── /api/one-to-one — weekly 1:1s ─────────────────────────────────────────────
# Which team gets which questions, and who may see whom, lives in
# shared/oto_templates.py. This endpoint resolves the caller's templates,
# builds the derived half for the chosen one, and stores the typed half.

# Sees every template and every person. Kept explicit rather than tied to the
# general admin rule (any Director), which would put Harry's team's 1:1s in
# front of every director in the business.
ONE_TO_ONE_ADMINS = {"jason@saragossa.io"}

# What each template's save keeps — the typed half, nothing derived.
_OTO_KEEP = {
    "perm": ("actions", "live_job_notes", "resourcing_priority", "next_placement",
             "next_job", "bd_existing", "bd_new", "meetings_last_outcome",
             "meetings_this_plan", "mbr_progress", "priority_resourcing",
             "priority_bd", "support_needed"),
    "contract": ("actions", "committed", "chances_week", "chances_month",
                 "chances_other", "blocks", "meeting_plans"),
}


@app.route(route="one-to-one", methods=["GET", "POST"])
def one_to_one(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_auth(req)
    if err:
        return err
    from shared.dataverse import (VACANCY_CLOSE_REASONS, get_one_to_one, upsert_one_to_one,
                                  list_one_to_one_weeks, get_latest_mbr_actions, is_guid)
    from shared.oneonone import (build_one_to_one, week_start, default_week,
                                 quarter_weeks, INPUT_ROWS)
    from shared.oneonone_contract import build_contract_one_to_one
    from shared.oto_templates import templates_for
    try:
        body = req.get_json() if req.method == "POST" else {}
    except ValueError:
        body = {}
    try:
        is_admin_user = (email or "").lower() in ONE_TO_ONE_ADMINS
        templates = templates_for(email, is_admin_user)
        if not templates:
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "You are not on a team that uses 1:1s yet."}),
                mimetype="application/json", status_code=403)

        wanted = (req.params.get("template") or (body or {}).get("template") or "").strip()
        tpl = next((t for t in templates if t["id"] == wanted), None) or templates[0]
        people, is_lead = tpl["people"], tpl["is_lead"]

        uid = (req.params.get("uid") or (body or {}).get("uid")
               or people[0]["systemuserid"]).strip()
        person = next((p for p in people if p["systemuserid"] == uid), None)
        if not is_guid(uid) or not person:
            return func.HttpResponse(json.dumps({"ok": False, "error": "forbidden"}),
                                     mimetype="application/json", status_code=403)

        raw = req.params.get("week") or (body or {}).get("week")
        try:
            wk = week_start(date.fromisoformat(raw)) if raw else default_week(tpl["kind"])
        except ValueError:
            return func.HttpResponse(json.dumps({"ok": False, "error": "bad week"}),
                                     mimetype="application/json", status_code=400)

        if req.method == "POST":
            from shared.ai_readiness import latest_score
            payload = {k: (body or {}).get(k) for k in _OTO_KEEP[tpl["kind"]]}
            payload["template"] = tpl["id"]
            # The AI Readiness score is captured on the FIRST save and kept, so
            # the record shows the score that was discussed rather than drifting
            # every time someone corrects a typo. A failed fetch stores nothing,
            # leaving a later save free to capture it.
            existing = get_one_to_one(uid, wk.isoformat()) or {}
            payload["ai_readiness"] = existing.get("ai_readiness") or latest_score(uid)
            upsert_one_to_one(uid, wk.isoformat(), payload)
            return func.HttpResponse(json.dumps({"ok": True}),
                                     mimetype="application/json", status_code=200)

        from datetime import timedelta as _td
        from shared.ai_readiness import for_display, latest_score
        derived = (build_contract_one_to_one(uid, wk) if tpl["kind"] == "contract"
                   else build_one_to_one(uid, wk))
        saved = get_one_to_one(uid, wk.isoformat())
        prev = get_one_to_one(uid, (wk - _td(days=7)).isoformat())
        # Saved records show the score as it was; an unsaved one shows today's.
        frozen = (saved or {}).get("ai_readiness")
        ai = for_display(frozen, live=False) if frozen else for_display(latest_score(uid), live=True)
        return func.HttpResponse(json.dumps({
            "ok": True, "is_lead": is_lead, "is_admin": is_admin_user,
            "template": {"id": tpl["id"], "name": tpl["name"], "kind": tpl["kind"]},
            # Every template this person can see, so the page can offer a switch
            "templates": [{"id": t["id"], "name": t["name"], "kind": t["kind"]} for t in templates],
            "ai_readiness": ai,
            "person": {"uid": uid, "name": person.get("fullname", "")},
            "people": [{"uid": p["systemuserid"], "name": p.get("fullname", "")} for p in people],
            "input_rows": [{"key": k, "label": l} for k, l in INPUT_ROWS],
            "close_reasons": [{"code": c, "label": lb} for c, lb in VACANCY_CLOSE_REASONS],
            **derived,
            "saved": saved,
            "carried_actions": (prev or {}).get("actions") or [],
            "mbr_actions": get_latest_mbr_actions(uid),
            "quarter": {**quarter_weeks(wk), "completed": sorted(list_one_to_one_weeks(uid))},
        }), mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("one-to-one error")
        return _server_error()


# ── /api/close-vacancy (POST) — close a job from the 1:1 ──────────────────────
# Writes straight into Mercury, so the guard rails matter more than the code:
#   * only a reason from VACANCY_CLOSE_REASONS, never an arbitrary statuscode;
#   * only a vacancy whose delivery owner is someone whose 1:1 the caller may
#     open — the same rule that decides what they can see;
#   * only a vacancy that is still open, so a second click cannot overwrite
#     the reason someone already recorded.

@app.route(route="close-vacancy", methods=["POST"])
def close_vacancy_route(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_auth(req)
    if err:
        return err
    from shared.dataverse import (VACANCY_CLOSE_CODES, close_vacancy, get_vacancy,
                                  is_guid)
    from shared.oto_templates import templates_for
    try:
        body = req.get_json() or {}
    except ValueError:
        return _bad_request("expected JSON")
    try:
        vid = str(body.get("vacancy_id") or "").strip()
        try:
            reason = int(body.get("statuscode"))
        except (TypeError, ValueError):
            return _bad_request("statuscode must be a number")
        if not is_guid(vid):
            return _bad_request("bad vacancy_id")
        if reason not in VACANCY_CLOSE_CODES:
            return _bad_request("that is not a closing reason")

        is_admin_user = (email or "").lower() in ONE_TO_ONE_ADMINS
        mine = {p["systemuserid"] for t in templates_for(email, is_admin_user)
                for p in t["people"]}
        if not mine:
            return func.HttpResponse(json.dumps({"ok": False, "error": "forbidden"}),
                                     mimetype="application/json", status_code=403)

        vac = get_vacancy(vid)
        if not vac:
            return func.HttpResponse(json.dumps({"ok": False, "error": "No such vacancy."}),
                                     mimetype="application/json", status_code=404)
        if vac.get("_crimson_deliveryownerid_value") not in mine:
            logging.warning("%s tried to close a vacancy outside their teams", email)
            return func.HttpResponse(json.dumps({"ok": False, "error": "forbidden"}),
                                     mimetype="application/json", status_code=403)
        if vac.get("statecode") != 0:
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "That job is already closed."}),
                mimetype="application/json", status_code=409)

        close_vacancy(vid, reason)
        logging.info("%s closed vacancy %s (%s) as %s",
                     email, vid, vac.get("crimson_jobtitle"), reason)
        return func.HttpResponse(json.dumps({"ok": True}),
                                 mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("close-vacancy error")
        return _server_error()


# ── Performance Stats (pilot) ─────────────────────────────────────────────────
# Contract desk dashboard, piloted with Jim Jeffers and Andrew Turton.
# Access is an explicit allowlist while it is a pilot — widen it here, or move
# it to a table if it outgrows a handful of people.

PERF_STATS_ALLOWED = {
    "jim@saragossa.io",        # Jim Jeffers — Contract Sales Director
    "andrewt@saragossa.io",    # Andrew Turton — Regional Director, Chicago
    "jason@saragossa.io",      # owner/support
}


@app.route(route="performance-stats", methods=["GET"])
def performance_stats(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_auth(req)
    if err:
        return err
    if (email or "").lower() not in PERF_STATS_ALLOWED:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "This dashboard is limited to the pilot group."}),
            mimetype="application/json", status_code=403)
    try:
        from shared.perfstats import build_performance_stats
        return func.HttpResponse(json.dumps({"ok": True, **build_performance_stats()}),
                                 mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("performance-stats error")
        return _server_error()


# ── MBR (beta) ────────────────────────────────────────────────────────────────
# GET  /api/mbr-people                     → who this user may open
# GET  /api/mbr?uid=&year=&month=          → metrics, prompts, saved form, carry-forward
# POST /api/mbr                            → save the judgement fields and actions
# GET/POST /api/mbr-targets                → per-person monthly targets (admin)

def _mbr_visible_people(email: str):
    """
    (people, can_manage) — MBR visibility, deliberately NOT the analytics admin
    check: reading someone's performance conversation is a different permission
    from reading revenue. Rules, additive:
      - your own MBR
      - your team, if you are flagged a team lead
      - the territories granted to you in crbb7_mbrscope ("*" = all)
    """
    from shared.dataverse import (get_all_territory_consultants, get_team_membership_map,
                                  get_overrides, get_mbr_scopes, get_territory_name)
    from shared.dataverse import odata_get_all, odata_str
    people = [c for c in get_all_territory_consultants() if not c.get("isdisabled")]
    # Resolve the caller from ALL Mercury users, not just the six consultant
    # territories — directors sit outside them (Jason's user is in "Testing"),
    # so looking them up in `people` would silently deny their own grant.
    me = next((u for u in odata_get_all("systemusers", params={
        "$select": "systemuserid,fullname,title,internalemailaddress",
        "$filter": (f"internalemailaddress eq '{odata_str(email)}'"
                    f" and isdisabled eq false"),
    })), None)
    scopes = get_mbr_scopes()

    # Grants are the authority. Deliberately NOT the analytics admin check:
    # finance and analytics access must not carry into performance conversations.
    if scopes is None:
        # Table unreadable — fall back to Director title so the module can never
        # lock everyone out (including out of the screen that fixes the grants).
        logging.warning("MBR scope table unreadable — falling back to Director titles")
        if "director" in ((me or {}).get("title") or "").lower():
            return people, True
        scopes = {}

    my_scope = scopes.get(me["systemuserid"]) if me else None
    if my_scope and "*" in my_scope:
        return people, True
    if not me:
        return [], False

    visible = {me["systemuserid"]: me}
    overrides = {o["crbb7_userid"]: o for o in get_overrides()}
    if (overrides.get(me["systemuserid"]) or {}).get("crbb7_isteamlead"):
        teams = get_team_membership_map()
        my_team = teams.get(me["systemuserid"])
        if my_team:
            for c in people:
                if teams.get(c["systemuserid"]) == my_team:
                    visible[c["systemuserid"]] = c
    for c in people:
        if my_scope and get_territory_name(c.get("_territoryid_value")) in my_scope:
            visible[c["systemuserid"]] = c
    return list(visible.values()), False


@app.route(route="mbr-people", methods=["GET"])
def mbr_people(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_auth(req)
    if err:
        return err
    try:
        people, admin = _mbr_visible_people(email)
        return func.HttpResponse(json.dumps({
            "ok": True, "is_admin": admin,
            "people": [{"uid": p["systemuserid"], "name": p.get("fullname", ""),
                        "email": p.get("internalemailaddress", "")} for p in
                       sorted(people, key=lambda x: x.get("fullname") or "")],
        }), mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("mbr-people error")
        return _server_error()


@app.route(route="mbr", methods=["GET", "POST"])
def mbr(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_auth(req)
    if err:
        return err
    from shared.dataverse import get_mbr, upsert_mbr, get_mbr_targets, is_guid
    try:
        body = req.get_json() if req.method == "POST" else {}
    except ValueError:
        body = {}
    uid = (req.params.get("uid") or (body or {}).get("uid") or "").strip()
    if not is_guid(uid):
        return func.HttpResponse(json.dumps({"ok": False, "error": "valid uid required"}),
                                 mimetype="application/json", status_code=400)
    try:
        people, is_admin_user = _mbr_visible_people(email)
        person = next((p for p in people if p["systemuserid"] == uid), None)
        if not person:
            return func.HttpResponse(json.dumps({"ok": False, "error": "forbidden"}),
                                     mimetype="application/json", status_code=403)

        today = date.today()
        py, pm = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        year  = int(req.params.get("year")  or (body or {}).get("year")  or py)
        month = int(req.params.get("month") or (body or {}).get("month") or pm)
        if not (1 <= month <= 12 and 2000 <= year <= 2100):
            return func.HttpResponse(json.dumps({"ok": False, "error": "bad period"}),
                                     mimetype="application/json", status_code=400)

        if req.method == "POST":
            from shared.ai_readiness import month_score
            payload = {k: (body or {}).get(k) for k in
                       ("positives", "improve", "aspirations", "support", "actions", "commentary")}
            existing = get_mbr(uid, year, month) or {}
            # Carry over what a save must not lose: the Claude prompts already
            # generated for this month (or every save would bill another call),
            # and the AI Readiness score, captured on the first save and kept.
            if existing.get("prompt_cache"):
                payload["prompt_cache"] = existing["prompt_cache"]
            payload["ai_readiness"] = existing.get("ai_readiness") or month_score(uid, year, month)
            upsert_mbr(uid, year, month, payload, (body or {}).get("status") or "draft")
            return func.HttpResponse(json.dumps({"ok": True}),
                                     mimetype="application/json", status_code=200)

        from shared.mbr import build_mbr_metrics, previous_month
        from shared.mbr_prompts import generate_prompts, pick_flagged
        from shared.mbr_registry import DEFAULT_TARGETS

        from shared.ai_readiness import for_display, month_score

        data    = build_mbr_metrics(uid, year, month)
        targets = {**DEFAULT_TARGETS, **(get_mbr_targets(uid).get(uid) or {})}
        saved   = get_mbr(uid, year, month)
        ly, lm  = previous_month(year, month)
        last    = get_mbr(uid, ly, lm)

        # This month's score: as saved, or live until it is. Last month's comes
        # only from its own saved MBR — nothing is fetched for the past.
        frozen = (saved or {}).get("ai_readiness")
        ai = (for_display(frozen, live=False) if frozen
              else for_display(month_score(uid, year, month), live=True))
        ai_prev = for_display((last or {}).get("ai_readiness"), live=False)

        flagged = pick_flagged(data["metrics"], targets)
        # Reuse the prompts already generated for this month unless the flagged
        # set has changed — otherwise every page load would bill another call,
        # and the questions would shift under the consultant mid-meeting.
        cached = (saved or {}).get("prompt_cache") or {}
        keys = [f["key"] for f in flagged]
        # Only a real generation is worth reusing — never pin template fallbacks,
        # or adding the API key later would have no effect.
        if (cached.get("keys") == keys and cached.get("prompts")
                and cached.get("source") == "claude"):
            prompts = {"prompts": cached["prompts"], "summary": cached.get("summary"),
                       "source": "claude"}
        else:
            prompts = generate_prompts(person.get("fullname", ""), data["month"], flagged)
            if prompts.get("source") == "claude":
                try:
                    upsert_mbr(uid, year, month,
                               {**{k: v for k, v in (saved or {}).items()
                                   if k not in ("id", "status")},
                                "prompt_cache": {"keys": keys, **prompts}},
                               (saved or {}).get("status") or "draft")
                except Exception:
                    logging.warning("Could not cache MBR prompts", exc_info=True)

        for m in data["metrics"]:
            m["target"] = targets.get(m["target_key"]) if m["target_key"] else None

        return func.HttpResponse(json.dumps({
            "ok": True, "person": {"uid": uid, "name": person.get("fullname", "")},
            **data, "targets": targets, "saved": saved,
            "ai_readiness": ai, "ai_readiness_prev": ai_prev,
            "carried_actions": (last or {}).get("actions") or [],
            "flagged": [f["key"] for f in flagged],
            **{k: v for k, v in prompts.items()
               if k != "error" or is_admin_user},
        }), mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("mbr error")
        return _server_error()


@app.route(route="mbr-scopes", methods=["GET", "POST"])
def mbr_scopes(req: func.HttpRequest) -> func.HttpResponse:
    """Who can open whose MBR. Only someone with full MBR access may change it."""
    email, err = require_auth(req)
    if err:
        return err
    from shared.dataverse import (get_mbr_scopes, upsert_mbr_scope, is_guid,
                                  get_all_territory_consultants, TERRITORY_IDS)
    try:
        _people, can_manage = _mbr_visible_people(email)
        if not can_manage:
            return func.HttpResponse(json.dumps({"ok": False, "error": "forbidden"}),
                                     mimetype="application/json", status_code=403)
        if req.method == "GET":
            users = [u for u in get_all_territory_consultants() if not u.get("isdisabled")]
            return func.HttpResponse(json.dumps({
                "ok": True, "scopes": get_mbr_scopes(),
                "territories": list(TERRITORY_IDS.keys()),
                "users": [{"uid": u["systemuserid"], "name": u.get("fullname", ""),
                           "title": u.get("title") or ""} for u in
                          sorted(users, key=lambda x: x.get("fullname") or "")],
            }), mimetype="application/json", status_code=200)

        body = req.get_json() or {}
        uid = (body.get("userid") or "").strip()
        if not is_guid(uid):
            return func.HttpResponse(json.dumps({"ok": False, "error": "valid userid required"}),
                                     mimetype="application/json", status_code=400)
        allowed = set(TERRITORY_IDS.keys()) | {"*"}
        terrs = [t for t in (body.get("territories") or []) if t in allowed]
        upsert_mbr_scope(uid, terrs)
        return func.HttpResponse(json.dumps({"ok": True, "scopes": get_mbr_scopes()}),
                                 mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("mbr-scopes error")
        return _server_error()


@app.route(route="mbr-targets", methods=["GET", "POST"])
def mbr_targets(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_auth(req)
    if err:
        return err
    _people, can_manage = _mbr_visible_people(email)
    if not can_manage:
        return func.HttpResponse(json.dumps({"ok": False, "error": "forbidden"}),
                                 mimetype="application/json", status_code=403)
    from shared.dataverse import get_mbr_targets, upsert_mbr_targets, is_guid
    from shared.mbr_registry import DEFAULT_TARGETS, TARGET_KEYS
    try:
        if req.method == "GET":
            return func.HttpResponse(json.dumps({
                "ok": True, "targets": get_mbr_targets(), "defaults": DEFAULT_TARGETS,
            }), mimetype="application/json", status_code=200)
        body = req.get_json() or {}
        uid = (body.get("userid") or "").strip()
        if not is_guid(uid):
            return func.HttpResponse(json.dumps({"ok": False, "error": "valid userid required"}),
                                     mimetype="application/json", status_code=400)
        clean = {}
        for key, value in (body.get("targets") or {}).items():
            if key not in TARGET_KEYS:
                continue
            clean[key] = None if value in (None, "") else float(value)
        upsert_mbr_targets(uid, clean)
        return func.HttpResponse(json.dumps({"ok": True, "targets": get_mbr_targets()}),
                                 mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("mbr-targets error")
        return _server_error()


# ── /api/board-schedule-run (POST) — fire due schedules ───────────────────────
# Called every minute by the Logic App scheduler. No user identity, so it is
# guarded by a shared key; GitHub's cron still runs as a backup and the
# "sent" stamp makes a double-fire impossible.

@app.route(route="board-schedule-run", methods=["POST"])
def board_schedule_run(req: func.HttpRequest) -> func.HttpResponse:
    import hmac
    expected = os.environ.get("SCHEDULE_RUNNER_KEY") or ""
    supplied = req.headers.get("x-api-key") or ""
    if not expected or not hmac.compare_digest(expected, supplied):
        logging.warning("board-schedule-run: bad or missing key")
        return func.HttpResponse("Forbidden", status_code=403)
    try:
        from shared.board_schedule import run_due_schedules
        result = run_due_schedules()
        return func.HttpResponse(
            json.dumps({"ok": True, **result}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("board-schedule-run error")
        return _server_error()


# ── /api/promotion-data (GET) — feed the promotion tracker ────────────────────
# Machine-to-machine, guarded by a shared key the way the ROI tracker is; an
# admin session is also accepted so the payload can be eyeballed in a browser.
#
# The tracker reads permanent placements from Mercury itself and works out its
# own rolling 12 months. The one thing it cannot see is the manual Deploy &
# Consult ledger, which counts toward promotion — so this returns exactly that,
# per consultant, BY MONTH, in the tracker's own "YYYY-MM" key format, ready to
# fold into its buckets.

@app.route(route="promotion-data", methods=["GET"])
def promotion_data(req: func.HttpRequest) -> func.HttpResponse:
    import hmac
    expected = os.environ.get("PROMOTION_TRACKER_KEY") or ""
    supplied = req.headers.get("x-api-key") or ""
    if not (expected and hmac.compare_digest(expected, supplied)):
        email, err = require_admin(req)
        if err:
            return err
    try:
        from shared.calc import (CCY_BY_TERRITORY, SOLUTION_PERM_START,
                                 _WRITTEN_CONTRACT_TERRITORIES)
        from shared.dataverse import (TERRITORY_IDS, get_all_territory_consultants,
                                      get_solution_entries)

        today = date.today()
        by_id = {tid: name for name, tid in TERRITORY_IDS.items()}
        ledger = get_solution_entries()

        people = []
        for c in get_all_territory_consultants():
            uid = c["systemuserid"]
            entries = ledger.get(uid)
            if not entries:
                continue
            territory = by_id.get(c.get("_territoryid_value"))
            # A perm desk counts this revenue only from April 2026; a contract
            # desk always has. The tracker covers perm desks only, but the flag
            # keeps the payload honest either way.
            is_contract = territory in _WRITTEN_CONTRACT_TERRITORIES
            months = {}
            for key, amount in entries.items():
                y, m = (int(p) for p in key.split("-"))
                if not is_contract and (y, m) < SOLUTION_PERM_START:
                    continue
                if amount:
                    # Zero-padded to match the tracker's own month keys.
                    months[f"{y}-{m:02d}"] = round(float(amount), 2)
            if not months:
                continue
            people.append({
                "uid": uid,
                "email": (c.get("internalemailaddress") or "").lower().strip() or None,
                "name": c.get("fullname"),
                "territory": territory,
                "is_contract": is_contract,
                # Ledger figures are stored in the desk's own currency.
                "currency": CCY_BY_TERRITORY.get(territory, "GBP"),
                "months": dict(sorted(months.items())),
                "total": round(sum(months.values()), 2),
            })

        people.sort(key=lambda p: (p["territory"] or "", p["name"] or ""))
        return func.HttpResponse(
            json.dumps({
                "ok": True,
                "as_of": today.isoformat(),
                # Deploy & Consult revenue per consultant, by month, for the
                # promotion tracker to fold into its own rolling window. It
                # reads placements from Mercury itself; this manual ledger is
                # the part it cannot see.
                "solution_counts_from": "%04d-%02d" % SOLUTION_PERM_START,
                "people": people,
            }),
            mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("promotion-data error")
        return _server_error()


# ── /api/screen-links (GET) — the wall-screen URLs, for the admin page ────────
# The key lives only in app settings; this is the one place it is handed out,
# and only to an admin, so a screen can be set up without anyone digging in
# the Azure portal.

@app.route(route="screen-links", methods=["GET"])
def screen_links(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    key = os.environ.get("SCREEN_KEY") or ""
    base = (os.environ.get("PUBLIC_BASE_URL") or "https://weeklyreport.saragossa.io").rstrip("/")
    if not key:
        return func.HttpResponse(json.dumps({"ok": False, "error": "SCREEN_KEY is not set"}),
                                 mimetype="application/json", status_code=200)
    from urllib.parse import quote
    q = quote(key, safe="")
    return func.HttpResponse(json.dumps({"ok": True, "links": [
        {"label": "Contract UK",  "note": "GBP",  "url": f"{base}/contract-screen?desk=uk&key={q}"},
        {"label": "Contract USA", "note": "USD",  "url": f"{base}/contract-screen?desk=usa&key={q}"},
        {"label": "Both desks",   "note": "side by side", "url": f"{base}/contract-screen?key={q}"},
    ]}), mimetype="application/json", status_code=200)


# ── /api/commission-sync (POST) — pull the workbooks from SharePoint ──────────
# Admin-triggered. Previews by default; ?commit=1 writes.

@app.route(route="commission-sync", methods=["POST"])
def commission_sync_post(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    try:
        from shared.commission_sync import SyncError, sync_year
        body = req.get_json() or {}
        year = int(body.get("year") or date.today().year)
        months = body.get("months") or None
        if months is not None:
            months = [int(m) for m in months]
        result = sync_year(year, months, commit=bool(body.get("commit")))
        return func.HttpResponse(json.dumps({"ok": True, **result}),
                                 mimetype="application/json", status_code=200)
    except SyncError as exc:
        return _bad_request(str(exc))
    except Exception:
        logging.exception("commission-sync error")
        return _server_error()


# ── /api/commission-sync-run (POST) — the monthly scheduled pull ──────────────
# Called by the Logic App. No user identity, so it is guarded by the same shared
# key as the board scheduler, and it only acts on the second Friday of a month
# unless forced. Importing a month twice is harmless — each import replaces it.

@app.route(route="commission-sync-run", methods=["POST"])
def commission_sync_run(req: func.HttpRequest) -> func.HttpResponse:
    import hmac
    expected = os.environ.get("SCHEDULE_RUNNER_KEY") or ""
    supplied = req.headers.get("x-api-key") or ""
    if not expected or not hmac.compare_digest(expected, supplied):
        logging.warning("commission-sync-run: bad or missing key")
        return func.HttpResponse("Forbidden", status_code=403)
    try:
        from shared.commission_sync import (SyncError, compose_report,
                                            is_second_friday, sync_year)
        def _flag(name):
            return (req.params.get(name) or "").lower() in ("1", "true", "yes")

        forced = _flag("force")
        # preview=1 walks the library and reports without writing or emailing —
        # how the wiring gets checked before a schedule is trusted with it.
        preview = _flag("preview")
        if not forced and not is_second_friday():
            return func.HttpResponse(json.dumps({"ok": True, "skipped": "not the second Friday"}),
                                     mimetype="application/json", status_code=200)

        today = date.today()
        # months=1,2,3 restricts a run. Left unset, a scheduled run does the
        # month that has just landed plus the one before it — enough to pick up
        # a restatement, while a whole-year sweep would outlast the 45-second
        # gateway limit even with the writes parallelised. A backfill is done
        # by passing months= explicitly, a few at a time.
        months = [int(m) for m in (req.params.get("months") or "").split(",")
                  if m.strip().isdigit()]
        if not months:
            from shared.calc import last_complete_ledger_month
            _, newest = last_complete_ledger_month(today)
            months = sorted({newest, 12 if newest == 1 else newest - 1})
        try:
            result = sync_year(today.year, months, commit=not preview)
            subject, text = compose_report(result)
            if preview:
                return func.HttpResponse(json.dumps({"ok": True, "preview": True,
                                                     "report": text, **result}),
                                         mimetype="application/json", status_code=200)
        except SyncError as exc:
            result = {"ok": False, "error": str(exc)}
            subject = "Commission sync failed"
            text = str(exc)

        sender = os.environ.get("ALERT_SENDER")
        to = [e.strip() for e in
              (os.environ.get("COMMISSION_SYNC_RECIPIENTS") or "").split(",") if e.strip()]
        if sender and to:
            from shared.dataverse import graph_send_mail
            graph_send_mail(sender, to, subject, text)
        else:
            logging.warning("commission-sync-run: no ALERT_SENDER/"
                            "COMMISSION_SYNC_RECIPIENTS, not reporting by email")
        return func.HttpResponse(json.dumps({"ok": True, "subject": subject, **result}),
                                 mimetype="application/json", status_code=200)
    except Exception:
        logging.exception("commission-sync-run error")
        return _server_error()


# ── /api/nb-target (GET) — new-business £1m target drill-in ───────────────────
# Visible to the tracked person themselves and to admins.

NB_TARGET_PEOPLE = {
    "charlie@saragossa.io": {
        "uid": "18a4c869-3264-ee11-8def-6045bd0c1c1b",  # Charlie Smith (Mercury)
        "name": "Charlie Smith",
    },
}


@app.route(route="nb-target", methods=["GET"])
def nb_target_get(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_auth(req)
    if err:
        return err
    who = (req.params.get("who") or "charlie@saragossa.io").lower()
    person = NB_TARGET_PEOPLE.get(who)
    if not person:
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "No NB target configured for this person"}),
            mimetype="application/json", status_code=404,
        )
    if email.lower() != who:
        from shared.dataverse import is_admin
        if not is_admin(email):
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "forbidden"}),
                mimetype="application/json", status_code=403,
            )
    # "as at" date — lets the consultant roll the 12-month window forward to see
    # where already-booked future starts will put them.
    as_of = None
    raw = (req.params.get("as_of") or "").strip()
    if raw:
        try:
            as_of = date.fromisoformat(raw[:10])
        except ValueError:
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "Invalid as_of date"}),
                mimetype="application/json", status_code=400,
            )
    try:
        from shared.nbtarget import build_nb_target
        data = build_nb_target(person["uid"], as_of)
        data.update({"ok": True, "name": person["name"]})
        return func.HttpResponse(
            json.dumps(data), mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("nb-target error")
        return _server_error()


# ── /api/nb-thresholds (POST) — save NB-uplift qualification thresholds ────────

@app.route(route="nb-thresholds", methods=["POST"])
def nb_thresholds_post(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err
    try:
        body = req.get_json() or {}
        clean = {}
        for key in ("perm_fee_pct", "perm_min_value", "contract_margin_pct", "contract_min_margin"):
            if body.get(key) is not None:
                try:
                    clean[key] = float(body[key])
                except (TypeError, ValueError):
                    return func.HttpResponse(
                        json.dumps({"ok": False, "error": f"{key} must be a number"}),
                        mimetype="application/json", status_code=400,
                    )
        upsert_nb_thresholds(clean)
        return func.HttpResponse(
            json.dumps({"ok": True, "nb_thresholds": get_nb_thresholds()}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("nb-thresholds POST error")
        return _server_error()


# ── /api/settings/{id} (DELETE) ──────────────────────────────────────────────

@app.route(route="settings/{override_id}", methods=["DELETE"])
def settings_delete(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err

    override_id = req.route_params.get("override_id")
    if not override_id or not is_guid(override_id):
        return func.HttpResponse(
            json.dumps({"ok": False, "error": "valid override_id required"}),
            mimetype="application/json",
            status_code=400,
        )

    try:
        delete_override(override_id)
        return func.HttpResponse(
            json.dumps({"ok": True}),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as e:
        logging.exception("settings DELETE error")
        return _server_error()


# ── /api/admin-report ─────────────────────────────────────────────────────────

@app.route(route="analytics-report", methods=["GET"])
def analytics_report(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err

    try:
        today = date.today()
        year  = today.year

        consultants      = get_all_territory_consultants()   # active + inactive
        overrides        = get_overrides()
        team_map         = get_team_membership_map()
        placements_this  = get_placements_full_year(year)
        placements_last  = get_placements_full_year(year - 1)
        # Deals already done with a start next year — what is gathering for it.
        placements_next  = get_placements_full_year(year + 1)
        created_this     = get_placements_created_in_year(year)
        created_last     = get_placements_created_in_year(year - 1)
        budgets          = get_budgets()

        try:
            fx_rates = get_fx_rates()
        except Exception:
            logging.warning("admin-report: could not fetch live FX rates, using fallback")
            fx_rates = None

        # Bob job-title history for US perm consultants (best-effort; falls back
        # to Mercury titles if Bob is unavailable).
        bob_titles = {}
        try:
            us_tids = {TERRITORY_IDS["Chicago"], TERRITORY_IDS["New York"]}
            us_emails = [
                c.get("internalemailaddress") for c in consultants
                if c.get("_territoryid_value") in us_tids
                and not c.get("isdisabled", False)
                and c.get("internalemailaddress")
            ]
            if us_emails:
                from shared.bob import get_titles_for_emails
                bob_titles = get_titles_for_emails(us_emails, year)
        except Exception:
            logging.warning("admin-report: Bob enrichment failed, using Mercury titles", exc_info=True)

        report = build_admin_report(
            consultants, placements_this, placements_last,
            overrides, today,
            team_map=team_map, budgets=budgets, fx_rates=fx_rates,
            bob_titles=bob_titles,
            created_this=created_this, created_last=created_last,
            solution_entries=get_solution_entries(),
            placements_next=placements_next,
        )
        # For the Contract Entry ledger grid only — the analytics figures
        # themselves are perm-only (the ledger feeds just the weekly report).
        report["contract_entries"] = get_contract_entries()
        report["solution_entries"] = get_solution_entries()

        return func.HttpResponse(
            json.dumps({"ok": True, **report}),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as e:
        logging.exception("admin-report error")
        return _server_error()


# ── /api/admin/budget (POST) ──────────────────────────────────────────────────

@app.route(route="analytics-budget", methods=["POST"])
def analytics_budget_post(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_admin(req)
    if err:
        return err

    try:
        body = req.get_json()
        year      = body.get("year")
        territory = body.get("territory")
        months    = body.get("months")   # {month_str: amount}

        if not year or not territory or not months:
            return func.HttpResponse(
                json.dumps({"ok": False, "error": "year, territory and months are required"}),
                mimetype="application/json",
                status_code=400,
            )

        upsert_monthly_budgets(int(year), territory, months)
        return func.HttpResponse(
            json.dumps({"ok": True}),
            mimetype="application/json",
            status_code=200,
        )
    except Exception:
        logging.exception("admin budget POST error")
        return _server_error()
