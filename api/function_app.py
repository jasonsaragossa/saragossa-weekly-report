"""
Azure Functions V2 — all API endpoints for the Saragossa weekly report.

Routes:
  GET  /api/report-data   → full report JSON (all authenticated users)
  GET  /api/settings      → override list + Mercury user list (admin only)
  POST /api/settings      → upsert an override (admin only)
  DELETE /api/settings/{id} → remove an override (admin only)
"""
import json, logging, os
from datetime import date, datetime, timezone

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
                              contract_entries=get_contract_entries(),
                              solution_entries=get_solution_entries())

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


# ── /api/solution-entries (POST) — Deploy & Component monthly ledger ──────────

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
    people = [c for c in get_all_territory_consultants() if not c.get("isdisabled")]
    me = next((c for c in people
               if (c.get("internalemailaddress") or "").lower() == (email or "").lower()), None)
    scopes = get_mbr_scopes()
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
            payload = {k: (body or {}).get(k) for k in
                       ("positives", "improve", "aspirations", "support", "actions", "commentary")}
            upsert_mbr(uid, year, month, payload, (body or {}).get("status") or "draft")
            return func.HttpResponse(json.dumps({"ok": True}),
                                     mimetype="application/json", status_code=200)

        from shared.mbr import build_mbr_metrics, previous_month
        from shared.mbr_prompts import generate_prompts, pick_flagged
        from shared.mbr_registry import DEFAULT_TARGETS

        data    = build_mbr_metrics(uid, year, month)
        targets = {**DEFAULT_TARGETS, **(get_mbr_targets(uid).get(uid) or {})}
        saved   = get_mbr(uid, year, month)
        ly, lm  = previous_month(year, month)
        last    = get_mbr(uid, ly, lm)

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
