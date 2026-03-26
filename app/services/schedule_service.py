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
from app.utils.venue_timezones import format_game_time_venue

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
try:
    from next_opponent import next_games, next_games_aaa
except ImportError:
    next_games = None
    next_games_aaa = None


@lru_cache(maxsize=1)
def _team_directory() -> Dict[int, Dict[str, str]]:
    """Cache MLB team metadata keyed by team id for quick lookups."""
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


@lru_cache(maxsize=1)
def _aaa_team_directory() -> Dict[int, Dict[str, str]]:
    """Cache Triple-A team metadata keyed by team id for quick lookups."""
    try:
        teams = statsapi.get("teams", {"sportId": 11}).get("teams", [])
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
    """Get team abbreviation from team ID (checks MLB then AAA directories)."""
    if not team_id:
        return None
    result = (_team_directory().get(int(team_id)) or {}).get("abbr")
    if not result:
        result = (_aaa_team_directory().get(int(team_id)) or {}).get("abbr") or None
    return result


def build_mock_upcoming_games(team_abbr: Optional[str], limit: int = 5) -> List[Dict[str, Any]]:
    """Generate a deterministic mock schedule for local testing.

    IMPORTANT: This is intentionally team-dependent so different users (with different
    team_abbr) see different series in the admin uploader + gameday.
    """
    now = datetime.now().astimezone()
    base_first_pitch = now.replace(hour=19, minute=10, second=0, microsecond=0)

    team_key = (team_abbr or "NYM").strip().upper() or "NYM"
    # Real MLB team ids so team_abbr_from_id() resolves consistently.
    opponent_pool = [
        {"name": "Arizona Diamondbacks", "abbr": "ARI", "id": 109, "venue": "Chase Field"},
        {"name": "Atlanta Braves", "abbr": "ATL", "id": 144, "venue": "Truist Park"},
        {"name": "Baltimore Orioles", "abbr": "BAL", "id": 110, "venue": "Oriole Park at Camden Yards"},
        {"name": "Boston Red Sox", "abbr": "BOS", "id": 111, "venue": "Fenway Park"},
        {"name": "Chicago Cubs", "abbr": "CHC", "id": 112, "venue": "Wrigley Field"},
        {"name": "Cincinnati Reds", "abbr": "CIN", "id": 113, "venue": "Great American Ball Park"},
        {"name": "Cleveland Guardians", "abbr": "CLE", "id": 114, "venue": "Progressive Field"},
        {"name": "Houston Astros", "abbr": "HOU", "id": 117, "venue": "Minute Maid Park"},
        {"name": "Los Angeles Dodgers", "abbr": "LAD", "id": 119, "venue": "Dodger Stadium"},
        {"name": "Miami Marlins", "abbr": "MIA", "id": 146, "venue": "loanDepot park"},
        {"name": "New York Yankees", "abbr": "NYY", "id": 147, "venue": "Yankee Stadium"},
        {"name": "Philadelphia Phillies", "abbr": "PHI", "id": 143, "venue": "Citizens Bank Park"},
        {"name": "San Diego Padres", "abbr": "SD", "id": 135, "venue": "Petco Park"},
        {"name": "Seattle Mariners", "abbr": "SEA", "id": 136, "venue": "T-Mobile Park"},
        {"name": "Texas Rangers", "abbr": "TEX", "id": 140, "venue": "Globe Life Field"},
        {"name": "Washington Nationals", "abbr": "WSH", "id": 120, "venue": "Nationals Park"},
    ]

    # Deterministic team-based "randomness" (no RNG) so each team gets different opponents.
    seed = sum(ord(c) for c in team_key)
    start = seed % len(opponent_pool)

    def _opp(rel: int) -> Dict[str, Any]:
        return opponent_pool[(start + rel) % len(opponent_pool)]

    # Build a few short series (contiguous opponent_id) so collect_series_for_team() groups correctly.
    series_defs = [
        # Most recent past series (2 games)
        {"series_start": -2, "games": 2, "opp_rel": -1, "home": False, "statuses": ["Final", "Final"], "series": "2-game set"},
        # Current series (2 games)
        {"series_start": 0, "games": 2, "opp_rel": 0, "home": True, "statuses": ["In Progress", "Pre-Game"], "series": "Division matchup"},
        # Next upcoming (2 games)
        {"series_start": 3, "games": 2, "opp_rel": 1, "home": True, "statuses": ["Scheduled", "Scheduled"], "series": "2-game set"},
        # Another upcoming (3 games)
        {"series_start": 6, "games": 3, "opp_rel": 2, "home": False, "statuses": ["Scheduled", "Scheduled", "Scheduled"], "series": "3-game series"},
    ]

    blueprint: List[Dict[str, Any]] = []
    base_pk = 500000 + (seed % 1000) * 10
    pk_counter = 0
    for sdef in series_defs:
        opp = _opp(sdef["opp_rel"])
        for i in range(sdef["games"]):
            days_offset = int(sdef["series_start"]) + i
            status = sdef["statuses"][i] if i < len(sdef["statuses"]) else "Scheduled"
            blueprint.append({
                "days_offset": days_offset,
                "status": status,
                "opponent": opp["name"],
                "opponent_abbr": opp["abbr"],
                "opponent_id": opp["id"],
                "home": bool(sdef["home"]),
                "venue": opp["venue"] if not sdef["home"] else "Home Park",
                "series": sdef["series"],
                "game_pk": base_pk + pk_counter,
                "probable_pitchers": [],
            })
            pk_counter += 1

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
        venue = game.get("venue")
        display_time = format_game_time_venue(game_time, venue)

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
            "venue": venue,
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


def collect_series_for_team(team_abbr: Optional[str], days_ahead: int = 14, team_level: str = "MLB") -> List[Dict[str, Any]]:
    """Group schedule into opponent series for selection purposes."""
    if not team_abbr:
        return []

    games: List[Dict[str, Any]] = []
    use_mock = Config.USE_MOCK_SCHEDULE
    is_aaa = (team_level or "MLB").upper() == "AAA"

    if use_mock and not is_aaa:
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
        fetcher = next_games_aaa if is_aaa else next_games
        if not fetcher:
            return []
        try:
            games = fetcher(team_abbr, days_ahead=days_ahead, include_started=True)
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

