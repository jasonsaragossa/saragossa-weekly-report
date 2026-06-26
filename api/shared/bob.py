"""
HiBob (Bob) client — reads employee job-title history so HPB grades can be
derived per quarter from the HR source of truth.

Auth: HTTP Basic with base64(BOB_SERVICE_ID:BOB_SERVICE_TOKEN). Create a Bob
service user with "View employees' Work section histories" permission.
"""
import os, base64, requests
from datetime import date, datetime

BOB_BASE = "https://api.hibob.com/v1"


def _auth_header() -> dict:
    sid = os.environ.get("BOB_SERVICE_ID")
    tok = os.environ.get("BOB_SERVICE_TOKEN")
    if not sid or not tok:
        raise RuntimeError("BOB_SERVICE_ID / BOB_SERVICE_TOKEN not configured")
    raw = f"{sid}:{tok}".encode("utf-8")
    return {
        "Authorization": "Basic " + base64.b64encode(raw).decode("ascii"),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def find_employee_id(email: str) -> str | None:
    resp = requests.post(
        f"{BOB_BASE}/people/search",
        headers=_auth_header(),
        json={
            "fields": ["root.id", "root.email", "root.fullName"],
            "filters": [{"fieldPath": "root.email", "operator": "equals", "values": [email]}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    employees = resp.json().get("employees", [])
    if not employees:
        return None
    emp = employees[0]
    return emp.get("/root/id") or emp.get("id")


def get_work_history(emp_id: str) -> list[dict]:
    resp = requests.get(f"{BOB_BASE}/people/{emp_id}/work", headers=_auth_header(), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("values", data) if isinstance(data, dict) else data


# ── Title → HPB grade (same logic the app uses elsewhere) ──────────────────────

def title_to_grade(title: str) -> str:
    t = (title or "").lower()
    if "team lead" in t:  return "team_lead"
    if "associate" in t:  return "associate"
    if "senior" in t:     return "senior"
    if "principal" in t:  return "principal"
    if "consultant" in t: return "consultant"
    return "none"


def _parse(d) -> date | None:
    if not d:
        return None
    s = str(d)[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _entry_title(e: dict) -> str:
    return e.get("title") or e.get("jobTitle") or e.get("role") or ""


def _entry_effective(e: dict) -> date | None:
    return _parse(e.get("effectiveDate") or e.get("activeEffectiveDate") or e.get("startDate"))


def grades_by_quarter(history: list[dict], year: int) -> dict:
    """{ '1': {date, title, grade}, ... } using the latest entry on/before each quarter start."""
    dated = [(_entry_effective(e), _entry_title(e)) for e in history]
    dated = sorted([(d, t) for d, t in dated if d is not None], key=lambda x: x[0])
    out = {}
    for q in range(1, 5):
        qstart = date(year, 3 * (q - 1) + 1, 1)
        title = ""
        for d, t in dated:
            if d <= qstart:
                title = t
        out[str(q)] = {"as_of": qstart.isoformat(), "title": title, "grade": title_to_grade(title)}
    return out
