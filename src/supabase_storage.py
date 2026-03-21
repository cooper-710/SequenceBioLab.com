"""
Supabase Storage helper for player documents.

Replaces the player_document_blobs DB table approach with Supabase object
storage, keeping the 500 MB Postgres DB well under the free-plan limit.
"""
import os
import logging

log = logging.getLogger(__name__)

BUCKET = "player-documents"


def _get_client():
    """Return an authenticated Supabase client from environment variables."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables must be set"
        )
    from supabase import create_client
    return create_client(url, key)


def upload_file(doc_id: int, data: bytes, content_type: str = "application/pdf") -> str:
    """Upload file bytes to Supabase Storage.

    Uses upsert so re-uploading the same doc_id overwrites the existing file.
    Returns the storage path (e.g. '42.pdf') which should be saved to
    player_documents.storage_path.
    """
    client = _get_client()
    path = f"{doc_id}.pdf"
    client.storage.from_(BUCKET).upload(
        path,
        data,
        {"content-type": content_type, "upsert": "true"},
    )
    log.info(f"[storage] Uploaded doc_id={doc_id} → {BUCKET}/{path} ({len(data)} bytes)")
    return path


def download_file(storage_path: str) -> bytes:
    """Download and return raw file bytes from Supabase Storage."""
    client = _get_client()
    data = client.storage.from_(BUCKET).download(storage_path)
    return data


def delete_file(storage_path: str) -> None:
    """Delete a file from Supabase Storage. Best-effort — never raises."""
    try:
        client = _get_client()
        client.storage.from_(BUCKET).remove([storage_path])
        log.info(f"[storage] Deleted {BUCKET}/{storage_path}")
    except Exception as exc:
        log.warning(f"[storage] Failed to delete {storage_path}: {exc}")
