import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import database  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    instance = database.PlayerDB(db_path=str(tmp_path / "players.db"))
    yield instance
    instance.close()


def create_user(db):
    return db.create_user(
        email="lifecycle@example.com",
        password_hash="hash",
        first_name="Life",
        last_name="Cycle",
        is_admin=False,
    )


def test_reports_receive_expiry_but_workouts_do_not(db):
    user_id = create_user(db)
    report_id = db.create_player_document(
        player_id=user_id,
        filename="report.pdf",
        path="",
        uploaded_by=None,
        category="report",
    )
    workout_id = db.create_player_document(
        player_id=user_id,
        filename="workout.pdf",
        path="",
        uploaded_by=None,
        category="workout",
    )

    report = db.get_player_document(report_id)
    workout = db.get_player_document(workout_id)

    assert report["lifecycle_status"] == "active"
    assert report["expires_at"] == pytest.approx(
        report["uploaded_at"] + (7 * 24 * 60 * 60), abs=1
    )
    assert workout["expires_at"] is None


def test_generic_documents_are_outside_automated_retention(db):
    user_id = create_user(db)
    doc_id = db.create_player_document(
        player_id=user_id,
        filename="manual.pdf",
        path="",
        uploaded_by=None,
        category=None,
    )

    assert db.get_player_document(doc_id)["expires_at"] is None


def test_storage_activation_records_retry_metadata(db):
    user_id = create_user(db)
    doc_id = db.create_player_document(
        player_id=user_id,
        filename="report.pdf",
        path="",
        uploaded_by=None,
        category="report",
        lifecycle_status="pending_upload",
    )

    db.set_document_storage_path(
        doc_id,
        f"{doc_id}.pdf",
        object_size_bytes=1234,
        lifecycle_status="active",
    )
    document = db.get_player_document(doc_id)

    assert document["storage_path"] == f"{doc_id}.pdf"
    assert document["object_size_bytes"] == 1234
    assert document["lifecycle_status"] == "active"
    assert document["last_delete_error"] is None


def test_database_bulk_delete_refuses_storage_backed_rows(db):
    user_id = create_user(db)
    doc_id = db.create_player_document(
        player_id=user_id,
        filename="report.pdf",
        path="",
        uploaded_by=None,
        category="report",
    )
    db.set_document_storage_path(doc_id, f"{doc_id}.pdf")

    with pytest.raises(RuntimeError, match="lifecycle service"):
        db.delete_all_player_documents(user_id)

    assert db.get_player_document(doc_id) is not None


def test_user_delete_refuses_to_orphan_storage_objects(db):
    user_id = create_user(db)
    doc_id = db.create_player_document(
        player_id=user_id,
        filename="report.pdf",
        path="",
        uploaded_by=None,
        category="report",
    )
    db.set_document_storage_path(doc_id, f"{doc_id}.pdf")

    with pytest.raises(RuntimeError, match="Storage-backed"):
        db.delete_user(user_id)

    assert db.get_user_by_id(user_id) is not None
    assert db.get_player_document(doc_id) is not None
