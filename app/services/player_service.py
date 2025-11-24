"""
Player service for player-related operations
"""
from typing import Optional, Dict, Any
from flask import g
from app.config import Config
from app.utils.helpers import clean_str
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
try:
    from database import PlayerDB
except ImportError:
    PlayerDB = None


def lookup_team_for_name(first_name: Optional[str], last_name: Optional[str]) -> Optional[str]:
    """Attempt to determine a team abbreviation for the given player name."""
    if not PlayerDB:
        return None
    first = (first_name or "").strip()
    last = (last_name or "").strip()
    if not last:
        return None
    try:
        db = PlayerDB()
        candidates = db.search_players(search=last, limit=50)
        team_abbr = None
        for candidate in candidates:
            cand_first = (candidate.get("first_name") or "").split()
            cand_last = (candidate.get("last_name") or "").split()
            # Basic matching on first + last
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
        return team_abbr or None
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Warning resolving team for {first_name} {last_name}: {exc}")
        return None


def determine_user_team(user: Optional[Dict[str, Any]]) -> str:
    """Best-effort resolution of the user's team abbreviation."""
    team_abbr = None

    if user:
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





