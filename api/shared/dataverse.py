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

def get_all_named_users() -> list[dict]:
    """
    Every named Mercury user, enabled or not, for name matching.

    Wider than get_all_territory_consultants(): finance's commission sheets pay
    people who have no territory at all — leavers whose territory was cleared,
    and the generic "Saragossa House" account — and their contribution still has
    to land somewhere rather than being dropped.
    """
    return odata_get_all(
        "systemusers",
        params={
            "$select": "systemuserid,fullname,isdisabled,_territoryid_value",
            "$filter": "isintegrationuser eq false and fullname ne null",
        },
    )


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

# "Cancelled - Rebated" is NOT a normal cancellation: the placement still
# counts and the fee still credits in its start month — only the rebated
# amount is clawed back, in the month it was rebated. These records go
# inactive in Mercury, so every fetch has to opt them back in explicitly.
REBATED_STATUS = 975310000
REBATE_FIELDS = "recruit_rebateamount,recruit_rebatedon,statuscode"


def active_or_rebated_filter() -> str:
    """OData predicate: live placements, plus rebated ones (see REBATED_STATUS)."""
    cancel_filter = " and ".join(f"statuscode ne {c}" for c in CANCEL_CODES)
    return f"((statecode eq 0 and {cancel_filter}) or statuscode eq {REBATED_STATUS})"

def get_placements(start_date: str, end_date: str) -> list[dict]:
    """
    Fetches all active perm placements where crimson_startdate is in range.
    No row cap — paginated automatically.
    """
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
                "_recruit_candidatecontact_value,"
                "_mercury_clientrelationshipowner_value,"
                "_crimson_consultant_value,"
                "_mercury_assignmentowner_value,"
                "_mercury_contractorrelationship_userid_value,"
                f"crimson_name,{REBATE_FIELDS}"
            ),
            "$filter": (
                f"crimson_type eq {PERM_TYPE}"
                f" and crimson_startdate ge {start_date}"
                f" and crimson_startdate le {end_date}"
                f" and {active_or_rebated_filter()}"
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
    type_filter = " or ".join(f"crimson_type eq {t}" for t in CONTRACT_TYPES)
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
                "_mercury_contractorrelationship_userid_value,"
                f"crimson_name,{REBATE_FIELDS}"
            ),
            "$filter": (
                f"({type_filter})"
                f" and crimson_startdate ge {start_date}"
                f" and crimson_startdate le {end_date}"
                f" and {active_or_rebated_filter()}"
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
    return odata_get_all(
        "crimson_placements",
        params={
            "$select": (
                "crimson_placementid,crimson_type,createdon,"
                "crimson_name,crimson_startdate,"
                "recruit_truegrossprofit,crimson_specialinstructionsclient,"
                "_recruit_candidatecontact_value,statuscode,"
                "_crimson_clientname_value,"
                "crimson_extension,crimson_placementidcode,"
                "_mercury_parentplacementid_value,"
                "_mercury_clientrelationshipowner_value,"
                "_crimson_consultant_value,"
                "_mercury_assignmentowner_value,"
                "_mercury_contractorrelationship_userid_value,"
                f"{REBATE_FIELDS}"
            ),
            "$filter": (
                f"createdon ge {year}-01-01T00:00:00Z"
                f" and createdon lt {year + 1}-01-01T00:00:00Z"
                f" and {active_or_rebated_filter()}"
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
                "_mercury_contractorrelationship_userid_value,"
                f"{REBATE_FIELDS}"
            ),
            "$filter": (
                f"crimson_type eq {PERM_TYPE}"
                f" and crimson_startdate ge {year}-01-01"
                f" and crimson_startdate le {year}-12-31"
                f" and {active_or_rebated_filter()}"
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


# ── Solution monthly entries (crbb7_solutionentry) ────────────────────────────
# Deploy & Component revenue booked against a perm consultant, entered by hand
# the same way as the contract ledger. Column names differ slightly from the
# contract table (crbb7_user_id / crbb7_entry_year) — they were auto-generated.

def get_solution_entries() -> dict:
    """Manually entered solution revenue: {uid: {"YYYY-M": amount}}."""
    try:
        rows = odata_get_all(
            "crbb7_solutionentries",
            params={"$select": "crbb7_user_id,crbb7_entry_year,crbb7_month,crbb7_amount"},
        )
    except Exception:
        logging.warning("Could not read crbb7_solutionentry — no manual solution data")
        return {}
    out = {}
    for r in rows:
        uid, y, m = r.get("crbb7_user_id"), r.get("crbb7_entry_year"), r.get("crbb7_month")
        if not uid or not y or not m:
            continue
        out.setdefault(uid, {})[f"{int(y)}-{int(m)}"] = float(r.get("crbb7_amount") or 0)
    return out


def upsert_solution_entries(userid: str, entries: list) -> None:
    """entries: [{year, month, amount}] — amount None/blank deletes that month's row."""
    existing = odata_get_all(
        "crbb7_solutionentries",
        params={
            "$select": "crbb7_solutionentryid,crbb7_entry_year,crbb7_month",
            "$filter": f"crbb7_user_id eq '{odata_str(userid)}'",
        },
    )
    by_key = {(r.get("crbb7_entry_year"), r.get("crbb7_month")): r["crbb7_solutionentryid"]
              for r in existing}
    for e in entries:
        year, month = int(e["year"]), int(e["month"])
        amount = e.get("amount")
        rid = by_key.get((year, month))
        if amount is None:
            if rid:
                odata_delete(f"crbb7_solutionentries({rid})")
            continue
        body = {
            "crbb7_user_id":    userid,
            "crbb7_entry_year": year,
            "crbb7_month":      month,
            "crbb7_amount":     float(amount),
            "crbb7_name":       f"{userid} {year}-{month:02d}"[:99],
        }
        if rid:
            odata_patch(f"crbb7_solutionentries({rid})", body)
        else:
            odata_post("crbb7_solutionentries", body)


# ── Wholesale month replacement (commission spreadsheet import) ───────────────
# The finance workbook is the source of truth for the month it covers, so an
# import replaces that month outright: anyone absent from the sheet is zeroed
# by having their row deleted, not left behind at a stale figure.

_LEDGERS = {
    "contract": {"set": "crbb7_contractentries", "id": "crbb7_contractentryid",
                 "user": "crbb7_userid", "year": "crbb7_entryyear"},
    "solution": {"set": "crbb7_solutionentries", "id": "crbb7_solutionentryid",
                 "user": "crbb7_user_id", "year": "crbb7_entry_year"},
}


def replace_month_entries(kind: str, year: int, month: int, amounts: dict) -> dict:
    """
    amounts: {userid: amount}. Returns {"written": n, "deleted": n}.
    """
    t = _LEDGERS[kind]
    year, month = int(year), int(month)
    existing = odata_get_all(t["set"], params={
        "$select": f"{t['id']},{t['user']},{t['year']},crbb7_month",
        "$filter": f"{t['year']} eq {year} and crbb7_month eq {month}",
    })
    by_user = {r.get(t["user"]): r[t["id"]] for r in existing if r.get(t["user"])}

    written = 0
    for uid, amount in amounts.items():
        body = {t["user"]: uid, t["year"]: year, "crbb7_month": month,
                "crbb7_amount": float(amount),
                "crbb7_name": f"{uid} {year}-{month:02d}"[:99]}
        rid = by_user.pop(uid, None)
        if rid:
            odata_patch(f"{t['set']}({rid})", body)
        else:
            odata_post(t["set"], body)
        written += 1

    for rid in by_user.values():          # everyone the sheet no longer lists
        odata_delete(f"{t['set']}({rid})")
    return {"written": written, "deleted": len(by_user)}


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
    rows = odata_get_all(
        "crimson_placements",
        params={
            "$select": (
                "crimson_placementid,crimson_startdate,"
                "crimson_specialinstructionsclient,_crimson_clientname_value"
            ),
            "$filter": (
                f"_mercury_clientrelationshipowner_value eq '{uid}'"
                f" and {active_or_rebated_filter()}"
                f" and crimson_startdate ge {start_date}"
                f" and crimson_startdate le {end_date}"
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


# ── Board report data sources ─────────────────────────────────────────────────

def get_user_territory_map() -> dict:
    """{systemuserid: territory name} for ALL users (any territory, incl.
    Consult/Deploy) — used to bucket placement splits for the board report."""
    territories = odata_get_all("territories", params={"$select": "territoryid,name"})
    tid_name = {t["territoryid"]: t.get("name", "") for t in territories}
    users = odata_get_all(
        "systemusers",
        params={"$select": "systemuserid,_territoryid_value"},
    )
    out = {
        u["systemuserid"]: tid_name.get(u.get("_territoryid_value"), "")
        for u in users
    }
    # Synthetic territories: users with no Mercury territory that the app
    # treats as their own region (e.g. Cameron Scott).
    for uid, terr in _UNASSIGNED_HOUSE_USERS.items():
        out[uid] = terr
    return out


def get_cancel_log() -> list:
    """
    [{placementid, ptype, detected, logged}] — `detected` is the cancellation
    date we recorded; `logged` is when the log row itself was written. Seeded
    rows (detected approximated from modifiedon) have detected <= their seed
    day; only organically-detected rows are reliably dated.
    """
    try:
        rows = odata_get_all(
            "crbb7_cancellogs",
            params={"$select": "crbb7_placementid,crbb7_ptype,crbb7_detected,createdon"},
        )
    except Exception:
        logging.warning("Could not read crbb7_cancellog")
        return []
    return [
        {"placementid": r.get("crbb7_placementid"), "ptype": r.get("crbb7_ptype") or "",
         "detected": r.get("crbb7_detected") or "", "logged": (r.get("createdon") or "")[:10]}
        for r in rows if r.get("crbb7_placementid")
    ]


def sync_cancel_log(today_iso: str) -> int:
    """
    Records placements newly showing a cancelled status. On the very first run
    (empty log) the detected date is seeded from each placement's modifiedon —
    the closest available approximation; thereafter, detected = today. Returns
    the number of new rows written.
    """
    cancel_filter = " or ".join(f"statuscode eq {c}" for c in CANCEL_CODES)
    cancelled = odata_get_all(
        "crimson_placements",
        params={
            "$select": "crimson_placementid,crimson_type,modifiedon",
            "$filter": f"({cancel_filter})",
        },
    )
    existing = {e["placementid"] for e in get_cancel_log()}
    seed_mode = not existing
    type_labels = {143570000: "Permanent", 143570001: "Contract", 143570002: "Temporary"}
    added = 0
    for p in cancelled:
        pid = p["crimson_placementid"]
        if pid in existing:
            continue
        detected = (p.get("modifiedon") or today_iso)[:10] if seed_mode else today_iso
        odata_post("crbb7_cancellogs", {
            "crbb7_placementid": pid,
            "crbb7_ptype":       type_labels.get(p.get("crimson_type"), "Other"),
            "crbb7_detected":    detected,
            "crbb7_name":        f"{pid} {detected}",
        })
        added += 1
    return added


def get_first_placement_dates(client_ids: list) -> dict:
    """
    {client_id: earliest createdon} across ALL their non-cancelled placements —
    a client is only a "new client" in the month of their first-ever placement.
    Rebated placements still count (money-only claw-back), so they are included.
    """
    out = {}
    ids = [c for c in (client_ids or []) if c]
    for i in range(0, len(ids), 20):
        chunk = ids[i:i + 20]
        or_f = " or ".join(f"_crimson_clientname_value eq '{cid}'" for cid in chunk)
        rows = odata_get_all(
            "crimson_placements",
            params={
                "$select": "_crimson_clientname_value,createdon",
                "$filter": f"({or_f}) and {active_or_rebated_filter()}",
            },
        )
        for r in rows:
            cid, created = r.get("_crimson_clientname_value"), r.get("createdon") or ""
            if cid and created and (cid not in out or created < out[cid]):
                out[cid] = created
    return out


def get_cancelled_created_in_year(year: int) -> list:
    """
    Placements CREATED in the year that are NOW cancelled — the board email's
    cancellation rule: "created in the month in question, now cancelled".
    Includes rebated ones so the caller can report them separately.
    """
    cancel_filter = " or ".join(f"statuscode eq {c}" for c in CANCEL_CODES)
    return odata_get_all(
        "crimson_placements",
        params={
            "$select": "crimson_placementid,crimson_type,createdon,statuscode",
            "$filter": (
                f"({cancel_filter})"
                f" and createdon ge {year}-01-01T00:00:00Z"
                f" and createdon lt {year + 1}-01-01T00:00:00Z"
            ),
        },
    )


def get_cancellations_by_status_change(year: int, month: int) -> dict:
    """
    {"cancelled": {"Permanent": n, ...}, "rebated": {"Permanent": n, ...}} —
    placements whose statuscode CHANGED to a cancelled value during the given
    month, read from the audit log (Jason's rule: cancelled-in-month means the
    status flipped that month). "Cancelled - Rebated" is reported separately:
    the placement still counts as a deal, only money is clawed back.
    Raises if the audit log can't be read so callers can fall back.
    """
    import json as _json
    from datetime import date as _d
    start = _d(year, month, 1)
    end   = _d(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)

    # Candidates: currently cancelled and touched on/after the month start —
    # the cancelling edit itself bumps modifiedon, so this is a superset.
    cancel_filter = " or ".join(f"statuscode eq {c}" for c in CANCEL_CODES)
    candidates = odata_get_all(
        "crimson_placements",
        params={
            "$select": "crimson_placementid,crimson_type",
            "$filter": f"({cancel_filter}) and modifiedon ge {start.isoformat()}",
        },
    )
    type_labels = {143570000: "Permanent", 143570001: "Contract", 143570002: "Temporary"}
    start_s, end_s = start.isoformat(), end.isoformat()
    # RetrieveRecordChangeHistory is the API that the "View Audit History"
    # privilege covers (raw audit-table reads need a separate privilege).
    # One call per candidate — parallelised to stay inside the SWA 45s limit.
    def _cancel_code_in_window(p):
        """The cancel statuscode this placement moved to during the month, or None."""
        pid = p["crimson_placementid"]
        resp = requests.get(
            f"{DATAVERSE_URL}/api/data/v9.1/RetrieveRecordChangeHistory(Target=@t)",
            params={"@t": _json.dumps({"@odata.id": f"crimson_placements({pid})"})},
            headers=_headers(), timeout=60,
        )
        resp.raise_for_status()
        details = (resp.json().get("AuditDetailCollection") or {}).get("AuditDetails") or []
        for d in details:
            created = ((d.get("AuditRecord") or {}).get("createdon") or "")[:10]
            if not (start_s <= created < end_s):
                continue
            sc = (d.get("NewValue") or {}).get("statuscode")
            try:
                if sc is not None and int(sc) in CANCEL_CODES:
                    return int(sc)
            except (TypeError, ValueError):
                pass
        return None

    from concurrent.futures import ThreadPoolExecutor
    counts, rebated = {}, {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for p, code in zip(candidates, pool.map(_cancel_code_in_window, candidates)):
            if code is None:
                continue
            label = type_labels.get(p.get("crimson_type"), "Other")
            target = rebated if code == REBATED_STATUS else counts
            target[label] = target.get(label, 0) + 1
    return {"cancelled": counts, "rebated": rebated}


def fetch_roi_summary() -> dict:
    """
    Tech ROI figures from the ROI & Efficiency Tracker via its keyed endpoint.
    Returns {"rows": [{group, target, achieved, pct}], "total_achieved": float}
    or {} when unconfigured/unreachable (the email section degrades gracefully).
    """
    base = os.environ.get("ROI_TRACKER_URL")
    key  = os.environ.get("ROI_TRACKER_API_KEY")
    if not base or not key:
        return {}
    try:
        year = __import__("datetime").date.today().year
        resp = requests.get(
            f"{base.rstrip('/')}/api/roi",
            params={"from": f"{year}-01-01", "to": f"{year + 1}-01-01"},
            headers={"x-api-key": key}, timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logging.warning("Could not fetch ROI tracker figures", exc_info=True)
        return {}
    achieved = {g.get("name"): float(g.get("gbp") or 0) for g in data.get("groups", [])}
    rows = []
    for t in data.get("tools", []):
        group  = t.get("group")
        # roiTarget is a MULTIPLE ("return 10x cost"); the £ target is the
        # resolved yearlyTargetGbp (annual cost × multiple).
        target = float(t.get("yearlyTargetGbp") or 0)
        if not group or target <= 0:
            continue
        got = achieved.get(group, 0.0)
        rows.append({
            "group":    group,
            "target":   round(target, 2),
            "achieved": round(got, 2),
            "pct":      round(got / target * 100, 1),
        })
    rows.sort(key=lambda r: r["target"], reverse=True)
    return {"rows": rows, "total_achieved": round(sum(achieved.values()), 2)}


def get_latest_forecast() -> dict:
    """
    Latest placement-predictor snapshot (per-solution xP for the current and
    next month) plus the most recent digest subject line.
    """
    out = {"snapshot_date": None, "current": [], "next": [], "digest_subject": None}
    try:
        snaps = odata_get_all(
            "crbb7_predictionsnapshots",
            params={
                "$select": ("crbb7_solution,crbb7_horizon,crbb7_targetmonth,"
                            "crbb7_expectedtotal,crbb7_confirmedsofar,crbb7_snapshotdate"),
                "$orderby": "crbb7_snapshotdate desc",
                "$top": 40,
            },
        )
        if snaps:
            latest = snaps[0].get("crbb7_snapshotdate")
            out["snapshot_date"] = (latest or "")[:10]
            for s in snaps:
                if s.get("crbb7_snapshotdate") != latest:
                    continue
                row = {
                    "solution":  s.get("crbb7_solution") or "?",
                    "month":     s.get("crbb7_targetmonth") or "",
                    "expected":  float(s.get("crbb7_expectedtotal") or 0),
                    "confirmed": float(s.get("crbb7_confirmedsofar") or 0),
                }
                (out["current"] if s.get("crbb7_horizon") == "current" else out["next"]).append(row)
    except Exception:
        logging.warning("Could not read prediction snapshots", exc_info=True)
    try:
        digests = odata_get_all(
            "crbb7_modelstatses",
            params={
                "$select": "crbb7_summary,crbb7_compute_date",
                "$filter": "crbb7_kind eq 'digest'",
                "$orderby": "crbb7_compute_date desc",
                "$top": 1,
            },
        )
        if digests:
            out["digest_subject"] = digests[0].get("crbb7_summary")
    except Exception:
        logging.warning("Could not read forecast digest", exc_info=True)
    return out


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


# ── Board report schedule (crbb7_boardschedule) ───────────────────────────────
# One row per planned send. The GitHub Actions cron fires anything due; the
# Analytics page creates and cancels them. Times are stored in UTC.

def _parse_dt(raw: str):
    """Dataverse UTC datetime string → aware datetime, or None."""
    from datetime import datetime, timezone
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def get_board_schedules(include_sent: bool = True) -> list[dict]:
    rows = odata_get_all(
        "crbb7_boardschedules",
        params={"$select": ("crbb7_boardscheduleid,crbb7_send_at,crbb7_sent_on,"
                            "crbb7_recipients,crbb7_created_by_email,crbb7_name")},
    )
    out = []
    for r in rows:
        if not include_sent and r.get("crbb7_sent_on"):
            continue
        recips = [e.strip() for e in (r.get("crbb7_recipients") or "").split(",") if e.strip()]
        out.append({
            "id":         r.get("crbb7_boardscheduleid"),
            "send_at":    r.get("crbb7_send_at"),
            "send_at_dt": _parse_dt(r.get("crbb7_send_at")),
            "sent_on":    r.get("crbb7_sent_on"),
            "recipients": recips,
            "created_by": r.get("crbb7_created_by_email") or "",
            "label":      r.get("crbb7_name") or "",
        })
    out.sort(key=lambda s: s.get("send_at") or "")
    return out


def add_board_schedule(send_at_utc: str, recipients: list = None, created_by: str = "") -> dict:
    """send_at_utc: ISO 8601 UTC (e.g. 2026-08-20T16:00:00Z)."""
    return odata_post("crbb7_boardschedules", {
        "crbb7_send_at":         send_at_utc,
        "crbb7_recipients":      ", ".join(recipients or []),
        "crbb7_created_by_email": created_by,
        "crbb7_name":            f"Board report {send_at_utc[:16].replace('T', ' ')}Z",
    })


def delete_board_schedule(rowid: str) -> None:
    odata_delete(f"crbb7_boardschedules({rowid})")


def mark_board_schedule_sent(rowid: str, note: str = "") -> None:
    from datetime import datetime, timezone
    body = {"crbb7_sent_on": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if note:
        body["crbb7_recipients"] = note[:900]
    odata_patch(f"crbb7_boardschedules({rowid})", body)


# ── MBR (crbb7_mbr / crbb7_mbrtarget) ─────────────────────────────────────────
# Beta. The judgement fields and the action list are stored as one JSON payload
# per person per month — fine for a prototype, but revisit if MBR content ever
# becomes evidence in promotion or comp decisions (it would need per-field
# history and an audit trail).

def get_mbr(uid: str, year: int, month: int) -> dict:
    rows = odata_get_all("crbb7_mbrs", params={
        "$select": "crbb7_mbrid,crbb7_user_id,crbb7_entry_year,crbb7_month,crbb7_payload,crbb7_status",
        "$filter": (f"crbb7_user_id eq '{odata_str(uid)}' and crbb7_entry_year eq {int(year)}"
                    f" and crbb7_month eq {int(month)}"),
    })
    if not rows:
        return {}
    import json as _json
    r = rows[0]
    try:
        payload = _json.loads(r.get("crbb7_payload") or "{}")
    except ValueError:
        logging.warning("MBR %s %s-%s has unreadable payload", uid, year, month)
        payload = {}
    return {"id": r["crbb7_mbrid"], "status": r.get("crbb7_status") or "draft", **payload}


def upsert_mbr(uid: str, year: int, month: int, payload: dict, status: str = "draft") -> None:
    import json as _json
    existing = odata_get_all("crbb7_mbrs", params={
        "$select": "crbb7_mbrid",
        "$filter": (f"crbb7_user_id eq '{odata_str(uid)}' and crbb7_entry_year eq {int(year)}"
                    f" and crbb7_month eq {int(month)}"),
    })
    body = {
        "crbb7_user_id":   uid,
        "crbb7_entry_year": int(year),
        "crbb7_month":     int(month),
        "crbb7_payload":   _json.dumps(payload),
        "crbb7_status":    status,
        "crbb7_name":      f"MBR {uid} {year}-{month:02d}"[:840],
    }
    if existing:
        odata_patch(f"crbb7_mbrs({existing[0]['crbb7_mbrid']})", body)
    else:
        odata_post("crbb7_mbrs", body)


def get_mbr_targets(uid: str = None) -> dict:
    """{uid: {target_key: value}} — all people, or just one."""
    params = {"$select": "crbb7_user_id,crbb7_target_key,crbb7_value"}
    if uid:
        params["$filter"] = f"crbb7_user_id eq '{odata_str(uid)}'"
    try:
        rows = odata_get_all("crbb7_mbrtargets", params=params)
    except Exception:
        logging.warning("Could not read crbb7_mbrtarget")
        return {}
    out = {}
    for r in rows:
        u, k = r.get("crbb7_user_id"), r.get("crbb7_target_key")
        if u and k:
            out.setdefault(u, {})[k] = float(r.get("crbb7_value") or 0)
    return out


def upsert_mbr_targets(uid: str, targets: dict) -> None:
    """targets: {target_key: value}; a None value removes that target."""
    existing = odata_get_all("crbb7_mbrtargets", params={
        "$select": "crbb7_mbrtargetid,crbb7_target_key",
        "$filter": f"crbb7_user_id eq '{odata_str(uid)}'",
    })
    by_key = {r.get("crbb7_target_key"): r["crbb7_mbrtargetid"] for r in existing}
    for key, value in targets.items():
        rid = by_key.get(key)
        if value is None:
            if rid:
                odata_delete(f"crbb7_mbrtargets({rid})")
            continue
        body = {"crbb7_user_id": uid, "crbb7_target_key": key,
                "crbb7_value": float(value), "crbb7_name": f"{uid} {key}"[:840]}
        if rid:
            odata_patch(f"crbb7_mbrtargets({rid})", body)
        else:
            odata_post("crbb7_mbrtargets", body)


# ── MBR scope (crbb7_mbrscope) ────────────────────────────────────────────────
# Who may open whose MBR, deliberately separate from analytics admin: reading
# someone's performance conversation is a different permission from reading
# revenue figures. A row grants its user the listed territories; "*" grants all.
# Team leads get their own team automatically and need no row here.

def get_mbr_scopes() -> dict:
    """
    {uid: [territory, ...]} — '*' means every territory.
    Returns None (not {}) if the table can't be read, so callers can tell
    "nobody is granted" apart from "the grant table is unavailable" and avoid
    locking everyone out of the module.
    """
    try:
        rows = odata_get_all("crbb7_mbrscopes",
                             params={"$select": "crbb7_user_id,crbb7_territories"})
    except Exception:
        logging.warning("Could not read crbb7_mbrscope", exc_info=True)
        return None
    out = {}
    for r in rows:
        uid = r.get("crbb7_user_id")
        if not uid:
            continue
        out[uid] = [t.strip() for t in (r.get("crbb7_territories") or "").split(",") if t.strip()]
    return out


def upsert_mbr_scope(uid: str, territories: list) -> None:
    """An empty list removes the row entirely."""
    existing = odata_get_all("crbb7_mbrscopes", params={
        "$select": "crbb7_mbrscopeid",
        "$filter": f"crbb7_user_id eq '{odata_str(uid)}'",
    })
    rid = existing[0]["crbb7_mbrscopeid"] if existing else None
    if not territories:
        if rid:
            odata_delete(f"crbb7_mbrscopes({rid})")
        return
    body = {"crbb7_user_id": uid, "crbb7_territories": ", ".join(territories),
            "crbb7_name": f"MBR scope {uid}"[:840]}
    if rid:
        odata_patch(f"crbb7_mbrscopes({rid})", body)
    else:
        odata_post("crbb7_mbrscopes", body)


# ── Weekly 1:1 (crbb7_oneonone) ───────────────────────────────────────────────
# One row per person per week; the typed half of the form is a JSON payload.

def get_one_to_one(uid: str, week_start: str) -> dict:
    try:
        rows = odata_get_all("crbb7_oneonones", params={
            "$select": "crbb7_oneononeid,crbb7_payload",
            "$filter": (f"crbb7_user_id eq '{odata_str(uid)}'"
                        f" and crbb7_week_start eq '{odata_str(week_start)}'"),
        })
    except Exception:
        logging.warning("Could not read crbb7_oneonone", exc_info=True)
        return {}
    if not rows:
        return {}
    import json as _json
    try:
        return _json.loads(rows[0].get("crbb7_payload") or "{}")
    except ValueError:
        return {}


def upsert_one_to_one(uid: str, week_start: str, payload: dict) -> None:
    import json as _json
    existing = odata_get_all("crbb7_oneonones", params={
        "$select": "crbb7_oneononeid",
        "$filter": (f"crbb7_user_id eq '{odata_str(uid)}'"
                    f" and crbb7_week_start eq '{odata_str(week_start)}'"),
    })
    body = {"crbb7_user_id": uid, "crbb7_week_start": week_start,
            "crbb7_payload": _json.dumps(payload),
            "crbb7_name": f"1:1 {uid} {week_start}"[:840]}
    if existing:
        odata_patch(f"crbb7_oneonones({existing[0]['crbb7_oneononeid']})", body)
    else:
        odata_post("crbb7_oneonones", body)


def get_latest_mbr_actions(uid: str) -> list:
    """Actions from this person's most recent MBR, for the 1:1's MBR section."""
    try:
        rows = odata_get_all("crbb7_mbrs", params={
            "$select": "crbb7_entry_year,crbb7_month,crbb7_payload",
            "$filter": f"crbb7_user_id eq '{odata_str(uid)}'",
        })
    except Exception:
        return []
    if not rows:
        return []
    import json as _json
    rows.sort(key=lambda r: (r.get("crbb7_entry_year") or 0, r.get("crbb7_month") or 0),
              reverse=True)
    try:
        return (_json.loads(rows[0].get("crbb7_payload") or "{}") or {}).get("actions") or []
    except ValueError:
        return []


def list_one_to_one_weeks(uid: str) -> set:
    """Week-start dates this person already has a saved 1:1 for."""
    try:
        rows = odata_get_all("crbb7_oneonones", params={
            "$select": "crbb7_week_start",
            "$filter": f"crbb7_user_id eq '{odata_str(uid)}'",
        })
    except Exception:
        return set()
    return {r.get("crbb7_week_start") for r in rows if r.get("crbb7_week_start")}
