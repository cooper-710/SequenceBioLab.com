"""
Supabase Storage helper for player documents.

Uses the Supabase Storage REST API directly via requests (already a dependency),
avoiding any reliance on the supabase-py client package.
"""
import os
import logging
import requests

log = logging.getLogger(__name__)

BUCKET = "player-documents"


def _get_config():
    """Return (supabase_url, service_key) from environment variables."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables must be set"
        )
    return url, key


def upload_file(doc_id: int, data: bytes, content_type: str = "application/pdf") -> str:
    """Upload file bytes to Supabase Storage via REST API.

    Uses upsert so re-uploading the same doc_id overwrites the existing file.
    Returns the storage path (e.g. '42.pdf') to be saved in player_documents.storage_path.
    """
    url, key = _get_config()
    path = f"{doc_id}.pdf"
    endpoint = f"{url}/storage/v1/object/{BUCKET}/{path}"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    resp = requests.post(endpoint, headers=headers, data=data, timeout=60)
    resp.raise_for_status()
    log.info(f"[storage] Uploaded doc_id={doc_id} → {BUCKET}/{path} ({len(data)} bytes)")
    return path


def download_file(storage_path: str) -> bytes:
    """Download and return raw file bytes from Supabase Storage via REST API."""
    url, key = _get_config()
    endpoint = f"{url}/storage/v1/object/{BUCKET}/{storage_path}"
    headers = {"Authorization": f"Bearer {key}"}
    resp = requests.get(endpoint, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.content


def delete_file(storage_path: str) -> None:
    """Delete a file from Supabase Storage via REST API. Best-effort — never raises."""
    try:
        url, key = _get_config()
        endpoint = f"{url}/storage/v1/object/{BUCKET}"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        resp = requests.delete(endpoint, headers=headers, json={"prefixes": [storage_path]}, timeout=30)
        resp.raise_for_status()
        log.info(f"[storage] Deleted {BUCKET}/{storage_path}")
    except Exception as exc:
        log.warning(f"[storage] Failed to delete {storage_path}: {exc}")
