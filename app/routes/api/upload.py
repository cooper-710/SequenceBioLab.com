from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
import os
import hmac
from pathlib import Path
from datetime import datetime, timedelta, timezone

bp = Blueprint('upload', __name__)

# Configure upload settings
UPLOAD_FOLDER = Path(__file__).resolve().parents[3] / "uploads" / "reports"
ALLOWED_EXTENSIONS = {'pdf'}

# API key for upload authentication
UPLOAD_API_KEY = os.environ.get('UPLOAD_API_KEY') or 'oIGnSnzbA9nhIC7aJXp3jQzhV3NHwlfPDOUNbwUhTzCr'

# Map full team names to abbreviations
TEAM_NAME_TO_ABBR = {
    'Arizona Diamondbacks': 'ARI',
    'Atlanta Braves': 'ATL',
    'Baltimore Orioles': 'BAL',
    'Boston Red Sox': 'BOS',
    'Chicago Cubs': 'CHC',
    'Chicago White Sox': 'CWS',
    'Cincinnati Reds': 'CIN',
    'Cleveland Guardians': 'CLE',
    'Colorado Rockies': 'COL',
    'Detroit Tigers': 'DET',
    'Houston Astros': 'HOU',
    'Kansas City Royals': 'KC',
    'Los Angeles Angels': 'LAA',
    'Los Angeles Dodgers': 'LAD',
    'Miami Marlins': 'MIA',
    'Milwaukee Brewers': 'MIL',
    'Minnesota Twins': 'MIN',
    'New York Mets': 'NYM',
    'New York Yankees': 'NYY',
    'Athletics': 'ATH',
    'Philadelphia Phillies': 'PHI',
    'Pittsburgh Pirates': 'PIT',
    'San Diego Padres': 'SD',
    'San Francisco Giants': 'SF',
    'Seattle Mariners': 'SEA',
    'St. Louis Cardinals': 'STL',
    'Tampa Bay Rays': 'TB',
    'Texas Rangers': 'TEX',
    'Toronto Blue Jays': 'TOR',
    'Washington Nationals': 'WAS'
}

def get_team_abbr_from_name(team_name):
    """Convert full team name to abbreviation. Also handles abbreviations directly."""
    if not team_name:
        return None
    # Check direct mapping first
    abbr = TEAM_NAME_TO_ABBR.get(team_name)
    if abbr:
        return abbr
    # Check if it's already an abbreviation
    if team_name.upper() in TEAM_NAME_TO_ABBR.values():
        return team_name.upper()
    # Try partial match (e.g. "Dodgers" -> "LAD")
    team_lower = team_name.lower()
    for full_name, ab in TEAM_NAME_TO_ABBR.items():
        if team_lower in full_name.lower():
            return ab
    return None

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

def match_series(user_team_abbr, opponent_abbr, series_date_str):
    """
    Match an upload to a series using the schedule service.
    Returns (series_opponent, series_label, series_start_ts, series_end_ts) or Nones.
    """
    try:
        from app.services.schedule_service import collect_series_for_team
    except ImportError:
        return None, None, None, None

    if not user_team_abbr or not opponent_abbr:
        return None, None, None, None

    # Fetch series for the user's team (look 30 days ahead to catch upcoming series)
    series_list = collect_series_for_team(user_team_abbr, days_ahead=30)
    if not series_list:
        return None, None, None, None

    # Parse the provided series date for proximity matching
    target_date = None
    if series_date_str:
        try:
            target_date = datetime.strptime(series_date_str, '%Y-%m-%d').date()
        except ValueError:
            pass

    # Find matching series by opponent abbreviation
    matches = [s for s in series_list if s.get('opponent_abbr') == opponent_abbr]

    if not matches:
        return None, None, None, None

    # If we have a target date, pick the closest series
    if target_date and len(matches) > 1:
        def date_distance(s):
            try:
                s_start = datetime.fromisoformat(s['start']).date()
                return abs((s_start - target_date).days)
            except Exception:
                return 9999
        matches.sort(key=date_distance)

    best = matches[0]

    # Convert start/end to timestamps
    try:
        start_ts = datetime.fromisoformat(best['start']).timestamp()
        end_dt = datetime.fromisoformat(best['end'])
        end_ts = (end_dt + timedelta(days=1)).timestamp()  # end of last game day
    except Exception:
        return opponent_abbr, best.get('series_label'), None, None

    return opponent_abbr, best.get('series_label'), start_ts, end_ts

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
        series_matched = False
        try:
            from database import PlayerDB
            db = PlayerDB()

            # Look up user by first + last name
            parts = player_name.strip().split(None, 1)
            first_name = parts[0] if parts else player_name
            last_name = parts[1] if len(parts) > 1 else ''

            cursor = db.conn.cursor()
            if db.is_postgres:
                db._execute(cursor, """
                    SELECT id, team_abbr FROM users
                    WHERE LOWER(first_name) = LOWER(%s) AND LOWER(last_name) = LOWER(%s)
                """, (first_name, last_name))
            else:
                db._execute(cursor, """
                    SELECT id, team_abbr FROM users
                    WHERE LOWER(first_name) = LOWER(?) AND LOWER(last_name) = LOWER(?)
                """, (first_name, last_name))
            row = cursor.fetchone()

            if row:
                player_id = row['id']
                user_team_abbr = row['team_abbr']

                # Try to match to a series
                opponent_abbr = get_team_abbr_from_name(opponent)
                s_opponent, s_label, s_start, s_end = match_series(
                    user_team_abbr, opponent_abbr, series_date
                )
                series_matched = s_start is not None

                # Read file bytes for DB blob storage (Render filesystem is ephemeral)
                file_data = filepath.read_bytes() if filepath.exists() else None

                doc_id = db.create_player_document(
                    player_id=player_id,
                    filename=filename,
                    path=str(filepath),
                    uploaded_by=None,
                    category='report',
                    series_opponent=s_opponent,
                    series_label=s_label,
                    series_start=s_start,
                    series_end=s_end
                )

                # Store DB-backed blob for durable downloads
                if file_data and doc_id:
                    try:
                        db.upsert_player_document_blob(int(doc_id), "application/pdf", file_data)
                    except Exception:
                        pass

            db.close()
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
            "doc_id": doc_id,
            "series_matched": series_matched
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
