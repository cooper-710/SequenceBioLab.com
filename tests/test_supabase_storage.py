import sys
from pathlib import Path

import pytest
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import supabase_storage as storage  # noqa: E402


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code = status_code
        self.content = content
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


def queued_request(*outcomes):
    remaining = list(outcomes)
    calls = []

    def request_func(**kwargs):
        calls.append(kwargs)
        outcome = remaining.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    request_func.calls = calls
    return request_func


@pytest.fixture(autouse=True)
def storage_environment(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-service-key")


def test_delete_success_returns_true(monkeypatch):
    request_func = queued_request(FakeResponse(200))
    monkeypatch.setattr(storage.requests, "delete", request_func)

    assert storage.delete_file("42.pdf") is True
    assert len(request_func.calls) == 1
    assert request_func.calls[0]["json"] == {"prefixes": ["42.pdf"]}


def test_current_secret_key_uses_apikey_header_only(monkeypatch):
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_current")
    request_func = queued_request(FakeResponse(200))
    monkeypatch.setattr(storage.requests, "delete", request_func)

    assert storage.delete_file("42.pdf") is True
    headers = request_func.calls[0]["headers"]
    assert headers["apikey"] == "sb_secret_current"
    assert "Authorization" not in headers


def test_legacy_service_key_keeps_bearer_header(monkeypatch):
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "legacy-service-jwt")
    request_func = queued_request(FakeResponse(200))
    monkeypatch.setattr(storage.requests, "delete", request_func)

    assert storage.delete_file("42.pdf") is True
    headers = request_func.calls[0]["headers"]
    assert headers["apikey"] == "legacy-service-jwt"
    assert headers["Authorization"] == "Bearer legacy-service-jwt"


def test_delete_missing_object_is_idempotent_success(monkeypatch):
    request_func = queued_request(FakeResponse(404))
    sleeps = []
    monkeypatch.setattr(storage.requests, "delete", request_func)
    monkeypatch.setattr(storage.time, "sleep", sleeps.append)

    assert storage.delete_file("missing.pdf") is False
    assert len(request_func.calls) == 1
    assert sleeps == []


def test_delete_retries_transient_status_with_bounded_backoff(monkeypatch):
    first = FakeResponse(503)
    second = FakeResponse(429)
    request_func = queued_request(first, second, FakeResponse(200))
    sleeps = []
    monkeypatch.setattr(storage.requests, "delete", request_func)
    monkeypatch.setattr(storage.time, "sleep", sleeps.append)

    assert storage.delete_file("42.pdf") is True
    assert len(request_func.calls) == 3
    assert sleeps == [0.25, 0.5]
    assert first.closed is True
    assert second.closed is True


def test_delete_surfaces_permanent_error_without_retry(monkeypatch):
    request_func = queued_request(FakeResponse(403))
    sleeps = []
    monkeypatch.setattr(storage.requests, "delete", request_func)
    monkeypatch.setattr(storage.time, "sleep", sleeps.append)

    with pytest.raises(requests.HTTPError) as exc_info:
        storage.delete_file("42.pdf")

    assert exc_info.value.response.status_code == 403
    assert len(request_func.calls) == 1
    assert sleeps == []


def test_delete_surfaces_exhausted_transient_error(monkeypatch):
    request_func = queued_request(
        FakeResponse(503),
        FakeResponse(503),
        FakeResponse(503),
    )
    sleeps = []
    monkeypatch.setattr(storage.requests, "delete", request_func)
    monkeypatch.setattr(storage.time, "sleep", sleeps.append)

    with pytest.raises(requests.HTTPError) as exc_info:
        storage.delete_file("42.pdf")

    assert exc_info.value.response.status_code == 503
    assert len(request_func.calls) == 3
    assert sleeps == [0.25, 0.5]


def test_connection_error_is_retried_but_invalid_url_is_not(monkeypatch):
    transient = queued_request(
        requests.ConnectionError("temporary"),
        FakeResponse(200),
    )
    sleeps = []
    monkeypatch.setattr(storage.requests, "delete", transient)
    monkeypatch.setattr(storage.time, "sleep", sleeps.append)

    assert storage.delete_file("42.pdf") is True
    assert len(transient.calls) == 2
    assert sleeps == [0.25]

    permanent = queued_request(requests.exceptions.InvalidURL("invalid"))
    monkeypatch.setattr(storage.requests, "delete", permanent)
    with pytest.raises(requests.exceptions.InvalidURL):
        storage.delete_file("42.pdf")
    assert len(permanent.calls) == 1


def test_upload_retries_transient_status(monkeypatch):
    request_func = queued_request(FakeResponse(500), FakeResponse(200))
    monkeypatch.setattr(storage.requests, "post", request_func)
    monkeypatch.setattr(storage.time, "sleep", lambda _delay: None)

    assert storage.upload_file(42, b"%PDF", "application/pdf") == "42.pdf"
    assert len(request_func.calls) == 2


def test_download_surfaces_non_transient_error(monkeypatch):
    request_func = queued_request(FakeResponse(401))
    monkeypatch.setattr(storage.requests, "get", request_func)

    with pytest.raises(requests.HTTPError):
        storage.download_file("42.pdf")
    assert len(request_func.calls) == 1


def test_empty_storage_path_is_rejected_before_request(monkeypatch):
    request_func = queued_request(FakeResponse(200))
    monkeypatch.setattr(storage.requests, "delete", request_func)

    with pytest.raises(ValueError):
        storage.delete_file("   ")
    assert request_func.calls == []


def test_missing_configuration_surfaces(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")
    request_func = queued_request(FakeResponse(200))
    monkeypatch.setattr(storage.requests, "delete", request_func)

    with pytest.raises(RuntimeError):
        storage.delete_file("42.pdf")
    assert request_func.calls == []
