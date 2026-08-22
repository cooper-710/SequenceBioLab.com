import sys
from pathlib import Path

import pytest
import requests
from flask import Flask


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import database  # noqa: E402
import app.routes.api.admin as admin_api  # noqa: E402
import app.services.document_lifecycle as document_lifecycle  # noqa: E402


@pytest.fixture()
def admin_client(tmp_path, monkeypatch):
    real_player_db = database.PlayerDB
    db_path = tmp_path / "players.db"
    db = real_player_db(db_path=str(db_path))
    admin_id = db.create_user(
        email="admin@example.com",
        password_hash="hash",
        first_name="Admin",
        last_name="User",
        is_admin=True,
    )
    player_id = db.create_user(
        email="player@example.com",
        password_hash="hash",
        first_name="Player",
        last_name="User",
        is_admin=False,
    )

    monkeypatch.setattr(admin_api, "PlayerDB", lambda: real_player_db(db_path=str(db_path)))

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test"
    app.register_blueprint(admin_api.bp, url_prefix="/api/admin")

    @app.before_request
    def set_user():
        from flask import g, session

        g.user = {
            "id": int(session["user_id"]),
            "is_admin": bool(session.get("is_admin")),
        } if session.get("user_id") else None

    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user_id"] = int(admin_id)
            session["is_admin"] = True
        yield client, db, int(player_id)

    db.close()


def create_report(db, player_id):
    doc_id = db.create_player_document(
        player_id=player_id,
        filename="report.pdf",
        path="",
        uploaded_by=None,
        category="report",
    )
    db.set_document_storage_path(doc_id, f"{doc_id}.pdf")
    return int(doc_id)


def test_single_report_delete_uses_storage_lifecycle(admin_client, monkeypatch):
    client, db, player_id = admin_client
    doc_id = create_report(db, player_id)
    deleted_paths = []
    monkeypatch.setattr(
        document_lifecycle,
        "delete_storage_file",
        lambda path: deleted_paths.append(path) or True,
    )

    response = client.delete(f"/api/admin/player-docs/{doc_id}")

    assert response.status_code == 200
    assert deleted_paths == [f"{doc_id}.pdf"]
    assert db.get_player_document(doc_id) is None


def test_single_report_delete_keeps_metadata_when_storage_fails(
    admin_client, monkeypatch
):
    client, db, player_id = admin_client
    doc_id = create_report(db, player_id)

    def fail_delete(_path):
        raise requests.ConnectionError("storage unavailable")

    monkeypatch.setattr(document_lifecycle, "delete_storage_file", fail_delete)

    response = client.delete(f"/api/admin/player-docs/{doc_id}")

    assert response.status_code == 502
    document = db.get_player_document(doc_id)
    assert document is not None
    assert document["storage_path"] == f"{doc_id}.pdf"
    assert document["lifecycle_status"] == "delete_failed"
    assert document["delete_attempts"] == 1


def test_audit_log_failure_does_not_report_completed_delete_as_failed(
    admin_client, monkeypatch
):
    client, db, player_id = admin_client
    doc_id = create_report(db, player_id)
    monkeypatch.setattr(document_lifecycle, "delete_storage_file", lambda _path: True)

    def fail_event(*_args, **_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(database.PlayerDB, "record_player_document_event", fail_event)

    response = client.delete(f"/api/admin/player-docs/{doc_id}")

    assert response.status_code == 200
    assert db.get_player_document(doc_id) is None


def test_bulk_delete_removes_reports_but_protects_storage_workouts(
    admin_client, monkeypatch
):
    client, db, player_id = admin_client
    report_id = create_report(db, player_id)
    workout_id = db.create_player_document(
        player_id=player_id,
        filename="workout.pdf",
        path="",
        uploaded_by=None,
        category="workout",
    )
    db.set_document_storage_path(workout_id, f"{workout_id}.pdf")
    monkeypatch.setattr(document_lifecycle, "delete_storage_file", lambda _path: True)

    response = client.delete(f"/api/admin/player-docs/by-player/{player_id}")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "partial"
    assert payload["count"] == 1
    assert payload["protected_document_ids"] == [int(workout_id)]
    assert db.get_player_document(report_id) is None
    assert db.get_player_document(workout_id) is not None


def test_player_cannot_download_another_players_report(admin_client, monkeypatch):
    client, db, owner_id = admin_client
    doc_id = create_report(db, owner_id)
    other_id = db.create_user(
        email="other@example.com",
        password_hash="hash",
        first_name="Other",
        last_name="Player",
        is_admin=False,
    )
    monkeypatch.setattr(
        document_lifecycle,
        "delete_storage_file",
        lambda _path: True,
    )

    with client.session_transaction() as session:
        session["user_id"] = int(other_id)
        session["is_admin"] = False

    response = client.get(f"/api/admin/player-docs/{doc_id}")

    assert response.status_code == 403


def test_workout_delete_refuses_to_orphan_storage_object(admin_client):
    client, db, player_id = admin_client
    workout_id = db.create_player_document(
        player_id=player_id,
        filename="workout.pdf",
        path="",
        uploaded_by=None,
        category="workout",
    )
    db.set_document_storage_path(workout_id, f"{workout_id}.pdf")

    response = client.delete(f"/api/admin/workouts/{workout_id}")

    assert response.status_code == 409
    assert db.get_player_document(workout_id) is not None


def test_admin_listing_keeps_failed_reports_visible_for_retry(admin_client):
    client, db, player_id = admin_client
    doc_id = create_report(db, player_id)
    db.mark_document_lifecycle_failure(doc_id, "delete_failed", "temporary outage")

    response = client.get(f"/api/admin/player-docs/by-player/{player_id}")

    assert response.status_code == 200
    documents = response.get_json()["documents"]
    failed = next(doc for doc in documents if doc["id"] == doc_id)
    assert failed["lifecycle_status"] == "delete_failed"
    assert failed["last_delete_error"] == "temporary outage"
