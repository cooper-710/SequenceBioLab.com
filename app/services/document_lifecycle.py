"""Reliable lifecycle primitives for report documents.

The database remains the metadata source of truth, but a report's durable
Storage object must be removed before its metadata is deleted. This module is
deliberately report-only: workouts and generic player documents require their
own explicit retention policy and are never eligible through this API.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Protocol

from supabase_storage import delete_file as delete_storage_file


log = logging.getLogger(__name__)

REPORT_CATEGORY = "report"


class DocumentDatabase(Protocol):
    """Database operations required by the lifecycle primitive."""

    def get_player_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        ...

    def delete_player_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        ...


class DocumentLifecycleError(RuntimeError):
    """Base error for a report lifecycle operation."""


class NonReportDocumentError(DocumentLifecycleError):
    """Raised when report-only deletion is attempted for another category."""

    def __init__(self, doc_id: int, category: Optional[str]):
        self.doc_id = int(doc_id)
        self.category = category
        super().__init__(
            f"Document {self.doc_id} is not a report (category={category!r})"
        )


class DocumentMetadataDeleteError(DocumentLifecycleError):
    """Raised when Storage succeeded but the database row could not be removed."""

    def __init__(self, doc_id: int):
        self.doc_id = int(doc_id)
        super().__init__(
            f"Storage cleanup completed for document {self.doc_id}, "
            "but its metadata row was not deleted"
        )


@dataclass(frozen=True)
class ReportDeletionResult:
    """Outcome of a completed report deletion."""

    document: Mapping[str, Any]
    storage_object_existed: Optional[bool]
    local_file_deleted: bool


StorageDelete = Callable[[str], bool]


def is_report_document(document: Mapping[str, Any]) -> bool:
    """Return whether a document is explicitly categorized as a report."""
    return (document.get("category") or "").strip().lower() == REPORT_CATEGORY


def delete_report_document(
    db: DocumentDatabase,
    doc_id: int,
    *,
    storage_delete: Optional[StorageDelete] = None,
    remove_local_file: bool = True,
) -> Optional[ReportDeletionResult]:
    """Delete one report with Storage-first ordering.

    The operation is idempotent when the metadata row or Storage object is
    already missing. Storage errors deliberately surface and prevent the
    database deletion. Workouts and every non-report category are rejected.

    Local files are ephemeral cache copies. Their cleanup happens only after
    Storage and metadata deletion and is best-effort.
    """
    document = db.get_player_document(int(doc_id))
    if document is None:
        return None

    if not is_report_document(document):
        category = (document.get("category") or "").strip().lower() or None
        raise NonReportDocumentError(int(doc_id), category)

    storage_path = (document.get("storage_path") or "").strip()
    storage_object_existed: Optional[bool] = None
    if storage_path:
        storage_delete = storage_delete or delete_storage_file
        # This call must finish successfully before metadata is removed. It may
        # return False when the object was already absent, which is still safe.
        storage_object_existed = storage_delete(storage_path)

    deleted_document = db.delete_player_document(int(doc_id))
    if deleted_document is None:
        # A concurrent delete is possible. Surface the inconsistent state so a
        # caller can reconcile rather than falsely reporting full success.
        raise DocumentMetadataDeleteError(int(doc_id))

    local_file_deleted = False
    local_path_raw = (deleted_document.get("path") or "").strip()
    if remove_local_file and local_path_raw:
        local_path = Path(local_path_raw)
        if local_path.exists() and local_path.is_file():
            try:
                local_path.unlink()
                local_file_deleted = True
            except OSError as exc:
                log.warning(
                    "Unable to remove local cache for report document %s at %s: %s",
                    doc_id,
                    local_path,
                    exc,
                )

    return ReportDeletionResult(
        document=dict(deleted_document),
        storage_object_existed=storage_object_existed,
        local_file_deleted=local_file_deleted,
    )
