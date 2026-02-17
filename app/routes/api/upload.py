from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
import os
import hmac
from pathlib import Path

bp = Blueprint('upload', __name__)

# Configure upload settings
UPLOAD_FOLDER = Path(__file__).resolve().parents[3] / "uploads" / "reports"
ALLOWED_EXTENSIONS = {'pdf'}

# API key for upload authentication
UPLOAD_API_KEY = os.environ.get('UPLOAD_API_KEY') or 'oIGnSnzbA9nhIC7aJXp3jQzhV3NHwlfPDOUNbwUhTzCr'

def require_api_key(f):
    """Decorator to require a valid API key for access"""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key', '')
        if not UPLOAD_API_KEY:
            return jsonify({"success": False, "error": "API key not configured on server"}), 500
        if not api_key or not hmac.compare_digest(api_key, UPLOAD_API_KEY):
            return jsonify({"success": False, "error": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@bp.route('/api/upload-report', methods=['POST'])
@require_api_key
def upload_report():
    """Upload a scouting report PDF"""
    try:
        # Check if file is in request
        if 'pdf' not in request.files:
            return jsonify({"success": False, "error": "No file provided"}), 400

        file = request.files['pdf']
        if file.filename == '':
            return jsonify({"success": False, "error": "No file selected"}), 400

        if not allowed_file(file.filename):
            return jsonify({"success": False, "error": "Only PDF files allowed"}), 400

        # Get metadata
        player_name = request.form.get('player_name', 'Unknown')
        opponent = request.form.get('opponent', 'Unknown')
        series_date = request.form.get('series_date', '')

        # Create upload directory if it doesn't exist
        UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

        # Save file
        filename = secure_filename(file.filename)
        filepath = UPLOAD_FOLDER / filename
        file.save(str(filepath))

        # Insert into player_documents database
        doc_id = None
        try:
            from database import PlayerDB
            db = PlayerDB()

            # Look up user by first + last name
            parts = player_name.strip().split(None, 1)
            first_name = parts[0] if parts else player_name
            last_name = parts[1] if len(parts) > 1 else ''

            cursor = db.conn.cursor()
            db._execute(cursor, """
                SELECT id FROM users
                WHERE LOWER(first_name) = LOWER(?) AND LOWER(last_name) = LOWER(?)
            """, (first_name, last_name))
            row = cursor.fetchone()

            if row:
                player_id = row['id']
                doc_id = db.create_player_document(
                    player_id=player_id,
                    filename=filename,
                    path=str(filepath),
                    uploaded_by=None,
                    category='report',
                    series_opponent=opponent if opponent != 'Unknown' else None
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Database insert failed: {e}")
            # Continue anyway - file is saved

        return jsonify({
            "success": True,
            "message": "Upload successful",
            "filename": filename,
            "player": player_name,
            "opponent": opponent,
            "doc_id": doc_id
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
