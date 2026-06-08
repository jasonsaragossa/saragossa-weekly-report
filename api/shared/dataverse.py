"""
Mercury Dataverse client.
Uses MSAL client credentials (service principal) to authenticate.
The Web API OData endpoint has no row cap - we paginate with $skiptoken.
"""
import os, requests, msal, logging
from functools import lru_cache

DATAVERSE_URL  = os.environ["DATAVERSE_URL"]          # e.g. https://saragossa.crm11.dynamics.com
TENANT_ID      = os.environ["DATAVERSE_TENANT_ID"]
CLIENT_ID      = os.environ["DATAVERSE_CLIENT_ID"]
CLIENT_SECRET  = os.environ["DATAVERSE_CLIENT_SECRET"]
SCOPE          = [f"{DATAVERSE_URL}/.default"]

@lru_cache(maxsize=1)
def _msal_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        client_credential=CLIENT_SECRET,
    )

def _get_token() -> str:
    result = _msal_app().acquire_token_for_client(scopes=SCOPE)
    if "access_token" not in result:
        raise RuntimeError(f"MSAL token error: {result.get('error_description')}")
    return result["access_token"]

def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Prefer": "odata.maxpagesize=1000",
    }

def odata_get_all(path: str, params: dict = None) -> list:
    """Fetches all pages from an OData endpoint."""
    url = f"{DATAVERSE_URL}/api/data/v9.1/{path}"
    results = []
    while url:
        resp = requests.get(url, headers=_headers(), params=params if url.endswith(path) else None)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return results

def odata_post(path: str, body: dict) -> dict:
    url = f"{DATAVERSE_URL}/api/data/v9.1/{path}"
    headers = _headers()
    headers["Prefer"] = "return=representation"
    resp = requests.post(url, headers=headers, json=body)
    if not resp.ok:
        raise RuntimeError(f"POST {path} {resp.status_code}: {resp.text[:1000]}")
    return resp.json() if resp.content else {}

def odata_patch(path: str, body: dict) -> None:
    url = f"{DATAVERSE_URL}/api/data/v9.1/{path}"
    resp = requests.patch(url, headers=_headers(), json=body)
    if not resp.ok:
        raise RuntimeError(f"PATCH {path} {resp.status_code}: {resp.text[:1000]}")

def odata_delete(path: str) -> None:
    url = f"{DATAVERSE_URL}/api/data/v9.1/{path}"
    resp = requests.delete(url, headers=_headers())
    resp.raise_for_status()


# ── Territory IDs ────────────────────────────────────────────────────────────

TERRITORY_IDS = {
    "Bristol":          "b10329a2-cbbe-ee11-9079-6045bd0c1c1b",
    "London":           "134b21a8-cbbe-ee11-9079-6045bd0c1c1b",
    "Chicago":          "ca64adae-cbbe-ee11-9079-6045bd0c1c1b",
    "New York":         "776699c0-5bae-f011-bbd2-000d3a0b968e",
    "London Contract":  "e5a8ae46-ffc4-ee11-9079-6045bd0c1d6a",
    "Chicago Contract": "34eed662-22b2-ef11-b8e8-6045bdfcb26b",
}

FINANCE_TEAM_NAME = "Bristol Finance and Compliance"


# ── User queries ─────────────────────────────────────────────────────────────

def get_active_consultants() -> list[dict]:
    """Returns all active users in the 6 territories."""
    territory_filter = " or ".join(
        f"_territoryid_value eq '{tid}'" for tid in TERRITORY_IDS.values()
    )
    return odata_get_all(
        "systemusers",
        params={
            "$select": "systemuserid,fullname,title,createdon,_territoryid_value",
            "$filter": f"isdisabled eq false and ({territory_filter})",
            "$orderby": "createdon asc",
        },
    )

# "Saragossa House" accounts that have no territory assigned in Mercury.
# We inject them into the Bristol territory so their placements appear in analytics.
# Key = systemuserid, value = territory name to assign.
_UNASSIGNED_HOUSE_USERS = {
    "cf6f0d98-2a7a-ee11-8179-002248c7244c": "Bristol",   # Saragossa House (generic)
}

def get_all_territory_consultants() -> list[dict]:
    """
    Returns active AND inactive users in the 6 territories, with isdisabled flag.
    Also injects any unassigned house users defined in _UNASSIGNED_HOUSE_USERS.
    """
    territory_filter = " or ".join(
        f"_territoryid_value eq '{tid}'" for tid in TERRITORY_IDS.values()
    )
    results = odata_get_all(
        "systemusers",
        params={
            "$select": "systemuserid,fullname,title,createdon,_territoryid_value,isdisabled",
            "$filter": f"({territory_filter})",
            "$orderby": "createdon asc",
        },
    )
    # Inject house users that have no territory in Mercury
    existing_ids = {r["systemuserid"] for r in results}
    for uid, territory in _UNASSIGNED_HOUSE_USERS.items():
        if uid in existing_ids:
            continue
        house_users = odata_get_all(
            "systemusers",
            params={
                "$select": "systemuserid,fullname,title,createdon,isdisabled",
                "$filter": f"systemuserid eq '{uid}'",
            },
        )
        for u in house_users:
            u["_territoryid_value"] = TERRITORY_IDS[territory]
            results.append(u)
    return results


# Known report team names — must match Dataverse team names exactly
_REPORT_TEAM_NAMES = [
    "Team Batt", "Team Charlie", "Team Sion", "Team Harry W",
    "Team Data & Cyber", "Team Data and Cyber", "Team Snoz",
    "Team JD", "Team Matty", "Team Adam", "Team Adam W",
]

def get_team_membership_map() -> dict:
    """
    Returns {systemuserid: team_name} for all users in any known report team.
    Uses separate queries per team to avoid $expand encoding issues.
    """
    name_filter = " or ".join(f"name eq '{t}'" for t in _REPORT_TEAM_NAMES)
    teams = odata_get_all("teams", params={
        "$select": "teamid,name",
        "$filter": name_filter,
    })
    uid_to_team = {}
    for team in teams:
        members = odata_get_all(
            f"teams({team['teamid']})/teammembership_association",
            params={"$select": "systemuserid"},
        )
        for m in members:
            uid = m.get("systemuserid")
            if uid and uid not in uid_to_team:
                uid_to_team[uid] = team["name"]
    return uid_to_team

def get_territory_name(tid: str) -> str:
    return next((k for k, v in TERRITORY_IDS.items() if v == tid), "Unknown")

def is_admin(user_email: str) -> bool:
    """
    Admin = Director job title OR member of Bristol Finance and Compliance team.
    """
    # Check job title
    users = odata_get_all(
        "systemusers",
        params={
            "$select": "jobtitle",
            "$filter": f"internalemailaddress eq '{user_email}' and isdisabled eq false",
        },
    )
    if users and "director" in (users[0].get("jobtitle") or "").lower():
        return True

    # Check team membership
    teams = odata_get_all(
        "teams",
        params={
            "$select": "teamid",
            "$filter": f"name eq '{FINANCE_TEAM_NAME}'",
        },
    )
    if not teams:
        return False
    team_id = teams[0]["teamid"]

    # Check if this user is in that team
    user_lookup = odata_get_all(
        "systemusers",
        params={
            "$select": "systemuserid",
            "$filter": f"internalemailaddress eq '{user_email}' and isdisabled eq false",
        },
    )
    if not user_lookup:
        return False
    user_id = user_lookup[0]["systemuserid"]

    members = odata_get_all(
        f"teams({team_id})/teammembership_association",
        params={"$select": "systemuserid", "$filter": f"systemuserid eq '{user_id}'"},
    )
    return len(members) > 0


# ── Placement queries ─────────────────────────────────────────────────────────

PERM_TYPE      = 143570000
CONTRACT_TYPES = [143570001, 143570002]   # Contract, Temporary

# All Mercury cancellation statuscodes (from crimson_placement schema)
CANCEL_CODES = [
    143570009,  # Cancelled - Candidate did not start
    143570010,  # Cancelled - Client cancelled
    939310015,  # Cancelled by us
    939310016,  # Cancelled - Changed Client
    975310000,  # Cancelled - Rebated
]
CANCELLED_DIDNOTSTART = 143570009  # kept as alias used elsewhere

def get_placements(start_date: str, end_date: str) -> list[dict]:
    """
    Fetches all active perm placements where crimson_startdate is in range.
    No row cap — paginated automatically.
    """
    cancel_filter = " and ".join(f"statuscode ne {c}" for c in CANCEL_CODES)
    return odata_get_all(
        "crimson_placements",
        params={
            "$select": (
                "crimson_placementid,recruit_truegrossprofit,"
                "crimson_startdate,crimson_specialinstructionsclient,"
                "_recruit_truegrossprofitcurrency_value,"
                "_mercury_clientrelationshipowner_value,"
                "_crimson_consultant_value,"
                "_mercury_assignmentowner_value,"
                "_mercury_contractorrelationship_userid_value"
            ),
            "$filter": (
                f"crimson_type eq {PERM_TYPE}"
                f" and statecode eq 0"
                f" and crimson_startdate ge {start_date}"
                f" and crimson_startdate le {end_date}"
                f" and {cancel_filter}"
            ),
            "$expand": "recruit_truegrossprofitcurrency($select=isocurrencycode)",
        },
    )


# ── FX rates ─────────────────────────────────────────────────────────────────

def get_fx_rates() -> dict:
    """
    Returns {iso_code: unitsPerGbp} using the most recent rate per currency
    from the existing crbb7_fxrate table.
    crbb7_name format is 'USD 2026-01' — currency is the first token.
    """
    records = odata_get_all(
        "crbb7_fxrates",
        params={
            "$select": "crbb7_name,crbb7_rate",
            "$orderby": "crbb7_month desc",
        },
    )
    rates = {}
    for r in records:
        name = r.get("crbb7_name") or ""
        ccy = name.split()[0] if name else None
        if ccy and ccy not in rates and r.get("crbb7_rate"):
            rates[ccy] = float(r["crbb7_rate"])
    return rates


# ── Live contract placements ──────────────────────────────────────────────────

def get_live_contract_placements(today_str: str) -> list[dict]:
    """
    Returns all live contract/temp placements as of today_str.
    Live = startdate <= today AND effective_enddate >= today
    Effective end = min(crimson_actualenddate, crimson_enddate).
    Excludes cancelled-did-not-start (statuscode 143570009).
    """
    type_filter = " or ".join(f"crimson_type eq {t}" for t in CONTRACT_TYPES)
    return odata_get_all(
        "crimson_placements",
        params={
            "$select": (
                "crimson_placementid,"
                "crimson_startdate,crimson_enddate,crimson_actualenddate,"
                "statuscode,recruit_trueweeklygrossprofit,"
                "_mercury_clientrelationshipowner_value,"
                "_crimson_consultant_value,"
                "_mercury_assignmentowner_value,"
                "_mercury_contractorrelationship_userid_value"
            ),
            "$expand": "recruit_trueweeklygrossprofitcurrency($select=isocurrencycode)",
            "$filter": (
                f"({type_filter})"
                f" and statecode eq 0"
                f" and statuscode ne {CANCELLED_DIDNOTSTART}"
                f" and crimson_startdate le {today_str}"
                f" and crimson_enddate ge {today_str}"
                f" and (crimson_actualenddate eq null or crimson_actualenddate ge {today_str})"
            ),
        },
    )


# ── Admin: full-year placements ───────────────────────────────────────────────

def get_placements_full_year(year: int) -> list[dict]:
    """
    Fetch all active or completed perm placements for a given calendar year.
    statecode 0 = Active, 1 = Completed/Won — both valid for historical data.
    statecode 2 = Cancelled — explicitly excluded here and via statuscode filters.
    """
    cancel_filter = " and ".join(f"statuscode ne {c}" for c in CANCEL_CODES)
    return odata_get_all(
        "crimson_placements",
        params={
            "$select": (
                "crimson_placementid,recruit_truegrossprofit,"
                "crimson_startdate,crimson_specialinstructionsclient,"
                "_mercury_clientrelationshipowner_value,"
                "_crimson_consultant_value,"
                "_mercury_assignmentowner_value,"
                "_mercury_contractorrelationship_userid_value"
            ),
            "$filter": (
                f"crimson_type eq {PERM_TYPE}"
                f" and crimson_startdate ge {year}-01-01"
                f" and crimson_startdate le {year}-12-31"
                f" and {cancel_filter}"
            ),
            "$expand": "recruit_truegrossprofitcurrency($select=isocurrencycode)",
        },
    )


# ── Budget table (crbb7_budget) ───────────────────────────────────────────────

def get_budgets() -> list[dict]:
    """Returns all budget records. Gracefully returns [] if table doesn't exist."""
    try:
        return odata_get_all("crbb7_budgets")
    except Exception as e:
        logging.warning(f"get_budgets failed (table may not exist yet): {e}")
        return []

def upsert_monthly_budgets(year: int, territory: str, monthly_amounts: dict) -> None:
    """
    Upserts one Dataverse record per month for a territory/year.
    monthly_amounts: {month_int: amount}  e.g. {1: 50000, 2: 60000, ...}
    """
    for month, amount in monthly_amounts.items():
        if amount is None:
            continue
        existing = odata_get_all(
            "crbb7_budgets",
            params={
                "$filter": (
                    f"crbb7_year eq {year}"
                    f" and crbb7_territory eq '{territory}'"
                    f" and crbb7_month eq {int(month)}"
                ),
            },
        )
        body = {
            "crbb7_year":      year,
            "crbb7_territory": territory,
            "crbb7_month":     int(month),
            "crbb7_amount":    float(amount),
        }
        if existing:
            rid = existing[0]["crbb7_budgetid"]
            odata_patch(f"crbb7_budgets({rid})", body)
        else:
            odata_post("crbb7_budgets", body)


# ── Override table (crbb7_useroverride) ───────────────────────────────────────

def get_overrides() -> list[dict]:
    # No $select — table is small so fetching all columns is fine.
    # Specific $select causes 400s likely due to a column name discrepancy
    # in the Dataverse table; calc.py reads only the fields it needs by name.
    return odata_get_all("crbb7_useroverrides")

def upsert_override(data: dict, updated_by: str) -> dict:
    """
    data: { userid, name, territory, team, is_hidden }
    Checks for existing override by userid; patches if found, posts if not.
    """
    existing = odata_get_all(
        "crbb7_useroverrides",
        params={
            "$filter": f"crbb7_userid eq '{data['userid']}'",
        },
    )
    body = {
        "crbb7_userid":   data["userid"],
        "crbb7_team":     data.get("team", ""),
        "crbb7_ishidden": data.get("is_hidden", False),
    }
    # Contract manual fields
    for api_key, dv_key in [
        ("margin_ytd",       "crbb7_marginytd"),
        ("contract_last12m", "crbb7_contractlast12m"),
        ("rolling_3m",       "crbb7_rolling3m"),
    ]:
        if api_key in data and data[api_key] is not None:
            body[dv_key] = data[api_key]

    # History / dates — only write if non-empty (avoids overwriting existing values with null)
    for api_key, dv_key in [
        ("date_joined",        "crbb7_datejoined"),
        ("date_joined_team",   "crbb7_datejoinedteam"),
        ("previous_team",      "crbb7_previousteam"),
        ("previous_territory", "crbb7_previousterritory"),
    ]:
        if api_key in data:
            val = data[api_key]
            body[dv_key] = val if val not in (None, "") else None
    if existing:
        rid = existing[0]["crbb7_useroverrideid"]
        odata_patch(f"crbb7_useroverrides({rid})", body)
        return {"id": rid, **body}
    else:
        result = odata_post("crbb7_useroverrides", body)
        return result

def delete_override(override_id: str) -> None:
    odata_delete(f"crbb7_useroverrides({override_id})")
