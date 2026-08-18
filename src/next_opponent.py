# src/next_opponent.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from functools import lru_cache
import logging
import statsapi  # pip install MLB-StatsAPI


logger = logging.getLogger(__name__)

# Resolve the common abbreviations locally. A cold Gameday request should not
# need a separate MLB metadata request before it can ask for the schedule.
_MLB_TEAM_IDS = {
    "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111, "CHC": 112,
    "CWS": 145, "CHW": 145, "CIN": 113, "CLE": 114, "COL": 115,
    "DET": 116, "HOU": 117, "KC": 118, "KCR": 118, "LAA": 108,
    "ANA": 108, "LAD": 119, "MIA": 146, "MIL": 158, "MIN": 142,
    "NYM": 121, "NYY": 147, "OAK": 133, "PHI": 143, "PIT": 134,
    "SD": 135, "SDP": 135, "SF": 137, "SFG": 137, "SEA": 136,
    "STL": 138, "TB": 139, "TBR": 139, "TEX": 140, "TOR": 141,
    "WSH": 120, "WSN": 120, "WAS": 120,
}

_AAA_TEAM_IDS = {
    "ABQ": 342, "BUF": 422, "CLT": 494, "CLB": 445, "COL": 445,
    "DUR": 234, "ELP": 4904, "GWN": 431, "IND": 484, "IOW": 451,
    "JAX": 564, "LHV": 1410, "LOU": 416, "LV": 400, "MEM": 235,
    "NAS": 556, "NOR": 568, "OKC": 238, "OMA": 541, "RNO": 2310,
    "ROC": 534, "RR": 102, "SAC": 105, "SL": 561, "STP": 1960,
    "SUG": 5434, "SWB": 531, "SYR": 552, "TAC": 529, "TOL": 512,
    "WOR": 533,
}

# ---------- Team index helpers ----------

def _build_team_index() -> Dict[str, int]:
    """
    Build a case-insensitive index mapping common keys (fileCode, abbreviation, names) -> teamId.
    """
    idx: Dict[str, int] = {}
    teams = statsapi.get('teams', {'sportId': 1})['teams']
    for t in teams:
        tid = t['id']
        keys = set()
        for k in (
            t.get('fileCode'),
            t.get('abbreviation'),
            t.get('teamName'),
            t.get('name'),
            t.get('clubName'),
            t.get('shortName'),
        ):
            if k:
                keys.add(k.upper())
        # also support city + team (e.g., "NEW YORK METS")
        city = t.get('venue', {}).get('city')
        if city and t.get('teamName'):
            keys.add(f"{city} {t['teamName']}".upper())
        for k in keys:
            idx[k] = tid
    return idx


@lru_cache(maxsize=1)
def _team_index() -> Dict[str, int]:
    """
    Lazy team index builder.

    IMPORTANT: Avoid network calls at import time so unit tests and offline
    environments can import this module safely.
    """
    return _build_team_index()

def _resolve_team_id(team_key: str) -> int:
    k = team_key.strip().upper()
    if k in _MLB_TEAM_IDS:
        return _MLB_TEAM_IDS[k]
    idx = _team_index()
    if k not in idx:
        raise ValueError(f"Unrecognized team key: {team_key!r}")
    return idx[k]

# ---------- AAA Team index helpers ----------

def _build_aaa_team_index() -> Dict[str, int]:
    """Build a case-insensitive index mapping keys -> teamId for Triple-A (sportId=11)."""
    idx: Dict[str, int] = {}
    teams = statsapi.get('teams', {'sportId': 11})['teams']
    for t in teams:
        tid = t['id']
        keys = set()
        for k in (
            t.get('fileCode'),
            t.get('abbreviation'),
            t.get('teamName'),
            t.get('name'),
            t.get('clubName'),
            t.get('shortName'),
        ):
            if k:
                keys.add(k.upper())
        city = t.get('venue', {}).get('city')
        if city and t.get('teamName'):
            keys.add(f"{city} {t['teamName']}".upper())
        for k in keys:
            idx[k] = tid
    return idx


@lru_cache(maxsize=1)
def _aaa_team_index() -> Dict[str, int]:
    """Lazy AAA team index builder."""
    return _build_aaa_team_index()


def _resolve_aaa_team_id(team_key: str) -> int:
    k = team_key.strip().upper()
    if k in _AAA_TEAM_IDS:
        return _AAA_TEAM_IDS[k]
    idx = _aaa_team_index()
    if k not in idx:
        raise ValueError(f"Unrecognized AAA team key: {team_key!r}")
    return idx[k]

# ---------- Core logic ----------

def _fetch_schedule(
    team_id: int,
    sport_id: int,
    query_start,
    query_end,
) -> Dict[str, Any]:
    """Fetch the minimal schedule shape needed by Gameday.

    ``statsapi.schedule`` hydrates broadcasts, media, decisions, linescores,
    and series status for every game. That response is unnecessarily large for
    Gameday and was slow enough on a cold Render instance to exceed the browser
    timeout. Keep the upstream request bounded and hydrate only probable
    pitchers.
    """
    try:
        return statsapi.get(
            "schedule",
            {
                "sportId": sport_id,
                "teamId": team_id,
                "startDate": query_start.isoformat(),
                "endDate": query_end.isoformat(),
                "hydrate": "probablePitcher(note)",
            },
            request_kwargs={"timeout": (3.05, 15)},
        ) or {}
    except Exception as exc:
        logger.warning("Schedule request failed for team %s: %s", team_id, exc)
        return {}


def _parse_schedule(
    payload: Dict[str, Any],
    team_id: int,
    *,
    include_started: bool,
) -> List[Dict[str, Any]]:
    """Normalize a raw MLB StatsAPI schedule response."""
    results: List[Dict[str, Any]] = []
    for date_entry in payload.get("dates") or []:
        fallback_date = date_entry.get("date")
        for game in date_entry.get("games") or []:
            teams = game.get("teams") or {}
            home = teams.get("home") or {}
            away = teams.get("away") or {}
            home_team = home.get("team") or {}
            away_team = away.get("team") or {}
            home_id = home_team.get("id")
            away_id = away_team.get("id")
            if home_id is None or away_id is None:
                continue

            status = ((game.get("status") or {}).get("detailedState") or "")
            if not include_started and status in ("Final", "Game Over"):
                continue

            is_home = int(home_id) == int(team_id)
            opponent = away if is_home else home
            opponent_team = away_team if is_home else home_team
            probable = opponent.get("probablePitcher") or {}
            probable_pitchers = []
            if probable.get("fullName"):
                entry = {"name": str(probable["fullName"])}
                if probable.get("id"):
                    entry["id"] = int(probable["id"])
                probable_pitchers.append(entry)

            game_datetime = game.get("gameDate")
            if game_datetime:
                try:
                    game_datetime = datetime.fromisoformat(
                        str(game_datetime).replace("Z", "+00:00")
                    ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    game_datetime = None

            game_date = fallback_date
            if not game_date and game_datetime:
                game_date = game_datetime[:10]
            if not game_date:
                continue

            results.append({
                "game_date": game_date,
                "game_datetime": game_datetime,
                "game_pk": game.get("gamePk"),
                "home_id": int(home_id),
                "home_name": home_team.get("name"),
                "away_id": int(away_id),
                "away_name": away_team.get("name"),
                "opponent_id": int(opponent_team.get("id")),
                "opponent_name": opponent_team.get("name"),
                "is_home": is_home,
                "venue": (game.get("venue") or {}).get("name"),
                "series_description": game.get("seriesDescription"),
                "status": status,
                "probable_pitchers": probable_pitchers,
                "game_type": game.get("gameType", "R"),
            })

    def _sort_key(item: Dict[str, Any]):
        raw = item.get("game_datetime") or item["game_date"]
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.max.replace(tzinfo=timezone.utc)

    results.sort(key=_sort_key)
    return results

def _probables_from_game(game: Dict[str, Any], team_id: int) -> List[Dict[str, Any]]:
    """
    Return a list of probable pitchers for the OPPONENT of `team_id` in this game.
    List length is usually 0 or 1 (MLB sometimes lists both if TBA changes).
    """
    home_id, away_id = game['home_id'], game['away_id']
    prob: List[Dict[str, Any]] = []

    # schedule dict keys commonly present in statsapi.schedule()
    # 'home_probable_pitcher', 'home_probable_pitcher_id', 'away_probable_pitcher', 'away_probable_pitcher_id'
    if team_id == home_id:
        opp_name = game.get('away_probable_pitcher')
        opp_id   = game.get('away_probable_pitcher_id')
    else:
        opp_name = game.get('home_probable_pitcher')
        opp_id   = game.get('home_probable_pitcher_id')

    if opp_name:
        entry: Dict[str, Any] = {"name": str(opp_name)}
        if opp_id:
            entry["id"] = int(opp_id)
        prob.append(entry)

    return prob

def next_games(team_key: str, days_ahead: int = 7, include_started: bool = False, start_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Find all games for a team in [start_date, start_date+days_ahead], earliest first.

    If *start_date* is not provided, defaults to yesterday (UTC) so the
    user's local "today" game is always included even when the server (UTC)
    has rolled over to the next day.

    Returns a list of dicts:
      {
        "game_date": "YYYY-MM-DD",
        "game_datetime": "YYYY-MM-DDTHH:MM:SSZ",   # UTC ISO 8601 if provided
        "game_pk": <int>,
        "home_id": <int>, "home_name": <str>,
        "away_id": <int>, "away_name": <str>,
        "opponent_id": <int>, "opponent_name": <str>,
        "is_home": <bool>,
        "venue": <str>,
        "series_description": <str|None>,
        "status": <str>,                           # Scheduled, Pre-Game, In Progress, Final, etc.
        "probable_pitchers": [{"id": <int>, "name": <str>}, ...]  # opponent probables (0–1 typical)
      }
    """
    team_id = _resolve_team_id(team_key)
    tz = timezone.utc
    today = datetime.now(tz).date()

    if start_date:
        query_start = datetime.fromisoformat(start_date).date()
    else:
        # Default: 1 day in the past for timezone safety
        query_start = today - timedelta(days=1)

    end_date = query_start + timedelta(days=days_ahead)
    payload = _fetch_schedule(team_id, 1, query_start, end_date)
    return _parse_schedule(payload, team_id, include_started=include_started)

def next_games_aaa(team_key: str, days_ahead: int = 7, include_started: bool = False, start_date: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Same as next_games() but for Triple-A (sportId=11).

    AAA team abbreviations (e.g. SYR, LHV, WOR) are resolved via _aaa_team_index().
    Returns the identical dict format as next_games() so all downstream logic is unchanged.
    """
    team_id = _resolve_aaa_team_id(team_key)
    tz = timezone.utc
    today = datetime.now(tz).date()

    if start_date:
        query_start = datetime.fromisoformat(start_date).date()
    else:
        query_start = today - timedelta(days=1)

    end_date_val = query_start + timedelta(days=days_ahead)
    payload = _fetch_schedule(team_id, 11, query_start, end_date_val)
    return _parse_schedule(payload, team_id, include_started=include_started)


def next_game_info(team_key: str, days_ahead: int = 7) -> Dict[str, Any]:
    """
    Convenience wrapper: return the earliest upcoming game dict within the window.
    Raises if none found.
    """
    games = next_games(team_key, days_ahead=days_ahead, include_started=False)
    if not games:
        raise RuntimeError(f"No upcoming games found within {days_ahead} days for {team_key}.")
    return games[0]

def next_series_game_info(team_key: str, days_ahead: int = 14) -> dict:
    games = next_games(team_key, days_ahead=days_ahead, include_started=False)
    if not games:
        raise RuntimeError(f"No upcoming games found within {days_ahead} days for {team_key}.")
    def series_chunks(gs):
        chunk = []
        last_opp = None
        for g in gs:
            opp = g["opponent_id"]
            if last_opp is None or opp == last_opp:
                chunk.append(g)
            else:
                yield chunk
                chunk = [g]
            last_opp = opp
        if chunk:
            yield chunk
    chunks = list(series_chunks(games))
    if not chunks:
        raise RuntimeError("No series chunks computed.")
    if len(chunks) == 1:
        raise RuntimeError("Only one opponent in window. Increase days_ahead.")
    return chunks[1][0]

def next_series_game_info(team_key: str, days_ahead: int = 14) -> dict:
    games = next_games(team_key, days_ahead=days_ahead, include_started=False)
    if not games:
        raise RuntimeError(f"No upcoming games found within {days_ahead} days for {team_key}.")
    def series_chunks(gs):
        chunk = []
        last_opp = None
        for g in gs:
            opp = g["opponent_id"]
            if last_opp is None or opp == last_opp:
                chunk.append(g)
            else:
                yield chunk
                chunk = [g]
            last_opp = opp
        if chunk:
            yield chunk
    chunks = list(series_chunks(games))
    if not chunks:
        raise RuntimeError("No series chunks computed.")
    if len(chunks) == 1:
        raise RuntimeError("Only one opponent in window. Increase days_ahead.")
    return chunks[1][0]
