"""Every test starts with disposable data and no external provider access."""
import os
import tempfile
from pathlib import Path

import pytest

_test_data = tempfile.TemporaryDirectory(prefix="medienwerk-tests-")
_root = Path(_test_data.name)
os.environ["MEDIENWERK_WORKSPACE"] = str(_root / "workspace")
os.environ["MEDIENWERK_DATABASE_URL"] = f"sqlite:///{_root / 'app.db'}"
os.environ["MEDIENWERK_CONFIG_FILE"] = str(_root / "config.json")
os.environ["MEDIENWERK_CAMPAIGNS_FILE"] = str(_root / "campaigns.json")
os.environ["MEDIENWERK_DISABLE_SCHEDULER"] = "1"


@pytest.fixture(autouse=True)
def block_external_requests(monkeypatch):
    """Tests must opt into a fake provider; production requests fail immediately."""
    import requests
    import urllib.request
    import httpx

    def blocked(*args, **kwargs):
        raise AssertionError("External network access is disabled in local tests")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    # The modern Google SDK uses HTTPX. Block its real network transports;
    # explicit MockTransport fixtures remain usable for SDK serialization tests.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)


def pytest_sessionfinish(session, exitstatus):
    _test_data.cleanup()
