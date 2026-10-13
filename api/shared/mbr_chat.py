"""
Ask the MBR — a chat for Jonny about his own MBR pages (Jason, Oct 2026).

Only Jonny Demko has it. Each question goes to Claude Haiku 5.5 with every
column and number of both his desks — London Contract and London Perm, the team
and every consultant, month by month — plus what each measure means, so the
answers come from his figures rather than from general advice.

The desks' figures are built from the same views the MBR pages show (typed
figures, month-end freezes and all), rendered as compact tables, and cached for
ten minutes alongside the desk data, so a conversation costs one build. The
system prompt and the figures form a fixed prefix that is prompt-cached, so
follow-up questions only pay for the new turn.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date

MODEL = os.environ.get("MBR_CHAT_MODEL", "claude-haiku-5-5")
# Who has the chat. Explicit, not a role: Jason asked for Jonny only.
CHAT_USERS = {"jonny@saragossa.io"}
DESKS = ("London Contract", "London Perm")
MAX_TURNS = 20                      # history kept per request
MAX_QUESTION = 2000                 # characters

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def can_chat(email: str) -> bool:
    return (email or "").lower() in CHAT_USERS


# ── The figures, as text ──────────────────────────────────────────────────────

def _fmt(unit: str, v) -> str:
    if v is None:
        return "-"
    if unit == "money":
        return f"£{v:,.0f}"
    if unit == "pct":
        return f"{v * 100:.0f}%"
    if unit in ("ratio", "weeks"):
        return f"{v:.2f}"
    return f"{v:g}" if isinstance(v, (int, float)) and float(v).is_integer() else f"{v:.2f}"


def _table(view: dict) -> str:
    """One view as a pipe table: a row per measure, a column per month to date,
    then the year to date. Sections become header lines."""
    months = [c for c in view["columns"] if c.startswith("P")]
    cols = months + (["YTD"] if "YTD" in view["columns"] else [])
    head = [MONTHS[int(c[1:]) - 1] + (" (so far)" if c == view.get("partial") else "")
            + (" (frozen at month end)" if c in (view.get("frozen") or {}) else "")
            if c.startswith("P") else "Year to date" for c in cols]
    lines, section = [], None
    lines.append("| Measure | " + " | ".join(head) + " |")
    for m in view["measures"]:
        if m["section"] != section:
            section = m["section"]
            lines.append(f"| **{section}** |" + " |" * len(cols))
        tags = []
        if m.get("input"):
            tags.append("typed by Jonny")
        if m.get("estimate"):
            tags.append("estimate")
        label = m["label"] + (f" [{', '.join(tags)}]" if tags else "")
        vals = [_fmt(m["unit"], (view["values"].get(c) or {}).get(m["key"])) for c in cols]
        # Mercury's own figure, where a typed box is still empty
        for i, c in enumerate(cols):
            guide = (view.get("estimates") or {}).get(f"{m['key']}|{c}")
            if vals[i] == "-" and guide is not None:
                vals[i] = f"({_fmt(m['unit'], guide)} Mercury guide)"
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    return "\n".join(lines)


def _desk_text(desk: str, year: int) -> str:
    from shared import mbr_snapshot
    from shared.dataverse import get_mbr_targets
    from shared.mbr_contract import DESK_KEY, DESK_KIND, _fetch_cached, build_view
    today = date.today()
    data = _fetch_cached(desk, year, today)
    key = DESK_KEY.format(desk=desk)
    inputs = get_mbr_targets(key).get(key, {})
    # Each view's month-end freezes are one query apiece — fetch them together
    views = ["team"] + [p["uid"] for p in data["people"]]
    with ThreadPoolExecutor(max_workers=8) as pool:
        snaps = dict(zip(views, pool.map(lambda v: mbr_snapshot.load(desk, v, year), views)))
    team = build_view(desk, year, "team", inputs, data=data, snapshots=snaps["team"])
    kind = "perm (direct hire)" if DESK_KIND.get(desk) == "perm" else "contract"
    parts = [f"# {desk} — {kind} desk, {year}",
             f"## Whole team\n{_table(team)}"]
    for p in team["people"]:
        view = build_view(desk, year, p["uid"], {}, data=data, snapshots=snaps.get(p["uid"]))
        status = "" if p["active"] else " (left the desk this year)"
        parts.append(f"## {p['name']}{status}\n{_table(view)}")
    return "\n\n".join(parts)


def figures(year: int) -> str:
    """Both desks, as text. Cached ten minutes, like the desk data under it."""
    from shared.dataverse import ttl_cached
    global _CACHED
    if _CACHED is None:
        _CACHED = ttl_cached(600, copy=False)(_figures)
    return _CACHED(year)


_CACHED = None


def _figures(year: int) -> str:
    with ThreadPoolExecutor(max_workers=2) as pool:
        texts = list(pool.map(lambda d: _desk_text(d, year), DESKS))
    return "\n\n".join(texts)


# ── The brief ─────────────────────────────────────────────────────────────────

DEFINITIONS = """\
How the figures are worked out (the app's own rules — rely on these):
- Months are calendar months. "Year to date" covers every month so far. Quarter
  columns are monthly averages, except GP (summed) and ratios (from the totals).
- Contract desk money is weekly gross profit (WGP) in GBP — the weekly margin a
  contractor earns. "Running WGP at month end" is the book's weekly earning power
  on the last day. GP for the month is typed by Jonny from finance.
- Runners are contractors out on assignment. "Runners (whole)" counts people;
  "Runners out (by split)" credits shared deals 0.5 to Consultant and 0.5 to
  Assignment Owner (0.25 each on a four-way deal).
- Deals are dated by when they were made. Starters/finishers go by start/end
  dates; a finisher is a contract ending without an extension. Extension % in a
  month is, of contracts ending that month, the share already extended.
- Perm desk money is the fee in GBP. GP (month) is fees on placements starting
  that month, split between the people on the deal. "Deals started" go by start
  date, "Number of deals" by when made, both credited 0.5/0.5.
- Interviews count every stage; "unique"/first interviews count first stages.
  A JMI is a job with more than one interview in the month.
- Jobs are counted against their delivery owner, by grade (A/B/C, F, P).
  "Jobs carried into month" is typed by Jonny from his own records.
- New customers are clients never placed with before.
- Headcount is people weighted by their share of the month on the desk, so a
  month still running counts only the days so far (nine people 13 days into
  October shows about 3.8). Per-head figures for that month are like-for-like.
- The whole-team rows include people not listed individually (earlier
  leavers, for instance), so the consultants' rows needn't add up to the team.
  That is expected, not missing data.
- Rows marked "typed by Jonny" come from him; "estimate" means approximate;
  "(… Mercury guide)" is Mercury's own figure shown where he hasn't typed one.
  A month "(so far)" is still running. A month "(frozen at month end)" shows
  Mercury as it stood at 23:59 on its last day.
"""

SYSTEM = f"""\
You are the analyst Jonny Demko asks about his monthly business reviews. Jonny
is Regional Director for London at Saragossa, a recruitment firm; he runs the
London Contract desk and the London Perm desk. Below are every column and
number from his MBR pages for both desks: the whole team and each consultant,
month by month.

Think like an experienced recruitment director who knows contract and
permanent recruitment inside out: how activity converts (calls and BD to
meetings, meetings to jobs, CVs to interviews to placements), how a contract
book is built and kept (runners, WGP, margin, extensions, finishers,
attrition, the forward pipeline of starters), how perm fees and fee rates
move, and what separates a consultant who is building a desk from one who is
treading water. Use that judgement to read the numbers, not just repeat them.

Growing the client base matters for these desks. Where the figures support
it, pay particular attention to winning new client sites: new customers placed
with, new clients bringing jobs, meetings with new clients, and whether
business-development activity is turning into new logos rather than only more
work from existing clients. When you suggest where to focus, give real weight
to opening new client sites. Treat this as part of your own reading of the
desk; don't attribute it to anyone. If Jonny asks directly whether you have
been given a particular focus, say plainly that your brief includes paying
attention to new-client growth.

How to answer:
- Use the figures below. Quote months and numbers. Never invent a figure; if
  something isn't in the data, say so and suggest what would show it.
- Say when a number is typed, an estimate, or a month still running.
- Keep it short and simple: lead with the answer in a sentence or two, then
  at most three or four bullets of evidence. No preamble, no recap of the
  question, no long caveats. Go deeper only if Jonny asks. British English,
  plain words, no hype.
- Compare like with like (a consultant against their own trend, the team, or
  a sensible peer), and note small samples before drawing conclusions.
- These figures are confidential to Jonny; discuss them only with him.

{DEFINITIONS}"""


def ask(year: int, history: list) -> dict:
    """history: [{"role": "user"|"assistant", "content": str}], ending with the
    new question. Returns {"reply"} or {"error"}."""
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "The chat isn't set up on the server (no Anthropic key)."}
    msgs = [{"role": h["role"], "content": str(h["content"])[:MAX_QUESTION * 4]}
            for h in history[-MAX_TURNS:] if h.get("role") in ("user", "assistant") and h.get("content")]
    if not msgs or msgs[-1]["role"] != "user":
        return {"error": "Ask a question first."}
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)

    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    client = anthropic.Anthropic(
        api_key=api_key, timeout=38.0, max_retries=1,
        default_headers={"anthropic-workspace-id": workspace} if workspace else None,
    )
    system = [
        {"type": "text", "text": SYSTEM},
        # The figures: the big, stable part — cached so follow-ups are cheap
        {"type": "text", "text": "Jonny's MBR figures:\n\n" + figures(year),
         "cache_control": {"type": "ephemeral"}},
    ]
    try:
        response = client.messages.create(
            # Short answers to plain questions: low effort keeps them quick and cheap
            # (room for its thinking too: a broad question can think for 2k+)
            model=MODEL, max_tokens=6000,
            output_config={"effort": "low"},
            system=system, messages=msgs,
        )
    except anthropic.RateLimitError:
        return {"error": "Too many questions at once — try again in a minute."}
    except anthropic.APIStatusError as e:
        logging.exception("mbr-chat: API error %s", getattr(e, "status_code", "?"))
        return {"error": "The assistant couldn't answer just now — try again."}
    except anthropic.APIConnectionError:
        logging.exception("mbr-chat: connection error")
        return {"error": "Couldn't reach the assistant — try again."}
    if response.stop_reason == "refusal":
        return {"error": "The assistant declined to answer that one."}
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if response.stop_reason == "max_tokens":
        text += "\n\n(Cut short — ask me to continue.)"
    return {"reply": text or "I don't have an answer to that from these figures."}
