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
    val = emp.get("/root/id") or emp.get("id")
    # Bob wraps field values as {"value": "..."} — unwrap to the bare id.
    if isinstance(val, dict):
        val = val.get("value")
    return val


def get_work_history(emp_id: str) -> list[dict]:
    resp = requests.get(f"{BOB_BASE}/people/{emp_id}/work", headers=_auth_header(), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("values", data) if isinstance(data, dict) else data


def get_named_lists() -> dict:
    resp = requests.get(f"{BOB_BASE}/company/named-lists", headers=_auth_header(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def _flatten_named_lists(node, out: dict) -> None:
    """Walk the named-lists JSON, recording {str(id): label} for every value node."""
    if isinstance(node, dict):
        nid = node.get("id")
        label = node.get("value") or node.get("name")
        if nid is not None and isinstance(label, str):
            out[str(nid)] = label
        for v in node.values():
            _flatten_named_lists(v, out)
    elif isinstance(node, list):
        for item in node:
            _flatten_named_lists(item, out)


def build_title_map() -> dict:
    """{ str(list-value id): human title } across all company named lists."""
    out = {}
    _flatten_named_lists(get_named_lists(), out)
    return out


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


def _val(x):
    """Bob sometimes wraps a field as {'value': ...} — return the bare value."""
    return x.get("value") if isinstance(x, dict) else x


def _entry_title(e: dict) -> str:
    return _val(e.get("title") or e.get("jobTitle") or e.get("role")) or ""


def _entry_effective(e: dict) -> date | None:
    return _parse(_val(e.get("effectiveDate") or e.get("activeEffectiveDate") or e.get("startDate")))


def employment_start(history: list[dict]) -> str | None:
    """Earliest work-entry effective date = the employee's start date (ISO), or None."""
    dates = [d for d in (_entry_effective(e) for e in history) if d is not None]
    return min(dates).isoformat() if dates else None


def _resolved_title(e: dict, title_map: dict) -> str:
    """Title text for a work entry, resolving Bob's numeric list-value id to its label."""
    raw = _entry_title(e)
    return (title_map or {}).get(str(raw), raw)


def grades_by_quarter(history: list[dict], year: int, title_map: dict = None) -> dict:
    """{ '1': {date, title, grade}, ... } using the latest entry on/before each quarter start."""
    dated = [(_entry_effective(e), _resolved_title(e, title_map)) for e in history]
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


def get_titles_for_emails(emails: list[str], year: int) -> dict:
    """
    Best-effort: for each email, return the Bob job title resolved to an HPB grade
    key for the current title and each quarter start.

    Returns { email_lower: {"current": grade, "quarters": {"1": grade, ...}} }.
    Emails not found in Bob (or that error) are simply omitted, so callers fall
    back to their existing source.
    """
    from concurrent.futures import ThreadPoolExecutor

    emails = [e for e in emails if e]
    if not emails:
        return {}
    title_map = build_title_map()   # one call, shared across everyone

    def fetch(email: str):
        try:
            emp_id = find_employee_id(email)
            if not emp_id:
                return email, None
            history = get_work_history(emp_id)
            quarters = {q: g["grade"] for q, g in grades_by_quarter(history, year, title_map).items()}
            return email, {
                "current": current_grade(history, title_map)["grade"],
                "quarters": quarters,
                "start": employment_start(history),
            }
        except Exception:
            return email, None

    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for email, data in ex.map(fetch, emails):
            if data:
                out[email.lower()] = data
    return out


def current_grade(history: list[dict], title_map: dict = None) -> dict:
    """Current title/grade — the entry flagged isCurrent, else the latest by effective date."""
    cur = next((e for e in history if e.get("isCurrent")), None)
    if cur is None and history:
        cur = max(history, key=lambda e: _entry_effective(e) or date.min)
    if cur is None:
        return {"title": "", "grade": "none"}
    title = _resolved_title(cur, title_map)
    return {"title": title, "grade": title_to_grade(title)}
