"""
Purpose-tagged activity fetching, shared by 121s, MBR and Performance Stats.

The trap this exists to close: Mercury tags activity purpose on TWO different
fields depending on the entity —

    phonecall, appointment ->  _mercury_purpose_value
    email                  ->  _recruit_purpose_value

Checking only the first made BD emails read as zero everywhere, when there are
~1,750 a fortnight company-wide. Anything counting a purpose family should go
through here rather than querying an entity directly.
"""
from datetime import date

from shared.dataverse import odata_get_all, odata_str

PURPOSE_FIELD = {
    "phonecalls":   "_mercury_purpose_value",
    "appointments": "_mercury_purpose_value",
    "emails":       "_recruit_purpose_value",
}
DATE_FIELD = {
    "phonecalls":   "createdon",
    "appointments": "scheduledstart",
    "emails":       "createdon",
}
CONTACT_EXPAND = ("regardingobjectid_account($select=name),"
                  "regardingobjectid_contact($select=fullname,jobtitle,_parentcustomerid_value)")


def fetch(entity: str, uids, start: date, end: date, purposes=None,
          with_contacts: bool = True) -> list:
    """
    Activities of one entity for one or more owners in a window, optionally
    restricted to a purpose family. Every row carries `purpose` and `when`
    normalised, so callers don't need to know which field the entity uses.
    """
    if isinstance(uids, str):
        uids = [uids]
    uids = [u for u in uids if u]
    if not uids:
        return []
    pf, df = PURPOSE_FIELD[entity], DATE_FIELD[entity]

    owner_or = " or ".join("_ownerid_value eq '%s'" % odata_str(u) for u in uids)
    clauses = [f"({owner_or})",
               f"{df} ge {start.isoformat()}", f"{df} lt {end.isoformat()}"]
    if purposes:
        clauses.append("(" + " or ".join(f"{pf} eq '{p}'" for p in purposes) + ")")

    params = {"$select": f"activityid,{pf},{df},subject,_ownerid_value",
              "$filter": " and ".join(clauses)}
    if with_contacts:
        params["$expand"] = CONTACT_EXPAND

    rows = odata_get_all(entity, params=params)
    for r in rows:
        r["purpose"] = r.get(pf)
        r["when"] = (r.get(df) or "")[:10]
        r["entity"] = entity
    return rows


def fetch_all(uids, start: date, end: date, purposes=None,
              entities=("phonecalls", "appointments", "emails")) -> list:
    """Every entity at once — use when a metric spans calls, meetings and email."""
    out = []
    for entity in entities:
        out.extend(fetch(entity, uids, start, end, purposes))
    return out
