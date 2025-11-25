"""
Page service for page-related helper functions
"""
import os
import re
import textwrap
import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from flask import current_app, url_for
from urllib.parse import quote
import sys
import requests
import statsapi

from app.config import Config
from app.utils.formatters import coerce_utc_datetime
from app.services.player_service import determine_user_team
from app.services.schedule_service import collect_series_for_team, team_abbr_from_id
from app.services.cache_service import cache_service, CACHE_UPCOMING_GAMES, CACHE_PLAYER_NEWS

# Import PlayerDB and next_games if available
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
try:
    from database import PlayerDB
except ImportError:
    PlayerDB = None

try:
    from next_opponent import next_games
except ImportError:
    next_games = None

logger = logging.getLogger(__name__)

# Cache for player news
_PLAYER_NEWS_CACHE: Dict[str, Tuple[List[Dict[str, Any]], datetime]] = {}


def _get_use_mock_schedule() -> bool:
    """Get USE_MOCK_SCHEDULE setting from Flask app config or Config."""
    try:
        return bool(current_app.config.get("USE_MOCK_SCHEDULE", False))
    except RuntimeError:
        # No application context, use Config
        return Config.USE_MOCK_SCHEDULE


def _collect_staff_notes(team_abbr: Optional[str], limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve staff notes for display on the Gameday hub."""
    if not PlayerDB:
        return []

    try:
        db = PlayerDB()
        notes = db.list_staff_notes(team_abbr=team_abbr, limit=limit)
        db.close()
    except Exception as exc:
        logger.warning(f"Warning fetching staff notes: {exc}")
        return []

    return [_format_staff_note(note) for note in notes]


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


def load_next_series_snapshot(user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Load the next active series snapshot for the user."""
    try:
        team_abbr = determine_user_team(user)
        series_list = collect_series_for_team(team_abbr, days_ahead=365)
    except Exception as exc:
        logger.warning(f"Warning building next series snapshot: {exc}")
        series_list = []

    next_active = None
    for series in series_list:
        if series.get("status") != "expired":
            next_active = series
            break

    if not next_active:
        return None

    start_dt = coerce_utc_datetime(next_active.get("start"))
    end_dt = coerce_utc_datetime(next_active.get("end"))
    now_local = datetime.now(timezone.utc).astimezone()
    start_local = start_dt.astimezone(now_local.tzinfo) if start_dt else None
    end_local = end_dt.astimezone(now_local.tzinfo) if end_dt else None
    if start_local:
        days_until = max(0, (start_local.date() - now_local.date()).days)
    else:
        days_until = None

    # Get first game datetime for countdown clock
    first_game_datetime = next_active.get("first_game_datetime")
    first_game_dt = None
    if first_game_datetime:
        first_game_dt = coerce_utc_datetime(first_game_datetime)
        if first_game_dt:
            first_game_dt = first_game_dt.astimezone(now_local.tzinfo)

    def _fmt(dt: Optional[datetime]) -> Optional[str]:
        if not dt:
            return None
        return dt.strftime("%b %d")

    return {
        "opponent_name": next_active.get("opponent_name"),
        "opponent_id": next_active.get("opponent_id"),
        "opponent_abbr": next_active.get("opponent_abbr"),
        "start_date": _fmt(start_local),
        "end_date": _fmt(end_local),
        "status": next_active.get("status"),
        "days_until": days_until,
        "first_game_datetime_iso": first_game_dt.isoformat() if first_game_dt else None,  # For countdown clock
    }


def load_schedule_calendar(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Load schedule data for calendar widget (full month)."""
    try:
        team_abbr = determine_user_team(user)
        use_mock = _get_use_mock_schedule()
        
        # Get games - use mock or real data
        games = []
        if use_mock:
            # Get mock games with raw date data (same pattern as schedule page)
            now = datetime.now().astimezone()
            base_first_pitch = now.replace(hour=19, minute=10, second=0, microsecond=0)
            
            mock_blueprint = [
                {"days_offset": 0, "opponent": "Washington Nationals", "opponent_abbr": "WSH", "opponent_id": 120, "is_home": True, "status": "Scheduled"},
                {"days_offset": 1, "opponent": "Washington Nationals", "opponent_abbr": "WSH", "opponent_id": 120, "is_home": True, "status": "Scheduled"},
                {"days_offset": 3, "opponent": "Philadelphia Phillies", "opponent_abbr": "PHI", "opponent_id": 143, "is_home": False, "status": "Scheduled"},
                {"days_offset": 4, "opponent": "Philadelphia Phillies", "opponent_abbr": "PHI", "opponent_id": 143, "is_home": False, "status": "Scheduled"},
                {"days_offset": 6, "opponent": "Atlanta Braves", "opponent_abbr": "ATL", "opponent_id": 144, "is_home": True, "status": "Scheduled"},
                {"days_offset": 8, "opponent": "Miami Marlins", "opponent_abbr": "MIA", "opponent_id": 146, "is_home": True, "status": "Scheduled"},
                {"days_offset": 10, "opponent": "New York Yankees", "opponent_abbr": "NYY", "opponent_id": 147, "is_home": False, "status": "Scheduled"},
            ]
            
            # Generate games for the next 365 days to cover full season
            # Repeat the pattern every 14 days to create a realistic schedule
            # Calculate weeks needed: 365 days / 14 days per cycle ≈ 26 weeks
            for week_offset in range(0, 26):  # 26 weeks ≈ 365 days
                for entry in mock_blueprint:
                    days_offset = entry["days_offset"] + (week_offset * 14)
                    
                    game_dt = base_first_pitch + timedelta(days=days_offset)
                    games.append({
                        "game_date": game_dt.date().isoformat(),
                        "game_datetime": game_dt.isoformat(),
                        "opponent_name": entry["opponent"],
                        "opponent_abbr": entry["opponent_abbr"],
                        "opponent_id": entry["opponent_id"],
                        "is_home": entry["is_home"],
                        "status": entry.get("status", "Scheduled"),
                        "venue": "TBD",
                    })
        elif next_games:
            # Get 365 days of games to show all upcoming games (same as gameday hub)
            games = next_games(team_abbr, days_ahead=365, include_started=True)
        else:
            return []
        
        # Format for calendar display
        calendar_data = []
        for game in games:
            game_date = game.get("game_date")
            if game_date:
                try:
                    # Handle both ISO string and date object
                    if isinstance(game_date, str):
                        dt = datetime.fromisoformat(game_date)
                    else:
                        dt = game_date if isinstance(game_date, datetime) else datetime.combine(game_date, datetime.min.time())
                    
                    opponent_id = game.get("opponent_id")
                    opponent_abbr = game.get("opponent_abbr", "")
                    # Derive opponent_abbr from opponent_id if not present
                    if not opponent_abbr and opponent_id:
                        opponent_abbr = team_abbr_from_id(opponent_id) or ""
                    
                    calendar_data.append({
                        "date": dt.strftime("%Y-%m-%d"),
                        "day": dt.strftime("%d"),
                        "day_name": dt.strftime("%a"),
                        "opponent": game.get("opponent_name", ""),
                        "opponent_abbr": opponent_abbr,
                        "opponent_id": opponent_id,
                        "is_home": game.get("is_home", False),
                        "venue": game.get("venue", ""),
                        "status": game.get("status", "Scheduled"),
                    })
                except Exception as e:
                    logger.warning(f"Warning formatting game date {game_date}: {e}")
                    continue
        
        return calendar_data
    except Exception as e:
        logger.warning(f"Warning loading schedule calendar: {e}")
        return []


def load_full_season_schedule(user: Dict[str, Any], start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load full season schedule, optionally filtered by date range."""
    try:
        team_abbr = determine_user_team(user)
        use_mock = _get_use_mock_schedule()
        
        # Default to full season (March to October)
        if not start_date:
            current_year = datetime.now().year
            start_date = f"{current_year}-03-01"
        if not end_date:
            current_year = datetime.now().year
            end_date = f"{current_year}-10-31"
        
        # Calculate days between dates
        start_dt = datetime.fromisoformat(start_date).date()
        end_dt = datetime.fromisoformat(end_date).date()
        today = datetime.now().date()
        
        # Get games - use mock or real data
        games = []
        if use_mock:
            # Get mock games with raw date data (same as calendar widget)
            # Start from start_date (March 1st) or today, whichever is later
            if start_dt > datetime.now().date():
                # Season hasn't started yet, start from season start date
                base_date = start_dt
            else:
                # Season has started, use today
                base_date = datetime.now().date()
            
            # Create base datetime for game times (7:10 PM)
            base_first_pitch = datetime.combine(base_date, datetime.min.time().replace(hour=19, minute=10))
            if base_first_pitch.tzinfo is None:
                base_first_pitch = base_first_pitch.replace(tzinfo=datetime.now().astimezone().tzinfo)
            
            mock_blueprint = [
                {"days_offset": 0, "opponent": "Washington Nationals", "opponent_abbr": "WSH", "opponent_id": 120, "is_home": True, "status": "Scheduled"},
                {"days_offset": 1, "opponent": "Washington Nationals", "opponent_abbr": "WSH", "opponent_id": 120, "is_home": True, "status": "Scheduled"},
                {"days_offset": 3, "opponent": "Philadelphia Phillies", "opponent_abbr": "PHI", "opponent_id": 143, "is_home": False, "status": "Scheduled"},
                {"days_offset": 4, "opponent": "Philadelphia Phillies", "opponent_abbr": "PHI", "opponent_id": 143, "is_home": False, "status": "Scheduled"},
                {"days_offset": 6, "opponent": "Atlanta Braves", "opponent_abbr": "ATL", "opponent_id": 144, "is_home": True, "status": "Scheduled"},
                {"days_offset": 8, "opponent": "Miami Marlins", "opponent_abbr": "MIA", "opponent_id": 146, "is_home": True, "status": "Scheduled"},
                {"days_offset": 10, "opponent": "New York Yankees", "opponent_abbr": "NYY", "opponent_id": 147, "is_home": False, "status": "Scheduled"},
            ]
            
            # Generate games for the full season (March to October)
            # Calculate how many weeks we need to cover from start_date to end_date
            days_span = (end_dt - start_dt).days
            weeks_needed = max(1, (days_span // 14) + 2)  # Add buffer
            
            # Repeat the pattern every 14 days to create a realistic schedule
            for week_offset in range(0, weeks_needed):
                for entry in mock_blueprint:
                    days_offset = entry["days_offset"] + (week_offset * 14)
                    
                    game_dt = base_first_pitch + timedelta(days=days_offset)
                    game_date = game_dt.date()
                    
                    # Only include if within date range
                    if start_dt <= game_date <= end_dt:
                        games.append({
                            "game_date": game_date.isoformat(),
                            "game_datetime": game_dt.isoformat(),
                            "opponent_name": entry["opponent"],
                            "opponent_abbr": entry["opponent_abbr"],
                            "opponent_id": entry["opponent_id"],
                            "is_home": entry["is_home"],
                            "status": entry.get("status", "Scheduled"),
                            "venue": "TBD",
                        })
        elif next_games:
            days_ahead = max((end_dt - today).days, 0)
            
            if days_ahead == 0:
                days_ahead = 365  # If end date is in past, get a full year
            
            # Get all games in range - USE REAL DATA ONLY
            try:
                games = next_games(team_abbr, days_ahead=min(days_ahead, 365), include_started=True)
                logger.info(f"Loaded {len(games)} games from real API for {team_abbr}")
            except Exception as e:
                logger.warning(f"Error fetching games from API: {e}")
                games = []
        else:
            logger.warning("next_games not available, cannot load real schedule data")
            games = []
        
        # Filter by date range if provided
        filtered_games = []
        for game in games:
            game_date_str = game.get("game_date")
            if game_date_str:
                try:
                    if isinstance(game_date_str, str):
                        game_date = datetime.fromisoformat(game_date_str).date()
                    else:
                        game_date = game_date_str if isinstance(game_date_str, date) else datetime.combine(game_date_str, datetime.min.time()).date()
                    
                    if start_dt <= game_date <= end_dt:
                        filtered_games.append(game)
                except Exception:
                    continue
        
        return filtered_games
    except Exception as e:
        logger.warning(f"Warning loading full season schedule: {e}")
        return []


def format_player_document(doc: Dict[str, Any]) -> Dict[str, Any]:
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
        try:
            viewer_url = url_for("view_workout_document", doc_id=doc.get("id"))
        except Exception:
            pass

    return {
        "id": doc.get("id"),
        "player_id": doc.get("player_id"),
        "filename": doc.get("filename"),
        "uploaded_at": _fmt(uploaded_ts),
        "uploaded_at_iso": _iso(uploaded_ts),
        "download_url": url_for("download_player_document", doc_id=doc.get("id")),
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


def friendly_title(filename: Optional[str]) -> str:
    """Convert filename to friendly title."""
    if not filename:
        return "Document"
    stem = os.path.splitext(filename)[0]
    cleaned = re.sub(r"[_\-]+", " ", stem).strip()
    return cleaned if cleaned else filename


def humanize_time_ago(target: Optional[datetime], reference: Optional[datetime] = None) -> str:
    """Format datetime as human-readable time ago."""
    if not target:
        return "just now"
    if reference is None:
        reference = datetime.now(timezone.utc).astimezone()

    if target.tzinfo is None:
        target = target.replace(tzinfo=reference.tzinfo or timezone.utc)
    delta = reference - target
    seconds = delta.total_seconds()

    if seconds < 0:
        seconds = abs(seconds)
        prefix = "in "
    else:
        prefix = ""

    if seconds < 60:
        phrase = "moments"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        phrase = f"{minutes} min"
    elif seconds < 86400:
        hours = int(seconds // 3600)
        phrase = f"{hours} hr"
    elif seconds < 7 * 86400:
        days = int(seconds // 86400)
        phrase = f"{days} day"
    else:
        return target.strftime("%b %d")

    if prefix:
        return f"{prefix}{phrase}"
    return f"{phrase} ago"


def map_document_to_deliverable(
    raw_doc: Dict[str, Any],
    formatted: Dict[str, Any],
    uploader_name: str,
    reference_now: datetime,
) -> Dict[str, Any]:
    """Map a player document to a deliverable format."""
    uploaded_ts = raw_doc.get("uploaded_at") or 0
    uploaded_dt = datetime.fromtimestamp(uploaded_ts, tz=timezone.utc).astimezone(reference_now.tzinfo)

    category = formatted.get("category")
    category_icon = {
        Config.WORKOUT_CATEGORY: "fas fa-dumbbell",
        "scouting": "fas fa-clipboard-user",
        "report": "fas fa-chart-line",
        "video": "fas fa-film",
    }.get(category, "fas fa-file-lines")

    series_label = formatted.get("series_label")
    summary = series_label or (formatted.get("series_range_display") or "Shared document")

    title = friendly_title(formatted.get("filename") or raw_doc.get("filename"))
    try:
        link = formatted.get("viewer_url") or formatted.get("download_url") or url_for("reports_library")
    except Exception:
        link = "#"
    requires_ack = bool(
        category != Config.WORKOUT_CATEGORY
        and (reference_now - uploaded_dt).total_seconds() < 5 * 24 * 3600
    )
    if formatted.get("series_status") in {"current", "upcoming"}:
        requires_ack = True

    return {
        "id": raw_doc.get("id"),
        "icon": category_icon,
        "title": title,
        "summary": summary,
        "owner": uploader_name or "Sequence Staff",
        "time_ago": humanize_time_ago(uploaded_dt, reference_now),
        "link": link,
        "requires_ack": requires_ack,
        "uploaded_ts": uploaded_ts,
    }


def load_player_deliverables(user: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], int]:
    """Load player deliverables for a user."""
    if not PlayerDB or not user:
        return sample_deliverables()

    rows: List[Dict[str, Any]] = []
    db = None
    try:
        db = PlayerDB()
        cursor = db.conn.cursor()
        # Use _execute to handle PostgreSQL parameter conversion (? -> %s)
        db._execute(cursor,
            """
            SELECT d.*,
                   u.first_name AS uploader_first_name,
                   u.last_name AS uploader_last_name
            FROM player_documents AS d
            LEFT JOIN users AS u ON u.id = d.uploaded_by
            WHERE d.player_id = ?
            ORDER BY d.uploaded_at DESC
            LIMIT 6
            """,
            (int(user.get("id")),),
        )
        rows = [dict(row) for row in cursor.fetchall()]
    except Exception as exc:
        logger.warning(f"Warning loading player deliverables for user {user.get('id')}: {exc}")
    finally:
        if db:
            db.close()

    if not rows:
        return None, [], 0

    now_local = datetime.now(timezone.utc).astimezone()
    deliverables: List[Dict[str, Any]] = []

    for raw_doc in rows:
        raw_doc["category"] = (raw_doc.get("category") or "").strip().lower() or None
        uploader_name = "Sequence Staff"
        first = (raw_doc.get("uploader_first_name") or "").strip()
        last = (raw_doc.get("uploader_last_name") or "").strip()
        if first or last:
            uploader_name = f"{first} {last}".strip()

        formatted = format_player_document(raw_doc)
        deliverable = map_document_to_deliverable(raw_doc, formatted, uploader_name, now_local)
        deliverables.append(deliverable)

    deliverables.sort(key=lambda item: item.get("uploaded_ts") or 0, reverse=True)

    outstanding_count = sum(1 for item in deliverables if item.get("requires_ack"))
    latest = deliverables[0] if deliverables else None
    latest_document = None
    if latest:
        latest_document = {
            "title": latest["title"],
            "owner": latest["owner"],
            "time_ago": latest["time_ago"],
            "link": latest["link"],
        }

    for item in deliverables:
        item.pop("uploaded_ts", None)

    return latest_document, deliverables, outstanding_count


def sample_deliverables() -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], int]:
    """Return sample deliverables when database is unavailable."""
    now_local = datetime.now(timezone.utc).astimezone()
    try:
        deliverables = [
            {
                "id": "sample-capsule",
                "icon": "fas fa-clipboard-user",
                "title": "Dodgers Series Capsule",
                "summary": "Matchup tendencies & red zone plan.",
                "owner": "Pro Scouting",
                "time_ago": "2 hr ago",
                "link": url_for("reports_library"),
                "requires_ack": True,
                "uploaded_ts": now_local.timestamp() - 2 * 3600,
            },
            {
                "id": "sample-workout",
                "icon": "fas fa-dumbbell",
                "title": "Wednesday Activation",
                "summary": "Mobility + lower half sequencing.",
                "owner": "Performance Team",
                "time_ago": "Yesterday",
                "link": url_for("workouts"),
                "requires_ack": False,
                "uploaded_ts": now_local.timestamp() - 27 * 3600,
            },
            {
                "id": "sample-video",
                "icon": "fas fa-film",
                "title": "LHP Slider Review",
                "summary": "High-leverage pitch shapes & cues.",
                "owner": "Video Coord.",
                "time_ago": "3 days ago",
                "link": url_for("visuals"),
                "requires_ack": True,
                "uploaded_ts": now_local.timestamp() - 3 * 86400,
            },
        ]
        outstanding = sum(1 for item in deliverables if item["requires_ack"])
        latest = deliverables[0]
        latest_document = {
            "title": latest["title"],
            "owner": latest["owner"],
            "time_ago": latest["time_ago"],
            "link": latest["link"],
        }
        for item in deliverables:
            item.pop("uploaded_ts", None)
        return latest_document, deliverables, outstanding
    except Exception:
        # Fallback if url_for fails
        latest_document = {
            "title": "Dodgers Series Capsule",
            "owner": "Pro Scouting",
            "time_ago": "2 hr ago",
            "link": "#",
        }
        deliverables = [
            {
                "id": "sample-capsule",
                "icon": "fas fa-clipboard-user",
                "title": "Dodgers Series Capsule",
                "summary": "Matchup tendencies & red zone plan.",
                "owner": "Pro Scouting",
                "time_ago": "2 hr ago",
                "link": "#",
                "requires_ack": True,
            }
        ]
        return latest_document, deliverables, 1


def build_focus_highlights(
    next_series: Optional[Dict[str, Any]],
    latest_document: Optional[Dict[str, Any]],
    outstanding_count: int,
) -> List[Dict[str, Any]]:
    """Build focus highlights for the home page."""
    highlights: List[Dict[str, Any]] = []

    if next_series:
        start = next_series.get("start_date")
        days_until = next_series.get("days_until")
        detail_parts: List[str] = []
        if start:
            detail_parts.append(f"Starts {start}")
        if days_until is not None:
            detail_parts.append(f"{days_until} day{'s' if days_until != 1 else ''} out")
        try:
            highlights.append(
                {
                    "icon": "fas fa-baseball",
                    "label": "Next Series",
                    "value": next_series.get("opponent_name") or "Opponent TBD",
                    "detail": " • ".join(detail_parts) if detail_parts else None,
                    "cta": {
                        "label": "Matchup Capsule",
                        "href": url_for("gameday"),
                    },
                }
            )
        except Exception:
            highlights.append(
                {
                    "icon": "fas fa-baseball",
                    "label": "Next Series",
                    "value": next_series.get("opponent_name") or "Opponent TBD",
                    "detail": " • ".join(detail_parts) if detail_parts else None,
                    "cta": {
                        "label": "Matchup Capsule",
                        "href": "#",
                    },
                }
            )

    if latest_document:
        try:
            highlights.append(
                {
                    "icon": "fas fa-file-lines",
                    "label": "Latest Upload",
                    "value": latest_document.get("title", "New document"),
                    "detail": f"{latest_document.get('owner', 'Staff')} • {latest_document.get('time_ago', 'just now')}",
                    "cta": {
                        "label": "Open File",
                        "href": latest_document.get("link") or url_for("reports_library"),
                    },
                }
            )
        except Exception:
            highlights.append(
                {
                    "icon": "fas fa-file-lines",
                    "label": "Latest Upload",
                    "value": latest_document.get("title", "New document"),
                    "detail": f"{latest_document.get('owner', 'Staff')} • {latest_document.get('time_ago', 'just now')}",
                    "cta": {
                        "label": "Open File",
                        "href": latest_document.get("link") or "#",
                    },
                }
            )

    if outstanding_count:
        try:
            highlights.append(
                {
                    "icon": "fas fa-bell",
                    "label": "Action Needed",
                    "value": f"{outstanding_count} item(s) awaiting acknowledgement",
                    "detail": None,
                    "cta": {
                        "label": "Review",
                        "href": url_for("reports_library"),
                    },
                }
            )
        except Exception:
            highlights.append(
                {
                    "icon": "fas fa-bell",
                    "label": "Action Needed",
                    "value": f"{outstanding_count} item(s) awaiting acknowledgement",
                    "detail": None,
                    "cta": {
                        "label": "Review",
                        "href": "#",
                    },
                }
            )

    if not highlights:
        highlights.append(
            {
                "icon": "fas fa-check-circle",
                "label": "All Clear",
                "value": "You're caught up on updates and action items.",
                "detail": None,
                "cta": None,
            }
        )

    return highlights


def build_performance_snapshot() -> Dict[str, Any]:
    """Build performance snapshot for the home page."""
    offense_values = [0.318, 0.327, 0.334, 0.329, 0.338, 0.345]
    training_values = [78, 80, 82, 84, 87, 90]

    offense_delta = offense_values[-1] - offense_values[-2]
    training_delta = training_values[-1] - training_values[-2]

    return {
        "offense_metric": {
            "value": f"{offense_values[-1]:.3f} xwOBA",
            "delta_label": f"{offense_delta:+.3f} vs last 7",
            "sparkline": build_sparkline_svg(offense_values, "#f97316"),
        },
        "training_metric": {
            "value": f"{training_values[-1]:.0f}% readiness",
            "delta_label": f"{training_delta:+.0f}% vs last week",
            "sparkline": build_sparkline_svg(training_values, "#22d3ee"),
        },
    }


def build_sparkline_svg(values: List[float], stroke: str) -> str:
    """Build SVG sparkline for performance metrics."""
    if not values:
        return ""

    width = max(len(values) - 1, 1) * 20
    height = 48
    min_val = min(values)
    max_val = max(values)
    spread = max(max_val - min_val, 0.0001)

    coords = []
    for idx, value in enumerate(values):
        x = (width / (len(values) - 1)) * idx if len(values) > 1 else width / 2
        y = height - ((value - min_val) / spread) * height
        coords.append(f"{x:.2f},{y:.2f}")

    points = " ".join(coords)
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" aria-hidden="true">'
        f'<polyline fill="none" stroke="{stroke}" stroke-width="3" points="{points}" stroke-linecap="round"/>'
        "</svg>"
    )


def load_journal_preview(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Load journal preview for the home page."""
    if not PlayerDB or not user:
        return sample_journal_entries()

    entries: List[Dict[str, Any]] = []
    db = None
    try:
        db = PlayerDB()
        rows = db.list_journal_entries(user_id=user.get("id"), limit=3)
    except Exception as exc:
        logger.warning(f"Warning fetching journal entries: {exc}")
        rows = []
    finally:
        if db:
            db.close()

    if not rows:
        return sample_journal_entries()

    for row in rows:
        entry_date = row.get("entry_date") or ""
        try:
            parsed_date = datetime.strptime(entry_date, "%Y-%m-%d")
            date_label = parsed_date.strftime("%b %d")
        except Exception:
            date_label = entry_date or "Recent"

        body = (row.get("body") or "").strip()
        preview = textwrap.shorten(body, width=180, placeholder="…") if body else "Notes captured."
        title = (row.get("title") or "Training reflections").strip()

        entries.append({
            "title": title,
            "date": date_label,
            "preview": preview,
            "reply": None,
        })

    return entries


def sample_journal_entries() -> List[Dict[str, Any]]:
    """Return sample journal entries when database is unavailable."""
    return [
        {
            "title": "Game 3 vs LAD — at-bat notes",
            "date": "Jun 10",
            "preview": "Saw their setup man three times — slider start up, finish below barrel. Staying through the middle with shorter gather helped.",
            "reply": {
                "coach_name": "Ramirez",
                "text": "Keep that gather—add fastball machine reps tomorrow with same cue.",
            },
        },
        {
            "title": "Bullpen touch & feel",
            "date": "Jun 09",
            "preview": "Good carry when I stayed stacked. Focus for next pen: tempo after leg lift and staying tall through release.",
            "reply": None,
        },
    ]


def load_resource_links(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Load resource links for the home page."""
    try:
        team_abbr = determine_user_team(user)
        notes = _collect_staff_notes(team_abbr=team_abbr, limit=4)
    except Exception as exc:
        logger.warning(f"Warning loading resources: {exc}")
        notes = []

    if notes:
        resources = []
        for note in notes:
            tags = note.get("tags") or []
            category = " • ".join(tags) if tags else "Staff note"
            try:
                resources.append({
                    "title": note.get("title") or "Staff update",
                    "category": category,
                    "link": url_for("gameday") + f"#staff-note-{note.get('id')}",
                })
            except Exception:
                resources.append({
                    "title": note.get("title") or "Staff update",
                    "category": category,
                    "link": "#",
                })
        return resources

    return sample_resources()


def sample_resources() -> List[Dict[str, Any]]:
    """Return sample resources when database is unavailable."""
    try:
        return [
            {
                "title": "Recovery: 24-hour travel reset",
                "category": "Recovery",
                "link": url_for("nutrition"),
            },
            {
                "title": "Mobility primer — lower half",
                "category": "Movement",
                "link": url_for("workouts"),
            },
            {
                "title": "Approach dashboard — LHP game plan",
                "category": "Video",
                "link": url_for("visuals"),
            },
        ]
    except Exception:
        return [
            {
                "title": "Recovery: 24-hour travel reset",
                "category": "Recovery",
                "link": "#",
            },
            {
                "title": "Mobility primer — lower half",
                "category": "Movement",
                "link": "#",
            },
            {
                "title": "Approach dashboard — LHP game plan",
                "category": "Video",
                "link": "#",
            },
        ]


def load_support_contacts() -> List[Dict[str, Any]]:
    """Load support contacts for the home page."""
    return sample_support_contacts()


def sample_support_contacts() -> List[Dict[str, Any]]:
    """Return sample support contacts."""
    try:
        return [
            {
                "name": "Jordan Lee",
                "role": "Hitting Coach",
                "contact_label": "Message",
                "contact_link": "mailto:jlee@sequencebiolab.com",
                "photo": None,
            },
            {
                "name": "Morgan Patel",
                "role": "Performance Lead",
                "contact_label": "Call",
                "contact_link": "tel:+15555551212",
                "photo": None,
            },
            {
                "name": "Avery Chen",
                "role": "Nutrition",
                "contact_label": "Check-in",
                "contact_link": url_for("nutrition"),
                "photo": None,
            },
        ]
    except Exception:
        return [
            {
                "name": "Jordan Lee",
                "role": "Hitting Coach",
                "contact_label": "Message",
                "contact_link": "mailto:jlee@sequencebiolab.com",
                "photo": None,
            },
            {
                "name": "Morgan Patel",
                "role": "Performance Lead",
                "contact_label": "Call",
                "contact_link": "tel:+15555551212",
                "photo": None,
            },
            {
                "name": "Avery Chen",
                "role": "Nutrition",
                "contact_label": "Check-in",
                "contact_link": "#",
                "photo": None,
            },
        ]


def _format_news_time(date_str: Optional[str]) -> str:
    """Format news date to human-readable time ago."""
    if not date_str:
        return "Recently"
    
    try:
        # Try parsing various date formats
        news_date = None
        # Try dateutil first
        try:
            from dateutil import parser
            news_date = parser.parse(date_str)
        except (ImportError, Exception):
            # Fallback to datetime.strptime for common formats
            date_formats = [
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%m/%d/%Y",
            ]
            for fmt in date_formats:
                try:
                    news_date = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue
        
        if not news_date:
            return "Recently"
        
        now = datetime.now(timezone.utc)
        if news_date.tzinfo is None:
            news_date = news_date.replace(tzinfo=timezone.utc)
        
        delta = now - news_date
        days = delta.days
        total_seconds = delta.total_seconds()
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        
        if days == 0:
            if total_seconds < 60:
                return "Just now"
            elif hours == 0:
                return f"{minutes} min{'s' if minutes != 1 else ''} ago"
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif days == 1:
            return "Yesterday"
        elif days < 7:
            return f"{days} days ago"
        elif days < 30:
            weeks = days // 7
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        else:
            months = days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
    except Exception:
        return "Recently"


def _get_news_icon(category: str) -> str:
    """Get icon class based on news category."""
    category_lower = category.lower()
    if "video" in category_lower or "highlight" in category_lower:
        return "fas fa-video"
    elif "injury" in category_lower or "health" in category_lower:
        return "fas fa-heartbeat"
    elif "trade" in category_lower or "transaction" in category_lower:
        return "fas fa-exchange-alt"
    elif "performance" in category_lower or "stats" in category_lower:
        return "fas fa-trophy"
    elif "interview" in category_lower:
        return "fas fa-microphone"
    else:
        return "fas fa-newspaper"


# Player news loading is complex and involves RSS feeds
def load_player_news(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Load 2 player-specific and 2 league-wide news articles."""
    first_name = (user.get("first_name") or "").strip()
    last_name = (user.get("last_name") or "").strip()
    
    if not first_name or not last_name:
        return []
    
    player_name = f"{first_name} {last_name}"
    
    # Check cache first (5 minute TTL for fast repeated loads)
    cache_key = f"news_{player_name}"
    cached = cache_service.get(CACHE_PLAYER_NEWS, cache_key)
    if cached is not None:
        return cached
    
    player_news_items = []
    league_news_items = []
    
    # Helper function to check if image URL is good (not Google proxy, etc.)
    def is_good_image_url(url):
        if not url:
            return False
        # Skip Google proxy images
        if 'googleusercontent.com' in url or 'google.com' in url:
            return False
        # Skip data URIs (too small usually)
        if url.startswith('data:'):
            return False
        # Skip very small images
        if any(skip in url.lower() for skip in ['icon', 'logo', 'avatar', 'thumb', '16x16', '32x32']):
            # But allow if it's clearly an article image
            if any(allow in url.lower() for allow in ['article', 'news', 'story', 'feature', 'hero', 'main']):
                return True
            return False
        return True
    
    # Helper function to parse date for sorting (newest first)
    def parse_date_for_sort(date_str):
        if not date_str:
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            from dateutil import parser
            parsed = parser.parse(date_str)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (ImportError, Exception):
            # Fallback to datetime.strptime for common formats
            date_formats = [
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%m/%d/%Y",
            ]
            for fmt in date_formats:
                try:
                    parsed = datetime.strptime(date_str, fmt)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return parsed
                except ValueError:
                    continue
        return datetime.min.replace(tzinfo=timezone.utc)
    
    # Helper function to fetch image for a news item (called only for selected items)
    def fetch_news_image(link, entry=None, headers=None):
        """Fetch image URL for a news item from RSS feed only. Returns None if no good image found."""
        if not entry:
            return None
        
        image_url = None
        
        # Use RSS feed images only (skip slow article page fetching)
        # Try media_content
        if entry.get('media_content'):
            media = entry.get('media_content', [])
            if isinstance(media, list) and len(media) > 0:
                media_item = media[0]
                candidate = None
                if isinstance(media_item, dict):
                    candidate = media_item.get('url')
                elif isinstance(media_item, str):
                    candidate = media_item
                if candidate and is_good_image_url(candidate):
                    image_url = candidate
        
        # Try media_thumbnail
        if not image_url and entry.get('media_thumbnail'):
            thumb = entry.get('media_thumbnail', [])
            if isinstance(thumb, list) and len(thumb) > 0:
                thumb_item = thumb[0]
                candidate = None
                if isinstance(thumb_item, dict):
                    candidate = thumb_item.get('url')
                elif isinstance(thumb_item, str):
                    candidate = thumb_item
                if candidate and is_good_image_url(candidate):
                    image_url = candidate
        
        # Try to extract from summary/description HTML
        if not image_url:
            summary_html = entry.get('summary', entry.get('description', ''))
            if summary_html and '<img' in summary_html:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(summary_html, 'html.parser')
                    for img_tag in soup.find_all('img'):
                        candidate = img_tag.get('src')
                        if candidate:
                            # Handle relative URLs
                            if not candidate.startswith('http'):
                                if candidate.startswith('//'):
                                    candidate = 'https:' + candidate
                                elif candidate.startswith('/'):
                                    try:
                                        from urllib.parse import urlparse
                                        parsed = urlparse(link)
                                        candidate = f"{parsed.scheme}://{parsed.netloc}{candidate}"
                                    except:
                                        continue
                            
                            if is_good_image_url(candidate):
                                image_url = candidate
                                break
                except:
                    pass
        
        # If we only have a Google proxy image, set to None to use fallback icon
        if image_url and not is_good_image_url(image_url):
            image_url = None
        
        return image_url
    
    try:
        import feedparser
        from bs4 import BeautifulSoup
        
        # First, try Google News - fetch with requests first, then parse
        try:
            search_queries = [
                f"{player_name}",
                f"{last_name} baseball",
                f"{first_name} {last_name} MLB",
            ]
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            for query in search_queries:
                if len(player_news_items) >= 2:
                    break
                try:
                    # Fetch RSS feed with requests first
                    google_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en&gl=US&ceid=US:en"
                    response = requests.get(google_url, headers=headers, timeout=10, allow_redirects=True)
                    
                    if response.status_code == 200:
                        # Parse the XML content
                        feed = feedparser.parse(response.content)
                        
                        if feed.entries and len(feed.entries) > 0:
                            # Collect all matching entries first, then sort by date
                            matching_entries = []
                            
                            for entry in feed.entries[:20]:
                                title = entry.get('title', '')
                                # Clean Google News title (remove " - Source" suffix)
                                if ' - ' in title:
                                    title_parts = title.split(' - ')
                                    title = ' - '.join(title_parts[:-1])  # Remove last part (source)
                                
                                summary = entry.get('summary', entry.get('description', ''))
                                link = entry.get('link', '#')
                                published = entry.get('published', entry.get('updated', ''))
                                
                                # More lenient matching
                                search_text = (title + " " + summary).lower()
                                player_lower = player_name.lower()
                                last_lower = last_name.lower()
                                
                                # Match if player name or last name appears
                                if (player_lower in search_text or 
                                    last_lower in search_text or
                                    (first_name.lower() in search_text and last_lower in search_text)):
                                    
                                    # Skip duplicates
                                    if (any(existing.get('title', '').lower().startswith(title.lower()[:50]) for existing in player_news_items) or
                                        any(existing.get('title', '').lower().startswith(title.lower()[:50]) for existing in matching_entries)):
                                        continue
                                    
                                    # Determine category
                                    category = "MLB News"
                                    if any(word in search_text for word in ['video', 'highlight', 'watch', 'replay']):
                                        category = "Video Analysis"
                                    elif any(word in search_text for word in ['stat', 'performance', 'batting', 'hitting', 'home run', 'homer']):
                                        category = "Performance"
                                    elif any(word in search_text for word in ['injury', 'health', 'disabled list', 'dl']):
                                        category = "Health"
                                    
                                    # Store basic info first
                                    matching_entries.append({
                                        "category": category,
                                        "title": title[:100] + "..." if len(title) > 100 else title,
                                        "description": (summary[:150] + "..." if len(summary) > 150 else summary) or "Read more...",
                                        "published_date": published,
                                        "link": link,
                                        "icon": _get_news_icon(category),
                                        "type": "player",
                                        "entry": entry,
                                    })
                            
                            # Sort matching entries by date (newest first) and take top 2
                            if matching_entries:
                                matching_entries.sort(
                                    key=lambda x: parse_date_for_sort(x.get("published_date", "")),
                                    reverse=True
                                )
                                # Add up to 2 items
                                needed = 2 - len(player_news_items)
                                selected_entries = matching_entries[:needed]
                                
                                # Now fetch images only for the selected items
                                for item in selected_entries:
                                    image_url = fetch_news_image(item["link"], item.get("entry"), headers)
                                    item.pop("entry", None)
                                    item["image"] = image_url
                                    item["time_ago"] = _format_news_time(item["published_date"])
                                    item.pop("published_date", None)
                                
                                player_news_items.extend(selected_entries)
                                
                except Exception as e:
                    logger.warning(f"Warning: Could not fetch Google News for query '{query}': {e}")
                    continue
        except Exception as e:
            logger.warning(f"Warning: Could not fetch Google News: {e}")
        
        # Now fetch league-wide news (2 articles)
        try:
            # Fetch general MLB news
            league_queries = [
                "MLB news",
                "Major League Baseball",
                "MLB latest",
            ]
            
            for query in league_queries:
                if len(league_news_items) >= 2:
                    break
                try:
                    google_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en&gl=US&ceid=US:en"
                    response = requests.get(google_url, headers=headers, timeout=10, allow_redirects=True)
                    
                    if response.status_code == 200:
                        feed = feedparser.parse(response.content)
                        
                        if feed.entries and len(feed.entries) > 0:
                            # Collect all matching entries first, then sort by date
                            matching_entries = []
                            
                            for entry in feed.entries[:20]:
                                title = entry.get('title', '')
                                # Clean Google News title
                                if ' - ' in title:
                                    title_parts = title.split(' - ')
                                    title = ' - '.join(title_parts[:-1])
                                
                                summary = entry.get('summary', entry.get('description', ''))
                                link = entry.get('link', '#')
                                published = entry.get('published', entry.get('updated', ''))
                                
                                # Skip if it's about the player (we want league-wide only)
                                search_text = (title + " " + summary).lower()
                                player_lower = player_name.lower()
                                last_lower = last_name.lower()
                                
                                if (player_lower in search_text or 
                                    last_lower in search_text or
                                    (first_name.lower() in search_text and last_lower in search_text)):
                                    continue  # Skip player-specific news
                                
                                # Skip duplicates
                                if (any(existing.get('title', '').lower().startswith(title.lower()[:50]) for existing in league_news_items) or
                                    any(existing.get('title', '').lower().startswith(title.lower()[:50]) for existing in matching_entries)):
                                    continue
                                
                                # Determine category
                                category = "MLB News"
                                if any(word in search_text for word in ['video', 'highlight', 'watch', 'replay']):
                                    category = "Video Analysis"
                                elif any(word in search_text for word in ['stat', 'performance', 'batting', 'hitting']):
                                    category = "Performance"
                                
                                # Store basic info first
                                matching_entries.append({
                                    "category": category,
                                    "title": title[:100] + "..." if len(title) > 100 else title,
                                    "description": (summary[:150] + "..." if len(summary) > 150 else summary) or "Read more...",
                                    "published_date": published,
                                    "link": link,
                                    "icon": _get_news_icon(category),
                                    "type": "league",
                                    "entry": entry,
                                })
                            
                            # Sort matching entries by date (newest first) and take top 2
                            if matching_entries:
                                matching_entries.sort(
                                    key=lambda x: parse_date_for_sort(x.get("published_date", "")),
                                    reverse=True
                                )
                                # Add up to 2 items
                                needed = 2 - len(league_news_items)
                                selected_entries = matching_entries[:needed]
                                
                                # Now fetch images only for the selected items
                                for item in selected_entries:
                                    image_url = fetch_news_image(item["link"], item.get("entry"), headers)
                                    item.pop("entry", None)
                                    item["image"] = image_url
                                    item["time_ago"] = _format_news_time(item["published_date"])
                                    item.pop("published_date", None)
                                
                                league_news_items.extend(selected_entries)
                                
                except Exception as e:
                    logger.warning(f"Warning: Could not fetch league news for query '{query}': {e}")
                    continue
        except Exception as e:
            logger.warning(f"Warning: Could not fetch league news: {e}")
        
        # Try multiple RSS feeds as backup for player news
        if len(player_news_items) < 2:
            rss_urls = [
                "https://www.espn.com/espn/rss/mlb/news",
                "https://feeds.feedburner.com/mlb/rss",
            ]
            
            rss_headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            for rss_url in rss_urls:
                if len(player_news_items) >= 2:
                    break
                try:
                    feed = feedparser.parse(rss_url)
                    if feed.entries and len(feed.entries) > 0:
                        # Collect all matching entries first, then sort by date
                        matching_entries = []
                        
                        for entry in feed.entries[:30]:
                            title = entry.get('title', '')
                            summary = entry.get('summary', entry.get('description', ''))
                            link = entry.get('link', '#')
                            published = entry.get('published', entry.get('updated', ''))
                            
                            search_text = (title + " " + summary).lower()
                            player_lower = player_name.lower()
                            last_lower = last_name.lower()
                            
                            if (player_lower in search_text or 
                                last_lower in search_text or
                                (first_name.lower() in search_text and last_lower in search_text)):
                                
                                # Skip duplicates
                                if (any(existing.get('title', '').lower().startswith(title.lower()[:50]) for existing in player_news_items) or
                                    any(existing.get('title', '').lower().startswith(title.lower()[:50]) for existing in matching_entries)):
                                    continue
                                
                                category = "MLB News"
                                if any(word in search_text for word in ['video', 'highlight', 'watch', 'replay']):
                                    category = "Video Analysis"
                                elif any(word in search_text for word in ['stat', 'performance', 'batting', 'hitting', 'home run', 'homer']):
                                    category = "Performance"
                                
                                # Store basic info first
                                matching_entries.append({
                                    "category": category,
                                    "title": title[:100] + "..." if len(title) > 100 else title,
                                    "description": (summary[:150] + "..." if len(summary) > 150 else summary) or "Read more...",
                                    "published_date": published,
                                    "link": link,
                                    "icon": _get_news_icon(category),
                                    "type": "player",
                                    "entry": entry,
                                })
                        
                        # Sort matching entries by date (newest first) and take top items needed
                        if matching_entries:
                            matching_entries.sort(
                                key=lambda x: parse_date_for_sort(x.get("published_date", "")),
                                reverse=True
                            )
                            # Add up to 2 items
                            needed = 2 - len(player_news_items)
                            selected_entries = matching_entries[:needed]
                            
                            # Now fetch images only for the selected items
                            for item in selected_entries:
                                image_url = fetch_news_image(item["link"], item.get("entry"), rss_headers)
                                item.pop("entry", None)
                                item["image"] = image_url
                                item["time_ago"] = _format_news_time(item["published_date"])
                                item.pop("published_date", None)
                            
                            player_news_items.extend(selected_entries)
                            
                except Exception as e:
                    logger.warning(f"Warning: Could not parse RSS feed {rss_url}: {e}")
                    continue
        
    except ImportError as e:
        logger.warning(f"Warning: Missing required library for news fetching: {e}")
    except Exception as e:
        logger.warning(f"Warning: Error loading player news for {player_name}: {e}")
        import traceback
        traceback.print_exc()
    
    # Combine player and league news: 2 player-specific, 2 league-wide
    combined_news = player_news_items[:2] + league_news_items[:2]
    result = combined_news if combined_news else []
    
    # Cache the result for 5 minutes (300 seconds) for fast repeated loads
    cache_service.set(CACHE_PLAYER_NEWS, cache_key, result, 300)
    
    return result


def build_player_home_context(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the complete home page context for a user."""
    if not user:
        return {}

    next_series = load_next_series_snapshot(user)
    latest_document, deliverables, outstanding_count = load_player_deliverables(user)
    performance = build_performance_snapshot()
    journal_entries = load_journal_preview(user)
    resources = load_resource_links(user)
    support_team = load_support_contacts()
    focus_highlights = build_focus_highlights(next_series, latest_document, outstanding_count)
    player_news = load_player_news(user)
    # Use local MLB logo file
    try:
        mlb_logo_url = url_for('static', filename='MLB_Logo.png')
    except Exception:
        mlb_logo_url = "/static/MLB_Logo.png"
    schedule_calendar = load_schedule_calendar(user)
    # Ensure schedule_calendar is always a list, never None or Undefined
    if not isinstance(schedule_calendar, list):
        schedule_calendar = []

    return {
        "hero_message": None,
        "next_series": next_series or {},  # Ensure it's always a dict, never None
        "latest_document": latest_document,
        "deliverables": deliverables,
        "outstanding_count": outstanding_count,
        "performance": performance,
        "journal_entries": journal_entries,
        "resources": resources,
        "support_team": support_team,
        "focus_highlights": focus_highlights,
        "player_news": player_news,
        "mlb_logo_url": mlb_logo_url,
        "schedule_calendar": schedule_calendar,
    }


def purge_concluded_series_documents(reference_ts: Optional[float] = None) -> None:
    """Remove player documents tied to series that have already finished."""
    if not PlayerDB:
        return
    try:
        db = PlayerDB()
        if reference_ts is None:
            reference_ts = datetime.now().timestamp() - Config.SERIES_AUTO_DELETE_GRACE_SECONDS
        expired_docs = db.list_expired_player_documents(reference_ts)
        for doc in expired_docs:
            deleted = db.delete_player_document(doc["id"])
            if not deleted:
                continue
            db.record_player_document_event(
                player_id=deleted["player_id"],
                filename=deleted["filename"],
                action="auto_delete_series",
                performed_by=None,
            )
            file_path = Path(deleted.get("path") or "")
            if file_path.exists() and file_path.is_file():
                try:
                    file_path.unlink()
                except OSError as exc:
                    logger.warning(f"Warning removing expired document file {file_path}: {exc}")
        db.close()
    except Exception as exc:
        logger.warning(f"Warning purging expired player documents: {exc}")


def schedule_auto_reports(games: List[Dict[str, Any]], team_abbr: Optional[str]) -> None:
    """Schedule auto reports for upcoming games."""
    if not games:
        return
    try:
        from app.services.report_service import maybe_trigger_report
        from app.utils.helpers import current_player_full_name, resolve_default_season_start
        
        player_name = current_player_full_name()
        if not player_name:
            return
        season_start = resolve_default_season_start()
        for game in games:
            maybe_trigger_report(game, team_abbr, player_name, season_start)
    except Exception as exc:
        logger.warning(f"Warning scheduling auto reports: {exc}")


def collect_recent_reports(limit: int = 5) -> List[Dict[str, Any]]:
    """Return recent generated reports with metadata."""
    reports = []
    try:
        pdf_files = sorted(Config.PDF_OUTPUT_DIR.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception as exc:
        logger.warning(f"Warning reading reports directory: {exc}")
        return reports

    for pdf in pdf_files[:limit]:
        try:
            mtime = datetime.fromtimestamp(pdf.stat().st_mtime).strftime("%b %d, %Y %I:%M %p")
        except Exception:
            mtime = "Unknown"

        reports.append({
            "title": pdf.stem.replace("_", " "),
            "generated_at": mtime,
            "filename": pdf.name,
        })
    return reports


def attach_reports_to_games(
    games: List[Dict[str, Any]],
    reports: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Annotate each upcoming game with any available scouting reports."""
    from app.constants import REPORT_OPP_PATTERN
    
    report_map: Dict[str, List[Dict[str, Any]]] = {}
    for report in reports:
        filename = report.get("filename") or ""
        match = REPORT_OPP_PATTERN.search(filename)
        if not match:
            continue
        abbr = match.group(1).upper()
        payload = {
            "title": report.get("title"),
            "generated_at": report.get("generated_at"),
            "url": report.get("url"),
        }
        report_map.setdefault(abbr, []).append(payload)

    for game in games:
        abbr = game.get("opponent_abbr")
        game["reports"] = report_map.get(abbr, [])
    return games

