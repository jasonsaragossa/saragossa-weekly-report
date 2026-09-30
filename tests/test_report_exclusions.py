"""
Jim Jeffers and Jonny Demko run desks rather than bill against them, so they
appear nowhere a consultant's figures are shown (Jason, Sep 2026).

The exclusion once reached only the Analytics list and not the weekly report's,
so both fetches are tested here.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")

from shared import dataverse as D  # noqa: E402

PEOPLE = [
    {"systemuserid": "jim", "fullname": "Jim Jeffers", "internalemailaddress": "jim@saragossa.io"},
    {"systemuserid": "jonny", "fullname": "Jonny Demko", "internalemailaddress": "Jonny@Saragossa.io"},
    {"systemuserid": "junaid", "fullname": "Junaid Shabir", "internalemailaddress": "junaid@saragossa.io"},
    {"systemuserid": "connor", "fullname": "Connor Newhouse", "internalemailaddress": "connor@saragossa.io"},
]


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setattr(D, "odata_get_all", lambda path, params=None: [dict(p) for p in PEOPLE])
    monkeypatch.setattr(D, "_UNASSIGNED_HOUSE_USERS", {})


def names(users):
    return sorted(u["fullname"] for u in users)


@pytest.mark.parametrize("fetch", ["get_active_consultants", "get_all_territory_consultants"])
def test_neither_appears_in_any_consultant_list(fetch):
    got = names(getattr(D, fetch)())
    assert "Jim Jeffers" not in got and "Jonny Demko" not in got


@pytest.mark.parametrize("fetch", ["get_active_consultants", "get_all_territory_consultants"])
def test_everyone_else_is_untouched(fetch):
    assert names(getattr(D, fetch)()) == ["Connor Newhouse", "Junaid Shabir"]


def test_the_weekly_report_fetch_asks_for_the_email_it_filters_on():
    """Without the email in $select the filter has nothing to compare, and
    silently keeps everyone — the original bug's quieter cousin."""
    asked = {}
    D.odata_get_all = lambda path, params=None: asked.update(params or {}) or []
    D.get_active_consultants()
    assert "internalemailaddress" in asked["$select"]


def test_matching_ignores_email_case():
    assert not D._on_report({"internalemailaddress": "JONNY@saragossa.io"})
    assert D._on_report({"internalemailaddress": None})
