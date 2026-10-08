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
from shared.dataverse import (TERRITORY_IDS, odata_get_all, odata_str, ttl_cached)

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
    # Bristol direct hire — a copy of the desk's own Loop template, "DUPLICATE
    # ONLY - 1-1 Template 2026" (Jason, Oct 2026)
    "bristol": {
        "name":      "Bristol",
        "kind":      "loop",
        "locale":    "en-GB",
        # Moved into the app the week of 5 Oct 2026; earlier weeks are in Loop
        "start_week": "2026-10-05",
        "territory": "Bristol",
        "exclude_names": ("saragossa house",),
        # James runs the desk and the 1:1s rather than sitting in one
        "exclude_emails": ("james@saragossa.io",),
        "leads":     {"james@saragossa.io"},
        "sub_teams": {
            "Team Charlie": "charlie@saragossa.io",
            "Team Sion":    "sion@saragossa.io",
            "Team Harry W": "harry@saragossa.io",
            "Team Jake":    "jakec@saragossa.io",
        },
        # Where last week's activity is, as the Loop page points to it
        "dashboard": "https://saragossa.oneupsales.io/dashboard/51097",
        # The Loop's Key Inputs: (Mercury count, label, weekly guideline). The
        # guideline is one figure for the whole desk, set by James or Jason
        # on the page; these are the Loop's own starting values.
        "key_inputs": (("bd_actions", "Total BD Actions", 75),
                       ("client_meetings", "Client Meetings", 2),
                       ("candidate_calls", "Candidate Calls", 25),
                       ("leads", "Leads Gained", 3)),
        "guideline_editors": {"james@saragossa.io", "jason@saragossa.io"},
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


@ttl_cached(300)
def _team_members(team_name: str) -> list:
    teams = odata_get_all("teams", params={
        "$select": "teamid", "$filter": f"name eq '{odata_str(team_name)}'"})
    if not teams:
        return []
    return [m for m in odata_get_all(
        f"teams({teams[0]['teamid']})/teammembership_association",
        params={"$select": _SELECT}) if not m.get("isdisabled")]


@ttl_cached(300)
def _territory_people(tid: str) -> list:
    return odata_get_all("systemusers", params={
        "$select": _SELECT,
        "$filter": f"_territoryid_value eq '{tid}' and isdisabled eq false"})


def _effective_teams() -> dict:
    """{systemuserid: team} — Settings' team if set, else Mercury's."""
    from shared.dataverse import get_overrides, get_team_membership_map
    teams = dict(get_team_membership_map())
    for o in get_overrides():
        if o.get("crbb7_team") and o.get("crbb7_userid"):
            teams[o["crbb7_userid"]] = o["crbb7_team"]
    return teams


def roster(template: dict) -> list:
    """Everyone the template covers, sorted by name."""
    if template.get("team"):
        people = _team_members(template["team"])
    else:
        people = _territory_people(TERRITORY_IDS[template["territory"]])
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
    # A sub-team lead sees their team, but only those also on this roster.
    # The team is the one the report shows: a team set in Settings wins over
    # Mercury's membership (Jake Cogzell leads Team Jake but is still in Team
    # Sion in Mercury). A lead always sees their own 1:1 too.
    for team_name, lead in (t.get("sub_teams") or {}).items():
        if email == lead.lower():
            team_of = _effective_teams()
            mine = [p for p in people if team_of.get(p["systemuserid"]) == team_name
                    or (p.get("internalemailaddress") or "").lower() == email]
            return mine, len(mine) > 1
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
                        "dashboard": t.get("dashboard"),
                        "people": people, "is_lead": is_lead})
    return out
