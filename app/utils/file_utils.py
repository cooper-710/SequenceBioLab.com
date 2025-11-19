"""
File utility functions
"""
from pathlib import Path
from typing import Optional
from app.config import Config
from app.utils.helpers import sanitize_filename_component
from app.constants import REPORT_OPP_PATTERN


def report_exists_for_player(
    player_name: str, 
    opponent_abbr: Optional[str], 
    opponent_label: Optional[str]
) -> bool:
    """Check if a report exists for a player."""
    if not player_name:
        return True
    
    player_slug = sanitize_filename_component(player_name).lower()
    player_slug_alt = player_slug.replace(" ", "_")
    opponent_code = (opponent_abbr or "").upper()
    stubs = []
    
    if opponent_label:
        stubs.append(sanitize_filename_component(f"{player_name} vs {opponent_label}").lower())
    if opponent_code:
        stubs.append(sanitize_filename_component(f"{player_name} vs {opponent_code}").lower())
    
    stubs_alt = [s.replace(" ", "_") for s in stubs]
    
    for pdf in Config.PDF_OUTPUT_DIR.glob("*.pdf"):
        stem_lower = pdf.stem.lower()
        if opponent_code and f"_vs_{opponent_code.lower()}" in stem_lower and (player_slug in stem_lower or player_slug_alt in stem_lower):
            return True
        for stub in stubs:
            if stub and stub in stem_lower:
                return True
        for stub in stubs_alt:
            if stub and stub in stem_lower:
                return True
    
    return False



