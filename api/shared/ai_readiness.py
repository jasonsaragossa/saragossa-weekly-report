"""
AI Readiness scores for the 121s and MBRs.

The AI Readiness app scores every consultant once a day and serves the result
from its snapshot at /api/consultant-scores — see
saragossa-ai-readiness-repo/docs/consultant-scores-api.md. This is the only
place the weekly report talks to it.

How the score is used (Jason, Sep 2026):

  * While a 1:1 or MBR is UNSAVED, the page shows the person's current score,
    fetched on each load.
  * On the FIRST save the score is written into the saved record and kept —
    reopening the record shows the score that was actually discussed, not
    today's, and a later edit to fix a typo does not move it.
  * Nothing is backfilled. Records saved before this went in, and months
    before it, show "—".

Everything degrades to None: AI Readiness being down must never block a 1:1.
"""
import logging
import os
from datetime import date, datetime, timezone

import requests

TIMEOUT_S = 8      # inside the 45-second gateway budget the page already spends


def _fetch(uid: str, params: dict = None) -> dict | None:
    """The consultant's record from AI Readiness, or None if unavailable."""
    base = (os.environ.get("AI_READINESS_URL") or "").rstrip("/")
    key = os.environ.get("AI_READINESS_API_KEY") or ""
    if not base or not key or not uid:
        return None
    try:
        resp = requests.get(f"{base}/api/consultant-scores",
                            params={"userId": uid, **(params or {})},
                            headers={"x-api-key": key}, timeout=TIMEOUT_S)
        resp.raise_for_status()
        people = resp.json().get("consultants") or []
        return people[0] if people else None
    except Exception:
        logging.warning("AI Readiness unavailable for %s", uid, exc_info=True)
        return None


def band(score) -> str | None:
    """The app's own colour bands: red < 50, amber 50–74, green ≥ 75."""
    if score is None:
        return None
    return "red" if score < 50 else "amber" if score < 75 else "green"


def _stamp(extra: dict) -> dict:
    return {**extra, "captured": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def latest_score(uid: str) -> dict | None:
    """
    For a 1:1: where the person is today.
    {"score", "date", "issues", "captured"} or None.
    """
    rec = _fetch(uid)
    latest = (rec or {}).get("latest")
    if not latest or latest.get("score") is None:
        return None
    return _stamp({"score": round(float(latest["score"]), 1),
                   "date": latest.get("date"), "issues": latest.get("issues")})


def month_score(uid: str, year: int, month: int) -> dict | None:
    """
    For an MBR: the calendar month's average, which is the month's figure
    rather than one day's blip. Only this month is asked for — nothing before
    the feature went in is fetched.
    {"score", "month": "YYYY-MM", "days", "captured"} or None.
    """
    first = date(year, month, 1)
    last = (date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1))
    rec = _fetch(uid, {"from": first.isoformat(),
                       "to": min(last, date.today()).isoformat()})
    key = f"{year:04d}-{month:02d}"
    value = ((rec or {}).get("monthly") or {}).get(key)
    if value is None:
        return None
    days = sum(1 for p in (rec.get("points") or []) if str(p.get("date", "")).startswith(key))
    return _stamp({"score": round(float(value), 1), "month": key, "days": days})


def for_display(snap: dict | None, live: bool) -> dict | None:
    """What the page gets: the snapshot plus its band and whether it is live."""
    if not snap:
        return None
    return {**snap, "band": band(snap.get("score")), "live": live}
