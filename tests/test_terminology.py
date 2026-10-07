"""
WGP (weekly gross profit), never WNF / weekly net fee, in anything people see
(Jason, Oct 2026).

Internal names stay lowercase `wnf` on purpose: other apps and long-open
OneUp screens read those fields, so only what is displayed changed. That makes
the uppercase term a clean signal of a visible leak.
"""
import glob
import io
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
VISIBLE = sorted(glob.glob(os.path.join(ROOT, "public", "*.html"))
                 + glob.glob(os.path.join(ROOT, "public", "*.js")))
OLD = re.compile(r"\bWNFI?\b|weekly net fee|net fee income", re.I)


def visible_mentions(text):
    """Old-term hits, ignoring lowercase internal identifiers like r.wnf."""
    return [m.group(0) for m in OLD.finditer(text) if not m.group(0).islower()]


@pytest.mark.parametrize("path", VISIBLE, ids=os.path.basename)
def test_no_page_says_wnf(path):
    assert visible_mentions(io.open(path, encoding="utf-8").read()) == []


def test_the_contract_1_1_labels_say_wgp():
    src = io.open(os.path.join(ROOT, "api", "shared", "oneonone_contract.py"), encoding="utf-8").read()
    assert '"label": "WGP added"' in src
    assert '"label": "WNFI added"' not in src


def test_internal_field_names_are_kept_for_readers_still_running_old_pages():
    """A OneUp screen left open reads r.wnf; renaming it would show $0."""
    assert "r.wnf" in io.open(os.path.join(ROOT, "public", "contract-screen.js"), encoding="utf-8").read()
