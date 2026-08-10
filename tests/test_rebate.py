"""Verify the rebate maths against the worked example in rebates.md."""
import os, sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
# shared.dataverse reads its config at import time; stub it for a pure-maths test
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared.calc import compute_metrics, compute_written_months, rebate_of

UID = "u1"
# £20,125 GP New Business perm, all three roles, started 1 Jul, rebated
# £15,093.75 on 10 Aug (75%). Fee % / value clear the NB thresholds.
P = {
    "crimson_placementid": "p1",
    "crimson_name": "Rust Developer",
    "crimson_type": 143570000,
    "crimson_startdate": "2026-07-01",
    "createdon": "2026-07-01",
    "recruit_truegrossprofit": 20125.0,
    "recruit_truegrossprofitcurrency": {"isocurrencycode": "GBP"},
    "crimson_specialinstructionsclient": "New Business",
    "crimson_permanentfeepercent": 20.0,
    "crimson_clientname": {"name": "Client X"},
    "_crimson_clientname_value": "c1",
    "_mercury_clientrelationshipowner_value": UID,
    "_crimson_consultant_value": UID,
    "_mercury_assignmentowner_value": UID,
    "statuscode": 975310000,
    "recruit_rebateamount": 15093.75,
    "recruit_rebatedon": "2026-08-10",
}

assert rebate_of(P) == (15093.75, date(2026, 8, 10)), rebate_of(P)

# ── Window covering July only: full credit, no deduction yet ──
m = compute_metrics(UID, [P], "GBP", date(2026, 7, 31))
assert round(m["roll12"], 2) == 20125.00, m["roll12"]
assert round(m["roll12_uplift"], 2) == 10062.50, m["roll12_uplift"]
assert round(m["roll12_total"], 2) == 30187.50, m["roll12_total"]
assert m["rebate_total"] == 0
print(f"July only:      roll12 {m['roll12']:>10,.2f}  uplift {m['roll12_uplift']:>10,.2f}  total {m['roll12_total']:>10,.2f}")

# ── Window covering both months: nets to 1.5x the kept fee ──
m2 = compute_metrics(UID, [P], "GBP", date(2026, 8, 31))
def near(a, b, tol=0.011):
    assert abs(a - b) < tol, f"{a} != {b}"

near(m2["roll12"], 5031.25)
near(m2["roll12_uplift"], 2515.625)
near(m2["roll12_total"], 7546.88)
near(m2["rebate_total"], 22640.625)
assert m2["nb_clients"] == 1, "client count must be untouched by the rebate"
assert len(m2["rebate_detail"]) == 1
print(f"Jul+Aug:        roll12 {m2['roll12']:>10,.2f}  uplift {m2['roll12_uplift']:>10,.2f}  "
      f"total {m2['roll12_total']:>10,.2f}  (MD says 7,546.88)")
print(f"                net kept = 1.5 x kept fee {5031.25 * 1.5:,.2f} OK")
print(f"                NB clients still counted: {m2['nb_clients']} OK")

# ── YTD nets both sides in the same year ──
assert round(m2["ytd"], 2) == 5031.25, m2["ytd"]

# ── Written view (created basis) nets against the placement's own month ──
w = compute_written_months(UID, [P], "GBP", 2026)
assert round(w["months"]["7"], 2) == 5031.25, w["months"]["7"]
assert w["counts"]["7"] == 1.0, "count must survive the rebate"
print(f"Written Jul:    {w['months']['7']:>10,.2f}  count {w['counts']['7']} OK")

print("\nAll rebate assertions passed.")
