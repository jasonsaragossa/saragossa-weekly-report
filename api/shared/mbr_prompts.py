"""
MBR prompt engine.

Picks the five or six metrics worth talking about, then asks Claude to turn each
into a probing question using the registry's prompt_context. The model proposes;
the consultant chooses and justifies. It never writes the answer.

Falls back to template questions when ANTHROPIC_API_KEY is unset, so the form
still works before the key is added.
"""
import json
import logging
import os

# Opus 5 by default. Cost is trivial at this volume (~65 MBRs/month) and these
# questions are read by consultants, so quality is worth more than the saving.
# Override with MBR_PROMPT_MODEL / MBR_PROMPT_EFFORT if that changes.
MODEL  = os.environ.get("MBR_PROMPT_MODEL", "claude-opus-5")
EFFORT = os.environ.get("MBR_PROMPT_EFFORT", "medium")
MAX_FLAGS = 6
# Ignore noise: a metric must move by at least this much to be flagged
MIN_MOVE_PCT = 15.0


def pick_flagged(metrics: list, targets: dict) -> list:
    """
    The five or six worth discussing. Ranked by how far off they are, so the
    meeting covers the biggest movements rather than every metric.
    """
    scored = []
    for m in metrics:
        if m["value"] is None:
            continue
        score, reason, shape = 0.0, None, None

        chg = m.get("change_pct")
        if chg is not None and abs(chg) >= MIN_MOVE_PCT:
            good = (chg > 0) if m["direction"] == "up" else (chg < 0)
            score = abs(chg)
            reason = f"{'up' if chg > 0 else 'down'} {abs(chg):.0f}% on last month"
            shape = "repeatable" if good else "recover"

        tkey = m.get("target_key")
        target = (targets or {}).get(tkey) if tkey else None
        if target:
            pct = m["value"] / target * 100 if target else None
            if pct is not None and pct < 80:
                miss = 100 - pct
                if miss > score:
                    score, reason, shape = miss, f"{pct:.0f}% of target", "recover"
            elif pct is not None and pct >= 120 and score < 20:
                score, reason, shape = pct - 100, f"{pct:.0f}% of target", "repeatable"

        if reason:
            scored.append({**m, "flag_reason": reason, "shape": shape, "_score": score,
                           "target": target})
    scored.sort(key=lambda x: -x["_score"])
    return [{k: v for k, v in s.items() if k != "_score"} for s in scored[:MAX_FLAGS]]


def _fallback_question(m: dict) -> str:
    name = m["name"]
    if m["shape"] == "repeatable":
        return f"{name} is {m['flag_reason']}. What did you do differently, and how do you repeat it next month?"
    return f"{name} is {m['flag_reason']}. What's driving that, and what will you change?"


def generate_prompts(person_name: str, month_label: str, flagged: list) -> dict:
    """
    Returns {"prompts": [{key, question}], "summary": {...}, "source": "claude"|"template"}
    Never raises — a prompt failure must not block the MBR.
    """
    if not flagged:
        return {"prompts": [], "summary": None, "source": "none"}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"prompts": [{"key": m["key"], "question": _fallback_question(m),
                             "flag_reason": m["flag_reason"]} for m in flagged],
                "summary": None, "source": "template"}

    lines = []
    for m in flagged:
        lines.append(json.dumps({
            "key": m["key"], "metric": m["name"], "value": m["value"],
            "last_month": m["previous"], "movement": m["flag_reason"],
            "target": m.get("target"), "why_it_matters": m["prompt_context"],
        }))
    system = (
        "You write probing questions for a recruitment monthly business review. "
        "You are preparing a consultant to explain their own numbers to their manager.\n"
        "Rules:\n"
        "- Ask a question. Never state the answer or diagnose the cause.\n"
        "- One question per metric, at most 25 words.\n"
        "- Use the supplied context about what moves each metric so the question is specific "
        "to recruitment, not generic management-speak.\n"
        "- If a metric moved favourably, ask what is repeatable. If unfavourably, ask what changes.\n"
        "- Plain British English. No preamble, no encouragement, no exclamation marks."
    )
    user = (
        f"Consultant: {person_name}. Month: {month_label}.\n"
        f"Flagged metrics, one JSON object per line:\n" + "\n".join(lines) + "\n\n"
        "Return ONLY a JSON object of the form:\n"
        '{"prompts":[{"key":"<metric key>","question":"..."}],'
        '"summary":{"good":["...","...","..."],"improve":["...","...","..."]}}\n'
        "The summary lists three candidate positives and three candidate areas to impact, "
        "drawn only from the data given. These are candidates the consultant will choose from."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=40.0)
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            output_config={"effort": EFFORT},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("prompt generation refused")
        text = "".join(b.text for b in response.content if b.type == "text")
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start:end + 1])
        by_key = {p["key"]: p.get("question", "") for p in data.get("prompts", [])}
        return {
            "prompts": [{"key": m["key"],
                         "question": by_key.get(m["key"]) or _fallback_question(m),
                         "flag_reason": m["flag_reason"]} for m in flagged],
            "summary": data.get("summary"),
            "source": "claude",
        }
    except Exception:
        logging.warning("MBR prompt generation failed — using templates", exc_info=True)
        return {"prompts": [{"key": m["key"], "question": _fallback_question(m),
                             "flag_reason": m["flag_reason"]} for m in flagged],
                "summary": None, "source": "template"}
