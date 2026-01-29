"""
Page routes
"""
from flask import Blueprint, render_template, request, session, g, redirect, url_for, send_file, make_response, jsonify
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, quote
from typing import Optional, List, Dict, Any
from pathlib import Path
import sys
from io import BytesIO

from app.middleware.auth import login_required, admin_required, invalidate_user_cache, refresh_user_cache_with_db
from app.services.page_service import (
    build_player_home_context,
    build_gameday_context,
    load_full_season_schedule,
    purge_concluded_series_documents,
    format_player_document,
    collect_series_for_gameday,
)
from app.config import Config
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
from flask import flash, abort
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import json
import uuid
from app.utils.validators import detect_image_type, convert_heic_to_jpeg
import hashlib

bp = Blueprint('pages', __name__)

# Import PlayerDB if available
try:
    # repo_root/app/routes/pages.py -> repo_root is 3 levels up
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from database import PlayerDB
except ImportError:
    PlayerDB = None


@bp.route('/')
@login_required
def home():
    """Welcome screen - loads instantly."""
    from flask import jsonify
    viewer_user = getattr(g, "user", None)
    if not viewer_user:
        return redirect(url_for('auth.login'))
    
    admin_user_options: List[Dict[str, Any]] = []
    selected_user_id = None
    
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
            logger.warning(f"Warning fetching users for admin welcome selector: {exc}")
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
    
    # Minimal context - no heavy data loading for instant render
    context = {
        "current_user": viewer_user,
        "admin_user_options": admin_user_options,
        "selected_user_id": selected_user_id,
    }
    return render_template('welcome.html', **context)


@bp.route('/dashboard')
@login_required
def dashboard():
    """Detailed dashboard with full data."""
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
            logger.warning(f"Warning fetching users for admin dashboard selector: {exc}")
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
    
    # Get dates with games for calendar (3 months range: 1 month back, 2 months forward)
    import statsapi
    dates_with_games = set()
    try:
        start_range = today - timedelta(days=30)
        end_range = today + timedelta(days=60)
        schedule = statsapi.schedule(
            start_date=start_range.isoformat(),
            end_date=end_range.isoformat()
        )
        if schedule:
            for game in schedule:
                # Try multiple date field formats
                game_date_str = game.get('game_date') or game.get('gameDate') or game.get('game_datetime')
                if game_date_str:
                    try:
                        # Handle ISO datetime format (YYYY-MM-DDTHH:MM:SS)
                        if 'T' in str(game_date_str):
                            game_date = datetime.fromisoformat(str(game_date_str).replace('Z', '+00:00')).date()
                        else:
                            # Handle date-only format (YYYY-MM-DD)
                            game_date = datetime.strptime(str(game_date_str), '%Y-%m-%d').date()
                        dates_with_games.add(game_date.isoformat())
                    except (ValueError, TypeError) as e:
                        continue
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Error fetching dates with games: {e}")
    
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
        is_today=is_today,
        dates_with_games=list(dates_with_games)
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

    # Schedule/series are loaded asynchronously to keep initial page render fast.
    upcoming_games: List[Dict[str, Any]] = []
    # Load league leaders asynchronously to avoid blocking initial page render
    league_leader_groups = None

    player_documents = []
    document_log = []
    if PlayerDB and target_user and target_user.get("id"):
        db = None
        try:
            db = PlayerDB()
            user_docs = db.list_player_documents(target_user.get("id"))
            # Hide series reports from the "Player Documents" card (they render on the Series card instead).
            player_documents = [
                format_player_document(doc)
                for doc in user_docs
                if (doc.get("category") or "").strip().lower() != Config.REPORT_DOC_CATEGORY
            ]
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

    # Load standings asynchronously to avoid blocking initial page render
    standings_data = None

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

    show_date_redirect_note = False
    requested_tab = "current"

    # Load lightweight gameday context data (next_series, calendar, deliverables)
    gameday_ctx = build_gameday_context(target_user) if target_user else {}

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
        # Gameday context data
        next_series=gameday_ctx.get("next_series"),
        schedule_calendar=gameday_ctx.get("schedule_calendar", []),
        deliverables=gameday_ctx.get("deliverables", []),
    )


@bp.route('/api/gameday/schedule')
@login_required
def gameday_schedule():
    """Async schedule/series content for gameday."""
    viewer_user = getattr(g, "user", None)
    target_user = viewer_user

    requested_user_id = request.args.get("user_id", type=int)
    if session.get("is_admin") and PlayerDB and requested_user_id:
        db = None
        try:
            db = PlayerDB()
            fetched = db.get_user_by_id(int(requested_user_id))
            if fetched:
                target_user = fetched
        except Exception:
            target_user = viewer_user
        finally:
            try:
                if db:
                    db.close()
            except Exception:
                pass

    # This endpoint is on the critical path for "Series" rendering.
    # Removed purge_concluded_series_documents() - it was blocking and should run in background.
    # Check ETag FIRST before doing any work, so 304 responses are instant.

    # Fast ETag check using cached series data (without building HTML or querying DB).
    # Use a simple cache key based on user + date to generate ETag without DB work.
    cache_key_for_etag = None
    if target_user and target_user.get("id"):
        cache_key_for_etag = f"gameday-schedule-etag-{target_user.get('id')}-{datetime.now().date().isoformat()}"
    
    # Try to get cached ETag first (fast lookup)
    cached_etag = None
    if cache_key_for_etag:
        try:
            from app.services.persistent_cache import get_json as persistent_cache_get_json
            cached_etag_data = persistent_cache_get_json("gameday_schedule_etag", {"key": cache_key_for_etag})
            if isinstance(cached_etag_data, str):
                cached_etag = cached_etag_data
        except Exception:
            pass
    
    # Check If-None-Match BEFORE doing any expensive work
    inm = request.headers.get("If-None-Match")
    if inm and cached_etag and inm.strip() == cached_etag:
        resp = make_response("", 304)
        resp.headers["ETag"] = cached_etag
        resp.headers["Cache-Control"] = "private, max-age=60"
        resp.headers["Vary"] = "Cookie"
        return resp

    # Only now do the actual work if we need to build the response
    upcoming_games: List[Dict[str, Any]] = []
    # Use cached series list for gameday (built from full-season schedule).
    upcoming_games = collect_series_for_gameday(target_user) or []

    # Cache report_docs lookup to avoid DB query on every request
    report_docs: List[Dict[str, Any]] = []
    if PlayerDB and target_user and target_user.get("id"):
        report_cache_key = f"gameday-report-docs-{target_user.get('id')}"
        try:
            from app.services.persistent_cache import get_json as persistent_cache_get_json, get_or_set_json as persistent_get_or_set_json
            
            def _load_report_docs():
                db = None
                try:
                    db = PlayerDB()
                    return db.list_player_documents(int(target_user.get("id")), category=Config.REPORT_DOC_CATEGORY) or []
                except Exception:
                    return []
                finally:
                    try:
                        if db:
                            db.close()
                    except Exception:
                        pass
            
            report_docs = persistent_get_or_set_json(
                "gameday_report_docs",
                {"user_id": int(target_user.get("id"))},
                ttl_seconds=300,  # 5 min cache
                builder=_load_report_docs,
            ) or []
        except Exception:
            # Fallback to direct query if cache fails
            db = None
            try:
                db = PlayerDB()
                report_docs = db.list_player_documents(int(target_user.get("id")), category=Config.REPORT_DOC_CATEGORY) or []
            except Exception:
                report_docs = []
            finally:
                try:
                    if db:
                        db.close()
                except Exception:
                    pass

    if report_docs and upcoming_games:
        # Build per-opponent lists and match by series window overlap.
        by_opp: Dict[str, List[Dict[str, Any]]] = {}
        for doc in report_docs:
            opp = (doc.get("series_opponent") or "").strip().upper()
            if not opp:
                continue
            start_ts = doc.get("series_start")
            end_ts = doc.get("series_end")
            if not start_ts or not end_ts:
                continue
            by_opp.setdefault(opp, []).append(doc)

        for game in upcoming_games:
            opp = (game.get("opponent_abbr") or "").strip().upper()
            if not opp:
                continue
            # Recover the series window from display_date is hard; use category grouping window if present.
            # We stored start/end dates during formatting as datetime.date.
            series_start = game.get("_series_start_date")
            series_end = game.get("_series_end_date")
            matched: List[Dict[str, Any]] = []
            if series_start and series_end:
                for doc in by_opp.get(opp, []):
                    doc_start = datetime.fromtimestamp(doc["series_start"]).date()
                    doc_end = datetime.fromtimestamp(doc["series_end"]).date()
                    if doc_start <= series_end and doc_end >= series_start:
                        matched.append({
                            "title": doc.get("filename") or "Report",
                            "url": url_for("admin.download_player_document", doc_id=doc.get("id")),
                            "generated_at": None,
                        })
            else:
                # Fallback: match by opponent only.
                for doc in by_opp.get(opp, []):
                    matched.append({
                        "title": doc.get("filename") or "Report",
                        "url": url_for("admin.download_player_document", doc_id=doc.get("id")),
                        "generated_at": None,
                    })
            game["reports"] = matched

    html = render_template(
        "partials/gameday_schedule_content.html",
        upcoming_games=upcoming_games,
        show_date_redirect_note=False,
        default_schedule_tab="current",
    )
    
    # Generate ETag from HTML and cache it for fast 304 checks next time
    etag = 'W/"gameday-schedule-{}"'.format(hashlib.md5(html.encode("utf-8")).hexdigest())
    
    # Cache the ETag for fast lookup next time
    if cache_key_for_etag:
        try:
            from app.services.persistent_cache import set_json as persistent_cache_set_json
            persistent_cache_set_json("gameday_schedule_etag", {"key": cache_key_for_etag}, etag, ttl_seconds=300)
        except Exception:
            pass

    resp = jsonify({"schedule_html": html})
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "private, max-age=60"
    resp.headers["Vary"] = "Cookie"
    return resp


@bp.route('/api/gameday/widgets')
@login_required
def gameday_widgets():
    """Async widgets for gameday (leaders + standings)."""
    viewer_user = getattr(g, "user", None)
    target_user = viewer_user

    requested_user_id = request.args.get("user_id", type=int)
    if session.get("is_admin") and PlayerDB and requested_user_id:
        db = None
        try:
            db = PlayerDB()
            fetched = db.get_user_by_id(int(requested_user_id))
            if fetched:
                target_user = fetched
        except Exception:
            target_user = viewer_user
        finally:
            try:
                if db:
                    db.close()
            except Exception:
                pass

    team_abbr = determine_user_team(target_user)
    team_metadata = get_team_metadata(team_abbr)

    standings_view = request.args.get('standings_view', 'division').lower()
    if standings_view not in {"division", "wildcard"}:
        standings_view = "division"

    requested_division_id = request.args.get('division_id', type=int)
    requested_league_id = request.args.get('league_id', type=int)

    league_leader_groups = []
    try:
        league_leader_groups = collect_league_leaders() or []
    except Exception:
        league_leader_groups = []

    standings_data = None
    try:
        standings_data = collect_standings_data(
            standings_view,
            team_metadata,
            division_id=requested_division_id,
            league_id=requested_league_id
        )
    except Exception:
        standings_data = None

    leaders_html = render_template(
        "partials/gameday_leaders_content.html",
        league_leader_groups=league_leader_groups,
    )
    standings_html = render_template(
        "partials/gameday_standings_content.html",
        standings_data=standings_data,
    )
    return jsonify({
        "leaders_html": leaders_html,
        "standings_html": standings_html,
    })


@bp.route("/api/time")
@login_required
def api_time():
    """Return server UTC time for client clock skew correction."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return jsonify({"server_unix_ms": now_ms})


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


@bp.route('/video')
@login_required
def video():
    """Video page"""
    # Determine iframe URL based on user role
    is_admin = session.get("is_admin", False)
    
    if is_admin:
        video_url = "https://sequence-video.vercel.app/admin#admin"
    else:
        # Get player name from session or g.user
        first_name = session.get("first_name", "")
        last_name = session.get("last_name", "")
        
        # Fallback to g.user if session doesn't have names
        if not first_name or not last_name:
            user = g.user or {}
            first_name = user.get("first_name", "")
            last_name = user.get("last_name", "")
        
        # Construct player name and URL encode it
        player_name = f"{first_name} {last_name}".strip()
        if player_name:
            # Use quote instead of quote_plus for path segments (encodes space as %20, not +)
            encoded_name = quote(player_name)
            video_url = f"https://sequence-video.vercel.app/player/{encoded_name}#user"
        else:
            # Fallback if no name available
            video_url = "https://sequence-video.vercel.app/admin#admin"
    
    return render_template('video.html', video_url=video_url)


@bp.route('/tools')
@login_required
def tools():
    """Tools page"""
    return render_template('tools.html')


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
    """Workouts page integrated with external weights app."""
    viewer_user = getattr(g, "user", None)
    
    # Check admin status from both session and user object
    is_admin = bool(session.get("is_admin")) or (viewer_user and viewer_user.get("is_admin"))
    
    # External weights app URLs
    WEIGHTS_APP_BASE = "https://sequence-weights-git-main-cooper-710s-projects.vercel.app"
    ADMIN_TOKEN = "admin-sequence-2024-secure-token"
    
    weights_app_url = ""
    player_name = None
    
    try:
        if is_admin:
            # Admin link with token
            weights_app_url = f"{WEIGHTS_APP_BASE}/admin?token={ADMIN_TOKEN}"
            player_name = None
        else:
            # Get player name exactly like mocap does
            player_name = request.args.get('player')
            if not player_name:
                if viewer_user and viewer_user.get('first_name') and viewer_user.get('last_name'):
                    player_name = f"{viewer_user['first_name']} {viewer_user['last_name']}"
                elif session.get('first_name') and session.get('last_name'):
                    player_name = f"{session['first_name']} {session['last_name']}"
                else:
                    # Fallback (should be rare with login_required)
                    player_name = "Player"
            
            # URL encode the name (spaces become +)
            encoded_name = quote_plus(player_name)
            weights_app_url = f"{WEIGHTS_APP_BASE}/user?mode=player&player={encoded_name}"
    except Exception as exc:
        # Log error and provide fallback
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error building workouts URL: {exc}")
        # Provide a fallback URL
        if is_admin:
            weights_app_url = f"{WEIGHTS_APP_BASE}/admin?token={ADMIN_TOKEN}"
        else:
            weights_app_url = f"{WEIGHTS_APP_BASE}/user?mode=player&player=Player"
    
    # Ensure we always have a URL
    if not weights_app_url:
        weights_app_url = f"{WEIGHTS_APP_BASE}/user?mode=player&player=Player"
    
    from app.middleware.csrf import generate_csrf_token

    return render_template(
        'workouts.html',
        weights_app_url=weights_app_url,
        is_admin=is_admin,
        player_name=player_name,
        csrf_token=generate_csrf_token(),
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
                    # Invalidate and refresh cache to ensure latest data
                    invalidate_user_cache(viewer["id"])
                    g.user = refresh_user_cache_with_db(db, viewer["id"])
                    flash("Profile details updated.", "success")
                else:
                    flash("No profile changes detected.", "info")

            elif form_name == "appearance":
                theme = (request.form.get("theme_preference") or "").strip().lower()
                if theme not in {"light", "dark"}:
                    flash("Unknown theme selection.", "error")
                else:
                    db.update_user_profile(viewer["id"], theme_preference=theme)
                    # Invalidate and refresh cache to ensure latest data
                    invalidate_user_cache(viewer["id"])
                    g.user = refresh_user_cache_with_db(db, viewer["id"])
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
                # Invalidate and refresh cache to ensure latest data
                invalidate_user_cache(viewer["id"])
                g.user = refresh_user_cache_with_db(db, viewer["id"])
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
                    # Invalidate cache after password change (security best practice)
                    invalidate_user_cache(viewer["id"])
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
                                # Convert HEIC/HEIF to JPEG for browser compatibility
                                if detected_type == "heic" or extension in (".heic", ".heif"):
                                    jpeg_data = convert_heic_to_jpeg(data)
                                    if jpeg_data is None:
                                        flash("Failed to convert HEIC image. Please try a different format.", "error")
                                        return redirect(url_for("pages.profile_settings"))
                                    data = jpeg_data
                                    extension = ".jpg"
                                    detected_type = "jpeg"

                                # Store avatar in DB (Supabase/Postgres) to avoid Render ephemeral filesystem 404s
                                content_type = {
                                    "jpeg": "image/jpeg",
                                    "png": "image/png",
                                    "gif": "image/gif",
                                    "webp": "image/webp",
                                }.get(detected_type, "image/jpeg")

                                try:
                                    db.upsert_user_avatar(viewer["id"], content_type=content_type, data=data)
                                except Exception as exc:
                                    import logging
                                    logger = logging.getLogger(__name__)
                                    logger.warning(f"Warning: failed to store avatar in DB: {exc}")
                                    flash("Unable to save profile photo. Please try again.", "error")
                                    return redirect(url_for("pages.profile_settings"))

                                # Mark user as having a DB-backed avatar
                                db.update_user_profile(viewer["id"], profile_image_path="avatar")
                                
                                # Invalidate and refresh cache to show updated image immediately
                                invalidate_user_cache(viewer["id"])
                                g.user = refresh_user_cache_with_db(db, viewer["id"])
                                
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


@bp.route("/media/avatar/<int:user_id>")
@login_required
def user_avatar(user_id: int):
    """Serve DB-backed user avatar (fixes missing files on Render)."""
    viewer = g.user or {}
    viewer_id = viewer.get("id")
    is_admin = bool(session.get("is_admin")) or bool(viewer.get("is_admin"))

    # Only allow users to fetch their own avatar unless admin
    if not viewer_id or (not is_admin and int(viewer_id) != int(user_id)):
        abort(403)

    if not PlayerDB:
        abort(404)

    db = None
    try:
        db = PlayerDB()
        avatar = db.get_user_avatar(int(user_id))
    finally:
        try:
            if db:
                db.close()
        except Exception:
            pass

    if not avatar or not avatar.get("data"):
        # Fallback to default logo so legacy users don't get broken images.
        try:
            default_path = Config.ROOT_DIR / "static" / "sequence-logo.png"
            resp = send_file(str(default_path), mimetype="image/png", download_name="avatar-default.png")
            resp.headers["Cache-Control"] = "private, max-age=86400"
            return resp
        except Exception:
            abort(404)

    data = avatar.get("data")
    content_type = (avatar.get("content_type") or "image/jpeg").strip()

    updated_at = avatar.get("updated_at") or 0
    try:
        etag = f'W/"avatar-{int(user_id)}-{int(float(updated_at))}"'
    except Exception:
        etag = f'W/"avatar-{int(user_id)}"'

    inm = request.headers.get("If-None-Match")
    if inm and inm.strip() == etag:
        resp = make_response("", 304)
        resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = "private, max-age=31536000, immutable"
        resp.headers["Vary"] = "Cookie"
        return resp

    resp = send_file(BytesIO(data), mimetype=content_type, download_name=f"user-{user_id}-avatar")
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    resp.headers["Vary"] = "Cookie"
    return resp


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


@bp.route('/api/welcome/quick-stats')
@login_required
def api_welcome_quick_stats():
    """API endpoint for welcome screen quick stats."""
    from flask import jsonify
    viewer_user = getattr(g, "user", None)
    if not viewer_user:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        from app.services.page_service import load_next_series_snapshot, load_schedule_calendar, load_player_deliverables
        
        next_series = load_next_series_snapshot(viewer_user)
        schedule = load_schedule_calendar(viewer_user)
        
        # Count upcoming games (next 30 days)
        from datetime import datetime, timedelta
        today = datetime.now().date()
        thirty_days = today + timedelta(days=30)
        upcoming_count = 0
        for game in schedule:
            if game.get('date'):
                try:
                    game_date = datetime.fromisoformat(game['date']).date()
                    if today <= game_date <= thirty_days:
                        upcoming_count += 1
                except Exception:
                    continue
        
        # Get deliverables count
        _, deliverables, _ = load_player_deliverables(viewer_user)
        reports_count = len(deliverables) if deliverables else 0
        
        return jsonify({
            "next_series": next_series or {},
            "upcoming_count": upcoming_count,
            "reports_count": reports_count,
        })
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error loading welcome stats: {e}")
        return jsonify({"error": str(e)}), 500
