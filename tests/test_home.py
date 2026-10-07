"""
The home page and shared menu (Jason, Oct 2026): a card per section, pills per
team, and only what this person can actually open.
"""
import io
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

import function_app as F  # noqa: E402

PUBLIC = os.path.join(os.path.dirname(__file__), "..", "public")
TERR = {"lc": "London Contract", "cc": "Chicago Contract", "lp": "London"}


def person(uid, terr=None):
    return {"systemuserid": uid, "fullname": uid.title(), "_territoryid_value": terr}


@pytest.fixture
def access(monkeypatch):
    """Set what each section's own access check returns for the caller."""
    def configure(templates=(), mbr=(), admin=False):
        monkeypatch.setattr("shared.oto_templates.templates_for",
                            lambda email, is_admin: [{"id": t, "name": t.title()} for t in templates])
        monkeypatch.setattr(F, "_mbr_visible_people", lambda email: (list(mbr), False))
        monkeypatch.setattr("shared.dataverse.is_admin", lambda email: admin)
        monkeypatch.setattr("shared.dataverse.get_territory_name", lambda tid: TERR.get(tid, "Unknown"))
    return configure


def keys(sections):
    return [s["key"] for s in sections]


def test_a_consultant_sees_the_report_and_their_own_desk(access):
    access(mbr=[person("louis", "lc")])
    s = F._home_sections("louis@saragossa.io")
    assert keys(s) == ["report", "mbr"]
    assert s[1]["pills"] == [{"label": "London Contract", "href": "/mbr?desk=London%20Contract"}]


def test_121_pills_are_the_teams_this_person_can_open(access):
    access(templates=["contract_usa"], mbr=[person("connor", "cc")])
    s = F._home_sections("connor@saragossa.io")
    assert s[1] == {**s[1], "key": "121",
                    "pills": [{"label": "Contract_Usa", "href": "/121?template=contract_usa"}]}


def test_the_perm_desks_are_named_as_perm(access):
    access(mbr=[person("harry", "lp"), person("clara", "lp")])
    assert F._home_sections("harry@saragossa.io")[1]["pills"][0]["label"] == "London Perm"


def test_someone_on_no_desk_gets_no_empty_mbr(access):
    """Finance and ops can always open their own MBR — but there is nothing
    in it, so the section isn't offered."""
    access(mbr=[person("becky", None)], admin=True)
    assert keys(F._home_sections("becky@saragossa.io")) == ["report", "admin"]


def test_performance_stats_only_for_its_allowlist(access):
    access(mbr=[person("jim", "cc")])
    assert "perf" in keys(F._home_sections("jim@saragossa.io"))
    assert "perf" not in keys(F._home_sections("connor@saragossa.io"))


def test_admin_section_only_for_admins(access):
    access(mbr=[person("connor", "cc")], admin=False)
    assert "admin" not in keys(F._home_sections("connor@saragossa.io"))


def test_a_failing_access_check_hides_that_section_not_the_page(access, monkeypatch):
    access(mbr=[person("louis", "lc")])
    def boom(email, is_admin):
        raise RuntimeError("Dataverse down")
    monkeypatch.setattr("shared.oto_templates.templates_for", boom)
    assert keys(F._home_sections("louis@saragossa.io")) == ["report", "mbr"]


def test_every_section_has_a_description():
    for key, (title, desc) in F.HOME_SECTIONS.items():
        assert title and len(desc) > 30, key


def test_descriptions_use_wgp_not_wnf():
    text = " ".join(d for _, d in F.HOME_SECTIONS.values())
    assert "WNF" not in text and "net fee" not in text.lower()


# ── The pages ─────────────────────────────────────────────────────────────────

PAGES = {"report.html": "report", "121.html": "121", "mbr.html": "mbr",
         "performance.html": "perf", "admin.html": "admin", "settings.html": "settings"}


def read(name):
    return io.open(os.path.join(PUBLIC, name), encoding="utf-8").read()


@pytest.mark.parametrize("page,active", PAGES.items())
def test_every_page_uses_the_shared_menu(page, active):
    html = read(page)
    assert f'id="main-menu" data-active="{active}"' in html
    assert '<script src="/nav.js"></script>' in html
    # nav.js must load before the page's own script
    assert html.index("/nav.js") < max(html.index(f"/{js}") for js in re.findall(
        r'<script src="/([a-z0-9-]+\.js)"', html) if js not in ("nav.js", "theme.js"))


@pytest.mark.parametrize("page", list(PAGES) + ["index.html"])
def test_no_page_hard_codes_a_link_to_analytics(page):
    """The menu once showed Analytics to anyone signed in."""
    html = read(page)
    assert 'href="/admin" class="menu-link' not in html
    assert 'id="admin-link"' not in html


def test_home_is_at_the_root_and_the_report_moved():
    assert 'src="/home.js"' in read("index.html")
    assert 'src="/app.js"' in read("report.html")


def test_report_only_people_skip_the_home_page():
    js = read("home.js")
    assert 'sections.length === 1 && sections[0].key === "report"' in js
    assert 'window.location.replace("/report")' in js


def test_pills_open_a_team_or_desk_directly():
    assert 'new URLSearchParams(window.location.search).get("template")' in read("121.js")
    assert 'new URLSearchParams(window.location.search).get("desk")' in read("mbr.js")


def test_home_never_puts_mercury_names_into_html():
    js = read("home.js")
    assert "innerHTML" not in js.split("function card")[1]


# ── No menu inside the pages (Jason, Oct 2026) ────────────────────────────────
# The home page is the menu. Inside a section the header only offers a way back.

def test_inside_a_page_the_header_only_links_home():
    js = read("nav.js")
    assert '"← Home"' in js
    for target in ('"/admin"', '"/settings"', '"/report"', '"/121"', '"/mbr"', '"/performance"'):
        assert target not in js, target


def test_the_home_page_itself_shows_no_back_link():
    js = read("nav.js")
    assert 'if (host.dataset.active === "home") return;' in js
    assert 'data-active="home"' in read("index.html")


@pytest.mark.parametrize("page", PAGES)
def test_the_logo_still_goes_home(page):
    assert '<a href="/" class="logo-link"><img src="/logo.svg"' in read(page) \
        or '<a href="/"><img src="/logo.svg"' in read(page)
