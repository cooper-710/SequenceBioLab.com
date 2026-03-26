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
        series_matched = False
        series_debug = {}
        db = None
        try:
            import logging
            log = logging.getLogger('upload')

            from database import PlayerDB
            db = PlayerDB()

            # Look up user by first + last name
            parts = player_name.strip().split(None, 1)
            first_name = parts[0] if parts else player_name
            last_name = parts[1] if len(parts) > 1 else ''

            cursor = db.conn.cursor()
            if db.is_postgres:
                db._execute(cursor, """
                    SELECT id, team_abbr, team_level FROM users
                    WHERE LOWER(first_name) = LOWER(%s) AND LOWER(last_name) = LOWER(%s)
                """, (first_name, last_name))
            else:
                db._execute(cursor, """
                    SELECT id, team_abbr, team_level FROM users
                    WHERE LOWER(first_name) = LOWER(?) AND LOWER(last_name) = LOWER(?)
                """, (first_name, last_name))
            row = cursor.fetchone()

            if not row:
                log.warning(f"[upload] User not found: '{first_name}' '{last_name}'")
                series_debug['error'] = f"User not found: {first_name} {last_name}"
            else:
                player_id = row['id']
                user_team_abbr = row['team_abbr'] if row['team_abbr'] else None
                user_team_level = (row['team_level'] if row.get('team_level') else None) or "MLB"
                log.info(f"[upload] Found user id={player_id}, team_abbr={user_team_abbr}, team_level={user_team_level}")
                series_debug['player_id'] = player_id
                series_debug['user_team_abbr'] = user_team_abbr

                # --- Series matching ---
                s_opponent = opponent if opponent != 'Unknown' else None
                s_label = None
                s_start = None
                s_end = None

                try:
                    # Convert opponent name to abbreviation
                    team_map = {
                        'Arizona Diamondbacks': 'ARI', 'Atlanta Braves': 'ATL',
                        'Baltimore Orioles': 'BAL', 'Boston Red Sox': 'BOS',
                        'Chicago Cubs': 'CHC', 'Chicago White Sox': 'CWS',
                        'Cincinnati Reds': 'CIN', 'Cleveland Guardians': 'CLE',
                        'Colorado Rockies': 'COL', 'Detroit Tigers': 'DET',
                        'Houston Astros': 'HOU', 'Kansas City Royals': 'KC',
                        'Los Angeles Angels': 'LAA', 'Los Angeles Dodgers': 'LAD',
                        'Miami Marlins': 'MIA', 'Milwaukee Brewers': 'MIL',
                        'Minnesota Twins': 'MIN', 'New York Mets': 'NYM',
                        'New York Yankees': 'NYY', 'Athletics': 'ATH',
                        'Philadelphia Phillies': 'PHI', 'Pittsburgh Pirates': 'PIT',
                        'San Diego Padres': 'SD', 'San Francisco Giants': 'SF',
                        'Seattle Mariners': 'SEA', 'St. Louis Cardinals': 'STL',
                        'Tampa Bay Rays': 'TB', 'Texas Rangers': 'TEX',
                        'Toronto Blue Jays': 'TOR', 'Washington Nationals': 'WSH'
                    }
                    opp_abbr = team_map.get(opponent)
                    if not opp_abbr and opponent:
                        opp_upper = opponent.upper()
                        if opp_upper in team_map.values():
                            opp_abbr = opp_upper
                        else:
                            for name, ab in team_map.items():
                                if opponent.lower() in name.lower():
                                    opp_abbr = ab
                                    break

                    log.info(f"[upload] opponent='{opponent}' -> opp_abbr={opp_abbr}")
                    series_debug['opp_abbr'] = opp_abbr

                    if opp_abbr:
                        s_opponent = opp_abbr

                    if user_team_abbr and (opp_abbr or opponent):
                        from app.services.schedule_service import collect_series_for_team
                        from datetime import datetime, timedelta

                        series_list = collect_series_for_team(user_team_abbr, days_ahead=30, team_level=user_team_level)
                        log.info(f"[upload] collect_series_for_team({user_team_abbr}, team_level={user_team_level}) returned {len(series_list)} series")
                        series_debug['total_series'] = len(series_list)
                        series_debug['all_opponents'] = [(s.get('opponent_abbr'), s.get('opponent_name')) for s in series_list]

                        # Match by abbreviation first, then fall back to opponent name
                        matches = [s for s in series_list if s.get('opponent_abbr') == opp_abbr]
                        if not matches and opponent:
                            # Try matching by opponent name (handles abbreviation mismatches)
                            opp_lower = opponent.lower()
                            matches = [s for s in series_list
                                       if s.get('opponent_name') and opp_lower in s['opponent_name'].lower()]
                        if not matches and opp_abbr:
                            # Try case-insensitive abbreviation match
                            matches = [s for s in series_list
                                       if s.get('opponent_abbr') and s['opponent_abbr'].upper() == opp_abbr.upper()]
                        log.info(f"[upload] Matches for opp_abbr={opp_abbr}, name='{opponent}': {len(matches)}")
                        series_debug['matches_found'] = len(matches)

                        if matches and series_date:
                            try:
                                target = datetime.strptime(series_date, '%Y-%m-%d').date()
                                matches.sort(key=lambda s: abs((datetime.fromisoformat(s['start']).date() - target).days))
                            except Exception:
                                pass

                        if matches:
                            best = matches[0]
                            s_label = best.get('series_label')
                            log.info(f"[upload] Best match: label={s_label}, start={best.get('start')}, end={best.get('end')}")
                            series_debug['matched_series'] = s_label
                            try:
                                s_start = datetime.fromisoformat(best['start']).timestamp()
                                end_dt = datetime.fromisoformat(best['end'])
                                s_end = (end_dt + timedelta(days=1)).timestamp()
                                series_matched = True
                            except Exception as e:
                                log.warning(f"[upload] Failed to parse series dates: {e}")
                        else:
                            log.warning(f"[upload] No series match for {opp_abbr} in schedule")
                    else:
                        log.warning(f"[upload] Skipping series match: team_abbr={user_team_abbr}, opp_abbr={opp_abbr}")
                        series_debug['skip_reason'] = f"team_abbr={user_team_abbr}, opp_abbr={opp_abbr}"
                except Exception as e:
                    log.warning(f"[upload] Series matching exception: {e}")
                    series_debug['exception'] = str(e)

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
                log.info(f"[upload] Created doc id={doc_id}, series_opponent={s_opponent}, series_label={s_label}, s_start={s_start}, s_end={s_end}")

                # Store file in Supabase Storage so it survives Render's ephemeral filesystem
                if doc_id:
                    try:
                        with open(str(filepath), 'rb') as f:
                            pdf_data = f.read()
                        from supabase_storage import upload_file as storage_upload
                        storage_path = storage_upload(int(doc_id), pdf_data, "application/pdf")
                        db.set_document_storage_path(int(doc_id), storage_path)
                        log.info(f"[upload] Stored in Supabase Storage for doc_id={doc_id}, path={storage_path}")
                    except Exception as storage_err:
                        log.warning(f"[upload] Failed to store in Supabase Storage for doc_id={doc_id}: {storage_err}")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Database insert failed: {e}")
            series_debug['db_error'] = str(e)
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

        return jsonify({
            "success": True,
            "message": "Upload successful",
            "filename": filename,
            "player": player_name,
            "opponent": opponent,
            "doc_id": doc_id,
            "series_matched": series_matched,
            "series_debug": series_debug
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
