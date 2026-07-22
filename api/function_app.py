"""
Azure Functions V2 — all API endpoints for the Saragossa weekly report.

Routes:
  GET  /api/report-data   → full report JSON (all authenticated users)
  GET  /api/settings      → override list + Mercury user list (admin only)
  POST /api/settings      → upsert an override (admin only)
  DELETE /api/settings/{id} → remove an override (admin only)
"""
import json, logging, os
from datetime import date

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
    get_manual_nb_clients, add_manual_nb_client, remove_manual_nb_client, search_accounts,
    get_nb_clients_for_cro, get_nb_alert_state, upsert_nb_alert_state, delete_nb_alert_state,
)
from shared.calc import build_report, build_admin_report, build_month_created

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def _server_error() -> func.HttpResponse:
    """Generic 500 — full detail is logged server-side, never returned to the client."""
    return func.HttpResponse(
        json.dumps({"ok": False, "error": "Internal server error"}),
        mimetype="application/json",
        status_code=500,
    )


# ── /api/report-data ──────────────────────────────────────────────────────────

@app.route(route="report-data", methods=["GET"])
def report_data(req: func.HttpRequest) -> func.HttpResponse:
    email, err = require_auth(req)
    if err:
        return err

    try:
        today = date.today()

        # Date window: placements from 12 months ago through end of this year
        start = date(today.year - 1, today.month, 1).isoformat()
        end   = date(today.year, 12, 31).isoformat()

        consultants     = get_active_consultants()
        placements      = get_placements(start, end)
        contract_pl     = get_contract_placements(start, end)
        overrides       = get_overrides()
        team_map        = get_team_membership_map()
        live_contracts  = get_live_contract_placements(today.isoformat())
        nb_thresholds   = get_nb_thresholds()
        manual_nb       = get_manual_nb_clients()
        try:
            alert_state = {u: s["client_ids"] for u, s in get_nb_alert_state().items()}
        except Exception:
            logging.warning("report-data: could not read NB alert state")
            alert_state = {}
        try:
            fx_rates = get_fx_rates()
        except Exception:
            logging.warning("Could not fetch live FX rates — using hardcoded fallback")
            fx_rates = None

        report = build_report(consultants, placements, overrides, today, team_map,
                              live_contracts, fx_rates, nb_thresholds, contract_pl, manual_nb,
                              nb_alert_state=alert_state,
                              contract_entries=get_contract_entries())

        month_created = build_month_created(
            get_placements_created_in_year(today.year), consultants, today, fx_rates)

        return func.HttpResponse(
            json.dumps({"ok": True, "report": report, "as_of": today.isoformat(),
                        "month_created": month_created}),
            mimetype="application/json",
            status_code=200,
        )
    except Exception as e:
        logging.exception("report-data error")
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
        subject, text, html = compose_board_email(_bar)
        graph_send_mail(sender, [email], subject, text, body_html=html)
        return func.HttpResponse(
            json.dumps({"ok": True, "sent_to": email}),
            mimetype="application/json", status_code=200,
        )
    except Exception:
        logging.exception("board-report error")
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

        contract_entries = get_contract_entries()
        report = build_admin_report(
            consultants, placements_this, placements_last,
            overrides, today,
            team_map=team_map, budgets=budgets, fx_rates=fx_rates,
            bob_titles=bob_titles,
            created_this=created_this, created_last=created_last,
            contract_entries=contract_entries,
        )
        report["contract_entries"] = contract_entries

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
