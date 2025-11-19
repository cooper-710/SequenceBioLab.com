"""
Page routes
"""
from flask import Blueprint, render_template, request, session, g, redirect, url_for
from datetime import datetime, timedelta
from urllib.parse import quote_plus
from typing import Optional, List, Dict, Any
from pathlib import Path
import sys

from app.middleware.auth import login_required, admin_required
from app.config import Config
from app.services.page_service import (
    build_player_home_context,
    load_full_season_schedule,
    purge_concluded_series_documents,
    schedule_auto_reports,
    collect_recent_reports,
    attach_reports_to_games,
    format_player_document
)
from app.services.analytics_service import (
    get_team_metadata,
    collect_league_leaders,
    collect_standings_data
)
from app.services.schedule_service import team_abbr_from_id
from app.services.player_service import determine_user_team
from app.utils.helpers import sanitize_filename_component, clean_str
from app.utils.formatters import (
    normalize_journal_visibility,
    prepare_journal_timeline,
    augment_journal_entry,
    format_journal_date
)
from app.middleware.csrf import generate_csrf_token, validate_csrf
from app.constants import DIVISION_OPTIONS, LEAGUE_OPTIONS, JOURNAL_VISIBILITY_OPTIONS, MAX_JOURNAL_TIMELINE_ENTRIES
from app.config import Config
from flask import flash, abort
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import json
import uuid
from app.utils.validators import detect_image_type

bp = Blueprint('pages', __name__)

# Import PlayerDB if available
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
    from database import PlayerDB
except ImportError:
    PlayerDB = None


@bp.route('/')
def home():
    """Landing/home page"""
    viewer_user = getattr(g, "user", None)
    target_user = viewer_user
    admin_user_options: List[Dict[str, Any]] = []
    requested_user_id = request.args.get("user_id", type=int)

    def _format_user_label(record: Optional[Dict[str, Any]]) -> str:
        if not record:
            return "Unknown User"
        first = (record.get("first_name") or "").strip()
        last = (record.get("last_name") or "").strip()
        full_name = f"{first} {last}".strip()
        if full_name:
            return full_name
        email = (record.get("email") or "").strip()
        if email:
            return email
        return f"User #{record.get('id')}"

    if session.get("is_admin") and PlayerDB:
        user_rows: List[Dict[str, Any]] = []
        db = None
        try:
            db = PlayerDB()
            user_rows = db.list_users()
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Warning fetching users for admin home selector: {exc}")
        finally:
            try:
                if db:
                    db.close()
            except Exception:
                pass

        admin_user_options = [
            {"id": row["id"], "label": _format_user_label(row)}
            for row in user_rows
        ]

        if requested_user_id:
            for row in user_rows:
                if row["id"] == requested_user_id:
                    target_user = row
                    break

    context = build_player_home_context(target_user)
    context["admin_user_options"] = admin_user_options
    context["selected_user_id"] = (target_user.get("id") if target_user else None)
    context["selected_user"] = target_user
    return render_template('home.html', **context)


@bp.route('/schedule')
@login_required
def schedule():
    """Full schedule page with month-by-month navigation."""
    viewer_user = getattr(g, "user", None)
    if not viewer_user:
        return redirect(url_for('auth.login'))
    
    target_user = viewer_user
    admin_user_options: List[Dict[str, Any]] = []
    requested_user_id = request.args.get("user_id", type=int)
    
    def _format_user_label(record: Optional[Dict[str, Any]]) -> str:
        if not record:
            return "Unknown User"
        first = (record.get("first_name") or "").strip()
        last = (record.get("last_name") or "").strip()
        full_name = f"{first} {last}".strip()
        if full_name:
            return full_name
        email = (record.get("email") or "").strip()
        if email:
            return email
        return f"User #{record.get('id')}"
    
    if session.get("is_admin") and PlayerDB:
        user_rows: List[Dict[str, Any]] = []
        db = None
        try:
            db = PlayerDB()
            user_rows = db.list_users()
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Warning fetching users for admin schedule selector: {exc}")
        finally:
            try:
                if db:
                    db.close()
            except Exception:
                pass
        
        admin_user_options = [
            {"id": row["id"], "label": _format_user_label(row)}
            for row in user_rows
        ]
        
        if requested_user_id:
            for row in user_rows:
                if row["id"] == requested_user_id:
                    target_user = row
                    break
    
    # Get month/year from query params, default to current month
    month = request.args.get('month', type=int)
    year = request.args.get('year', type=int)
    
    if not month or not year:
        now = datetime.now()
        month = now.month
        year = now.year
    
    # Calculate date range for the month
    start_date = datetime(year, month, 1).date()
    if month == 12:
        end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
    
    # Load games for this month using target_user (selected user for admin)
    games = load_full_season_schedule(
        target_user, 
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat()
    )
    
    # Group games by date and format dates
    games_by_date = {}
    for game in games:
        game_date = game.get("game_date")
        if game_date:
            try:
                dt = datetime.fromisoformat(game_date)
                date_key = dt.strftime("%Y-%m-%d")
                if date_key not in games_by_date:
                    games_by_date[date_key] = {
                        "date_obj": dt,
                        "day_name": dt.strftime("%A"),
                        "date_formatted": dt.strftime("%B %d, %Y"),
                        "games": []
                    }
                
                # Format game time if available
                formatted_game = dict(game)
                if game.get("game_datetime"):
                    try:
                        game_dt = datetime.fromisoformat(game["game_datetime"].replace('Z', '+00:00'))
                        formatted_game["time_formatted"] = game_dt.strftime("%I:%M %p")
                    except Exception:
                        formatted_game["time_formatted"] = "TBD"
                else:
                    formatted_game["time_formatted"] = "TBD"
                
                games_by_date[date_key]["games"].append(formatted_game)
            except Exception:
                continue
    
    # Calculate previous/next month
    if month == 1:
        prev_month = 12
        prev_year = year - 1
    else:
        prev_month = month - 1
        prev_year = year
    
    if month == 12:
        next_month = 1
        next_year = year + 1
    else:
        next_month = month + 1
        next_year = year
    
    # Get all months with games for quick navigation
    all_games = load_full_season_schedule(target_user)
    months_with_games = set()
    for game in all_games:
        game_date = game.get("game_date")
        if game_date:
            try:
                dt = datetime.fromisoformat(game_date)
                months_with_games.add((dt.year, dt.month))
            except Exception:
                continue
    
    # Add current month if no games found (so user can still navigate)
    months_with_games.add((year, month))
    
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    
    return render_template(
        'schedule.html',
        games_by_date=games_by_date,
        current_month=month,
        current_year=year,
        month_name=month_names[month - 1],
        prev_month=prev_month,
        prev_year=prev_year,
        next_month=next_month,
        next_year=next_year,
        months_with_games=months_with_games,
        month_names=month_names,
        admin_user_options=admin_user_options,
        selected_user_id=(target_user.get("id") if target_user else None)
    )


@bp.route('/live-scores')
@login_required
def live_scores():
    """Live scores page showing current game scores"""
    viewer_user = getattr(g, "user", None)
    if not viewer_user:
        return redirect(url_for('auth.login'))
    
    from app.services.live_scores_service import get_games_for_date
    
    # Get date from query parameter, default to today
    date_str = request.args.get('date')
    target_date = datetime.now().date()
    
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            # Invalid date format, use today
            target_date = datetime.now().date()
    
    try:
        games = get_games_for_date(target_date)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Error fetching live scores: {e}")
        games = []
    
    # Count live games
    live_games_count = sum(1 for game in games if game.get('is_live'))
    
    # Calculate previous/next dates
    prev_date = target_date - timedelta(days=1)
    next_date = target_date + timedelta(days=1)
    today = datetime.now().date()
    
    # Format dates for display
    date_display = target_date.strftime("%A, %B %d, %Y")
    prev_date_display = prev_date.strftime("%b %d")
    next_date_display = next_date.strftime("%b %d")
    is_today = target_date == today
    
    return render_template(
        'live_scores.html',
        games=games,
        live_games_count=live_games_count,
        has_games=len(games) > 0,
        target_date=target_date,
        target_date_str=target_date.isoformat(),
        prev_date_str=prev_date.isoformat(),
        next_date_str=next_date.isoformat(),
        prev_date_display=prev_date_display,
        next_date_display=next_date_display,
        date_display=date_display,
        is_today=is_today
    )


@bp.route('/live-scores/box-score/<int:game_pk>')
@login_required
def box_score(game_pk):
    """Custom box score page for a specific game"""
    viewer_user = getattr(g, "user", None)
    if not viewer_user:
        return redirect(url_for('auth.login'))
    
    from app.services.box_score_service import get_box_score
    from app.services.schedule_service import team_abbr_from_id
    
    try:
        box_score_data = get_box_score(game_pk)
        
        if not box_score_data:
            flash("Box score not available for this game.", "error")
            return redirect(url_for('pages.live_scores'))
        
        # Get team abbreviations for logos
        away_abbr = team_abbr_from_id(box_score_data.get('away_id'))
        home_abbr = team_abbr_from_id(box_score_data.get('home_id'))
        
        box_score_data['away_abbr'] = away_abbr
        box_score_data['home_abbr'] = home_abbr
        
        # Format inning scores
        innings_list = []
        away_innings = []
        home_innings = []
        
        innings_data = box_score_data.get('innings', [])
        
        # Sort innings by number
        sorted_innings = sorted(innings_data, key=lambda x: x.get('num', 0))
        
        for inning in sorted_innings:
            inning_num = inning.get('num', 0)
            away_runs = inning.get('away', {}).get('runs', 0) or 0
            home_runs = inning.get('home', {}).get('runs', 0) or 0
            
            # Convert to int if needed
            try:
                away_runs = int(away_runs)
                home_runs = int(home_runs)
            except (ValueError, TypeError):
                away_runs = 0
                home_runs = 0
            
            away_innings.append(away_runs if away_runs > 0 else 0)
            home_innings.append(home_runs if home_runs > 0 else 0)
            innings_list.append(inning_num)
        
        # Ensure we show at least 9 innings (or more for extra innings)
        max_inning = max(innings_list) if innings_list else 9
        if max_inning < 9:
            max_inning = 9
        
        # Fill in missing innings with 0's
        for i in range(1, max_inning + 1):
            if i not in innings_list:
                innings_list.append(i)
                away_innings.append(0)
                home_innings.append(0)
        
        # Sort again to ensure proper order
        sorted_data = sorted(zip(innings_list, away_innings, home_innings), key=lambda x: x[0])
        innings_list = [x[0] for x in sorted_data]
        away_innings = [x[1] for x in sorted_data]
        home_innings = [x[2] for x in sorted_data]
        
        box_score_data['innings_list'] = innings_list
        box_score_data['away_innings'] = away_innings
        box_score_data['home_innings'] = home_innings
        
        return render_template('box_score.html', **box_score_data)
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error loading box score: {e}")
        flash("Error loading box score. Please try again.", "error")
        return redirect(url_for('pages.live_scores'))


@bp.route('/gameday')
@login_required
def gameday():
    """Daily hub for schedule, reports, notes, and standings."""
    viewer_user = getattr(g, "user", None)
    target_user = viewer_user
    admin_user_options: List[Dict[str, Any]] = []
    requested_user_id = request.args.get("user_id", type=int)

    def _format_user_label(record: Optional[Dict[str, Any]]) -> str:
        if not record:
            return "Unknown User"
        first = (record.get("first_name") or "").strip()
        last = (record.get("last_name") or "").strip()
        full_name = f"{first} {last}".strip()
        if full_name:
            return full_name
        email = (record.get("email") or "").strip()
        if email:
            return email
        return f"User #{record.get('id')}"

    if session.get("is_admin") and PlayerDB:
        user_rows: List[Dict[str, Any]] = []
        db = None
        try:
            db = PlayerDB()
            user_rows = db.list_users()
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Warning fetching users for admin gameday selector: {exc}")
        finally:
            try:
                if db:
                    db.close()
            except Exception:
                pass

        admin_user_options = [
            {"id": row["id"], "label": _format_user_label(row)}
            for row in user_rows
        ]

        if requested_user_id:
            for row in user_rows:
                if row["id"] == requested_user_id:
                    target_user = row
                    break

        if target_user is None and viewer_user is not None:
            target_user = viewer_user
        elif target_user is None and user_rows:
            target_user = user_rows[0]
    else:
        requested_user_id = None

    team_abbr = determine_user_team(target_user)
    team_metadata = get_team_metadata(team_abbr)

    purge_concluded_series_documents()

    # Get date parameter if provided (from calendar click)
    requested_date = request.args.get("date")
    
    # Always load full season schedule (365 days) to support date filtering and series display
    raw_games = None
    from datetime import date as date_type
    today = date_type.today()
    end_date = today + timedelta(days=365)
    
    try:
        raw_games = load_full_season_schedule(
            target_user,
            start_date=today.isoformat(),
            end_date=end_date.isoformat()
        )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Warning loading games from load_full_season_schedule: {e}")
        raw_games = []
    
    # Group games into series and format for display
    upcoming_games = []
    if raw_games and len(raw_games) > 0:
        # Format the games and group into series
        from datetime import date as date_type
        today = date_type.today()
        
        # Group games into series (consecutive games against same opponent)
        series_groups = []
        current_series = None
        last_opponent_id = None
        last_game_date = None
        
        # Sort games by date first
        sorted_games = sorted(raw_games, key=lambda g: g.get("game_date", ""))
        
        for game in sorted_games:
            date_str = game.get("game_date") or game.get("game_date_iso") or game.get("date")
            if not date_str:
                continue
                
            try:
                if isinstance(date_str, str):
                    game_date = datetime.fromisoformat(date_str.split('T')[0] if 'T' in date_str else date_str).date()
                else:
                    game_date = date_str if isinstance(date_str, date_type) else datetime.combine(date_str, datetime.min.time()).date()
            except Exception:
                continue
            
            opponent_id = game.get("opponent_id")
            
            # Start new series if opponent changes or gap > 1 day
            if (last_opponent_id is not None and 
                (opponent_id != last_opponent_id or 
                 (last_game_date and (game_date - last_game_date).days > 1))):
                if current_series:
                    series_groups.append(current_series)
                current_series = None
            
            if not current_series:
                current_series = {
                    "opponent_id": opponent_id,
                    "opponent_name": game.get("opponent_name") or game.get("opponent"),
                    "opponent_abbr": game.get("opponent_abbr"),
                    "games": [],
                    "start_date": game_date,
                    "end_date": game_date,
                }
            
            current_series["games"].append(game)
            current_series["end_date"] = max(current_series["end_date"], game_date)
            last_opponent_id = opponent_id
            last_game_date = game_date
        
        if current_series:
            series_groups.append(current_series)
        
        # Sort series by start date
        series_groups.sort(key=lambda s: s["start_date"])
        
        # Find the next upcoming series (first future series) to mark as "current" if no actual current series
        next_upcoming_series_key = None
        has_current_series = False
        for series in series_groups:
            if not series["games"]:
                continue
            series_start = series["start_date"]
            series_end = series["end_date"]
            if series_start <= today <= series_end:
                has_current_series = True
                break
            elif series_start > today and next_upcoming_series_key is None:
                # Store a unique key for the next upcoming series
                next_upcoming_series_key = (series["opponent_id"], series["start_date"])
        
        # Format series for display
        formatted = []
        for series in series_groups:
            if not series["games"]:
                continue
                
            first_game = series["games"][0]
            series_start = series["start_date"]
            series_end = series["end_date"]
            
            # Determine category (past, current, future)
            if series_end < today:
                category = "past"
            elif series_start <= today <= series_end:
                category = "current"
            elif not has_current_series and next_upcoming_series_key and (series["opponent_id"], series["start_date"]) == next_upcoming_series_key:
                # If no actual current series, mark the next upcoming as "current" for display
                category = "current"
            else:
                category = "future"
            
            # Format date
            if series_start == series_end:
                display_date = series_start.strftime("%a, %b %d")
            else:
                display_date = f"{series_start.strftime('%a, %b %d')} - {series_end.strftime('%b %d')}"
            
            game_time = first_game.get("game_datetime")
            display_time = "TBD"
            if game_time:
                try:
                    display_time = datetime.fromisoformat(game_time.replace("Z", "+00:00")).astimezone().strftime("%I:%M %p %Z")
                except Exception:
                    display_time = "TBD"
            
            team_abbr_code = team_abbr_from_id(series["opponent_id"])
            series_label = f"{len(series['games'])}-game series" if len(series["games"]) > 1 else "Single game"
            
            # Get status from first game
            status = first_game.get("status", "Scheduled")
            
            # Handle probable_pitchers
            probables_raw = first_game.get("probable_pitchers") or []
            probables = []
            for p in probables_raw:
                if isinstance(p, dict):
                    name = p.get("name")
                    if name:
                        probables.append(name)
                elif isinstance(p, str):
                    probables.append(p)
            
            formatted.append({
                "date": display_date,
                "time": display_time,
                "opponent": series["opponent_name"],
                "opponent_abbr": team_abbr_code,
                "opponent_id": series["opponent_id"],
                "home": first_game.get("is_home"),
                "venue": first_game.get("venue"),
                "series": series_label,
                "status": status,
                "game_pk": first_game.get("game_pk"),
                "probable_pitchers": probables,
                "reports": [],
                "category": category,  # Add category for JavaScript filtering
            })
        
        # formatted is already in the correct order (same as sorted series_groups)
        upcoming_games = formatted
    
    schedule_auto_reports(upcoming_games, team_abbr)

    player_slug = None
    if target_user and target_user.get("first_name") and target_user.get("last_name"):
        player_slug = sanitize_filename_component(
            f"{target_user['first_name']} {target_user['last_name']}"
        ).lower().replace(" ", "_")

    recent_reports = []
    for report in collect_recent_reports(limit=25):
        filename = report.get("filename") or ""
        if player_slug and player_slug not in filename.lower():
            continue
        try:
            recent_reports.append({
                **report,
                "url": url_for("reports.download_report_file", filename=filename)
            })
        except Exception:
            recent_reports.append({
                **report,
                "url": f"/reports/files/{filename}"
            })

    upcoming_games = attach_reports_to_games(upcoming_games, recent_reports)
    league_leader_groups = collect_league_leaders()

    player_documents = []
    document_log = []
    if PlayerDB and target_user and target_user.get("id"):
        db = None
        try:
            db = PlayerDB()
            user_docs = db.list_player_documents(target_user.get("id"))
            player_documents = [format_player_document(doc) for doc in user_docs]
            events = db.list_player_document_events(player_id=target_user.get("id"), limit=20)
            document_log = [
                {
                    "filename": evt.get("filename"),
                    "action": evt.get("action"),
                    "performed_by": evt.get("performed_by"),
                    "timestamp": evt.get("timestamp"),
                    "timestamp_human": datetime.fromtimestamp(evt["timestamp"]).strftime("%b %d, %Y %I:%M %p")
                    if evt.get("timestamp") else None,
                }
                for evt in events
            ]
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Warning fetching player documents: {exc}")
        finally:
            try:
                if db:
                    db.close()
            except Exception:
                pass

    standings_view = request.args.get('standings_view', 'division').lower()
    if standings_view not in {"division", "wildcard"}:
        standings_view = "division"

    requested_division_id = request.args.get('division_id', type=int)
    requested_league_id = request.args.get('league_id', type=int)

    standings_data = collect_standings_data(
        standings_view,
        team_metadata,
        division_id=requested_division_id,
        league_id=requested_league_id
    )

    selected_division_id = None
    selected_league_id = None
    if standings_data:
        selected_division_id = standings_data.get("division_id")
        selected_league_id = standings_data.get("league_id")
    else:
        selected_division_id = requested_division_id or (team_metadata or {}).get("division_id")
        selected_league_id = requested_league_id or (team_metadata or {}).get("league_id")

    if not selected_division_id and standings_view == "division":
        selected_division_id = (team_metadata or {}).get("division_id") or DIVISION_OPTIONS[0]["id"]

    if not selected_league_id:
        selected_league_id = (team_metadata or {}).get("league_id") or LEAGUE_OPTIONS[0]["id"]

    # Check if requested_date doesn't match any displayed series (i.e., is beyond the upcoming series)
    show_date_redirect_note = False
    requested_tab = None  # Will be "past", "current", or "future" if a date was requested
    if requested_date:
        try:
            from datetime import date as date_type
            today = date_type.today()
            filter_date = datetime.fromisoformat(requested_date).date()
            
            # Load full season schedule to check what series are actually displayed
            # (The displayed series are: one past, one current, one upcoming)
            full_schedule_games = load_full_season_schedule(
                target_user,
                start_date=today.isoformat(),
                end_date=(today + timedelta(days=365)).isoformat()
            )
            
            if full_schedule_games:
                # Group into series to find which ones are displayed
                all_series_groups = []
                current_series = None
                last_opponent_id = None
                last_game_date = None
                
                sorted_games = sorted(full_schedule_games, key=lambda g: g.get("game_date", ""))
                for game in sorted_games:
                    date_str = game.get("game_date") or game.get("game_date_iso") or game.get("date")
                    if not date_str:
                        continue
                    try:
                        if isinstance(date_str, str):
                            game_date = datetime.fromisoformat(date_str.split('T')[0] if 'T' in date_str else date_str).date()
                        else:
                            game_date = date_str if isinstance(date_str, date_type) else datetime.combine(date_str, datetime.min.time()).date()
                    except Exception:
                        continue
                    
                    opponent_id = game.get("opponent_id")
                    if (last_opponent_id is not None and 
                        (opponent_id != last_opponent_id or 
                         (last_game_date and (game_date - last_game_date).days > 1))):
                        if current_series:
                            all_series_groups.append(current_series)
                        current_series = None
                    
                    if not current_series:
                        current_series = {
                            "opponent_id": opponent_id,
                            "start_date": game_date,
                            "end_date": game_date,
                        }
                    current_series["end_date"] = max(current_series["end_date"], game_date)
                    last_opponent_id = opponent_id
                    last_game_date = game_date
                
                if current_series:
                    all_series_groups.append(current_series)
                
                # Find displayed series (one past, one current, one upcoming)
                past_series = []
                current_series_list = []
                upcoming_series_list = []
                
                for series in all_series_groups:
                    series_start = series["start_date"]
                    series_end = series["end_date"]
                    if series_end < today:
                        past_series.append(series)
                    elif series_start <= today <= series_end:
                        current_series_list.append(series)
                    else:
                        upcoming_series_list.append(series)
                
                past_series.sort(key=lambda s: s["start_date"], reverse=True)
                upcoming_series_list.sort(key=lambda s: s["start_date"])
                
                # Get the latest date from displayed series (matching gameday hub logic)
                displayed_series = []
                if past_series:
                    displayed_series.append(past_series[0])
                if current_series_list:
                    displayed_series.append(current_series_list[0])
                    if upcoming_series_list:
                        displayed_series.append(upcoming_series_list[0])
                elif upcoming_series_list:
                    displayed_series.append(upcoming_series_list[0])
                    if len(upcoming_series_list) > 1:
                        displayed_series.append(upcoming_series_list[1])
                
                # Check if requested date is in any displayed series and determine which tab
                date_in_displayed = False
                for series in displayed_series:
                    if series["start_date"] <= filter_date <= series["end_date"]:
                        date_in_displayed = True
                        # Determine which tab this series belongs to by comparing series identifiers
                        # (opponent_id and start_date) since object identity won't work
                        series_key = (series["opponent_id"], series["start_date"])
                        
                        # Check past series
                        if past_series and (past_series[0]["opponent_id"], past_series[0]["start_date"]) == series_key:
                            requested_tab = "past"
                        # Check current series
                        elif current_series_list and (current_series_list[0]["opponent_id"], current_series_list[0]["start_date"]) == series_key:
                            requested_tab = "current"
                        # Check upcoming series
                        elif upcoming_series_list:
                            # Check first upcoming (which might be shown as "current" if no actual current)
                            if (upcoming_series_list[0]["opponent_id"], upcoming_series_list[0]["start_date"]) == series_key:
                                # If there's no current series, first upcoming is shown as "current"
                                if not current_series_list:
                                    requested_tab = "current"
                                else:
                                    requested_tab = "future"
                            # Check second upcoming if it exists
                            elif len(upcoming_series_list) > 1 and (upcoming_series_list[1]["opponent_id"], upcoming_series_list[1]["start_date"]) == series_key:
                                requested_tab = "future"
                        break
                
                # If date is not in displayed series and is after the latest displayed series, show note
                if not date_in_displayed and displayed_series:
                    latest_displayed_date = max(s["end_date"] for s in displayed_series)
                    if filter_date > latest_displayed_date:
                        show_date_redirect_note = True
                        requested_tab = None  # Don't switch tabs if showing note
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error checking date redirect note: {e}")
            pass  # If date parsing fails, don't show note

    return render_template(
        'gameday.html',
        team_abbr=team_abbr,
        upcoming_games=upcoming_games,
        league_leader_groups=league_leader_groups,
        player_documents=player_documents,
        document_log=document_log,
        standings_data=standings_data,
        standings_view=standings_view,
        division_options=DIVISION_OPTIONS,
        league_options=LEAGUE_OPTIONS,
        selected_division_id=selected_division_id,
        selected_league_id=selected_league_id,
        admin_user_options=admin_user_options,
        selected_user_id=(target_user.get("id") if target_user else None),
        target_user_label=_format_user_label(target_user),
        viewer_user=viewer_user,
        show_date_redirect_note=show_date_redirect_note,
        default_schedule_tab=requested_tab or "current",
    )


# Simple template-only routes that don't need helper functions
@bp.route('/scouting-report')
def scouting_report():
    """Scouting report generator page"""
    return render_template('scouting_report.html')


@bp.route('/pitchers-report')
def pitchers_report():
    """Pitcher's reports page"""
    return render_template('pitchers_report.html')


@bp.route('/mocap')
@login_required
def mocap():
    """Mocap analysis page"""
    is_admin = session.get('is_admin', False)
    
    if is_admin:
        base_url = "https://cooper-710.github.io/motion-webapp"
        mode = "admin"
    else:
        base_url = "https://motion-webapp.pages.dev"
        mode = "player"
    
    player_name = request.args.get('player')
    if not player_name:
        user = getattr(g, "user", None)
        if user and user.get('first_name') and user.get('last_name'):
            player_name = f"{user['first_name']} {user['last_name']}"
        elif session.get('first_name') and session.get('last_name'):
            player_name = f"{session['first_name']} {session['last_name']}"
        else:
            player_name = "Pete Alonso"
    
    encoded_player_name = quote_plus(player_name)
    session_date = request.args.get('session', '2025-08-27')
    
    if is_admin:
        motion_app_url = f"{base_url}/?mode={mode}&player={encoded_player_name}&session={session_date}"
    else:
        motion_app_url = f"{base_url}/?mode={mode}&player={encoded_player_name}&session={session_date}&lock=1"
    
    return render_template('mocap.html', motion_app_url=motion_app_url)


@bp.route('/pitchviz')
def pitchviz():
    """PitchViz visualization page"""
    base_url = "https://cooper-710.github.io/NEWPV-main_with_orbit/"
    team = request.args.get('team', 'ARI')
    pitcher = request.args.get('pitcher', 'Backhus, Kyle')
    view = request.args.get('view', 'catcher')
    trail = request.args.get('trail', '0')
    orbit = request.args.get('orbit', '1')
    encoded_pitcher = quote_plus(pitcher)
    pitchviz_url = f"{base_url}?team={team}&pitcher={encoded_pitcher}&view={view}&trail={trail}&orbit={orbit}"
    return render_template('pitchviz.html', pitchviz_url=pitchviz_url)


@bp.route('/contractviz')
def contractviz():
    """ContractViz analysis page"""
    base_url = "https://contract-viz.vercel.app/"
    contractviz_url = base_url
    return render_template('contractviz.html', contractviz_url=contractviz_url)


@bp.route('/admin')
@admin_required
def admin_dashboard():
    """Render the admin control center."""
    return render_template('admin.html')


@bp.route('/admin/data-refresh')
@admin_required
def data_refresh():
    """Render the data refresh page."""
    return render_template('data_refresh.html')


@bp.route('/player-database')
def player_database():
    """Player database page"""
    return render_template('player_database.html')


@bp.route('/player/<player_id>')
def player_profile(player_id):
    """Player profile page"""
    return render_template('player_profile.html', player_id=player_id)


@bp.route('/visuals')
def visuals():
    """Visuals page"""
    return render_template('visuals.html')


@bp.route('/heatmaps')
def heatmaps():
    """Heatmaps visualization page"""
    return render_template('heatmaps.html')


@bp.route('/spraychart')
def spraychart():
    """Spray chart visualization page"""
    return render_template('spraychart.html')


@bp.route('/timeline')
def timeline():
    """Performance Timeline visualization page"""
    return render_template('timeline.html')


@bp.route('/pitchplots')
def pitchplots():
    """Pitch Plots visualization page"""
    return render_template('pitchplots.html')


@bp.route('/velocity_trends')
def velocity_trends():
    """Velocity Trends visualization page"""
    return render_template('velocity_trends.html')


@bp.route('/pitch-mix-analysis')
def pitch_mix_analysis():
    """Pitch Mix Analysis visualization page"""
    return render_template('pitch_mix_analysis.html')


@bp.route('/count-performance')
def count_performance():
    """Count Performance Breakdown visualization page"""
    return render_template('count_performance.html')


@bp.route('/zone-contact-rates')
def zone_contact_rates():
    """Zone Contact Rates visualization page"""
    return render_template('zone_contact_rates.html')


@bp.route('/plate-discipline-matrix')
def plate_discipline_matrix():
    """Plate Discipline Matrix visualization page"""
    return render_template('plate_discipline_matrix.html')


@bp.route('/expected-stats-comparison')
def expected_stats_comparison():
    """Expected Stats Comparison visualization page"""
    return render_template('expected_stats_comparison.html')


@bp.route('/pitch-tunnel')
def pitch_tunnel():
    """Pitch Tunnel Analysis visualization page"""
    return render_template('pitch_tunnel.html')


@bp.route('/barrel-quality-contact')
def barrel_quality_contact():
    """Barrel Rate & Quality of Contact visualization page"""
    return render_template('barrel_quality_contact.html')


@bp.route('/swing-decision-matrix')
def swing_decision_matrix():
    """Swing Decision Matrix visualization page"""
    return render_template('swing_decision_matrix.html')


@bp.route('/pitch-arsenal-effectiveness')
def pitch_arsenal_effectiveness():
    """Pitch Arsenal Effectiveness visualization page"""
    return render_template('pitch_arsenal_effectiveness.html')


@bp.route('/matchups')
@login_required
def matchups():
    """Player matchup page - view historical performance against specific opponents"""
    viewer_user = getattr(g, "user", None)
    if not viewer_user:
        return redirect(url_for('auth.login'))
    
    # Get player's name for default display
    first_name = (viewer_user.get("first_name") or "").strip()
    last_name = (viewer_user.get("last_name") or "").strip()
    player_name = f"{first_name} {last_name}".strip() if first_name or last_name else None
    
    from datetime import datetime
    current_year = datetime.now().year
    
    return render_template(
        'matchups.html',
        player_name=player_name,
        current_user_id=viewer_user.get("id"),
        current_year=current_year
    )


@bp.route('/game-analysis')
def game_analysis():
    """Game analysis page"""
    return render_template('game_analysis.html')


@bp.route('/reports-library')
def reports_library():
    """Reports library page"""
    return render_template('reports_library.html')


@bp.route('/workouts')
@login_required
def workouts():
    """Workouts page with admin/player modes."""
    viewer_user = getattr(g, "user", None)
    current_user_id = viewer_user.get("id") if viewer_user else None
    workout_document = None
    if PlayerDB and current_user_id:
        db = None
        try:
            db = PlayerDB()
            latest = db.get_latest_player_document_by_category(current_user_id, Config.WORKOUT_CATEGORY)
            if latest:
                workout_document = format_player_document(latest)
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Warning: unable to load workout document: {exc}")
        finally:
            if db:
                db.close()

    first_name = (viewer_user or {}).get("first_name") or ""
    last_name = (viewer_user or {}).get("last_name") or ""
    name_parts = [part for part in (first_name.strip(), last_name.strip()) if part]
    initial_player_label = " ".join(name_parts) if name_parts else ((viewer_user or {}).get("email") or "Player")

    is_admin = bool(session.get("is_admin"))
    initial_player_id = None if is_admin else current_user_id
    if is_admin:
        workout_document = None

    from app.middleware.csrf import generate_csrf_token

    return render_template(
        'workouts.html',
        workout_document=workout_document,
        csrf_token=generate_csrf_token(),
        workout_category=Config.WORKOUT_CATEGORY,
        initial_player_id=initial_player_id,
        initial_player_label=initial_player_label if initial_player_id else "",
        current_user_id=current_user_id,
        current_user_label=initial_player_label,
    )


@bp.route('/nutrition')
@login_required
def nutrition():
    """Nutrition placeholder page"""
    return render_template('nutrition.html')


@bp.route('/journaling', methods=['GET', 'POST'])
@login_required
def journaling():
    """Personal journaling workspace for players."""
    viewer_user = getattr(g, "user", None)
    if not viewer_user:
        abort(403)

    today_iso = datetime.now().strftime("%Y-%m-%d")
    selected_visibility = normalize_journal_visibility(
        request.values.get("visibility") if request.method == "GET" else request.form.get("visibility"),
        default="private",
    )
    selected_date_raw = request.values.get("date") if request.method == "GET" else request.form.get("entry_date")
    if not selected_date_raw:
        selected_date_raw = today_iso
    # Check if we should reset the form (after saving)
    should_reset_form = request.values.get("reset") == "1"

    entry_errors: List[str] = []
    just_saved = False

    if request.method == "POST":
        if not validate_csrf(request.form.get("csrf_token")):
            abort(400, description="Invalid CSRF token")

        entry_date = (request.form.get("entry_date") or "").strip()
        visibility_choice = normalize_journal_visibility(request.form.get("visibility"), default="private")
        title = (request.form.get("title") or "").strip()
        body = request.form.get("body") or ""

        if not entry_date:
            entry_errors.append("Entry date is required.")

        try:
            datetime.strptime(entry_date, "%Y-%m-%d")
        except ValueError:
            entry_errors.append("Entry date must be in YYYY-MM-DD format.")

        if PlayerDB is None:
            entry_errors.append("Database is unavailable. Please try again later.")

        if not entry_errors and PlayerDB:
            db = None
            try:
                db = PlayerDB()
                db.upsert_journal_entry(
                    user_id=viewer_user["id"],
                    entry_date=entry_date,
                    visibility=visibility_choice,
                    title=title,
                    body=body,
                )
                flash("Journal entry saved.", "success")
                just_saved = True
                # Redirect to today to reset form for new entry
                # The saved entry will appear in the timeline automatically
                # Use 'reset=1' parameter to indicate we should show blank form
                return redirect(url_for(
                    "pages.journaling",
                    date=today_iso,
                    visibility=visibility_choice,
                    reset=1,
                ))
            except ValueError as exc:
                entry_errors.append(str(exc))
            except Exception as exc:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Warning: failed to save journal entry: {exc}")
                entry_errors.append("An unexpected error occurred while saving.")
            finally:
                if db:
                    db.close()

        selected_date_raw = entry_date or selected_date_raw
        selected_visibility = visibility_choice

    timeline_entries: List[Dict[str, Any]] = []
    current_entry: Optional[Dict[str, Any]] = None

    if PlayerDB:
        db = None
        try:
            db = PlayerDB()
            entries = db.list_journal_entries(
                user_id=viewer_user["id"],
                limit=MAX_JOURNAL_TIMELINE_ENTRIES,
            )
            timeline_entries = prepare_journal_timeline(entries)

            # Ensure the selected date corresponds to an existing entry if possible
            # But skip this if we're resetting the form after save
            if not should_reset_form:
                known_dates = {item["date"] for item in timeline_entries}
                if selected_date_raw not in known_dates and timeline_entries:
                    selected_date_raw = timeline_entries[0]["date"]

            # Don't load entry if we're resetting the form (after saving)
            if should_reset_form:
                current_entry = None
            else:
                current_entry = db.get_journal_entry(
                    user_id=viewer_user["id"],
                    entry_date=selected_date_raw,
                    visibility=selected_visibility,
                )
                current_entry = augment_journal_entry(current_entry)
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Warning: unable to load journal entries: {exc}")
            timeline_entries = []
            current_entry = None
        finally:
            if db:
                db.close()
    else:
        flash("Journal features are temporarily unavailable.", "warning")

    return render_template(
        'journaling.html',
        selected_date=selected_date_raw,
        selected_visibility=selected_visibility,
        entry=current_entry,
        timeline_entries=timeline_entries,
        entry_errors=entry_errors,
        just_saved=just_saved,
        journal_visibility_options=JOURNAL_VISIBILITY_OPTIONS,
        today=today_iso,
        today_display=format_journal_date(today_iso),
        is_admin_view=False,
        target_user=viewer_user,
        selected_date_display=format_journal_date(selected_date_raw),
    )


@bp.route('/journaling/admin')
@login_required
def journaling_admin():
    """Admin view of public journal entries."""
    if not session.get("is_admin"):
        abort(403)

    viewer_user = getattr(g, "user", None)
    today_iso = datetime.now().strftime("%Y-%m-%d")
    selected_user_id = request.args.get("user_id", type=int)
    selected_date_raw = request.args.get("date")

    user_options: List[Dict[str, Any]] = []
    target_user: Optional[Dict[str, Any]] = None
    timeline_entries: List[Dict[str, Any]] = []
    current_entry: Optional[Dict[str, Any]] = None

    def _format_user_label(record: Dict[str, Any]) -> str:
        first = (record.get("first_name") or "").strip()
        last = (record.get("last_name") or "").strip()
        if first or last:
            return f"{first} {last}".strip()
        return (record.get("email") or f"User #{record.get('id')}").strip()

    if PlayerDB:
        db = None
        try:
            db = PlayerDB()
            user_records = db.list_users()
            user_options = [
                {"id": record["id"], "label": _format_user_label(record)}
                for record in user_records
            ]
            if selected_user_id:
                target_user = db.get_user_by_id(selected_user_id)
            if not target_user and user_records:
                target_user = user_records[0]

            if target_user:
                entries = db.list_journal_entries(
                    user_id=target_user["id"],
                    visibility="public",
                    limit=MAX_JOURNAL_TIMELINE_ENTRIES,
                )
                timeline_entries = prepare_journal_timeline(entries)
                known_dates = {item["date"] for item in timeline_entries}
                if not selected_date_raw and timeline_entries:
                    selected_date_raw = timeline_entries[0]["date"]
                elif selected_date_raw not in known_dates:
                    selected_date_raw = timeline_entries[0]["date"] if timeline_entries else selected_date_raw

                if selected_date_raw:
                    current_entry = db.get_journal_entry(
                        user_id=target_user["id"],
                        entry_date=selected_date_raw,
                        visibility="public",
                    )
                    current_entry = augment_journal_entry(current_entry)
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Warning: admin journal view error: {exc}")
            timeline_entries = []
            current_entry = None
        finally:
            if db:
                db.close()
    else:
        flash("Journal features are temporarily unavailable.", "warning")

    return render_template(
        'journaling.html',
        selected_date=selected_date_raw,
        selected_visibility="public",
        entry=current_entry,
        timeline_entries=timeline_entries,
        entry_errors=[],
        just_saved=False,
        journal_visibility_options=JOURNAL_VISIBILITY_OPTIONS,
        today=today_iso,
        today_display=format_journal_date(today_iso),
        is_admin_view=True,
        target_user=target_user,
        admin_user_options=user_options,
        viewer_user=viewer_user,
        selected_date_display=format_journal_date(selected_date_raw),
    )


@bp.route('/journaling/delete', methods=['POST'])
@login_required
def delete_journal_entry():
    """Delete a journal entry belonging to the current user."""
    viewer_user = getattr(g, "user", None)
    if not viewer_user:
        abort(403)

    if not validate_csrf(request.form.get("csrf_token")):
        abort(400, description="Invalid CSRF token")

    entry_id = request.form.get("entry_id", type=int)
    entry_date = (request.form.get("entry_date") or "").strip()
    visibility = normalize_journal_visibility(request.form.get("visibility"), default="private")

    if not entry_date:
        entry_date = datetime.now().strftime("%Y-%m-%d")

    if entry_id is None or PlayerDB is None:
        flash("Unable to delete journal entry.", "error")
        return redirect(url_for("pages.journaling", date=entry_date, visibility=visibility))

    success = False
    db = None
    try:
        db = PlayerDB()
        success = db.delete_journal_entry(entry_id, viewer_user["id"])
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Warning: failed to delete journal entry {entry_id}: {exc}")
        success = False
    finally:
        if db:
            db.close()

    if success:
        flash("Journal entry deleted.", "success")
    else:
        flash("Unable to delete journal entry.", "error")

    return redirect(url_for("pages.journaling", date=entry_date, visibility=visibility))


@bp.route('/profile-settings', methods=['GET', 'POST'])
@login_required
def profile_settings():
    """Allow authenticated users to manage their personal preferences."""
    if not PlayerDB:
        flash("Profile settings are temporarily unavailable.", "error")
        return redirect(url_for("pages.home"))

    viewer = g.user or {}
    notification_prefs_raw = viewer.get("notification_preferences") or "{}"
    if isinstance(notification_prefs_raw, str):
        try:
            notification_prefs = json.loads(notification_prefs_raw or "{}")
            if not isinstance(notification_prefs, dict):
                notification_prefs = {}
        except Exception:
            notification_prefs = {}
    elif isinstance(notification_prefs_raw, dict):
        notification_prefs = notification_prefs_raw
    else:
        notification_prefs = {}

    if request.method == "POST":
        if not validate_csrf(request.form.get("csrf_token")):
            flash("Invalid form submission. Please try again.", "error")
            return redirect(url_for("pages.profile_settings"))

        form_name = (request.form.get("form_name") or "basic-info").strip().lower()
        db = None
        try:
            db = PlayerDB()
            if form_name == "basic-info":
                updates = {
                    "first_name": clean_str(request.form.get("first_name")),
                    "last_name": clean_str(request.form.get("last_name")),
                    "pronouns": clean_str(request.form.get("pronouns")),
                    "job_title": clean_str(request.form.get("job_title")),
                    "phone": clean_str(request.form.get("phone")),
                    "timezone": clean_str(request.form.get("timezone")),
                    "bio": (request.form.get("bio") or "").strip(),
                }
                # Normalize optional fields
                for key, value in list(updates.items()):
                    if value is not None:
                        value = value.strip()
                        updates[key] = value or None
                success = db.update_user_profile(viewer["id"], **updates)
                if success:
                    flash("Profile details updated.", "success")
                else:
                    flash("No profile changes detected.", "info")

            elif form_name == "appearance":
                theme = (request.form.get("theme_preference") or "").strip().lower()
                if theme not in {"light", "dark"}:
                    flash("Unknown theme selection.", "error")
                else:
                    db.update_user_profile(viewer["id"], theme_preference=theme)
                    session["theme_preference"] = theme
                    flash("Appearance preference saved.", "success")

            elif form_name == "notifications":
                prefs_payload = {
                    "weekly_digest": bool(request.form.get("weekly_digest")),
                    "reports_ready": bool(request.form.get("reports_ready")),
                    "system_updates": bool(request.form.get("system_updates")),
                }
                db.update_user_profile(
                    viewer["id"],
                    notification_preferences=json.dumps(prefs_payload)
                )
                flash("Notification preferences updated.", "success")

            elif form_name == "change-password":
                current_pw = request.form.get("current_password") or ""
                new_pw = request.form.get("new_password") or ""
                confirm_pw = request.form.get("confirm_password") or ""
                stored_hash = viewer.get("password_hash") or ""

                if not check_password_hash(stored_hash, current_pw):
                    flash("Current password is incorrect.", "error")
                elif new_pw != confirm_pw:
                    flash("New passwords do not match.", "error")
                elif len(new_pw) < 12:
                    flash("Password must be at least 12 characters.", "error")
                else:
                    db.update_user_password(viewer["id"], generate_password_hash(new_pw))
                    flash("Password updated.", "success")

            elif form_name == "avatar":
                file = request.files.get("profile_image")
                if not file or not file.filename:
                    flash("Please select an image to upload.", "error")
                else:
                    filename = secure_filename(file.filename)
                    extension = Path(filename).suffix.lower()
                    if extension not in Config.ALLOWED_PROFILE_EXTENSIONS:
                        flash("Unsupported image type.", "error")
                    else:
                        data = file.read()
                        if len(data) > Config.MAX_UPLOAD_SIZE:
                            flash("Image exceeds 5 MB limit.", "error")
                        else:
                            detected_type = detect_image_type(data)
                            if detected_type not in Config.ALLOWED_PROFILE_TYPES:
                                flash("Uploaded file is not a valid image.", "error")
                            else:
                                unique_name = f"user-{viewer['id']}-{uuid.uuid4().hex}{extension}"
                                destination = Config.UPLOAD_DIR / unique_name
                                with destination.open("wb") as fh:
                                    fh.write(data)

                                # Remove previous avatar if one exists
                                previous = viewer.get("profile_image_path")
                                if previous:
                                    old_path = Config.ROOT_DIR / "static" / previous
                                    try:
                                        old_path.unlink()
                                    except FileNotFoundError:
                                        pass
                                rel_path = f"uploads/profile_photos/{unique_name}"
                                db.update_user_profile(viewer["id"], profile_image_path=rel_path)
                                flash("Profile photo updated.", "success")
            else:
                flash("Unknown form submission.", "error")
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Warning: unable to update profile: {exc}")
            flash(f"Unable to update profile: {exc}", "error")
        finally:
            if db:
                db.close()

        return redirect(url_for("pages.profile_settings"))

    common_timezones = [
        "US/Pacific", "US/Mountain", "US/Central", "US/Eastern",
        "US/Arizona", "US/Hawaii", "Canada/Eastern", "Europe/London",
        "Europe/Paris", "Asia/Tokyo", "Australia/Sydney"
    ]

    return render_template(
        "profile_settings.html",
        notification_prefs=notification_prefs,
        timezones=common_timezones
    )


@bp.route('/terms-of-service')
def terms_of_service():
    """Terms of Service page"""
    from datetime import datetime
    from app.config import Config
    return render_template('terms_of_service.html', 
                         current_date=datetime.now().strftime('%B %d, %Y'),
                         contact_email=Config.CONTACT_EMAIL)


@bp.route('/privacy-policy')
def privacy_policy():
    """Privacy Policy page"""
    from datetime import datetime
    from app.config import Config
    return render_template('privacy_policy.html',
                         current_date=datetime.now().strftime('%B %d, %Y'),
                         contact_email=Config.CONTACT_EMAIL)


@bp.route('/contact-us')
def contact_us():
    """Contact Us page"""
    from app.config import Config
    return render_template('contact_us.html', contact_email=Config.CONTACT_EMAIL)
