"""Ask the MBR: Jonny only, his figures as text, and the call to Claude."""
import json
from types import SimpleNamespace

import pytest

import function_app as F
from shared import mbr_chat as C


class Req:
    def __init__(self, body=None):
        self._body = body

    def get_json(self):
        return self._body


@pytest.fixture
def call(monkeypatch):
    def go(email, body):
        monkeypatch.setattr(F, "require_auth", lambda req: (email, None))
        resp = F.mbr_chat(Req(body))
        return resp.status_code, json.loads(resp.get_body())
    return go


def test_only_jonny_has_the_chat():
    assert C.can_chat("jonny@saragossa.io") and C.can_chat("Jonny@Saragossa.io")
    assert not C.can_chat("jason@saragossa.io") and not C.can_chat("")


def test_anyone_else_is_turned_away(monkeypatch, call):
    monkeypatch.setattr(C, "ask", lambda *a: pytest.fail("must not ask Claude"))
    status, out = call("louis@saragossa.io", {"messages": [{"role": "user", "content": "hi"}]})
    assert status == 403 and out["error"] == "forbidden"


def test_opening_the_panel_builds_the_figures(monkeypatch, call):
    built = []
    monkeypatch.setattr(C, "figures", lambda year: built.append(year) or "")
    monkeypatch.setattr(C, "ask", lambda *a: pytest.fail("warming must not ask Claude"))
    status, out = call("jonny@saragossa.io", {"year": 2026, "warm": True})
    assert status == 200 and out["ok"] and built == [2026]


def test_a_question_is_answered(monkeypatch, call):
    monkeypatch.setattr(C, "ask", lambda year, history: {"reply": f"{year}:{history[-1]['content']}"})
    status, out = call("jonny@saragossa.io",
                       {"year": 2026, "messages": [{"role": "user", "content": "How was May?"}, "junk"]})
    assert status == 200 and out["reply"] == "2026:How was May?"


def test_an_overlong_question_is_refused(monkeypatch, call):
    monkeypatch.setattr(C, "ask", lambda *a: pytest.fail("must not ask Claude"))
    status, _ = call("jonny@saragossa.io",
                     {"messages": [{"role": "user", "content": "x" * (C.MAX_QUESTION + 1)}]})
    assert status == 400


def test_a_view_reads_as_a_table():
    view = {"columns": ["P1", "P2", "Q1", "YTD"], "partial": "P2", "frozen": {"P1": {}},
            "measures": [{"key": "gp", "label": "GP", "unit": "money", "section": "Targets", "input": True},
                         {"key": "runners", "label": "Runners", "unit": "count", "section": "Book"}],
            "values": {"P1": {"gp": 12000, "runners": 4}, "P2": {"runners": 4.5}, "YTD": {"gp": 12000}},
            "estimates": {"gp|P2": 9000}}
    text = C._table(view)
    assert "| Measure | Jan (frozen at month end) | Feb (so far) | Year to date |" in text
    assert "| GP [typed by Jonny] | £12,000 | (£9,000 Mercury guide) | £12,000 |" in text
    assert "| Runners | 4 | 4.50 | - |" in text
    assert "Q1" not in text                                     # quarters left out


def test_ask_sends_the_figures_cached_and_returns_the_text(monkeypatch):
    sent = {}

    class Messages:
        def create(self, **kw):
            sent.update(kw)
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text="May was strong.")])

    class Client:
        def __init__(self, **kw):
            self.messages = Messages()

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", Client)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(C, "figures", lambda year: "FIGURES")
    out = C.ask(2026, [{"role": "assistant", "content": "stray"},
                       {"role": "user", "content": "How was May?"}])
    assert out == {"reply": "May was strong."}
    assert sent["model"] == C.MODEL
    assert sent["messages"] == [{"role": "user", "content": "How was May?"}]   # starts with the user
    assert "FIGURES" in sent["system"][1]["text"] and sent["system"][1]["cache_control"]


def test_ask_needs_a_question(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    assert "error" in C.ask(2026, [{"role": "assistant", "content": "hello"}])
