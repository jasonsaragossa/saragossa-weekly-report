"""
Azure Functions V2 — all API endpoints for the Saragossa weekly report.

Routes:
  GET  /api/report-data   → full report JSON (all authenticated users)
  GET  /api/settings      → override list + Mercury user list (admin only)
  POST /api/settings      → upsert an override (admin only)
  DELETE /api/settings/{id} → remove an override (admin only)
"""
import json, logging
from datetime import date

import azure.functions as func

from shared.auth import require_auth, require_admin
from shared.dataverse import (
    get_active_consultants, get_placements, get_overrides,
    get_team_membership_map, get_live_contract_placements, get_fx_rates,
    get_placements_full_year, get_budgets, upsert_monthly_budgets,
    get_all_territory_consultants, get_all_active_users, get_finance_team_members,
    upsert_override, delete_override, is_guid, TERRITORY_IDS,
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
        overrides       = get_overrides()
        team_map        = get_team_membership_map()
        live_contracts  = get_live_contract_placements(today.isoformat())
        try:
            fx_rates = get_fx_rates()
        except Exception:
            logging.warning("Could not fetch live FX rates — using hardcoded fallback")
            fx_rates = None

        report = build_report(consultants, placements, overrides, today, team_map, live_contracts, fx_rates)

        return func.HttpResponse(
            json.dumps({"ok": True, "report": report, "as_of": today.isoformat()}),
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
                        "all_active_users": all_users, "finance_member_uids": finance_uids}),
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
        )

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
