"""
The London Contract MBR engine: each of Jason's rulings (Oct 2026), on a small
synthetic desk. The live engine was also checked against Jonny's and Louis's
own sheets for Jan-Aug 2026 (running WGP within 0-5%, deals within one).
"""
from datetime import date

import pytest

from shared import mbr_contract as M

A, B, H, J = "alice", "bob", "house", "jonny"           # two consultants, house, director
GBP = {"GBP": 1.0}


def pl(pid, code, start, end, *, wgp=500.0, created=None, roles=(A, A, A), status=1,
       margin=20.0, client="acme", vacancy=None, ext_link=None, actual_end=None, margin_only=False):
    r = list(roles) + [None] * (4 - len(roles))
    return {"crimson_placementid": pid, "crimson_name": pid, "crimson_placementidcode": code,
            "crimson_extension": 1 if code.split("/")[1] != "00" else 0,
            "crimson_startdate": start, "crimson_enddate": end, "crimson_actualenddate": actual_end,
            "createdon": (created or start) + "T09:00:00", "statuscode": status,
            "recruit_trueweeklygrossprofit": wgp, "recruit_trueweeklygrossprofitcurrency": {"isocurrencycode": "GBP"},
            "mercury_marginpercent": margin, "mercury_ismarginonly": margin_only,
            "_crimson_clientname_value": client, "_crimson_vacancy_value": vacancy,
            "_mercury_extendedplacementid_value": ext_link,
            "_mercury_assignmentowner_value": r[0], "_crimson_consultant_value": r[1],
            "_mercury_clientrelationshipowner_value": r[2],
            "_mercury_contractorrelationship_userid_value": r[3]}


def data(**over):
    d = {"placements": [], "shortlists": [], "vacancies": [], "calls": [], "appointments": [],
         "emails": [], "first_placed": {}, "fx": GBP, "director": J, "book": {A, B, H, J},
         "presence": {A: [(date(2025, 1, 1), date(2026, 12, 31))],
                      B: [(date(2025, 1, 1), date(2026, 12, 31))]},
         "people": [{"uid": A, "name": "Alice", "active": True}, {"uid": B, "name": "Bob", "active": True}]}
    d.update(over)
    return d


def run(d, people=frozenset({A}), month=3, book=None):
    return M.finish(M.compute(set(people), 2026, month, d, GBP, J, book))


# ── Runners ───────────────────────────────────────────────────────────────────

def test_runners_are_shown_whole_and_by_split():
    """A contract Alice shares three ways is one runner, or a third by split."""
    d = data(placements=[pl("p1", "001/00/01", "2026-01-05", "2026-12-31", roles=(A, "x", "y"))])
    out = run(d)
    assert out["runners"] == 1 and out["runners_split"] == pytest.approx(1 / 3, abs=0.01)
    assert out["wgp_running"] == pytest.approx(500 / 3, abs=0.01)


def test_the_desk_book_takes_in_the_house_account_and_director():
    """Jonny's team book only reconciles with them in; headcount doesn't."""
    d = data(placements=[pl("h1", "002/00/01", "2026-01-05", "2026-12-31", roles=(H, H, H))])
    team = run(d, people={A, B}, book={A, B, H, J})
    assert team["runners"] == 1 and team["wgp_running"] == 500
    assert run(d, people={A})["runners"] == 0                   # not Alice's


def test_a_contract_and_its_extension_are_one_runner():
    d = data(placements=[pl("o", "003/00/01", "2026-01-05", "2026-03-31"),
                         pl("e", "003/01/00", "2026-03-15", "2026-09-30")])
    assert run(d)["runners"] == 1


# ── Finishers and extension % ─────────────────────────────────────────────────

def test_a_finisher_is_someone_ending_with_no_extension():
    d = data(placements=[
        pl("gone", "010/00/01", "2025-06-01", "2026-03-20"),               # finished
        pl("ext", "011/00/01", "2025-06-01", "2026-03-20"),                # extended by code
        pl("ext2", "011/01/00", "2026-03-21", "2026-09-20"),
        pl("linked", "012/00/01", "2025-06-01", "2026-03-25", ext_link="somewhere")])  # forward link
    out = run(d)
    assert out["finishers"] == 1
    assert out["extension_pct"] == pytest.approx(2 / 3)       # 2 of 3 due were extended


def test_extension_pct_next_month_uses_the_same_rule():
    d = data(placements=[pl("a", "020/00/01", "2025-06-01", "2026-04-10"),
                         pl("b", "021/00/01", "2025-06-01", "2026-04-15"),
                         pl("b2", "021/01/00", "2026-04-16", "2026-10-15")])
    out = run(d)
    assert out["finishers_next"] == 2 and out["extension_pct_next"] == pytest.approx(0.5)
    assert out["expected_finishers_wgp"] == 500                 # only the unextended one


def test_terminations_are_their_status_in_the_month():
    d = data(placements=[pl("t", "030/00/01", "2025-06-01", "2026-06-30",
                            actual_end="2026-03-10", status=143570008)])
    out = run(d)
    assert out["terminations"] == 1 and out["terminations_wgp"] == 500


# ── Deals ─────────────────────────────────────────────────────────────────────

def test_deals_are_dated_by_when_they_were_made():
    """Agreed in March, starting in April: a March deal."""
    d = data(placements=[pl("d", "040/00/01", "2026-04-06", "2026-10-06", created="2026-03-20")])
    assert run(d, month=3)["deals"] == 1 and run(d, month=4)["deals"] == 0


def test_an_extension_is_not_a_new_deal():
    d = data(placements=[pl("x", "041/01/00", "2026-03-10", "2026-09-10", created="2026-03-05")])
    assert run(d)["deals"] == 0


def test_a_margin_only_deal_stays_out_of_the_average_margin():
    d = data(placements=[pl("m1", "050/00/01", "2026-03-02", "2026-09-02", margin=20.0),
                         pl("m2", "051/00/01", "2026-03-02", "2026-09-02", margin=100.0, margin_only=True)])
    assert run(d)["deals_avg_margin"] == pytest.approx(0.20)


def test_contract_length_uses_the_agreed_end_not_an_early_finish():
    d = data(placements=[pl("l", "052/00/01", "2026-03-02", "2026-08-31", actual_end="2026-04-01")])
    assert run(d)["deals_avg_weeks"] == pytest.approx(26, abs=0.1)


# ── Interviews ────────────────────────────────────────────────────────────────

def sl(owner, job, *, first=None, further=None, cv=None, client="acme"):
    return {"_owninguser_value": owner, "_crimson_vacancyid_value": job, "_crimson_clientid_value": client,
            "new_statussubmitteddate": cv, "mercury_firstinterviewdate": first,
            "mercury_furtherinterviewdate": further, "mercury_finalinterviewdate": None}


def test_first_interviews_and_jmis():
    """A JMI is a job with more than one interview against it in the month."""
    d = data(shortlists=[sl(A, "j1", first="2026-03-03"), sl(A, "j1", first="2026-03-10", further="2026-03-20"),
                         sl(A, "j2", first="2026-03-12")])
    out = run(d)
    assert out["interviews"] == 4 and out["interviews_first"] == 3
    assert out["jmis"] == 1 and out["jobs_with_iv"] == 2


# ── Jobs ──────────────────────────────────────────────────────────────────────

GRADE = {g: k for k, g in M.GRADES.items()}


def vac(vid, grade, created, owner=A, client="acme", open_=True, closed=None):
    return {"crimson_vacancyid": vid, "_mercury_vacancytype_value": GRADE[grade], "_crimson_clientid_value": client,
            "_crimson_deliveryownerid_value": owner, "createdon": created + "T09:00:00",
            "statecode": 0 if open_ else 1, "modifiedon": (closed or created) + "T09:00:00",
            "crbb7_closedon": closed and closed + "T09:00:00", "recruit_closeddate": None}


def test_jobs_belong_to_their_delivery_owner_and_ratios_read_jobs_per_placement():
    d = data(vacancies=[vac("v1", "A", "2026-03-02"), vac("v2", "B", "2026-03-05"),
                        vac("v3", "B", "2026-03-09", owner=B)],
             placements=[pl("p", "060/00/01", "2026-03-20", "2026-09-20", vacancy="v1")])
    out = run(d)
    assert out["jobs_added"] == 2                              # Bob's job isn't Alice's
    assert out["jobs_per_placement"] == pytest.approx(2.0)
    assert out["a_jobs_per_placement"] == pytest.approx(1.0)   # 1 A job, 1 A filled


def test_a_speculative_job_is_covered_once_a_cv_goes_against_it():
    d = data(vacancies=[vac("s1", "S", "2026-03-02"), vac("s2", "S", "2026-03-04")],
             shortlists=[sl(A, "s1", cv="2026-03-06")])
    out = run(d)
    assert out["jobs_spec"] == 2 and out["jobs_spec_covered"] == 1


def test_carried_in_uses_the_closing_date_where_there_is_one():
    d = data(vacancies=[vac("c1", "A", "2026-01-10"),                                   # still open
                        vac("c2", "A", "2026-01-10", open_=False, closed="2026-02-15"),  # closed before March
                        vac("c3", "B", "2026-01-10", open_=False, closed="2026-03-20")]) # open on 1 March
    out = run(d)
    assert out["carried_a"] == 1 and out["carried_b"] == 1


# ── Customers ─────────────────────────────────────────────────────────────────

def test_a_new_customer_is_one_never_placed_with_before():
    d = data(placements=[pl("n", "070/00/01", "2026-03-10", "2026-09-10", client="newco"),
                         pl("o", "071/00/01", "2026-03-10", "2026-09-10", client="oldco")],
             first_placed={"newco": date(2026, 3, 10), "oldco": date(2024, 5, 1)})
    assert run(d)["new_customers_placed"] == 1


# ── Headcount and periods ─────────────────────────────────────────────────────

def test_headcount_counts_part_months_pro_rata():
    d = data(presence={A: [(date(2025, 1, 1), date(2026, 12, 31))],
                       B: [(date(2026, 3, 17), date(2026, 12, 31))]})      # joins 17 March
    assert run(d, people={A, B})["headcount"] == pytest.approx(1 + 15 / 31, abs=0.01)


def test_quarter_ratios_come_from_totals_not_an_average_of_ratios():
    jan = M.finish({"interviews": 10, "deals": 1})
    feb = M.finish({"interviews": 2, "deals": 2})
    q = M.period([jan, feb])
    assert q["iv_per_placement"] == pytest.approx(12 / 3)      # not (10 + 1) / 2
    assert q["interviews"] == pytest.approx(6)                 # quarter is a monthly average


def test_new_customers_add_up_over_a_quarter():
    q = M.period([M.finish({"new_customers_placed": 1}), M.finish({"new_customers_placed": 2})])
    assert q["new_customers_placed"] == 3


def test_every_measure_says_wgp_never_wnf():
    for key, label, *_ in M.MEASURES:
        assert "WNF" not in label and "NFI" not in label, key


# ── Typed rows (Jason, Oct 2026): every column typed, ratios follow ───────────

def test_typed_quarters_drive_their_ratios_against_the_quarters_totals():
    """Q1 GP per fee earner = Q1's typed GP over Q1's person-months — not over
    the quarter's average headcount, which would triple it."""
    d = data(presence={A: [(date(2025, 1, 1), date(2026, 12, 31))]})
    d["people"] = [{"uid": A, "name": "Alice", "active": True}]
    inputs = {"gp_month:2026-01": 100, "gp_month:2026-02": 100, "gp_month:2026-03": 100,
              "gp_month:2026-Q1": 300, "gp_budget:2026-Q1": 600}
    v = M.build_view("London Contract", 2026, "team", inputs, today=date(2026, 4, 15), data=d)
    q1 = v["values"]["Q1"]
    assert q1["gp_month"] == 300
    assert q1["gp_achievement"] == pytest.approx(0.5)
    assert q1["gp_per_head"] == pytest.approx(300 / 3)           # 3 person-months


def test_an_empty_typed_cell_offers_mercurys_figure_as_a_guide():
    d = data(vacancies=[vac("c1", "A", "2026-01-10")])
    d["people"] = [{"uid": A, "name": "Alice", "active": True}]
    v = M.build_view("London Contract", 2026, "team", {}, today=date(2026, 3, 15), data=d)
    assert v["values"]["P3"]["carried_a"] is None                # nothing typed
    assert v["estimates"]["carried_a|P3"] == 1                   # Mercury's guess, shown greyed
