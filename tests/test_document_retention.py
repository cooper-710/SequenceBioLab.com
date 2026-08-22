import sys
from pathlib import Path
from datetime import datetime

import pytest


@pytest.fixture()
def temp_db_and_files(tmp_path, monkeypatch):
    """
    Create a temp SQLite DB + dummy files, and monkeypatch the purge service
    to use the temp DB instead of the default build/database path.
    """
    # Ensure `database` module import (matches app.services.page_service sys.path behavior)
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "src"))
    import database  # noqa: E402

    db_path = tmp_path / "players.db"
    db = database.PlayerDB(db_path=str(db_path))

    # Point the purge service at our temp DB by patching PlayerDB constructor used there.
    import app.services.page_service as page_service  # noqa: E402

    monkeypatch.setattr(
        page_service,
        "PlayerDB",
        lambda: database.PlayerDB(db_path=str(db_path)),
    )
    monkeypatch.setattr(page_service.Config, "DOCUMENT_REQUEST_CLEANUP_ENABLED", True)

    yield db, tmp_path, database, page_service

    db.close()


def _create_user(db, email: str = "player@example.com") -> int:
    return db.create_user(
        email=email,
        password_hash="hash",
        first_name="Test",
        last_name="Player",
        is_admin=False,
    )


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"dummy")


def test_non_series_docs_auto_delete_after_retention(temp_db_and_files):
    db, tmp_path, _database, page_service = temp_db_and_files

    user_id = _create_user(db)

    # Create two docs:
    # - a non-series report that should be deleted after retention
    # - a legacy workout doc that should be excluded from non-series purge
    old_ts = datetime.now().timestamp() - (8 * 24 * 60 * 60)  # 8 days ago

    non_series_path = tmp_path / "player_documents" / str(user_id) / "notes.pdf"
    workout_path = tmp_path / "workouts" / str(user_id) / "legacy_workout.pdf"
    _touch(non_series_path)
    _touch(workout_path)

    non_series_id = db.create_player_document(
        player_id=user_id,
        filename="notes.pdf",
        path=str(non_series_path),
        uploaded_by=None,
        category="report",
        series_opponent=None,
        series_label=None,
        series_start=None,
        series_end=None,  # <- non-series
    )
    workout_id = db.create_player_document(
        player_id=user_id,
        filename="legacy_workout.pdf",
        path=str(workout_path),
        uploaded_by=None,
        category="workout",
        series_opponent=None,
        series_label=None,
        series_start=None,
        series_end=None,  # <- also non-series, but should be excluded by category
    )

    # Backdate uploaded_at for both docs so they exceed retention.
    cursor = db.conn.cursor()
    db._execute(
        cursor,
        "UPDATE player_documents SET uploaded_at = ? WHERE id IN (?, ?)",
        (float(old_ts), int(non_series_id), int(workout_id)),
    )
    db.conn.commit()

    assert non_series_path.exists()
    assert workout_path.exists()

    # Trigger purge (lazy cleanup hook)
    page_service.purge_concluded_series_documents()

    # Non-series doc should be deleted.
    assert db.get_player_document(int(non_series_id)) is None
    assert not non_series_path.exists()

    # Workout doc should remain.
    assert db.get_player_document(int(workout_id)) is not None
    assert workout_path.exists()

    # Log should contain auto_delete_non_series for the deleted doc.
    events = db.list_player_document_events(player_id=user_id, limit=50)
    assert any(
        evt.get("action") == "auto_delete_non_series" and evt.get("filename") == "notes.pdf"
        for evt in events
    )
