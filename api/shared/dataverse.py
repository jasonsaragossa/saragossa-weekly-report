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


import re

_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def odata_str(value) -> str:
    """Escape a value for safe inclusion inside an OData string literal ('...')."""
    return str(value).replace("'", "''")


def is_guid(value) -> bool:
    """True if value is a well-formed GUID (for entity-key path segments)."""
    return bool(_GUID_RE.match(str(value or "")))


# ── Territory IDs ────────────────────────────────────────────────────────────

TERRITORY_IDS = {
    "Bristol":          "b10329a2-cbbe-ee11-9079-6045bd0c1c1b",
    "London":           "134b21a8-cbbe-ee11-9079-6045bd0c1c1b",
    "Chicago":          "ca64adae-cbbe-ee11-9079-6045bd0c1c1b",
    "New York":         "776699c0-5bae-f011-bbd2-000d3a0b968e",
    "London Contract":  "e5a8ae46-ffc4-ee11-9079-6045bd0c1d6a",
    "Chicago Contract": "34eed662-22b2-ef11-b8e8-6045bdfcb26b",
    # Synthetic territory — no Dataverse territory record; UID used as unique key
    "Cameron Scott":    "b835f278-3264-ee11-8def-6045bd0c1d6a",
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

# Users with no territory in Mercury that we inject into the analytics.
# Key = systemuserid, value = territory name (must exist in TERRITORY_IDS).
_UNASSIGNED_HOUSE_USERS = {
    # NB: the generic "Saragossa House" user (cf6f0d98-…) is deliberately NOT
    # tracked — its placements (e.g. house-owned retainers) belong in "Other".
    "b835f278-3264-ee11-8def-6045bd0c1d6a": "Cameron Scott",  # Director of Solution Sales
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
            "$select": "systemuserid,fullname,title,createdon,_territoryid_value,isdisabled,internalemailaddress",
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
    "Team Makenzie", "Team Mike B",
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

# Emails always granted access, regardless of their Mercury user state.
# Temporary: Stephen Herniman (CFO) — his Mercury user is currently disabled
# but should be live. Remove once his Mercury account is re-enabled.
ANALYTICS_ALWAYS_ALLOW = {"stephen.herniman@saragossa.io"}


def is_admin(user_email: str) -> bool:
    """
    Admin (Analytics + Settings) =
      Always-allow list, OR Director title, OR manually granted via override,
      OR member of the Finance and Compliance team.
    """
    if user_email and user_email.lower() in ANALYTICS_ALWAYS_ALLOW:
        return True

    users = odata_get_all(
        "systemusers",
        params={
            "$select": "systemuserid,title",
            "$filter": f"internalemailaddress eq '{odata_str(user_email)}' and isdisabled eq false",
        },
    )
    if not users:
        return False
    user_id = users[0]["systemuserid"]

    # 1. Directors always have access (can't be locked out via overrides)
    if "director" in (users[0].get("title") or "").lower():
        return True

    # 2. Explicit override: True = grant, False = deny (revokes the team default)
    ov = odata_get_all(
        "crbb7_useroverrides",
        params={
            "$select": "crbb7_canaccessanalytics",
            "$filter": f"crbb7_userid eq '{user_id}'",
        },
    )
    if ov:
        flag = ov[0].get("crbb7_canaccessanalytics")
        if flag is True:
            return True
        if flag is False:
            return False
        # flag unset → fall through to the team rule

    # 3. Finance and Compliance team membership (the default for that team)
    return user_id in set(get_finance_team_members())


def get_finance_team_members() -> list[str]:
    """systemuserids of everyone in the Finance & Compliance team."""
    teams = odata_get_all(
        "teams",
        params={"$select": "teamid", "$filter": f"name eq '{FINANCE_TEAM_NAME}'"},
    )
    if not teams:
        return []
    members = odata_get_all(
        f"teams({teams[0]['teamid']})/teammembership_association",
        params={"$select": "systemuserid"},
    )
    return [m["systemuserid"] for m in members]


def get_all_active_users() -> list[dict]:
    """All enabled, human users (id + name + email) — for the analytics-access picker."""
    users = odata_get_all(
        "systemusers",
        params={
            "$select": "systemuserid,fullname,internalemailaddress",
            "$filter": "isdisabled eq false and isintegrationuser eq false and internalemailaddress ne null",
            "$orderby": "fullname asc",
        },
    )
    return [
        {"uid": u["systemuserid"], "name": u.get("fullname", ""), "email": u.get("internalemailaddress", "")}
        for u in users
    ]


# ── Placement queries ─────────────────────────────────────────────────────────

PERM_TYPE      = 143570000
CONTRACT_TYPES = [143570001, 143570002]   # Contract, Temporary

# Contact ID for the "RETAINER CANDIDATE" placeholder used on all retained placements
RETAINER_CANDIDATE_CONTACT_ID = "7aa8cfa4-d1f2-f011-8406-7c1e52796145"

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
                "crimson_type,crimson_permanentfeepercent,"
                "mercury_marginpercent,recruit_weeklymarginvalue_mc,"
                "_crimson_clientname_value,"
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
            "$expand": (
                "recruit_truegrossprofitcurrency($select=isocurrencycode),"
                "crimson_clientname($select=name)"
            ),
        },
    )


def get_contract_placements(start_date: str, end_date: str) -> list[dict]:
    """
    Contract/temp placements with a start date in range — used for the
    cross-type NB-client count and the CRO's NB uplift on contract deals.
    """
    cancel_filter = " and ".join(f"statuscode ne {c}" for c in CANCEL_CODES)
    type_filter   = " or ".join(f"crimson_type eq {t}" for t in CONTRACT_TYPES)
    return odata_get_all(
        "crimson_placements",
        params={
            "$select": (
                "crimson_placementid,crimson_startdate,crimson_specialinstructionsclient,"
                "crimson_type,_crimson_clientname_value,"
                "recruit_truegrossprofit,mercury_marginpercent,recruit_weeklymarginvalue_mc,"
                "_recruit_truegrossprofitcurrency_value,"
                "_mercury_clientrelationshipowner_value,"
                "_crimson_consultant_value,"
                "_mercury_assignmentowner_value,"
                "_mercury_contractorrelationship_userid_value"
            ),
            "$filter": (
                f"({type_filter})"
                f" and statecode eq 0"
                f" and crimson_startdate ge {start_date}"
                f" and crimson_startdate le {end_date}"
                f" and {cancel_filter}"
            ),
            "$expand": (
                "crimson_clientname($select=name),"
                "recruit_truegrossprofitcurrency($select=isocurrencycode)"
            ),
        },
    )


def get_placements_created_in_year(year: int) -> list[dict]:
    """
    All placements (any type) CREATED in the given calendar year — the basis
    for the "Written" monthly view. Includes extension markers so initial
    contracts can be told apart from extensions.
    """
    cancel_filter = " and ".join(f"statuscode ne {c}" for c in CANCEL_CODES)
    return odata_get_all(
        "crimson_placements",
        params={
            "$select": (
                "crimson_placementid,crimson_type,createdon,"
                "crimson_name,crimson_startdate,"
                "recruit_truegrossprofit,crimson_specialinstructionsclient,"
                "crimson_extension,crimson_placementidcode,"
                "_mercury_parentplacementid_value,"
                "_mercury_clientrelationshipowner_value,"
                "_crimson_consultant_value,"
                "_mercury_assignmentowner_value,"
                "_mercury_contractorrelationship_userid_value"
            ),
            "$filter": (
                f"statecode eq 0"
                f" and createdon ge {year}-01-01T00:00:00Z"
                f" and createdon lt {year + 1}-01-01T00:00:00Z"
                f" and {cancel_filter}"
            ),
            "$expand": (
                "recruit_truegrossprofitcurrency($select=isocurrencycode),"
                "crimson_clientname($select=name)"
            ),
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
    Includes expanded client name and owner names for the "Other" drilldown.
    """
    cancel_filter = " and ".join(f"statuscode ne {c}" for c in CANCEL_CODES)
    return odata_get_all(
        "crimson_placements",
        params={
            "$select": (
                "crimson_placementid,crimson_name,recruit_truegrossprofit,"
                "crimson_startdate,crimson_specialinstructionsclient,createdon,"
                "_recruit_candidatecontact_value,"
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
            "$expand": (
                "recruit_truegrossprofitcurrency($select=isocurrencycode),"
                "crimson_clientname($select=name),"
                "mercury_clientrelationshipowner($select=fullname),"
                "crimson_consultant($select=fullname),"
                "mercury_assignmentowner($select=fullname)"
            ),
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
                    f"crbb7_year eq {int(year)}"
                    f" and crbb7_territory eq '{odata_str(territory)}'"
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
            "$filter": f"crbb7_userid eq '{odata_str(data['userid'])}'",
        },
    )
    # Only write team / hidden when the caller actually sent them, so partial
    # saves (e.g. granting analytics access) don't clobber existing values.
    body = {"crbb7_userid": data["userid"]}
    if "team" in data:
        body["crbb7_team"] = data.get("team") or ""
    if "is_hidden" in data:
        body["crbb7_ishidden"] = bool(data["is_hidden"])
    # Numeric override fields
    for api_key, dv_key in [
        ("margin_ytd",       "crbb7_marginytd"),
        ("contract_last12m", "crbb7_contractlast12m"),
        ("rolling_3m",       "crbb7_rolling3m"),
        ("target",           "crbb7_target"),
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

    # HPB (High Performance Bonus) fields — US perm only
    if "is_team_lead" in data:
        body["crbb7_isteamlead"] = bool(data["is_team_lead"])
    for q in ("1", "2", "3", "4"):
        api_key = "hpb_grade_q" + q
        if api_key in data:
            v = data[api_key]
            body["crbb7_hpbgradeq" + q] = v if v not in (None, "") else None

    # Analytics access grant
    if "can_access_analytics" in data:
        body["crbb7_canaccessanalytics"] = bool(data["can_access_analytics"])

    # crbb7_ishidden is NOT NULL — default it on first create
    if not existing and "crbb7_ishidden" not in body:
        body["crbb7_ishidden"] = False

    if existing:
        rid = existing[0]["crbb7_useroverrideid"]
        odata_patch(f"crbb7_useroverrides({rid})", body)
        return {"id": rid, **body}
    else:
        result = odata_post("crbb7_useroverrides", body)
        return result

def delete_override(override_id: str) -> None:
    odata_delete(f"crbb7_useroverrides({override_id})")


# ── Contract monthly entries (crbb7_contractentry) ─────────────────────────────

def get_contract_entries() -> dict:
    """
    Manually entered contract figures: {uid: {"YYYY-M": amount}}.
    Gracefully returns {} if the table doesn't exist yet.
    """
    try:
        rows = odata_get_all(
            "crbb7_contractentries",
            # NB: crbb7_entryyear, not crbb7_year — the original auto-created
            # int column is range-capped at 1000 and can't hold a year.
            params={"$select": "crbb7_userid,crbb7_entryyear,crbb7_month,crbb7_amount"},
        )
    except Exception:
        logging.warning("Could not read crbb7_contractentry — no manual contract data")
        return {}
    out = {}
    for r in rows:
        uid, y, m = r.get("crbb7_userid"), r.get("crbb7_entryyear"), r.get("crbb7_month")
        if not uid or not y or not m:
            continue
        out.setdefault(uid, {})[f"{int(y)}-{int(m)}"] = float(r.get("crbb7_amount") or 0)
    return out


def upsert_contract_entries(userid: str, entries: list) -> None:
    """
    entries: [{year, month, amount}] — amount None/blank deletes that month's row.
    """
    existing = odata_get_all(
        "crbb7_contractentries",
        params={
            "$select": "crbb7_contractentryid,crbb7_entryyear,crbb7_month",
            "$filter": f"crbb7_userid eq '{odata_str(userid)}'",
        },
    )
    by_key = {(r.get("crbb7_entryyear"), r.get("crbb7_month")): r["crbb7_contractentryid"] for r in existing}
    for e in entries:
        year, month = int(e["year"]), int(e["month"])
        amount = e.get("amount")
        rid = by_key.get((year, month))
        if amount is None:
            if rid:
                odata_delete(f"crbb7_contractentries({rid})")
            continue
        body = {
            "crbb7_userid":    userid,
            "crbb7_entryyear": year,
            "crbb7_month":     month,
            "crbb7_amount":    float(amount),
            "crbb7_name":      f"{userid} {year}-{month:02d}",
        }
        if rid:
            odata_patch(f"crbb7_contractentries({rid})", body)
        else:
            odata_post("crbb7_contractentries", body)


# ── NB-uplift qualification thresholds (crbb7_nbconfig, single row) ────────────

_NB_THRESHOLD_DEFAULTS = {
    "perm_fee_pct":        18.0,
    "perm_min_value":      8000.0,
    "contract_margin_pct": 15.0,
    "contract_min_margin": 75.0,
}
_NB_COLS = {
    "perm_fee_pct":        "crbb7_permfeepct",
    "perm_min_value":      "crbb7_permminval",
    "contract_margin_pct": "crbb7_contractmarginpct",
    "contract_min_margin": "crbb7_contractminmargin",
}


def get_nb_thresholds() -> dict:
    """Returns the NB-uplift thresholds, falling back to code defaults per field."""
    out = dict(_NB_THRESHOLD_DEFAULTS)
    try:
        rows = odata_get_all("crbb7_nbconfigs", params={"$select": ",".join(_NB_COLS.values())})
    except Exception:
        logging.warning("Could not read crbb7_nbconfig, using default NB thresholds")
        return out
    if rows:
        r = rows[0]
        for key, col in _NB_COLS.items():
            if r.get(col) is not None:
                out[key] = float(r[col])
    return out


def upsert_nb_thresholds(values: dict) -> None:
    """Patches the single NB-config row (creates it if missing)."""
    body = {}
    for key, col in _NB_COLS.items():
        if values.get(key) is not None:
            v = float(values[key])
            body[col] = int(v) if col == "crbb7_permminval" else v
    if not body:
        return
    rows = odata_get_all("crbb7_nbconfigs", params={"$select": "crbb7_nbconfigid"})
    if rows:
        odata_patch(f"crbb7_nbconfigs({rows[0]['crbb7_nbconfigid']})", body)
    else:
        body["crbb7_name"] = "default"
        odata_post("crbb7_nbconfigs", body)


# ── NB-client alert state (crbb7_nbalert: one row per user, recording the
#    client ids already "consumed" by previous alerts — the next alert only
#    fires once they have 5 clients not in this set) ───────────────────────────

def get_nb_alert_state() -> dict:
    """{ uid: {"rowid": guid, "client_ids": set} } from previous alerts."""
    rows = odata_get_all(
        "crbb7_nbalerts",
        params={"$select": "crbb7_nbalertid,crbb7_userid,crbb7_clientids"},
    )
    out = {}
    for r in rows:
        uid = r.get("crbb7_userid")
        if not uid:
            continue
        raw = r.get("crbb7_clientids") or ""
        out[uid] = {
            "rowid":      r["crbb7_nbalertid"],
            "client_ids": {c for c in raw.split(",") if c},
        }
    return out


def upsert_nb_alert_state(uid: str, client_ids: set, rowid: str = None) -> None:
    """Persists the full set of client ids consumed by alerts for this user."""
    body = {
        "crbb7_userid":    uid,
        "crbb7_name":      uid,
        "crbb7_clientids": ",".join(sorted(client_ids)),
    }
    if rowid:
        odata_patch(f"crbb7_nbalerts({rowid})", body)
    else:
        odata_post("crbb7_nbalerts", body)


def delete_nb_alert_state(rowid: str) -> None:
    odata_delete(f"crbb7_nbalerts({rowid})")


def get_nb_clients_for_cro(uid: str, start_date: str, end_date: str) -> dict:
    """
    {client_id: name} — new-business clients won as CRO in the window, any
    placement type. Mirrors the client-counting rules in compute_metrics.
    `uid` must be a validated GUID.
    """
    cancel_filter = " and ".join(f"statuscode ne {c}" for c in CANCEL_CODES)
    rows = odata_get_all(
        "crimson_placements",
        params={
            "$select": (
                "crimson_placementid,crimson_startdate,"
                "crimson_specialinstructionsclient,_crimson_clientname_value"
            ),
            "$filter": (
                f"_mercury_clientrelationshipowner_value eq '{uid}'"
                f" and statecode eq 0"
                f" and crimson_startdate ge {start_date}"
                f" and crimson_startdate le {end_date}"
                f" and {cancel_filter}"
            ),
            "$expand": "crimson_clientname($select=name)",
        },
    )
    out = {}
    for p in rows:
        if "new business" in (p.get("crimson_specialinstructionsclient") or "").lower():
            cid = p.get("_crimson_clientname_value")
            if cid:
                out[cid] = (p.get("crimson_clientname") or {}).get("name") or "(unknown client)"
    return out


# ── Manual NB-client additions (crbb7_nbclient) ───────────────────────────────

def get_manual_nb_clients() -> dict:
    """{ uid: [ {id, name, rowid} ] } — admin-added NB clients per consultant."""
    rows = odata_get_all(
        "crbb7_nbclients",
        params={"$select": "crbb7_userid,crbb7_clientid,crbb7_clientname,crbb7_nbclientid"},
    )
    out = {}
    for r in rows:
        uid = r.get("crbb7_userid")
        if not uid:
            continue
        out.setdefault(uid, []).append({
            "id":    r.get("crbb7_clientid"),
            "name":  r.get("crbb7_clientname") or "(client)",
            "rowid": r.get("crbb7_nbclientid"),
        })
    return out


def add_manual_nb_client(uid: str, client_id: str, client_name: str) -> dict:
    return odata_post("crbb7_nbclients", {
        "crbb7_userid":     uid,
        "crbb7_clientid":   client_id,
        "crbb7_clientname": client_name,
        "crbb7_name":       client_name or uid,
    })


def remove_manual_nb_client(rowid: str) -> None:
    odata_delete(f"crbb7_nbclients({rowid})")


def search_accounts(query: str, top: int = 25) -> list[dict]:
    """Search client accounts by name (for the NB-client picker)."""
    q = odata_str(query)
    rows = odata_get_all(
        "accounts",
        params={
            "$select": "accountid,name",
            "$filter": f"contains(name,'{q}') and statecode eq 0",
            "$orderby": "name asc",
            "$top": top,
        },
    )
    return [{"id": a["accountid"], "name": a.get("name", "")} for a in rows[:top]]


# ── Microsoft Graph email (for scheduled alerts) ──────────────────────────────

def _graph_token() -> str:
    result = _msal_app().acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        raise RuntimeError(f"Graph token error: {result.get('error_description')}")
    return result["access_token"]


def graph_send_mail(sender: str, recipients: list, subject: str, body_text: str,
                    body_html: str = None, inline_images: dict = None) -> None:
    """
    Sends an email as `sender` via Graph (needs Mail.Send app permission).
    body_html: optional HTML body (plain text used when None).
    inline_images: {content_id: png_bytes} embedded as inline attachments,
    referenced in the HTML as <img src="cid:content_id">.
    """
    import base64
    message = {
        "subject": subject,
        "body": {
            "contentType": "HTML" if body_html else "Text",
            "content": body_html or body_text,
        },
        "toRecipients": [{"emailAddress": {"address": r}} for r in recipients],
    }
    if inline_images:
        message["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": f"{cid}.png",
                "contentType": "image/png",
                "contentBytes": base64.b64encode(data).decode("ascii"),
                "contentId": cid,
                "isInline": True,
            }
            for cid, data in inline_images.items()
        ]
    msg = {"message": message, "saveToSentItems": False}
    resp = requests.post(
        f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail",
        headers={"Authorization": f"Bearer {_graph_token()}", "Content-Type": "application/json"},
        json=msg, timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Graph sendMail {resp.status_code}: {resp.text[:500]}")
