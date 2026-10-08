"""
Month-end snapshots of the Contract MBR (Jason, Oct 2026).

Mercury keeps moving after a month closes: contracts are cancelled, entries are
back-dated, owners are reassigned. So a month worked out live in November is
not the month Jonny reviewed in October. At 23:59 London time on the last day
of each month, the desk's figures — the team and every consultant — are worked
out and frozen. From then on that month shows what it was at 23:59, not what
Mercury says today.

Stored in the MBR table (crbb7_mbr), one record per view per month, under a
user id that can't collide with a person's: "snapshot:<desk>:team" or
"snapshot:<desk>:<systemuserid>". Each record is the engine's raw month (before
finishing), so frozen and live months go through exactly the same arithmetic.

Typed figures (GP, budgets, carried-in) aren't frozen: they're Jonny's own
inputs and stay editable.

Triggered every minute by the Logic App behind /api/board-schedule-run; only
the run at 23:59 on the last day does anything. A missed 23:59 (the app down)
is caught up in the first hours of the next month, marked late.
"""
import calendar
import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")
STATUS = "snapshot"
# A snapshot missed at 23:59 is still taken up to this long after, marked late;
# later than that it would hold too much of the next month's changes to be
# worth calling the month end.
CATCH_UP = timedelta(hours=6)


def view_id(desk: str, view: str) -> str:
    return f"snapshot:{desk}:{view}"


def month_due(now_utc: datetime) -> tuple | None:
    """
    (year, month, late) if a month-end snapshot is due now, else None.
    Due from 23:59 London time on the last day of the month, and — in case
    that minute was missed — until CATCH_UP into the next month.
    """
    local = now_utc.astimezone(LONDON)
    last = calendar.monthrange(local.year, local.month)[1]
    if local.day == last and (local.hour, local.minute) >= (23, 59):
        return local.year, local.month, False
    first_of_month = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if local - first_of_month < CATCH_UP - timedelta(minutes=1):
        prev = first_of_month - timedelta(days=1)
        return prev.year, prev.month, True
    return None


def load(desk: str, view: str, year: int) -> dict:
    """{month: {"raw": {...}, "taken_at": iso, "late": bool}} for one view's year."""
    from shared.dataverse import odata_get_all, odata_str
    try:
        rows = odata_get_all("crbb7_mbrs", params={
            "$select": "crbb7_month,crbb7_payload",
            "$filter": (f"crbb7_user_id eq '{odata_str(view_id(desk, view))}'"
                        f" and crbb7_entry_year eq {int(year)} and crbb7_status eq '{STATUS}'"),
        })
    except Exception:
        logging.warning("Could not read MBR snapshots", exc_info=True)
        return {}
    out = {}
    for r in rows:
        try:
            out[int(r["crbb7_month"])] = json.loads(r.get("crbb7_payload") or "{}")
        except (ValueError, TypeError):
            continue
    return out


def exists(desk: str, year: int, month: int) -> bool:
    return month in load(desk, "team", year)


def _store(desk: str, view: str, year: int, month: int, payload: dict) -> None:
    from shared.dataverse import odata_get_all, odata_patch, odata_post, odata_str
    uid = view_id(desk, view)
    body = {"crbb7_user_id": uid, "crbb7_entry_year": int(year), "crbb7_month": int(month),
            "crbb7_payload": json.dumps(payload, separators=(",", ":")),
            "crbb7_status": STATUS, "crbb7_name": f"MBR snapshot {desk} {view} {year}-{month:02d}"[:840]}
    existing = odata_get_all("crbb7_mbrs", params={
        "$select": "crbb7_mbrid",
        "$filter": (f"crbb7_user_id eq '{odata_str(uid)}' and crbb7_entry_year eq {int(year)}"
                    f" and crbb7_month eq {int(month)}"),
    })
    if existing:
        odata_patch(f"crbb7_mbrs({existing[0]['crbb7_mbrid']})", body)
    else:
        odata_post("crbb7_mbrs", body)


def _compact(raw: dict) -> dict:
    """Round the floats, so a month fits comfortably in one record."""
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in raw.items()}


def take(desk: str, year: int, month: int, late: bool = False, now_utc: datetime | None = None) -> dict:
    """Work out the month as Mercury has it now, and freeze it. Returns a summary."""
    from shared.mbr_contract import compute, fetch_year
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    data = fetch_year(desk, year, last_day)
    taken = (now_utc or datetime.now(tz=LONDON)).astimezone(LONDON).isoformat(timespec="seconds")
    team_ids = {p["uid"] for p in data["people"]}
    views = [("team", team_ids, data["director"], data.get("book"))]
    views += [(uid, {uid}, None, None) for uid in sorted(team_ids)]
    for view, people, director, book in views:
        raw = compute(people, year, month, data, data["fx"], director, book)
        _store(desk, view, year, month, {"taken_at": taken, "late": late, "raw": _compact(raw)})
    return {"desk": desk, "year": year, "month": month, "views": len(views), "late": late,
            "taken_at": taken}


def run_due(now_utc: datetime | None = None) -> list:
    """Take any month-end snapshot that is due and not yet taken. Safe to call
    every minute: once a month is frozen it's left alone."""
    from shared.mbr_contract import DESKS
    now_utc = now_utc or datetime.now(tz=ZoneInfo("UTC"))
    due = month_due(now_utc)
    if not due:
        return []
    year, month, late = due
    done = []
    for desk in DESKS:
        try:
            if exists(desk, year, month):
                continue
            done.append(take(desk, year, month, late, now_utc))
        except Exception:
            logging.exception("MBR snapshot failed for %s %s-%02d", desk, year, month)
    return done
