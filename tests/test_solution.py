"""Deploy & Component (solution) revenue: windows, HPB quarters, year totals."""
import os, sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared.calc import (solution_manual_metrics, solution_year_total,
                         solution_quarters)

# Today is 24 Aug 2026, so the ledger runs Aug 25 .. Jul 26 (a month behind).
today = date(2026, 8, 24)
ledger = {
    "2025-8": 1000, "2025-9": 1000, "2025-10": 1000, "2025-11": 1000, "2025-12": 1000,
    "2026-1": 2000, "2026-2": 2000, "2026-3": 2000,
    "2026-4": 3000, "2026-5": 3000, "2026-6": 3000,
    "2026-7": 4000,
    "2026-8": 9999,   # current month — must be excluded, entry is a month behind
}

m = solution_manual_metrics(ledger, today)
# YTD = Jan..Jul 2026 only
assert m["solution_ytd"] == 2000*3 + 3000*3 + 4000, m["solution_ytd"]
# Rolling 12 = Aug 25 .. Jul 26
assert m["solution_roll12"] == 1000*5 + 2000*3 + 3000*3 + 4000, m["solution_roll12"]
print(f"YTD {m['solution_ytd']:,}  Rolling12 {m['solution_roll12']:,}  "
      f"(current month excluded) OK")

# Analytics column = everything booked in the calendar year, current month included
assert solution_year_total(ledger, 2026) == 2000*3 + 3000*3 + 4000 + 9999
assert solution_year_total(ledger, 2025) == 5000
print(f"Year total 2026 {solution_year_total(ledger, 2026):,}  2025 {solution_year_total(ledger, 2025):,} OK")

# HPB quarters
q = solution_quarters(ledger, 2026)
assert q["1"] == 6000, q          # Jan-Mar
assert q["2"] == 9000, q          # Apr-Jun
assert q["3"] == 4000 + 9999, q   # Jul-Sep
assert q["4"] == 0, q
print(f"Quarters {q} OK")

# Empty / missing ledgers must be harmless
assert solution_manual_metrics(None, today) == {"solution_ytd": 0, "solution_roll12": 0}
assert solution_quarters(None, 2026) == {"1": 0.0, "2": 0.0, "3": 0.0, "4": 0.0}
assert solution_year_total(None, 2026) == 0
print("empty ledger safe OK")

print("\nAll solution-revenue assertions passed.")
