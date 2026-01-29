"""
Venue → IANA timezone mapping for MLB ballparks and spring training sites.
Used to display game times in the venue's local time (e.g. 1:10 PM EST at Clover Park).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# IANA timezone keys for lookup
ET = "America/New_York"
CT = "America/Chicago"
MT = "America/Denver"
PT = "America/Los_Angeles"
AZ = "America/Phoenix"

# Venue name (normalized: stripped, casefolded) -> IANA timezone.
# Include canonical names and common API variants (e.g. loanDepot park, LoanDepot Park).
_VENUE_TZ: dict[str, str] = {}

def _add(name: str, tz: str) -> None:
    k = name.strip().casefold()
    if k:
        _VENUE_TZ[k] = tz

# ==============================================================================
# REGULAR SEASON MLB STADIUMS
# ==============================================================================

# Eastern Time (America/New_York)
for v in (
    # AL East
    "Fenway Park",
    "Yankee Stadium",
    "Oriole Park at Camden Yards",
    "Camden Yards",
    "Tropicana Field",
    "Rogers Centre",
    # NL East
    "Citi Field",
    "Citizens Bank Park",
    "Nationals Park",
    "Truist Park",
    "SunTrust Park",
    "LoanDepot Park",
    "loanDepot park",
    "Marlins Park",
    # AL/NL Central (Eastern timezone cities)
    "Great American Ball Park",  # Cincinnati
    "Progressive Field",  # Cleveland
    "Comerica Park",  # Detroit
    "PNC Park",  # Pittsburgh
):
    _add(v, ET)

# Central Time (America/Chicago)
for v in (
    # AL Central
    "Guaranteed Rate Field",
    "Rate Field",
    "U.S. Cellular Field",
    "Kauffman Stadium",
    "Target Field",
    # NL Central
    "Wrigley Field",
    "American Family Field",
    "Miller Park",
    "Busch Stadium",
    # AL West
    "Globe Life Field",  # Texas
    "Minute Maid Park",
    "Daikin Park",
):
    _add(v, CT)

# Mountain Time (America/Denver)
for v in (
    "Coors Field",
):
    _add(v, MT)

# Pacific Time (America/Los_Angeles)
for v in (
    "Dodger Stadium",
    "Angel Stadium",
    "Angel Stadium of Anaheim",
    "Petco Park",
    "Oracle Park",
    "AT&T Park",
    "Pacific Bell Park",
    "T-Mobile Park",
    "Safeco Field",
    "Sutter Health Park",  # A's temporary home 2025+
    "Oakland Coliseum",
    "RingCentral Coliseum",
    "O.co Coliseum",
):
    _add(v, PT)

# Arizona (America/Phoenix - no DST)
for v in (
    "Chase Field",
):
    _add(v, AZ)

# ==============================================================================
# SPRING TRAINING - CACTUS LEAGUE (Arizona)
# All Arizona spring training facilities use America/Phoenix (no DST)
# ==============================================================================
for v in (
    # Brewers
    "American Family Fields of Phoenix",
    "American Family Fields",
    "Maryvale Baseball Park",
    # Dodgers & White Sox (shared)
    "Camelback Ranch",
    "Camelback Ranch-Glendale",
    # Reds & Guardians (shared)
    "Goodyear Ballpark",
    # Athletics
    "Hohokam Stadium",
    # Padres & Mariners (shared)
    "Peoria Sports Complex",
    "Peoria Stadium",
    # Diamondbacks & Rockies (shared)
    "Salt River Fields at Talking Stick",
    "Salt River Fields",
    # Giants
    "Scottsdale Stadium",
    # Cubs
    "Sloan Park",
    # Royals & Rangers (shared)
    "Surprise Stadium",
    # Angels
    "Tempe Diablo Stadium",
):
    _add(v, AZ)

# ==============================================================================
# SPRING TRAINING - GRAPEFRUIT LEAGUE (Florida)
# All Florida spring training facilities use America/New_York (Eastern)
# ==============================================================================
for v in (
    # Phillies - Clearwater
    "BayCare Ballpark",
    "Spectrum Field",
    "Bright House Field",
    # Rays - Port Charlotte
    "Charlotte Sports Park",
    # Mets - Port St. Lucie
    "Clover Park",
    "First Data Field",
    "Tradition Field",
    "Digital Domain Park",
    # Braves - North Port
    "CoolToday Park",
    # Orioles - Sarasota
    "Ed Smith Stadium",
    # Astros & Nationals (shared) - West Palm Beach
    "CACTI Park of the Palm Beaches",
    "FITTEAM Ballpark of the Palm Beaches",
    "The Ballpark of the Palm Beaches",
    # Yankees - Tampa
    "George M. Steinbrenner Field",
    "Steinbrenner Field",
    "Legends Field",
    # Red Sox - Fort Myers
    "JetBlue Park at Fenway South",
    "JetBlue Park",
    # Pirates - Bradenton
    "LECOM Park",
    "McKechnie Field",
    # Twins - Fort Myers
    "Lee Health Sports Complex",
    "Hammond Stadium",
    "CenturyLink Sports Complex",
    # Tigers - Lakeland
    "Publix Field at Joker Marchant Stadium",
    "Joker Marchant Stadium",
    # Cardinals & Marlins (shared) - Jupiter
    "Roger Dean Chevrolet Stadium",
    "Roger Dean Stadium",
    # Blue Jays - Dunedin
    "TD Ballpark",
    "Dunedin Stadium",
    "Florida Auto Exchange Stadium",
):
    _add(v, ET)


def get_venue_timezone(venue: Optional[str]) -> Optional[str]:
    """Return IANA timezone for venue, or None if unknown."""
    if not venue or not isinstance(venue, str):
        return None
    key = venue.strip().casefold()
    return _VENUE_TZ.get(key)


def format_game_time_venue(
    game_datetime_utc: Optional[str],
    venue: Optional[str],
) -> str:
    """
    Format a game datetime in the viewer/device local time.
    E.g. "2026-02-21T18:10:00Z" + "Clover Park" -> "1:10 PM EST" (if viewer is ET).

    Display priority:
      1. Device/server local timezone (what the browser/device is in for local dev)
      2. Venue timezone (last-resort hint if local conversion fails)

    Returns "TBD" if datetime is missing or unparseable.
    """
    if not game_datetime_utc:
        return "TBD"
    try:
        dt = datetime.fromisoformat(
            game_datetime_utc.replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        return "TBD"

    # 1. Device/server local timezone (approximates viewer device in local/dev setups)
    try:
        local = dt.astimezone()  # Uses system local timezone
        hour = int(local.strftime("%I"))
        rest = local.strftime("%M %p %Z")
        return f"{hour}:{rest}"
    except Exception:
        pass

    # 2. Last resort: try venue timezone if we have a mapping
    tz_name = get_venue_timezone(venue)
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            local = dt.astimezone(ZoneInfo(tz_name))
            hour = int(local.strftime("%I"))
            rest = local.strftime("%M %p %Z")
            return f"{hour}:{rest}"
        except Exception:
            pass

    return "TBD"
