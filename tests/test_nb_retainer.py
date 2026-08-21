"""Retainers: NB uplift is exempt from the fee-% / value gates, and a flagged
retainer counts as a new-business client."""
import os, sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared.calc import compute_metrics, _nb_qualifies, NB_UPLIFT_DEFAULTS, is_retainer
from shared.dataverse import RETAINER_CANDIDATE_CONTACT_ID

UID = "u1"

def placement(**over):
    p = {
        "crimson_placementid": "p1",
        "crimson_name": "RETAINER - Head of Data",
        "crimson_type": 143570000,
        "crimson_startdate": "2026-06-11",
        "createdon": "2026-06-11",
        "recruit_truegrossprofit": 25000.0,
        "recruit_truegrossprofitcurrency": {"isocurrencycode": "GBP"},
        "crimson_specialinstructionsclient": "New Business",
        "crimson_permanentfeepercent": 8.33,      # well under the 18% gate
        "crimson_clientname": {"name": "Client X"},
        "_crimson_clientname_value": "c1",
        "_recruit_candidatecontact_value": RETAINER_CANDIDATE_CONTACT_ID,
        "_mercury_clientrelationshipowner_value": UID,
        "_crimson_consultant_value": UID,
        "_mercury_assignmentowner_value": UID,
    }
    p.update(over)
    return p

today = date(2026, 6, 30)

# A retainer at 8.33% would fail the perm gate — but retainers are exempt
r = placement()
assert is_retainer(r)
assert _nb_qualifies(r, NB_UPLIFT_DEFAULTS), "retainer should bypass the fee-% gate"

m = compute_metrics(UID, [r], "GBP", today)
assert m["nb_clients"] == 1, m["nb_clients"]
assert round(m["roll12_uplift"], 2) == 12500.00, m["roll12_uplift"]
print(f"retainer NB      : clients {m['nb_clients']}, uplift {m['roll12_uplift']:,.2f} OK")

# Same fee % on a NON-retainer must still be rejected by the gate
n = placement(_recruit_candidatecontact_value="someone-else")
assert not is_retainer(n)
assert not _nb_qualifies(n, NB_UPLIFT_DEFAULTS), "non-retainer must still face the 18% gate"
m2 = compute_metrics(UID, [n], "GBP", today)
assert m2["roll12_uplift"] == 0, m2["roll12_uplift"]
assert m2["nb_clients"] == 1, "client still counts even when the uplift doesn't"
print(f"non-retainer 8.3%: uplift {m2['roll12_uplift']:,.2f}, clients {m2['nb_clients']} OK")

# An UNFLAGGED retainer is not new business at all (detection stays flag-driven)
u = placement(crimson_specialinstructionsclient=None)
m3 = compute_metrics(UID, [u], "GBP", today)
assert m3["nb_clients"] == 0, m3["nb_clients"]
assert m3["roll12_uplift"] == 0, m3["roll12_uplift"]
print(f"unflagged retainer: clients {m3['nb_clients']}, uplift {m3['roll12_uplift']:,.2f} OK")

print("\nAll retainer NB assertions passed.")
