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
    # MLB team ID -> Primary Color
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
    # Triple-A (AAA) team ID -> Primary Color
    342:  "#6B2D8B",  # ABQ - Albuquerque Isotopes (Purple)
    422:  "#003087",  # BUF - Buffalo Bisons (Royal Blue)
    494:  "#27251F",  # CLT - Charlotte Knights (Black)
    445:  "#13274F",  # COL - Columbus Clippers (Navy)
    234:  "#002D72",  # DUR - Durham Bulls (Navy)
    4904: "#5B3427",  # ELP - El Paso Chihuahuas (Brown)
    431:  "#13274F",  # GWN - Gwinnett Stripers (Navy)
    484:  "#003087",  # IND - Indianapolis Indians (Blue)
    451:  "#0E3386",  # IOW - Iowa Cubs (Cubs Blue)
    564:  "#007B7B",  # JAX - Jacksonville Jumbo Shrimp (Teal)
    1410: "#C41230",  # LHV - Lehigh Valley IronPigs (Red)
    416:  "#C41E3A",  # LOU - Louisville Bats (Red)
    400:  "#003087",  # LV  - Las Vegas Aviators (Navy)
    235:  "#C41230",  # MEM - Memphis Redbirds (Red)
    556:  "#003087",  # NAS - Nashville Sounds (Navy)
    568:  "#003087",  # NOR - Norfolk Tides (Navy)
    238:  "#005A9C",  # OKC - Oklahoma City Comets (Blue)
    541:  "#004687",  # OMA - Omaha Storm Chasers (Blue)
    2310: "#722F8A",  # RNO - Reno Aces (Purple)
    534:  "#C41E3A",  # ROC - Rochester Red Wings (Red)
    102:  "#003278",  # RR  - Round Rock Express (Blue)
    105:  "#002856",  # SAC - Sacramento River Cats (Navy)
    561:  "#003087",  # SL  - Salt Lake Bees (Blue)
    1960: "#C41E3A",  # STP - St. Paul Saints (Red)
    5434: "#002D62",  # SUG - Sugar Land Space Cowboys (Navy)
    531:  "#0C2340",  # SWB - Scranton/WB RailRiders (Navy)
    552:  "#002D72",  # SYR - Syracuse Mets (Blue)
    529:  "#0C2C56",  # TAC - Tacoma Rainiers (Navy)
    512:  "#0C2340",  # TOL - Toledo Mud Hens (Navy)
    533:  "#0D2B56",  # WOR - Worcester Red Sox (Navy)
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
    # MLB alternative abbreviations
    "ANA": "#BA0021", "CHW": "#27251F", "KCR": "#004687", "SDP": "#2F241D",
    "SFG": "#FD5A1E", "TBR": "#092C5C", "WSN": "#AB0003", "WAS": "#AB0003",
    # Triple-A (AAA) team abbreviations
    "ABQ": "#6B2D8B",  # Albuquerque Isotopes (Purple)
    "BUF": "#003087",  # Buffalo Bisons (Royal Blue)
    "CLT": "#27251F",  # Charlotte Knights (Black)
    "CLB": "#13274F",  # Columbus Clippers (Navy)
    "DUR": "#002D72",  # Durham Bulls (Navy)
    "ELP": "#5B3427",  # El Paso Chihuahuas (Brown)
    "GWN": "#13274F",  # Gwinnett Stripers (Navy)
    "IND": "#003087",  # Indianapolis Indians (Blue)
    "IOW": "#0E3386",  # Iowa Cubs (Cubs Blue)
    "JAX": "#007B7B",  # Jacksonville Jumbo Shrimp (Teal)
    "LHV": "#C41230",  # Lehigh Valley IronPigs (Red)
    "LOU": "#C41E3A",  # Louisville Bats (Red)
    "LV":  "#003087",  # Las Vegas Aviators (Navy)
    "MEM": "#C41230",  # Memphis Redbirds (Red)
    "NAS": "#003087",  # Nashville Sounds (Navy)
    "NOR": "#003087",  # Norfolk Tides (Navy)
    "OKC": "#005A9C",  # Oklahoma City Comets (Blue)
    "OMA": "#004687",  # Omaha Storm Chasers (Blue)
    "RNO": "#722F8A",  # Reno Aces (Purple)
    "ROC": "#C41E3A",  # Rochester Red Wings (Red)
    "RR":  "#003278",  # Round Rock Express (Blue)
    "SAC": "#002856",  # Sacramento River Cats (Navy)
    "SL":  "#003087",  # Salt Lake Bees (Blue)
    "STP": "#C41E3A",  # St. Paul Saints (Red)
    "SUG": "#002D62",  # Sugar Land Space Cowboys (Navy)
    "SWB": "#0C2340",  # Scranton/WB RailRiders (Navy)
    "SYR": "#002D72",  # Syracuse Mets (Blue)
    "TAC": "#0C2C56",  # Tacoma Rainiers (Navy)
    "TOL": "#0C2340",  # Toledo Mud Hens (Navy)
    "WOR": "#0D2B56",  # Worcester Red Sox (Navy)
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
    "static",
    "auth.login",
    "auth.register",
    "auth.account_deactivated",
    "auth.verify_email",
    "auth.verify_email_pending",
    "auth.resend_verification",
    "auth.manage_devices_login",
    "auth.forgot_password",
    "auth.forgot_password_sent",
    "auth.reset_password",
    "upload.upload_report"
}
