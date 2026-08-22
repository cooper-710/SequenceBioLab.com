import sys
from pathlib import Path

import pytest
import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from app.services.document_lifecycle import (  # noqa: E402
    DocumentMetadataDeleteError,
    NonReportDocumentError,
    delete_report_document,
)


class FakeDatabase:
    def __init__(self, document, events, *, delete_result="document"):
        self.document = dict(document) if document is not None else None
        self.events = events
        self.delete_result = delete_result

    def get_player_document(self, doc_id):
        self.events.append(("get", doc_id))
        return dict(self.document) if self.document is not None else None

    def delete_player_document(self, doc_id):
        self.events.append(("db_delete", doc_id))
        if self.delete_result is None:
            return None
        return dict(self.document)


def report_document(tmp_path, **overrides):
    document = {
        "id": 42,
        "player_id": 7,
        "filename": "report.pdf",
        "path": str(tmp_path / "report.pdf"),
        "category": "report",
        "storage_path": "42.pdf",
    }
    document.update(overrides)
    return document


def test_report_deletion_is_storage_first(tmp_path):
    local_path = tmp_path / "report.pdf"
    local_path.write_bytes(b"local cache")
    events = []
    db = FakeDatabase(report_document(tmp_path), events)

    def storage_delete(storage_path):
        events.append(("storage_delete", storage_path))
        return True

    result = delete_report_document(db, 42, storage_delete=storage_delete)

    assert events == [
        ("get", 42),
        ("storage_delete", "42.pdf"),
        ("db_delete", 42),
    ]
    assert result is not None
    assert result.storage_object_existed is True
    assert result.local_file_deleted is True
    assert not local_path.exists()


def test_missing_storage_object_still_allows_metadata_deletion(tmp_path):
    events = []
    db = FakeDatabase(report_document(tmp_path, path=""), events)

    def storage_delete(storage_path):
        events.append(("storage_delete", storage_path))
        return False

    result = delete_report_document(db, 42, storage_delete=storage_delete)

    assert events[-1] == ("db_delete", 42)
    assert result is not None
    assert result.storage_object_existed is False


def test_storage_error_surfaces_before_database_or_local_delete(tmp_path):
    local_path = tmp_path / "report.pdf"
    local_path.write_bytes(b"local cache")
    events = []
    db = FakeDatabase(report_document(tmp_path), events)

    def storage_delete(storage_path):
        events.append(("storage_delete", storage_path))
        raise requests.HTTPError("storage unavailable")

    with pytest.raises(requests.HTTPError):
        delete_report_document(db, 42, storage_delete=storage_delete)

    assert events == [("get", 42), ("storage_delete", "42.pdf")]
    assert local_path.exists()


@pytest.mark.parametrize("category", ["workout", None, "scouting"])
def test_non_report_categories_are_never_deleted(tmp_path, category):
    events = []
    db = FakeDatabase(report_document(tmp_path, category=category), events)
    storage_calls = []

    with pytest.raises(NonReportDocumentError):
        delete_report_document(
            db,
            42,
            storage_delete=lambda path: storage_calls.append(path) or True,
        )

    assert events == [("get", 42)]
    assert storage_calls == []


def test_blob_only_report_without_storage_path_can_be_deleted(tmp_path):
    events = []
    db = FakeDatabase(
        report_document(tmp_path, path="", storage_path=None),
        events,
    )
    storage_calls = []

    result = delete_report_document(
        db,
        42,
        storage_delete=lambda path: storage_calls.append(path) or True,
    )

    assert events == [("get", 42), ("db_delete", 42)]
    assert storage_calls == []
    assert result is not None
    assert result.storage_object_existed is None


def test_missing_metadata_row_is_idempotent(tmp_path):
    events = []
    db = FakeDatabase(None, events)

    result = delete_report_document(
        db,
        42,
        storage_delete=lambda _path: pytest.fail("Storage should not be called"),
    )

    assert result is None
    assert events == [("get", 42)]


def test_metadata_delete_race_surfaces_after_storage_cleanup(tmp_path):
    events = []
    db = FakeDatabase(
        report_document(tmp_path, path=""),
        events,
        delete_result=None,
    )

    def storage_delete(storage_path):
        events.append(("storage_delete", storage_path))
        return True

    with pytest.raises(DocumentMetadataDeleteError):
        delete_report_document(db, 42, storage_delete=storage_delete)

    assert events == [
        ("get", 42),
        ("storage_delete", "42.pdf"),
        ("db_delete", 42),
    ]
