#!/usr/bin/env python3
"""
Update player teams in database from Positions.csv using most recent season data.
This script will:
1. Populate the players table from Positions.csv if it's empty
2. Update all player teams to their most recent team from the CSV
"""
import sys
import csv
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Get repo root directory
ROOT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT_DIR / 'src'))
from database import PlayerDB

def load_latest_teams_from_csv(csv_path: str) -> dict:
    """
    Load the most recent team for each player from Positions.csv.
    
    Returns:
        dict: {player_id: {'team_abbr': 'XXX', 'team_name': '...', 'season': YYYY, 'player_name': '...'}}
    """
    latest_teams = {}
    
    csv_file = Path(csv_path)
    if not csv_file.exists():
        print(f"Error: {csv_path} not found")
        return latest_teams
    
    print(f"Reading {csv_path}...")
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                player_id = row.get('player_id', '').strip()
                season = int(row.get('season', 0))
                team_abbr = row.get('team_abbrev', '').strip().upper()
                team_name = row.get('team_name', '').strip()
                player_name = row.get('player_name', '').strip()
                team_id = row.get('team_id', '').strip()
                
                if not player_id or not team_abbr or not player_name:
                    continue
                
                # Keep the most recent season for each player
                if player_id not in latest_teams:
                    latest_teams[player_id] = {
                        'team_abbr': team_abbr,
                        'team_name': team_name,
                        'team_id': team_id,
                        'season': season,
                        'player_name': player_name
                    }
                else:
                    # Update if this season is more recent
                    if season > latest_teams[player_id]['season']:
                        latest_teams[player_id] = {
                            'team_abbr': team_abbr,
                            'team_name': team_name,
                            'team_id': team_id,
                            'season': season,
                            'player_name': player_name
                        }
            except (ValueError, KeyError) as e:
                continue
    
    print(f"Found {len(latest_teams)} players with team data")
    return latest_teams

def populate_players_from_csv(db: PlayerDB, latest_teams: dict, dry_run: bool = False):
    """
    Populate the players table from the latest teams data.
    """
    cursor = db.conn.cursor()
    
    # Check if players table is empty
    cursor.execute("SELECT COUNT(*) FROM players")
    count_result = cursor.fetchone()
    # Handle both tuple (SQLite) and dict-like (PostgreSQL) results
    if hasattr(count_result, '__getitem__') and not isinstance(count_result, dict):
        existing_count = count_result[0]
    elif isinstance(count_result, dict):
        existing_count = list(count_result.values())[0]
    else:
        existing_count = count_result[0] if count_result else 0
    
    if existing_count > 0:
        print(f"Database already has {existing_count} players. Skipping population.")
        return
    
    print(f"\nPopulating players table with {len(latest_teams)} players...")
    
    added_count = 0
    for player_id, info in latest_teams.items():
        player_name = info['player_name']
        # Split name into first and last
        name_parts = player_name.split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        
        if dry_run:
            print(f"  Would add: {player_name} (ID: {player_id}, Team: {info['team_abbr']})")
        else:
            try:
                # Create a unique player_id from mlbam_id
                db_player_id = f"mlbam-{player_id}"
                
                # Use appropriate SQL syntax based on database type
                if db.is_postgres:
                    cursor.execute("""
                        INSERT INTO players 
                        (player_id, mlbam_id, name, first_name, last_name, 
                         team_id, team_abbr, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (player_id) DO UPDATE SET
                        mlbam_id = EXCLUDED.mlbam_id,
                        name = EXCLUDED.name,
                        first_name = EXCLUDED.first_name,
                        last_name = EXCLUDED.last_name,
                        team_id = EXCLUDED.team_id,
                        team_abbr = EXCLUDED.team_abbr,
                        updated_at = EXCLUDED.updated_at
                    """, (
                        db_player_id,
                        player_id,
                        player_name,
                        first_name,
                        last_name,
                        info['team_id'],
                        info['team_abbr'],
                        datetime.now().timestamp()
                    ))
                else:
                    cursor.execute("""
                        INSERT OR REPLACE INTO players 
                        (player_id, mlbam_id, name, first_name, last_name, 
                         team_id, team_abbr, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        db_player_id,
                        player_id,
                        player_name,
                        first_name,
                        last_name,
                        info['team_id'],
                        info['team_abbr'],
                        datetime.now().timestamp()
                    ))
                added_count += 1
                if added_count % 100 == 0:
                    print(f"  Added {added_count} players...")
            except Exception as e:
                print(f"  ❌ Error adding {player_name}: {e}")
    
    if not dry_run:
        db.conn.commit()
        print(f"✅ Added {added_count} players to database")
    
    return added_count

def update_database_teams(db: PlayerDB, latest_teams: dict, dry_run: bool = False):
    """
    Update player teams in the database.
    
    Args:
        db: PlayerDB instance
        latest_teams: dict from load_latest_teams_from_csv
        dry_run: If True, only print what would be updated without making changes
    """
    cursor = db.conn.cursor()
    
    # Get all players from database
    cursor.execute("SELECT player_id, mlbam_id, name, team_abbr FROM players")
    db_players = cursor.fetchall()
    
    updated_count = 0
    not_found_count = 0
    already_correct_count = 0
    
    print(f"\nProcessing {len(db_players)} players from database...")
    
    for player_row in db_players:
        # Handle both dict-like (PostgreSQL) and tuple (SQLite) row access
        # Use database type to determine access method
        if db.is_postgres:
            # PostgreSQL RealDictRow - access by key
            player_id = player_row.get('player_id')
            mlbam_id = player_row.get('mlbam_id')
            player_name = player_row.get('name')
            current_team_abbr = player_row.get('team_abbr')
        else:
            # SQLite Row or tuple - access by index
            player_id = player_row[0]
            mlbam_id = player_row[1]
            player_name = player_row[2]
            current_team_abbr = player_row[3]
        
        # Try to find player in CSV by mlbam_id first
        team_info = None
        if mlbam_id:
            team_info = latest_teams.get(str(mlbam_id))
        
        # If not found by ID, try to find by name (less reliable but fallback)
        if not team_info and player_name:
            # Search for matching name in latest_teams
            for pid, info in latest_teams.items():
                if info.get('player_name', '').strip().lower() == player_name.strip().lower():
                    team_info = info
                    break
        
        if not team_info:
            not_found_count += 1
            continue
        
        new_team_abbr = team_info['team_abbr']
        season = team_info['season']
        
        # Check if update is needed
        if current_team_abbr and current_team_abbr.upper() == new_team_abbr.upper():
            already_correct_count += 1
            continue
        
        # Update the player
        if dry_run:
            print(f"  🔄 Would update: {player_name} ({mlbam_id})")
            print(f"     Current: {current_team_abbr or 'None'} → New: {new_team_abbr} (season {season})")
        else:
            try:
                # Use appropriate parameter style based on database type
                if db.is_postgres:
                    cursor.execute("""
                        UPDATE players 
                        SET team_abbr = %s, team_id = %s, updated_at = %s
                        WHERE player_id = %s
                    """, (new_team_abbr, team_info['team_id'], datetime.now().timestamp(), player_id))
                else:
                    cursor.execute("""
                        UPDATE players 
                        SET team_abbr = ?, team_id = ?, updated_at = ?
                        WHERE player_id = ?
                    """, (new_team_abbr, team_info['team_id'], datetime.now().timestamp(), player_id))
                updated_count += 1
                if updated_count <= 20:  # Only print first 20 to avoid spam
                    print(f"  ✅ Updated: {player_name} → {new_team_abbr} (season {season})")
            except Exception as e:
                print(f"  ❌ Error updating {player_name}: {e}")
    
    if not dry_run:
        db.conn.commit()
        if updated_count > 20:
            print(f"  ... and {updated_count - 20} more updates")
    
    print(f"\n📊 Summary:")
    print(f"   Updated: {updated_count}")
    print(f"   Already correct: {already_correct_count}")
    print(f"   Not found in CSV: {not_found_count}")
    
    return updated_count, already_correct_count, not_found_count

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Update player teams from Positions.csv')
    parser.add_argument('--csv', default=None, help='Path to Positions.csv file (default: data/Positions.csv)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without making changes')
    parser.add_argument('--skip-populate', action='store_true', help='Skip populating players table if empty')
    args = parser.parse_args()
    
    # Default to data/Positions.csv if not specified
    if args.csv is None:
        csv_path = Path(__file__).parent / "data" / "Positions.csv"
        args.csv = str(csv_path)
    
    # Load latest teams from CSV
    latest_teams = load_latest_teams_from_csv(args.csv)
    
    if not latest_teams:
        print("No team data found. Exiting.")
        return
    
    # Connect to database
    print("\nConnecting to database...")
    db = PlayerDB()
    
    try:
        # First, populate players table if empty
        if not args.skip_populate:
            populate_players_from_csv(db, latest_teams, dry_run=args.dry_run)
        
        # Then update teams
        update_database_teams(db, latest_teams, dry_run=args.dry_run)
        
        if args.dry_run:
            print("\n⚠️  DRY RUN - No changes were made. Run without --dry-run to apply updates.")
        else:
            print("\n✅ Update complete!")
    finally:
        db.close()

if __name__ == "__main__":
    main()
