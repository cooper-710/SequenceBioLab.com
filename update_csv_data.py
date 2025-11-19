#!/usr/bin/env python3
"""
Automated CSV Data Update Script (Incremental)
Updates fangraphs.csv, fangraphs_pitchers.csv, Positions.csv, and statscast.csv
Only fetches missing historical seasons and always updates current season
"""

import sys
import subprocess
import os
import shutil
from pathlib import Path
from datetime import datetime
import time
import random
import logging
import traceback
import numpy as np
import pandas as pd
import requests
from tqdm import tqdm
import argparse

# Configuration
# Get repo root directory (if script is in scripts/, go up one level)
SCRIPT_DIR = Path(__file__).parent.resolve()
ROOT_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR
START_YEAR = 2017
END_YEAR = datetime.now().year
CURRENT_YEAR = datetime.now().year
MIN_AB = 1
MIN_IP = 1.0

# Parse command line arguments
parser = argparse.ArgumentParser(description='Update CSV data files incrementally')
parser.add_argument('--test', action='store_true', 
                   help='Test mode: use test file paths, do not modify production files')
parser.add_argument('--dry-run', action='store_true',
                   help='Dry run: show what would be fetched but do not save files')
parser.add_argument('--simulate-year', type=int, metavar='YEAR',
                   help='Simulate a specific year as current (e.g., 2026 for testing)')
parser.add_argument('--force-full', action='store_true',
                   help='Force full rebuild of all seasons (ignore incremental logic)')
args = parser.parse_args()

# Adjust paths and year based on test mode
if args.test:
    TEST_DIR = ROOT_DIR / "test_data"
    TEST_DIR.mkdir(exist_ok=True)
    FANGRAPHS_HITTERS_PATH = TEST_DIR / "fangraphs.csv"
    FANGRAPHS_PITCHERS_PATH = TEST_DIR / "fangraphs_pitchers.csv"
    POSITIONS_PATH = TEST_DIR / "Positions.csv"
    STATSCAST_PATH = TEST_DIR / "statscast.csv"
    logger_prefix = "[TEST MODE] "
else:
    DATA_DIR = ROOT_DIR / "data"
    DATA_DIR.mkdir(exist_ok=True)
    FANGRAPHS_HITTERS_PATH = DATA_DIR / "fangraphs.csv"
    FANGRAPHS_PITCHERS_PATH = DATA_DIR / "fangraphs_pitchers.csv"
    POSITIONS_PATH = DATA_DIR / "Positions.csv"
    STATSCAST_PATH = DATA_DIR / "statscast.csv"
    logger_prefix = ""

# Override current year if simulating
if args.simulate_year:
    CURRENT_YEAR = args.simulate_year
    logger_prefix += f"[SIMULATE {CURRENT_YEAR}] "

# Setup logging
LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
log_file = TEST_DIR / 'data_update.log' if args.test else LOG_DIR / 'data_update.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PrefixedLogger:
    """Wrapper to add prefix to log messages"""
    def __init__(self, logger, prefix):
        self.logger = logger
        self.prefix = prefix
    
    def info(self, msg):
        self.logger.info(self.prefix + msg)
    
    def warning(self, msg):
        self.logger.warning(self.prefix + msg)
    
    def error(self, msg):
        self.logger.error(self.prefix + msg)

logger = PrefixedLogger(logger, logger_prefix)


def install_dependencies():
    """Install/upgrade required packages"""
    logger.info("Checking dependencies...")
    
    def sh(args):
        subprocess.check_call([sys.executable, "-m", *args], 
                            stdout=subprocess.DEVNULL, 
                            stderr=subprocess.DEVNULL)
    
    try:
        # Install pybaseball
        try:
            sh(["pip", "install", "--upgrade", "--quiet", "pybaseball==2.2.8"])
        except subprocess.CalledProcessError:
            logger.warning("PyPI install failed, trying GitHub...")
            sh(["pip", "install", "--upgrade", "--quiet", 
                "git+https://github.com/jldbc/pybaseball.git@master"])
        
        # Install other dependencies
        sh(["pip", "install", "--upgrade", "--quiet", 
            "pandas", "numpy", "requests", "tqdm", "python-dateutil"])
        
        import pybaseball as pb
        logger.info(f"✓ Dependencies OK (pybaseball {pb.__version__})")
        return True
    except Exception as e:
        logger.error(f"Failed to install dependencies: {e}")
        return False


def get_existing_seasons(csv_path, season_col='Season'):
    """Get set of seasons already present in CSV file"""
    if not csv_path.exists():
        return set()
    
    try:
        # Try to read just the season column
        df = pd.read_csv(csv_path, usecols=[season_col], dtype={season_col: 'Int64'})
        seasons = set(df[season_col].dropna().unique().astype(int))
        return seasons
    except Exception as e:
        logger.warning(f"Could not read existing seasons from {csv_path}: {e}")
        return set()


def determine_seasons_to_fetch(existing_seasons, start_year, end_year, current_year, force_full=False):
    """
    Determine which seasons need to be fetched:
    - Missing historical seasons (fetch once)
    - Current season (always fetch to get latest stats)
    """
    if force_full:
        all_seasons = set(range(start_year, end_year + 1))
        return sorted(all_seasons), set(), False
    
    all_seasons = set(range(start_year, end_year + 1))
    missing_historical = all_seasons - existing_seasons - {current_year}
    seasons_to_fetch = missing_historical | {current_year}
    
    return sorted(seasons_to_fetch), missing_historical, current_year in existing_seasons


def merge_dataframes(existing_df, new_df, season_col='Season', current_year=None):
    """
    Merge new data with existing:
    - Remove all rows for current_year from existing
    - Append new data (which includes current_year + any new historical seasons)
    """
    if existing_df is None or existing_df.empty:
        return new_df.copy() if new_df is not None and not new_df.empty else pd.DataFrame()
    
    if new_df is None or new_df.empty:
        return existing_df.copy()
    
    # Remove current year from existing data (will be replaced with fresh data)
    if current_year is not None and season_col in existing_df.columns:
        existing_df = existing_df[existing_df[season_col] != current_year].copy()
    
    # Combine: existing (without current year) + new data
    combined = pd.concat([existing_df, new_df], ignore_index=True)
    
    # Remove duplicates - keep the newer data (from new_df)
    if season_col in combined.columns:
        # Sort by season descending, then drop duplicates keeping first (newest)
        combined = combined.sort_values(season_col, ascending=False)
        # If there's a way to identify unique rows (e.g., Season + Name), use that
        if 'Name' in combined.columns:
            combined = combined.drop_duplicates(subset=[season_col, 'Name'], keep='first')
        elif 'player_name' in combined.columns:
            combined = combined.drop_duplicates(subset=[season_col, 'player_name'], keep='first')
        else:
            combined = combined.drop_duplicates(keep='first')
    
    return combined


def update_fangraphs_hitters():
    """Update fangraphs.csv incrementally"""
    logger.info("Updating Fangraphs hitters data...")
    
    try:
        from pybaseball import batting_stats
        
        # Check existing seasons
        existing_seasons = get_existing_seasons(FANGRAPHS_HITTERS_PATH)
        seasons_to_fetch, missing_historical, has_current = determine_seasons_to_fetch(
            existing_seasons, START_YEAR, END_YEAR, CURRENT_YEAR, args.force_full
        )
        
        if args.dry_run:
            logger.info(f"  [DRY RUN] Existing seasons: {sorted(existing_seasons) if existing_seasons else 'None'}")
            logger.info(f"  [DRY RUN] Would fetch seasons: {seasons_to_fetch}")
            if missing_historical:
                logger.info(f"  [DRY RUN] New historical seasons: {missing_historical}")
            if CURRENT_YEAR in seasons_to_fetch:
                logger.info(f"  [DRY RUN] Would update current season: {CURRENT_YEAR}")
            return True
        
        if not seasons_to_fetch:
            logger.info("  No new seasons to fetch. Data is up to date.")
            return True
        
        logger.info(f"  Fetching seasons: {seasons_to_fetch}")
        if missing_historical:
            logger.info(f"    New historical seasons: {missing_historical}")
        if CURRENT_YEAR in seasons_to_fetch:
            logger.info(f"    Updating current season: {CURRENT_YEAR}")
        
        # Fetch only needed seasons
        min_year = min(seasons_to_fetch)
        max_year = max(seasons_to_fetch)
        
        logger.info(f"  Calling batting_stats({min_year}, {max_year})...")
        df = batting_stats(min_year, max_year, qual=0)
        
        # Filter to only the seasons we need
        if 'Season' in df.columns:
            df = df[df['Season'].isin(seasons_to_fetch)].copy()
            logger.info(f"  Fetched {len(df):,} rows for seasons {seasons_to_fetch}")
        
        # Rename core columns
        rename_core = {"IDfg": "fg_IDfg", "Team": "fg_Team", "Pos": "fg_Pos"}
        df = df.rename(columns=rename_core)
        df = df.rename(columns=lambda c: c if c in ["Season","Name","fg_IDfg","fg_Team","fg_Pos"] 
                      else f"fg_{c}")
        
        # Derive singles if needed
        if "fg_1B" not in df.columns and {"fg_H","fg_2B","fg_3B","fg_HR"}.issubset(df.columns):
            df["fg_1B"] = df["fg_H"] - df["fg_2B"] - df["fg_3B"] - df["fg_HR"]
        
        # Filter by AB
        df = df[pd.to_numeric(df.get("fg_AB", 0), errors="coerce").fillna(0) >= MIN_AB].copy()
        
        # Load existing data
        existing_df = None
        if FANGRAPHS_HITTERS_PATH.exists():
            try:
                existing_df = pd.read_csv(FANGRAPHS_HITTERS_PATH)
                logger.info(f"  Loaded {len(existing_df):,} existing rows")
            except Exception as e:
                logger.warning(f"  Could not load existing data: {e}")
        
        # Merge with existing
        final = merge_dataframes(existing_df, df, season_col='Season', current_year=CURRENT_YEAR)
        
        # Sort by Season, Name for consistency
        if 'Season' in final.columns and 'Name' in final.columns:
            final = final.sort_values(['Season', 'Name']).reset_index(drop=True)
        
        # Backup existing file
        if FANGRAPHS_HITTERS_PATH.exists() and not args.test:
            BACKUP_DIR = DATA_DIR / "backups"
            BACKUP_DIR.mkdir(exist_ok=True)
            backup_filename = f"fangraphs_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            backup_path = BACKUP_DIR / backup_filename
            shutil.copy2(FANGRAPHS_HITTERS_PATH, backup_path)
            logger.info(f"  Backed up to {backup_path.name}")
        
        # Save
        final.to_csv(FANGRAPHS_HITTERS_PATH, index=False)
        logger.info(f"✓ Updated {FANGRAPHS_HITTERS_PATH.name} ({len(final):,} total rows, +{len(df):,} new/updated)")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to update Fangraphs hitters: {e}")
        if not args.test:
            logger.error(traceback.format_exc())
        return False


def update_fangraphs_pitchers():
    """Update fangraphs_pitchers.csv incrementally"""
    logger.info("Updating Fangraphs pitchers data...")
    
    try:
        from pybaseball import pitching_stats
        
        # Check existing seasons
        existing_seasons = get_existing_seasons(FANGRAPHS_PITCHERS_PATH)
        seasons_to_fetch, missing_historical, has_current = determine_seasons_to_fetch(
            existing_seasons, START_YEAR, END_YEAR, CURRENT_YEAR, args.force_full
        )
        
        if args.dry_run:
            logger.info(f"  [DRY RUN] Existing seasons: {sorted(existing_seasons) if existing_seasons else 'None'}")
            logger.info(f"  [DRY RUN] Would fetch seasons: {seasons_to_fetch}")
            return True
        
        if not seasons_to_fetch:
            logger.info("  No new seasons to fetch. Data is up to date.")
            return True
        
        logger.info(f"  Fetching seasons: {seasons_to_fetch}")
        
        # Fetch only needed seasons
        min_year = min(seasons_to_fetch)
        max_year = max(seasons_to_fetch)
        
        logger.info(f"  Calling pitching_stats({min_year}, {max_year})...")
        df = pitching_stats(min_year, max_year, qual=0)
        
        # Filter to only the seasons we need
        if 'Season' in df.columns:
            df = df[df['Season'].isin(seasons_to_fetch)].copy()
            logger.info(f"  Fetched {len(df):,} rows for seasons {seasons_to_fetch}")
        
        # Rename core columns
        rename_core = {"IDfg": "fg_IDfg", "Team": "fg_Team"}
        df = df.rename(columns=rename_core)
        
        # Ensure expected columns exist
        for c in ["fg_IDfg", "fg_Team"]:
            if c not in df.columns:
                df[c] = np.nan
        
        # Prefix columns
        keep_unprefixed = {"Season", "Name", "fg_IDfg", "fg_Team"}
        df = df.rename(columns=lambda c: c if c in keep_unprefixed 
                      else (f"fg_{c}" if not c.startswith("fg_") else c))
        
        # Filter by IP
        ip_col = "fg_IP" if "fg_IP" in df.columns else ("IP" if "IP" in df.columns else None)
        if ip_col is None:
            logger.warning("  No IP column found; skipping IP filter.")
        else:
            df[ip_col] = pd.to_numeric(df[ip_col], errors="coerce")
            df = df[df[ip_col].fillna(0) >= float(MIN_IP)].copy()
        
        # Load existing data
        existing_df = None
        if FANGRAPHS_PITCHERS_PATH.exists():
            try:
                existing_df = pd.read_csv(FANGRAPHS_PITCHERS_PATH)
                logger.info(f"  Loaded {len(existing_df):,} existing rows")
            except Exception as e:
                logger.warning(f"  Could not load existing data: {e}")
        
        # Merge with existing
        final = merge_dataframes(existing_df, df, season_col='Season', current_year=CURRENT_YEAR)
        
        # Sort by Season, Name
        if 'Season' in final.columns and 'Name' in final.columns:
            final = final.sort_values(['Season', 'Name']).reset_index(drop=True)
        
        # Backup existing file
        if FANGRAPHS_PITCHERS_PATH.exists() and not args.test:
            BACKUP_DIR = DATA_DIR / "backups"
            BACKUP_DIR.mkdir(exist_ok=True)
            backup_filename = f"fangraphs_pitchers_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            backup_path = BACKUP_DIR / backup_filename
            shutil.copy2(FANGRAPHS_PITCHERS_PATH, backup_path)
            logger.info(f"  Backed up to {backup_path.name}")
        
        # Save
        final.to_csv(FANGRAPHS_PITCHERS_PATH, index=False)
        logger.info(f"✓ Updated {FANGRAPHS_PITCHERS_PATH.name} ({len(final):,} total rows, +{len(df):,} new/updated)")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to update Fangraphs pitchers: {e}")
        if not args.test:
            logger.error(traceback.format_exc())
        return False


def update_positions():
    """Update Positions.csv incrementally"""
    logger.info("Updating Positions data...")
    
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "SequenceBioLab-DataUpdate/1.0",
            "Accept": "application/json"
        })
        
        SPORT_ID = 1
        
        def get_json(url, params=None, max_retries=5, backoff=0.75):
            for attempt in range(1, max_retries+1):
                try:
                    r = session.get(url, params=params, timeout=25)
                    if r.status_code == 200:
                        return r.json()
                    if r.status_code in (429, 500, 502, 503, 504):
                        time.sleep(backoff * attempt + random.uniform(0, 0.5))
                    else:
                        r.raise_for_status()
                except requests.RequestException:
                    time.sleep(backoff * attempt + random.uniform(0, 0.5))
            raise RuntimeError(f"Failed after {max_retries} tries: {url}")
        
        def teams_for_season(season):
            url = "https://statsapi.mlb.com/api/v1/teams"
            data = get_json(url, params={"sportId": SPORT_ID, "season": season})
            teams = []
            for t in data.get("teams", []):
                if t.get("sport", {}).get("id") == SPORT_ID and not t.get("springOnly", False):
                    teams.append({
                        "team_id": t.get("id"),
                        "team_name": t.get("name"),
                        "abbrev": t.get("abbreviation"),
                    })
            return teams
        
        def team_full_roster(season, team_id):
            url = f"https://statsapi.mlb.com/api/v1/teams/{team_id}/roster/fullRoster"
            data = get_json(url, params={"season": season})
            rows = []
            for item in data.get("roster", []):
                person = item.get("person", {}) or {}
                pos = item.get("position", {}) or {}
                rows.append({
                    "season": season,
                    "team_id": team_id,
                    "player_id": person.get("id"),
                    "player_name": person.get("fullName"),
                    "position_code": pos.get("code") or pos.get("abbreviation"),
                    "position_name": pos.get("name"),
                    "position_type": pos.get("type"),
                })
            return rows
        
        # Check existing seasons
        existing_seasons = get_existing_seasons(POSITIONS_PATH, season_col='season')
        seasons_to_fetch, missing_historical, has_current = determine_seasons_to_fetch(
            existing_seasons, START_YEAR, END_YEAR, CURRENT_YEAR, args.force_full
        )
        
        if args.dry_run:
            logger.info(f"  [DRY RUN] Existing seasons: {sorted(existing_seasons) if existing_seasons else 'None'}")
            logger.info(f"  [DRY RUN] Would fetch seasons: {seasons_to_fetch}")
            return True
        
        if not seasons_to_fetch:
            logger.info("  No new seasons to fetch. Data is up to date.")
            return True
        
        logger.info(f"  Fetching seasons: {seasons_to_fetch}")
        
        # Fetch only needed seasons
        all_rows = []
        for yr in tqdm(seasons_to_fetch, desc="  Seasons"):
            teams = teams_for_season(yr)
            for t in tqdm(teams, leave=False, desc=f"    Teams {yr}"):
                rows = team_full_roster(yr, t["team_id"])
                for r in rows:
                    r["team_name"] = t["team_name"]
                    r["team_abbrev"] = t["abbrev"]
                all_rows.extend(rows)
                time.sleep(0.05 + random.uniform(0, 0.05))
        
        # Build DataFrame
        new_df = pd.DataFrame(all_rows).dropna(subset=["player_id"])
        
        # De-duplicate new data
        new_df = (new_df.sort_values(["season","player_id","team_id"])
                 .drop_duplicates(subset=["season","player_id"], keep="first")
                 .reset_index(drop=True))
        
        # Load existing data
        existing_df = None
        if POSITIONS_PATH.exists():
            try:
                existing_df = pd.read_csv(POSITIONS_PATH)
                logger.info(f"  Loaded {len(existing_df):,} existing rows")
            except Exception as e:
                logger.warning(f"  Could not load existing data: {e}")
        
        # Merge with existing
        final = merge_dataframes(existing_df, new_df, season_col='season', current_year=CURRENT_YEAR)
        
        # De-duplicate final (in case of any overlap)
        final = (final.sort_values(["season","player_id","team_id"])
                .drop_duplicates(subset=["season","player_id"], keep="first")
                .reset_index(drop=True))
        
        # Sort by season, player_id
        final = final.sort_values(['season', 'player_id']).reset_index(drop=True)
        
        # Backup existing file
        if POSITIONS_PATH.exists() and not args.test:
            BACKUP_DIR = DATA_DIR / "backups"
            BACKUP_DIR.mkdir(exist_ok=True)
            backup_filename = f"Positions_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            backup_path = BACKUP_DIR / backup_filename
            shutil.copy2(POSITIONS_PATH, backup_path)
            logger.info(f"  Backed up to {backup_path.name}")
        
        # Save
        final.to_csv(POSITIONS_PATH, index=False)
        logger.info(f"✓ Updated {POSITIONS_PATH.name} ({len(final):,} total rows, +{len(new_df):,} new/updated)")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to update Positions: {e}")
        if not args.test:
            logger.error(traceback.format_exc())
        return False


def update_statcast():
    """Update statscast.csv incrementally by aggregating raw Statcast data"""
    logger.info("Updating Statcast data...")
    
    try:
        from pybaseball import statcast_batter, playerid_lookup
        
        # Check existing seasons
        existing_seasons = get_existing_seasons(STATSCAST_PATH, season_col='year')
        seasons_to_fetch, missing_historical, has_current = determine_seasons_to_fetch(
            existing_seasons, START_YEAR, END_YEAR, CURRENT_YEAR, args.force_full
        )
        
        if args.dry_run:
            logger.info(f"  [DRY RUN] Existing seasons: {sorted(existing_seasons) if existing_seasons else 'None'}")
            logger.info(f"  [DRY RUN] Would fetch seasons: {seasons_to_fetch}")
            if CURRENT_YEAR in seasons_to_fetch:
                logger.info(f"  [DRY RUN] Would update current season: {CURRENT_YEAR}")
            return True
        
        if not seasons_to_fetch:
            logger.info("  No new seasons to fetch. Data is up to date.")
            return True
        
        logger.info(f"  Fetching seasons: {seasons_to_fetch}")
        if CURRENT_YEAR in seasons_to_fetch:
            logger.info(f"    Updating current season: {CURRENT_YEAR}")
        
        # Load existing data to get player list
        existing_df = None
        if STATSCAST_PATH.exists():
            try:
                existing_df = pd.read_csv(STATSCAST_PATH)
                logger.info(f"  Loaded {len(existing_df):,} existing rows")
            except Exception as e:
                logger.warning(f"  Could not load existing data: {e}")
        
        # Get list of players who had at-bats in these seasons
        # Use fangraphs data as source of truth for who played
        player_seasons = set()
        if FANGRAPHS_HITTERS_PATH.exists():
            try:
                fg_df = pd.read_csv(FANGRAPHS_HITTERS_PATH)
                if 'Season' in fg_df.columns and 'Name' in fg_df.columns:
                    for _, row in fg_df[fg_df['Season'].isin(seasons_to_fetch)].iterrows():
                        player_seasons.add((row['Name'], int(row['Season'])))
                logger.info(f"  Found {len(player_seasons):,} player-season combinations to fetch")
            except Exception as e:
                logger.warning(f"  Could not load fangraphs data for player list: {e}")
                return False
        
        if not player_seasons:
            logger.warning("  No players found for these seasons")
            return False
        
        # Fetch and aggregate statcast data for each player-season
        all_rows = []
        total = len(player_seasons)
        
        for idx, (player_name, season) in enumerate(tqdm(player_seasons, desc="  Fetching Statcast", unit="player"), 1):
            try:
                # Get player ID
                name_parts = player_name.split()
                if len(name_parts) < 2:
                    continue
                last_name = name_parts[-1]
                first_name = name_parts[0]
                
                try:
                    player_lookup = playerid_lookup(last_name, first_name)
                    if player_lookup.empty or 'key_mlbam' not in player_lookup.columns:
                        continue
                    player_id = int(player_lookup.iloc[0]['key_mlbam'])
                    if pd.isna(player_id):
                        continue
                except Exception:
                    continue
                
                # Fetch statcast data for the season
                start_date = f"{season}-03-01"  # Start of season
                end_date = f"{season}-11-30"    # End of season
                
                # Retry logic for statcast API (can be flaky)
                sc_df = None
                max_retries = 2
                for retry in range(max_retries):
                    try:
                        sc_df = statcast_batter(start_date, end_date, player_id)
                        if sc_df is not None and not sc_df.empty:
                            break  # Success, exit retry loop
                    except (pd.errors.ParserError, ValueError, KeyError) as e:
                        # Parsing errors - retry once
                        if retry < max_retries - 1:
                            time.sleep(1)  # Brief delay before retry
                            continue
                        else:
                            # Final retry failed, skip this player
                            sc_df = None
                            break
                    except Exception as e:
                        # Other errors - skip this player
                        sc_df = None
                        break
                
                if sc_df is None or sc_df.empty:
                    continue
                
                # Aggregate the data
                row = aggregate_statcast_data(sc_df, player_name, player_id, season)
                if row:
                    all_rows.append(row)
                
                # Rate limiting (more aggressive for statcast API to avoid errors)
                if idx % 5 == 0:
                    time.sleep(1)  # Longer delay to avoid overwhelming API
                else:
                    time.sleep(0.2)  # Small delay between each request
                    
            except Exception as e:
                # Silently skip players with processing errors
                continue
        
        if not all_rows:
            logger.warning("  No statcast data fetched (this may be normal if API had issues)")
            # Don't fail completely - other data sources succeeded
            return True  # Return True so overall update doesn't fail
        
        # Create DataFrame
        new_df = pd.DataFrame(all_rows)
        logger.info(f"  Fetched {len(new_df):,} rows for seasons {seasons_to_fetch}")
        
        # Merge with existing
        final = merge_dataframes(existing_df, new_df, season_col='year', current_year=CURRENT_YEAR)
        
        # Sort by year, player_id for consistency
        if 'year' in final.columns and 'player_id' in final.columns:
            final = final.sort_values(['year', 'player_id']).reset_index(drop=True)
        
        # Backup existing file
        if STATSCAST_PATH.exists() and not args.test:
            BACKUP_DIR = DATA_DIR / "backups"
            BACKUP_DIR.mkdir(exist_ok=True)
            backup_filename = f"statscast_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            backup_path = BACKUP_DIR / backup_filename
            shutil.copy2(STATSCAST_PATH, backup_path)
            logger.info(f"  Backed up to {backup_path.name}")
        
        # Save
        final.to_csv(STATSCAST_PATH, index=False)
        logger.info(f"✓ Updated {STATSCAST_PATH.name} ({len(final):,} total rows, +{len(new_df):,} new/updated)")
        return True
        
    except Exception as e:
        logger.error(f"✗ Failed to update Statcast: {e}")
        if not args.test:
            logger.error(traceback.format_exc())
        return False


def aggregate_statcast_data(sc_df: pd.DataFrame, player_name: str, player_id: int, year: int) -> dict:
    """Aggregate raw Statcast data into season-level statistics matching statscast.csv format"""
    
    if sc_df.empty:
        return None
    
    # Initialize row with basic info
    name_parts = player_name.split()
    last_name = name_parts[-1] if name_parts else ""
    first_name = name_parts[0] if len(name_parts) > 1 else ""
    full_name = f"{last_name}, {first_name}" if first_name else last_name
    
    row = {
        "last_name, first_name": full_name,
        "player_id": player_id,
        "year": year,
        "player_age": None,  # Would need to calculate from birth date
    }
    
    # Basic counting stats from events
    events = sc_df['events'].astype(str).str.lower() if 'events' in sc_df.columns else pd.Series()
    
    # Plate appearances (unique at-bats)
    if 'at_bat_number' in sc_df.columns and 'game_pk' in sc_df.columns:
        pa_df = sc_df[events.notna() & (events != 'nan') & (events != '') & (events != 'none')].copy()
        if not pa_df.empty:
            pa_count = pa_df.groupby(['game_pk', 'at_bat_number']).size().shape[0]
        else:
            pa_count = 0
    else:
        pa_count = events.notna().sum()
    
    # At-bats (exclude walks, HBP, etc.)
    ab_events = ['single', 'double', 'triple', 'home_run', 'strikeout', 'strikeout_double_play',
                 'field_out', 'grounded_into_double_play', 'force_out', 'fielders_choice',
                 'fielders_choice_out', 'double_play', 'triple_play']
    ab_count = events[events.isin(ab_events)].shape[0] if not events.empty else 0
    
    # Hits
    hit_events = ['single', 'double', 'triple', 'home_run']
    hits = events[events.isin(hit_events)].shape[0] if not events.empty else 0
    singles = events[events == 'single'].shape[0] if not events.empty else 0
    doubles = events[events == 'double'].shape[0] if not events.empty else 0
    triples = events[events == 'triple'].shape[0] if not events.empty else 0
    home_runs = events[events == 'home_run'].shape[0] if not events.empty else 0
    
    # Strikeouts and walks
    strikeouts = events[events.str.contains('strikeout', na=False)].shape[0] if not events.empty else 0
    walks = events[events.str.contains('walk', na=False)].shape[0] if not events.empty else 0
    
    # Calculate percentages
    k_percent = (strikeouts / pa_count * 100) if pa_count > 0 else None
    bb_percent = (walks / pa_count * 100) if pa_count > 0 else None
    batting_avg = (hits / ab_count) if ab_count > 0 else None
    
    # Total bases
    total_bases = singles + (doubles * 2) + (triples * 3) + (home_runs * 4)
    slg_percent = (total_bases / ab_count) if ab_count > 0 else None
    
    # On-base percentage (simplified - would need HBP, SF)
    on_base = hits + walks
    on_base_percent = (on_base / pa_count) if pa_count > 0 else None
    ops = (batting_avg or 0) + (slg_percent or 0) if batting_avg and slg_percent else None
    
    # Isolated power
    iso = (slg_percent - batting_avg) if (slg_percent and batting_avg) else None
    
    # BABIP (simplified)
    babip = None  # Would need more detailed calculation
    
    # Pitch-level stats
    if 'pitch_type' in sc_df.columns:
        total_pitches = len(sc_df)
    else:
        total_pitches = None
    
    # Batted ball stats
    if 'bb_type' in sc_df.columns:
        bb_type = sc_df['bb_type'].astype(str).str.lower()
        groundballs = (bb_type == 'ground_ball').sum()
        flyballs = (bb_type == 'fly_ball').sum()
        linedrives = (bb_type == 'line_drive').sum()
        popups = (bb_type == 'popup').sum()
        batted_balls = bb_type.notna().sum()
    else:
        groundballs = flyballs = linedrives = popups = batted_balls = None
    
    # Exit velocity and launch angle
    if 'launch_speed' in sc_df.columns:
        exit_velocity_avg = sc_df['launch_speed'].mean()
    else:
        exit_velocity_avg = None
    
    if 'launch_angle' in sc_df.columns:
        launch_angle_avg = sc_df['launch_angle'].mean()
        # Sweet spot: 8-32 degrees
        sweet_spot = ((sc_df['launch_angle'] >= 8) & (sc_df['launch_angle'] <= 32)).sum()
        sweet_spot_percent = (sweet_spot / len(sc_df) * 100) if len(sc_df) > 0 else None
    else:
        launch_angle_avg = None
        sweet_spot_percent = None
    
    # Hard hit (95+ mph)
    if 'launch_speed' in sc_df.columns:
        hard_hit = (sc_df['launch_speed'] >= 95).sum()
        hard_hit_percent = (hard_hit / len(sc_df) * 100) if len(sc_df) > 0 else None
    else:
        hard_hit_percent = None
    
    # Barrel (simplified - would need exact formula)
    barrel = None
    barrel_batted_rate = None
    
    # Expected stats
    if 'estimated_ba_using_speedangle' in sc_df.columns:
        xba = sc_df['estimated_ba_using_speedangle'].mean()
    else:
        xba = None
    
    if 'estimated_slg_using_speedangle' in sc_df.columns:
        xslg = sc_df['estimated_slg_using_speedangle'].mean()
    else:
        xslg = None
    
    if 'estimated_woba_using_speedangle' in sc_df.columns:
        xwoba = sc_df['estimated_woba_using_speedangle'].mean()
    else:
        xwoba = None
    
    # Zone stats
    if 'zone' in sc_df.columns:
        in_zone = sc_df['zone'].notna().sum()
        in_zone_percent = (in_zone / total_pitches * 100) if total_pitches else None
    else:
        in_zone = in_zone_percent = None
    
    # Swing stats
    if 'description' in sc_df.columns:
        desc = sc_df['description'].astype(str).str.lower()
        swings = desc.str.contains('swinging', na=False).sum()
        swing_percent = (swings / total_pitches * 100) if total_pitches else None
        whiffs = desc.str.contains('swinging_strike', na=False).sum()
        whiff_percent = (whiffs / swings * 100) if swings > 0 else None
    else:
        swing_percent = whiff_percent = None
    
    # Populate row with all calculated values
    row.update({
        "ab": int(ab_count) if ab_count else None,
        "pa": int(pa_count) if pa_count else None,
        "hit": int(hits) if hits else None,
        "single": int(singles) if singles else None,
        "double": int(doubles) if doubles else None,
        "triple": int(triples) if triples else None,
        "home_run": int(home_runs) if home_runs else None,
        "strikeout": int(strikeouts) if strikeouts else None,
        "walk": int(walks) if walks else None,
        "k_percent": round(k_percent, 1) if k_percent is not None else None,
        "bb_percent": round(bb_percent, 1) if bb_percent is not None else None,
        "batting_avg": f"{batting_avg:.3f}".lstrip('0') if batting_avg is not None else None,
        "slg_percent": f"{slg_percent:.3f}".lstrip('0') if slg_percent is not None else None,
        "on_base_percent": f"{on_base_percent:.3f}".lstrip('0') if on_base_percent is not None else None,
        "on_base_plus_slg": f"{ops:.3f}".lstrip('0') if ops is not None else None,
        "isolated_power": f"{iso:.3f}".lstrip('0') if iso is not None else None,
        "babip": f"{babip:.3f}".lstrip('0') if babip is not None else None,
        "b_total_bases": int(total_bases) if total_bases else None,
        "b_total_pitches": int(total_pitches) if total_pitches else None,
        "groundballs": int(groundballs) if groundballs else None,
        "flyballs": int(flyballs) if flyballs else None,
        "linedrives": int(linedrives) if linedrives else None,
        "popups": int(popups) if popups else None,
        "batted_ball": int(batted_balls) if batted_balls else None,
        "exit_velocity_avg": round(exit_velocity_avg, 1) if exit_velocity_avg is not None else None,
        "launch_angle_avg": round(launch_angle_avg, 1) if launch_angle_avg is not None else None,
        "sweet_spot_percent": round(sweet_spot_percent, 1) if sweet_spot_percent is not None else None,
        "hard_hit_percent": round(hard_hit_percent, 1) if hard_hit_percent is not None else None,
        "xba": f"{xba:.3f}".lstrip('0') if xba is not None else None,
        "xslg": f"{xslg:.3f}".lstrip('0') if xslg is not None else None,
        "xwoba": f"{xwoba:.3f}".lstrip('0') if xwoba is not None else None,
        "in_zone": int(in_zone) if in_zone else None,
        "in_zone_percent": round(in_zone_percent, 1) if in_zone_percent is not None else None,
        "swing_percent": round(swing_percent, 1) if swing_percent is not None else None,
        "whiff_percent": round(whiff_percent, 1) if whiff_percent is not None else None,
    })
    
    # Add all other columns as None to match CSV structure
    # (Many columns require more complex calculations or aren't available in raw statcast)
    all_columns = [
        "b_rbi", "b_lob", "r_total_caught_stealing", "r_total_stolen_base", "b_ab_scoring",
        "b_ball", "b_called_strike", "b_catcher_interf", "b_foul", "b_foul_tip", "b_game",
        "b_gnd_into_dp", "b_gnd_into_tp", "b_gnd_rule_double", "b_hit_by_pitch", "b_hit_ground",
        "b_hit_fly", "b_hit_into_play", "b_hit_line_drive", "b_hit_popup", "b_out_fly",
        "b_out_ground", "b_out_line_drive", "b_out_popup", "b_intent_ball", "b_intent_walk",
        "b_interference", "b_pinch_hit", "b_pinch_run", "b_pitchout", "b_played_dh",
        "b_sac_bunt", "b_sac_fly", "b_swinging_strike", "r_caught_stealing_2b",
        "r_caught_stealing_3b", "r_caught_stealing_home", "r_defensive_indiff", "r_interference",
        "r_pickoff_1b", "r_pickoff_2b", "r_pickoff_3b", "r_run", "r_stolen_base_2b",
        "r_stolen_base_3b", "r_stolen_base_home", "b_total_ball", "b_total_sacrifices",
        "b_total_strike", "b_total_swinging_strike", "r_stolen_base_pct", "r_total_pickoff",
        "b_reached_on_error", "b_walkoff", "b_reached_on_int", "xobp", "xiso", "wobacon",
        "xwobacon", "bacon", "xbacon", "xbadiff", "xslgdiff", "wobadiff", "avg_swing_speed",
        "fast_swing_rate", "blasts_contact", "blasts_swing", "squared_up_contact",
        "squared_up_swing", "avg_swing_length", "swords", "attack_angle", "attack_direction",
        "ideal_angle_rate", "vertical_swing_path", "barrel", "barrel_batted_rate",
        "solidcontact_percent", "flareburner_percent", "poorlyunder_percent",
        "poorlytopped_percent", "poorlyweak_percent", "avg_best_speed", "avg_hyper_speed",
        "z_swing_percent", "z_swing_miss_percent", "oz_swing_percent", "oz_swing_miss_percent",
        "oz_contact_percent", "out_zone_swing_miss", "out_zone_swing", "out_zone_percent",
        "out_zone", "meatball_swing_percent", "meatball_percent", "pitch_count_offspeed",
        "pitch_count_fastball", "pitch_count_breaking", "pitch_count", "iz_contact_percent",
        "in_zone_swing_miss", "in_zone_swing", "edge_percent", "edge", "pull_percent",
        "straightaway_percent", "opposite_percent", "f_strike_percent", "groundballs_percent",
        "flyballs_percent", "linedrives_percent", "popups_percent", "pop_2b_sba_count",
        "pop_2b_sba", "pop_2b_sb", "pop_2b_cs", "pop_3b_sba_count", "pop_3b_sba", "pop_3b_sb",
        "pop_3b_cs", "exchange_2b_3b_sba", "maxeff_arm_2b_3b_sba", "n_outs_above_average",
        "n_fieldout_5stars", "n_opp_5stars", "n_5star_percent", "n_fieldout_4stars",
        "n_opp_4stars", "n_4star_percent", "n_fieldout_3stars", "n_opp_3stars",
        "n_3star_percent", "n_fieldout_2stars", "n_opp_2stars", "n_2star_percent",
        "n_fieldout_1stars", "n_opp_1stars", "n_1star_percent", "rel_league_reaction_distance",
        "rel_league_burst_distance", "rel_league_routing_distance", "rel_league_bootup_distance",
        "f_bootup_distance", "n_bolts", "hp_to_1b", "sprint_speed"
    ]
    
    for col in all_columns:
        if col not in row:
            row[col] = None
    
    return row


def main():
    """Main execution function"""
    mode_str = []
    if args.test:
        mode_str.append("TEST MODE")
    if args.dry_run:
        mode_str.append("DRY RUN")
    if args.simulate_year:
        mode_str.append(f"SIMULATE {args.simulate_year}")
    if args.force_full:
        mode_str.append("FULL REBUILD")
    
    mode_str = " | ".join(mode_str) if mode_str else "PRODUCTION"
    
    logger.info("=" * 70)
    logger.info(f"Starting CSV data update ({mode_str})")
    logger.info(f"Year range: {START_YEAR}-{END_YEAR} (Current: {CURRENT_YEAR})")
    if args.test:
        logger.info(f"Test files will be saved to: {TEST_DIR}")
    logger.info("=" * 70)
    
    # Install dependencies
    if not install_dependencies():
        logger.error("Failed to install dependencies. Exiting.")
        return False
    
    results = {}
    
    # Update each data source
    results['fangraphs_hitters'] = update_fangraphs_hitters()
    results['fangraphs_pitchers'] = update_fangraphs_pitchers()
    results['positions'] = update_positions()
    results['statcast'] = update_statcast()
    
    # Summary
    logger.info("=" * 70)
    logger.info("Update Summary:")
    for source, success in results.items():
        status = "✓ SUCCESS" if success else "✗ FAILED"
        logger.info(f"  {source:20s}: {status}")
    logger.info("=" * 70)
    
    return all(results.values())


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

