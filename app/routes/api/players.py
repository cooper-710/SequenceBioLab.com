"""
Player API routes
"""
from flask import Blueprint, request, jsonify
from urllib.parse import unquote
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

bp = Blueprint('players', __name__)

# Import PlayerDB if available
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
    from database import PlayerDB
except ImportError:
    PlayerDB = None

# Import CSV data loader if available
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
    from csv_data_loader import CSVDataLoader
    from app.config import Config
    csv_loader = CSVDataLoader(str(Config.ROOT_DIR))
except (ImportError, Exception):
    csv_loader = None

# In-memory cache for playIds (by game_pk)
# This persists across requests to avoid repeated API calls
_play_ids_cache = {}
_cache_lock = Lock()  # Thread-safe access to cache

# In-memory cache for available seasons (by player_id + opponent_id + role)
_seasons_cache = {}
_seasons_cache_lock = Lock()  # Thread-safe access to seasons cache


@bp.route('/players', methods=['GET'])
def api_players():
    """List/search players with filters"""
    if not PlayerDB:
        return jsonify({"error": "Database not available"}), 500
    
    try:
        db = PlayerDB()
        search = request.args.get('search', '').strip() or None
        team = request.args.get('team', '').strip() or None
        position = request.args.get('position', '').strip() or None
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 25))
        offset = (page - 1) * limit
        
        players = db.search_players(search=search, team=team, position=position, limit=limit, offset=offset)
        total = db.count_players(search=search, team=team, position=position)
        
        db.close()
        
        return jsonify({
            "players": players,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/players/<player_id>', methods=['GET'])
def api_player_detail(player_id):
    """Get detailed player profile"""
    if not PlayerDB:
        return jsonify({"error": "Database not available"}), 500
    
    try:
        db = PlayerDB()
        player = db.get_player(player_id)
        
        if not player:
            db.close()
            return jsonify({"error": "Player not found"}), 404
        
        # Get current season stats (default to 2024)
        season = request.args.get('season', '2024')
        current_season = db.get_player_current_season(player_id, season)
        
        db.close()
        
        return jsonify({
            "player": player,
            "current_season": current_season
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/players/<player_id>/stats', methods=['GET'])
def api_player_stats(player_id):
    """Get player stats history"""
    if not PlayerDB:
        return jsonify({"error": "Database not available"}), 500
    
    try:
        db = PlayerDB()
        seasons = db.get_player_seasons(player_id)
        db.close()
        
        return jsonify({
            "player_id": player_id,
            "seasons": seasons
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/players/<player_id>/seasons', methods=['GET'])
def api_player_seasons(player_id):
    """Get season-by-season stats (alias for stats)"""
    return api_player_stats(player_id)


@bp.route('/teams', methods=['GET'])
def api_teams():
    """Get all teams for filter dropdown"""
    if not PlayerDB:
        return jsonify({"error": "Database not available"}), 500
    
    try:
        db = PlayerDB()
        teams = db.get_all_teams()
        db.close()
        
        return jsonify({"teams": teams})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# CSV-based Player Search API Routes
@bp.route('/csv/search', methods=['GET'])
def api_csv_search():
    """Search for players by name in CSV files"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        search_term = request.args.get('q', '').strip()
        if not search_term:
            return jsonify({"players": []})
        
        players = csv_loader.search_players(search_term)
        return jsonify({"players": players})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.route('/csv/player/<player_name>/seasons', methods=['GET'])
def api_csv_player_seasons(player_name):
    """Get available seasons for a specific player"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        # Decode URL-encoded player name
        player_name = unquote(player_name)
        
        # Try direct player data lookup first (more reliable)
        player_data = csv_loader.get_player_data(player_name)
        if player_data and player_data.get('fangraphs'):
            # Extract unique seasons from fangraphs data
            seasons = set()
            for row in player_data['fangraphs']:
                if 'Season' in row and row['Season'] is not None:
                    try:
                        seasons.add(int(row['Season']))
                    except (ValueError, TypeError):
                        pass
            
            if seasons:
                seasons_str = sorted([str(s) for s in seasons], reverse=True)
                # Use the actual name from the data (preserves accents)
                actual_name = player_data.get('name', player_name)
                return jsonify({
                    "player": actual_name,
                    "seasons": seasons_str
                })
        
        # Fallback: Get all players summary to find this player
        players = csv_loader.get_all_players_summary()
        # Use normalization for matching
        player_name_normalized = csv_loader._normalize_name(player_name)
        
        for player in players:
            if csv_loader._normalize_name(player.get('name', '')) == player_name_normalized:
                seasons = player.get('seasons', [])
                # Ensure seasons are strings for the dropdown
                seasons_str = [str(s) for s in seasons] if seasons else []
                return jsonify({
                    "player": player.get('name'),  # Return original name with accents
                    "seasons": seasons_str
                })
        
        return jsonify({"error": f"Player '{player_name}' not found"}), 404
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.route('/csv/player/<player_name>', methods=['GET'])
def api_csv_player_data(player_name):
    """Get all data for a specific player from CSV files"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        # Decode URL-encoded player name
        player_name = unquote(player_name)
        
        player_data = csv_loader.get_player_data(player_name)
        return jsonify(player_data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.route('/players/sync', methods=['POST'])
def api_sync_players():
    """Trigger database sync (background job)"""
    # This would trigger a background sync job
    # For now, return a message indicating it needs to be run manually
    return jsonify({
        "message": "Sync initiated. This is a long-running operation.",
        "status": "queued"
    }), 202


@bp.route('/player-type', methods=['GET'])
def api_player_type():
    """Detect if a player is a pitcher or batter"""
    player_name = request.args.get('player', '').strip()
    
    if not player_name:
        return jsonify({"error": "Player name is required"}), 400
    
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
        from scrape_savant import lookup_batter_id
        import statsapi
        
        # Try to get player info from statsapi
        try:
            player_id = lookup_batter_id(player_name)
            
            # Try to get player position info
            # Check if player has pitching stats (more reliable than position)
            from datetime import datetime
            current_year = datetime.now().year
            
            try:
                # Try to get pitching stats
                pitching_stats = statsapi.player_stat_data(player_id, group='[pitching]', type='season', season=current_year)
                if pitching_stats and pitching_stats.get('stats'):
                    # Has pitching stats, likely a pitcher
                    return jsonify({
                        "player": player_name,
                        "is_pitcher": True,
                        "player_type": "pitcher"
                    })
            except Exception:
                pass
            
            # Try to get hitting stats
            try:
                hitting_stats = statsapi.player_stat_data(player_id, group='[hitting]', type='season', season=current_year)
                if hitting_stats and hitting_stats.get('stats'):
                    # Has hitting stats
                    # Check if also has pitching - if so, likely primarily a pitcher
                    try:
                        pitching_stats = statsapi.player_stat_data(player_id, group='[pitching]', type='season', season=current_year)
                        if pitching_stats and pitching_stats.get('stats'):
                            return jsonify({
                                "player": player_name,
                                "is_pitcher": True,
                                "player_type": "pitcher"
                            })
                    except Exception:
                        pass
                    
                    return jsonify({
                        "player": player_name,
                        "is_pitcher": False,
                        "player_type": "batter"
                    })
            except Exception:
                pass
            
            # Fallback: check multiple years
            for year in range(current_year, current_year - 5, -1):
                try:
                    pitching_stats = statsapi.player_stat_data(player_id, group='[pitching]', type='season', season=year)
                    if pitching_stats and pitching_stats.get('stats'):
                        return jsonify({
                            "player": player_name,
                            "is_pitcher": True,
                            "player_type": "pitcher"
                        })
                except Exception:
                    continue
            
            # Default to batter if we can't determine
            return jsonify({
                "player": player_name,
                "is_pitcher": False,
                "player_type": "batter"
            })
            
        except Exception as e:
            # If lookup fails, try CSV data loader as fallback
            if csv_loader:
                try:
                    player_data = csv_loader.get_player_data(player_name)
                    if player_data:
                        # Check positions in CSV data
                        positions = []
                        if player_data.get('fangraphs'):
                            for row in player_data['fangraphs']:
                                if 'Pos' in row and row['Pos']:
                                    positions.append(str(row['Pos']))
                        
                        # Check if any position contains 'P' for pitcher
                        for pos in positions:
                            if 'P' in pos.upper():
                                return jsonify({
                                    "player": player_name,
                                    "is_pitcher": True,
                                    "player_type": "pitcher"
                                })
                        
                        # Default to batter
                        return jsonify({
                            "player": player_name,
                            "is_pitcher": False,
                            "player_type": "batter"
                        })
                except Exception:
                    pass
            
            return jsonify({"error": f"Could not determine player type: {str(e)}"}), 404
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Error detecting player type: {str(e)}"}), 500


@bp.route('/matchups/seasons', methods=['GET'])
def api_matchups_seasons():
    """Get available seasons with matchup data for a player vs opponent (optimized with caching)"""
    
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
        from scrape_savant import lookup_batter_id, fetch_batter_statcast, fetch_pitcher_statcast
    except ImportError:
        return jsonify({"error": "Statcast module not available"}), 500
    
    # Get parameters
    player_name = request.args.get('player', '').strip()
    opponent_name = request.args.get('opponent', '').strip()
    player_role = request.args.get('role', 'batter').lower()
    
    if not player_name or not opponent_name:
        return jsonify({"error": "Both player and opponent names are required"}), 400
    
    try:
        # Look up IDs for both players
        player_id = lookup_batter_id(player_name)
        opponent_id = lookup_batter_id(opponent_name)
    except Exception as e:
        return jsonify({"error": f"Could not find player IDs: {str(e)}"}), 404
    
    # Check cache first (thread-safe)
    cache_key = f"{player_id}_{opponent_id}_{player_role}"
    with _seasons_cache_lock:
        if cache_key in _seasons_cache:
            return jsonify({"seasons": _seasons_cache[cache_key]})
    
    try:
        from datetime import date
        import pandas as pd
        
        today = date.today()
        start_year = 2015
        end_year = today.year
        
        # Fetch Statcast data for a wide date range
        start_date = f"{start_year}-03-01"
        end_date = f"{end_year}-11-30"
        
        # Fetch Statcast data (unfiltered first)
        df_raw = pd.DataFrame()
        try:
            if player_role == 'pitcher':
                df_raw = fetch_pitcher_statcast(player_id, start_date, end_date)
            else:
                df_raw = fetch_batter_statcast(player_id, start_date, end_date)
        except Exception as e:
            return jsonify({"error": f"Error fetching Statcast data: {str(e)}"}), 500
        
        if df_raw.empty:
            seasons = []
            # Cache empty result too
            with _seasons_cache_lock:
                _seasons_cache[cache_key] = seasons
            return jsonify({"seasons": seasons})
        
        # Find the correct column name for filtering
        filter_col = None
        if player_role == 'pitcher':
            for col_name in ['batter', 'batter_id']:
                if col_name in df_raw.columns:
                    filter_col = col_name
                    break
        else:
            for col_name in ['pitcher', 'pitcher_id']:
                if col_name in df_raw.columns:
                    filter_col = col_name
                    break
        
        if not filter_col:
            seasons = []
            with _seasons_cache_lock:
                _seasons_cache[cache_key] = seasons
            return jsonify({"seasons": seasons})
        
        # Convert IDs to same type and filter to opponent
        df_raw[filter_col] = pd.to_numeric(df_raw[filter_col], errors='coerce')
        opponent_id_int = int(opponent_id)
        df = df_raw[df_raw[filter_col] == opponent_id_int].copy()
        
        if df.empty:
            seasons = []
            with _seasons_cache_lock:
                _seasons_cache[cache_key] = seasons
            return jsonify({"seasons": seasons})
        
        # Filter to regular season games only
        if 'game_type' in df.columns:
            df = df[df['game_type'] == 'R'].copy()
        
        if df.empty:
            seasons = []
            with _seasons_cache_lock:
                _seasons_cache[cache_key] = seasons
            return jsonify({"seasons": seasons})
        
        # Get available seasons from game_date or game_year
        # OPTIMIZATION: Prefer game_year if available (faster than parsing dates)
        seasons = set()
        if 'game_year' in df.columns:
            years = df['game_year'].dropna().unique()
            seasons = set(int(y) for y in years if pd.notna(y))
        elif 'game_date' in df.columns:
            # Only parse dates if game_year not available
            df['game_date'] = pd.to_datetime(df['game_date'], errors='coerce')
            years = df['game_date'].dt.year.dropna().unique()
            seasons = set(int(y) for y in years if pd.notna(y))
        
        # Filter to valid season range and sort
        seasons = sorted([s for s in seasons if start_year <= s <= end_year])
        
        # Cache the result (thread-safe)
        with _seasons_cache_lock:
            _seasons_cache[cache_key] = seasons
        
        return jsonify({"seasons": seasons})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Error fetching available seasons: {str(e)}"}), 500


def get_all_play_ids_from_game(game_pk):
    """Fetch all playIds (UUIDs) for all at-bats in a game from MLB StatsAPI"""
    try:
        import statsapi
        game_data = statsapi.get('game', {'gamePk': game_pk})
        
        # Get game date from StatsAPI (more accurate than Statcast)
        game_date = None
        if isinstance(game_data, dict) and 'gameData' in game_data:
            game_date = game_data['gameData'].get('datetime', {}).get('originalDate', '')
        
        if isinstance(game_data, dict) and 'liveData' in game_data:
            plays = game_data['liveData'].get('plays', {}).get('allPlays', [])
            
            # Build a dictionary: {at_bat_index: {'by_pitch_num': {...}, 'by_sequence': [...], 'batter_id': ..., 'pitcher_id': ..., 'game_date': ...}}
            all_play_ids = {}
            
            for play in plays:
                at_bat_index = play.get('about', {}).get('atBatIndex')
                if at_bat_index is not None:
                    play_ids_by_pitch_num = {}
                    play_ids_by_sequence = []
                    
                    # Get batter and pitcher IDs for verification
                    batter_id = play.get('matchup', {}).get('batter', {}).get('id')
                    pitcher_id = play.get('matchup', {}).get('pitcher', {}).get('id')
                    
                    if 'playEvents' in play:
                        # Collect playIds both by pitchNumber, event index, and sequence order
                        # IMPORTANT: Collect ALL pitch events (even if missing playId) to maintain sequence alignment
                        # IMPORTANT: Check multiple locations for playId as StatsAPI may store it differently
                        by_event_index = {}
                        by_pitch_sequence = {}  # Map Statcast sequence (0,1,2...) to playId
                        pitch_sequence_counter = 0  # Count only pitch events (ignores non-pitch events)
                        
                        for event in play['playEvents']:
                            if event.get('isPitch'):
                                pitch_num = event.get('pitchNumber')
                                event_index = event.get('index')  # Event index in the sequence (includes non-pitch events)
                                
                                # Try multiple locations for playId (StatsAPI may store it in different places)
                                play_id = None
                                
                                # Check primary location
                                if event.get('playId'):
                                    play_id = event.get('playId')
                                # Check alternate field names
                                elif event.get('play_id'):
                                    play_id = event.get('play_id')
                                # Check nested in content
                                elif event.get('content', {}).get('playId'):
                                    play_id = event.get('content', {}).get('playId')
                                elif event.get('content', {}).get('link'):
                                    # If link is a playId format (UUID), use it
                                    link = event.get('content', {}).get('link', '')
                                    if link and len(link) > 30:  # UUID-like string
                                        play_id = link
                                
                                # Store in sequence list (including None for pitches without playId)
                                play_ids_by_sequence.append(play_id)
                                
                                # Store by pitch sequence (0, 1, 2, ...) - this matches Statcast's sequence
                                by_pitch_sequence[pitch_sequence_counter] = play_id
                                pitch_sequence_counter += 1
                                
                                # Store in pitch_number dict only if playId exists
                                if pitch_num and play_id:
                                    play_ids_by_pitch_num[pitch_num] = play_id
                                
                                # Store by event index (actual StatsAPI event index, includes non-pitch events)
                                if event_index is not None and play_id:
                                    by_event_index[event_index] = play_id
                    
                    if play_ids_by_pitch_num or play_ids_by_sequence:
                        all_play_ids[at_bat_index] = {
                            'by_pitch_num': play_ids_by_pitch_num,
                            'by_sequence': play_ids_by_sequence,
                            'by_pitch_sequence': by_pitch_sequence,  # Pitch-only sequence (0,1,2...) - matches Statcast
                            'by_event_index': by_event_index,  # Event index-based matching (includes non-pitch events)
                            'batter_id': batter_id,
                            'pitcher_id': pitcher_id,
                            'game_date': game_date  # Use StatsAPI date
                        }
            
            return all_play_ids
    except Exception as e:
        print(f"Error fetching playIds from MLB API for game {game_pk}: {e}")
        return {}
    return {}


@bp.route('/matchups', methods=['GET'])
def api_matchups():
    """Get historical matchup data between a player and opponent using Statcast ONLY with proper filtering"""
    
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
        from scrape_savant import lookup_batter_id, fetch_batter_statcast, fetch_pitcher_statcast
    except ImportError:
        return jsonify({"error": "Statcast module not available"}), 500
    
    # Get parameters
    player_name = request.args.get('player', '').strip()
    opponent_name = request.args.get('opponent', '').strip()
    player_role = request.args.get('role', 'batter').lower()
    season = request.args.get('season', type=int)
    seasons = request.args.getlist('seasons')
    
    if not player_name or not opponent_name:
        return jsonify({"error": "Both player and opponent names are required"}), 400
    
    try:
        # Look up IDs for both players
        player_id = lookup_batter_id(player_name)
        opponent_id = lookup_batter_id(opponent_name)
        
        print(f"DEBUG: Player: {player_name} -> ID: {player_id}")
        print(f"DEBUG: Opponent: {opponent_name} -> ID: {opponent_id}")
        print(f"DEBUG: Role: {player_role}")
    except Exception as e:
        return jsonify({"error": f"Could not find player IDs: {str(e)}"}), 404
    
    # Initialize variables for cleanup
    df_raw = None
    df = None
    df_with_events = None
    pa_ending = None
    
    try:
        from datetime import date
        import numpy as np
        import pandas as pd
        import math
        import gc  # For garbage collection
        
        today = date.today()
        
        # MEMORY FIX: Strict limits to prevent memory exhaustion
        MAX_SEASONS = 2  # Hard limit - max 2 years
        MAX_ROWS = 300000  # Reject if data exceeds this
        
        # Determine seasons with hard limit
        if seasons and len(seasons) > 0:
            season_ints = sorted([int(s) for s in seasons if s.isdigit()])[:MAX_SEASONS]  # Hard limit
            if not season_ints:
                season_ints = [today.year - 1, today.year]  # Default to 2 years
        elif season:
            season_ints = [season]
        else:
            season_ints = [today.year - 1, today.year]  # Default to 2 years (reduced from 4)
        
        # Calculate date range
        if season_ints:
            min_season = min(season_ints)
            max_season = max(season_ints)
            start_date = f"{min_season}-03-01"
            end_date = f"{max_season}-11-30"
        else:
            start_date = f"{today.year - 1}-03-01"  # Reduced from 4 to 2 years
            end_date = today.strftime("%Y-%m-%d")
        
        # STEP 1: Fetch Statcast data (unfiltered first)
        df_raw = pd.DataFrame()
        try:
            if player_role == 'pitcher':
                df_raw = fetch_pitcher_statcast(player_id, start_date, end_date)
                print(f"Fetched Statcast data for pitcher {player_id}: {len(df_raw)} rows (BEFORE filtering)")
            else:
                df_raw = fetch_batter_statcast(player_id, start_date, end_date)
                print(f"Fetched Statcast data for batter {player_id}: {len(df_raw)} rows (BEFORE filtering)")
        except Exception as e:
            print(f"Error fetching Statcast data: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Error fetching Statcast data: {str(e)}"}), 500
        
        # MEMORY FIX: Reject if data is too large (before processing)
        if len(df_raw) > MAX_ROWS:
            row_count = len(df_raw)
            del df_raw
            gc.collect()
            return jsonify({
                "error": f"Too much data to process ({row_count:,} rows). Please select fewer seasons (max 2 years recommended)."
            }), 400
        
        if df_raw.empty:
            del df_raw
            gc.collect()
            return jsonify({
                "player": player_name,
                "opponent": opponent_name,
                "player_role": player_role,
                "matchups": [],
                "summary": {},
                "message": "No Statcast data found for these players"
            })
        
        # STEP 2: Find the correct column name for filtering
        filter_col = None
        if player_role == 'pitcher':
            for col_name in ['batter', 'batter_id']:
                if col_name in df_raw.columns:
                    filter_col = col_name
                    break
        else:
            for col_name in ['pitcher', 'pitcher_id']:
                if col_name in df_raw.columns:
                    filter_col = col_name
                    break
        
        if not filter_col:
            available_cols = df_raw.columns.tolist()
            del df_raw
            gc.collect()
            return jsonify({
                "error": f"Could not find filter column. Available columns: {available_cols}"
            }), 500
        
        print(f"DEBUG: Using filter column: '{filter_col}'")
        print(f"DEBUG: Looking for opponent_id: {opponent_id} (type: {type(opponent_id)})")
        
        # STEP 3: Convert IDs to same type and filter
        df_raw[filter_col] = pd.to_numeric(df_raw[filter_col], errors='coerce')
        opponent_id_int = int(opponent_id)
        
        # Debug: Show unique values before filtering
        unique_vals = df_raw[filter_col].dropna().unique()[:20]
        print(f"DEBUG: Unique {filter_col} values in data (first 20): {unique_vals}")
        print(f"DEBUG: Looking for {opponent_id_int} in these values: {opponent_id_int in unique_vals}")
        
        # CRITICAL: Filter BEFORE any calculations to reduce memory
        df = df_raw[df_raw[filter_col] == opponent_id_int].copy()
        
        # Clean up large DataFrame immediately after filtering
        del df_raw
        gc.collect()
        
        if df.empty:
            del df
            gc.collect()
            return jsonify({
                "player": player_name,
                "opponent": opponent_name,
                "player_role": player_role,
                "matchups": [],
                "summary": {},
                "error": f"No matchup data found. Player {player_name} (ID: {player_id}) has no at-bats vs {opponent_name} (ID: {opponent_id_int}) in selected seasons."
            })
        
        print(f"DEBUG: After filtering to {opponent_id_int}: {len(df)} rows")
        
        # STEP 4: Filter to regular season games only (exclude spring training, exhibition, etc.)
        if 'game_type' in df.columns:
            before_reg_season = len(df)
            df = df[df['game_type'] == 'R'].copy()
            print(f"DEBUG: After filtering to regular season games (game_type='R'): {before_reg_season} -> {len(df)} rows")
            
            if df.empty:
                del df
                gc.collect()
                return jsonify({
                    "player": player_name,
                    "opponent": opponent_name,
                    "player_role": player_role,
                    "matchups": [],
                    "summary": {},
                    "error": f"No regular season matchup data found. Player {player_name} (ID: {player_id}) has no regular season at-bats vs {opponent_name} (ID: {opponent_id_int}) in selected seasons."
                })
        
        # STEP 5: Verify filter worked
        unique_after = df[filter_col].unique()
        if len(unique_after) > 1 or (len(unique_after) == 1 and int(unique_after[0]) != opponent_id_int):
            del df
            gc.collect()
            return jsonify({
                "error": f"Filter validation failed. Expected only {opponent_id_int}, but found: {unique_after}"
            }), 500
        
        # STEP 5: Now calculate stats using the EXACT logic from plots_hitter_checkin.py
        # Filter to rows with valid events
        if 'events' not in df.columns or 'at_bat_number' not in df.columns or 'game_pk' not in df.columns:
            del df
            gc.collect()
            return jsonify({
                "error": "Missing required columns: events, at_bat_number, or game_pk"
            }), 500
        
        events_mask = df['events'].notna()
        events_str = df['events'].astype(str).str.lower()
        events_mask = events_mask & (events_str != 'nan') & (events_str != '') & (events_str != 'none')
        df_with_events = df[events_mask].copy()
        
        if df_with_events.empty:
            del df_with_events
            if df is not None:
                del df
            gc.collect()
            return jsonify({
                "player": player_name,
                "opponent": opponent_name,
                "player_role": player_role,
                "matchups": [],
                "summary": {},
                "message": "No plate appearance data found"
            })
        
        # Group by at-bat to get unique at-bats (use last pitch of each at-bat)
        if 'pitch_number' in df_with_events.columns:
            df_with_events = df_with_events.sort_values(['game_pk', 'at_bat_number', 'pitch_number'])
        else:
            df_with_events = df_with_events.sort_index()
        
        pa_ending = df_with_events.groupby(['game_pk', 'at_bat_number'], sort=False).last().reset_index()
        pa_ending = pa_ending.drop_duplicates(subset=['game_pk', 'at_bat_number'], keep='last')
        
        print(f"DEBUG: Unique at-bats after grouping: {len(pa_ending)}")
        
        # Now use the EXACT event categorization from plots_hitter_checkin.py
        events_series = pa_ending['events'].astype(str).str.lower()
        
        # Exclude non-PA events (but NOT sac_fly - it counts as PA)
        non_pa_events = ['sac_bunt', 'sac_bunt_double_play', 'catcher_interf', 
                        'caught_stealing_2b', 'caught_stealing_3b', 'caught_stealing_home',
                        'pickoff_1b', 'pickoff_2b', 'pickoff_3b', 'other_out']
        pa_ending = pa_ending[~events_series.isin(non_pa_events)]
        events_series = pa_ending['events'].astype(str).str.lower()
        
        # Separate sac flies (count in PA but NOT in AB)
        sac_flies = pa_ending[events_series.isin(['sac_fly', 'sac_fly_double_play'])]
        pa_for_ab = pa_ending[~pa_ending.index.isin(sac_flies.index)] if not sac_flies.empty else pa_ending
        events_for_ab = pa_for_ab['events'].astype(str).str.lower()
        
        # Categorize events
        hits = pa_for_ab[events_for_ab.isin(['single', 'double', 'triple', 'home_run'])]
        outs = pa_for_ab[events_for_ab.isin(['strikeout', 'strikeout_double_play', 'field_out', 'force_out',
                                            'grounded_into_double_play', 'fielders_choice', 'fielders_choice_out',
                                            'double_play', 'triple_play'])]
        walks = pa_for_ab[events_for_ab.isin(['walk', 'intent_walk', 'hit_by_pitch'])]
        strikeouts = pa_for_ab[events_for_ab.isin(['strikeout', 'strikeout_double_play'])]
        home_runs = pa_for_ab[events_for_ab == 'home_run']
        
        # Calculate totals
        total_pa = len(pa_ending)
        total_ab = len(hits) + len(outs)
        total_h = len(hits)
        total_hr = len(home_runs)
        total_so = len(strikeouts)
        total_bb = len(walks)
        total_sf = len(sac_flies)
        
        # Calculate slugging (total bases)
        total_bases = 0
        for _, row in hits.iterrows():
            event = str(row['events']).lower()
            if event == 'single':
                total_bases += 1
            elif event == 'double':
                total_bases += 2
            elif event == 'triple':
                total_bases += 3
            elif event == 'home_run':
                total_bases += 4
        
        # Calculate rate stats
        avg = round(total_h / total_ab, 3) if total_ab > 0 else 0.0
        obp = round((total_h + total_bb) / total_pa, 3) if total_pa > 0 else 0.0
        slg = round(total_bases / total_ab, 3) if total_ab > 0 else 0.0
        ops = round(obp + slg, 3)
        
        print(f"DEBUG: Final calculated stats: AB={total_ab}, H={total_h}, HR={total_hr}, BB={total_bb}, SO={total_so}, PA={total_pa}, SF={total_sf}")
        print(f"DEBUG: Verification: AB ({total_ab}) + BB ({total_bb}) + SF ({total_sf}) = {total_ab + total_bb + total_sf} (should equal PA {total_pa})")
        
        # Build at-bats list for display
        at_bats = []
        if 'game_pk' in df.columns and 'at_bat_number' in df.columns:
            grouped = df.groupby(['game_pk', 'at_bat_number'])
            
            # Calculate player-relative at-bat numbers per game
            # Group all at-bats by game_pk and sort by original at_bat_number
            game_at_bats = {}
            for (game_pk, ab_num), ab_df in grouped:
                game_pk_int = int(game_pk)
                if game_pk_int not in game_at_bats:
                    game_at_bats[game_pk_int] = []
                game_at_bats[game_pk_int].append((int(ab_num), game_pk, ab_num, ab_df))
            
            # Sort by original at_bat_number within each game and assign player-relative numbers
            player_at_bat_numbers = {}  # {(game_pk, original_ab_num): player_relative_num}
            for game_pk_int, at_bat_list in game_at_bats.items():
                # Sort by original at_bat_number
                at_bat_list.sort(key=lambda x: x[0])
                # Assign sequential numbers starting from 1
                for player_ab_num, (original_ab_num, game_pk, ab_num, ab_df) in enumerate(at_bat_list, start=1):
                    player_at_bat_numbers[(game_pk_int, original_ab_num)] = player_ab_num
            
            # Cache playIds by game_pk - fetch all at-bats for a game at once
            # OPTIMIZATION: Use parallel fetching and in-memory cache
            play_ids_cache = {}
            
            # First pass: collect all unique game_pks
            unique_game_pks = df['game_pk'].dropna().unique()
            
            # Helper function to fetch playIds with caching
            def fetch_play_ids_cached(game_pk):
                """Fetch playIds for a game, using cache if available"""
                game_pk_int = int(game_pk)
                
                # Check cache first (thread-safe)
                with _cache_lock:
                    if game_pk_int in _play_ids_cache:
                        return game_pk_int, _play_ids_cache[game_pk_int]
                
                # Fetch from API
                play_ids = get_all_play_ids_from_game(game_pk_int)
                
                # Store in cache (thread-safe)
                with _cache_lock:
                    _play_ids_cache[game_pk_int] = play_ids
                
                return game_pk_int, play_ids
            
            # OPTIMIZATION: Fetch playIds in parallel (max 10 concurrent requests)
            # This speeds up requests when there are multiple games
            if len(unique_game_pks) > 1:
                print(f"DEBUG: Fetching playIds for {len(unique_game_pks)} games in parallel...")
                with ThreadPoolExecutor(max_workers=10) as executor:
                    future_to_game = {
                        executor.submit(fetch_play_ids_cached, game_pk): game_pk
                        for game_pk in unique_game_pks if pd.notna(game_pk)
                    }
                    
                    for future in as_completed(future_to_game):
                        try:
                            game_pk_int, play_ids = future.result()
                            play_ids_cache[game_pk_int] = play_ids
                        except Exception as e:
                            game_pk = future_to_game[future]
                            print(f"DEBUG: Error fetching playIds for game {game_pk}: {e}")
                            play_ids_cache[int(game_pk)] = {}
                
                print(f"DEBUG: Fetched playIds for {len(play_ids_cache)} games")
            else:
                # Single game - no need for threading overhead
                for game_pk in unique_game_pks:
                    if pd.notna(game_pk):
                        game_pk_int, play_ids = fetch_play_ids_cached(game_pk)
                        play_ids_cache[game_pk_int] = play_ids
            
            for (game_pk, ab_num), ab_df in grouped:
                # Get Statcast batter and pitcher IDs for this at-bat
                first_pitch = ab_df.iloc[0]
                statcast_batter_id = None
                statcast_pitcher_id = None
                
                if player_role == 'pitcher':
                    # If player is pitcher, opponent is batter
                    statcast_batter_id = int(first_pitch.get('batter')) if pd.notna(first_pitch.get('batter')) else None
                    statcast_pitcher_id = player_id
                else:
                    # If player is batter, opponent is pitcher
                    statcast_batter_id = player_id
                    statcast_pitcher_id = int(first_pitch.get('pitcher')) if pd.notna(first_pitch.get('pitcher')) else None
                
                # Get playIds for this at-bat from cache
                game_play_ids = play_ids_cache.get(int(game_pk), {})
                
                # Find the correct StatsAPI atBatIndex by matching batter/pitcher IDs AND pitch count
                # Statcast's at_bat_number may not match StatsAPI's atBatIndex
                # Multiple at-bats may have same batter/pitcher, so we need to match by pitch count too
                play_ids = {}
                matched_at_bat_index = None
                statcast_pitch_count = len(ab_df)
                
                # First, collect all potential matches (same batter/pitcher)
                potential_matches = []
                for at_bat_index, play_data in game_play_ids.items():
                    if isinstance(play_data, dict):
                        statsapi_batter_id = play_data.get('batter_id')
                        statsapi_pitcher_id = play_data.get('pitcher_id')
                        statsapi_pitch_count = len(play_data.get('by_pitch_sequence', {}))
                        
                        # Match by batter and pitcher IDs
                        if (statcast_batter_id and statsapi_batter_id and int(statcast_batter_id) == int(statsapi_batter_id) and
                            statcast_pitcher_id and statsapi_pitcher_id and int(statcast_pitcher_id) == int(statsapi_pitcher_id)):
                            pitch_count_diff = abs(statsapi_pitch_count - statcast_pitch_count)
                            potential_matches.append({
                                'at_bat_index': at_bat_index,
                                'play_data': play_data,
                                'pitch_count': statsapi_pitch_count,
                                'pitch_count_diff': pitch_count_diff
                            })
                
                # Find the best match - prefer exact pitch count match, then closest
                if potential_matches:
                    # Sort by pitch count difference (prefer exact matches, then closest)
                    potential_matches.sort(key=lambda x: (x['pitch_count_diff'], x['at_bat_index']))
                    
                    # Use the best match
                    best_match = potential_matches[0]
                    play_ids = best_match['play_data']
                    matched_at_bat_index = best_match['at_bat_index']
                    
                    # Reduced logging for performance (only log if mismatch or multiple matches)
                    if best_match['pitch_count_diff'] > 0 or len(potential_matches) > 1:
                        print(f"DEBUG: Matched Statcast at_bat_number={ab_num} ({statcast_pitch_count} pitches) to StatsAPI atBatIndex={matched_at_bat_index} ({best_match['pitch_count']} pitches, diff={best_match['pitch_count_diff']})")
                    # Removed detailed logging of playId keys for performance
                
                # Fallback: if no match found, try using at_bat_number directly (for backwards compatibility)
                if not play_ids and int(ab_num) in game_play_ids:
                    play_ids = game_play_ids.get(int(ab_num), {})
                    print(f"DEBUG: Warning - Using at_bat_number={ab_num} directly without verification (matchup may be incorrect)")
                    
                if not play_ids:
                    print(f"DEBUG: ERROR - No playIds found for at-bat {ab_num} in game {game_pk}")
                
                outcome = None
                if 'events' in ab_df.columns:
                    events_col = ab_df['events'].dropna()
                    if not events_col.empty:
                        outcome = str(events_col.iloc[-1])
                
                pitch_count = len(ab_df)
                strikes = 0
                balls = 0
                if 'type' in ab_df.columns:
                    strikes = ab_df['type'].eq('S').sum()
                    balls = ab_df['type'].eq('B').sum()
                
                # Use game_date from StatsAPI if available (more accurate), otherwise fallback to Statcast
                game_date = None
                if isinstance(play_ids, dict) and play_ids.get('game_date'):
                    game_date = play_ids['game_date']
                elif 'game_date' in first_pitch:
                    game_date = str(first_pitch['game_date'])
                
                def clean_dict(d):
                    if isinstance(d, dict):
                        return {k: clean_dict(v) for k, v in d.items()}
                    elif isinstance(d, list):
                        return [clean_dict(item) for item in d]
                    elif isinstance(d, (np.integer, np.floating)):
                        return int(d) if isinstance(d, np.integer) else float(d)
                    elif isinstance(d, np.ndarray):
                        return d.tolist()
                    elif pd.isna(d):
                        return None
                    elif isinstance(d, float) and (np.isnan(d) or math.isinf(d)):
                        return None
                    return d
                
                # Sort pitches by pitch number to get correct sequence
                if 'pitch_number' in ab_df.columns:
                    ab_df_sorted = ab_df.sort_values('pitch_number').copy()
                else:
                    ab_df_sorted = ab_df.copy()
                
                # Build pitches array with only the data we need
                pitches_data = []
                # play_ids is now a dict with 'by_pitch_num', 'by_sequence', 'by_pitch_sequence', and 'by_event_index'
                play_ids_by_pitch_num = {}
                play_ids_by_sequence = []
                play_ids_by_pitch_sequence = {}  # Pitch-only sequence (0,1,2...) - matches Statcast sequence
                play_ids_by_event_index = {}
                if isinstance(play_ids, dict):
                    play_ids_by_pitch_num = play_ids.get('by_pitch_num', {})
                    play_ids_by_sequence = play_ids.get('by_sequence', [])
                    play_ids_by_pitch_sequence = play_ids.get('by_pitch_sequence', {})
                    play_ids_by_event_index = play_ids.get('by_event_index', {})
                elif isinstance(play_ids, list):
                    # Legacy format - treat as sequence list
                    play_ids_by_sequence = play_ids
                
                # CRITICAL: StatsAPI may have non-pitch events mixed in (e.g., timeout at index 4)
                # Statcast's sequence (0, 1, 2, 3, 4...) is pitch-only, so we need to match to StatsAPI's pitch-only sequence
                # Use by_pitch_sequence which counts only pitch events (0, 1, 2, 3, 4...) matching Statcast
                
                # Use enumerate to track sequence position (not DataFrame index)
                # Match pitches carefully: try multiple strategies in order of reliability
                for sequence_idx, (df_idx, pitch_row) in enumerate(ab_df_sorted.iterrows()):
                    pitch_num = int(pitch_row.get('pitch_number', sequence_idx + 1)) if pd.notna(pitch_row.get('pitch_number')) else sequence_idx + 1
                    
                    # Get playId for this pitch - try multiple matching strategies
                    play_id = None
                    match_method = None
                    
                    # Strategy 1: Match by pitch_number (most reliable - pitch numbers should match between Statcast and StatsAPI)
                    if pitch_num in play_ids_by_pitch_num and play_ids_by_pitch_num[pitch_num]:
                        play_id = play_ids_by_pitch_num[pitch_num]
                        match_method = "pitch_number"
                    # Strategy 1.5: Match by pitch sequence (CRITICAL - this matches Statcast's sequence to StatsAPI's pitch-only sequence)
                    # This accounts for non-pitch events in StatsAPI by counting only pitch events
                    elif sequence_idx in play_ids_by_pitch_sequence and play_ids_by_pitch_sequence[sequence_idx]:
                        play_id = play_ids_by_pitch_sequence[sequence_idx]
                        match_method = "pitch_sequence"
                    # Strategy 2: Match by event index (fallback - event index includes non-pitch events, so may not match)
                    elif sequence_idx in play_ids_by_event_index and play_ids_by_event_index[sequence_idx]:
                        play_id = play_ids_by_event_index[sequence_idx]
                        match_method = "event_index"
                    # Strategy 3: Match by sequence position in play_ids_by_sequence (fallback)
                    elif sequence_idx < len(play_ids_by_sequence):
                        play_id = play_ids_by_sequence[sequence_idx]
                        if play_id:
                            match_method = "sequence_position"
                    # Strategy 4: Try to find closest match by pitch number
                    else:
                        # Try finding the closest available pitch number
                        available_pitch_nums = sorted(play_ids_by_pitch_num.keys())
                        if available_pitch_nums:
                            # Find closest pitch number
                            closest_pitch_num = min(available_pitch_nums, key=lambda x: abs(x - pitch_num))
                            if abs(closest_pitch_num - pitch_num) <= 1:  # Only use if within 1 pitch
                                play_id = play_ids_by_pitch_num[closest_pitch_num]
                                if play_id:  # Only use if playId exists
                                    match_method = "closest_pitch_number"
                            else:
                                # Last resort: try any available playId from pitch_sequence if we're close
                                if play_ids_by_pitch_sequence:
                                    max_seq = max(play_ids_by_pitch_sequence.keys())
                                    if sequence_idx <= max_seq + 2:  # Within 2 pitches
                                        for i in range(max(0, sequence_idx-2), min(max_seq+1, sequence_idx+3)):
                                            if i in play_ids_by_pitch_sequence and play_ids_by_pitch_sequence[i]:
                                                play_id = play_ids_by_pitch_sequence[i]
                                                match_method = "pitch_sequence_fallback"
                                                break
                    
                    # Calculate IVB (Induced Vertical Break) and HVB (Horizontal Break)
                    pfx_z = pitch_row.get('pfx_z')
                    pfx_x = pitch_row.get('pfx_x')
                    ivb = float(pfx_z * 12) if pd.notna(pfx_z) else None
                    hvb = float(pfx_x * -12) if pd.notna(pfx_x) else None  # Negative for batter perspective
                    
                    # Get spin axis
                    spin_axis = float(pitch_row.get('spin_axis')) if pd.notna(pitch_row.get('spin_axis')) else None
                    
                    # Get event to determine if ball was hit into play
                    event = str(pitch_row.get('events', '')).lower() if pd.notna(pitch_row.get('events')) else ''
                    description = str(pitch_row.get('description', '')).lower() if pd.notna(pitch_row.get('description')) else ''
                    is_hit_into_play = ('hit_into_play' in description or 
                                       event in ['single', 'double', 'triple', 'home_run', 'field_out', 'force_out',
                                                'fielders_choice', 'grounded_into_double_play', 'double_play', 'triple_play'])
                    
                    # Exit stats (only for balls hit into play)
                    exit_velocity = None
                    launch_angle = None
                    hit_distance = None
                    exit_spin = None
                    
                    if is_hit_into_play:
                        exit_velocity = float(pitch_row.get('launch_speed')) if pd.notna(pitch_row.get('launch_speed')) else None
                        launch_angle = float(pitch_row.get('launch_angle')) if pd.notna(pitch_row.get('launch_angle')) else None
                        # Try hit_distance_sc first, then hit_distance
                        distance_col = 'hit_distance_sc' if 'hit_distance_sc' in pitch_row.index else 'hit_distance'
                        hit_distance = float(pitch_row.get(distance_col)) if pd.notna(pitch_row.get(distance_col)) else None
                        # Exit spin rate might be in launch_spin_rate column
                        exit_spin = float(pitch_row.get('launch_spin_rate')) if pd.notna(pitch_row.get('launch_spin_rate')) else None
                    
                    pitch_data = {
                        "pitch_number": pitch_num,
                        "balls": int(pitch_row.get('balls', 0)) if pd.notna(pitch_row.get('balls')) else 0,
                        "strikes": int(pitch_row.get('strikes', 0)) if pd.notna(pitch_row.get('strikes')) else 0,
                        "pitch_type": str(pitch_row.get('pitch_type', '')) if pd.notna(pitch_row.get('pitch_type')) else None,
                        "description": str(pitch_row.get('description', '')) if pd.notna(pitch_row.get('description')) else None,
                        "plate_x": float(pitch_row.get('plate_x')) if pd.notna(pitch_row.get('plate_x')) else None,
                        "plate_z": float(pitch_row.get('plate_z')) if pd.notna(pitch_row.get('plate_z')) else None,
                        "velocity": float(pitch_row.get('release_speed')) if pd.notna(pitch_row.get('release_speed')) else None,
                        "ivb": ivb,
                        "hvb": hvb,
                        "spin": float(pitch_row.get('release_spin_rate')) if pd.notna(pitch_row.get('release_spin_rate')) else None,
                        "axis": spin_axis,
                        "is_hit": is_hit_into_play,
                        "exit_velocity": exit_velocity,
                        "launch_angle": launch_angle,
                        "hit_distance": hit_distance,
                        "exit_spin": exit_spin,
                        "play_id": play_id  # UUID for video URL
                    }
                    pitches_data.append(clean_dict(pitch_data))
                
                # Get player-relative at-bat number (defaults to original if not found)
                player_ab_num = player_at_bat_numbers.get((int(game_pk), int(ab_num)), int(ab_num))
                
                at_bats.append({
                    "game_pk": int(game_pk),
                    "at_bat_number": int(ab_num),  # Keep original for reference
                    "player_at_bat_number": player_ab_num,  # Player-relative number (1st, 2nd, 3rd...)
                    "game_date": game_date,
                    "pitch_count": pitch_count,
                    "balls": int(balls),
                    "strikes": int(strikes),
                    "outcome": outcome,
                    "pitches": pitches_data
                })
        
        summary = {
            "total_at_bats": total_ab,
            "hits": total_h,
            "home_runs": total_hr,
            "strikeouts": total_so,
            "walks": total_bb,
            "average": avg,
            "slugging_percentage": slg,
            "on_base_percentage": obp,
            "ops": ops,
            "data_source": "Statcast (Filtered to matchup)",
            "verification": {
                "total_pa": total_pa,
                "ab_plus_walks_plus_sf": total_ab + total_bb + total_sf,
                "should_equal_pa": total_ab + total_bb + total_sf == total_pa
            }
        }
        
        # Clean up DataFrames before returning
        if df_with_events is not None:
            del df_with_events
        if pa_ending is not None:
            del pa_ending
        if df is not None:
            del df
        gc.collect()
        
        return jsonify({
            "player": player_name,
            "opponent": opponent_name,
            "player_role": player_role,
            "matchups": at_bats,
            "summary": summary
        })
        
    except Exception as e:
        # Cleanup on error
        if df_raw is not None:
            del df_raw
        if df is not None:
            del df
        if df_with_events is not None:
            del df_with_events
        if pa_ending is not None:
            del pa_ending
        gc.collect()
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Error fetching matchup data: {str(e)}"}), 500
