# src/database.py
"""
Player Database - PostgreSQL/SQLite compatible operations
"""
import os
import sqlite3
import json
import threading
import socket
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from urllib.parse import urlparse

# Try to import PostgreSQL driver
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, execute_values
    from psycopg2 import pool
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False
    pool = None

# Module-level connection pools for PostgreSQL (per-worker)
# Each gunicorn worker process needs its own pool to avoid conflicts
import os
_postgres_pools = {}  # Dict of {worker_pid: pool}
_pool_lock = threading.Lock()
_schema_initialized = False
_schema_lock = threading.Lock()


def _get_postgres_pool(database_url: str):
    """Get or create PostgreSQL connection pool (per-worker)"""
    global _postgres_pools
    worker_pid = os.getpid()
    
    # Check if this worker already has a pool
    if worker_pid in _postgres_pools:
        return _postgres_pools[worker_pid]
    
    with _pool_lock:
        # Double-check after acquiring lock
        if worker_pid in _postgres_pools:
            return _postgres_pools[worker_pid]
        
        # Parse connection URL to force IPv4
        parsed = urlparse(database_url)
        hostname = parsed.hostname
        port = parsed.port or 5432
        
        # URL decode username and password (urlparse should do this, but be explicit)
        from urllib.parse import unquote
        username = unquote(parsed.username or '')
        password = unquote(parsed.password or '')
        
        # Log connection details (without password) for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Creating connection pool for worker {worker_pid}: host={hostname}, port={port}, user={username}, database={parsed.path.lstrip('/') or 'postgres'}")
        
        # Build connection parameters dict
        conn_params = {
            'host': hostname,  # Keep hostname for SSL/routing
            'port': port,
            'database': parsed.path.lstrip('/') or 'postgres',
            'user': username,  # Use decoded username
            'password': password,  # Use decoded password
            'connect_timeout': 30,  # Increased to 30 seconds for Supabase pooler reliability
            'cursor_factory': RealDictCursor,
            'sslmode': 'require',  # REQUIRED for Supabase connections
        }
        
        # Check if connection string already has sslmode parameter
        # If so, use that instead of defaulting to 'require'
        if parsed.query:
            from urllib.parse import parse_qs
            query_params = parse_qs(parsed.query)
            if 'sslmode' in query_params:
                conn_params['sslmode'] = query_params['sslmode'][0]
        
        # For Supabase pooler, DO NOT use hostaddr as it breaks SSL verification
        # The pooler handles IPv4/IPv6 routing automatically via hostname
        is_supabase = 'pooler.supabase.com' in hostname or 'supabase.co' in hostname
        
        if not is_supabase:
            # Only force IPv4 for non-Supabase connections
            ipv4_addr = None
            try:
                # Try getaddrinfo with IPv4 only
                addr_info = socket.getaddrinfo(hostname, port, socket.AF_INET, socket.SOCK_STREAM)
                if addr_info:
                    ipv4_addr = addr_info[0][4][0]
            except (socket.gaierror, OSError):
                try:
                    # Fallback to gethostbyname (IPv4 only)
                    ipv4_addr = socket.gethostbyname(hostname)
                except (socket.gaierror, OSError):
                    pass
            
            if ipv4_addr:
                conn_params['hostaddr'] = ipv4_addr
                logger.info(f"Using IPv4 address {ipv4_addr} for {hostname}")
        else:
            logger.info(f"Using hostname for Supabase connection (SSL verification enabled)")
        
        # Create connection pool with conservative settings per worker
        # CRITICAL FIX: Supabase Session mode has strict connection limits
        # - minconn=0: Don't create connections at pool creation (lazy initialization)
        # - maxconn=1: Each worker can only use 1 connection maximum
        # With 4 workers, this gives us maximum 4 total connections (well within limits)
        pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=0,  # CRITICAL: Don't create connections at startup (lazy init)
            maxconn=1,  # CRITICAL: Only 1 connection per worker to stay within Supabase limits
            **conn_params
        )
        _postgres_pools[worker_pid] = pool
    return _postgres_pools[worker_pid]


class PlayerDB:
    """Database operations for player data - supports PostgreSQL and SQLite"""
    
    def __init__(self, db_path: str = "build/database/players.db", database_url: Optional[str] = None):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file (used if DATABASE_URL not set)
            database_url: PostgreSQL connection URL (takes precedence if set)
        """
        self.database_url = database_url or os.environ.get('DATABASE_URL')
        self.is_postgres = bool(self.database_url and HAS_POSTGRES)
        self.db_path = Path(db_path)
        self._from_pool = False  # Track if connection came from pool
        
        if self.is_postgres:
            # Get connection from pool (reuses existing connections)
            # Use timeout to prevent hanging if pool is exhausted
            import time
            conn_pool = _get_postgres_pool(self.database_url)
            max_retries = 3
            retry_delay = 1.0  # Start with 1 second
            
            for attempt in range(max_retries):
                try:
                    # Try to get connection with a timeout
                    # If pool is exhausted, this will raise PoolError
                    
                    # Use a timeout mechanism for getconn
                    # Note: psycopg2 pool doesn't have built-in timeout, so we use a workaround
                    self.conn = None
                    start_time = time.time()
                    timeout_seconds = 10  # 10 second timeout for getting connection
                    
                    while self.conn is None and (time.time() - start_time) < timeout_seconds:
                        try:
                            self.conn = conn_pool.getconn()
                            self._from_pool = True
                            break
                        except psycopg2.pool.PoolError:
                            # Pool exhausted, wait a bit and retry
                            if (time.time() - start_time) < timeout_seconds:
                                time.sleep(0.5)
                                continue
                            raise
                    
                    if self.conn is None:
                        raise psycopg2.pool.PoolError("Timeout waiting for connection from pool")
                    
                    # Test the connection immediately
                    test_cursor = self.conn.cursor()
                    test_cursor.execute("SELECT 1")
                    test_cursor.fetchone()
                    test_cursor.close()
                    break  # Success, exit retry loop
                    
                except (psycopg2.pool.PoolError, psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                    if attempt < max_retries - 1:
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.warning(f"Failed to get database connection (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    # If we can't get a connection after retries, log and raise
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Failed to get database connection from pool after {max_retries} attempts: {e}")
                    raise
                except Exception as e:
                    # For other exceptions, don't retry
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Failed to get database connection from pool: {e}")
                    raise
            self.param_style = '%s'  # PostgreSQL uses %s
        else:
            # SQLite connection (fallback)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.row_factory = sqlite3.Row
            self.param_style = '?'  # SQLite uses ?
        
        # Initialize schema only once per worker (thread-safe)
        self._init_schema_cached()
    
    def _param(self, *args):
        """Convert parameters to appropriate style for current database"""
        if self.is_postgres:
            return args
        return args
    
    def _ensure_connection(self):
        """Ensure connection is valid, refresh if needed"""
        if not self.is_postgres:
            return  # SQLite doesn't need this
        
        try:
            # Quick validation query
            test_cursor = self.conn.cursor()
            test_cursor.execute("SELECT 1")
            test_cursor.fetchone()
            test_cursor.close()
        except (psycopg2.OperationalError, psycopg2.InterfaceError, psycopg2.DatabaseError, psycopg2.ProgrammingError) as e:
            # Connection is dead, get a fresh one
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Connection lost, refreshing: {e}")
            
            if self._from_pool:
                worker_pid = os.getpid()
                if worker_pid in _postgres_pools:
                    try:
                        _postgres_pools[worker_pid].putconn(self.conn, close=True)  # Close bad connection
                    except:
                        pass
            # Get fresh connection with retry for transient SSL errors
            conn_pool = _get_postgres_pool(self.database_url)
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.conn = conn_pool.getconn()
                    self._from_pool = True
                    # Verify the new connection works
                    test_cursor = self.conn.cursor()
                    test_cursor.execute("SELECT 1")
                    test_cursor.fetchone()
                    test_cursor.close()
                    break  # Success, exit retry loop
                except Exception as pool_err:
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        continue
                    logger.error(f"Failed to get fresh connection from pool after {max_retries} attempts: {pool_err}")
                    raise
    
    def _execute(self, cursor, query: str, params: tuple = None):
        """Execute query with proper parameter style and handle connection errors"""
        if self.is_postgres:
            # Convert ? to %s for PostgreSQL
            query = query.replace('?', '%s')
        
        # Ensure connection is valid before executing
        if self.is_postgres:
            self._ensure_connection()
        
        # Execute query - if it fails with connection error, connection is refreshed for next attempt
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
        except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
            # Connection error detected - refresh connection for future use
            # Note: Current cursor is invalid, but connection is now fresh
            # Caller will need to create new cursor on retry
            try:
                self._ensure_connection()
            except:
                pass
            # Re-raise so caller can handle (they can retry with new cursor)
            raise
    
    def _init_schema_cached(self):
        """Initialize schema only once per worker (thread-safe)"""
        global _schema_initialized
        if _schema_initialized:
            return  # Schema already initialized
        
        with _schema_lock:
            # Double-check after acquiring lock
            if _schema_initialized:
                return
            # Initialize schema
            self._init_schema()
            _schema_initialized = True
    
    def _init_schema(self):
        """Initialize database schema"""
        cursor = self.conn.cursor()
        
        # Determine auto-increment syntax
        if self.is_postgres:
            auto_inc = "SERIAL PRIMARY KEY"
            real_type = "DOUBLE PRECISION"
            text_type = "TEXT"
        else:
            auto_inc = "INTEGER PRIMARY KEY AUTOINCREMENT"
            real_type = "REAL"
            text_type = "TEXT"
        
        # Teams table
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS teams (
                team_id {text_type} PRIMARY KEY,
                abbreviation {text_type},
                name {text_type},
                city {text_type},
                league {text_type},
                division {text_type},
                updated_at {real_type}
            )
        """)
        
        # Players table
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS players (
                player_id {text_type} PRIMARY KEY,
                mlbam_id {text_type},
                name {text_type} NOT NULL,
                first_name {text_type},
                last_name {text_type},
                position {text_type},
                primary_position {text_type},
                team_id {text_type},
                team_abbr {text_type},
                jersey_number {text_type},
                handedness {text_type},
                height {text_type},
                weight INTEGER,
                birth_date {text_type},
                birth_place {text_type},
                debut_date {text_type},
                updated_at {real_type},
                FOREIGN KEY (team_id) REFERENCES teams(team_id)
            )
        """)
        
        # Player stats (time-series)
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS player_stats (
                id {auto_inc},
                player_id {text_type} NOT NULL,
                season {text_type},
                stat_type {text_type},
                category {text_type},
                value {real_type},
                updated_at {real_type},
                FOREIGN KEY (player_id) REFERENCES players(player_id),
                UNIQUE(player_id, season, stat_type, category)
            )
        """)
        
        # Player seasons
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS player_seasons (
                id {auto_inc},
                player_id {text_type} NOT NULL,
                season {text_type} NOT NULL,
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
                avg {real_type},
                obp {real_type},
                slg {real_type},
                ops {real_type},
                updated_at {real_type},
                FOREIGN KEY (player_id) REFERENCES players(player_id),
                UNIQUE(player_id, season)
            )
        """)
        
        # Player history
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS player_history (
                id {auto_inc},
                player_id {text_type} NOT NULL,
                date {text_type} NOT NULL,
                event_type {text_type},
                from_team {text_type},
                to_team {text_type},
                details {text_type},
                updated_at {real_type},
                FOREIGN KEY (player_id) REFERENCES players(player_id)
            )
        """)
        
        # Create indexes
        for idx_query in [
            f"CREATE INDEX IF NOT EXISTS idx_players_name ON players(name)",
            f"CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_abbr)",
            f"CREATE INDEX IF NOT EXISTS idx_players_position ON players(position)",
            f"CREATE INDEX IF NOT EXISTS idx_player_seasons_player_season ON player_seasons(player_id, season)",
            f"CREATE INDEX IF NOT EXISTS idx_player_stats_player_season ON player_stats(player_id, season)",
        ]:
            try:
                self._execute(cursor, idx_query)
            except Exception:
                pass  # Index might already exist
        
        # Users table
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS users (
                id {auto_inc},
                email {text_type} UNIQUE NOT NULL,
                password_hash {text_type} NOT NULL,
                first_name {text_type} NOT NULL,
                last_name {text_type} NOT NULL,
                created_at {real_type} NOT NULL,
                updated_at {real_type} NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._execute(cursor, f"CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
        
        # Invite codes table
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS invite_codes (
                id {auto_inc},
                code {text_type} UNIQUE NOT NULL,
                created_by INTEGER,
                created_at {real_type} NOT NULL,
                used_at {real_type},
                used_by INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (created_by) REFERENCES users(id),
                FOREIGN KEY (used_by) REFERENCES users(id)
            )
        """)
        self._execute(cursor, f"CREATE INDEX IF NOT EXISTS idx_invite_codes_code ON invite_codes(code)")
        self._execute(cursor, f"CREATE INDEX IF NOT EXISTS idx_invite_codes_active ON invite_codes(is_active)")
        
        # Email verification tokens table
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS email_verification_tokens (
                id {auto_inc},
                user_id INTEGER NOT NULL,
                token {text_type} UNIQUE NOT NULL,
                created_at {real_type} NOT NULL,
                expires_at {real_type} NOT NULL,
                used_at {real_type},
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        """)
        self._execute(cursor, f"CREATE INDEX IF NOT EXISTS idx_verification_tokens_token ON email_verification_tokens(token)")
        self._execute(cursor, f"CREATE INDEX IF NOT EXISTS idx_verification_tokens_user ON email_verification_tokens(user_id)")
        
        # Ensure legacy columns exist (invite_codes table)
        self._ensure_columns_exist('invite_codes', {
            'used_at': real_type,
            'used_by': 'INTEGER',
            'is_active': 'INTEGER',
        })
        
        # Ensure legacy columns exist (users table)
        self._ensure_columns_exist('users', {
            'updated_at': real_type,
            'is_admin': 'INTEGER',
            'is_active': 'INTEGER',
            'email_verified': 'INTEGER',
            'theme_preference': text_type,
            'profile_image_path': text_type,
            'bio': text_type,
            'job_title': text_type,
            'pronouns': text_type,
            'phone': text_type,
            'timezone': text_type,
            'notification_preferences': text_type,
        })
        
        # Player documents table
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS player_documents (
                id {auto_inc},
                player_id INTEGER NOT NULL,
                filename {text_type} NOT NULL,
                path {text_type} NOT NULL,
                uploaded_by INTEGER,
                uploaded_at {real_type} NOT NULL,
                category {text_type},
                series_opponent {text_type},
                series_label {text_type},
                series_start {real_type},
                series_end {real_type},
                FOREIGN KEY (player_id) REFERENCES users(id),
                FOREIGN KEY (uploaded_by) REFERENCES users(id)
            )
        """)
        self._execute(cursor, f"CREATE INDEX IF NOT EXISTS idx_player_documents_player ON player_documents(player_id)")
        
        # Ensure legacy columns exist (player_documents table)
        self._ensure_columns_exist('player_documents', {
            'category': text_type,
            'series_opponent': text_type,
            'series_label': text_type,
            'series_start': real_type,
            'series_end': real_type,
        })
        
        # Player document log
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS player_document_log (
                id {auto_inc},
                player_id INTEGER NOT NULL,
                filename {text_type} NOT NULL,
                action {text_type} NOT NULL,
                performed_by INTEGER,
                timestamp {real_type} NOT NULL,
                FOREIGN KEY (player_id) REFERENCES users(id),
                FOREIGN KEY (performed_by) REFERENCES users(id)
            )
        """)
        self._execute(cursor, f"CREATE INDEX IF NOT EXISTS idx_player_document_log_player ON player_document_log(player_id)")
        self._execute(cursor, f"CREATE INDEX IF NOT EXISTS idx_player_document_log_time ON player_document_log(timestamp)")
        
        # Journal entries
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS journal_entries (
                id {auto_inc},
                user_id INTEGER NOT NULL,
                entry_date {text_type} NOT NULL,
                visibility {text_type} NOT NULL,
                title {text_type},
                body {text_type},
                created_at {real_type} NOT NULL,
                updated_at {real_type} NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(user_id, entry_date, visibility)
            )
        """)
        self._execute(cursor, f"""
            CREATE INDEX IF NOT EXISTS idx_journal_entries_user_date
            ON journal_entries(user_id, entry_date)
        """)
        
        # Staff notes
        self._execute(cursor, f"""
            CREATE TABLE IF NOT EXISTS staff_notes (
                id {auto_inc},
                title {text_type} NOT NULL,
                body {text_type} NOT NULL,
                team_abbr {text_type},
                tags {text_type},
                pinned INTEGER NOT NULL DEFAULT 0,
                author_id INTEGER,
                author_name {text_type},
                created_at {real_type} NOT NULL,
                updated_at {real_type} NOT NULL,
                FOREIGN KEY (author_id) REFERENCES users(id)
            )
        """)
        self._execute(cursor, f"CREATE INDEX IF NOT EXISTS idx_staff_notes_team ON staff_notes(team_abbr)")
        self._execute(cursor, f"CREATE INDEX IF NOT EXISTS idx_staff_notes_pinned ON staff_notes(pinned)")
        
        self.conn.commit()
    
    def _ensure_columns_exist(self, table_name: str, columns: Dict[str, str]):
        """Ensure columns exist in table (for migrations)"""
        existing_columns = self._get_table_columns(table_name)
        for col_name, col_type in columns.items():
            if col_name not in existing_columns:
                try:
                    default = "DEFAULT 0" if "INTEGER" in col_type else "DEFAULT NULL"
                    if col_name == "updated_at":
                        default = "DEFAULT 0"
                    elif col_name == "is_active":
                        default = "DEFAULT 1"  # New accounts should be active by default
                    elif col_name == "email_verified":
                        default = "DEFAULT 0"  # New accounts need email verification
                    self._execute(self.conn.cursor(), 
                        f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type} {default}")
                    self.conn.commit()
                except Exception:
                    pass  # Column might already exist
    
    def _get_table_columns(self, table_name: str) -> set:
        """Get list of columns in a table"""
        if self.is_postgres:
            cursor = self.conn.cursor()
            self._execute(cursor, """
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = %s
            """, (table_name,))
            return {row['column_name'] for row in cursor.fetchall()}
        else:
            cursor = self.conn.cursor()
            self._execute(cursor, f"PRAGMA table_info({table_name})")
            return {row[1] for row in cursor.fetchall()}
    
    def upsert_team(self, team_data: Dict[str, Any]):
        """Insert or update team"""
        cursor = self.conn.cursor()
        params = (
            team_data.get('id') or team_data.get('team_id'),
            team_data.get('abbreviation') or team_data.get('abbr'),
            team_data.get('name') or team_data.get('team_name'),
            team_data.get('city'),
            team_data.get('league'),
            team_data.get('division'),
            datetime.now().timestamp()
        )
        
        if self.is_postgres:
            self._execute(cursor, """
                INSERT INTO teams 
                (team_id, abbreviation, name, city, league, division, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (team_id) DO UPDATE SET
                    abbreviation = EXCLUDED.abbreviation,
                    name = EXCLUDED.name,
                    city = EXCLUDED.city,
                    league = EXCLUDED.league,
                    division = EXCLUDED.division,
                    updated_at = EXCLUDED.updated_at
            """, params)
        else:
            self._execute(cursor, """
                INSERT OR REPLACE INTO teams 
                (team_id, abbreviation, name, city, league, division, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, params)
        self.conn.commit()
    
    def upsert_player(self, player_data: Dict[str, Any]):
        """Insert or update player"""
        cursor = self.conn.cursor()
        
        player_id = (player_data.get('id') or 
                    player_data.get('player_id') or 
                    player_data.get('sportradar_id'))
        
        if not player_id:
            raise ValueError("Player data missing ID")
        
        params = (
            player_id,
            player_data.get('mlbam_id') or player_data.get('mlb_id'),
            player_data.get('name') or player_data.get('full_name') or 
                f"{player_data.get('first_name', '')} {player_data.get('last_name', '')}".strip(),
            player_data.get('first_name'),
            player_data.get('last_name'),
            player_data.get('position') or player_data.get('primary_position'),
            player_data.get('primary_position') or player_data.get('position'),
            player_data.get('team_id') or player_data.get('team', {}).get('id'),
            player_data.get('team_abbr') or player_data.get('team', {}).get('abbreviation'),
            player_data.get('jersey_number') or player_data.get('jersey'),
            player_data.get('handedness') or player_data.get('bats'),
            player_data.get('height'),
            player_data.get('weight'),
            player_data.get('birth_date') or player_data.get('date_of_birth'),
            player_data.get('birth_place'),
            player_data.get('debut_date') or player_data.get('mlb_debut'),
            datetime.now().timestamp()
        )
        
        if self.is_postgres:
            self._execute(cursor, """
                INSERT INTO players 
                (player_id, mlbam_id, name, first_name, last_name, position, 
                 primary_position, team_id, team_abbr, jersey_number, handedness,
                 height, weight, birth_date, birth_place, debut_date, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (player_id) DO UPDATE SET
                    mlbam_id = EXCLUDED.mlbam_id,
                    name = EXCLUDED.name,
                    first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    position = EXCLUDED.position,
                    primary_position = EXCLUDED.primary_position,
                    team_id = EXCLUDED.team_id,
                    team_abbr = EXCLUDED.team_abbr,
                    jersey_number = EXCLUDED.jersey_number,
                    handedness = EXCLUDED.handedness,
                    height = EXCLUDED.height,
                    weight = EXCLUDED.weight,
                    birth_date = EXCLUDED.birth_date,
                    birth_place = EXCLUDED.birth_place,
                    debut_date = EXCLUDED.debut_date,
                    updated_at = EXCLUDED.updated_at
            """, params)
        else:
            self._execute(cursor, """
                INSERT OR REPLACE INTO players 
                (player_id, mlbam_id, name, first_name, last_name, position, 
                 primary_position, team_id, team_abbr, jersey_number, handedness,
                 height, weight, birth_date, birth_place, debut_date, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, params)
        self.conn.commit()
    
    def upsert_player_season(self, player_id: str, season: str, stats: Dict[str, Any]):
        """Insert or update player season stats"""
        cursor = self.conn.cursor()
        params = (
            player_id,
            season,
            stats.get('games') or stats.get('games_played'),
            stats.get('at_bats') or stats.get('ab'),
            stats.get('hits') or stats.get('h'),
            stats.get('doubles') or stats.get('2b') or stats.get('doubles'),
            stats.get('triples') or stats.get('3b') or stats.get('triples'),
            stats.get('home_runs') or stats.get('hr'),
            stats.get('rbi') or stats.get('runs_batted_in'),
            stats.get('runs') or stats.get('r'),
            stats.get('stolen_bases') or stats.get('sb'),
            stats.get('walks') or stats.get('bb'),
            stats.get('strikeouts') or stats.get('so') or stats.get('k'),
            stats.get('avg') or stats.get('batting_average'),
            stats.get('obp') or stats.get('on_base_percentage'),
            stats.get('slg') or stats.get('slugging_percentage'),
            stats.get('ops') or stats.get('on_base_plus_slugging'),
            datetime.now().timestamp()
        )
        
        if self.is_postgres:
            self._execute(cursor, """
                INSERT INTO player_seasons
                (player_id, season, games, at_bats, hits, doubles, triples,
                 home_runs, rbi, runs, stolen_bases, walks, strikeouts,
                 avg, obp, slg, ops, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (player_id, season) DO UPDATE SET
                    games = EXCLUDED.games,
                    at_bats = EXCLUDED.at_bats,
                    hits = EXCLUDED.hits,
                    doubles = EXCLUDED.doubles,
                    triples = EXCLUDED.triples,
                    home_runs = EXCLUDED.home_runs,
                    rbi = EXCLUDED.rbi,
                    runs = EXCLUDED.runs,
                    stolen_bases = EXCLUDED.stolen_bases,
                    walks = EXCLUDED.walks,
                    strikeouts = EXCLUDED.strikeouts,
                    avg = EXCLUDED.avg,
                    obp = EXCLUDED.obp,
                    slg = EXCLUDED.slg,
                    ops = EXCLUDED.ops,
                    updated_at = EXCLUDED.updated_at
            """, params)
        else:
            self._execute(cursor, """
                INSERT OR REPLACE INTO player_seasons
                (player_id, season, games, at_bats, hits, doubles, triples,
                 home_runs, rbi, runs, stolen_bases, walks, strikeouts,
                 avg, obp, slg, ops, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, params)
        self.conn.commit()
    
    def search_players(self, search: Optional[str] = None, team: Optional[str] = None,
                      position: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Search players with filters"""
        cursor = self.conn.cursor()
        
        query = "SELECT * FROM players WHERE 1=1"
        params = []
        
        if search:
            query += " AND (name LIKE ? OR first_name LIKE ? OR last_name LIKE ?)"
            search_term = f"%{search}%"
            params.extend([search_term, search_term, search_term])
        
        if team:
            query += " AND team_abbr = ?"
            params.append(team.upper())
        
        if position:
            query += " AND position LIKE ?"
            params.append(f"%{position}%")
        
        query += " ORDER BY name LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        self._execute(cursor, query, tuple(params))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    def get_player(self, player_id: str) -> Optional[Dict[str, Any]]:
        """Get player by ID"""
        cursor = self.conn.cursor()
        self._execute(cursor, "SELECT * FROM players WHERE player_id = ?", (player_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_player_seasons(self, player_id: str) -> List[Dict[str, Any]]:
        """Get all season stats for a player"""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            SELECT * FROM player_seasons 
            WHERE player_id = ? 
            ORDER BY season DESC
        """, (player_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    def get_player_current_season(self, player_id: str, season: str = "2024") -> Optional[Dict[str, Any]]:
        """Get current season stats for a player"""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            SELECT * FROM player_seasons 
            WHERE player_id = ? AND season = ?
        """, (player_id, season))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def get_all_teams(self) -> List[Dict[str, Any]]:
        """Get all teams"""
        cursor = self.conn.cursor()
        self._execute(cursor, "SELECT * FROM teams ORDER BY abbreviation")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    
    def count_players(self, search: Optional[str] = None, team: Optional[str] = None,
                     position: Optional[str] = None) -> int:
        """Count players matching filters"""
        cursor = self.conn.cursor()
        
        query = "SELECT COUNT(*) FROM players WHERE 1=1"
        params = []
        
        if search:
            query += " AND (name LIKE ? OR first_name LIKE ? OR last_name LIKE ?)"
            search_term = f"%{search}%"
            params.extend([search_term, search_term, search_term])
        
        if team:
            query += " AND team_abbr = ?"
            params.append(team.upper())
        
        if position:
            query += " AND position LIKE ?"
            params.append(f"%{position}%")
        
        self._execute(cursor, query, tuple(params))
        result = cursor.fetchone()
        return result['count'] if self.is_postgres else result[0]
    
    def close(self):
        """Close database connection or return to pool"""
        if self.is_postgres and self._from_pool:
            worker_pid = os.getpid()
            if worker_pid in _postgres_pools:
                # Return connection to pool instead of closing
                _postgres_pools[worker_pid].putconn(self.conn)
                self._from_pool = False
            else:
                # Pool doesn't exist, just close
                self.conn.close()
        else:
            # Close SQLite connection or direct PostgreSQL connection
            self.conn.close()

    # ---------------------------
    # Authentication helpers
    # ---------------------------

    def create_user(self, email: str, password_hash: str, first_name: str, last_name: str, is_admin: bool = False, is_active: bool = True, email_verified: bool = False) -> int:
        """Insert a new user and return the user ID."""
        cursor = self.conn.cursor()
        params = (
            (email or "").strip().lower(),
            password_hash,
            (first_name or "").strip(),
            (last_name or "").strip(),
            datetime.now().timestamp(),
            datetime.now().timestamp(),
            1 if is_admin else 0,
            1 if is_active else 0,
            1 if email_verified else 0
        )
        
        if self.is_postgres:
            self._execute(cursor, """
                INSERT INTO users (email, password_hash, first_name, last_name, created_at, updated_at, is_admin, is_active, email_verified)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, params)
            user_id = cursor.fetchone()['id']
        else:
            self._execute(cursor, """
                INSERT INTO users (email, password_hash, first_name, last_name, created_at, updated_at, is_admin, is_active, email_verified)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, params)
            user_id = cursor.lastrowid
        
        self.conn.commit()
        return user_id

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Retrieve a user record by email."""
        if not email:
            return None
        cursor = self.conn.cursor()
        self._execute(cursor, "SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a user record by ID."""
        cursor = self.conn.cursor()
        self._execute(cursor, "SELECT * FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if row:
            user_dict = dict(row)
            # Ensure is_active defaults to True if not set
            if 'is_active' not in user_dict or user_dict.get('is_active') is None:
                user_dict['is_active'] = 1
            # Ensure email_verified defaults to False if not set
            if 'email_verified' not in user_dict or user_dict.get('email_verified') is None:
                user_dict['email_verified'] = 0
            return user_dict
        return None

    def list_users(self) -> List[Dict[str, Any]]:
        """Return all users sorted by creation date."""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            SELECT id, email, first_name, last_name, created_at, updated_at, is_admin, 
                   COALESCE(is_active, 1) as is_active,
                   COALESCE(email_verified, 0) as email_verified
            FROM users
            ORDER BY created_at DESC
        """)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def set_user_admin(self, user_id: int, is_admin: bool) -> None:
        """Toggle admin flag for a user."""
        cursor = self.conn.cursor()
        self._execute(cursor,
            "UPDATE users SET is_admin = ?, updated_at = ? WHERE id = ?",
            (1 if is_admin else 0, datetime.now().timestamp(), user_id)
        )
        self.conn.commit()

    def set_user_active(self, user_id: int, is_active: bool) -> None:
        """Set user active/inactive status."""
        cursor = self.conn.cursor()
        self._execute(cursor,
            "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
            (1 if is_active else 0, datetime.now().timestamp(), user_id)
        )
        self.conn.commit()

    def delete_user(self, user_id: int) -> bool:
        """Delete a user account. Returns True if deleted, False if not found."""
        cursor = self.conn.cursor()
        
        # First check if user exists and get admin status
        self._execute(cursor, "SELECT id, is_admin FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            return False
        
        # Convert row to dict for easier access
        user_dict = dict(user) if hasattr(user, 'keys') else {'id': user[0], 'is_admin': user[1] if len(user) > 1 else 0}
        
        # Prevent deleting admin accounts
        if user_dict.get("is_admin"):
            raise PermissionError("Cannot delete admin accounts.")
        
        # Delete related data first (foreign key constraints)
        # Delete verification tokens
        self._execute(cursor, "DELETE FROM email_verification_tokens WHERE user_id = ?", (user_id,))
        # Clear invite code references (set used_by to NULL to preserve code history)
        self._execute(cursor, "UPDATE invite_codes SET used_by = NULL WHERE used_by = ?", (user_id,))
        # Delete player document logs (must be before player documents)
        self._execute(cursor, "DELETE FROM player_document_log WHERE player_id = ?", (user_id,))
        # Delete player documents
        self._execute(cursor, "DELETE FROM player_documents WHERE player_id = ?", (user_id,))
        # Delete journal entries
        self._execute(cursor, "DELETE FROM journal_entries WHERE user_id = ?", (user_id,))
        
        # Finally delete the user
        self._execute(cursor, "DELETE FROM users WHERE id = ?", (user_id,))
        self.conn.commit()
        return True

    def update_user_password(self, user_id: int, password_hash: str) -> None:
        """Update a user's password hash."""
        cursor = self.conn.cursor()
        self._execute(cursor,
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (password_hash, datetime.now().timestamp(), user_id)
        )
        self.conn.commit()

    def create_verification_token(self, user_id: int, token: str, expires_in_hours: int = 24) -> int:
        """Create an email verification token"""
        cursor = self.conn.cursor()
        expires_at = datetime.now().timestamp() + (expires_in_hours * 3600)
        params = (user_id, token, datetime.now().timestamp(), expires_at)
        
        if self.is_postgres:
            self._execute(cursor, """
                INSERT INTO email_verification_tokens (user_id, token, created_at, expires_at)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, params)
            token_id = cursor.fetchone()['id']
        else:
            self._execute(cursor, """
                INSERT INTO email_verification_tokens (user_id, token, created_at, expires_at)
                VALUES (?, ?, ?, ?)
            """, params)
            token_id = cursor.lastrowid
        
        self.conn.commit()
        return token_id

    def get_verification_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Get verification token by token string"""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            SELECT * FROM email_verification_tokens 
            WHERE token = ? AND used_at IS NULL AND expires_at > ?
        """, (token, datetime.now().timestamp()))
        row = cursor.fetchone()
        return dict(row) if row else None

    def mark_token_used(self, token_id: int) -> None:
        """Mark a verification token as used"""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            UPDATE email_verification_tokens 
            SET used_at = ? 
            WHERE id = ?
        """, (datetime.now().timestamp(), token_id))
        self.conn.commit()

    def mark_email_verified(self, user_id: int) -> None:
        """Mark user's email as verified"""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            UPDATE users 
            SET email_verified = 1, updated_at = ? 
            WHERE id = ?
        """, (datetime.now().timestamp(), user_id))
        self.conn.commit()

    def delete_expired_tokens(self) -> None:
        """Clean up expired verification tokens"""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            DELETE FROM email_verification_tokens 
            WHERE expires_at < ? OR used_at IS NOT NULL
        """, (datetime.now().timestamp(),))
        self.conn.commit()

    def create_invite_code(self, code: str, created_by: Optional[int] = None) -> int:
        """Create a new invite code and return its ID."""
        cursor = self.conn.cursor()
        params = (
            code.upper().strip(),
            created_by,
            datetime.now().timestamp(),
            1  # is_active
        )
        
        if self.is_postgres:
            self._execute(cursor, """
                INSERT INTO invite_codes (code, created_by, created_at, is_active)
                VALUES (%s, %s, %s, %s)
                RETURNING id
            """, params)
            invite_id = cursor.fetchone()['id']
        else:
            self._execute(cursor, """
                INSERT INTO invite_codes (code, created_by, created_at, is_active)
                VALUES (?, ?, ?, ?)
            """, params)
            invite_id = cursor.lastrowid
        
        self.conn.commit()
        return invite_id

    def get_invite_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Retrieve an invite code by code string."""
        if not code:
            return None
        cursor = self.conn.cursor()
        self._execute(cursor, 
            "SELECT * FROM invite_codes WHERE code = ?", 
            (code.upper().strip(),)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def use_invite_code(self, code: str, used_by: int) -> bool:
        """Mark an invite code as used. Returns True if successful."""
        cursor = self.conn.cursor()
        invite = self.get_invite_code(code)
        if not invite or not invite.get("is_active") or invite.get("used_at"):
            return False
        
        self._execute(cursor, """
            UPDATE invite_codes 
            SET used_at = ?, used_by = ?, is_active = 0
            WHERE code = ?
        """, (datetime.now().timestamp(), used_by, code.upper().strip()))
        self.conn.commit()
        return True

    def list_invite_codes(self, include_used: bool = False, limit: int = 100) -> List[Dict[str, Any]]:
        """List invite codes, optionally including used ones."""
        cursor = self.conn.cursor()
        if include_used:
            self._execute(cursor, """
                SELECT 
                    ic.*,
                    u.first_name as used_by_first_name,
                    u.last_name as used_by_last_name
                FROM invite_codes ic
                LEFT JOIN users u ON ic.used_by = u.id
                ORDER BY ic.created_at DESC
                LIMIT ?
            """, (limit,))
        else:
            self._execute(cursor, """
                SELECT 
                    ic.*,
                    u.first_name as used_by_first_name,
                    u.last_name as used_by_last_name
                FROM invite_codes ic
                LEFT JOIN users u ON ic.used_by = u.id
                WHERE ic.is_active = 1 AND ic.used_at IS NULL
                ORDER BY ic.created_at DESC
                LIMIT ?
            """, (limit,))
        rows = cursor.fetchall()
        # Convert rows to dicts, handling both SQLite Row and PostgreSQL RealDictRow
        result = []
        for row in rows:
            if hasattr(row, 'keys'):
                # Already a dict-like object (PostgreSQL RealDictRow or similar)
                result.append(dict(row))
            elif hasattr(row, '__iter__') and not isinstance(row, str):
                # SQLite Row or tuple
                if self.is_postgres:
                    result.append(dict(row))
                else:
                    # SQLite Row object
                    result.append({key: row[key] for key in row.keys()})
            else:
                # Fallback
                result.append(dict(row))
        return result

    def delete_invite_code(self, code_id: int) -> bool:
        """Delete an invite code by ID."""
        cursor = self.conn.cursor()
        self._execute(cursor, "DELETE FROM invite_codes WHERE id = ?", (code_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def update_user_profile(self, user_id: int, **fields) -> bool:
        """Update user profile metadata."""
        allowed_fields = {
            "first_name",
            "last_name",
            "theme_preference",
            "profile_image_path",
            "bio",
            "job_title",
            "pronouns",
            "phone",
            "timezone",
            "notification_preferences",
        }
        updates = {key: value for key, value in fields.items() if key in allowed_fields}
        if not updates:
            return False

        assignments = []
        params = []
        for column, value in updates.items():
            assignments.append(f"{column} = ?")
            params.append(value)

        assignments.append("updated_at = ?")
        params.append(datetime.now().timestamp())
        params.append(user_id)

        cursor = self.conn.cursor()
        query = f"UPDATE users SET {', '.join(assignments)} WHERE id = ?"
        self._execute(cursor, query, tuple(params))
        self.conn.commit()
        return cursor.rowcount > 0

    # ---------------------------
    # Staff notes helpers
    # ---------------------------

    def create_staff_note(self, title: str, body: str, author_id: Optional[int], author_name: str,
                          team_abbr: Optional[str] = None, tags: Optional[List[str]] = None,
                          pinned: bool = False) -> int:
        """Create a staff note and return its ID."""
        cursor = self.conn.cursor()
        now_ts = datetime.now().timestamp()
        params = (
            (title or "").strip(),
            (body or "").strip(),
            (team_abbr or "").strip().upper() or None,
            json.dumps(tags or []),
            1 if pinned else 0,
            author_id,
            author_name,
            now_ts,
            now_ts,
        )
        
        if self.is_postgres:
            self._execute(cursor, """
                INSERT INTO staff_notes (title, body, team_abbr, tags, pinned, author_id, author_name, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, params)
            note_id = cursor.fetchone()['id']
        else:
            self._execute(cursor, """
                INSERT INTO staff_notes (title, body, team_abbr, tags, pinned, author_id, author_name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, params)
            note_id = cursor.lastrowid
        
        self.conn.commit()
        return note_id

    def update_staff_note(self, note_id: int, **fields) -> bool:
        """Update an existing staff note with provided fields."""
        allowed = {"title", "body", "team_abbr", "tags", "pinned"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False

        params = []
        assignments = []
        if "title" in updates:
            assignments.append("title = ?")
            params.append((updates["title"] or "").strip())
        if "body" in updates:
            assignments.append("body = ?")
            params.append((updates["body"] or "").strip())
        if "team_abbr" in updates:
            assignments.append("team_abbr = ?")
            value = (updates["team_abbr"] or "").strip().upper()
            params.append(value or None)
        if "tags" in updates:
            assignments.append("tags = ?")
            params.append(json.dumps(updates["tags"] or []))
        if "pinned" in updates:
            assignments.append("pinned = ?")
            params.append(1 if updates["pinned"] else 0)

        assignments.append("updated_at = ?")
        params.append(datetime.now().timestamp())
        params.append(note_id)

        cursor = self.conn.cursor()
        query = f"""
            UPDATE staff_notes
            SET {', '.join(assignments)}
            WHERE id = ?
        """
        self._execute(cursor, query, tuple(params))
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_staff_note(self, note_id: int) -> bool:
        """Remove a staff note."""
        cursor = self.conn.cursor()
        self._execute(cursor, "DELETE FROM staff_notes WHERE id = ?", (note_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def get_staff_note(self, note_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single staff note."""
        cursor = self.conn.cursor()
        self._execute(cursor, "SELECT * FROM staff_notes WHERE id = ?", (note_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_staff_notes(self, team_abbr: Optional[str] = None, limit: int = 25) -> List[Dict[str, Any]]:
        """List staff notes optionally filtered by team."""
        cursor = self.conn.cursor()
        params = []
        query = """
            SELECT id, title, body, team_abbr, tags, pinned, author_id, author_name, created_at, updated_at
            FROM staff_notes
        """
        if team_abbr:
            query += " WHERE team_abbr IS NULL OR team_abbr = ?"
            params.append(team_abbr.strip().upper())
        query += " ORDER BY pinned DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        self._execute(cursor, query, tuple(params))
        rows = cursor.fetchall()
        notes = []
        for row in rows:
            data = dict(row)
            try:
                data["tags"] = json.loads(data.get("tags") or "[]")
            except json.JSONDecodeError:
                data["tags"] = []
            notes.append(data)
        return notes

    def create_player_document(self, player_id: int, filename: str, path: str,
                               uploaded_by: Optional[int],
                               category: Optional[str] = None,
                               series_opponent: Optional[str] = None,
                               series_label: Optional[str] = None,
                               series_start: Optional[float] = None,
                               series_end: Optional[float] = None) -> int:
        """Store metadata for an uploaded player document."""
        cursor = self.conn.cursor()
        params = (
            int(player_id),
            filename,
            path,
            uploaded_by,
            datetime.now().timestamp(),
            (category or "").strip().lower() or None,
            (series_opponent or "").strip().upper() or None,
            (series_label or "").strip() or None,
            float(series_start) if series_start is not None else None,
            float(series_end) if series_end is not None else None
        )
        
        if self.is_postgres:
            self._execute(cursor, """
                INSERT INTO player_documents (
                    player_id, filename, path, uploaded_by, uploaded_at, category,
                    series_opponent, series_label, series_start, series_end
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, params)
            doc_id = cursor.fetchone()['id']
        else:
            self._execute(cursor, """
                INSERT INTO player_documents (
                    player_id, filename, path, uploaded_by, uploaded_at, category,
                    series_opponent, series_label, series_start, series_end
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, params)
            doc_id = cursor.lastrowid
        
        self.conn.commit()
        return doc_id

    def delete_player_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Delete a player document and return the deleted record."""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            SELECT id, player_id, filename, path, uploaded_by, uploaded_at,
                   category, series_opponent, series_label, series_start, series_end
            FROM player_documents
            WHERE id = ?
        """, (doc_id,))
        row = cursor.fetchone()
        if not row:
            return None
        self._execute(cursor, "DELETE FROM player_documents WHERE id = ?", (doc_id,))
        self.conn.commit()
        return dict(row)

    def list_player_documents(self, player_id: int,
                              category: Optional[str] = None) -> List[Dict[str, Any]]:
        """List uploaded documents for a player."""
        cursor = self.conn.cursor()
        params: List[Any] = [int(player_id)]
        category_clause = "category IS NULL"
        if category is not None:
            category_clause = "category = ?"
            params.append((category or "").strip().lower())
        query = f"""
            SELECT id, player_id, filename, path, uploaded_by, uploaded_at,
                   category, series_opponent, series_label, series_start, series_end
            FROM player_documents
            WHERE player_id = ?
              AND {category_clause}
            ORDER BY uploaded_at DESC
        """
        self._execute(cursor, query, tuple(params))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_latest_player_document_by_category(self, player_id: int,
                                               category: str) -> Optional[Dict[str, Any]]:
        """Return newest document for a player within a category."""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            SELECT id, player_id, filename, path, uploaded_by, uploaded_at,
                   category, series_opponent, series_label, series_start, series_end
            FROM player_documents
            WHERE player_id = ? AND category = ?
            ORDER BY uploaded_at DESC
            LIMIT 1
        """, (int(player_id), (category or "").strip().lower()))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_documents_by_category(self, category: str,
                                   limit: int = 10) -> List[Dict[str, Any]]:
        """List most recent documents by category."""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            SELECT id, player_id, filename, path, uploaded_by, uploaded_at,
                   category, series_opponent, series_label, series_start, series_end
            FROM player_documents
            WHERE category = ?
            ORDER BY uploaded_at DESC
            LIMIT ?
        """, ((category or "").strip().lower(), int(limit)))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_latest_document_by_category(self, category: str) -> Optional[Dict[str, Any]]:
        """Return the newest document in a category."""
        docs = self.list_documents_by_category(category, limit=1)
        return docs[0] if docs else None

    def get_player_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve a single player document entry."""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            SELECT id, player_id, filename, path, uploaded_by, uploaded_at,
                   category, series_opponent, series_label, series_start, series_end
            FROM player_documents
            WHERE id = ?
        """, (doc_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_expired_player_documents(self, reference_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        """Return documents whose series window has elapsed."""
        cursor = self.conn.cursor()
        if reference_ts is None:
            reference_ts = datetime.now().timestamp()
        self._execute(cursor, """
            SELECT id, player_id, filename, path, uploaded_by, uploaded_at,
                   category,
                   series_opponent, series_label, series_start, series_end
            FROM player_documents
            WHERE series_end IS NOT NULL AND series_end <= ?
        """, (reference_ts,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def record_player_document_event(self, player_id: int, filename: str, action: str,
                                     performed_by: Optional[int]) -> int:
        """Log document actions such as upload/delete."""
        cursor = self.conn.cursor()
        params = (
            int(player_id),
            filename,
            action,
            performed_by,
            datetime.now().timestamp()
        )
        
        if self.is_postgres:
            self._execute(cursor, """
                INSERT INTO player_document_log (player_id, filename, action, performed_by, timestamp)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, params)
            log_id = cursor.fetchone()['id']
        else:
            self._execute(cursor, """
                INSERT INTO player_document_log (player_id, filename, action, performed_by, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, params)
            log_id = cursor.lastrowid
        
        self.conn.commit()
        return log_id

    def list_player_document_events(self, player_id: Optional[int] = None, limit: int = 200) -> List[Dict[str, Any]]:
        """Return document activity, optionally filtered by player."""
        cursor = self.conn.cursor()
        params = []
        query = """
            SELECT id, player_id, filename, action, performed_by, timestamp
            FROM player_document_log
        """
        if player_id:
            query += " WHERE player_id = ?"
            params.append(int(player_id))
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        self._execute(cursor, query, tuple(params))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    # ---------------------------
    # Journal entry helpers
    # ---------------------------

    def upsert_journal_entry(self, user_id: int, entry_date: str, visibility: str,
                             title: Optional[str], body: Optional[str]) -> int:
        """Create or update a journal entry for a user."""
        if not entry_date:
            raise ValueError("entry_date is required")

        normalized_visibility = (visibility or "private").strip().lower()
        if normalized_visibility not in {"public", "private"}:
            raise ValueError(f"Invalid visibility: {visibility}")

        sanitized_date = entry_date.strip()
        if len(sanitized_date) != 10:
            raise ValueError("entry_date must be formatted as YYYY-MM-DD")

        now_ts = datetime.now().timestamp()
        params = (
            int(user_id),
            sanitized_date,
            normalized_visibility,
            (title or "").strip() or None,
            (body or "").strip() or "",
            now_ts,
            now_ts,
        )
        
        cursor = self.conn.cursor()
        if self.is_postgres:
            self._execute(cursor, """
                INSERT INTO journal_entries (user_id, entry_date, visibility, title, body, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, entry_date, visibility) DO UPDATE SET
                    title = EXCLUDED.title,
                    body = EXCLUDED.body,
                    updated_at = EXCLUDED.updated_at
                RETURNING id
            """, params)
            entry_id = cursor.fetchone()['id']
        else:
            self._execute(cursor, """
                INSERT INTO journal_entries (user_id, entry_date, visibility, title, body, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, entry_date, visibility) DO UPDATE SET
                    title = excluded.title,
                    body = excluded.body,
                    updated_at = excluded.updated_at
            """, params)
            entry_id = cursor.lastrowid
        
        self.conn.commit()
        return entry_id

    def get_journal_entry(self, user_id: int, entry_date: str,
                          visibility: str) -> Optional[Dict[str, Any]]:
        """Fetch a journal entry for a specific date and visibility."""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            SELECT id, user_id, entry_date, visibility, title, body, created_at, updated_at
            FROM journal_entries
            WHERE user_id = ? AND entry_date = ? AND visibility = ?
        """, (int(user_id), entry_date.strip(), (visibility or "").strip().lower()))
        row = cursor.fetchone()
        return dict(row) if row else None

    def list_journal_entries(self, user_id: int,
                             start_date: Optional[str] = None,
                             end_date: Optional[str] = None,
                             visibility: Optional[str] = None,
                             limit: int = 180) -> List[Dict[str, Any]]:
        """List journal entries for a user ordered newest first."""
        cursor = self.conn.cursor()
        clauses = ["user_id = ?"]
        params: List[Any] = [int(user_id)]

        if visibility:
            normalized_visibility = (visibility or "").strip().lower()
            clauses.append("visibility = ?")
            params.append(normalized_visibility)

        if start_date:
            clauses.append("entry_date >= ?")
            params.append(start_date.strip())

        if end_date:
            clauses.append("entry_date <= ?")
            params.append(end_date.strip())

        query = f"""
            SELECT id, user_id, entry_date, visibility, title, body, created_at, updated_at
            FROM journal_entries
            WHERE {' AND '.join(clauses)}
            ORDER BY entry_date DESC, visibility ASC
            LIMIT ?
        """
        params.append(int(limit) if limit and limit > 0 else 180)

        self._execute(cursor, query, tuple(params))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def delete_journal_entry(self, entry_id: int, user_id: int) -> bool:
        """Remove a journal entry."""
        cursor = self.conn.cursor()
        self._execute(cursor, """
            DELETE FROM journal_entries
            WHERE id = ? AND user_id = ?
        """, (int(entry_id), int(user_id)))
        self.conn.commit()
        return cursor.rowcount > 0
