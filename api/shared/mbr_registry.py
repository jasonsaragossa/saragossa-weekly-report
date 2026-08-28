"""
MBR metric registry.

One entry per metric, in the shape the design brief asked for so Sion and James
can review definitions without reading code. Everything here is computed for
every consultant every month; which metrics a team *sees* is separate config.

Fields per metric:
  key            stable id, used by targets/config/prompts
  name           display name
  family         grouping in the form
  definition     plain English, reviewable by a non-engineer
  source         Dataverse table + fields + filters, in words
  grain          individual | team | territory
  attribution    whose number it is
  direction      up | down | context   (is higher better?)
  target_key     matching target field, or None if no target applies
  format         money | count | ratio | percent
  prompt_context why it matters and what levers move it — feeds the AI prompts
"""

# Activity purposes (mercury_activitypurpose GUIDs) grouped into families.
# Verified against live data Aug 2026: 93% of calls and 79% of meetings carry one.
BD_CALL_PURPOSES = {
    "45e272c6-a769-ee11-94f7-000d3ad6abf9": "BD Cold Call - Pitch Delivered",
    "7bb789e2-ef94-ee11-be37-002248c7244c": "BD Cold Call - No Pitch Delivered/No Answer",
    "cca8257a-2895-ee11-be37-002248c7244c": "BD Follow Up Call",
    "1de2ae64-1144-ef11-a316-6045bd0fcf1e": "BD Strategic Call",
    "44e272c6-a769-ee11-94f7-000d3ad6abf9": "Cold (Intro) Call",
}
BD_PITCH_PURPOSE     = "45e272c6-a769-ee11-94f7-000d3ad6abf9"   # Pitch Delivered
BD_NO_PITCH_PURPOSE  = "7bb789e2-ef94-ee11-be37-002248c7244c"   # No pitch / no answer

CANDIDATE_CALL_PURPOSES = {
    "49e272c6-a769-ee11-94f7-000d3ad6abf9": "Candidate Ad-Response Call",
    "48e272c6-a769-ee11-94f7-000d3ad6abf9": "Candidate check-in",
    "43e272c6-a769-ee11-94f7-000d3ad6abf9": "Candidate Interview Debrief",
    "3fe272c6-a769-ee11-94f7-000d3ad6abf9": "Candidate Interview Prep Call",
    "40e272c6-a769-ee11-94f7-000d3ad6abf9": "Candidate Offer Call",
    "41e272c6-a769-ee11-94f7-000d3ad6abf9": "Candidate Flip Call",
    "4ae272c6-a769-ee11-94f7-000d3ad6abf9": "Candidate Leads Call",
    "42e272c6-a769-ee11-94f7-000d3ad6abf9": "CandidateCV Follow Up Call",
}
CLIENT_MEETING_PURPOSES = {
    "92fcaab8-9a50-ee11-be6f-0022481b503e": "New Client Meeting",
    "28103947-f1aa-ee11-be37-002248c7244c": "Existing Client Meeting",
    "bdf76a79-e9f0-ee11-904c-6045bdd19e21": "Subsequent New Client Meeting",
    "94fcaab8-9a50-ee11-be6f-0022481b503e": "Client Presentation",
    "11350f1f-1e4e-f111-bec6-002248433928": "Solution Cross-Sell Meeting",
    "4ce272c6-a769-ee11-94f7-000d3ad6abf9": "Job Briefing",
}
LEAD_PURPOSES = {
    "d59958b7-98c6-ee11-9079-002248c7244c": "Lead Gained from Candidate",
    "b6e30f54-40cb-ee11-9079-6045bd0c1c1b": "Manager Referral",
}
SPEC_CV_PURPOSES = {
    "47e272c6-a769-ee11-94f7-000d3ad6abf9": "Spec CV",
    "4cf063c0-de38-f111-88b5-7c1e5209a533": "Spec CV Follow Up Call",
    "573fc500-5f8e-f011-b4cb-7c1e52656983": "Spec CV Follow Up Email",
}


REGISTRY = [
    # ── Revenue ───────────────────────────────────────────────────────────────
    dict(
        key="perm_gp", name="Perm Revenue (GP)", family="Revenue",
        definition="Gross profit on permanent placements starting in the month, "
                   "shared using the standard ownership split (CRO / Consultant / AO, "
                   "quarters where there is a Contractor Owner).",
        source="crimson_placement, recruit_truegrossprofit, filtered to crimson_startdate "
               "in the month, cancellations excluded, rebates netted at the rebate date.",
        grain="individual", attribution="Standard ownership split, same as the weekly report",
        direction="up", target_key="revenue", format="money",
        prompt_context="The headline outcome metric. It is a lagging indicator — it moves "
                       "because of interviews and jobs worked 6-10 weeks earlier. A drop here "
                       "with healthy funnel activity usually means timing; a drop with weak "
                       "funnel means the problem started last month.",
    ),
    dict(
        key="deals", name="Deals", family="Revenue",
        definition="Placements starting in the month, credited half to the Consultant and "
                   "half to the Assignment Owner — the same rule the board pack uses.",
        source="crimson_placement filtered to crimson_startdate in the month; 0.5 credit per "
               "owner slot; extensions and retainers excluded from the count.",
        grain="individual", attribution="0.5 Consultant + 0.5 AO",
        direction="up", target_key="deals", format="count",
        prompt_context="Volume rather than value. Read alongside revenue: more deals at lower "
                       "value can mean the desk is drifting down-market, fewer deals at higher "
                       "value can be healthy specialisation.",
    ),
    dict(
        key="new_clients", name="New Business Clients", family="Revenue",
        definition="Distinct clients whose placement was flagged New Business and where this "
                   "person is the Client Relationship Owner.",
        source="crimson_placement, crimson_specialinstructionsclient contains 'new business', "
               "CRO = this person, start date in the month.",
        grain="individual", attribution="Client Relationship Owner only",
        direction="up", target_key=None, format="count",
        prompt_context="The clearest signal that BD effort is converting. Zero new clients over "
                       "several months on a desk with high BD activity points at targeting or "
                       "pitch quality rather than effort.",
    ),

    # ── Funnel ────────────────────────────────────────────────────────────────
    dict(
        key="cvs_sent", name="CVs Sent", family="Funnel",
        definition="Candidates submitted to a client in the month. One candidate sent to three "
                   "clients counts three times — each is a separate submission.",
        source="crimson_vacancycandidate, new_statussubmitteddate in the month, owned by "
               "this person.",
        grain="individual", attribution="Shortlist owner",
        direction="up", target_key="cvs_sent", format="count",
        prompt_context="The top of the delivery funnel. High CVs with low interviews means "
                       "quality or briefing is off, not effort. NOTE: the brief flagged that "
                       "'one candidate to three clients' needs a ruling — this counts three.",
    ),
    dict(
        key="interviews_first", name="1st Interviews", family="Funnel",
        definition="Candidates reaching a first interview in the month.",
        source="crimson_vacancycandidate, mercury_firstinterviewdate in the month.",
        grain="individual", attribution="Shortlist owner",
        direction="up", target_key="interviews", format="count",
        prompt_context="The best leading indicator of revenue 6-10 weeks out. A fall here is "
                       "the earliest reliable warning that next quarter is at risk.",
    ),
    dict(
        key="interviews_further", name="Further / Final Interviews", family="Funnel",
        definition="Candidates reaching a further or final interview stage in the month.",
        source="crimson_vacancycandidate, mercury_furtherinterviewdate or "
               "mercury_finalinterviewdate in the month.",
        grain="individual", attribution="Shortlist owner",
        direction="up", target_key=None, format="count",
        prompt_context="Late-funnel depth. Healthy first interviews but few second stages "
                       "suggests candidates are not landing — prep, or the wrong shortlist.",
    ),
    dict(
        key="offers", name="Offers", family="Funnel",
        definition="Candidates receiving an offer in the month.",
        source="crimson_vacancycandidate, new_statusoffermadedate in the month.",
        grain="individual", attribution="Shortlist owner",
        direction="up", target_key=None, format="count",
        prompt_context="Offers that do not convert to placements point at closing, counter-offer "
                       "handling or salary alignment set too late in the process.",
    ),
    dict(
        key="cv_to_interview", name="CV : Interview", family="Funnel",
        definition="First interviews divided by CVs sent in the month — how many submissions "
                   "it takes to generate an interview.",
        source="Derived: interviews_first / cvs_sent.",
        grain="individual", attribution="Derived from this person's own funnel",
        direction="up", target_key=None, format="ratio",
        prompt_context="One of the two ratios the spreadsheet left undefined. Quality of "
                       "shortlisting, not volume. Falling ratio with rising CVs means the desk "
                       "is spraying. Improve it with better qualification at job-briefing.",
    ),

    # ── Business development ──────────────────────────────────────────────────
    dict(
        key="bd_calls", name="BD Calls", family="Business Development",
        definition="Outbound business development calls: cold calls (pitched or not), "
                   "follow-ups, strategic and intro calls.",
        source="phonecall, _mercury_purpose_value in the BD purpose family, in the month.",
        grain="individual", attribution="Activity owner",
        direction="up", target_key="bd_actions", format="count",
        prompt_context="Pure effort. Read with the pitch rate — high calls with a low pitch rate "
                       "is dialling without reaching decision makers, which is a list problem.",
    ),
    dict(
        key="bd_pitch_rate", name="BD Calls → Pitch %", family="Business Development",
        definition="Share of cold calls where a pitch was actually delivered.",
        source="Derived: 'BD Cold Call - Pitch Delivered' / (Pitch Delivered + "
               "'No Pitch Delivered/No Answer').",
        grain="individual", attribution="Activity owner",
        direction="up", target_key=None, format="percent",
        prompt_context="The second formula the spreadsheet left undefined — now computable. "
                       "Measures whether calls reach a conversation. Low rate is usually data "
                       "quality on the call list or calling at the wrong time of day.",
    ),
    dict(
        key="client_meetings", name="Client Meetings", family="Business Development",
        definition="Meetings held with clients — new, existing, subsequent, presentations, "
                   "cross-sell and job briefings.",
        source="appointment, _mercury_purpose_value in the client meeting family, "
               "scheduled in the month.",
        grain="individual", attribution="Meeting owner",
        direction="up", target_key="client_meetings", format="count",
        prompt_context="The strongest predictor of new business. Meetings without subsequent "
                       "jobs registered suggests the meeting is not converting to a brief.",
    ),
    dict(
        key="spec_cvs", name="Spec CVs", family="Business Development",
        definition="Speculative CVs sent and their follow-ups. Replaces 'manager referral "
                   "names pulled' per the updated form.",
        source="phonecall / appointment with a Spec CV purpose, in the month.",
        grain="individual", attribution="Activity owner",
        direction="up", target_key=None, format="count",
        prompt_context="A cheap route into new clients. Spec CVs with no follow-up call rarely "
                       "convert — the follow-up is the part that works.",
    ),
    dict(
        key="leads_gained", name="Leads Gained", family="Business Development",
        definition="Leads captured from candidates or manager referrals.",
        source="phonecall with a 'Lead Gained from Candidate' or 'Manager Referral' purpose.",
        grain="individual", attribution="Activity owner",
        direction="up", target_key="leads", format="count",
        prompt_context="Free BD from work already being done. Consistently zero means "
                       "candidate calls are not asking the lead-generating questions.",
    ),
    dict(
        key="candidate_calls", name="Candidate Calls", family="Delivery Activity",
        definition="Calls to candidates: ad-response, check-ins, prep, debriefs, offers, "
                   "flips and CV follow-ups.",
        source="phonecall, _mercury_purpose_value in the candidate purpose family, in the month.",
        grain="individual", attribution="Activity owner",
        direction="up", target_key="candidate_calls", format="count",
        prompt_context="Delivery effort and candidate care. Very high candidate calls with low "
                       "CVs sent can mean time spent on unqualified candidates.",
    ),
]

REGISTRY_BY_KEY = {m["key"]: m for m in REGISTRY}
FAMILIES = list(dict.fromkeys(m["family"] for m in REGISTRY))

# Loop template defaults — seed values for per-person targets (monthly).
DEFAULT_TARGETS = {
    "revenue_year":    0,      # annual perm revenue target — drives the MBR headline
    "revenue":         0,      # set per person; no company-wide default
    "deals":           0,
    "cvs_sent":        0,
    "interviews":      0,
    "bd_actions":      300,    # from the Loop template
    "client_meetings": 8,
    "candidate_calls": 100,
    "leads":           12,
}

TARGET_KEYS = list(DEFAULT_TARGETS.keys())

# Reporting currency by territory — the same convention the weekly report and
# analytics use, so a US consultant's MBR reads in dollars throughout.
TERRITORY_CCY = {
    "Bristol":          "GBP",
    "London":           "GBP",
    "London Contract":  "GBP",
    "Chicago":          "USD",
    "New York":         "USD",
    "Chicago Contract": "USD",
    "Cameron Scott":    "GBP",
}
