"""
Schedule service for MLB schedule data
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone, date
from functools import lru_cache
import statsapi
import sys
from pathlib import Path
from app.config import Config
from app.services.cache_service import cache_service, CACHE_UPCOMING_GAMES
from app.utils.formatters import coerce_utc_datetime, extract_game_datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
try:
    from next_opponent import next_games
except ImportError:
    next_games = None


@lru_cache(maxsize=1)
def _team_directory() -> Dict[int, Dict[str, str]]:
    """Cache team metadata keyed by team id for quick lookups."""
    try:
        teams = statsapi.get("teams", {"sportId": 1}).get("teams", [])
    except Exception:
        return {}
    directory: Dict[int, Dict[str, str]] = {}
    for entry in teams:
        team_id = entry.get("id")
        if not team_id:
            continue
        abbr = entry.get("abbreviation") or entry.get("fileCode") or entry.get("teamCode")
        directory[int(team_id)] = {
            "abbr": (abbr or "").upper(),
            "name": entry.get("teamName"),
        }
    return directory


def team_abbr_from_id(team_id: Optional[int]) -> Optional[str]:
    """Get team abbreviation from team ID."""
    if not team_id:
        return None
    return (_team_directory().get(int(team_id)) or {}).get("abbr")


def build_mock_upcoming_games(team_abbr: Optional[str], limit: int = 5) -> List[Dict[str, Any]]:
    """Generate a deterministic mock schedule for local testing."""
    now = datetime.now().astimezone()
    base_first_pitch = now.replace(hour=19, minute=10, second=0, microsecond=0)

    blueprint = [
        {
            "days_offset": -6,
            "status": "Final",
            "opponent": "Miami Marlins",
            "opponent_abbr": "MIA",
            "opponent_id": 146,
            "home": False,
            "venue": "loanDepot park",
            "series": "3-game series",
            "game_pk": 499900,
            "probable_pitchers": ["Jesús Luzardo"],
        },
        {
            "days_offset": -5,
            "status": "Final",
            "opponent": "Miami Marlins",
            "opponent_abbr": "MIA",
            "opponent_id": 146,
            "home": False,
            "venue": "loanDepot park",
            "series": "3-game series",
            "game_pk": 499901,
            "probable_pitchers": ["Sandy Alcantara"],
        },
        {
            "days_offset": 0,
            "status": "In Progress",
            "opponent": "Washington Nationals",
            "opponent_abbr": "WSH",
            "opponent_id": 120,
            "home": True,
            "venue": "Citi Field",
            "series": "Division matchup",
            "game_pk": 500000,
            "probable_pitchers": ["Josiah Gray"],
        },
        {
            "days_offset": 1,
            "status": "Pre-Game",
            "opponent": "Washington Nationals",
            "opponent_abbr": "WSH",
            "opponent_id": 120,
            "home": True,
            "venue": "Citi Field",
            "series": "Division matchup",
            "game_pk": 500001,
            "probable_pitchers": ["MacKenzie Gore"],
        },
        {
            "days_offset": 2,
            "status": "Scheduled",
            "opponent": "Philadelphia Phillies",
            "opponent_abbr": "PHI",
            "opponent_id": 143,
            "home": True,
            "venue": "Citi Field",
            "series": "3-game series",
            "game_pk": 500100,
            "probable_pitchers": ["Zack Wheeler"],
        },
        {
            "days_offset": 3,
            "status": "Scheduled",
            "opponent": "Philadelphia Phillies",
            "opponent_abbr": "PHI",
            "opponent_id": 143,
            "home": True,
            "venue": "Citi Field",
            "series": "3-game series",
            "game_pk": 500101,
            "probable_pitchers": ["Aaron Nola"],
        },
        {
            "days_offset": 5,
            "status": "Scheduled",
            "opponent": "Atlanta Braves",
            "opponent_abbr": "ATL",
            "opponent_id": 144,
            "home": False,
            "venue": "Truist Park",
            "series": "Division matchup",
            "game_pk": 500200,
            "probable_pitchers": ["Max Fried"],
        },
        {
            "days_offset": 6,
            "status": "Scheduled",
            "opponent": "Atlanta Braves",
            "opponent_abbr": "ATL",
            "opponent_id": 144,
            "home": False,
            "venue": "Truist Park",
            "series": "Division matchup",
            "game_pk": 500201,
            "probable_pitchers": ["Chris Sale"],
        },
    ]

    formatted: List[Dict[str, Any]] = []
    for entry in blueprint[:max(limit, len(blueprint))]:
        game_dt = base_first_pitch + timedelta(days=entry["days_offset"])
        formatted_time = game_dt.strftime("%I:%M %p %Z") if game_dt.tzinfo else game_dt.strftime("%I:%M %p")
        formatted.append({
            "date": game_dt.strftime("%a, %b %d"),
            "time": formatted_time,
            "opponent": entry["opponent"],
            "opponent_abbr": entry["opponent_abbr"],
            "opponent_id": entry["opponent_id"],
            "home": entry["home"],
            "venue": entry["venue"],
            "series": entry["series"],
            "status": entry["status"],
            "game_pk": entry["game_pk"],
            "probable_pitchers": entry["probable_pitchers"],
            "reports": [],
            "game_date_iso": game_dt.date().isoformat(),
            "game_datetime_iso": game_dt.astimezone(timezone.utc).isoformat(),
        })
    return formatted


def collect_upcoming_games(team_abbr: Optional[str], limit: int = 5) -> List[Dict[str, Any]]:
    """Return a formatted list of upcoming games for the given team."""
    use_mock = Config.USE_MOCK_SCHEDULE
    cache_key = ("MOCK" if use_mock else "LIVE", (team_abbr or "").upper(), limit)
    cached = cache_service.get(CACHE_UPCOMING_GAMES, cache_key)
    if cached is not None:
        return cached

    if use_mock:
        formatted_mock = build_mock_upcoming_games(team_abbr, limit)
        cache_service.set(CACHE_UPCOMING_GAMES, cache_key, formatted_mock, ttl_seconds=60)
        return formatted_mock

    if not next_games:
        return []

    try:
        games = next_games(team_abbr, days_ahead=14)
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Warning fetching upcoming games: {exc}")
        cache_service.set(CACHE_UPCOMING_GAMES, cache_key, [], ttl_seconds=120)
        return []

    formatted = []
    for game in games[:limit]:
        date_str = game.get("game_date")
        display_date = date_str
        display_time = "TBD"
        if date_str:
            try:
                display_date = datetime.fromisoformat(date_str).strftime("%a, %b %d")
            except Exception:
                pass

        game_time = game.get("game_datetime")
        if game_time:
            try:
                display_time = datetime.fromisoformat(game_time.replace("Z", "+00:00")).astimezone().strftime("%I:%M %p %Z")
            except Exception:
                display_time = "TBD"

        team_abbr_code = team_abbr_from_id(game.get("opponent_id"))
        probables = [
            p.get("name")
            for p in (game.get("probable_pitchers") or [])
            if p.get("name")
        ]
        formatted.append({
            "date": display_date,
            "time": display_time,
            "opponent": game.get("opponent_name"),
            "opponent_abbr": team_abbr_code,
            "opponent_id": game.get("opponent_id"),
            "home": game.get("is_home"),
            "venue": game.get("venue"),
            "series": game.get("series_description"),
            "status": game.get("status"),
            "game_pk": game.get("game_pk"),
            "probable_pitchers": probables,
            "reports": [],
            "game_date_iso": date_str,
            "game_datetime_iso": game_time,
        })
    cache_service.set(CACHE_UPCOMING_GAMES, cache_key, formatted, ttl_seconds=300)
    return formatted


def collect_series_for_team(team_abbr: Optional[str], days_ahead: int = 14) -> List[Dict[str, Any]]:
    """Group schedule into opponent series for selection purposes."""
    if not team_abbr:
        return []

    games: List[Dict[str, Any]] = []
    use_mock = Config.USE_MOCK_SCHEDULE

    if use_mock:
        raw = build_mock_upcoming_games(team_abbr, limit=20)
        for item in raw:
            try:
                games.append({
                    "game_date": item.get("game_date_iso") or item.get("date"),
                    "game_datetime": item.get("game_datetime_iso"),
                    "opponent_id": item.get("opponent_id"),
                    "opponent_name": item.get("opponent"),
                    "is_home": item.get("home"),
                    "venue": item.get("venue"),
                    "series_description": item.get("series"),
                    "status": item.get("status"),
                })
            except Exception:
                continue
    else:
        if not next_games:
            return []
        try:
            games = next_games(team_abbr, days_ahead=days_ahead, include_started=True)
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Warning fetching series schedule: {exc}")
            games = []

    if not games:
        return []

    chunks: List[List[Dict[str, Any]]] = []
    current_chunk: List[Dict[str, Any]] = []
    last_opponent = None
    for game in games:
        opponent = game.get("opponent_id")
        if last_opponent is None or opponent == last_opponent:
            current_chunk.append(game)
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = [game]
        last_opponent = opponent
    if current_chunk:
        chunks.append(current_chunk)

    now_ts = datetime.now(timezone.utc).timestamp()
    out: List[Dict[str, Any]] = []

    for chunk in chunks:
        if not chunk:
            continue
        first_game = chunk[0]
        opponent_id = first_game.get("opponent_id")
        opponent_name = first_game.get("opponent_name")
        opponent_abbr = team_abbr_from_id(opponent_id)

        game_dates = [g.get("game_date") for g in chunk if g.get("game_date")]
        if not game_dates:
            continue

        try:
            start_dt = datetime.fromisoformat(min(game_dates))
            end_dt = datetime.fromisoformat(max(game_dates))
        except Exception:
            continue

        start_ts = start_dt.timestamp()
        end_ts = end_dt.timestamp() + (24 * 60 * 60)

        range_label = start_dt.strftime("%b %d")
        if start_dt.date() != end_dt.date():
            range_label += f" – {end_dt.strftime('%b %d')}"

        status = "upcoming"
        if now_ts > end_ts:
            status = "completed"
        elif now_ts >= start_ts:
            status = "active"

        home_label = "Home vs" if first_game.get("is_home") else "Road @"
        series_label = f"{home_label} {opponent_name}".strip()

        # Get the first game's datetime for countdown clock
        first_game_datetime = first_game.get("game_datetime")
        # If game_datetime is missing, try to construct it from game_date
        if not first_game_datetime:
            try:
                first_game_date = first_game.get("game_date")
                if first_game_date:
                    # Use a default game time (7:10 PM local time)
                    if isinstance(first_game_date, str):
                        date_obj = datetime.fromisoformat(first_game_date).date()
                    else:
                        date_obj = first_game_date if isinstance(first_game_date, date) else datetime.combine(first_game_date, datetime.min.time()).date()
                    default_time = datetime.combine(date_obj, datetime.min.time().replace(hour=19, minute=10))
                    now_tz = datetime.now().astimezone().tzinfo
                    if default_time.tzinfo is None:
                        default_time = default_time.replace(tzinfo=now_tz)
                    first_game_datetime = default_time.isoformat()
            except Exception:
                first_game_datetime = None

        out.append({
            "id": f"{opponent_id}_{int(start_ts)}",
            "opponent_id": opponent_id,
            "opponent_name": opponent_name,
            "opponent_abbr": opponent_abbr,
            "is_home": bool(first_game.get("is_home")),
            "series_label": series_label,
            "series_description": first_game.get("series_description"),
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "range": range_label,
            "status": status,
            "game_count": len(chunk),
            "first_game_datetime": first_game_datetime,  # For countdown clock
        })

    out.sort(key=lambda item: item.get("start") or "")
    return out

