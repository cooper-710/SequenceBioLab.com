"""
Analytics service for league leaders, standings, and team metadata
"""
import logging
import re
import requests
import statsapi
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from app.config import Config
from app.constants import TEAM_ABBR_TO_ID, DIVISION_OPTIONS, LEAGUE_OPTIONS, LEADER_CATEGORY_ABBR
from app.services.cache_service import cache_service, CACHE_LEAGUE_LEADERS, CACHE_STANDINGS, CACHE_TEAM_METADATA

logger = logging.getLogger(__name__)


def get_team_metadata(team_abbr: Optional[str]) -> Dict[str, Any]:
    """Fetch MLB metadata for a given team abbreviation."""
    team_id = TEAM_ABBR_TO_ID.get((team_abbr or "").upper())
    if not team_id:
        return {}
    cache_key = (team_abbr or "").upper()
    cached = cache_service.get(CACHE_TEAM_METADATA, cache_key)
    if cached is not None:
        return cached
    try:
        team_payload = statsapi.get("team", {"teamId": team_id})
        team_info = (team_payload.get("teams") or [{}])[0]
        division = team_info.get("division") or {}
        league = team_info.get("league") or {}
        payload = {
            "team_id": team_id,
            "team_name": team_info.get("name"),
            "division_id": division.get("id"),
            "division_name": division.get("name"),
            "league_id": league.get("id"),
            "league_name": league.get("name")
        }
        cache_service.set(CACHE_TEAM_METADATA, cache_key, payload, ttl_seconds=3600)
        return payload
    except Exception as exc:
        logger.warning(f"Warning fetching team metadata: {exc}")
        payload = {"team_id": team_id}
        cache_service.set(CACHE_TEAM_METADATA, cache_key, payload, ttl_seconds=900)
        return payload


def parse_leader_lines(raw_text: str, max_entries: int = 5) -> List[Dict[str, Any]]:
    """Parse the text output from statsapi.league_leaders into structured rows."""
    entries = []
    if not raw_text:
        return entries

    for line in raw_text.splitlines():
        if line.startswith("Rank") or not line.strip():
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 4:
            continue
        rank, name, team, value = parts[:4]
        entries.append({
            "rank": rank.strip(),
            "player": name.strip(),
            "team": team.strip(),
            "value": value.strip(),
        })
        if len(entries) >= max_entries:
            break
    return entries


def filter_leader_entries(entries: List[Dict[str, Any]], include_pitchers: bool = False) -> List[Dict[str, Any]]:
    """Filter leader entries by primary position."""
    filtered = []
    for entry in entries:
        primary_position = (entry.get("position") or "").upper()
        if include_pitchers:
            if primary_position in {"", "P"}:
                filtered.append(entry)
        else:
            if primary_position and primary_position != "P":
                filtered.append(entry)
            elif not primary_position:
                filtered.append(entry)

    return filtered[:5]


def fetch_leader_entries(category: str, stat_group: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Fetch structured leader data directly from the MLB stats API."""
    params = {
        "leaderCategories": category,
        "season": datetime.now().year,
        "sportId": 1,
        "statGroup": stat_group,
        "leaderGameTypes": "R",
        "leaderBoardType": "regularSeason",
        "limit": max(limit, 5),
    }
    try:
        resp = requests.get(
            "https://statsapi.mlb.com/api/v1/stats/leaders",
            params=params,
            timeout=6
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        logger.warning(f"Warning fetching leaders {category}/{stat_group}: {exc}")
        return []

    leaders_block = (payload.get("leagueLeaders") or [])
    if not leaders_block:
        return []

    leaders = []
    for entry in leaders_block[0].get("leaders", [])[:limit]:
        person = entry.get("person") or {}
        team = entry.get("team") or {}
        leaders.append({
            "rank": entry.get("rank"),
            "player": person.get("fullName"),
            "team": team.get("name"),
            "value": entry.get("value"),
            "player_id": person.get("id"),
            "position": ((person.get("primaryPosition") or {}).get("abbreviation") or "")
        })
    return leaders


def collect_league_leaders() -> List[Dict[str, Any]]:
    """Get curated hitting and pitching leaderboards."""
    cached = cache_service.get(CACHE_LEAGUE_LEADERS, "default")
    if cached is not None:
        return cached

    groups = [
        ("Hitting Leaders", [
            ("homeRuns", "Home Runs"),
            ("runsBattedIn", "Runs Batted In"),
            ("battingAverage", "Batting Average"),
        ]),
        ("Pitching Leaders", [
            ("era", "Earned Run Average"),
            ("strikeouts", "Strikeouts"),
            ("whip", "WHIP"),
        ])
    ]

    result = []
    for group_label, categories in groups:
        category_entries = []
        for stat_code, label in categories:
            stat_group = "hitting" if group_label.startswith("Hitting") else "pitching"
            entries = fetch_leader_entries(stat_code, stat_group)
            if group_label.startswith("Hitting"):
                entries = filter_leader_entries(entries, include_pitchers=False)
            else:
                entries = filter_leader_entries(entries, include_pitchers=True)
            if entries:
                category_entries.append({
                    "label": label,
                    "abbr": LEADER_CATEGORY_ABBR.get(stat_code, "Value"),
                    "entries": entries
                })
        if category_entries:
            result.append({
                "group": group_label,
                "categories": category_entries
            })

    cache_service.set(CACHE_LEAGUE_LEADERS, "default", result, ttl_seconds=600)
    return result


def collect_standings_data(
    view: str,
    team_metadata: Dict[str, Any],
    division_id: Optional[int] = None,
    league_id: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """Return standings data for either a division or wildcard view."""
    season = datetime.now().year
    team_id = (team_metadata or {}).get("team_id")
    default_league_id = (team_metadata or {}).get("league_id")

    if view == "wildcard":
        league_id = int(league_id or default_league_id or 104)
        cache_key = ("wildcard", team_id, None, league_id)
        cached = cache_service.get(CACHE_STANDINGS, cache_key)
        if cached is not None:
            return cached
        try:
            standings_payload = statsapi.get("standings", {
                "leagueId": league_id,
                "season": season,
                "standingsType": "wildCard"
            })
        except Exception as exc:
            logger.warning(f"Warning fetching wildcard standings: {exc}")
            return None

        team_records = []
        for record in standings_payload.get("records", []):
            if record.get("league", {}).get("id") == league_id:
                team_records.extend(record.get("teamRecords", []))

        if not team_records:
            return None

        def rank_key(entry):
            try:
                return int(entry.get("wildCardRank", 999))
            except (TypeError, ValueError):
                return 999

        team_records.sort(key=rank_key)

        rows = []
        for entry in team_records:
            gb = entry.get("wildCardGamesBack")
            if gb in (None, "-", ""):
                gb = "0"
            rows.append({
                "team": entry.get("team", {}).get("name"),
                "wins": entry.get("wins"),
                "losses": entry.get("losses"),
                "games_back": gb,
                "is_user_team": entry.get("team", {}).get("id") == team_id
            })

        payload = {
            "title": f"{next((l['name'] for l in LEAGUE_OPTIONS if l['id'] == league_id), 'League')} Wild Card",
            "rows": rows,
            "view": "wildcard",
            "division_id": None,
            "league_id": league_id
        }
        cache_service.set(CACHE_STANDINGS, cache_key, payload, ttl_seconds=600)
        return payload

    # Division view
    resolved_division_id = division_id or (team_metadata or {}).get("division_id") or DIVISION_OPTIONS[0]["id"]
    try:
        division_id = int(resolved_division_id)
    except (TypeError, ValueError):
        division_id = DIVISION_OPTIONS[0]["id"]

    league_id = default_league_id or 104
    division_meta = next((opt for opt in DIVISION_OPTIONS if opt["id"] == division_id), None)
    if division_meta:
        league_id = division_meta.get("league_id") or league_id

    league_id = int(league_id)
    cache_key = ("division", team_id, division_id, league_id)
    cached = cache_service.get(CACHE_STANDINGS, cache_key)
    if cached is not None:
        return cached

    try:
        standings_payload = statsapi.get("standings", {
            "leagueId": league_id,
            "season": season
        })
    except Exception as exc:
        logger.warning(f"Warning fetching division standings: {exc}")
        return None

    division_record = None
    for record in standings_payload.get("records", []):
        if record.get("division", {}).get("id") == division_id:
            division_record = record
            break

    if not division_record:
        return None

    rows = []
    for entry in division_record.get("teamRecords", []):
        gb = entry.get("gamesBack")
        if gb in (None, "-", ""):
            gb = "0"
        rows.append({
            "team": entry.get("team", {}).get("name"),
            "wins": entry.get("wins"),
            "losses": entry.get("losses"),
            "games_back": gb,
            "is_user_team": entry.get("team", {}).get("id") == team_id
        })

    payload = {
        "title": division_record.get("division", {}).get("name", "Division"),
        "rows": rows,
        "view": "division",
        "division_id": division_id,
        "league_id": league_id
    }
    cache_service.set(CACHE_STANDINGS, cache_key, payload, ttl_seconds=600)
    return payload





