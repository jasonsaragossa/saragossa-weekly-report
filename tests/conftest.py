"""Shared test setup."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
os.environ.setdefault("DATAVERSE_URL", "https://example.invalid")
for _k in ("DATAVERSE_TENANT_ID", "DATAVERSE_CLIENT_ID", "DATAVERSE_CLIENT_SECRET"):
    os.environ.setdefault(_k, "test")


@pytest.fixture(autouse=True)
def _fresh_staff_lists():
    """The app keeps staff lists for five minutes; each test starts empty so
    one test's fake Mercury never answers another's."""
    from shared.dataverse import clear_ttl_cache
    clear_ttl_cache()
    yield
    clear_ttl_cache()
