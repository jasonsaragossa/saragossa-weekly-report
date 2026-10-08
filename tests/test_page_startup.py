"""A page's start-up must not reach a variable before its declaration has run.

On 7 Oct 2026 the 1:1 page broke for everyone ("Cannot access 'currentTemplate'
before initialization"): its start-up called load() straight away, and load()
read a `let` declared further down the file. It had only ever worked because
start-up used to await a fetch first. This checks the code a start-up runs
before its first await, for every page.
"""
import pathlib
import re

PUBLIC = pathlib.Path(__file__).resolve().parent.parent / "public"


def _startup_problems(src: str) -> list:
    lines = src.splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(r"\(async \(\) => \{", l)), None)
    if start is None:
        return []
    # Top-level let/const declared after the start-up block begins
    late = {m.group(1): i for i, l in enumerate(lines)
            if i > start and (m := re.match(r"(?:let|const)\s+([A-Za-z_$][\w$]*)", l))}
    # The start-up block, up to its first await (what runs before the file finishes)
    body = []
    for l in lines[start + 1:]:
        if "await" in l or l.startswith("})"):
            break
        body.append(l)
    called = set(re.findall(r"\b([A-Za-z_$][\w$]*)\(\)", "\n".join(body)))
    # Functions it calls, by name, and what those read before their own first await
    reads = set(re.findall(r"\b[A-Za-z_$][\w$]*\b", "\n".join(body)))
    for name in called:
        m = re.search(rf"^(?:async\s+)?function {re.escape(name)}\([^)]*\)\s*\{{(.*?)^\}}", src, re.S | re.M)
        if m:
            reads |= set(re.findall(r"\b[A-Za-z_$][\w$]*\b", m.group(1).split("await")[0]))
    return sorted(n for n in late if n in reads)


def test_no_page_reads_a_variable_before_it_is_declared():
    problems = {p.name: _startup_problems(p.read_text(encoding="utf-8"))
                for p in PUBLIC.glob("*.js")}
    assert {k: v for k, v in problems.items() if v} == {}


def test_the_check_would_have_caught_the_1_1_page():
    broken = (
        "(async () => {\n  load();\n})();\n"
        "async function load() {\n  const q = currentTemplate;\n  await fetch(q);\n}\n"
        "let currentTemplate = '';\n"
    )
    assert _startup_problems(broken) == ["currentTemplate"]
