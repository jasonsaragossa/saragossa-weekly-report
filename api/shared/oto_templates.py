"""
1:1 templates — which team gets which questions, and who may see whom.

Teams differ in what they want from a 1:1: Harry's perm team has its questions,
Jim's contract desk has its own. A template ties together a roster, an access
rule, the derived figures to compute and the sections to type into. Adding a
team means adding an entry here, not a page.

Access, per template:
  * "leads" see everyone on the roster;
  * a "sub-team lead" sees their own Mercury team within the roster;
  * everyone else on the roster sees only themselves;
  * admins see every template and every person.
"""
from shared.dataverse import (TERRITORY_IDS, odata_get_all, odata_str)

TEMPLATES = {
    "snoz": {
        "name":      "Team Snoz",
        "kind":      "perm",
        "locale":    "en-GB",
        # Roster = one Mercury team
        "team":      "Team Snoz",
        "leads":     {"harrysnozwell@saragossa.io"},
        "sub_teams": {},
    },
    "contract_usa": {
        "name":      "Contract USA",
        "kind":      "contract",
        # A US desk reads US dates — 9/14/2026, not 14/09/2026 (Jason, Sep 2026)
        "locale":    "en-US",
        # The first week the desk held 1:1s for. Earlier weeks can only ever
        # be empty, so they are neither shown nor reachable (Jason, Sep 2026).
        "start_week": "2026-09-21",
        # Roster = a territory; the house account is not a person
        "territory": "Chicago Contract",
        "exclude_names": ("saragossa house",),
        # Jim runs the 1:1s rather than sitting in one, so he is a lead but
        # not on the roster (Jason, Sep 2026).
        "exclude_emails": ("jim@saragossa.io",),
        # Jim runs the desk; Andrew is Jim's manager (Jason, Sep 2026)
        "leads":     {"jim@saragossa.io", "andrewt@saragossa.io"},
        # Each sub-team lead sees their own team only
        "sub_teams": {
            "Team Connor":   "connor@saragossa.io",
            "Team Makenzie": "makenzie@saragossa.io",
            "Team Mike B":   "michaelb@saragossa.io",
        },
    },
}

_SELECT = "systemuserid,fullname,internalemailaddress,isdisabled,title"

# The consultant career ladder, in order. Shown at the top of a 1:1 with the
# person's current rung highlighted, so progression is in front of both of
# them every week (Jason, Sep 2026).
CAREER_LADDER = ("Associate", "Consultant", "Senior Consultant",
                 "Lead Consultant", "Principal Consultant", "EIC")

# Mercury job titles that mean a rung but aren't spelled like one. Anything
# not on the ladder and not here leaves the strip unhighlighted rather than
# guessing — a wrong rung in a progression conversation is worse than none.
_TITLE_TO_RUNG = {
    "associate consultant": "Associate",
    "associate":            "Associate",
    "consultant":           "Consultant",
    "senior consultant":    "Senior Consultant",
    "lead consultant":      "Lead Consultant",
    "principal consultant": "Principal Consultant",
    "eic":                  "EIC",
    "expert in charge":     "EIC",
}


def rung(title: str) -> str | None:
    """Which rung of the ladder a Mercury job title is, or None."""
    return _TITLE_TO_RUNG.get((title or "").strip().lower())


def _team_members(team_name: str) -> list:
    teams = odata_get_all("teams", params={
        "$select": "teamid", "$filter": f"name eq '{odata_str(team_name)}'"})
    if not teams:
        return []
    return [m for m in odata_get_all(
        f"teams({teams[0]['teamid']})/teammembership_association",
        params={"$select": _SELECT}) if not m.get("isdisabled")]


def roster(template: dict) -> list:
    """Everyone the template covers, sorted by name."""
    if template.get("team"):
        people = _team_members(template["team"])
    else:
        tid = TERRITORY_IDS[template["territory"]]
        people = odata_get_all("systemusers", params={
            "$select": _SELECT,
            "$filter": f"_territoryid_value eq '{tid}' and isdisabled eq false"})
    skip = tuple(template.get("exclude_names") or ())
    skip_email = {e.lower() for e in (template.get("exclude_emails") or ())}
    people = [p for p in people
              if not (p.get("fullname") or "").lower().startswith(skip)
              and (p.get("internalemailaddress") or "").lower() not in skip_email]
    people.sort(key=lambda m: m.get("fullname") or "")
    return people


def visible_people(template_id: str, email: str, is_admin: bool) -> tuple:
    """
    (people, is_lead) for one template — who this user may open.
    Empty people means the template is not theirs at all.
    """
    t = TEMPLATES[template_id]
    email = (email or "").lower()
    people = roster(t)
    if is_admin or email in t["leads"]:
        return people, True
    # A sub-team lead sees their team, but only those also on this roster
    for team_name, lead in (t.get("sub_teams") or {}).items():
        if email == lead:
            ids = {m["systemuserid"] for m in _team_members(team_name)}
            mine = [p for p in people if p["systemuserid"] in ids]
            return mine, bool(mine)
    me = [p for p in people if (p.get("internalemailaddress") or "").lower() == email]
    return me, False


def templates_for(email: str, is_admin: bool) -> list:
    """
    The templates this user can see anything in, each with its people:
    [{"id", "name", "kind", "people", "is_lead"}]. Admins get all of them.
    """
    out = []
    for tid, t in TEMPLATES.items():
        people, is_lead = visible_people(tid, email, is_admin)
        if people:
            out.append({"id": tid, "name": t["name"], "kind": t["kind"],
                        "locale": t.get("locale") or "en-GB",
                        "start_week": t.get("start_week"),
                        "people": people, "is_lead": is_lead})
    return out
