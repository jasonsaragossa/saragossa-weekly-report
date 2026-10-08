"""
The Contract MBR as Jonny's own Excel workbook (Jason, Oct 2026).

The team view comes out as his Director sheet and a consultant's view as the
consultant sheet (Louis's layout), built from blank copies of his workbooks in
api/templates/ (see scripts/build_mbr_templates.py). Each month's figure goes
in its P column; the quarter, half-year and ratio cells are his own formulas,
which Excel works out on opening. Rows the app doesn't produce stay as he left
them: empty, for typing.
"""
import pathlib

from shared import xlsx_cells as X

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates"

# P1..P12 -> the sheet's month columns (quarters and halves sit between them)
MONTH_COL = {1: "C", 2: "D", 3: "E", 4: "G", 5: "H", 6: "I",
             7: "L", 8: "M", 9: "N", 10: "P", 11: "Q", 12: "R"}
PERIOD_COL = {"Q1": "F", "Q2": "J", "H1": "K", "Q3": "O", "Q4": "S", "H2": "T"}

# Director sheet, "Contract Performance": row -> (label as on the sheet, measure)
DIRECTOR_ROWS = {
    2: ("NFI (Month)", "gp_month"),
    3: ("NFI (Budget)", "gp_budget"),
    5: ("Runners out", "runners_split"),
    6: ("Runners out (budget)", "runners_budget"),
    8: ("NFI per fee earner (budget)", "gp_per_head_budget"),
    9: ("HC", "headcount"),
    10: ("TRWNF last day of period", "wgp_running"),
    11: ("# of runners", "runners"),
    15: ("Extension % in month", "extension_pct"),
    16: ("# of terminations in month", "terminations"),
    17: ("Value of terminations in month", "terminations_wgp"),
    20: ("# of starters next month", "starters_next"),
    21: ("Starters next month total WNF", "starters_next_wgp"),
    22: ("# of finishers next month", "finishers_next"),
    23: ("Total finishers next month WNF", "finishers_next_wgp"),
    25: ("# of actual finishers in month", "finishers"),
    26: ("Actual finishers in month WNF", "finishers_wgp"),
    27: ("Extension % in coming month", "extension_pct_next"),
    31: ("Number of deals", "deals"),
    32: ("NDWNF added", "deals_wgp"),
    36: ("Average margin of new deals", "deals_avg_margin"),
    37: ("Average length of contract (weeks)", "deals_avg_weeks"),
    38: ("Number of clients placed with", "clients_placed"),
    41: ("Number of interviews", "interviews"),
    42: ("Number of unique interviews", "interviews_first"),
    43: ("Number of JMIs", "jmis"),
    47: ("Number of jobs w/ IV", "jobs_with_iv"),
    48: ("Number of clients w/ IV", "clients_with_iv"),
    49: ("CV Submissions", "cvs"),
    52: ("A jobs", "jobs_a"),
    53: ("B jobs", "jobs_b"),
    54: ("C jobs", "jobs_c"),
    56: ("Number of clients with jobs", "clients_with_jobs"),
    63: ("F jobs", "jobs_f"),
    64: ("P jobs", "jobs_p"),
    67: ("Jobs filled A", "filled_a"),
    68: ("Jobs filled B", "filled_b"),
    73: ("A jobs carried into period", "carried_a"),
    74: ("B jobs carried into period", "carried_b"),
    78: ("Client meetings", "client_meetings"),
    80: ("Client meetings personally", "client_meetings_own"),
    83: ("Candidate calls", "candidate_calls"),
    84: ("Contractor leads pulled", "contractor_leads"),
    85: ("Manager referral names pulled", "manager_referrals"),
    88: ("BD calls", "bd_calls"),
    89: ("Pitch Delivered", "pitches"),
    91: ("Emails Sent", "bd_emails"),
    94: ("New customers w/ placements done", "new_customers_placed"),
    95: ("New customers w/ A,B,C,F,P jobs added", "new_customers_jobs"),
    96: ("New customers w/ meetings booked", "new_customers_meetings"),
}

# Consultant sheet, "Performance" (Louis's layout)
CONSULTANT_ROWS = {
    2: ("TRWNF last day of period", "wgp_running"),
    3: ("# of runners", "runners"),
    6: ("Starters next period", "starters_next_wgp"),
    7: ("Finishers next period (No, Unsure, Update Required)", "expected_finishers_wgp"),
    11: ("Number of deals", "deals"),
    12: ("NDWNF added", "deals_wgp"),
    14: ("Average length of contract (weeks)", "deals_avg_weeks"),
    15: ("Number of clients placed with", "clients_placed"),
    18: ("Number of interviews", "interviews"),
    19: ("Number of unique interviews", "interviews_first"),
    20: ("Number of JMIs", "jmis"),
    23: ("Number of jobs w/ IV", "jobs_with_iv"),
    24: ("Number of clients w/ IV", "clients_with_iv"),
    27: ("A jobs", "jobs_a"),
    28: ("B jobs", "jobs_b"),
    29: ("C jobs", "jobs_c"),
    37: ("F jobs", "jobs_f"),
    38: ("P jobs", "jobs_p"),
    41: ("Speculative jobs", "jobs_spec"),
    42: ("Speculative jobs covered", "jobs_spec_covered"),
    45: ("Jobs filled A", "filled_a"),
    46: ("Jobs filled B", "filled_b"),
    47: ("Jobs filled C", "filled_c"),
    53: ("A jobs carried into period", "carried_a"),
    54: ("B jobs carried into period", "carried_b"),
    55: ("C jobs carried into period", "carried_c"),
    59: ("Client meetings", "client_meetings"),
    60: ("Candidate meetings", "candidate_meetings"),
    63: ("Candidate calls", "candidate_calls"),
    64: ("Contractor leads pulled", "contractor_leads"),
    65: ("Manager referral names pulled", "manager_referrals"),
    68: ("BD calls - no pitch", "bd_calls"),
    69: ("BD calls or follow up calls - pitch delivered", "pitches"),
    70: ("BD Emails sent", "bd_emails"),
    71: ("Reference calls", "reference_calls"),
    74: ("New customers w/ placements done i.e. no live runners on site", "new_customers_placed"),
    75: ("New customers w/ A,B,C,F,P jobs added  i.e. no live runners on site", "new_customers_jobs"),
    76: ("New customers w/ meetings booked i.e. no live runners on site", "new_customers_meetings"),
}

# Sheet parts inside each template
DIRECTOR_PERF, DIRECTOR_WGP = "xl/worksheets/sheet1.xml", "xl/worksheets/sheet3.xml"
CONSULTANT_PERF, CONSULTANT_WGP = "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"


def _month_cells(view: dict, rows: dict) -> dict:
    vals = view["values"]
    cells = {}
    for row, (_label, key) in rows.items():
        for m, col in MONTH_COL.items():
            v = (vals.get(f"P{m}") or {}).get(key)
            if v is not None:
                cells[f"{col}{row}"] = v
    return cells


def _edit(cells: dict):
    return lambda xml: X.drop_cached_formula_results(X.set_cells(xml, cells))


def director(team: dict, consultants: list) -> bytes:
    """team: build_view(..., "team"); consultants: [(name, build_view(..., uid))]."""
    tracker = {}
    for i, (name, view) in enumerate(consultants):
        row = 4 + i
        tracker[f"A{row}"] = name
        for m, col in MONTH_COL.items():
            v = (view["values"].get(f"P{m}") or {}).get("wgp_running")
            if v is not None:
                tracker[f"{col}{row}"] = v
        for p, col in PERIOD_COL.items():
            v = (view["values"].get(p) or {}).get("wgp_running")
            if v is not None:
                tracker[f"{col}{row}"] = v
    src = (TEMPLATES / "mbr_director.xlsx").read_bytes()
    return X.rewrite(src, {DIRECTOR_PERF: _edit(_month_cells(team, DIRECTOR_ROWS)),
                           DIRECTOR_WGP: _edit(tracker),
                           "xl/workbook.xml": X.recalc_on_open})


def consultant(view: dict) -> bytes:
    tracker = {}
    for m in range(1, 13):
        v = (view["values"].get(f"P{m}") or {}).get("wgp_running")
        if v is not None:
            tracker[f"{'BCDEFGHIJKLM'[m - 1]}4"] = v
    src = (TEMPLATES / "mbr_consultant.xlsx").read_bytes()
    return X.rewrite(src, {CONSULTANT_PERF: _edit(_month_cells(view, CONSULTANT_ROWS)),
                           CONSULTANT_WGP: _edit(tracker),
                           "xl/workbook.xml": X.recalc_on_open})
