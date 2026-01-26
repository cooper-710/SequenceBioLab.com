import sys
from pathlib import Path

import pytest
from flask import Flask


@pytest.fixture()
def client_db(tmp_path, monkeypatch):
    """
    Build a tiny Flask app that mounts the admin API blueprint and uses a temp DB.

    This lets us regression-test that document downloads work even when the on-disk
    file is missing (Render ephemeral filesystem).
    """
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    import database  # noqa: E402

    db_path = tmp_path / "players.db"
    db = database.PlayerDB(db_path=str(db_path))

    user_id = db.create_user(
        email="player@example.com",
        password_hash="hash",
        first_name="Test",
        last_name="Player",
        is_admin=False,
    )

    import app.routes.api.admin as admin_api  # noqa: E402
    import app.services.page_service as page_service  # noqa: E402

    # Patch the blueprint + purge hook to use our temp DB.
    monkeypatch.setattr(admin_api, "PlayerDB", lambda: database.PlayerDB(db_path=str(db_path)))
    monkeypatch.setattr(page_service, "PlayerDB", lambda: database.PlayerDB(db_path=str(db_path)))

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test"
    app.register_blueprint(admin_api.bp, url_prefix="/api/admin")

    # Minimal auth context for routes that reference g.user (e.g. workout viewer).
    @app.before_request
    def _set_test_user():
        from flask import g, session
        if session.get("user_id"):
            g.user = {"id": int(session["user_id"]), "is_admin": bool(session.get("is_admin"))}
        else:
            g.user = None

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = int(user_id)
            sess["is_admin"] = True
        yield client, db, int(user_id)

    db.close()


def test_download_player_doc_falls_back_to_db_blob(client_db):
    client, db, user_id = client_db

    payload = b"%PDF-1.4\n% minimal pdf bytes\n"
    doc_id = db.create_player_document(
        player_id=int(user_id),
        filename="notes.pdf",
        path="",  # simulate missing/ephemeral file
        uploaded_by=int(user_id),
        category=None,
        series_opponent=None,
        series_label=None,
        series_start=None,
        series_end=None,
    )
    db.upsert_player_document_blob(int(doc_id), "application/pdf", payload)

    resp = client.get(f"/api/admin/player-docs/{int(doc_id)}")
    assert resp.status_code == 200
    assert resp.data == payload
    assert (resp.headers.get("Content-Type") or "").startswith("application/pdf")


def test_view_workout_doc_falls_back_to_db_blob(client_db):
    client, db, user_id = client_db

    payload = b"%PDF-1.4\n% workout pdf bytes\n"
    doc_id = db.create_player_document(
        player_id=int(user_id),
        filename="workout.pdf",
        path="",  # simulate missing/ephemeral file
        uploaded_by=int(user_id),
        category="workout",
        series_opponent=None,
        series_label=None,
        series_start=None,
        series_end=None,
    )
    db.upsert_player_document_blob(int(doc_id), "application/pdf", payload)

    resp = client.get(f"/api/admin/workout-docs/{int(doc_id)}")
    assert resp.status_code == 200
    assert resp.data == payload
    assert (resp.headers.get("Content-Type") or "").startswith("application/pdf")

