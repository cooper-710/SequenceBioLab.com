"""
Supabase Storage helper for player documents.

Uses the Supabase Storage REST API directly via requests (already a dependency),
avoiding any reliance on the supabase-py client package.
"""
import os
import logging
import time
from typing import Callable, FrozenSet, Optional

import requests

log = logging.getLogger(__name__)

BUCKET = "player-documents"

_MAX_ATTEMPTS = 3
_INITIAL_RETRY_DELAY_SECONDS = 0.25
_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
_RETRYABLE_EXCEPTIONS = (requests.Timeout, requests.ConnectionError)


def _get_config():
    """Return the project URL and a server-only API key.

    ``SUPABASE_SECRET_KEY`` is the current key format. Keep accepting the
    legacy ``SUPABASE_SERVICE_KEY`` name so existing deployments can rotate
    without an outage.
    """
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = (
        os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    )
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and a SUPABASE_SECRET_KEY (or legacy "
            "SUPABASE_SERVICE_KEY) must be set"
        )
    return url, key


def _server_key_headers(key: str) -> dict:
    """Build headers compatible with current secret and legacy JWT keys."""
    headers = {"apikey": key}
    # Current sb_secret keys are not JWTs and must not be sent as Bearer
    # credentials. Legacy service-role JWTs still require Authorization.
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _request_with_retries(
    request_func: Callable[..., requests.Response],
    *,
    operation: str,
    storage_path: str,
    allowed_statuses: Optional[FrozenSet[int]] = None,
    **request_kwargs,
) -> requests.Response:
    """Run one Storage request with bounded transient-error retries.

    Authentication, validation, and other permanent failures surface immediately.
    Only connection/time-out failures and explicitly retryable HTTP statuses are
    retried, for at most ``_MAX_ATTEMPTS`` total attempts.
    """
    allowed_statuses = allowed_statuses or frozenset()

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = request_func(**request_kwargs)
        except _RETRYABLE_EXCEPTIONS as exc:
            if attempt >= _MAX_ATTEMPTS:
                raise
            delay = _INITIAL_RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
            log.warning(
                "[storage] Transient %s failure for %s (attempt %s/%s): %s",
                operation,
                storage_path,
                attempt,
                _MAX_ATTEMPTS,
                exc,
            )
            time.sleep(delay)
            continue

        if response.status_code in allowed_statuses:
            return response

        if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_ATTEMPTS:
            delay = _INITIAL_RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
            log.warning(
                "[storage] Transient %s response for %s (status=%s, attempt %s/%s)",
                operation,
                storage_path,
                response.status_code,
                attempt,
                _MAX_ATTEMPTS,
            )
            response.close()
            time.sleep(delay)
            continue

        # Raises for every non-success response, including an exhausted transient
        # response. Callers must decide how to persist/retry lifecycle work.
        response.raise_for_status()
        return response

    raise RuntimeError(f"Storage {operation} exhausted unexpectedly for {storage_path}")


def _validate_storage_path(storage_path: str) -> str:
    if not isinstance(storage_path, str) or not storage_path.strip():
        raise ValueError("storage_path must be a non-empty string")
    return storage_path


def upload_file(doc_id: int, data: bytes, content_type: str = "application/pdf") -> str:
    """Upload file bytes to Supabase Storage via REST API.

    Uses upsert so re-uploading the same doc_id overwrites the existing file.
    Returns the storage path (e.g. '42.pdf') to be saved in player_documents.storage_path.
    """
    url, key = _get_config()
    path = f"{doc_id}.pdf"
    endpoint = f"{url}/storage/v1/object/{BUCKET}/{path}"
    headers = {
        **_server_key_headers(key),
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    _request_with_retries(
        requests.post,
        operation="upload",
        storage_path=path,
        url=endpoint,
        headers=headers,
        data=data,
        timeout=60,
    )
    log.info(f"[storage] Uploaded doc_id={doc_id} → {BUCKET}/{path} ({len(data)} bytes)")
    return path


def download_file(storage_path: str) -> bytes:
    """Download and return raw file bytes from Supabase Storage via REST API."""
    storage_path = _validate_storage_path(storage_path)
    url, key = _get_config()
    endpoint = f"{url}/storage/v1/object/{BUCKET}/{storage_path}"
    headers = _server_key_headers(key)
    resp = _request_with_retries(
        requests.get,
        operation="download",
        storage_path=storage_path,
        url=endpoint,
        headers=headers,
        timeout=60,
    )
    return resp.content


def delete_file(storage_path: str) -> bool:
    """Delete one object, returning whether it existed.

    A missing object is an idempotent success and returns ``False``. Other
    permanent failures and exhausted transient failures raise so database
    metadata is not deleted before Storage cleanup has actually succeeded.
    """
    storage_path = _validate_storage_path(storage_path)
    url, key = _get_config()
    endpoint = f"{url}/storage/v1/object/{BUCKET}"
    headers = {
        **_server_key_headers(key),
        "Content-Type": "application/json",
    }
    resp = _request_with_retries(
        requests.delete,
        operation="delete",
        storage_path=storage_path,
        allowed_statuses=frozenset({404}),
        url=endpoint,
        headers=headers,
        json={"prefixes": [storage_path]},
        timeout=30,
    )
    if resp.status_code == 404:
        log.info(f"[storage] Already absent {BUCKET}/{storage_path}")
        return False

    log.info(f"[storage] Deleted {BUCKET}/{storage_path}")
    return True
