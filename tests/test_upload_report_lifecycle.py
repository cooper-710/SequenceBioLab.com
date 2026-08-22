import io
import sys
from pathlib import Path

import pytest
import requests
from flask import Flask


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import database  # noqa: E402
import supabase_storage  # noqa: E402
import app.routes.api.upload as upload_api  # noqa: E402


@pytest.fixture()
def upload_client(tmp_path, monkeypatch):
    real_player_db = database.PlayerDB
    db_path = tmp_path / "players.db"
    db = real_player_db(db_path=str(db_path))
    user_id = db.create_user(
        email="report@example.com",
        password_hash="hash",
        first_name="Report",
        last_name="Player",
        is_admin=False,
    )

    monkeypatch.setattr(database, "PlayerDB", lambda: real_player_db(db_path=str(db_path)))
    monkeypatch.setattr(upload_api, "UPLOAD_API_KEY", "test-upload-key")
    monkeypatch.setattr(upload_api, "UPLOAD_FOLDER", tmp_path / "uploads")
    monkeypatch.setattr(upload_api.Config, "PLAYER_PDF_MAX_BYTES", 1024 * 1024)

    app = Flask(__name__)
    app.register_blueprint(upload_api.bp)
    with app.test_client() as client:
        yield client, db, int(user_id)
    db.close()


def post_report(client, payload=b"%PDF-1.4\nreport\n", **form):
    data = {
        "player_name": "Report Player",
        "opponent": "Unknown",
        "series_date": "",
        "pdf": (io.BytesIO(payload), "report.pdf"),
    }
    data.update(form)
    return client.post(
        "/api/upload-report",
        data=data,
        content_type="multipart/form-data",
        headers={"X-API-Key": "test-upload-key"},
    )


def test_upload_succeeds_only_after_storage_is_active(upload_client, monkeypatch):
    client, db, user_id = upload_client
    calls = []

    def fake_upload(doc_id, data, content_type):
        calls.append((doc_id, data, content_type))
        return f"{doc_id}.pdf"

    monkeypatch.setattr(supabase_storage, "upload_file", fake_upload)

    response = post_report(client)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True

    document = db.get_player_document(int(payload["doc_id"]))
    assert document["player_id"] == user_id
    assert document["storage_path"] == f"{document['id']}.pdf"
    assert document["lifecycle_status"] == "active"
    assert document["object_size_bytes"] == len(b"%PDF-1.4\nreport\n")
    assert len(calls) == 1


def test_same_client_filename_uses_distinct_local_cache_paths(upload_client, monkeypatch):
    client, db, user_id = upload_client
    monkeypatch.setattr(
        supabase_storage,
        "upload_file",
        lambda doc_id, _data, _content_type: f"{doc_id}.pdf",
    )

    first = post_report(client, payload=b"%PDF-1.4\nfirst\n")
    second = post_report(client, payload=b"%PDF-1.4\nsecond\n")

    assert first.status_code == 200
    assert second.status_code == 200
    documents = db.list_all_player_documents(user_id)
    assert len(documents) == 2
    assert documents[0]["filename"] == documents[1]["filename"] == "report.pdf"
    assert documents[0]["path"] != documents[1]["path"]


def test_storage_failure_returns_error_and_preserves_retry_path(upload_client, monkeypatch):
    client, db, user_id = upload_client

    def fail_upload(*_args, **_kwargs):
        raise requests.ConnectionError("temporary outage")

    monkeypatch.setattr(supabase_storage, "upload_file", fail_upload)

    response = post_report(client)
    assert response.status_code == 502
    payload = response.get_json()
    assert payload["success"] is False

    documents = db.list_all_player_documents(user_id)
    assert len(documents) == 1
    document = documents[0]
    assert document["storage_path"] == f"{document['id']}.pdf"
    assert document["lifecycle_status"] == "upload_failed"
    assert "temporary outage" in document["last_delete_error"]


def test_upload_rejects_non_pdf_bytes_before_database_write(upload_client):
    client, db, user_id = upload_client

    response = post_report(client, payload=b"not a pdf")

    assert response.status_code == 400
    assert db.list_all_player_documents(user_id) == []


def test_upload_rejects_oversized_pdf_before_database_write(
    upload_client, monkeypatch
):
    client, db, user_id = upload_client
    monkeypatch.setattr(upload_api.Config, "PLAYER_PDF_MAX_BYTES", 10)

    response = post_report(client, payload=b"%PDF-1.4\n" + (b"x" * 20))

    assert response.status_code == 413
    assert db.list_all_player_documents(user_id) == []
