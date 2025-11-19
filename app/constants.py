"""
Application constants
"""
import re
from typing import Optional

# Team abbreviations to MLB team ID mapping
TEAM_ABBR_TO_ID = {
    "ARI": 109, "ATL": 144, "BAL": 110, "BOS": 111, "CHC": 112, "CWS": 145, "CIN": 113,
    "CLE": 114, "COL": 115, "DET": 116, "HOU": 117, "KC": 118, "LAA": 108, "LAD": 119,
    "MIA": 146, "MIL": 158, "MIN": 142, "NYM": 121, "NYY": 147, "OAK": 133, "PHI": 143,
    "PIT": 134, "SD": 135, "SF": 137, "SEA": 136, "STL": 138, "TB": 139, "TEX": 140,
    "TOR": 141, "WSH": 120,
    "ANA": 108, "CHW": 145, "KCR": 118, "SDP": 135, "SFG": 137, "TBR": 139,
    "WSN": 120, "WAS": 120
}

# Team primary colors (hex codes)
TEAM_COLORS = {
    # Team ID -> Primary Color
    109: "#A71930",  # ARI - Arizona Diamondbacks (Sedona Red)
    144: "#CE1141",  # ATL - Atlanta Braves (Braves Red)
    110: "#DF4601",  # BAL - Baltimore Orioles (Oriole Orange)
    111: "#BD3039",  # BOS - Boston Red Sox (Red Sox Red)
    112: "#0E3386",  # CHC - Chicago Cubs (Cubs Blue)
    145: "#27251F",  # CWS - Chicago White Sox (Black)
    113: "#C6011F",  # CIN - Cincinnati Reds (Reds Red)
    114: "#E31937",  # CLE - Cleveland Guardians (Guardians Red)
    115: "#33006F",  # COL - Colorado Rockies (Purple)
    116: "#0C2340",  # DET - Detroit Tigers (Navy Blue)
    117: "#002D62",  # HOU - Houston Astros (Navy Blue)
    118: "#004687",  # KC - Kansas City Royals (Royal Blue)
    108: "#BA0021",  # LAA - Los Angeles Angels (Red)
    119: "#005A9C",  # LAD - Los Angeles Dodgers (Dodger Blue)
    146: "#00A3E0",  # MIA - Miami Marlins (Marlins Blue)
    158: "#0A2351",  # MIL - Milwaukee Brewers (Navy Blue)
    142: "#002B5C",  # MIN - Minnesota Twins (Twins Blue)
    121: "#002D72",  # NYM - New York Mets (Mets Blue)
    147: "#132448",  # NYY - New York Yankees (Navy Blue)
    133: "#003831",  # OAK - Oakland Athletics (Green)
    143: "#E81828",  # PHI - Philadelphia Phillies (Phillies Red)
    134: "#FDB827",  # PIT - Pittsburgh Pirates (Gold)
    135: "#2F241D",  # SD - San Diego Padres (Brown)
    137: "#FD5A1E",  # SF - San Francisco Giants (Orange)
    136: "#0C2C56",  # SEA - Seattle Mariners (Navy Blue)
    138: "#C41E3A",  # STL - St. Louis Cardinals (Cardinal Red)
    139: "#092C5C",  # TB - Tampa Bay Rays (Navy Blue)
    140: "#003278",  # TEX - Texas Rangers (Rangers Blue)
    141: "#134A8E",  # TOR - Toronto Blue Jays (Blue Jays Blue)
    120: "#AB0003",  # WSH - Washington Nationals (Nationals Red)
}

# Team abbreviation to primary color mapping
TEAM_ABBR_TO_COLOR = {
    "ARI": "#A71930", "ATL": "#CE1141", "BAL": "#DF4601", "BOS": "#BD3039",
    "CHC": "#0E3386", "CWS": "#27251F", "CIN": "#C6011F", "CLE": "#E31937",
    "COL": "#33006F", "DET": "#0C2340", "HOU": "#002D62", "KC": "#004687",
    "LAA": "#BA0021", "LAD": "#005A9C", "MIA": "#00A3E0", "MIL": "#0A2351",
    "MIN": "#002B5C", "NYM": "#002D72", "NYY": "#132448", "OAK": "#003831",
    "PHI": "#E81828", "PIT": "#FDB827", "SD": "#2F241D", "SF": "#FD5A1E",
    "SEA": "#0C2C56", "STL": "#C41E3A", "TB": "#092C5C", "TEX": "#003278",
    "TOR": "#134A8E", "WSH": "#AB0003",
    # Alternative abbreviations
    "ANA": "#BA0021", "CHW": "#27251F", "KCR": "#004687", "SDP": "#2F241D",
    "SFG": "#FD5A1E", "TBR": "#092C5C", "WSN": "#AB0003", "WAS": "#AB0003",
}

def get_team_color(team_id: Optional[int] = None, team_abbr: Optional[str] = None) -> str:
    """Get team primary color by ID or abbreviation."""
    if team_id and team_id in TEAM_COLORS:
        return TEAM_COLORS[team_id]
    if team_abbr:
        return TEAM_ABBR_TO_COLOR.get(team_abbr.upper(), "#666666")
    return "#666666"  # Default gray

# Division options
DIVISION_OPTIONS = [
    {"id": 201, "name": "American League East", "league_id": 103},
    {"id": 202, "name": "American League Central", "league_id": 103},
    {"id": 200, "name": "American League West", "league_id": 103},
    {"id": 204, "name": "National League East", "league_id": 104},
    {"id": 205, "name": "National League Central", "league_id": 104},
    {"id": 203, "name": "National League West", "league_id": 104},
]

# League options
LEAGUE_OPTIONS = [
    {"id": 103, "name": "American League"},
    {"id": 104, "name": "National League"},
]

# Leader category abbreviations
LEADER_CATEGORY_ABBR = {
    "homeRuns": "HR",
    "runsBattedIn": "RBI",
    "battingAverage": "AVG",
    "era": "ERA",
    "strikeouts": "K",
    "whip": "WHIP",
}

# Report filename pattern for opponent extraction
REPORT_OPP_PATTERN = re.compile(r"_vs_([A-Za-z0-9]+)", re.IGNORECASE)

# Journal visibility options
JOURNAL_VISIBILITY_OPTIONS = ("private", "public")
MAX_JOURNAL_TIMELINE_ENTRIES = 365

# Report generation constants
REPORT_LEAD_DAYS = 5

# Authentication exempt endpoints
AUTH_EXEMPT_ENDPOINTS = {
    "login",
    "register",
    "static",
    "auth.account_deactivated",
    "auth.verify_email",
    "auth.verify_email_pending",
    "auth.resend_verification"
}

