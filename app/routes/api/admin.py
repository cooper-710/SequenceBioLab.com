"""
Admin API routes
"""
from flask import Blueprint, request, jsonify, render_template, send_file, g, session, abort
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from werkzeug.utils import secure_filename
import mimetypes
import subprocess
import threading
import re
import logging

bp = Blueprint('admin', __name__)

# Import dependencies
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
try:
    from database import PlayerDB
except ImportError:
    PlayerDB = None

from app.config import Config
from app.middleware.auth import admin_required, login_required
from app.middleware.csrf import validate_csrf
from app.utils.helpers import clean_str
from app.utils.cron_manager import create_cron_job, remove_cron_job, get_cron_status
from app.services.schedule_service import collect_series_for_team
from app.services.player_service import determine_user_team
from app.services.page_service import purge_concluded_series_documents
from flask import url_for
import settings_manager

# Helper functions

def _format_user_record(user: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize user rows for admin API responses."""
    created_ts = user.get("created_at")
    updated_ts = user.get("updated_at")

    def _iso(ts):
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(ts).isoformat()
        except Exception:
            return None

    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "created_at": _iso(created_ts),
        "updated_at": _iso(updated_ts),
        "is_admin": bool(user.get("is_admin")),
        "is_active": bool(user.get("is_active", True)),  # Default to True for backward compatibility
        "email_verified": bool(user.get("email_verified", False)),  # Default to False for backward compatibility
    }


def _format_staff_note(note: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a staff note row for JSON/template contexts."""
    created_at = note.get("created_at")
    updated_at = note.get("updated_at")

    def _fmt(ts):
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(ts).strftime("%b %d, %Y %I:%M %p")
        except Exception:
            return None

    def _iso(ts):
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(ts).isoformat()
        except Exception:
            return None

    return {
        "id": note.get("id"),
        "title": note.get("title"),
        "body": note.get("body"),
        "team_abbr": note.get("team_abbr"),
        "tags": note.get("tags") or [],
        "author": note.get("author_name"),
        "pinned": bool(note.get("pinned")),
        "created_at": _fmt(created_at),
        "updated_at": _fmt(updated_at),
        "created_at_iso": _iso(created_at),
        "updated_at_iso": _iso(updated_at),
        "created_at_raw": created_at,
        "updated_at_raw": updated_at,
    }



def _format_player_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize player document metadata."""
    uploaded_ts = doc.get("uploaded_at")
    series_start_ts = doc.get("series_start")
    series_end_ts = doc.get("series_end")
    category = (doc.get("category") or "").strip().lower() if doc else None

    def _fmt(ts):
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(ts).strftime("%b %d, %Y %I:%M %p")
        except Exception:
            return None

    def _iso(ts):
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(ts).isoformat()
        except Exception:
            return None

    def _fmt_date(ts):
        if not ts:
            return None
        try:
            return datetime.fromtimestamp(ts).strftime("%b %d, %Y")
        except Exception:
            return None

    now_ts = datetime.now().timestamp()
    series_status = None
    start_date = datetime.fromtimestamp(series_start_ts).date() if series_start_ts else None
    end_date = datetime.fromtimestamp(series_end_ts).date() if series_end_ts else None
    today_date = datetime.fromtimestamp(now_ts).date()
    if series_start_ts and series_end_ts:
        if series_end_ts < now_ts:
            series_status = "expired"
        elif start_date and end_date and start_date <= today_date <= end_date:
            series_status = "current"
        elif series_start_ts <= now_ts <= series_end_ts:
            series_status = "current"
        else:
            series_status = "upcoming"

    series_start_display = _fmt_date(series_start_ts)
    series_end_display = _fmt_date(series_end_ts)
    if series_start_display and series_end_display:
        if series_start_display == series_end_display:
            series_range_display = series_start_display
        else:
            series_range_display = f"{series_start_display} – {series_end_display}"
    else:
        series_range_display = series_start_display or series_end_display

    viewer_url = None
    if category == Config.WORKOUT_CATEGORY:
        viewer_url = url_for("admin.view_workout_document", doc_id=doc.get("id"))

    return {
        "id": doc.get("id"),
        "player_id": doc.get("player_id"),
        "filename": doc.get("filename"),
        "uploaded_at": _fmt(uploaded_ts),
        "uploaded_at_iso": _iso(uploaded_ts),
        "download_url": url_for("admin.download_player_document", doc_id=doc.get("id")),
        "uploaded_by": doc.get("uploaded_by"),
        "category": category,
        "viewer_url": viewer_url,
        "series_opponent": doc.get("series_opponent"),
        "series_label": doc.get("series_label"),
        "series_start": _iso(series_start_ts),
        "series_start_display": series_start_display,
        "series_end": _iso(series_end_ts),
        "series_end_display": series_end_display,
        "series_range_display": series_range_display,
        "series_status": series_status,
    }



def _validate_workout_upload(file_storage) -> Optional[str]:
    if not file_storage:
        return "No document provided."
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        return "Please choose a file to upload."
    ext = Path(filename).suffix.lower()
    if ext not in Config.WORKOUT_ALLOWED_EXTENSIONS:
        return "Unsupported file type. Upload a PDF workout sheet."
    return None


# Note: /admin page route moved to pages blueprint






@bp.route('/users', methods=['GET'])

@admin_required

def api_admin_users():

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500



    try:

        db = PlayerDB()

        users = [

            _format_user_record(row)

            for row in db.list_users()

            if not row.get("is_admin")

        ]

        db.close()

        return jsonify({"users": users})

    except Exception as exc:

        return jsonify({"error": str(exc)}), 500






@bp.route('/users/<int:user_id>/role', methods=['POST'])

@admin_required

def api_admin_set_role(user_id: int):

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500



    payload = request.get_json(silent=True) or {}

    is_admin = bool(payload.get("is_admin"))



    if g.user and g.user.get("id") == user_id and not is_admin:

        return jsonify({"error": "You cannot revoke your own admin access."}), 400



    try:

        db = PlayerDB()

        db.set_user_admin(user_id, is_admin)

        updated = db.get_user_by_id(user_id)

        db.close()

    except Exception as exc:

        return jsonify({"error": str(exc)}), 500



    if not updated:

        return jsonify({"error": "User not found"}), 404



    return jsonify({"user": _format_user_record(updated)})


@bp.route('/users/<int:user_id>/active', methods=['POST'])
@admin_required
def api_admin_set_active(user_id: int):
    """Deactivate or activate a user account."""
    if not PlayerDB:
        return jsonify({"error": "Database unavailable"}), 500

    payload = request.get_json(silent=True) or {}
    is_active = bool(payload.get("is_active", True))

    try:
        db = PlayerDB()
        target_user = db.get_user_by_id(user_id)
        if not target_user:
            db.close()
            return jsonify({"error": "User not found"}), 404
        
        # Prevent deactivating admin accounts
        if target_user.get("is_admin") and not is_active:
            db.close()
            return jsonify({"error": "Admin accounts cannot be deactivated."}), 400
        
        # Prevent deactivating yourself
        if g.user and g.user.get("id") == user_id and not is_active:
            db.close()
            return jsonify({"error": "You cannot deactivate your own account."}), 400
        
        db.set_user_active(user_id, is_active)
        updated = db.get_user_by_id(user_id)
        db.close()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    if not updated:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"user": _format_user_record(updated)})


@bp.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
def api_admin_delete_user(user_id: int):
    """Delete a user account and all associated files."""
    if not PlayerDB:
        return jsonify({"error": "Database unavailable"}), 500

    try:
        db = PlayerDB()
        target_user = db.get_user_by_id(user_id)
        if not target_user:
            db.close()
            return jsonify({"error": "User not found"}), 404
        
        # Prevent deleting admin accounts
        if target_user.get("is_admin"):
            db.close()
            return jsonify({"error": "Admin accounts cannot be deleted."}), 400
        
        # Prevent deleting yourself
        if g.user and g.user.get("id") == user_id:
            db.close()
            return jsonify({"error": "You cannot delete your own account."}), 400
        
        # Get all player documents before deletion to clean up files
        player_docs = db.list_player_documents(user_id)
        doc_paths = [Path(doc.get("path") or "") for doc in player_docs if doc.get("path")]
        
        deleted = db.delete_user(user_id)
        db.close()
        
        # Clean up physical files after database deletion
        for doc_path in doc_paths:
            if doc_path.exists() and doc_path.is_file():
                try:
                    doc_path.unlink()
                except OSError as exc:
                    print(f"Warning removing player document file {doc_path}: {exc}")
        
        # Clean up player documents directory if it exists
        player_docs_dir = Config.PLAYER_DOCS_DIR / str(user_id)
        if player_docs_dir.exists() and player_docs_dir.is_dir():
            try:
                import shutil
                shutil.rmtree(player_docs_dir)
            except OSError as exc:
                print(f"Warning removing player documents directory {player_docs_dir}: {exc}")
        
        # Clean up workouts directory if it exists
        workouts_dir = Config.WORKOUT_DOCS_DIR / str(user_id)
        if workouts_dir.exists() and workouts_dir.is_dir():
            try:
                import shutil
                shutil.rmtree(workouts_dir)
            except OSError as exc:
                print(f"Warning removing workouts directory {workouts_dir}: {exc}")
        
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    if not deleted:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"status": "deleted", "user_id": user_id})






@bp.route('/staff-notes', methods=['GET', 'POST'])

@admin_required

def api_admin_staff_notes():

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500



    if request.method == 'GET':

        team_filter = request.args.get("team")

        try:

            db = PlayerDB()

            notes = db.list_staff_notes(team_abbr=team_filter, limit=100)

            db.close()

            return jsonify({"notes": [_format_staff_note(note) for note in notes]})

        except Exception as exc:

            return jsonify({"error": str(exc)}), 500



    # POST - create note

    payload = request.get_json(silent=True) or {}

    title = (payload.get("title") or "").strip()

    body = (payload.get("body") or "").strip()

    team_abbr = payload.get("team_abbr")

    tags = payload.get("tags") or []

    pinned = bool(payload.get("pinned"))



    if not title or not body:

        return jsonify({"error": "Title and body are required."}), 400



    try:

        db = PlayerDB()

        note_id = db.create_staff_note(

            title=title,

            body=body,

            team_abbr=team_abbr,

            tags=tags,

            pinned=pinned,

            author_id=g.user.get("id") if g.user else None,

            author_name=f"{g.user.get('first_name', '')} {g.user.get('last_name', '')}".strip() if g.user else "Admin"

        )

        created = db.get_staff_note(note_id)

        db.close()

    except Exception as exc:

        return jsonify({"error": str(exc)}), 500



    return jsonify({"note": _format_staff_note(created)}), 201






@bp.route('/staff-notes/<int:note_id>', methods=['PUT', 'DELETE'])

@admin_required

def api_admin_staff_note_detail(note_id: int):

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500



    if request.method == 'DELETE':

        try:

            db = PlayerDB()

            deleted = db.delete_staff_note(note_id)

            db.close()

        except Exception as exc:

            return jsonify({"error": str(exc)}), 500



        if not deleted:

            return jsonify({"error": "Note not found"}), 404



        return jsonify({"status": "deleted"})



    # PUT - update

    payload = request.get_json(silent=True) or {}

    fields = {}

    if "title" in payload:

        fields["title"] = payload["title"]

    if "body" in payload:

        fields["body"] = payload["body"]

    if "team_abbr" in payload:

        fields["team_abbr"] = payload["team_abbr"]

    if "tags" in payload:

        fields["tags"] = payload["tags"]

    if "pinned" in payload:

        fields["pinned"] = payload["pinned"]



    if not fields:

        return jsonify({"error": "No updates supplied."}), 400



    try:

        db = PlayerDB()

        updated = db.update_staff_note(note_id, **fields)

        note = db.get_staff_note(note_id) if updated else None

        db.close()

    except Exception as exc:

        return jsonify({"error": str(exc)}), 500



    if not updated or not note:

        return jsonify({"error": "Note not found"}), 404



    return jsonify({"note": _format_staff_note(note)})






@bp.route('/players', methods=['GET'])

@admin_required

def api_admin_players():

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500



    search = request.args.get("search", "").strip() or None

    limit = request.args.get("limit", type=int) or 200



    try:

        db = PlayerDB()

        players = db.search_players(search=search, limit=limit)

        db.close()

        return jsonify({"players": players})

    except Exception as exc:

        return jsonify({"error": str(exc)}), 500






@bp.route('/workouts', methods=['POST'])

@admin_required

def api_admin_workouts_upload():

    """Upload or replace the current workout document."""

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500



    csrf_token = request.form.get("csrf_token")

    if not validate_csrf(csrf_token):

        return jsonify({"error": "Invalid CSRF token. Refresh the page and try again."}), 400



    player_id_raw = (request.form.get("player_id") or "").strip()

    if not player_id_raw:

        return jsonify({"error": "Select a player before uploading."}), 400

    try:

        player_id = int(player_id_raw)

    except ValueError:

        return jsonify({"error": "Invalid player selection."}), 400



    file = request.files.get("document")

    error = _validate_workout_upload(file)

    if error:

        return jsonify({"error": error}), 400



    original_filename = secure_filename(file.filename)

    timestamp_label = datetime.now().strftime("%Y%m%d_%H%M%S")

    storage_name = f"{timestamp_label}_{original_filename}"

    dest_path: Optional[Path] = None

    db = None

    try:

        db = PlayerDB()

        player_record = db.get_user_by_id(player_id)

        if not player_record:

            raise LookupError("Player account not found.")

        if player_record.get("is_admin"):

            raise PermissionError("Cannot attach workouts to admin accounts.")



        player_dir = Config.WORKOUT_DOCS_DIR / str(player_id)

        player_dir.mkdir(parents=True, exist_ok=True)

        dest_path = player_dir / storage_name



        try:

            file.save(dest_path)

        except Exception as exc:

            raise RuntimeError(f"Unable to save workout document: {exc}") from exc



        uploader_id = g.user.get("id") if g.user else None

        doc_id = db.create_player_document(

            player_id=player_id,

            filename=original_filename,

            path=str(dest_path),

            uploaded_by=uploader_id,

            category=Config.WORKOUT_CATEGORY,

        )

        doc = db.get_player_document(doc_id)

        db.record_player_document_event(

            player_id=player_id,

            filename=original_filename,

            action="upload_workout",

            performed_by=uploader_id,

        )

    except LookupError as exc:

        if dest_path and dest_path.exists():

            try:

                dest_path.unlink()

            except OSError:

                pass

        return jsonify({"error": str(exc)}), 404

    except PermissionError as exc:

        if dest_path and dest_path.exists():

            try:

                dest_path.unlink()

            except OSError:

                pass

        return jsonify({"error": str(exc)}), 403

    except Exception as exc:

        if dest_path and dest_path.exists():

            try:

                dest_path.unlink()

            except OSError:

                pass

        return jsonify({"error": str(exc)}), 500

    finally:

        if db:

            db.close()



    return jsonify({"workout": _format_player_document(doc)}), 201






@bp.route('/workouts/latest', methods=['GET'])

@login_required

def api_workouts_latest():

    """Return the latest workout document metadata."""

    if not PlayerDB:

        return jsonify({"workout": None})



    viewer_user = getattr(g, "user", None)

    if not viewer_user:

        return jsonify({"error": "User session unavailable."}), 403



    requested_player_id = request.args.get("player_id", type=int)

    player_id = requested_player_id or viewer_user.get("id")



    if not player_id:

        return jsonify({"workout": None})



    if (

        requested_player_id

        and not session.get("is_admin")

        and player_id != viewer_user.get("id")

    ):

        return jsonify({"error": "Not authorized to view this workout."}), 403



    db = None

    doc = None

    try:

        db = PlayerDB()

        doc = db.get_latest_player_document_by_category(player_id, Config.WORKOUT_CATEGORY)

    except Exception as exc:

        if db:

            db.close()

            db = None

        return jsonify({"error": str(exc)}), 500

    finally:

        if db:

            db.close()



    if not doc:

        return jsonify({"workout": None})



    return jsonify({"workout": _format_player_document(doc)})






@bp.route('/workouts/player/<int:player_id>', methods=['GET'])

@admin_required

def api_admin_workouts_for_player(player_id: int):

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500



    db = None

    try:

        db = PlayerDB()

        player = db.get_user_by_id(player_id)

        if not player or player.get("is_admin"):

            return jsonify({"error": "Player account not found."}), 404

        docs = db.list_player_documents(player_id, category=Config.WORKOUT_CATEGORY)

        formatted = [_format_player_document(doc) for doc in docs]

    except Exception as exc:

        if db:

            db.close()

        return jsonify({"error": str(exc)}), 500

    finally:

        if db:

            db.close()



    return jsonify({"workouts": formatted})






@bp.route('/workouts/<int:doc_id>', methods=['DELETE'])

@admin_required

def api_admin_workouts_delete(doc_id: int):

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500



    db = None

    doc = None

    try:

        db = PlayerDB()

        doc = db.get_player_document(doc_id)

        if not doc or (doc.get("category") or "").strip().lower() != Config.WORKOUT_CATEGORY:

            db.close()

            return jsonify({"error": "Workout not found."}), 404

        deleted = db.delete_player_document(doc_id)

        if not deleted:

            db.close()

            return jsonify({"error": "Workout not found."}), 404

        doc = deleted

        db.record_player_document_event(

            player_id=doc.get("player_id"),

            filename=doc.get("filename"),

            action="delete_workout",

            performed_by=g.user.get("id") if g.user else None,

        )

    except Exception as exc:

        if db:

            db.close()

        return jsonify({"error": str(exc)}), 500

    finally:

        if db:

            db.close()



    path = Path((doc or {}).get("path") or "")

    if path.exists() and path.is_file():

        try:

            path.unlink()

        except OSError as exc:

            print(f"Warning removing workout document file {path}: {exc}")



    return jsonify({

        "status": "deleted",

        "workout": {

            "id": doc.get("id"),

            "player_id": doc.get("player_id"),

            "filename": doc.get("filename"),

        }

    })






@bp.route('/player-docs', methods=['POST'])

@admin_required

def api_admin_player_docs_upload():

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500



    player_id_raw = request.form.get("player_id", "").strip()

    file = request.files.get("document")



    if not player_id_raw:

        return jsonify({"error": "Player selection is required."}), 400

    if not file or not file.filename:

        return jsonify({"error": "A document must be provided."}), 400



    series_choice = (request.form.get("series_id") or "").strip()

    raw_series_opponent = clean_str(request.form.get("series_opponent")).upper()

    raw_series_label = clean_str(request.form.get("series_label"))

    series_start_raw = request.form.get("series_start", "").strip()

    series_end_raw = request.form.get("series_end", "").strip()



    def _parse_series_ts(raw: str) -> Optional[float]:

        if not raw:

            return None

        value = raw

        try:

            if value.endswith("Z"):

                value = value[:-1] + "+00:00"

            return datetime.fromisoformat(value).timestamp()

        except Exception:

            try:

                return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()

            except Exception:

                return None



    series_opponent = None

    series_label = None

    series_start_ts = None

    series_end_ts = None



    if series_choice and series_choice != "__none__":

        series_start_ts = _parse_series_ts(series_start_raw)

        series_end_ts = _parse_series_ts(series_end_raw)

        series_opponent = raw_series_opponent or None

        series_label = raw_series_label or None



        if not series_opponent or series_start_ts is None or series_end_ts is None:

            return jsonify({"error": "Series selection is required before uploading a document."}), 400



        if series_end_ts < series_start_ts:

            return jsonify({"error": "Series end date must be after its start date."}), 400



    try:

        player_id = int(player_id_raw)

    except ValueError:

        return jsonify({"error": "Invalid player identifier."}), 400



    filename = secure_filename(file.filename)

    if not filename:

        return jsonify({"error": "Invalid filename."}), 400



    player_dir = Config.PLAYER_DOCS_DIR / str(player_id)

    player_dir.mkdir(parents=True, exist_ok=True)

    dest_path = player_dir / filename



    try:

        file.save(dest_path)

        db = PlayerDB()

        player_record = db.get_user_by_id(player_id)

        if not player_record:

            db.close()

            if dest_path.exists():

                try:

                    dest_path.unlink()

                except OSError:

                    pass

            return jsonify({"error": "Player account not found."}), 404

        doc_id = db.create_player_document(

            player_id=player_id,

            filename=filename,

            path=str(dest_path),

            uploaded_by=g.user.get("id") if g.user else None,

            series_opponent=series_opponent,

            series_label=series_label,

            series_start=series_start_ts,

            series_end=series_end_ts

        )

        doc = db.get_player_document(doc_id)

        db.record_player_document_event(

            player_id=player_id,

            filename=filename,

            action="upload",

            performed_by=g.user.get("id") if g.user else None

        )

        db.close()

    except Exception as exc:

        if dest_path.exists():

            try:

                dest_path.unlink()

            except OSError:

                pass

        return jsonify({"error": str(exc)}), 500



    return jsonify({"document": _format_player_document(doc)}), 201






@bp.route('/player-series/<int:user_id>', methods=['GET'])

@admin_required

def api_admin_player_series(user_id: int):

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500

    try:

        db = PlayerDB()

        user = db.get_user_by_id(user_id)

        db.close()

    except Exception as exc:

        return jsonify({"error": str(exc)}), 500



    if not user or user.get("is_admin"):

        return jsonify({"series": []})



    team_abbr = determine_user_team(user)

    # Use 365 days to match gameday hub timeframe

    all_series = collect_series_for_team(team_abbr, days_ahead=365)

    

    # Filter to show only the same series as gameday hub (one per category: current, next upcoming, most recent past)

    from datetime import date as date_type

    today = date_type.today()

    

    # Separate series by category

    past_series = []

    current_series_list = []

    upcoming_series_list = []

    

    for series in all_series:

        status = series.get("status", "")

        start_str = series.get("start", "")

        end_str = series.get("end", "")

        

        if not start_str or not end_str:

            continue

            

        try:

            start_dt = datetime.fromisoformat(start_str.split('T')[0] if 'T' in start_str else start_str).date()

            end_dt = datetime.fromisoformat(end_str.split('T')[0] if 'T' in end_str else end_str).date()

        except Exception:

            continue

        

        # Categorize series (same logic as gameday hub)

        if end_dt < today or status == "expired":

            past_series.append(series)

        elif start_dt <= today <= end_dt or status == "current":

            current_series_list.append(series)

        else:

            upcoming_series_list.append(series)

    

    # Sort each category

    past_series.sort(key=lambda s: s.get("start", ""), reverse=True)  # Most recent first

    current_series_list.sort(key=lambda s: s.get("start", ""))

    upcoming_series_list.sort(key=lambda s: s.get("start", ""))

    

    # Select the series to show (matching gameday hub logic: one per category)

    filtered_series = []

    

    # Current series (or next upcoming if no current) - this is what shows in "Current Series" tab

    if current_series_list:

        filtered_series.append(current_series_list[0])

        # Next upcoming after current - this is what shows in "Upcoming Series" tab

        if upcoming_series_list:

            filtered_series.append(upcoming_series_list[0])

    elif upcoming_series_list:

        # No current, so first upcoming becomes "current" - this is what shows in "Current Series" tab

        filtered_series.append(upcoming_series_list[0])

        # Next upcoming after that - this is what shows in "Upcoming Series" tab

        if len(upcoming_series_list) > 1:

            filtered_series.append(upcoming_series_list[1])

    

    # Most recent past series - this is what shows in "Past Series" tab

    if past_series:

        filtered_series.append(past_series[0])

    

    # Sort by start date

    filtered_series.sort(key=lambda s: s.get("start", ""))

    

    return jsonify({"series": filtered_series, "team": team_abbr})






@bp.route('/player-docs/<player_id>', methods=['GET'])

@admin_required

def api_admin_player_docs_list(player_id: str):

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500

    purge_concluded_series_documents()

    try:

        db = PlayerDB()

        docs = db.list_player_documents(int(player_id))

        db.close()

        return jsonify({"documents": [_format_player_document(doc) for doc in docs]})

    except Exception as exc:

        return jsonify({"error": str(exc)}), 500






@bp.route('/player-docs/<int:doc_id>', methods=['GET'])

@login_required

def download_player_document(doc_id: int):

    if not PlayerDB:

        abort(404)

    purge_concluded_series_documents()

    try:

        db = PlayerDB()

        doc = db.get_player_document(doc_id)

        db.close()

    except Exception:

        doc = None

    if not doc:

        abort(404)

    path = Path(doc.get("path") or "")

    if not path.exists() or not path.is_file():

        abort(404)

    return send_file(path, as_attachment=True, download_name=doc.get("filename") or path.name)






@bp.route('/workout-docs/<int:doc_id>', methods=['GET'])

@login_required

def view_workout_document(doc_id: int):

    if not PlayerDB:

        abort(404)

    try:

        db = PlayerDB()

        doc = db.get_player_document(doc_id)

        db.close()

    except Exception:

        doc = None

    if not doc or (doc.get("category") or "").strip().lower() != Config.WORKOUT_CATEGORY:

        abort(404)

    viewer_user = getattr(g, "user", None)

    viewer_id = viewer_user.get("id") if viewer_user else None

    if viewer_id is None:

        abort(403)

    if doc.get("player_id") != viewer_id and not session.get("is_admin"):

        abort(403)

    path = Path(doc.get("path") or "")

    if not path.exists() or not path.is_file():

        abort(404)

    mime_type, _ = mimetypes.guess_type(path.name)

    return send_file(

        path,

        as_attachment=False,

        download_name=doc.get("filename") or path.name,

        mimetype=mime_type or "application/pdf",

    )






@bp.route('/player-docs/<int:doc_id>', methods=['DELETE'])

@admin_required

def api_admin_player_docs_delete(doc_id: int):

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500

    try:

        db = PlayerDB()

        doc = db.delete_player_document(doc_id)

        if not doc:

            db.close()

            return jsonify({"error": "Document not found"}), 404

        db.record_player_document_event(

            player_id=doc["player_id"],

            filename=doc["filename"],

            action="delete",

            performed_by=g.user.get("id") if g.user else None

        )

        db.close()

    except Exception as exc:

        return jsonify({"error": str(exc)}), 500



    try:

        path = Path(doc.get("path") or "")

        if path.exists() and path.is_file():

            path.unlink()

    except OSError as exc:

        print(f"Warning removing document file: {exc}")



    return jsonify({"status": "deleted", "document": _format_player_document(doc)})






@bp.route('/player-docs/logs', methods=['GET'])

@admin_required

def api_admin_player_docs_logs():

    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500

    purge_concluded_series_documents()

    player_id = request.args.get("player_id", type=int)

    limit = request.args.get("limit", type=int) or 200

    try:

        db = PlayerDB()

        events = db.list_player_document_events(player_id=player_id, limit=limit)

        db.close()



        def _format_event(evt: Dict[str, Any]) -> Dict[str, Any]:

            ts = evt.get("timestamp")

            try:

                human = datetime.fromtimestamp(ts).strftime("%b %d, %Y %I:%M %p") if ts else None

            except Exception:

                human = None

            return {

                "id": evt.get("id"),

                "player_id": evt.get("player_id"),

                "filename": evt.get("filename"),

                "action": evt.get("action"),

                "performed_by": evt.get("performed_by"),

                "timestamp": ts,

                "timestamp_human": human,

            }



        return jsonify({"events": [_format_event(evt) for evt in events]})

    except Exception as exc:

        return jsonify({"error": str(exc)}), 500




@bp.route('/staff-notes/<int:note_id>/pin', methods=['POST'])

@admin_required

def api_admin_staff_note_pin(note_id: int):

    payload = request.get_json(silent=True) or {}

    pinned = bool(payload.get("pinned"))



    if not PlayerDB:

        return jsonify({"error": "Database unavailable"}), 500



    try:

        db = PlayerDB()

        updated = db.update_staff_note(note_id, pinned=pinned)

        note = db.get_staff_note(note_id) if updated else None

        db.close()

    except Exception as exc:

        return jsonify({"error": str(exc)}), 500



    if not updated or not note:

        return jsonify({"error": "Note not found"}), 404



    return jsonify({"note": _format_staff_note(note)})


@bp.route('/invite-codes', methods=['GET', 'POST'])
@admin_required
def api_admin_invite_codes():
    """List or create invite codes"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("Invite codes endpoint called")
    except:
        pass
    
    if not PlayerDB:
        logger.error("PlayerDB not available")
        return jsonify({"error": "Database unavailable"}), 500
    
    if request.method == 'GET':
        include_used = request.args.get("include_used", "false").lower() == "true"
        try:
            db = PlayerDB()
            codes = db.list_invite_codes(include_used=include_used)
            db.close()
            
            def _format_invite_code(code: Dict[str, Any]) -> Dict[str, Any]:
                created_ts = code.get("created_at")
                used_ts = code.get("used_at")
                def _iso(ts):
                    if not ts:
                        return None
                    try:
                        return datetime.fromtimestamp(ts).isoformat()
                    except Exception:
                        return None
                
                # Build used_by_name from first_name and last_name
                used_by_first_name = code.get("used_by_first_name")
                used_by_last_name = code.get("used_by_last_name")
                used_by_name = None
                if used_by_first_name or used_by_last_name:
                    used_by_name = f"{used_by_first_name or ''} {used_by_last_name or ''}".strip()
                
                return {
                    "id": code.get("id"),
                    "code": code.get("code"),
                    "created_by": code.get("created_by"),
                    "created_at": _iso(created_ts),
                    "used_at": _iso(used_ts),
                    "used_by": code.get("used_by"),
                    "used_by_name": used_by_name,
                    "is_active": bool(code.get("is_active")),
                    "is_used": bool(used_ts),
                }
            
            formatted_codes = [_format_invite_code(code) for code in codes]
            return jsonify({"invite_codes": formatted_codes})
        except Exception as exc:
            import logging
            import traceback
            logger = logging.getLogger(__name__)
            error_msg = str(exc)
            error_traceback = traceback.format_exc()
            logger.error(f"Error fetching invite codes: {error_msg}\n{error_traceback}")
            print(f"ERROR in invite codes GET: {error_msg}")  # Also print to stdout
            print(error_traceback)
            return jsonify({"error": error_msg, "traceback": error_traceback if Config.DEBUG else None}), 500
    
    # POST - create new invite code
    import secrets
    payload = request.get_json(silent=True) or {}
    custom_code = (payload.get("code") or "").strip().upper()
    
    if custom_code:
        # Validate custom code
        if len(custom_code) < 6:
            return jsonify({"error": "Invite code must be at least 6 characters."}), 400
        code = custom_code
    else:
        # Generate random code (8 characters, alphanumeric, excluding confusing chars)
        code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
    
    try:
        db = PlayerDB()
        # Check if code already exists
        existing = db.get_invite_code(code)
        if existing:
            db.close()
            return jsonify({"error": "This invite code already exists. Please choose a different one."}), 400
        
        created_by = None
        if g.user and isinstance(g.user, dict):
            created_by = g.user.get("id")
        elif hasattr(g, 'user') and g.user:
            created_by = getattr(g.user, 'id', None)
        
        invite_id = db.create_invite_code(code, created_by=created_by)
        created = db.get_invite_code(code)
        if not created:
            db.close()
            return jsonify({"error": "Failed to create invite code"}), 500
        
        db.close()
        
        created_ts = created.get("created_at")
        def _iso(ts):
            if not ts:
                return None
            try:
                return datetime.fromtimestamp(ts).isoformat()
            except Exception:
                return None
        
        response_data = {
            "invite_code": {
                "id": created.get("id"),
                "code": created.get("code"),
                "created_by": created.get("created_by"),
                "created_at": _iso(created_ts),
                "used_at": None,
                "used_by": None,
                "is_active": True,
                "is_used": False,
            }
        }
        return jsonify(response_data), 201
    except Exception as exc:
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        error_msg = str(exc)
        error_traceback = traceback.format_exc()
        logger.error(f"Error creating invite code: {error_msg}\n{error_traceback}")
        print(f"ERROR in invite codes POST: {error_msg}")  # Also print to stdout
        print(error_traceback)
        return jsonify({"error": error_msg, "traceback": error_traceback if Config.DEBUG else None}), 500


@bp.route('/invite-codes/<int:code_id>', methods=['DELETE'])
@admin_required
def api_admin_invite_code_delete(code_id: int):
    """Delete an invite code"""
    if not PlayerDB:
        return jsonify({"error": "Database unavailable"}), 500
    
    try:
        db = PlayerDB()
        deleted = db.delete_invite_code(code_id)
        db.close()
        
        if not deleted:
            return jsonify({"error": "Invite code not found"}), 404
        
        return jsonify({"status": "deleted"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# Data refresh endpoints
ROOT_DIR = Path(__file__).parent.parent.parent.parent.resolve()
UPDATE_SCRIPT = ROOT_DIR / "scripts" / "update_csv_data.py"
LOG_FILE = ROOT_DIR / "logs" / "data_update.log"

# Global state for refresh status
_refresh_status = {
    'status': 'idle',  # idle, running, completed, failed
    'started_at': None,
    'completed_at': None,
    'error': None
}


@bp.route('/data-refresh/trigger', methods=['POST'])
@admin_required
def trigger_data_refresh():
    """Trigger a manual data refresh."""
    global _refresh_status
    
    if _refresh_status['status'] == 'running':
        return jsonify({'error': 'Refresh already in progress'}), 400
    
    def run_refresh():
        global _refresh_status
        _refresh_status['status'] = 'running'
        _refresh_status['started_at'] = datetime.now().isoformat()
        _refresh_status['error'] = None
        
        logger = logging.getLogger(__name__)
        
        try:
            # Verify script exists
            if not UPDATE_SCRIPT.exists():
                error_msg = f"Update script not found at: {UPDATE_SCRIPT}"
                logger.error(error_msg)
                _refresh_status['status'] = 'failed'
                _refresh_status['error'] = error_msg
                _refresh_status['completed_at'] = datetime.now().isoformat()
                return
            
            # Run the update script (explicitly without --dry-run to ensure real updates)
            cmd = ['python3', str(UPDATE_SCRIPT)]
            logger.info(f"Executing data refresh command: {' '.join(cmd)}")
            logger.info(f"Working directory: {ROOT_DIR}")
            logger.info(f"Script path: {UPDATE_SCRIPT}")
            logger.info(f"Script exists: {UPDATE_SCRIPT.exists()}")
            
            # Ensure log directory exists
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            # Write to log file directly so we can see output in real-time
            with open(LOG_FILE, 'a') as log_file:
                log_file.write(f"\n{'='*70}\n")
                log_file.write(f"Data refresh started at {datetime.now().isoformat()}\n")
                log_file.write(f"Command: {' '.join(cmd)}\n")
                log_file.write(f"{'='*70}\n")
            
            result = subprocess.run(
                cmd,
                cwd=str(ROOT_DIR),
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout
            )
            
            # Write output to log file
            with open(LOG_FILE, 'a') as log_file:
                if result.stdout:
                    log_file.write(result.stdout)
                if result.stderr:
                    log_file.write("\n--- STDERR ---\n")
                    log_file.write(result.stderr)
                log_file.write(f"\n{'='*70}\n")
                log_file.write(f"Data refresh completed at {datetime.now().isoformat()}\n")
                log_file.write(f"Exit code: {result.returncode}\n")
                log_file.write(f"{'='*70}\n\n")
            
            _refresh_status['status'] = 'completed' if result.returncode == 0 else 'failed'
            _refresh_status['completed_at'] = datetime.now().isoformat()
            if result.returncode != 0:
                error_msg = result.stderr[:1000] if result.stderr else (result.stdout[:1000] if result.stdout else 'Unknown error')
                _refresh_status['error'] = error_msg
                logger.error(f"Data refresh failed with exit code {result.returncode}: {error_msg}")
            else:
                logger.info("Data refresh completed successfully")
        except subprocess.TimeoutExpired:
            error_msg = 'Refresh timed out after 1 hour'
            _refresh_status['status'] = 'failed'
            _refresh_status['error'] = error_msg
            _refresh_status['completed_at'] = datetime.now().isoformat()
            logger.error(error_msg)
            with open(LOG_FILE, 'a') as log_file:
                log_file.write(f"\nERROR: {error_msg}\n")
        except Exception as e:
            error_msg = str(e)
            _refresh_status['status'] = 'failed'
            _refresh_status['error'] = error_msg
            _refresh_status['completed_at'] = datetime.now().isoformat()
            logger.exception(f"Exception during data refresh: {error_msg}")
            with open(LOG_FILE, 'a') as log_file:
                log_file.write(f"\nEXCEPTION: {error_msg}\n")
                import traceback
                log_file.write(traceback.format_exc())
    
    # Run in background thread
    thread = threading.Thread(target=run_refresh, daemon=True)
    thread.start()
    
    return jsonify({
        'message': 'Refresh started',
        'status': 'running'
    })


@bp.route('/data-refresh/status', methods=['GET'])
@admin_required
def get_refresh_status():
    """Get current refresh status."""
    return jsonify(_refresh_status)


@bp.route('/data-refresh/logs', methods=['GET'])
@admin_required
def get_refresh_logs():
    """Get data refresh log entries."""
    try:
        limit = request.args.get('limit', 100, type=int)
        
        if not LOG_FILE.exists():
            return jsonify({
                'logs': [],
                'last_refresh': None
            })
        
        # Read log file
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()
        
        # Parse log entries (format: timestamp - LEVEL - message)
        log_entries = []
        last_refresh = None
        
        # Parse from end (most recent first)
        for line in reversed(lines[-limit*2:]):  # Read more lines to account for multi-line entries
            line = line.strip()
            if not line:
                continue
            
            # Match log format: "2025-11-13 10:52:00,858 - INFO - message"
            match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (\w+) - (.+)', line)
            if match:
                timestamp_str, level, message = match.groups()
                # Convert to readable format
                try:
                    dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S,%f')
                    timestamp = dt.strftime('%Y-%m-%d %H:%M:%S')
                    if not last_refresh and level == 'INFO' and 'Starting CSV data update' in message:
                        last_refresh = dt.isoformat()
                except:
                    timestamp = timestamp_str
                
                log_entries.append({
                    'timestamp': timestamp,
                    'level': level,
                    'message': message
                })
        
        # Reverse to show oldest first
        log_entries.reverse()
        
        return jsonify({
            'logs': log_entries[:limit],
            'last_refresh': last_refresh
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/data-refresh/schedule', methods=['GET'])
@admin_required
def get_refresh_schedule():
    """Get current scheduled refresh settings."""
    try:
        settings = settings_manager.load_settings()
        schedule = settings.get('data_refresh', {})
        cron_status = get_cron_status()
        
        # Sync with actual cron job if there's a mismatch
        # Only update settings if cron exists but settings say disabled (cron takes precedence)
        if cron_status['enabled'] and not schedule.get('scheduled_enabled'):
            # Cron exists but settings say disabled - update settings to match cron
            schedule['scheduled_enabled'] = True
            schedule['scheduled_hour'] = cron_status['hour']
            schedule['scheduled_minute'] = cron_status['minute']
            settings['data_refresh'] = schedule
            settings_manager.save_settings(settings)
        # Don't disable settings if cron doesn't exist - user might have just saved it
        # or cron might not be running. Just report the actual status.
        
        return jsonify({
            'enabled': schedule.get('scheduled_enabled', False),
            'hour': schedule.get('scheduled_hour', 6),
            'minute': schedule.get('scheduled_minute', 0),
            'cron_status': cron_status,
            'cron_mismatch': schedule.get('scheduled_enabled', False) and not cron_status['enabled']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/data-refresh/schedule', methods=['POST'])
@admin_required
def set_refresh_schedule():
    """Set scheduled refresh settings."""
    try:
        data = request.get_json()
        enabled = data.get('enabled', False)
        hour = int(data.get('hour', 6))
        minute = int(data.get('minute', 0))
        
        # Validate
        if not (0 <= hour <= 23):
            return jsonify({'error': 'Hour must be between 0 and 23'}), 400
        if not (0 <= minute <= 59):
            return jsonify({'error': 'Minute must be between 0 and 59'}), 400
        
        # Update settings
        settings = settings_manager.load_settings()
        if 'data_refresh' not in settings:
            settings['data_refresh'] = {}
        
        settings['data_refresh']['scheduled_enabled'] = enabled
        settings['data_refresh']['scheduled_hour'] = hour
        settings['data_refresh']['scheduled_minute'] = minute
        
        settings_manager.save_settings(settings)
        
        # Update cron job
        if enabled:
            success, message = create_cron_job(hour, minute)
            if not success:
                return jsonify({'error': message}), 500
        else:
            success, message = remove_cron_job()
            if not success:
                return jsonify({'error': message}), 500
        
        return jsonify({
            'message': message,
            'enabled': enabled,
            'hour': hour,
            'minute': minute
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

