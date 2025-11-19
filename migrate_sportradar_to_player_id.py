#!/usr/bin/env python3
"""
Migration script to rename sportradar_id to player_id in the database.
This script will:
1. Rename the column in the players table
2. Update foreign key references in related tables
3. Update indexes
4. Preserve all existing data
"""
import sys
import sqlite3
from pathlib import Path

# Get repo root directory
ROOT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT_DIR / 'src'))
from database import PlayerDB

def migrate_database(db_path: str = None):
    """Migrate database from sportradar_id to player_id"""
    if db_path is None:
        db_path = str(ROOT_DIR / "build" / "database" / "players.db")
    db_file = Path(db_path)
    
    if not db_file.exists():
        print(f"Database file not found: {db_path}")
        print("This is fine if you're starting fresh. The new schema will use player_id.")
        return True
    
    print(f"Migrating database: {db_path}")
    print("=" * 60)
    
    # Connect to database
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Check if migration is needed
        cursor.execute("PRAGMA table_info(players)")
        columns = {row[1]: row for row in cursor.fetchall()}
        
        if 'player_id' in columns:
            print("✓ Database already uses player_id. Migration not needed.")
            conn.close()
            return True
        
        if 'sportradar_id' not in columns:
            print("⚠ Warning: Neither sportradar_id nor player_id found in players table.")
            print("  This might be a new database. Migration skipped.")
            conn.close()
            return True
        
        print("Step 1: Creating backup...")
        backup_path = db_file.with_suffix('.db.backup')
        import shutil
        shutil.copy2(db_file, backup_path)
        print(f"  ✓ Backup created: {backup_path}")
        
        print("\nStep 2: Disabling foreign key constraints...")
        cursor.execute("PRAGMA foreign_keys = OFF")
        
        print("\nStep 3: Renaming players table column...")
        # SQLite doesn't support ALTER TABLE RENAME COLUMN in older versions
        # So we need to recreate the table
        cursor.execute("""
            CREATE TABLE players_new (
                player_id TEXT PRIMARY KEY,
                mlbam_id TEXT,
                name TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                position TEXT,
                primary_position TEXT,
                team_id TEXT,
                team_abbr TEXT,
                jersey_number TEXT,
                handedness TEXT,
                height TEXT,
                weight INTEGER,
                birth_date TEXT,
                birth_place TEXT,
                debut_date TEXT,
                updated_at REAL,
                FOREIGN KEY (team_id) REFERENCES teams(team_id)
            )
        """)
        
        # Copy data
        cursor.execute("""
            INSERT INTO players_new 
            (player_id, mlbam_id, name, first_name, last_name, position, 
             primary_position, team_id, team_abbr, jersey_number, handedness,
             height, weight, birth_date, birth_place, debut_date, updated_at)
            SELECT 
                sportradar_id, mlbam_id, name, first_name, last_name, position,
                primary_position, team_id, team_abbr, jersey_number, handedness,
                height, weight, birth_date, birth_place, debut_date, updated_at
            FROM players
        """)
        
        # Drop old table and rename new one
        cursor.execute("DROP TABLE players")
        cursor.execute("ALTER TABLE players_new RENAME TO players")
        print("  ✓ Players table migrated")
        
        print("\nStep 4: Migrating player_stats table...")
        cursor.execute("""
            CREATE TABLE player_stats_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id TEXT NOT NULL,
                season TEXT,
                stat_type TEXT,
                category TEXT,
                value REAL,
                updated_at REAL,
                FOREIGN KEY (player_id) REFERENCES players(player_id),
                UNIQUE(player_id, season, stat_type, category)
            )
        """)
        cursor.execute("""
            INSERT INTO player_stats_new 
            (id, player_id, season, stat_type, category, value, updated_at)
            SELECT id, sportradar_id, season, stat_type, category, value, updated_at
            FROM player_stats
        """)
        cursor.execute("DROP TABLE player_stats")
        cursor.execute("ALTER TABLE player_stats_new RENAME TO player_stats")
        print("  ✓ player_stats table migrated")
        
        print("\nStep 5: Migrating player_seasons table...")
        cursor.execute("""
            CREATE TABLE player_seasons_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id TEXT NOT NULL,
                season TEXT NOT NULL,
                games INTEGER,
                at_bats INTEGER,
                hits INTEGER,
                doubles INTEGER,
                triples INTEGER,
                home_runs INTEGER,
                rbi INTEGER,
                runs INTEGER,
                stolen_bases INTEGER,
                walks INTEGER,
                strikeouts INTEGER,
                avg REAL,
                obp REAL,
                slg REAL,
                ops REAL,
                updated_at REAL,
                FOREIGN KEY (player_id) REFERENCES players(player_id),
                UNIQUE(player_id, season)
            )
        """)
        cursor.execute("""
            INSERT INTO player_seasons_new 
            (id, player_id, season, games, at_bats, hits, doubles, triples,
             home_runs, rbi, runs, stolen_bases, walks, strikeouts,
             avg, obp, slg, ops, updated_at)
            SELECT id, sportradar_id, season, games, at_bats, hits, doubles, triples,
                   home_runs, rbi, runs, stolen_bases, walks, strikeouts,
                   avg, obp, slg, ops, updated_at
            FROM player_seasons
        """)
        cursor.execute("DROP TABLE player_seasons")
        cursor.execute("ALTER TABLE player_seasons_new RENAME TO player_seasons")
        print("  ✓ player_seasons table migrated")
        
        print("\nStep 6: Migrating player_history table...")
        cursor.execute("""
            CREATE TABLE player_history_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id TEXT NOT NULL,
                date TEXT NOT NULL,
                event_type TEXT,
                from_team TEXT,
                to_team TEXT,
                details TEXT,
                updated_at REAL,
                FOREIGN KEY (player_id) REFERENCES players(player_id)
            )
        """)
        cursor.execute("""
            INSERT INTO player_history_new 
            (id, player_id, date, event_type, from_team, to_team, details, updated_at)
            SELECT id, sportradar_id, date, event_type, from_team, to_team, details, updated_at
            FROM player_history
        """)
        cursor.execute("DROP TABLE player_history")
        cursor.execute("ALTER TABLE player_history_new RENAME TO player_history")
        print("  ✓ player_history table migrated")
        
        print("\nStep 7: Recreating indexes...")
        cursor.execute("DROP INDEX IF EXISTS idx_player_seasons_player_season")
        cursor.execute("DROP INDEX IF EXISTS idx_player_stats_player_season")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_seasons_player_season ON player_seasons(player_id, season)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_stats_player_season ON player_stats(player_id, season)")
        print("  ✓ Indexes recreated")
        
        print("\nStep 8: Re-enabling foreign key constraints...")
        cursor.execute("PRAGMA foreign_keys = ON")
        
        # Commit all changes
        conn.commit()
        print("\n" + "=" * 60)
        print("✓ Migration completed successfully!")
        print(f"  Backup saved at: {backup_path}")
        
        # Verify migration
        cursor.execute("SELECT COUNT(*) FROM players")
        player_count = cursor.fetchone()[0]
        print(f"  Players in database: {player_count}")
        
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Migration failed: {e}")
        print(f"  Database backup available at: {backup_path}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    success = migrate_database()
    sys.exit(0 if success else 1)

