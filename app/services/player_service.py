"""
Player service for player-related operations.

User team resolution (determine_user_team):
  - If the user has an explicit team_abbr set (and it is not "AUTO"), that is used.
  - Otherwise the team is looked up by the user's first/last name via lookup_team_for_name(),
    which queries the `players` table (SQLite or Postgres). In production the table may be
    empty; we then fall back to data/Positions.csv (most recent year) so team resolution
    works without running update_player_teams in production.
"""
from typing import Optional, Dict, Any
import csv
import sys
import unicodedata
from pathlib import Path

from flask import g
from app.config import Config
from app.utils.helpers import clean_str

try:
    _repo_root = Path(__file__).resolve().parent.parent.parent
    if str(_repo_root / "src") not in sys.path:
        sys.path.insert(0, str(_repo_root / "src"))
except Exception:
    pass
try:
    from database import PlayerDB
except ImportError:
    PlayerDB = None


def _normalize_name(s: str) -> str:
    """Lowercase and strip accents for name matching."""
    if not s:
        return ""
    s = str(s).strip().lower()
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _lookup_team_from_positions_csv(first_name: Optional[str], last_name: Optional[str]) -> Optional[str]:
    """
    Fallback: look up team from data/Positions.csv using the most recent year.
    Used when the players table is empty (e.g. production Postgres never populated).
    """
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    if not last:
        return None
    csv_path = Config.ROOT_DIR / "data" / "Positions.csv"
    if not csv_path.exists():
        return None
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        if not rows:
            return None
        max_season = max((int(r.get("season", 0)) for r in rows if r.get("season")), default=0)
        if max_season <= 0:
            return None
        # Collect (player_name, team_abbrev) for most recent year; last row wins per name
        name_to_team = {}
        for r in rows:
            try:
                if int(r.get("season", 0)) != max_season:
                    continue
                name = (r.get("player_name") or "").strip()
                team = (r.get("team_abbrev") or "").strip().upper()
                if name and team:
                    name_to_team[name] = team
            except (ValueError, TypeError):
                continue
        if not name_to_team:
            return None
        first_n = _normalize_name(first)
        last_n = _normalize_name(last)
        for csv_name, team_abbr in name_to_team.items():
            csv_norm = _normalize_name(csv_name)
            words = csv_norm.split()
            if not words:
                continue
            if first_n and words[0] != first_n:
                continue
            if last_n and last_n not in [w for w in words]:
                continue
            return team_abbr
        return None
    except Exception:
        return None


def lookup_team_for_name(first_name: Optional[str], last_name: Optional[str]) -> Optional[str]:
    """Attempt to determine a team abbreviation for the given player name.
    Uses data/Positions.csv (most recent year) first so the current team is correct
    (e.g. Pete Alonso -> BAL in 2026). Falls back to the players table if not in CSV.
    """
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    if not last:
        return None
    # Prefer CSV (most recent year) so we get current team; DB can be stale (e.g. Alonso NYM -> BAL)
    team_abbr = _lookup_team_from_positions_csv(first_name, last_name)
    if not team_abbr and PlayerDB:
        try:
            db = PlayerDB()
            candidates = db.search_players(search=last, limit=50)
            for candidate in candidates:
                cand_first = (candidate.get("first_name") or "").split()
                cand_last = (candidate.get("last_name") or "").split()
                cand_first_name = cand_first[0] if cand_first else ""
                cand_last_name = cand_last[-1] if cand_last else ""
                if cand_first_name and first and cand_first_name.lower() != first.lower():
                    continue
                if cand_last_name and last and cand_last_name.lower() != last.lower():
                    continue
                team_abbr = (candidate.get("team_abbr") or candidate.get("team") or "").strip().upper()
                if team_abbr:
                    break
            db.close()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Warning resolving team for %s %s: %s", first_name, last_name, exc
            )
    return team_abbr or None


def determine_user_team(user: Optional[Dict[str, Any]]) -> str:
    """Best-effort resolution of the user's team abbreviation."""
    team_abbr = None

    if user:
        explicit = clean_str(user.get("team_abbr")).upper()
        if explicit and explicit != "AUTO":
            return explicit
        team_abbr = lookup_team_for_name(user.get("first_name"), user.get("last_name"))

    if not team_abbr:
        try:
            settings = getattr(g, "app_settings", {}) or Config.get_settings()
            report_defaults = settings.get("reports", {}) if isinstance(settings, dict) else {}
            default_team = (report_defaults.get("default_team") or "").strip().upper()
            if default_team and default_team != "AUTO":
                team_abbr = default_team
        except Exception:
            team_abbr = None

    if not team_abbr or team_abbr == "AUTO":
        team_abbr = "NYM"  # sensible default

    return team_abbr





