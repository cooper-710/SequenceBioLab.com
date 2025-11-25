"""
Visuals API routes
"""
from flask import Blueprint, request, jsonify
import sys
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np

bp = Blueprint('visuals', __name__)

# Import CSV data loader if available
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
    from csv_data_loader import CSVDataLoader
    from app.config import Config
    csv_loader = CSVDataLoader(str(Config.ROOT_DIR))
except (ImportError, Exception):
    csv_loader = None


@bp.route('/visuals/heatmap', methods=['GET'])
def api_visuals_heatmap():
    """Get heatmap data for visualization - returns location-based heatmap data"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        player_name = request.args.get('player', '').strip()
        if not player_name:
            return jsonify({"error": "Player name is required"}), 400
        
        metric = request.args.get('metric', '').strip()
        if not metric:
            return jsonify({"error": "Metric is required"}), 400
        
        season = request.args.get('season', '').strip() or None
        if season:
            try:
                season = int(season)
            except ValueError:
                season = None
        
        team = request.args.get('team', '').strip() or None
        position = request.args.get('position', '').strip() or None
        count = request.args.get('count', '').strip() or None
        pitcher_hand = request.args.get('pitcher_hand', '').strip() or None
        pitch_type = request.args.get('pitch_type', '').strip() or None
        
        # Import statcast functions
        sys.path.insert(0, str(Config.ROOT_DIR / "src"))
        from scrape_savant import fetch_batter_statcast, fetch_pitcher_statcast, lookup_batter_id
        from datetime import datetime, timedelta
        import pandas as pd
        import numpy as np
        
        # Get player data filtered by criteria
        try:
            players = csv_loader.get_all_players_summary()
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Error loading player data: {str(e)}"}), 500
        
        if not players:
            return jsonify({"error": "No players found in database"}), 404
        
        # Find the selected player (case-insensitive match with whitespace handling)
        selected_player_data = None
        player_name_normalized = player_name.strip().lower()
        for player in players:
            player_name_from_data = player.get('name', '').strip().lower()
            if player_name_from_data == player_name_normalized:
                selected_player_data = player
                break
        
        # If exact match not found, try partial match
        if not selected_player_data:
            for player in players:
                player_name_from_data = player.get('name', '').strip().lower()
                if player_name_normalized in player_name_from_data or player_name_from_data in player_name_normalized:
                    selected_player_data = player
                    break
        
        if not selected_player_data:
            # Return more helpful error with available players for debugging
            similar_names = [p['name'] for p in players if player_name_normalized[:3] in p['name'].lower()][:5]
            error_msg = f"Player '{player_name}' not found"
            if similar_names:
                error_msg += f". Similar names: {', '.join(similar_names)}"
            return jsonify({"error": error_msg}), 404
        
        # Use the actual player name from the database (to handle case differences)
        actual_player_name = selected_player_data.get('name')
        
        # Determine if player is a pitcher or hitter
        player_position = selected_player_data.get('position', '').upper()
        is_pitcher = 'P' in player_position or 'PITCHER' in player_position
        
        # Additional filters (if they match player's data)
        # Note: Team and position filters apply to the player's overall data
        if team and selected_player_data.get('team') != team:
            return jsonify({
                "error": f"Player '{actual_player_name}' does not match team filter '{team}'",
                "metric": metric,
                "data": [],
                "summary": {}
            }), 200
        
        if position and selected_player_data.get('position') != position:
            return jsonify({
                "error": f"Player '{actual_player_name}' does not match position filter '{position}'",
                "metric": metric,
                "data": [],
                "summary": {}
            }), 200
        
        # Get player ID (works for both batters and pitchers)
        try:
            player_id = lookup_batter_id(actual_player_name)
        except Exception as e:
            return jsonify({"error": f"Could not find player ID for '{actual_player_name}': {str(e)}"}), 404
        
        # Calculate date range for the season
        # If season is specified, use it; otherwise fetch all available data
        if season:
            start_date = f"{season}-03-01"  # Start of season
            end_date = f"{season}-11-30"    # End of season
            filter_by_season = True
        else:
            # Fetch data from a wide range to get all available seasons
            # Statcast data goes back to 2008, but we'll use a reasonable range
            current_year = datetime.now().year
            start_date = "2008-03-01"  # Statcast started in 2008
            end_date = f"{current_year}-11-30"
            filter_by_season = False
        
        # Fetch statcast data based on player type
        # Try to determine player type by attempting to fetch both types of data
        statcast_df = None
        is_pitcher_confirmed = False
        
        if is_pitcher:
            # Try pitcher data first
            try:
                statcast_df = fetch_pitcher_statcast(player_id, start_date, end_date)
                if statcast_df is not None and not statcast_df.empty:
                    is_pitcher_confirmed = True
            except Exception:
                pass
        
        # If not confirmed as pitcher or no pitcher data, try batter data
        if statcast_df is None or statcast_df.empty:
            try:
                statcast_df = fetch_batter_statcast(player_id, start_date, end_date)
                if statcast_df is not None and not statcast_df.empty:
                    is_pitcher_confirmed = False
            except Exception:
                pass
        
        # If still no data, try the other type
        if (statcast_df is None or statcast_df.empty) and not is_pitcher:
            try:
                statcast_df = fetch_pitcher_statcast(player_id, start_date, end_date)
                if statcast_df is not None and not statcast_df.empty:
                    is_pitcher_confirmed = True
            except Exception:
                pass
        
        if statcast_df is None or statcast_df.empty:
            return jsonify({
                "error": f"No statcast data found for {actual_player_name}",
                "metric": metric,
                "data": [],
                "grid": []
            }), 200
        
        # Filter by season if specified
        if filter_by_season:
            # First, try to filter by year column if it exists (most reliable)
            year_column = None
            for col_name in ['game_year', 'year', 'Year', 'season']:
                if col_name in statcast_df.columns:
                    year_column = col_name
                    break
            
            if year_column:
                # Filter by year (this is the most reliable method)
                # Convert to int if needed for comparison
                if not pd.api.types.is_integer_dtype(statcast_df[year_column]):
                    statcast_df[year_column] = pd.to_numeric(statcast_df[year_column], errors='coerce')
                statcast_df = statcast_df[
                    (statcast_df[year_column].notna()) & 
                    (statcast_df[year_column] == int(season))
                ]
            else:
                # Fallback: try filtering by date column
                date_column = None
                for col_name in ['game_date', 'gameDate', 'date', 'Date', 'game_day']:
                    if col_name in statcast_df.columns:
                        date_column = col_name
                        break
                
                if date_column:
                    # Convert date column to datetime if it's not already
                    if not pd.api.types.is_datetime64_any_dtype(statcast_df[date_column]):
                        statcast_df[date_column] = pd.to_datetime(statcast_df[date_column], errors='coerce')
                    
                    # Filter to the specific season
                    season_start = pd.to_datetime(f"{season}-03-01")
                    season_end = pd.to_datetime(f"{season}-11-30")
                    
                    # Drop rows where date conversion failed
                    statcast_df = statcast_df[statcast_df[date_column].notna()]
                    
                    # Filter by date range
                    statcast_df = statcast_df[
                        (statcast_df[date_column] >= season_start) & 
                        (statcast_df[date_column] <= season_end)
                    ]
            
            # Check if we have data after season filtering
            if statcast_df.empty:
                return jsonify({
                    "error": f"No statcast data found for {actual_player_name} for season {season}",
                    "metric": metric,
                    "data": [],
                    "grid": []
                }), 200
        
        # Filter by count if specified
        if count:
            count_parts = count.split('-')
            if len(count_parts) == 2:
                try:
                    balls_filter = int(count_parts[0])
                    strikes_filter = int(count_parts[1])
                    if 'balls' in statcast_df.columns and 'strikes' in statcast_df.columns:
                        statcast_df = statcast_df[
                            (statcast_df['balls'] == balls_filter) & 
                            (statcast_df['strikes'] == strikes_filter)
                        ]
                except ValueError:
                    pass
        
        # Filter by pitcher/batter handedness if specified
        if is_pitcher_confirmed:
            # For pitchers, filter by batter handedness (stand column)
            if pitcher_hand and 'stand' in statcast_df.columns:
                statcast_df = statcast_df[statcast_df['stand'] == pitcher_hand]
        else:
            # For hitters, filter by pitcher handedness (p_throws column)
            if pitcher_hand and 'p_throws' in statcast_df.columns:
                statcast_df = statcast_df[statcast_df['p_throws'] == pitcher_hand]
        
        # Filter by pitch type if specified
        if pitch_type and 'pitch_type' in statcast_df.columns:
            statcast_df = statcast_df[statcast_df['pitch_type'] == pitch_type]
        
        # Filter out rows without location data
        if 'plate_x' not in statcast_df.columns or 'plate_z' not in statcast_df.columns:
            return jsonify({
                "error": "Location data (plate_x, plate_z) not available in statcast data",
                "metric": metric,
                "data": [],
                "grid": []
            }), 200
        
        statcast_df = statcast_df[
            statcast_df['plate_x'].notna() & 
            statcast_df['plate_z'].notna()
        ]
        
        if statcast_df.empty:
            return jsonify({
                "error": "No valid location data found",
                "metric": metric,
                "data": [],
                "grid": []
            }), 200
        
        # Helper function to calculate SLG from events
        def calculate_slg(cell_data):
            """Calculate slugging percentage from events column"""
            if 'events' not in cell_data.columns:
                return None
            
            # Filter to only at-bats - need events that are not NaN
            # At-bats exclude walks, hit-by-pitch, etc.
            ab_data = cell_data[
                cell_data['events'].notna() & 
                cell_data['events'].isin([
                    'single', 'double', 'triple', 'home_run', 'field_out', 
                    'strikeout', 'force_out', 'grounded_into_double_play',
                    'fielders_choice', 'field_error', 'double_play', 'triple_play',
                    'sac_fly', 'sac_bunt', 'sac_fly_double_play', 'catcher_interf'
                ])
            ]
            
            if len(ab_data) == 0:
                return None
            
            # Calculate total bases
            bases_map = {
                'single': 1,
                'double': 2,
                'triple': 3,
                'home_run': 4
            }
            
            total_bases = 0
            for event in ab_data['events']:
                total_bases += bases_map.get(event, 0)
            
            return total_bases / len(ab_data)
        
        # Helper function to calculate OBP from events
        def calculate_obp(cell_data):
            """Calculate on-base percentage from events column"""
            if 'events' not in cell_data.columns:
                return None
            
            # Plate appearances = all events that are not NaN (actual outcomes)
            # Exclude stolen bases and caught stealing
            pa_data = cell_data[
                cell_data['events'].notna() & 
                ~cell_data['events'].isin([
                    'stolen_base_2b', 'stolen_base_3b', 'stolen_base_home',
                    'caught_stealing_2b', 'caught_stealing_3b', 'caught_stealing_home'
                ])
            ]
            
            if len(pa_data) == 0:
                return None
            
            # On-base events: hits, walks, hit-by-pitch
            on_base_events = ['single', 'double', 'triple', 'home_run', 'walk', 'hit_by_pitch']
            on_base_count = pa_data['events'].isin(on_base_events).sum()
            
            return on_base_count / len(pa_data)
        
        # Helper function to calculate HR rate from events
        def calculate_hr_rate(cell_data):
            """Calculate home run rate (HR per plate appearance)"""
            if 'events' not in cell_data.columns:
                return None
            
            # Count plate appearances (events that are not NaN)
            pa_data = cell_data[
                cell_data['events'].notna() & 
                ~cell_data['events'].isin([
                    'stolen_base_2b', 'stolen_base_3b', 'stolen_base_home',
                    'caught_stealing_2b', 'caught_stealing_3b', 'caught_stealing_home'
                ])
            ]
            
            if len(pa_data) == 0:
                return None
            
            hr_count = (pa_data['events'] == 'home_run').sum()
            return hr_count / len(pa_data)
        
        # Helper function to calculate RBI rate from events (approximate)
        def calculate_rbi_rate(cell_data):
            """Calculate approximate RBI rate - home runs always have RBI, others may vary"""
            if 'events' not in cell_data.columns:
                return None
            
            # Count plate appearances (events that are not NaN)
            pa_data = cell_data[
                cell_data['events'].notna() & 
                ~cell_data['events'].isin([
                    'stolen_base_2b', 'stolen_base_3b', 'stolen_base_home',
                    'caught_stealing_2b', 'caught_stealing_3b', 'caught_stealing_home'
                ])
            ]
            
            if len(pa_data) == 0:
                return None
            
            # Home runs always have at least 1 RBI (often more)
            # For other hits, we'll estimate based on hit type
            rbi_estimate = 0
            for event in pa_data['events']:
                if event == 'home_run':
                    rbi_estimate += 1.5  # Average ~1.5 RBI per HR
                elif event == 'triple':
                    rbi_estimate += 0.8  # High probability of scoring runner
                elif event == 'double':
                    rbi_estimate += 0.6
                elif event == 'single':
                    rbi_estimate += 0.4
            
            return rbi_estimate / len(pa_data)
        
        # Map metric to calculation method
        metric_upper = metric.upper()
        calculate_metric = None
        metric_column = None
        
        # Pitcher-specific metrics
        if is_pitcher_confirmed:
            if metric_upper in ['WHIFF_RATE', 'WHIFF RATE', 'WHIFF', 'WHIFF%']:
                def calculate_whiff_rate(cell_data):
                    """Calculate whiff rate (swinging strikes / swings)"""
                    if 'description' not in cell_data.columns:
                        return None
                    desc = cell_data['description'].astype(str).str.lower()
                    swings = desc.isin(['swinging_strike', 'swinging_strike_blocked', 'foul', 'foul_tip', 'hit_into_play']).sum()
                    whiffs = desc.isin(['swinging_strike', 'swinging_strike_blocked']).sum()
                    return (whiffs / swings) if swings > 0 else None
                calculate_metric = calculate_whiff_rate
            elif metric_upper in ['STRIKE_RATE', 'STRIKE RATE', 'STRIKE', 'STRIKE%']:
                def calculate_strike_rate(cell_data):
                    """Calculate strike rate (strikes / total pitches)"""
                    total = len(cell_data)
                    if total == 0:
                        return None
                    # Check for type column (S = strike, X = in play, B = ball)
                    if 'type' in cell_data.columns:
                        strikes = cell_data['type'].isin(['S', 'X']).sum()
                    elif 'description' in cell_data.columns:
                        # Fallback: count non-ball descriptions as strikes
                        desc = cell_data['description'].astype(str).str.lower()
                        strikes = (~desc.isin(['ball', 'blocked_ball', 'intent_ball'])).sum()
                    else:
                        return None
                    return strikes / total
                calculate_metric = calculate_strike_rate
            elif metric_upper in ['XWOBA', 'XWOBA_ALLOWED']:
                metric_column = 'estimated_woba_using_speedangle'
            elif metric_upper in ['XBA', 'XBA_ALLOWED']:
                metric_column = 'estimated_ba_using_speedangle'
            elif metric_upper in ['XSLG', 'XSLG_ALLOWED']:
                metric_column = 'estimated_slg_using_speedangle'
            else:
                # Default to xwOBA for pitchers
                metric_column = 'estimated_woba_using_speedangle'
        else:
            # Hitter-specific metrics
            if metric_upper in ['SLG', 'SLUGGING']:
                calculate_metric = calculate_slg
            elif metric_upper in ['OBP', 'ON_BASE_PERCENTAGE']:
                calculate_metric = calculate_obp
            elif metric_upper in ['OPS', 'ON_BASE_PLUS_SLUGGING']:
                # OPS = OBP + SLG
                def calculate_ops(cell_data):
                    obp = calculate_obp(cell_data)
                    slg = calculate_slg(cell_data)
                    if obp is None or slg is None:
                        return None
                    return obp + slg
                calculate_metric = calculate_ops
            elif metric_upper in ['HR', 'HOME_RUNS', 'HOME_RUN']:
                calculate_metric = calculate_hr_rate
            elif metric_upper in ['RBI', 'RUNS_BATTED_IN']:
                calculate_metric = calculate_rbi_rate
            elif metric_upper in ['WRC+', 'WRC', 'WRC_PLUS']:
                # wRC+ is complex, but we can use wOBA as a proxy since it's closely related
                # For a proper wRC+ calculation, we'd need league averages, park factors, etc.
                # We'll use woba_value if available, otherwise estimated_woba
                if 'woba_value' in statcast_df.columns:
                    metric_column = 'woba_value'
                else:
                    metric_column = 'estimated_woba_using_speedangle'
            elif metric_upper in ['WAR']:
                # WAR cannot be calculated at the pitch level - it's a cumulative stat
                return jsonify({
                    "error": "WAR is a cumulative statistic and cannot be visualized as a location-based heatmap. Please select a different metric.",
                    "metric": metric,
                    "data": [],
                    "grid": []
                }), 200
            else:
                # Direct column mappings for hitters
                metric_map = {
                    'XWOBA': 'estimated_woba_using_speedangle',
                    'XBA': 'estimated_ba_using_speedangle',
                    'XSLG': 'estimated_slg_using_speedangle',
                    'WOBA': 'woba_value',
                    'BA': 'hit',
                    'AVG': 'hit',
                    'AVERAGE': 'hit',
                }
                
                metric_column = metric_map.get(metric_upper, 'estimated_woba_using_speedangle')
        
        # If using direct column, verify it exists
        if calculate_metric is None:
            if metric_column not in statcast_df.columns:
                # Try alternative columns
                for alt_col in ['estimated_woba_using_speedangle', 'woba_value', 'launch_speed', 'launch_angle']:
                    if alt_col in statcast_df.columns:
                        metric_column = alt_col
                        break
                else:
                    return jsonify({
                        "error": f"Metric '{metric}' cannot be calculated from available statcast data",
                        "metric": metric,
                        "data": [],
                        "grid": []
                    }), 200
        
        # Create grid for strike zone (10x10 grid)
        # Strike zone: x from -1.5 to 1.5 feet, z from 1.5 to 3.5 feet
        grid_size = 12
        x_min, x_max = -2.0, 2.0
        z_min, z_max = 0.5, 4.5
        
        x_bins = np.linspace(x_min, x_max, grid_size + 1)
        z_bins = np.linspace(z_min, z_max, grid_size + 1)
        
        # Bin the data
        statcast_df['x_bin'] = pd.cut(statcast_df['plate_x'], bins=x_bins, labels=False)
        statcast_df['z_bin'] = pd.cut(statcast_df['plate_z'], bins=z_bins, labels=False)
        
        # Calculate average metric for each grid cell
        grid_data = []
        for x_idx in range(grid_size):
            for z_idx in range(grid_size):
                cell_data = statcast_df[
                    (statcast_df['x_bin'] == x_idx) & 
                    (statcast_df['z_bin'] == z_idx)
                ]
                
                pitch_count = len(cell_data)
                
                if not cell_data.empty:
                    # Use calculation function if available, otherwise use direct column
                    if calculate_metric is not None:
                        # Calculate metric from events/outcomes
                        avg_value = calculate_metric(cell_data)
                        if avg_value is not None:
                            avg_value = float(avg_value)
                        else:
                            avg_value = None
                    elif metric_column in cell_data.columns:
                        # Calculate average from direct column
                        values = cell_data[metric_column].dropna()
                        if len(values) > 0:
                            avg_value = float(values.mean())
                        else:
                            avg_value = None
                    else:
                        avg_value = None
                else:
                    avg_value = None
                
                # Calculate center coordinates of the cell
                x_center = (x_bins[x_idx] + x_bins[x_idx + 1]) / 2
                z_center = (z_bins[z_idx] + z_bins[z_idx + 1]) / 2
                
                grid_data.append({
                    'x': x_idx,
                    'y': grid_size - 1 - z_idx,  # Flip y-axis for display
                    'x_center': float(x_center),
                    'z_center': float(z_center),
                    'value': avg_value,
                    'count': pitch_count
                })
        
        # Filter out cells with no data
        grid_data = [cell for cell in grid_data if cell['value'] is not None and cell['count'] > 0]
        
        if not grid_data:
            return jsonify({
                "error": f"No {metric} data available for the selected filters",
                "metric": metric,
                "data": [],
                "grid": []
            }), 200
        
        # Calculate summary statistics
        values = [cell['value'] for cell in grid_data if cell['value'] is not None]
        
        # Determine batter handedness from statcast data
        batter_hand = 'R'  # Default to right-handed
        if 'stand' in statcast_df.columns:
            stand_values = statcast_df['stand'].dropna()
            if len(stand_values) > 0:
                # Use the most common value
                batter_hand = str(stand_values.mode().iloc[0]) if len(stand_values.mode()) > 0 else 'R'
        
        heatmap_data = {
            'player': actual_player_name,
            'metric': metric,
            'batter_hand': batter_hand,  # 'R' or 'L'
            'filters': {
                'season': season,
                'team': team,
                'position': position,
                'count': count,
                'pitcher_hand': pitcher_hand,
                'pitch_type': pitch_type
            },
            'grid': grid_data,
            'grid_size': grid_size,
            'x_range': [float(x_min), float(x_max)],
            'z_range': [float(z_min), float(z_max)],
            'summary': {
                'total_cells': len(grid_data),
                'min_value': float(min(values)) if values else 0,
                'max_value': float(max(values)) if values else 0,
                'avg_value': float(np.mean(values)) if values else 0,
                'total_pitches': sum(cell['count'] for cell in grid_data)
            }
        }
        
        return jsonify(heatmap_data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@bp.route('/visuals/heatmap/player-info', methods=['GET'])
def api_visuals_heatmap_player_info():
    """Get player type and available metrics"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        player_name = request.args.get('player', '').strip()
        if not player_name:
            return jsonify({"error": "Player name is required"}), 400
        
        players = csv_loader.get_all_players_summary()
        player_name_normalized = player_name.strip().lower()
        
        selected_player_data = None
        for player in players:
            if player.get('name', '').strip().lower() == player_name_normalized:
                selected_player_data = player
                break
        
        if not selected_player_data:
            return jsonify({"error": "Player not found"}), 404
        
        player_position = selected_player_data.get('position', '').upper()
        is_pitcher = 'P' in player_position or 'PITCHER' in player_position
        
        # Define sorted metrics
        hitter_metrics = [
            {'value': 'xwOBA', 'label': 'xwOBA'},
            {'value': 'xSLG', 'label': 'xSLG'},
            {'value': 'xBA', 'label': 'xBA'},
            {'value': 'wRC+', 'label': 'wRC+'},
            {'value': 'OPS', 'label': 'OPS'},
            {'value': 'SLG', 'label': 'SLG'},
            {'value': 'OBP', 'label': 'OBP'},
            {'value': 'AVG', 'label': 'Batting Average'},
            {'value': 'HR', 'label': 'Home Runs'},
            {'value': 'RBI', 'label': 'RBI'},
        ]
        
        pitcher_metrics = [
            {'value': 'xwOBA', 'label': 'xwOBA Allowed'},
            {'value': 'xBA', 'label': 'xBA Allowed'},
            {'value': 'xSLG', 'label': 'xSLG Allowed'},
            {'value': 'Whiff Rate', 'label': 'Whiff Rate'},
            {'value': 'Strike Rate', 'label': 'Strike Rate'},
        ]
        
        return jsonify({
            'is_pitcher': is_pitcher,
            'metrics': pitcher_metrics if is_pitcher else hitter_metrics
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route('/visuals/spraychart', methods=['GET'])
def api_visuals_spraychart():
    """Get spray chart data for visualization - returns batted ball locations"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        player_name = request.args.get('player', '').strip()
        if not player_name:
            return jsonify({"error": "Player name is required"}), 400
        
        season = request.args.get('season', '').strip() or None
        if season:
            try:
                season = int(season)
            except ValueError:
                season = None
        
        # Filter options
        event_type = request.args.get('event_type', '').strip() or None  # e.g., 'single', 'double', 'home_run'
        min_launch_speed = request.args.get('min_launch_speed', type=float)
        max_launch_speed = request.args.get('max_launch_speed', type=float)
        min_launch_angle = request.args.get('min_launch_angle', type=float)
        max_launch_angle = request.args.get('max_launch_angle', type=float)
        
        # Import statcast functions
        sys.path.insert(0, str(Config.ROOT_DIR / "src"))
        from scrape_savant import fetch_batter_statcast, fetch_pitcher_statcast, lookup_batter_id
        from datetime import datetime
        import pandas as pd
        import numpy as np
        
        # Get player data
        try:
            players = csv_loader.get_all_players_summary()
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Error loading player data: {str(e)}"}), 500
        
        if not players:
            return jsonify({"error": "No players found in database"}), 404
        
        # Find the selected player
        selected_player_data = None
        player_name_normalized = player_name.strip().lower()
        for player in players:
            player_name_from_data = player.get('name', '').strip().lower()
            if player_name_from_data == player_name_normalized:
                selected_player_data = player
                break
        
        if not selected_player_data:
            for player in players:
                player_name_from_data = player.get('name', '').strip().lower()
                if player_name_normalized in player_name_from_data or player_name_from_data in player_name_normalized:
                    selected_player_data = player
                    break
        
        if not selected_player_data:
            similar_names = [p['name'] for p in players if player_name_normalized[:3] in p['name'].lower()][:5]
            error_msg = f"Player '{player_name}' not found"
            if similar_names:
                error_msg += f". Similar names: {', '.join(similar_names)}"
            return jsonify({"error": error_msg}), 404
        
        actual_player_name = selected_player_data.get('name')
        
        # Get player ID (works for both batters and pitchers)
        try:
            player_id = lookup_batter_id(actual_player_name)
        except Exception as e:
            return jsonify({"error": f"Could not find player ID for '{actual_player_name}': {str(e)}"}), 404
        
        # Calculate date range
        if season:
            start_date = f"{season}-03-01"
            end_date = f"{season}-11-30"
            filter_by_season = True
        else:
            current_year = datetime.now().year
            start_date = "2008-03-01"
            end_date = f"{current_year}-11-30"
            filter_by_season = False
        
        # Try to fetch statcast data - try pitcher first (for spray chart, we want batted balls hit OFF of pitchers)
        # Then try batter if pitcher fails (for batters, we want batted balls they hit)
        statcast_df = None
        player_type = None
        
        # First, try as pitcher (batted balls hit off of them)
        try:
            pitcher_df = fetch_pitcher_statcast(player_id, start_date, end_date)
            if pitcher_df is not None and not pitcher_df.empty:
                # Check if there are any batted balls in the pitcher data
                if 'events' in pitcher_df.columns:
                    batted_balls = pitcher_df[pitcher_df['events'].notna()]
                    if not batted_balls.empty:
                        statcast_df = pitcher_df
                        player_type = 'pitcher'
        except Exception as e:
            pass  # Try batter below
        
        # If pitcher lookup failed or returned no batted ball data, try as batter
        if statcast_df is None or (statcast_df is not None and statcast_df.empty):
            try:
                batter_df = fetch_batter_statcast(player_id, start_date, end_date)
                if batter_df is not None and not batter_df.empty:
                    # Check if there are any batted balls in the batter data
                    if 'events' in batter_df.columns:
                        batted_balls = batter_df[batter_df['events'].notna()]
                        if not batted_balls.empty:
                            statcast_df = batter_df
                            player_type = 'batter'
            except Exception as e:
                pass  # Will return error below
        
        if statcast_df is None or (statcast_df is not None and statcast_df.empty):
            return jsonify({
                "error": f"No statcast data found for {actual_player_name}",
                "data": [],
                "summary": {}
            }), 200
        
        # Filter by season if specified
        if filter_by_season:
            year_column = None
            for col_name in ['game_year', 'year', 'Year', 'season']:
                if col_name in statcast_df.columns:
                    year_column = col_name
                    break
            
            if year_column:
                if not pd.api.types.is_integer_dtype(statcast_df[year_column]):
                    statcast_df[year_column] = pd.to_numeric(statcast_df[year_column], errors='coerce')
                statcast_df = statcast_df[
                    (statcast_df[year_column].notna()) & 
                    (statcast_df[year_column] == int(season))
                ]
            else:
                date_column = None
                for col_name in ['game_date', 'gameDate', 'date', 'Date', 'game_day']:
                    if col_name in statcast_df.columns:
                        date_column = col_name
                        break
                
                if date_column:
                    if not pd.api.types.is_datetime64_any_dtype(statcast_df[date_column]):
                        statcast_df[date_column] = pd.to_datetime(statcast_df[date_column], errors='coerce')
                    
                    season_start = pd.to_datetime(f"{season}-03-01")
                    season_end = pd.to_datetime(f"{season}-11-30")
                    
                    statcast_df = statcast_df[statcast_df[date_column].notna()]
                    statcast_df = statcast_df[
                        (statcast_df[date_column] >= season_start) & 
                        (statcast_df[date_column] <= season_end)
                    ]
            
            if statcast_df.empty:
                return jsonify({
                    "error": f"No statcast data found for {actual_player_name} for season {season}",
                    "data": [],
                    "summary": {}
                }), 200
        
        # Filter to only regular season games (exclude postseason, spring training, etc.)
        if 'game_type' in statcast_df.columns:
            statcast_df = statcast_df[statcast_df['game_type'] == 'R']
        
        # Filter to only events that are batted balls (have events)
        statcast_df = statcast_df[statcast_df['events'].notna()]
        
        # Filter by event type if specified (normalize to lowercase for matching)
        if event_type:
            statcast_df = statcast_df[statcast_df['events'].str.lower() == event_type.lower()]
        
        # Filter by launch speed if specified
        if min_launch_speed is not None and 'launch_speed' in statcast_df.columns:
            statcast_df = statcast_df[
                (statcast_df['launch_speed'].notna()) & 
                (statcast_df['launch_speed'] >= min_launch_speed)
            ]
        
        if max_launch_speed is not None and 'launch_speed' in statcast_df.columns:
            statcast_df = statcast_df[
                (statcast_df['launch_speed'].notna()) & 
                (statcast_df['launch_speed'] <= max_launch_speed)
            ]
        
        # Filter by launch angle if specified
        if min_launch_angle is not None and 'launch_angle' in statcast_df.columns:
            statcast_df = statcast_df[
                (statcast_df['launch_angle'].notna()) & 
                (statcast_df['launch_angle'] >= min_launch_angle)
            ]
        
        if max_launch_angle is not None and 'launch_angle' in statcast_df.columns:
            statcast_df = statcast_df[
                (statcast_df['launch_angle'].notna()) & 
                (statcast_df['launch_angle'] <= max_launch_angle)
            ]
        
        if statcast_df.empty:
            return jsonify({
                "error": "No batted ball data available for the selected filters",
                "data": [],
                "summary": {}
            }), 200
        
        # Count all events (including those without coordinates) for accurate statistics
        event_counts_all = {}
        for _, row in statcast_df.iterrows():
            event_name = str(row['events']).lower() if pd.notna(row['events']) else 'unknown'
            event_counts_all[event_name] = event_counts_all.get(event_name, 0) + 1
        
        # Now filter to only batted balls with hit coordinates for visualization
        statcast_df_with_coords = statcast_df[
            statcast_df['hc_x'].notna() & 
            statcast_df['hc_y'].notna()
        ]
        
        # Prepare spray chart data (only for entries with coordinates)
        spray_data = []
        for _, row in statcast_df_with_coords.iterrows():
            # Normalize event name to lowercase for consistent counting
            event_name = str(row['events']).lower() if pd.notna(row['events']) else 'unknown'
            
            spray_data.append({
                'x': float(row['hc_x']) if pd.notna(row['hc_x']) else None,
                'y': float(row['hc_y']) if pd.notna(row['hc_y']) else None,
                'event': event_name,
                'launch_speed': float(row['launch_speed']) if 'launch_speed' in row and pd.notna(row['launch_speed']) else None,
                'launch_angle': float(row['launch_angle']) if 'launch_angle' in row and pd.notna(row['launch_angle']) else None,
                'hit_distance': float(row['hit_distance_sc']) if 'hit_distance_sc' in row and pd.notna(row['hit_distance_sc']) else None,
                'is_barrel': bool(row['barrel']) if 'barrel' in row and pd.notna(row['barrel']) else None,
            })
        
        # Filter out entries without valid coordinates (shouldn't happen, but just in case)
        spray_data = [d for d in spray_data if d['x'] is not None and d['y'] is not None]
        
        # Calculate summary statistics from all data (not just those with coordinates)
        launch_speeds_all = statcast_df['launch_speed'].dropna().tolist() if 'launch_speed' in statcast_df.columns else []
        launch_angles_all = statcast_df['launch_angle'].dropna().tolist() if 'launch_angle' in statcast_df.columns else []
        
        # Use event counts from all data (accurate counts)
        event_counts = event_counts_all
        
        summary = {
            'total_batted_balls': len(statcast_df),  # Count all batted balls, not just those with coordinates
            'total_visualized': len(spray_data),  # Count of those with coordinates for visualization
            'avg_launch_speed': float(np.mean(launch_speeds_all)) if launch_speeds_all else None,
            'avg_launch_angle': float(np.mean(launch_angles_all)) if launch_angles_all else None,
            'min_launch_speed': float(min(launch_speeds_all)) if launch_speeds_all else None,
            'max_launch_speed': float(max(launch_speeds_all)) if launch_speeds_all else None,
            'min_launch_angle': float(min(launch_angles_all)) if launch_angles_all else None,
            'max_launch_angle': float(max(launch_angles_all)) if launch_angles_all else None,
            'event_counts': event_counts
        }
        
        return jsonify({
            'player': actual_player_name,
            'filters': {
                'season': season,
                'event_type': event_type,
                'min_launch_speed': min_launch_speed,
                'max_launch_speed': max_launch_speed,
                'min_launch_angle': min_launch_angle,
                'max_launch_angle': max_launch_angle
            },
            'data': spray_data,
            'summary': summary
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@bp.route('/visuals/barrel-quality-contact', methods=['GET'])
def api_visuals_barrel_quality_contact():
    """Get barrel rate and quality of contact data for visualization"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        player_name = request.args.get('player', '').strip()
        if not player_name:
            return jsonify({"error": "Player name is required"}), 400
        
        season = request.args.get('season', '').strip() or None
        if season:
            try:
                season = int(season)
            except ValueError:
                season = None
        
        # Import statcast functions
        sys.path.insert(0, str(Config.ROOT_DIR / "src"))
        from scrape_savant import fetch_batter_statcast, lookup_batter_id
        
        # Get player data
        try:
            players = csv_loader.get_all_players_summary()
        except Exception as e:
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Error loading player data: {str(e)}"}), 500
        
        if not players:
            return jsonify({"error": "No players found in database"}), 404
        
        # Find the selected player
        selected_player_data = None
        player_name_normalized = player_name.strip().lower()
        for player in players:
            player_name_from_data = player.get('name', '').strip().lower()
            if player_name_from_data == player_name_normalized:
                selected_player_data = player
                break
        
        if not selected_player_data:
            for player in players:
                player_name_from_data = player.get('name', '').strip().lower()
                if player_name_normalized in player_name_from_data or player_name_from_data in player_name_normalized:
                    selected_player_data = player
                    break
        
        if not selected_player_data:
            similar_names = [p['name'] for p in players if player_name_normalized[:3] in p['name'].lower()][:5]
            error_msg = f"Player '{player_name}' not found"
            if similar_names:
                error_msg += f". Similar names: {', '.join(similar_names)}"
            return jsonify({"error": error_msg}), 404
        
        actual_player_name = selected_player_data.get('name')
        
        # Get batter ID
        try:
            batter_id = lookup_batter_id(actual_player_name)
        except Exception as e:
            return jsonify({"error": f"Could not find player ID for '{actual_player_name}': {str(e)}"}), 404
        
        # Calculate date range
        if season:
            start_date = f"{season}-03-01"
            end_date = f"{season}-11-30"
            filter_by_season = True
        else:
            current_year = datetime.now().year
            start_date = "2008-03-01"
            end_date = f"{current_year}-11-30"
            filter_by_season = False
        
        # Fetch statcast data
        try:
            statcast_df = fetch_batter_statcast(batter_id, start_date, end_date)
        except Exception as e:
            return jsonify({"error": f"Error fetching statcast data: {str(e)}"}), 500
        
        if statcast_df is None or statcast_df.empty:
            return jsonify({
                "error": f"No statcast data found for {actual_player_name}",
                "data": [],
                "summary": {}
            }), 200
        
        # Filter by season if specified
        if filter_by_season:
            year_column = None
            for col_name in ['game_year', 'year', 'Year', 'season']:
                if col_name in statcast_df.columns:
                    year_column = col_name
                    break
            
            if year_column:
                if not pd.api.types.is_integer_dtype(statcast_df[year_column]):
                    statcast_df[year_column] = pd.to_numeric(statcast_df[year_column], errors='coerce')
                statcast_df = statcast_df[
                    (statcast_df[year_column].notna()) & 
                    (statcast_df[year_column] == int(season))
                ]
            else:
                date_column = None
                for col_name in ['game_date', 'gameDate', 'date', 'Date', 'game_day']:
                    if col_name in statcast_df.columns:
                        date_column = col_name
                        break
                
                if date_column:
                    if not pd.api.types.is_datetime64_any_dtype(statcast_df[date_column]):
                        statcast_df[date_column] = pd.to_datetime(statcast_df[date_column], errors='coerce')
                    
                    season_start = pd.to_datetime(f"{season}-03-01")
                    season_end = pd.to_datetime(f"{season}-11-30")
                    
                    statcast_df = statcast_df[statcast_df[date_column].notna()]
                    statcast_df = statcast_df[
                        (statcast_df[date_column] >= season_start) & 
                        (statcast_df[date_column] <= season_end)
                    ]
            
            if statcast_df.empty:
                return jsonify({
                    "error": f"No statcast data found for {actual_player_name} for season {season}",
                    "data": [],
                    "summary": {}
                }), 200
        
        # Filter to only regular season games
        if 'game_type' in statcast_df.columns:
            statcast_df = statcast_df[statcast_df['game_type'] == 'R']
        
        # Filter to only events that are batted balls (have events)
        statcast_df = statcast_df[statcast_df['events'].notna()]
        
        if statcast_df.empty:
            return jsonify({
                "error": "No batted ball data available for the selected filters",
                "data": [],
                "summary": {}
            }), 200
        
        # Helper function to classify barrel (based on Statcast barrel definition)
        def classify_barrel(la, ev):
            """Classify if a batted ball is a barrel based on launch angle and exit velocity"""
            if pd.isna(la) or pd.isna(ev) or la < -50 or la > 50:
                return False
            
            if la >= 8 and la <= 50:
                # Calculate minimum exit velocity based on launch angle
                min_ev_map = {8: 98, 12: 98, 14: 98, 16: 97, 18: 96, 20: 95, 22: 94, 24: 93, 26: 92, 28: 91, 30: 90, 32: 89, 34: 88, 36: 87, 38: 86, 40: 85, 42: 84, 44: 83, 46: 82, 48: 81, 50: 80}
                min_ev = min_ev_map.get(int(la // 2) * 2, 92)
                max_ev = 117
                if ev >= min_ev and ev <= max_ev:
                    return True
            return False
        
        # Helper function to classify quality of contact
        def classify_quality(la, ev):
            """Classify quality of contact"""
            if pd.isna(la) or pd.isna(ev):
                return 'unknown'
            if classify_barrel(la, ev):
                return 'barrel'
            if ev >= 95 and la >= 8 and la <= 32:
                return 'solid'
            if ev >= 95 and (la < 8 or la > 32):
                return 'flare'
            if la < 8:
                return 'topped'
            if ev < 95:
                return 'weak'
            return 'other'
        
        # Prepare batted ball data
        batted_ball_data = []
        quality_counts = {'barrel': 0, 'solid': 0, 'flare': 0, 'topped': 0, 'weak': 0, 'other': 0, 'unknown': 0}
        total_batted_balls = len(statcast_df)
        barrels = 0
        hard_hits = 0
        sweet_spots = 0
        
        for _, row in statcast_df.iterrows():
            la = row.get('launch_angle')
            ev = row.get('launch_speed')
            events = row.get('events', '')
            
            is_barrel = False
            if 'barrel' in row and pd.notna(row['barrel']):
                is_barrel = bool(row['barrel'])
            elif not pd.isna(la) and not pd.isna(ev):
                is_barrel = classify_barrel(la, ev)
            
            if is_barrel:
                barrels += 1
            if not pd.isna(ev) and ev >= 95:
                hard_hits += 1
            if not pd.isna(la) and la >= 8 and la <= 32:
                sweet_spots += 1
            
            quality = classify_quality(la, ev) if not pd.isna(la) and not pd.isna(ev) else 'unknown'
            quality_counts[quality] = quality_counts.get(quality, 0) + 1
            
            batted_ball_data.append({
                'launch_angle': float(la) if not pd.isna(la) else None,
                'exit_velocity': float(ev) if not pd.isna(ev) else None,
                'events': str(events) if pd.notna(events) else None,
                'is_barrel': is_barrel,
                'quality': quality,
                'estimated_woba_using_speedangle': float(row['estimated_woba_using_speedangle']) if 'estimated_woba_using_speedangle' in row and pd.notna(row['estimated_woba_using_speedangle']) else None,
                'estimated_ba_using_speedangle': float(row['estimated_ba_using_speedangle']) if 'estimated_ba_using_speedangle' in row and pd.notna(row['estimated_ba_using_speedangle']) else None,
                'estimated_slg_using_speedangle': float(row['estimated_slg_using_speedangle']) if 'estimated_slg_using_speedangle' in row and pd.notna(row['estimated_slg_using_speedangle']) else None,
            })
        
        # Calculate summary statistics
        launch_speeds = statcast_df['launch_speed'].dropna().tolist() if 'launch_speed' in statcast_df.columns else []
        launch_angles = statcast_df['launch_angle'].dropna().tolist() if 'launch_angle' in statcast_df.columns else []
        
        barrel_rate = (barrels / total_batted_balls * 100) if total_batted_balls > 0 else 0
        hard_hit_pct = (hard_hits / total_batted_balls * 100) if total_batted_balls > 0 else 0
        sweet_spot_pct = (sweet_spots / total_batted_balls * 100) if total_batted_balls > 0 else 0
        
        summary = {
            'total_batted_balls': total_batted_balls,
            'barrel_rate': barrel_rate,
            'barrels': barrels,
            'hard_hit_pct': hard_hit_pct,
            'sweet_spot_pct': sweet_spot_pct,
            'avg_exit_velocity': float(np.mean(launch_speeds)) if launch_speeds else None,
            'avg_launch_angle': float(np.mean(launch_angles)) if launch_angles else None,
            'quality_counts': quality_counts
        }
        
        return jsonify({
            'player': actual_player_name,
            'filters': {'season': season},
            'data': batted_ball_data,
            'summary': summary
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Error generating barrel analysis: {str(e)}"}), 500


@bp.route('/visuals/pitchplots', methods=['GET'])
def api_visuals_pitchplots():
    """Get pitch plots data for visualization - returns Trackman-style movement data"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        pitcher_name = request.args.get('pitcher', '').strip()
        if not pitcher_name:
            return jsonify({"error": "Pitcher name is required"}), 400
        
        season = request.args.get('season', '').strip() or None
        if season:
            try:
                season = int(season)
            except ValueError:
                season = None
        
        # Filter options
        pitch_type = request.args.get('pitch_type', '').strip() or None
        batter_hand = request.args.get('batter_hand', '').strip() or None
        count = request.args.get('count', '').strip() or None
        min_velocity = request.args.get('min_velocity', type=float)
        max_velocity = request.args.get('max_velocity', type=float)
        min_hb = request.args.get('min_hb', type=float)
        max_hb = request.args.get('max_hb', type=float)
        min_vb = request.args.get('min_vb', type=float)
        max_vb = request.args.get('max_vb', type=float)
        normalize_arm_side = request.args.get('normalize_arm_side', '0') == '1'
        
        # Import statcast functions
        sys.path.insert(0, str(Config.ROOT_DIR / "src"))
        from scrape_savant import fetch_pitcher_statcast
        from datetime import datetime
        import pandas as pd
        import numpy as np
        
        # Create lookup function for pitcher ID (similar to batter lookup)
        def lookup_pitcher_id(name: str) -> int:
            """Look up MLBAM ID for a pitcher by name"""
            from scrape_savant import lookup_batter_id
            # The lookup_batter_id function works for both batters and pitchers
            return lookup_batter_id(name)
        
        # Get pitcher ID
        try:
            pitcher_id = lookup_pitcher_id(pitcher_name)
        except Exception as e:
            return jsonify({"error": f"Could not find pitcher ID for '{pitcher_name}': {str(e)}"}), 404
        
        # Calculate date range
        if season:
            start_date = f"{season}-03-01"
            end_date = f"{season}-11-30"
            filter_by_season = True
        else:
            current_year = datetime.now().year
            start_date = "2008-03-01"
            end_date = f"{current_year}-11-30"
            filter_by_season = False
        
        # Fetch statcast data
        try:
            statcast_df = fetch_pitcher_statcast(pitcher_id, start_date, end_date)
        except Exception as e:
            return jsonify({"error": f"Error fetching statcast data: {str(e)}"}), 500
        
        if statcast_df is None or statcast_df.empty:
            return jsonify({
                "error": f"No statcast data found for {pitcher_name}",
                "pitcher": pitcher_name,
                "pitches": [],
                "summary": {}
            }), 200
        
        # Filter by season if specified
        if filter_by_season:
            year_column = None
            for col_name in ['game_year', 'year', 'Year', 'season']:
                if col_name in statcast_df.columns:
                    year_column = col_name
                    break
            
            if year_column:
                if not pd.api.types.is_integer_dtype(statcast_df[year_column]):
                    statcast_df[year_column] = pd.to_numeric(statcast_df[year_column], errors='coerce')
                statcast_df = statcast_df[
                    (statcast_df[year_column].notna()) & 
                    (statcast_df[year_column] == int(season))
                ]
            else:
                date_column = None
                for col_name in ['game_date', 'gameDate', 'date', 'Date', 'game_day']:
                    if col_name in statcast_df.columns:
                        date_column = col_name
                        break
                
                if date_column:
                    if not pd.api.types.is_datetime64_any_dtype(statcast_df[date_column]):
                        statcast_df[date_column] = pd.to_datetime(statcast_df[date_column], errors='coerce')
                    
                    season_start = pd.to_datetime(f"{season}-03-01")
                    season_end = pd.to_datetime(f"{season}-11-30")
                    
                    statcast_df = statcast_df[statcast_df[date_column].notna()]
                    statcast_df = statcast_df[
                        (statcast_df[date_column] >= season_start) & 
                        (statcast_df[date_column] <= season_end)
                    ]
            
            if statcast_df.empty:
                return jsonify({
                    "error": f"No statcast data found for {pitcher_name} for season {season}",
                    "pitcher": pitcher_name,
                    "pitches": [],
                    "summary": {}
                }), 200
        
        # Filter by pitch type if specified
        if pitch_type and 'pitch_type' in statcast_df.columns:
            statcast_df = statcast_df[statcast_df['pitch_type'] == pitch_type]
        
        # Filter by batter handedness if specified
        if batter_hand and 'stand' in statcast_df.columns:
            statcast_df = statcast_df[statcast_df['stand'] == batter_hand]
        
        # Filter by count if specified
        if count:
            count_parts = count.split('-')
            if len(count_parts) == 2:
                try:
                    balls_filter = int(count_parts[0])
                    strikes_filter = int(count_parts[1])
                    if 'balls' in statcast_df.columns and 'strikes' in statcast_df.columns:
                        statcast_df = statcast_df[
                            (statcast_df['balls'] == balls_filter) & 
                            (statcast_df['strikes'] == strikes_filter)
                        ]
                except ValueError:
                    pass
        
        # Filter by velocity if specified
        if min_velocity is not None and 'release_speed' in statcast_df.columns:
            statcast_df = statcast_df[
                (statcast_df['release_speed'].notna()) & 
                (statcast_df['release_speed'] >= min_velocity)
            ]
        
        if max_velocity is not None and 'release_speed' in statcast_df.columns:
            statcast_df = statcast_df[
                (statcast_df['release_speed'].notna()) & 
                (statcast_df['release_speed'] <= max_velocity)
            ]
        
        # Filter out rows without movement data
        if 'pfx_x' not in statcast_df.columns or 'pfx_z' not in statcast_df.columns:
            return jsonify({
                "error": "Movement data (pfx_x, pfx_z) not available in statcast data",
                "pitcher": pitcher_name,
                "pitches": [],
                "summary": {}
            }), 200
        
        statcast_df = statcast_df[
            statcast_df['pfx_x'].notna() & 
            statcast_df['pfx_z'].notna()
        ]
        
        if statcast_df.empty:
            return jsonify({
                "error": "No valid movement data found",
                "pitcher": pitcher_name,
                "pitches": [],
                "summary": {}
            }), 200
        
        # Get pitcher handedness
        pitcher_hand = 'R'  # Default
        if 'p_throws' in statcast_df.columns:
            throws_values = statcast_df['p_throws'].dropna()
            if len(throws_values) > 0:
                pitcher_hand = str(throws_values.mode().iloc[0]) if len(throws_values.mode()) > 0 else 'R'
        
        # Convert movement to inches and normalize if requested
        if normalize_arm_side:
            sign = statcast_df['p_throws'].map({"R": -1, "L": 1}).fillna(-1)
        else:
            sign = -1
        
        statcast_df['pfx_x_inches'] = statcast_df['pfx_x'] * 12 * sign
        statcast_df['pfx_z_inches'] = statcast_df['pfx_z'] * 12
        
        # Filter by horizontal break if specified
        if min_hb is not None:
            statcast_df = statcast_df[statcast_df['pfx_x_inches'] >= min_hb]
        
        if max_hb is not None:
            statcast_df = statcast_df[statcast_df['pfx_x_inches'] <= max_hb]
        
        # Filter by vertical break if specified
        if min_vb is not None:
            statcast_df = statcast_df[statcast_df['pfx_z_inches'] >= min_vb]
        
        if max_vb is not None:
            statcast_df = statcast_df[statcast_df['pfx_z_inches'] <= max_vb]
        
        if statcast_df.empty:
            return jsonify({
                "error": "No pitch data available for the selected filters",
                "pitcher": pitcher_name,
                "pitches": [],
                "summary": {}
            }), 200
        
        # Prepare pitch data
        pitches = []
        for _, row in statcast_df.iterrows():
            pitch_data = {
                'pitch_type': str(row.get('pitch_type', 'UN')).upper() if pd.notna(row.get('pitch_type')) else 'UN',
                'horizontal_break': float(row['pfx_x_inches']) if pd.notna(row['pfx_x_inches']) else None,
                'vertical_break': float(row['pfx_z_inches']) if pd.notna(row['pfx_z_inches']) else None,
                'velocity': float(row['release_speed']) if 'release_speed' in row and pd.notna(row['release_speed']) else None,
                'count': f"{int(row['balls'])}-{int(row['strikes'])}" if 'balls' in row and 'strikes' in row and pd.notna(row['balls']) and pd.notna(row['strikes']) else None,
                'release_height': float(row['release_pos_z']) if 'release_pos_z' in row and pd.notna(row['release_pos_z']) else None,
                'release_side': float(-row['release_pos_x']) if 'release_pos_x' in row and pd.notna(row['release_pos_x']) else None,
                'release_extension': float(row['release_extension']) if 'release_extension' in row and pd.notna(row['release_extension']) else None,
                'spin_rate': float(row['release_spin_rate']) if 'release_spin_rate' in row and pd.notna(row['release_spin_rate']) else None,
                'spin_axis': float(row['spin_axis']) if 'spin_axis' in row and pd.notna(row['spin_axis']) else None
            }
            
            # Only include pitches with valid movement data
            if pitch_data['horizontal_break'] is not None and pitch_data['vertical_break'] is not None:
                pitches.append(pitch_data)
        
        # Calculate overall summary statistics
        velocities = [p['velocity'] for p in pitches if p['velocity'] is not None]
        horizontal_breaks = [p['horizontal_break'] for p in pitches if p['horizontal_break'] is not None]
        vertical_breaks = [p['vertical_break'] for p in pitches if p['vertical_break'] is not None]
        
        # Calculate per-pitch-type statistics
        pitch_type_stats = []
        total_pitches = len(statcast_df)
        
        # Normalize pitch type labels (similar to plots_movement.py)
        def normalize_pitch_type(pt):
            mapping = {
                "FA": "FF", "FO": "FF", "SV": "SL", "ST": "SL",
                "KC": "CU", "CS": "CU", "UN": "FF"
            }
            pt_str = str(pt).upper() if pd.notna(pt) else "UN"
            return mapping.get(pt_str, pt_str)
        
        statcast_df['pitch_type_normalized'] = statcast_df['pitch_type'].apply(normalize_pitch_type)
        
        # Group by normalized pitch type
        for pitch_type in statcast_df['pitch_type_normalized'].unique():
            if pd.isna(pitch_type):
                continue
                
            pitch_type_df = statcast_df[statcast_df['pitch_type_normalized'] == pitch_type]
            pitch_count = len(pitch_type_df)
            
            if pitch_count < 1:
                continue
            
            # Calculate metrics
            pitch_stats = {
                'pitch_type': str(pitch_type),
                'count': pitch_count,
                'usage_pct': float((pitch_count / total_pitches * 100)) if total_pitches > 0 else 0.0
            }
            
            # Velocity stats
            if 'release_speed' in pitch_type_df.columns:
                velo_data = pitch_type_df['release_speed'].dropna()
                if len(velo_data) > 0:
                    pitch_stats['velocity_avg'] = float(velo_data.mean())
                    pitch_stats['velocity_min'] = float(velo_data.min())
                    pitch_stats['velocity_max'] = float(velo_data.max())
            
            # Movement stats (already in inches)
            hb_data = pitch_type_df['pfx_x_inches'].dropna()
            if len(hb_data) > 0:
                pitch_stats['horizontal_break_avg'] = float(hb_data.mean())
            
            vb_data = pitch_type_df['pfx_z_inches'].dropna()
            if len(vb_data) > 0:
                pitch_stats['vertical_break_avg'] = float(vb_data.mean())
            
            # Release position
            if 'release_pos_z' in pitch_type_df.columns:
                release_h_data = pitch_type_df['release_pos_z'].dropna()
                if len(release_h_data) > 0:
                    pitch_stats['release_height'] = float(release_h_data.mean())
            
            if 'release_pos_x' in pitch_type_df.columns:
                release_x_data = pitch_type_df['release_pos_x'].dropna()
                if len(release_x_data) > 0:
                    # Negate to match convention (left side positive)
                    pitch_stats['release_side'] = float(-release_x_data.mean())
            
            # Release extension
            if 'release_extension' in pitch_type_df.columns:
                ext_data = pitch_type_df['release_extension'].dropna()
                if len(ext_data) > 0:
                    pitch_stats['release_extension'] = float(ext_data.mean())
            
            # Spin rate
            if 'release_spin_rate' in pitch_type_df.columns:
                spin_data = pitch_type_df['release_spin_rate'].dropna()
                if len(spin_data) > 0:
                    pitch_stats['spin_rate_avg'] = float(spin_data.mean())
            
            # Spin axis
            if 'spin_axis' in pitch_type_df.columns:
                axis_data = pitch_type_df['spin_axis'].dropna()
                if len(axis_data) > 0:
                    # Calculate circular mean for spin axis (0-360 degrees)
                    axis_rad = np.deg2rad(axis_data)
                    mean_cos = np.cos(axis_rad).mean()
                    mean_sin = np.sin(axis_rad).mean()
                    mean_axis = np.rad2deg(np.arctan2(mean_sin, mean_cos))
                    if mean_axis < 0:
                        mean_axis += 360
                    pitch_stats['spin_axis_avg'] = float(mean_axis)
            
            # Release velocity components (for axis calculation if needed)
            if 'vx0' in pitch_type_df.columns and 'vy0' in pitch_type_df.columns and 'vz0' in pitch_type_df.columns:
                vx_data = pitch_type_df['vx0'].dropna()
                vy_data = pitch_type_df['vy0'].dropna()
                vz_data = pitch_type_df['vz0'].dropna()
                if len(vx_data) > 0 and len(vy_data) > 0 and len(vz_data) > 0:
                    pitch_stats['release_vx_avg'] = float(vx_data.mean())
                    pitch_stats['release_vy_avg'] = float(vy_data.mean())
                    pitch_stats['release_vz_avg'] = float(vz_data.mean())
            
            pitch_type_stats.append(pitch_stats)
        
        # Sort by usage percentage (descending)
        pitch_type_stats.sort(key=lambda x: x.get('usage_pct', 0), reverse=True)
        
        summary = {
            'total_pitches': len(pitches),
            'avg_velocity': float(np.mean(velocities)) if velocities else None,
            'min_velocity': float(min(velocities)) if velocities else None,
            'max_velocity': float(max(velocities)) if velocities else None,
            'avg_hb': float(np.mean(horizontal_breaks)) if horizontal_breaks else None,
            'avg_vb': float(np.mean(vertical_breaks)) if vertical_breaks else None,
            'pitcher_hand': pitcher_hand,
            'pitch_type_stats': pitch_type_stats
        }
        
        return jsonify({
            'pitcher': pitcher_name,
            'pitches': pitches,
            'summary': summary,
            'filters': {
                'season': season,
                'pitch_type': pitch_type,
                'batter_hand': batter_hand,
                'count': count,
                'min_velocity': min_velocity,
                'max_velocity': max_velocity,
                'min_hb': min_hb,
                'max_hb': max_hb,
                'min_vb': min_vb,
                'max_vb': max_vb,
                'normalize_arm_side': normalize_arm_side
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@bp.route('/visuals/pitch-mix-analysis', methods=['GET'])
def api_visuals_pitch_mix_analysis():
    """Get comprehensive pitch mix analysis data with breakdowns by count, situation, and batter handedness"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        pitcher_name = request.args.get('pitcher', '').strip()
        if not pitcher_name:
            return jsonify({"error": "Pitcher name is required"}), 400
        
        season = request.args.get('season', '').strip() or None
        if season:
            try:
                season = int(season)
            except ValueError:
                season = None
        
        # Import statcast functions
        sys.path.insert(0, str(Config.ROOT_DIR / "src"))
        from scrape_savant import fetch_pitcher_statcast
        
        # Create lookup function for pitcher ID
        def lookup_pitcher_id(name: str) -> int:
            """Look up MLBAM ID for a pitcher by name"""
            from scrape_savant import lookup_batter_id
            return lookup_batter_id(name)
        
        # Get pitcher ID
        try:
            pitcher_id = lookup_pitcher_id(pitcher_name)
        except Exception as e:
            return jsonify({"error": f"Could not find pitcher ID for '{pitcher_name}': {str(e)}"}), 404
        
        # Calculate date range
        if season:
            start_date = f"{season}-03-01"
            end_date = f"{season}-11-30"
            filter_by_season = True
        else:
            current_year = datetime.now().year
            start_date = "2008-03-01"
            end_date = f"{current_year}-11-30"
            filter_by_season = False
        
        # Fetch statcast data
        try:
            df = fetch_pitcher_statcast(pitcher_id, start_date, end_date)
        except Exception as e:
            return jsonify({"error": f"Error fetching statcast data: {str(e)}"}), 500
        
        if df is None or df.empty:
            return jsonify({
                "error": f"No statcast data found for {pitcher_name}",
                "pitcher": pitcher_name,
                "data": {}
            }), 200
        
        # Filter by season if specified
        if filter_by_season:
            year_column = None
            for col_name in ['game_year', 'year', 'Year', 'season']:
                if col_name in df.columns:
                    year_column = col_name
                    break
            
            if year_column:
                if not pd.api.types.is_integer_dtype(df[year_column]):
                    df[year_column] = pd.to_numeric(df[year_column], errors='coerce')
                df = df[
                    (df[year_column].notna()) & 
                    (df[year_column] == int(season))
                ]
            else:
                date_column = None
                for col_name in ['game_date', 'gameDate', 'date', 'Date', 'game_day']:
                    if col_name in df.columns:
                        date_column = col_name
                        break
                
                if date_column:
                    if not pd.api.types.is_datetime64_any_dtype(df[date_column]):
                        df[date_column] = pd.to_datetime(df[date_column], errors='coerce')
                    
                    season_start = pd.to_datetime(f"{season}-03-01")
                    season_end = pd.to_datetime(f"{season}-11-30")
                    
                    df = df[df[date_column].notna()]
                    df = df[
                        (df[date_column] >= season_start) & 
                        (df[date_column] <= season_end)
                    ]
            
            if df.empty:
                return jsonify({
                    "error": f"No statcast data found for {pitcher_name} for season {season}",
                    "pitcher": pitcher_name,
                    "data": {}
                }), 200
        
        # Filter out rows without necessary data
        df = df.dropna(subset=['pitch_type', 'balls', 'strikes'])
        if df.empty:
            return jsonify({
                "error": "No valid pitch data available",
                "pitcher": pitcher_name,
                "data": {}
            }), 200
        
        # Create count column
        df['count'] = df['balls'].astype(int).astype(str) + '-' + df['strikes'].astype(int).astype(str)
        
        # Define situations
        def get_situation(row):
            """Determine game situation based on base runners and inning"""
            inning = row.get('inning', 0) if pd.notna(row.get('inning')) else 0
            on_1b = row.get('on_1b', pd.NA) if 'on_1b' in row else pd.NA
            on_2b = row.get('on_2b', pd.NA) if 'on_2b' in row else pd.NA
            on_3b = row.get('on_3b', pd.NA) if 'on_3b' in row else pd.NA
            
            runners_on = sum([1 for r in [on_1b, on_2b, on_3b] if pd.notna(r)])
            
            if runners_on == 0:
                return "Bases Empty"
            elif runners_on == 1:
                if pd.notna(on_3b):
                    return "Runner on 3rd"
                elif pd.notna(on_2b):
                    return "Runner on 2nd"
                else:
                    return "Runner on 1st"
            elif runners_on == 2:
                if pd.notna(on_2b) and pd.notna(on_3b):
                    return "Runners on 2nd & 3rd"
                elif pd.notna(on_1b) and pd.notna(on_3b):
                    return "Runners on 1st & 3rd"
                else:
                    return "Runners on 1st & 2nd"
            else:
                return "Bases Loaded"
        
        df['situation'] = df.apply(get_situation, axis=1)
        
        # Get batter handedness
        if 'stand' not in df.columns:
            df['stand'] = 'R'
        
        # Calculate effectiveness metrics
        desc = df['description'].astype(str).str.lower()
        df['is_strike'] = desc.isin(['called_strike', 'foul', 'foul_tip', 'swinging_strike', 'swinging_strike_blocked', 'foul_bunt', 'hit_into_play'])
        df['is_swing'] = desc.isin(['foul', 'foul_tip', 'swinging_strike', 'swinging_strike_blocked', 'missed_bunt', 'foul_bunt', 'hit_into_play'])
        df['is_whiff'] = desc.isin(['swinging_strike', 'swinging_strike_blocked', 'missed_bunt'])
        
        # Determine if pitch is in zone
        if 'zone' in df.columns:
            df['is_zone'] = df['zone'].between(1, 9, inclusive='both')
        elif 'plate_x' in df.columns and 'plate_z' in df.columns:
            df['is_zone'] = (df['plate_x'].between(-0.85, 0.85, inclusive='both') & df['plate_z'].between(1.5, 3.5, inclusive='both'))
        else:
            df['is_zone'] = False
        
        # Helper function to calculate metrics for a group
        def calculate_metrics(group_df):
            total = len(group_df)
            if total == 0:
                return {}
            
            strikes = group_df['is_strike'].sum()
            swings = group_df['is_swing'].sum()
            whiffs = group_df['is_whiff'].sum()
            in_zone = group_df['is_zone'].sum() if 'is_zone' in group_df.columns else 0
            
            metrics = {
                'usage_pct': 100.0,
                'strike_rate': (strikes / total * 100) if total > 0 else 0.0,
                'swing_rate': (swings / total * 100) if total > 0 else 0.0,
                'whiff_rate': (whiffs / swings * 100) if swings > 0 else None,
                'zone_rate': (in_zone / total * 100) if total > 0 else 0.0,
            }
            
            # xwOBA if available
            if 'estimated_woba_using_speedangle' in group_df.columns:
                xwoba_values = group_df['estimated_woba_using_speedangle'].dropna()
                metrics['xwoba'] = float(xwoba_values.mean()) if len(xwoba_values) > 0 else None
            elif 'woba_value' in group_df.columns:
                woba_values = group_df['woba_value'].dropna()
                metrics['xwoba'] = float(woba_values.mean()) if len(woba_values) > 0 else None
            else:
                metrics['xwoba'] = None
            
            # Average velocity
            if 'release_speed' in group_df.columns:
                velo_values = group_df['release_speed'].dropna()
                metrics['avg_velocity'] = float(velo_values.mean()) if len(velo_values) > 0 else None
            else:
                metrics['avg_velocity'] = None
            
            return metrics
        
        # Breakdown by count
        count_data = {}
        for count in df['count'].unique():
            count_df = df[df['count'] == count]
            total_pitches = len(count_df)
            if total_pitches == 0:
                continue
            
            count_breakdown = {'total_pitches': total_pitches, 'by_pitch_type': {}}
            for pitch_type in count_df['pitch_type'].unique():
                pitch_df = count_df[count_df['pitch_type'] == pitch_type]
                pitch_count = len(pitch_df)
                if pitch_count == 0:
                    continue
                
                metrics = calculate_metrics(pitch_df)
                metrics['usage_pct'] = (pitch_count / total_pitches * 100) if total_pitches > 0 else 0.0
                metrics['pitch_count'] = pitch_count
                count_breakdown['by_pitch_type'][pitch_type] = metrics
            
            count_data[count] = count_breakdown
        
        # Breakdown by situation
        situation_data = {}
        for situation in df['situation'].unique():
            situation_df = df[df['situation'] == situation]
            total_pitches = len(situation_df)
            if total_pitches == 0:
                continue
            
            situation_breakdown = {'total_pitches': total_pitches, 'by_pitch_type': {}}
            for pitch_type in situation_df['pitch_type'].unique():
                pitch_df = situation_df[situation_df['pitch_type'] == pitch_type]
                pitch_count = len(pitch_df)
                if pitch_count == 0:
                    continue
                
                metrics = calculate_metrics(pitch_df)
                metrics['usage_pct'] = (pitch_count / total_pitches * 100) if total_pitches > 0 else 0.0
                metrics['pitch_count'] = pitch_count
                situation_breakdown['by_pitch_type'][pitch_type] = metrics
            
            situation_data[situation] = situation_breakdown
        
        # Breakdown by batter handedness
        batter_hand_data = {}
        for stand in ['R', 'L']:
            if stand not in df['stand'].values:
                continue
            
            hand_df = df[df['stand'] == stand]
            total_pitches = len(hand_df)
            if total_pitches == 0:
                continue
            
            hand_breakdown = {'total_pitches': total_pitches, 'by_pitch_type': {}}
            for pitch_type in hand_df['pitch_type'].unique():
                pitch_df = hand_df[hand_df['pitch_type'] == pitch_type]
                pitch_count = len(pitch_df)
                if pitch_count == 0:
                    continue
                
                metrics = calculate_metrics(pitch_df)
                metrics['usage_pct'] = (pitch_count / total_pitches * 100) if total_pitches > 0 else 0.0
                metrics['pitch_count'] = pitch_count
                hand_breakdown['by_pitch_type'][pitch_type] = metrics
            
            batter_hand_data[stand] = hand_breakdown
        
        # Overall pitch mix
        overall_total = len(df)
        overall_data = {'total_pitches': overall_total, 'by_pitch_type': {}}
        for pitch_type in df['pitch_type'].unique():
            pitch_df = df[df['pitch_type'] == pitch_type]
            pitch_count = len(pitch_df)
            if pitch_count == 0:
                continue
            
            metrics = calculate_metrics(pitch_df)
            metrics['usage_pct'] = (pitch_count / overall_total * 100) if overall_total > 0 else 0.0
            metrics['pitch_count'] = pitch_count
            overall_data['by_pitch_type'][pitch_type] = metrics
        
        # Get pitcher handedness
        pitcher_hand = 'R'
        if 'p_throws' in df.columns:
            throws_values = df['p_throws'].dropna()
            if len(throws_values) > 0:
                pitcher_hand = str(throws_values.mode().iloc[0]) if len(throws_values.mode()) > 0 else 'R'
        
        return jsonify({
            'pitcher': pitcher_name,
            'pitcher_hand': pitcher_hand,
            'season': season,
            'total_pitches': overall_total,
            'breakdowns': {
                'by_count': count_data,
                'by_situation': situation_data,
                'by_batter_hand': batter_hand_data,
                'overall': overall_data
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.route('/visuals/pitch-arsenal-effectiveness', methods=['GET'])
def api_visuals_pitch_arsenal_effectiveness():
    """Get comprehensive pitch arsenal effectiveness data with run value, whiff rates, ground ball rates, and putaway percentages"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        pitcher_name = request.args.get('pitcher', '').strip()
        if not pitcher_name:
            return jsonify({"error": "Pitcher name is required"}), 400
        
        season = request.args.get('season', '').strip() or None
        if season:
            try:
                season = int(season)
            except ValueError:
                season = None
        
        batter_hand = request.args.get('batter_hand', '').strip() or None
        count_filter = request.args.get('count_filter', '').strip() or None
        
        # Import statcast functions
        sys.path.insert(0, str(Config.ROOT_DIR / "src"))
        from scrape_savant import fetch_pitcher_statcast
        from datetime import datetime
        import pandas as pd
        import numpy as np
        
        # Create lookup function for pitcher ID
        def lookup_pitcher_id(name: str) -> int:
            """Look up MLBAM ID for a pitcher by name"""
            from scrape_savant import lookup_batter_id
            return lookup_batter_id(name)
        
        # Get pitcher ID
        try:
            pitcher_id = lookup_pitcher_id(pitcher_name)
        except Exception as e:
            return jsonify({"error": f"Could not find pitcher ID for '{pitcher_name}': {str(e)}"}), 404
        
        # Calculate date range
        if season:
            start_date = f"{season}-03-01"
            end_date = f"{season}-11-30"
            filter_by_season = True
        else:
            current_year = datetime.now().year
            start_date = "2008-03-01"
            end_date = f"{current_year}-11-30"
            filter_by_season = False
        
        # Fetch statcast data
        try:
            df = fetch_pitcher_statcast(pitcher_id, start_date, end_date)
        except Exception as e:
            return jsonify({"error": f"Error fetching statcast data: {str(e)}"}), 500
        
        if df is None or df.empty:
            return jsonify({
                "error": f"No statcast data found for {pitcher_name}",
                "pitcher": pitcher_name,
                "data": {}
            }), 200
        
        # Filter by season if specified
        if filter_by_season:
            year_column = None
            for col_name in ['game_year', 'year', 'Year', 'season']:
                if col_name in df.columns:
                    year_column = col_name
                    break
            
            if year_column:
                if not pd.api.types.is_integer_dtype(df[year_column]):
                    df[year_column] = pd.to_numeric(df[year_column], errors='coerce')
                df = df[
                    (df[year_column].notna()) & 
                    (df[year_column] == int(season))
                ]
            else:
                date_column = None
                for col_name in ['game_date', 'gameDate', 'date', 'Date', 'game_day']:
                    if col_name in df.columns:
                        date_column = col_name
                        break
                
                if date_column:
                    if not pd.api.types.is_datetime64_any_dtype(df[date_column]):
                        df[date_column] = pd.to_datetime(df[date_column], errors='coerce')
                    
                    season_start = pd.to_datetime(f"{season}-03-01")
                    season_end = pd.to_datetime(f"{season}-11-30")
                    
                    df = df[df[date_column].notna()]
                    df = df[
                        (df[date_column] >= season_start) & 
                        (df[date_column] <= season_end)
                    ]
            
            if df.empty:
                return jsonify({
                    "error": f"No statcast data found for {pitcher_name} for season {season}",
                    "pitcher": pitcher_name,
                    "data": {}
                }), 200
        
        # Filter by batter handedness if specified
        if batter_hand and 'stand' in df.columns:
            df = df[df['stand'] == batter_hand]
        
        # Filter by count if specified
        if count_filter:
            if count_filter == '2-strikes':
                df = df[df['strikes'] == 2]
            else:
                balls, strikes = map(int, count_filter.split('-'))
                df = df[(df['balls'] == balls) & (df['strikes'] == strikes)]
        
        # Filter out rows without necessary data
        df = df.dropna(subset=['pitch_type'])
        if df.empty:
            return jsonify({
                "error": "No valid pitch data available",
                "pitcher": pitcher_name,
                "data": {}
            }), 200
        
        # Calculate run value (delta_run_exp if available, otherwise use estimated_woba_against)
        if 'delta_run_exp' in df.columns:
            df['run_value'] = df['delta_run_exp']
        elif 'estimated_woba_using_speedangle' in df.columns:
            # Approximate run value from wOBA (rough conversion: wOBA * 1.2 - 0.3)
            df['run_value'] = df['estimated_woba_using_speedangle'] * 1.2 - 0.3
        else:
            df['run_value'] = 0.0
        
        # Calculate whiff rates
        desc = df['description'].astype(str).str.lower()
        df['is_strike'] = desc.isin([
            'called_strike', 'foul', 'foul_tip', 'swinging_strike', 
            'swinging_strike_blocked', 'foul_bunt', 'hit_into_play'
        ])
        df['is_whiff'] = desc.isin(['swinging_strike', 'swinging_strike_blocked', 'missed_bunt'])
        df['is_swing'] = desc.isin([
            'foul', 'foul_tip', 'swinging_strike', 'swinging_strike_blocked', 
            'missed_bunt', 'foul_bunt', 'hit_into_play'
        ])
        
        # Calculate ground ball rates (launch angle < 10 degrees)
        if 'launch_angle' in df.columns:
            df['is_ground_ball'] = (df['launch_angle'].notna()) & (df['launch_angle'] < 10)
            df['is_batted_ball'] = df['launch_angle'].notna()
        else:
            df['is_ground_ball'] = False
            df['is_batted_ball'] = False
        
        # Calculate strikeouts on 2-strike counts
        df['is_two_strike'] = df['strikes'] == 2
        df['is_strikeout'] = desc.isin(['strikeout', 'strikeout_double_play'])
        
        # Helper function to create zone heatmap data
        def create_zone_heatmap(group_df, metric_col, min_samples=5):
            """Create heatmap data for a zone-based metric"""
            if len(group_df) < min_samples:
                return {'zones': []}
            
            # Filter to pitches with location data
            loc_df = group_df[group_df['plate_x'].notna() & group_df['plate_z'].notna()]
            if len(loc_df) < min_samples:
                return {'zones': []}
            
            # Create grid zones
            zones = []
            x_bins = np.linspace(-2, 2, 10)  # 10 bins from -2 to 2 feet
            z_bins = np.linspace(0, 4, 10)   # 10 bins from 0 to 4 feet
            
            for i in range(len(x_bins) - 1):
                for j in range(len(z_bins) - 1):
                    x_min, x_max = x_bins[i], x_bins[i + 1]
                    z_min, z_max = z_bins[j], z_bins[j + 1]
                    
                    zone_df = loc_df[
                        (loc_df['plate_x'] >= x_min) & (loc_df['plate_x'] < x_max) &
                        (loc_df['plate_z'] >= z_min) & (loc_df['plate_z'] < z_max)
                    ]
                    
                    if len(zone_df) >= min_samples:
                        if metric_col == 'run_value':
                            value = zone_df['run_value'].mean()
                        elif metric_col == 'whiff_rate':
                            swings = zone_df['is_swing'].sum()
                            whiffs = zone_df['is_whiff'].sum()
                            value = (whiffs / swings * 100) if swings > 0 else 0
                        elif metric_col == 'ground_ball_rate':
                            batted = zone_df['is_batted_ball'].sum()
                            ground_balls = zone_df['is_ground_ball'].sum()
                            value = (ground_balls / batted * 100) if batted > 0 else 0
                        else:
                            value = 0
                        
                        zones.append({
                            'x': (x_min + x_max) / 2,
                            'z': (z_min + z_max) / 2,
                            'value': float(value),
                            'samples': len(zone_df)
                        })
            
            return {'zones': zones}
        
        # Get unique pitch types
        pitch_types = df['pitch_type'].unique().tolist()
        
        # Calculate heatmaps for each metric
        run_value_heatmaps = {}
        whiff_rate_heatmaps = {}
        ground_ball_heatmaps = {}
        putaway_data = {}
        summary = {}
        
        for pitch_type in pitch_types:
            pitch_df = df[df['pitch_type'] == pitch_type]
            
            if len(pitch_df) < 10:  # Skip if too few pitches
                continue
            
            # Run value heatmap
            run_value_heatmaps[pitch_type] = create_zone_heatmap(pitch_df, 'run_value')
            
            # Whiff rate heatmap
            swing_df = pitch_df[pitch_df['is_swing']]
            if len(swing_df) >= 10:
                whiff_rate_heatmaps[pitch_type] = create_zone_heatmap(swing_df, 'whiff_rate')
            else:
                whiff_rate_heatmaps[pitch_type] = {'zones': []}
            
            # Ground ball rate heatmap
            batted_df = pitch_df[pitch_df['is_batted_ball']]
            if len(batted_df) >= 10:
                ground_ball_heatmaps[pitch_type] = create_zone_heatmap(batted_df, 'ground_ball_rate')
            else:
                ground_ball_heatmaps[pitch_type] = {'zones': []}
            
            # Putaway percentage (strikeouts on 2-strike counts)
            two_strike_df = pitch_df[pitch_df['is_two_strike']]
            two_strike_count = len(two_strike_df)
            strikeouts = two_strike_df['is_strikeout'].sum()
            
            putaway_data[pitch_type] = {
                'two_strike_pitches': int(two_strike_count),
                'strikeouts': int(strikeouts),
                'putaway_pct': float((strikeouts / two_strike_count * 100) if two_strike_count > 0 else 0)
            }
            
            # Summary statistics
            total_pitches = len(pitch_df)
            overall_total = len(df)
            
            strikes = pitch_df['is_strike'].sum() if 'is_strike' in pitch_df.columns else 0
            swings = pitch_df['is_swing'].sum()
            whiffs = pitch_df['is_whiff'].sum()
            
            # Calculate metrics
            avg_run_value = pitch_df['run_value'].mean() if 'run_value' in pitch_df.columns else 0
            whiff_rate = (whiffs / swings * 100) if swings > 0 else None
            strike_rate = (strikes / total_pitches * 100) if total_pitches > 0 else 0
            
            # Ground ball rate
            batted = pitch_df['is_batted_ball'].sum()
            ground_balls = pitch_df['is_ground_ball'].sum()
            ground_ball_pct = (ground_balls / batted * 100) if batted > 0 else None
            
            # xwOBA
            if 'estimated_woba_using_speedangle' in pitch_df.columns:
                xwoba_values = pitch_df['estimated_woba_using_speedangle'].dropna()
                xwoba = float(xwoba_values.mean()) if len(xwoba_values) > 0 else None
            else:
                xwoba = None
            
            summary[pitch_type] = {
                'usage_pct': (total_pitches / overall_total * 100) if overall_total > 0 else 0,
                'avg_run_value': float(avg_run_value),
                'whiff_rate': float(whiff_rate) if whiff_rate is not None else None,
                'ground_ball_pct': float(ground_ball_pct) if ground_ball_pct is not None else None,
                'putaway_pct': putaway_data[pitch_type]['putaway_pct'],
                'strike_rate': float(strike_rate),
                'xwoba': xwoba
            }
        
        # Get pitcher handedness
        pitcher_hand = 'R'
        if 'p_throws' in df.columns:
            throws_values = df['p_throws'].dropna()
            if len(throws_values) > 0:
                pitcher_hand = str(throws_values.mode().iloc[0]) if len(throws_values.mode()) > 0 else 'R'
        
        return jsonify({
            'pitcher': pitcher_name,
            'pitcher_hand': pitcher_hand,
            'season': season,
            'total_pitches': len(df),
            'pitch_types': pitch_types,
            'run_value_heatmaps': run_value_heatmaps,
            'whiff_rate_heatmaps': whiff_rate_heatmaps,
            'ground_ball_heatmaps': ground_ball_heatmaps,
            'putaway_data': putaway_data,
            'summary': summary
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@bp.route('/visuals/count-performance', methods=['GET'])
@bp.route('/visuals/velocity-trends', methods=['GET'])
def api_visuals_velocity_trends():
    """Get velocity trends data for pitchers or batters"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        player_name = request.args.get('player', '').strip()
        if not player_name:
            return jsonify({"error": "Player name is required"}), 400
        
        player_type = request.args.get('player_type', 'pitcher').strip().lower()
        view_type = request.args.get('view_type', 'career').strip().lower()
        season = request.args.get('season', '').strip() or None
        game_date = request.args.get('game_date', '').strip() or None
        pitch_type = request.args.get('pitch_type', '').strip() or None
        
        if season:
            try:
                season = int(season)
            except ValueError:
                season = None
        
        # Import statcast functions
        sys.path.insert(0, str(Config.ROOT_DIR / "src"))
        from scrape_savant import fetch_pitcher_statcast, fetch_batter_statcast, lookup_batter_id
        from datetime import datetime
        import pandas as pd
        import numpy as np
        
        # Get player ID
        try:
            player_id = lookup_batter_id(player_name)
        except Exception as e:
            return jsonify({"error": f"Could not find player ID for '{player_name}': {str(e)}"}), 404
        
        # Calculate date range
        if view_type == 'career':
            # Get all available data
            current_year = datetime.now().year
            start_date = "2008-03-01"
            end_date = f"{current_year}-11-30"
            filter_by_season = False
        elif season:
            start_date = f"{season}-03-01"
            end_date = f"{season}-11-30"
            filter_by_season = True
        else:
            # Default to current season
            current_year = datetime.now().year
            start_date = f"{current_year}-03-01"
            end_date = f"{current_year}-11-30"
            filter_by_season = True
            season = current_year
        
        # Fetch statcast data
        try:
            if player_type == 'pitcher':
                df = fetch_pitcher_statcast(player_id, start_date, end_date)
                velocity_column = 'release_speed'
            else:
                df = fetch_batter_statcast(player_id, start_date, end_date)
                velocity_column = 'launch_speed'
        except Exception as e:
            return jsonify({"error": f"Error fetching statcast data: {str(e)}"}), 500
        
        if df is None or df.empty:
            return jsonify({
                "error": f"No statcast data found for {player_name}",
                "player": player_name,
                "trends": []
            }), 200
        
        # Filter by season if specified
        if filter_by_season and season:
            year_column = None
            for col_name in ['game_year', 'year', 'Year', 'season']:
                if col_name in df.columns:
                    year_column = col_name
                    break
            
            if year_column:
                if not pd.api.types.is_integer_dtype(df[year_column]):
                    df[year_column] = pd.to_numeric(df[year_column], errors='coerce')
                df = df[
                    (df[year_column].notna()) & 
                    (df[year_column] == int(season))
                ]
            else:
                date_column = None
                for col_name in ['game_date', 'gameDate', 'date', 'Date', 'game_day']:
                    if col_name in df.columns:
                        date_column = col_name
                        break
                
                if date_column:
                    if not pd.api.types.is_datetime64_any_dtype(df[date_column]):
                        df[date_column] = pd.to_datetime(df[date_column], errors='coerce')
                    
                    season_start = pd.to_datetime(f"{season}-03-01")
                    season_end = pd.to_datetime(f"{season}-11-30")
                    
                    df = df[df[date_column].notna()]
                    df = df[
                        (df[date_column] >= season_start) & 
                        (df[date_column] <= season_end)
                    ]
        
        # Filter by pitch type if specified (pitchers only)
        if pitch_type and player_type == 'pitcher' and 'pitch_type' in df.columns:
            df = df[df['pitch_type'] == pitch_type]
        
        # Filter out rows without velocity data
        if velocity_column not in df.columns:
            return jsonify({
                "error": f"Velocity data ({velocity_column}) not available",
                "player": player_name,
                "trends": []
            }), 200
        
        df = df[df[velocity_column].notna()]
        
        if df.empty:
            return jsonify({
                "error": "No valid velocity data found",
                "player": player_name,
                "trends": []
            }), 200
        
        # Prepare trends data based on view type
        trends = []
        
        if view_type == 'game':
            # Game-level fatigue: group by game and pitch number
            if 'game_date' in df.columns and 'pitch_number' in df.columns:
                # Get game_date column name variations
                date_col = 'game_date'
                if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
                    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                
                # Filter by specific game date if provided
                if game_date:
                    try:
                        filter_date = pd.to_datetime(game_date)
                        df = df[df[date_col].dt.date == filter_date.date()]
                    except Exception:
                        pass  # If date parsing fails, don't filter
                
                df = df[df[date_col].notna() & df['pitch_number'].notna()]
                
                for _, row in df.iterrows():
                    game_date_val = row[date_col]
                    if pd.notna(game_date_val):
                        if isinstance(game_date_val, pd.Timestamp):
                            game_date_str = game_date_val.strftime('%Y-%m-%d')
                        else:
                            game_date_str = str(game_date_val)
                    else:
                        game_date_str = 'Unknown'
                    
                    trends.append({
                        'game_date': game_date_str,
                        'pitch_number': int(row['pitch_number']) if pd.notna(row['pitch_number']) else None,
                        'velocity': float(row[velocity_column]) if pd.notna(row[velocity_column]) else None,
                        'season': int(row['game_year']) if 'game_year' in row and pd.notna(row.get('game_year')) else season
                    })
        elif view_type == 'season':
            # Season trends: group by game date
            if 'game_date' in df.columns:
                date_col = 'game_date'
                if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
                    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                
                df = df[df[date_col].notna()]
                
                for game_date, group in df.groupby(date_col):
                    velocities = group[velocity_column].dropna()
                    if len(velocities) > 0:
                        if isinstance(game_date, pd.Timestamp):
                            game_date_str = game_date.strftime('%Y-%m-%d')
                        else:
                            game_date_str = str(game_date)
                        
                        trends.append({
                            'game_date': game_date_str,
                            'velocity': float(velocities.mean()),
                            'season': int(group['game_year'].iloc[0]) if 'game_year' in group.columns and pd.notna(group['game_year'].iloc[0]) else season
                        })
        else:
            # Career trends: group by season
            year_column = None
            for col_name in ['game_year', 'year', 'Year', 'season']:
                if col_name in df.columns:
                    year_column = col_name
                    break
            
            if year_column:
                if not pd.api.types.is_integer_dtype(df[year_column]):
                    df[year_column] = pd.to_numeric(df[year_column], errors='coerce')
                df = df[df[year_column].notna()]
                
                for year, group in df.groupby(year_column):
                    velocities = group[velocity_column].dropna()
                    if len(velocities) > 0:
                        trends.append({
                            'season': int(year),
                            'velocity': float(velocities.mean()),
                            'game_date': None
                        })
            else:
                # Fallback: try to extract year from game_date
                if 'game_date' in df.columns:
                    date_col = 'game_date'
                    if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
                        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                    df = df[df[date_col].notna()]
                    df['year'] = df[date_col].dt.year
                    
                    for year, group in df.groupby('year'):
                        velocities = group[velocity_column].dropna()
                        if len(velocities) > 0:
                            trends.append({
                                'season': int(year),
                                'velocity': float(velocities.mean()),
                                'game_date': None
                            })
        
        # Sort trends appropriately
        if view_type == 'career':
            trends.sort(key=lambda x: x['season'] if x['season'] else 0)
        elif view_type == 'season':
            trends.sort(key=lambda x: x['game_date'] if x['game_date'] else '')
        else:
            # Game-level: sort by game_date then pitch_number
            trends.sort(key=lambda x: (x['game_date'] if x['game_date'] else '', x['pitch_number'] if x['pitch_number'] is not None else 0))
        
        return jsonify({
            'player': player_name,
            'player_type': player_type,
            'view_type': view_type,
            'season': season,
            'pitch_type': pitch_type,
            'trends': trends
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@bp.route('/visuals/swing-decision-matrix', methods=['GET'])
@bp.route('/visuals/zone-contact-rates', methods=['GET'])
def api_visuals_zone_contact_rates():
    """Get strike zone contact and swing rate data for a batter"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        batter_name = request.args.get('batter', '').strip()
        if not batter_name:
            return jsonify({"error": "Batter name is required"}), 400
        
        season = request.args.get('season', '').strip() or None
        if season:
            try:
                season = int(season)
            except ValueError:
                season = None
        
        # Import statcast functions
        sys.path.insert(0, str(Config.ROOT_DIR / "src"))
        from scrape_savant import fetch_batter_statcast, lookup_batter_id
        from datetime import datetime
        import pandas as pd
        import numpy as np
        
        # Get batter ID
        try:
            batter_id = lookup_batter_id(batter_name)
        except Exception as e:
            return jsonify({"error": f"Could not find batter ID for '{batter_name}': {str(e)}"}), 404
        
        # Calculate date range
        if season:
            start_date = f"{season}-03-01"
            end_date = f"{season}-11-30"
            filter_by_season = True
        else:
            current_year = datetime.now().year
            start_date = "2008-03-01"
            end_date = f"{current_year}-11-30"
            filter_by_season = False
        
        # Fetch statcast data
        try:
            df = fetch_batter_statcast(batter_id, start_date, end_date)
        except Exception as e:
            return jsonify({"error": f"Error fetching statcast data: {str(e)}"}), 500
        
        if df is None or df.empty:
            return jsonify({
                "error": f"No statcast data found for {batter_name}",
                "batter": batter_name,
                "data": {}
            }), 200
        
        # Filter by season if specified
        if filter_by_season:
            year_column = None
            for col_name in ['game_year', 'year', 'Year', 'season']:
                if col_name in df.columns:
                    year_column = col_name
                    break
            
            if year_column:
                if not pd.api.types.is_integer_dtype(df[year_column]):
                    df[year_column] = pd.to_numeric(df[year_column], errors='coerce')
                df = df[
                    (df[year_column].notna()) & 
                    (df[year_column] == int(season))
                ]
            else:
                date_column = None
                for col_name in ['game_date', 'gameDate', 'date', 'Date', 'game_day']:
                    if col_name in df.columns:
                        date_column = col_name
                        break
                
                if date_column:
                    if not pd.api.types.is_datetime64_any_dtype(df[date_column]):
                        df[date_column] = pd.to_datetime(df[date_column], errors='coerce')
                    
                    season_start = pd.to_datetime(f"{season}-03-01")
                    season_end = pd.to_datetime(f"{season}-11-30")
                    
                    df = df[df[date_column].notna()]
                    df = df[
                        (df[date_column] >= season_start) & 
                        (df[date_column] <= season_end)
                    ]
            
            if df.empty:
                return jsonify({
                    "error": f"No statcast data found for {batter_name} for season {season}",
                    "batter": batter_name,
                    "data": {}
                }), 200
        
        # Filter out rows without location data
        if 'plate_x' not in df.columns or 'plate_z' not in df.columns:
            return jsonify({
                "error": "Location data (plate_x, plate_z) not available",
                "batter": batter_name,
                "data": {}
            }), 200
        
        df = df[df['plate_x'].notna() & df['plate_z'].notna()]
        if df.empty:
            return jsonify({
                "error": "No valid location data found",
                "batter": batter_name,
                "data": {}
            }), 200
        
        # Calculate swing and contact indicators
        desc = df['description'].astype(str).str.lower()
        df['is_swing'] = desc.isin([
            'foul', 'foul_tip', 'swinging_strike', 'swinging_strike_blocked', 
            'missed_bunt', 'foul_bunt', 'hit_into_play'
        ])
        
        # Contact made (swing that resulted in contact, not a whiff)
        df['is_contact'] = desc.isin([
            'foul', 'foul_tip', 'foul_bunt', 'hit_into_play'
        ])
        
        # Whiff (swing and miss)
        df['is_whiff'] = desc.isin([
            'swinging_strike', 'swinging_strike_blocked', 'missed_bunt'
        ])
        
        # Quality of contact metrics
        df['is_hard_hit'] = False
        if 'launch_speed' in df.columns:
            df['is_hard_hit'] = df['launch_speed'] >= 95
        
        df['is_barrel'] = False
        if 'launch_speed' in df.columns and 'launch_angle' in df.columns:
            # Barrel definition: combination of launch speed and angle
            # Simplified: exit velo >= 98 and launch angle between 8-50 degrees
            # or exit velo >= 95 and launch angle 26-30 degrees
            launch_speed = df['launch_speed']
            launch_angle = df['launch_angle']
            df['is_barrel'] = (
                ((launch_speed >= 98) & (launch_angle >= 8) & (launch_angle <= 50)) |
                ((launch_speed >= 95) & (launch_angle >= 26) & (launch_angle <= 30))
            )
        
        # Create grid for strike zone (12x12 grid for better resolution)
        grid_size = 12
        x_min, x_max = -2.0, 2.0
        z_min, z_max = 0.5, 4.5
        
        x_bins = np.linspace(x_min, x_max, grid_size + 1)
        z_bins = np.linspace(z_min, z_max, grid_size + 1)
        
        # Bin the data
        df['x_bin'] = pd.cut(df['plate_x'], bins=x_bins, labels=False)
        df['z_bin'] = pd.cut(df['plate_z'], bins=z_bins, labels=False)
        
        # Calculate metrics for each grid cell
        grid_data = []
        for x_idx in range(grid_size):
            for z_idx in range(grid_size):
                cell_data = df[
                    (df['x_bin'] == x_idx) & 
                    (df['z_bin'] == z_idx)
                ]
                
                total_pitches = len(cell_data)
                
                if total_pitches == 0:
                    continue
                
                # Calculate rates
                swings = cell_data['is_swing'].sum()
                contacts = cell_data['is_contact'].sum()
                whiffs = cell_data['is_whiff'].sum()
                
                # Contact rate (contacts / swings)
                contact_rate = (contacts / swings * 100) if swings > 0 else None
                
                # Swing rate (swings / total pitches)
                swing_rate = (swings / total_pitches * 100) if total_pitches > 0 else 0.0
                
                # Whiff rate (whiffs / swings)
                whiff_rate = (whiffs / swings * 100) if swings > 0 else None
                
                # Quality of contact (only for batted balls)
                batted_balls = cell_data[cell_data['is_contact']]
                hard_hit_rate = None
                barrel_rate = None
                avg_exit_velo = None
                avg_launch_angle = None
                
                if len(batted_balls) > 0:
                    hard_hits = batted_balls['is_hard_hit'].sum()
                    hard_hit_rate = (hard_hits / len(batted_balls) * 100) if len(batted_balls) > 0 else None
                    
                    barrels = batted_balls['is_barrel'].sum()
                    barrel_rate = (barrels / len(batted_balls) * 100) if len(batted_balls) > 0 else None
                    
                    if 'launch_speed' in batted_balls.columns:
                        ev_values = batted_balls['launch_speed'].dropna()
                        if len(ev_values) > 0:
                            avg_exit_velo = float(ev_values.mean())
                    
                    if 'launch_angle' in batted_balls.columns:
                        la_values = batted_balls['launch_angle'].dropna()
                        if len(la_values) > 0:
                            avg_launch_angle = float(la_values.mean())
                
                # Calculate center coordinates of the cell
                x_center = (x_bins[x_idx] + x_bins[x_idx + 1]) / 2
                z_center = (z_bins[z_idx] + z_bins[z_idx + 1]) / 2
                
                grid_data.append({
                    'x': x_idx,
                    'y': grid_size - 1 - z_idx,  # Flip y-axis for display
                    'x_center': float(x_center),
                    'z_center': float(z_center),
                    'total_pitches': total_pitches,
                    'swings': int(swings),
                    'contacts': int(contacts),
                    'whiffs': int(whiffs),
                    'contact_rate': contact_rate,
                    'swing_rate': swing_rate,
                    'whiff_rate': whiff_rate,
                    'hard_hit_rate': hard_hit_rate,
                    'barrel_rate': barrel_rate,
                    'avg_exit_velo': avg_exit_velo,
                    'avg_launch_angle': avg_launch_angle
                })
        
        # Filter out cells with no data
        grid_data = [cell for cell in grid_data if cell['total_pitches'] > 0]
        
        if not grid_data:
            return jsonify({
                "error": f"No contact rate data available for {batter_name}",
                "batter": batter_name,
                "data": {}
            }), 200
        
        # Get batter handedness
        batter_hand = 'R'  # Default
        if 'stand' in df.columns:
            stand_values = df['stand'].dropna()
            if len(stand_values) > 0:
                batter_hand = str(stand_values.mode().iloc[0]) if len(stand_values.mode()) > 0 else 'R'
        
        return jsonify({
            'batter': batter_name,
            'batter_hand': batter_hand,
            'season': season,
            'total_pitches': len(df),
            'grid': grid_data,
            'grid_size': grid_size,
            'x_range': [float(x_min), float(x_max)],
            'z_range': [float(z_min), float(z_max)]
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@bp.route('/visuals/plate-discipline-matrix', methods=['GET'])
@bp.route('/visuals/expected-stats-comparison', methods=['GET'])
def api_visuals_expected_stats_comparison():
    """Get expected stats comparison data: xwOBA, xBA, xSLG, xISO vs actual with confidence intervals"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        batter_name = request.args.get('player', '').strip()
        if not batter_name:
            return jsonify({"error": "Player name is required"}), 400
        
        season = request.args.get('season', '').strip() or None
        if season:
            try:
                season = int(season)
            except ValueError:
                season = None
        
        pitch_type = request.args.get('pitch_type', '').strip() or None
        pitcher_hand = request.args.get('pitcher_hand', '').strip() or None
        count = request.args.get('count', '').strip() or None
        
        # Import statcast functions
        sys.path.insert(0, str(Config.ROOT_DIR / "src"))
        from scrape_savant import fetch_batter_statcast, lookup_batter_id
        from datetime import datetime
        import pandas as pd
        import numpy as np
        
        # Get batter ID
        try:
            batter_id = lookup_batter_id(batter_name)
        except Exception as e:
            return jsonify({"error": f"Could not find player ID for '{batter_name}': {str(e)}"}), 404
        
        # Calculate date range
        if season:
            start_date = f"{season}-03-01"
            end_date = f"{season}-11-30"
        else:
            # Get last 3 years of data
            current_year = datetime.now().year
            start_date = f"{current_year - 3}-03-01"
            end_date = f"{current_year}-11-30"
        
        # Fetch statcast data
        df = fetch_batter_statcast(batter_id, start_date, end_date)
        
        if df is None or df.empty:
            return jsonify({
                "error": f"No statcast data available for {batter_name}",
                "player": batter_name,
                "stats": {}
            }), 200
        
        # Filter by season if specified
        if season and 'game_year' in df.columns:
            df = df[df['game_year'] == season]
        
        # Apply filters
        if pitch_type:
            df = df[df['pitch_type'] == pitch_type]
        if pitcher_hand and 'p_throws' in df.columns:
            df = df[df['p_throws'] == pitcher_hand]
        if count and 'balls' in df.columns and 'strikes' in df.columns:
            balls, strikes = map(int, count.split('-'))
            df = df[(df['balls'] == balls) & (df['strikes'] == strikes)]
        
        if df.empty:
            return jsonify({
                "error": f"No data available for {batter_name} with selected filters",
                "player": batter_name,
                "stats": {}
            }), 200
        
        # Calculate expected and actual stats
        stats_result = calculate_expected_stats_comparison(df, batter_name)
        
        return jsonify(stats_result)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@bp.route('/visuals/pitch-mix-analysis', methods=['GET'])
@bp.route('/visuals/count-performance', methods=['GET'])

def api_visuals_count_performance():

    """Get batter performance breakdown by count"""

    if not csv_loader:

        return jsonify({"error": "CSV data loader not available"}), 500

    

    try:

        batter_name = request.args.get('batter', '').strip()

        if not batter_name:

            return jsonify({"error": "Batter name is required"}), 400

        

        season = request.args.get('season', '').strip() or None

        if season:

            try:

                season = int(season)

            except ValueError:

                season = None

        

        # Import statcast functions

        sys.path.insert(0, str(Config.ROOT_DIR / "src"))

        from scrape_savant import fetch_batter_statcast, lookup_batter_id

        from datetime import datetime

        import pandas as pd

        import numpy as np

        

        # Get batter ID

        try:

            batter_id = lookup_batter_id(batter_name)

        except Exception as e:

            return jsonify({"error": f"Could not find batter ID for '{batter_name}': {str(e)}"}), 404

        

        # Calculate date range

        if season:

            start_date = f"{season}-03-01"

            end_date = f"{season}-11-30"

            filter_by_season = True

        else:

            current_year = datetime.now().year

            start_date = "2008-03-01"

            end_date = f"{current_year}-11-30"

            filter_by_season = False

        

        # Fetch statcast data

        try:

            df = fetch_batter_statcast(batter_id, start_date, end_date)

        except Exception as e:

            return jsonify({"error": f"Error fetching statcast data: {str(e)}"}), 500

        

        if df is None or df.empty:

            return jsonify({

                "error": f"No statcast data found for {batter_name}",

                "batter": batter_name,

                "data": {}

            }), 200

        

        # Filter by season if specified

        if filter_by_season:

            year_column = None

            for col_name in ['game_year', 'year', 'Year', 'season']:

                if col_name in df.columns:

                    year_column = col_name

                    break

            

            if year_column:

                if not pd.api.types.is_integer_dtype(df[year_column]):

                    df[year_column] = pd.to_numeric(df[year_column], errors='coerce')

                df = df[

                    (df[year_column].notna()) & 

                    (df[year_column] == int(season))

                ]

            else:

                date_column = None

                for col_name in ['game_date', 'gameDate', 'date', 'Date', 'game_day']:

                    if col_name in df.columns:

                        date_column = col_name

                        break

                

                if date_column:

                    if not pd.api.types.is_datetime64_any_dtype(df[date_column]):

                        df[date_column] = pd.to_datetime(df[date_column], errors='coerce')

                    

                    season_start = pd.to_datetime(f"{season}-03-01")

                    season_end = pd.to_datetime(f"{season}-11-30")

                    

                    df = df[df[date_column].notna()]

                    df = df[

                        (df[date_column] >= season_start) & 

                        (df[date_column] <= season_end)

                    ]

            

            if df.empty:

                return jsonify({

                    "error": f"No statcast data found for {batter_name} for season {season}",

                    "batter": batter_name,

                    "data": {}

                }), 200

        

        # Filter out rows without necessary data

        df = df.dropna(subset=['balls', 'strikes'])

        if df.empty:

            return jsonify({

                "error": "No valid pitch data available",

                "batter": batter_name,

                "data": {}

            }), 200

        

        # Create count column

        df['count'] = df['balls'].astype(int).astype(str) + '-' + df['strikes'].astype(int).astype(str)

        

        # Define count order

        COUNT_ORDER = ['0-0', '1-0', '0-1', '1-1', '2-0', '2-1', '1-2', '2-2', '3-0', '3-1', '3-2', '0-2']

        df = df[df['count'].isin(COUNT_ORDER)]

        

        # Calculate outcome metrics

        desc = df['description'].astype(str).str.lower()

        

        # Use events column if available (this is the actual at-bat outcome)

        # Otherwise fall back to description

        if 'events' in df.columns:

            events = df['events'].astype(str).str.lower()

            # Hits from events

            df['is_hit'] = events.isin(['single', 'double', 'triple', 'home_run'])

            # Outs from events (field outs, strikeouts, etc.)

            df['is_out'] = events.isin([

                'strikeout', 'strikeout_double_play', 'field_out', 'force_out', 

                'grounded_into_double_play', 'double_play', 'triple_play',

                'fielders_choice', 'fielders_choice_out', 'sac_fly', 'sac_fly_double_play',

                'sac_bunt', 'sac_bunt_double_play', 'bunt_groundout', 'bunt_popout'

            ])

            # Walks from events

            df['is_walk'] = events.isin(['walk', 'intent_walk', 'hit_by_pitch'])

            # Strikeouts from events

            df['is_strikeout'] = events.isin(['strikeout', 'strikeout_double_play'])

            # PA ending indicator

            df['is_pa_ending'] = events.notna() & (events != 'nan') & (events != '')

        else:

            # Fallback to description if events column not available

            df['is_hit'] = desc.isin(['single', 'double', 'triple', 'home_run'])

            df['is_out'] = desc.isin(['strikeout', 'strikeout_double_play', 'field_out', 'force_out', 'grounded_into_double_play', 'double_play', 'triple_play'])

            df['is_walk'] = desc.isin(['walk', 'intent_walk', 'hit_by_pitch'])

            df['is_strikeout'] = desc.isin(['strikeout', 'strikeout_double_play'])

            df['is_pa_ending'] = (

                df['is_hit'] | df['is_out'] | df['is_walk'] | 

                desc.str.contains('hit_into_play', na=False)

            )

        

        # Swing and whiff rates (these are pitch-level, so use description)

        df['is_swing'] = desc.isin(['foul', 'foul_tip', 'swinging_strike', 'swinging_strike_blocked', 'missed_bunt', 'foul_bunt', 'hit_into_play'])

        df['is_whiff'] = desc.isin(['swinging_strike', 'swinging_strike_blocked', 'missed_bunt'])

        

        # Helper function to calculate metrics for a count

        def calculate_count_metrics(count_df):

            total_pitches = len(count_df)

            if total_pitches == 0:

                return {}

            

            # For at-bat outcomes (hits, outs, walks), only count pitches where at-bat ended

            # (i.e., where events is not null, or is_pa_ending is true)

            if 'events' in count_df.columns:

                # Filter to only pitches where events occurred (at-bat ending pitches)

                pa_df = count_df[count_df['events'].notna() & (count_df['events'].astype(str) != 'nan') & (count_df['events'].astype(str) != '')]

            else:

                # Fallback: use is_pa_ending flag

                pa_df = count_df[count_df['is_pa_ending']]

            

            # Plate appearances ending at this count

            pa_ending = len(pa_df)

            

            # Hits, walks, strikeouts (from at-bat ending pitches only)

            hits = pa_df['is_hit'].sum() if len(pa_df) > 0 else 0

            walks = pa_df['is_walk'].sum() if len(pa_df) > 0 else 0

            strikeouts = pa_df['is_strikeout'].sum() if len(pa_df) > 0 else 0

            outs = pa_df['is_out'].sum() if len(pa_df) > 0 else 0

            

            # Swing and whiff rates

            swings = count_df['is_swing'].sum()

            whiffs = count_df['is_whiff'].sum()

            

            # Batting average (hits / at-bats) - standard format (.XXX)

            # At-bats = hits + outs (excludes walks, hit-by-pitch, sacrifices)

            # We need to make sure we're only counting actual at-bats

            at_bats = hits + outs

            # Only calculate if we have actual at-bats

            if at_bats > 0:

                batting_avg = float(hits / at_bats)

            else:

                batting_avg = None

            

            # On-base percentage (hits + walks) / PA

            obp = ((hits + walks) / pa_ending * 100) if pa_ending > 0 else None

            

            # Strikeout rate

            k_rate = (strikeouts / pa_ending * 100) if pa_ending > 0 else None

            

            # Walk rate

            bb_rate = (walks / pa_ending * 100) if pa_ending > 0 else None

            

            # Swing rate

            swing_rate = (swings / total_pitches * 100) if total_pitches > 0 else 0.0

            

            # Whiff rate

            whiff_rate = (whiffs / swings * 100) if swings > 0 else None

            

            # xwOBA if available

            xwoba = None

            if 'estimated_woba_using_speedangle' in count_df.columns:

                xwoba_values = count_df['estimated_woba_using_speedangle'].dropna()

                if len(xwoba_values) > 0:

                    xwoba = float(xwoba_values.mean())

            elif 'woba_value' in count_df.columns:

                woba_values = count_df['woba_value'].dropna()

                if len(woba_values) > 0:

                    xwoba = float(woba_values.mean())

            

            # Average exit velocity

            avg_ev = None

            if 'launch_speed' in count_df.columns:

                ev_values = count_df['launch_speed'].dropna()

                if len(ev_values) > 0:

                    avg_ev = float(ev_values.mean())

            

            # Hard hit rate (95+ mph)

            hard_hit_rate = None

            if 'launch_speed' in count_df.columns:

                ev_values = count_df['launch_speed'].dropna()

                hard_hits = (ev_values >= 95).sum()

                hard_hit_rate = (hard_hits / len(ev_values) * 100) if len(ev_values) > 0 else None

            

            # Pitch types seen

            pitch_types = {}

            if 'pitch_type' in count_df.columns:

                pitch_type_counts = count_df['pitch_type'].value_counts()

                total_seen = pitch_type_counts.sum()

                for pt, count in pitch_type_counts.items():

                    if pd.notna(pt):

                        pitch_types[str(pt)] = {

                            'count': int(count),

                            'percentage': float(count / total_seen * 100) if total_seen > 0 else 0.0

                        }

            

            return {

                'total_pitches': total_pitches,

                'pa_ending': int(pa_ending),

                'hits': int(hits),

                'walks': int(walks),

                'strikeouts': int(strikeouts),

                'outs': int(outs),

                'at_bats': int(at_bats),

                'batting_avg': batting_avg,

                'obp': obp,

                'k_rate': k_rate,

                'bb_rate': bb_rate,

                'swing_rate': swing_rate,

                'whiff_rate': whiff_rate,

                'xwoba': xwoba,

                'avg_ev': avg_ev,

                'hard_hit_rate': hard_hit_rate,

                'pitch_types_seen': pitch_types

            }

        

        # Calculate metrics for each count

        count_data = {}

        for count in COUNT_ORDER:

            count_df = df[df['count'] == count]

            if len(count_df) == 0:

                continue

            count_data[count] = calculate_count_metrics(count_df)

        

        # Get batter handedness

        batter_hand = 'R'  # Default

        if 'stand' in df.columns:

            stand_values = df['stand'].dropna()

            if len(stand_values) > 0:

                batter_hand = str(stand_values.mode().iloc[0]) if len(stand_values.mode()) > 0 else 'R'

        

        # Overall stats

        overall_metrics = calculate_count_metrics(df)

        

        return jsonify({

            'batter': batter_name,

            'batter_hand': batter_hand,

            'season': season,

            'total_pitches': len(df),

            'overall': overall_metrics,

            'by_count': count_data

        })

    except Exception as e:

        import traceback

        traceback.print_exc()

        return jsonify({"error": str(e)}), 500


@bp.route('/visuals/swing-decision-matrix', methods=['GET'])

def api_visuals_swing_decision_matrix():

    """Get swing decision matrix data: run values, optimal decision zones, chase rates, and decision quality metrics"""

    if not csv_loader:

        return jsonify({"error": "CSV data loader not available"}), 500

    

    try:

        batter_name = request.args.get('batter', '').strip()

        if not batter_name:

            return jsonify({"error": "Batter name is required"}), 400

        

        season = request.args.get('season', '').strip() or None

        if season:

            try:

                season = int(season)

            except ValueError:

                season = None

        

        count = request.args.get('count', '').strip() or None

        

        # Import statcast functions

        sys.path.insert(0, str(Config.ROOT_DIR / "src"))

        from scrape_savant import fetch_batter_statcast, lookup_batter_id

        from datetime import datetime

        import pandas as pd

        import numpy as np

        

        # Get batter ID

        try:

            batter_id = lookup_batter_id(batter_name)

        except Exception as e:

            return jsonify({"error": f"Could not find batter ID for '{batter_name}': {str(e)}"}), 404

        

        # Calculate date range

        if season:

            start_date = f"{season}-03-01"

            end_date = f"{season}-11-30"

            filter_by_season = True

        else:

            current_year = datetime.now().year

            start_date = "2008-03-01"

            end_date = f"{current_year}-11-30"

            filter_by_season = False

        

        # Fetch statcast data

        try:

            df = fetch_batter_statcast(batter_id, start_date, end_date)

        except Exception as e:

            return jsonify({"error": f"Error fetching statcast data: {str(e)}"}), 500

        

        if df is None or df.empty:

            return jsonify({

                "error": f"No statcast data found for {batter_name}",

                "batter": batter_name,

                "data": {}

            }), 200

        

        # Filter by season if specified

        if filter_by_season:

            year_column = None

            for col_name in ['game_year', 'year', 'Year', 'season']:

                if col_name in df.columns:

                    year_column = col_name

                    break

            

            if year_column:

                if not pd.api.types.is_integer_dtype(df[year_column]):

                    df[year_column] = pd.to_numeric(df[year_column], errors='coerce')

                df = df[

                    (df[year_column].notna()) & 

                    (df[year_column] == int(season))

                ]

            else:

                date_column = None

                for col_name in ['game_date', 'gameDate', 'date', 'Date', 'game_day']:

                    if col_name in df.columns:

                        date_column = col_name

                        break

                

                if date_column:

                    if not pd.api.types.is_datetime64_any_dtype(df[date_column]):

                        df[date_column] = pd.to_datetime(df[date_column], errors='coerce')

                    

                    season_start = pd.to_datetime(f"{season}-03-01")

                    season_end = pd.to_datetime(f"{season}-11-30")

                    

                    df = df[df[date_column].notna()]

                    df = df[

                        (df[date_column] >= season_start) & 

                        (df[date_column] <= season_end)

                    ]

            

            if df.empty:

                return jsonify({

                    "error": f"No statcast data found for {batter_name} for season {season}",

                    "batter": batter_name,

                    "data": {}

                }), 200

        

        # Filter by count if specified

        if count:

            if 'balls' in df.columns and 'strikes' in df.columns:

                b, s = count.split('-')

                df = df[(df['balls'] == int(b)) & (df['strikes'] == int(s))]

        

        # Filter out rows without necessary data

        df = df.dropna(subset=['pitch_type'])

        if df.empty:

            return jsonify({

                "error": "No valid pitch data available",

                "batter": batter_name,

                "data": {}

            }), 200

        

        # Calculate swing, contact, and zone indicators

        desc = df['description'].astype(str).str.lower()

        df['is_swing'] = desc.isin([

            'foul', 'foul_tip', 'swinging_strike', 'swinging_strike_blocked', 

            'missed_bunt', 'foul_bunt', 'hit_into_play'

        ])

        

        df['is_take'] = ~df['is_swing']

        

        df['is_contact'] = desc.isin([

            'foul', 'foul_tip', 'foul_bunt', 'hit_into_play'

        ])

        

        # Determine strike zone

        df['is_in_zone'] = False

        if 'zone' in df.columns:

            df['is_in_zone'] = df['zone'].between(1, 9, inclusive='both')

            if 'plate_x' in df.columns and 'plate_z' in df.columns:

                zone_na_mask = df['zone'].isna()

                if zone_na_mask.any():

                    df.loc[zone_na_mask, 'is_in_zone'] = (

                        (df.loc[zone_na_mask, 'plate_x'].abs() <= 0.855) &

                        (df.loc[zone_na_mask, 'plate_z'] >= 1.5) &

                        (df.loc[zone_na_mask, 'plate_z'] <= 3.5)

                    )

        elif 'plate_x' in df.columns and 'plate_z' in df.columns:

            df['is_in_zone'] = (

                (df['plate_x'].abs() <= 0.855) &

                (df['plate_z'] >= 1.5) &

                (df['plate_z'] <= 3.5)

            )

        

        # Chase = swing on pitch outside the zone

        df['is_chase'] = df['is_swing'] & ~df['is_in_zone']

        

        # Assign zone numbers (1-9) based on plate_x and plate_z

        def assign_zone(row):

            if pd.isna(row.get('zone')):

                # Estimate zone from plate_x and plate_z

                if 'plate_x' not in row or 'plate_z' not in row:

                    return None

                if pd.isna(row['plate_x']) or pd.isna(row['plate_z']):

                    return None

                

                x = row['plate_x']

                z = row['plate_z']

                

                # Zone boundaries (approximate)

                # Horizontal: -0.855 to 0.855 (3 zones)

                # Vertical: 1.5 to 3.5 (3 zones)

                if x < -0.285:  # Left column

                    col = 0

                elif x < 0.285:  # Middle column

                    col = 1

                else:  # Right column

                    col = 2

                

                if z < 2.17:  # Bottom row

                    row_num = 2

                elif z < 2.83:  # Middle row

                    row_num = 1

                else:  # Top row

                    row_num = 0

                

                return row_num * 3 + col + 1

            else:

                zone_val = row['zone']

                if pd.isna(zone_val) or zone_val < 1 or zone_val > 9:

                    return None

                return int(zone_val)

        

        df['zone_num'] = df.apply(assign_zone, axis=1)

        df = df[df['zone_num'].notna()]

        

        if df.empty:

            return jsonify({

                "error": "No valid zone data available",

                "batter": batter_name,

                "data": {}

            }), 200

        

        # Run expectancy matrix (simplified - approximate values)

        # Based on count situation

        run_expectancy = {

            '0-0': 0.475, '1-0': 0.525, '0-1': 0.260,

            '2-0': 0.575, '1-1': 0.350, '0-2': 0.100,

            '3-0': 0.625, '2-1': 0.425, '1-2': 0.175,

            '3-1': 0.550, '2-2': 0.275, '3-2': 0.300

        }

        

        # Calculate run values for each pitch

        def calculate_run_value(row):

            # Get count

            b = int(row.get('balls', 0)) if pd.notna(row.get('balls')) else 0

            s = int(row.get('strikes', 0)) if pd.notna(row.get('strikes')) else 0

            count_str = f"{b}-{s}"

            

            base_re = run_expectancy.get(count_str, 0.35)

            

            # Calculate outcome value

            outcome = row['description'].lower()

            

            # Simplified run values by outcome

            if 'hit_into_play' in outcome:

                # Calculate from wOBA or estimate

                if 'woba_value' in row and pd.notna(row['woba_value']):

                    rv = float(row['woba_value']) - base_re

                elif 'estimated_woba_using_speedangle' in row and pd.notna(row['estimated_woba_using_speedangle']):

                    rv = float(row['estimated_woba_using_speedangle']) - base_re

                else:

                    # Estimate based on outcome

                    if 'single' in outcome or 'double' in outcome or 'triple' in outcome or 'home_run' in outcome:

                        rv = 0.1  # Positive value for hits

                    else:

                        rv = -0.05  # Out

                return rv

            elif 'ball' in outcome:

                # Walk increases run expectancy

                next_b = min(3, b + 1)

                if next_b == 4:

                    rv = 0.3  # Walk

                else:

                    next_count = f"{next_b}-{s}"

                    next_re = run_expectancy.get(next_count, 0.35)

                    rv = next_re - base_re

                return rv

            elif 'called_strike' in outcome:

                # Strike reduces run expectancy

                next_s = min(2, s + 1)

                if next_s == 3:

                    rv = -0.25  # Strikeout

                else:

                    next_count = f"{b}-{next_s}"

                    next_re = run_expectancy.get(next_count, 0.35)

                    rv = next_re - base_re

                return rv

            elif 'swinging_strike' in outcome:

                next_s = min(2, s + 1)

                if next_s == 3:

                    rv = -0.25  # Strikeout

                else:

                    next_count = f"{b}-{next_s}"

                    next_re = run_expectancy.get(next_count, 0.35)

                    rv = next_re - base_re

                return rv

            elif 'foul' in outcome:

                # Foul ball with 2 strikes has no effect, otherwise reduces RE slightly

                if s == 2:

                    rv = 0.0  # No change

                else:

                    next_s = min(2, s + 1)

                    next_count = f"{b}-{next_s}"

                    next_re = run_expectancy.get(next_count, 0.35)

                    rv = next_re - base_re

                return rv

            else:

                return 0.0

        

        df['run_value'] = df.apply(calculate_run_value, axis=1)

        

        # Calculate metrics by zone

        zone_data = []

        for zone_num in range(1, 10):

            zone_df = df[df['zone_num'] == zone_num]

            

            if len(zone_df) == 0:

                continue

            

            total_pitches = len(zone_df)

            swings = zone_df['is_swing'].sum()

            takes = zone_df['is_take'].sum()

            chases = zone_df['is_chase'].sum()

            in_zone = zone_df['is_in_zone'].sum()

            

            swing_rate = (swings / total_pitches * 100) if total_pitches > 0 else 0.0

            chase_rate = (chases / total_pitches * 100) if total_pitches > 0 else 0.0

            

            # Calculate average run value for swings and takes in this zone

            swing_rv = zone_df[zone_df['is_swing']]['run_value'].mean() if swings > 0 else 0.0

            take_rv = zone_df[zone_df['is_take']]['run_value'].mean() if takes > 0 else 0.0

            

            # Optimal decision: swing if swing_rv > take_rv

            is_optimal_swing = swing_rv > take_rv if (swings > 0 and takes > 0) else (swing_rv > 0 if swings > 0 else True)

            

            # Overall run value (weighted average)

            overall_rv = zone_df['run_value'].mean()

            

            # Decision quality: how often batter makes optimal decision

            optimal_decisions = 0

            if is_optimal_swing:

                optimal_decisions = swings

            else:

                optimal_decisions = takes

            

            decision_quality = (optimal_decisions / total_pitches * 100) if total_pitches > 0 else 0.0

            

            zone_data.append({

                'zone': int(zone_num),

                'total_pitches': int(total_pitches),

                'swings': int(swings),

                'takes': int(takes),

                'chases': int(chases),

                'in_zone': int(in_zone),

                'swing_rate': round(swing_rate, 1),

                'chase_rate': round(chase_rate, 1),

                'run_value': round(overall_rv, 4),

                'swing_run_value': round(swing_rv, 4),

                'take_run_value': round(take_rv, 4),

                'is_optimal_swing': bool(is_optimal_swing),

                'decision_quality': round(decision_quality, 1)

            })

        

        # Calculate overall metrics

        total_pitches = len(df)

        overall_swings = df['is_swing'].sum()

        overall_swing_rate = (overall_swings / total_pitches * 100) if total_pitches > 0 else 0.0

        

        zone_pitches = df[df['is_in_zone']]

        zone_swings = zone_pitches['is_swing'].sum() if len(zone_pitches) > 0 else 0

        zone_swing_rate = (zone_swings / len(zone_pitches) * 100) if len(zone_pitches) > 0 else 0.0

        

        chase_pitches = df[~df['is_in_zone']]

        chases = chase_pitches['is_swing'].sum() if len(chase_pitches) > 0 else 0

        chase_rate = (chases / len(chase_pitches) * 100) if len(chase_pitches) > 0 else 0.0

        

        take_rate_in_zone = ((len(zone_pitches) - zone_swings) / len(zone_pitches) * 100) if len(zone_pitches) > 0 else 0.0

        

        # Calculate optimal decision rate

        optimal_decisions_total = 0

        for zd in zone_data:

            if zd['is_optimal_swing']:

                optimal_decisions_total += zd['swings']

            else:

                optimal_decisions_total += zd['takes']

        

        optimal_decision_rate = (optimal_decisions_total / total_pitches * 100) if total_pitches > 0 else 0.0

        

        # Average run value

        avg_run_value = df['run_value'].mean() if len(df) > 0 else 0.0

        

        # Decision quality score (0-100)

        decision_quality_score = optimal_decision_rate

        

        # Quality breakdown

        quality_breakdown = {

            'optimal': optimal_decisions_total,

            'suboptimal': total_pitches - optimal_decisions_total,

            'poor': 0  # Could be enhanced with more sophisticated logic

        }

        

        # Get batter handedness

        batter_hand = 'R'

        if 'stand' in df.columns:

            stand_values = df['stand'].dropna()

            if len(stand_values) > 0:

                batter_hand = str(stand_values.mode().iloc[0]) if len(stand_values.mode()) > 0 else 'R'

        

        return jsonify({

            'batter': batter_name,

            'batter_hand': batter_hand,

            'season': season,

            'count': count,

            'total_pitches': total_pitches,

            'overall_swing_rate': round(overall_swing_rate, 1),

            'zone_swing_rate': round(zone_swing_rate, 1),

            'chase_rate': round(chase_rate, 1),

            'take_rate_in_zone': round(take_rate_in_zone, 1),

            'optimal_decision_rate': round(optimal_decision_rate, 1),

            'avg_run_value': round(avg_run_value, 4),

            'decision_quality_score': round(decision_quality_score, 1),

            'zone_data': zone_data,

            'quality_breakdown': quality_breakdown

        })

    except Exception as e:

        import traceback

        traceback.print_exc()

        return jsonify({"error": str(e)}), 500


@bp.route('/visuals/plate-discipline-matrix', methods=['GET'])

def api_visuals_plate_discipline_matrix():

    """Get plate discipline matrix data: swing rates, chase rates, and contact rates by pitch type and location"""

    if not csv_loader:

        return jsonify({"error": "CSV data loader not available"}), 500

    

    try:

        batter_name = request.args.get('batter', '').strip()

        if not batter_name:

            return jsonify({"error": "Batter name is required"}), 400

        

        season = request.args.get('season', '').strip() or None

        if season:

            try:

                season = int(season)

            except ValueError:

                season = None

        

        # Import statcast functions

        sys.path.insert(0, str(Config.ROOT_DIR / "src"))

        from scrape_savant import fetch_batter_statcast, lookup_batter_id

        from datetime import datetime

        import pandas as pd

        import numpy as np

        

        # Get batter ID

        try:

            batter_id = lookup_batter_id(batter_name)

        except Exception as e:

            return jsonify({"error": f"Could not find batter ID for '{batter_name}': {str(e)}"}), 404

        

        # Calculate date range

        if season:

            start_date = f"{season}-03-01"

            end_date = f"{season}-11-30"

            filter_by_season = True

        else:

            current_year = datetime.now().year

            start_date = "2008-03-01"

            end_date = f"{current_year}-11-30"

            filter_by_season = False

        

        # Fetch statcast data

        try:

            df = fetch_batter_statcast(batter_id, start_date, end_date)

        except Exception as e:

            return jsonify({"error": f"Error fetching statcast data: {str(e)}"}), 500

        

        if df is None or df.empty:

            return jsonify({

                "error": f"No statcast data found for {batter_name}",

                "batter": batter_name,

                "data": {}

            }), 200

        

        # Filter by season if specified

        if filter_by_season:

            year_column = None

            for col_name in ['game_year', 'year', 'Year', 'season']:

                if col_name in df.columns:

                    year_column = col_name

                    break

            

            if year_column:

                if not pd.api.types.is_integer_dtype(df[year_column]):

                    df[year_column] = pd.to_numeric(df[year_column], errors='coerce')

                df = df[

                    (df[year_column].notna()) & 

                    (df[year_column] == int(season))

                ]

            else:

                date_column = None

                for col_name in ['game_date', 'gameDate', 'date', 'Date', 'game_day']:

                    if col_name in df.columns:

                        date_column = col_name

                        break

                

                if date_column:

                    if not pd.api.types.is_datetime64_any_dtype(df[date_column]):

                        df[date_column] = pd.to_datetime(df[date_column], errors='coerce')

                    

                    season_start = pd.to_datetime(f"{season}-03-01")

                    season_end = pd.to_datetime(f"{season}-11-30")

                    

                    df = df[df[date_column].notna()]

                    df = df[

                        (df[date_column] >= season_start) & 

                        (df[date_column] <= season_end)

                    ]

            

            if df.empty:

                return jsonify({

                    "error": f"No statcast data found for {batter_name} for season {season}",

                    "batter": batter_name,

                    "data": {}

                }), 200

        

        # Filter out rows without necessary data

        df = df.dropna(subset=['pitch_type'])

        if df.empty:

            return jsonify({

                "error": "No valid pitch data available",

                "batter": batter_name,

                "data": {}

            }), 200

        

        # Calculate swing, contact, and zone indicators

        desc = df['description'].astype(str).str.lower()

        df['is_swing'] = desc.isin([

            'foul', 'foul_tip', 'swinging_strike', 'swinging_strike_blocked', 

            'missed_bunt', 'foul_bunt', 'hit_into_play'

        ])

        

        # Contact made (swing that resulted in contact, not a whiff)

        df['is_contact'] = desc.isin([

            'foul', 'foul_tip', 'foul_bunt', 'hit_into_play'

        ])

        

        # Determine if pitch is in zone (zone 1-9 are in zone, 11-14 are outside, NaN needs plate_x/plate_z check)

        df['is_in_zone'] = False

        if 'zone' in df.columns:

            # Zone 1-9 are in the strike zone

            df['is_in_zone'] = df['zone'].between(1, 9, inclusive='both')

            # For pitches without zone data, try to infer from plate_x and plate_z

            # Standard strike zone: plate_x: -0.855 to 0.855, plate_z: ~1.5 to ~3.5 (varies by batter)

            if 'plate_x' in df.columns and 'plate_z' in df.columns:

                zone_na_mask = df['zone'].isna()

                if zone_na_mask.any():

                    # Approximate zone boundaries (can be refined)

                    df.loc[zone_na_mask, 'is_in_zone'] = (

                        (df.loc[zone_na_mask, 'plate_x'].abs() <= 0.855) &

                        (df.loc[zone_na_mask, 'plate_z'] >= 1.5) &

                        (df.loc[zone_na_mask, 'plate_z'] <= 3.5)

                    )

        elif 'plate_x' in df.columns and 'plate_z' in df.columns:

            # Fallback: estimate zone from plate_x and plate_z

            df['is_in_zone'] = (

                (df['plate_x'].abs() <= 0.855) &

                (df['plate_z'] >= 1.5) &

                (df['plate_z'] <= 3.5)

            )

        

        # Chase = swing on pitch outside the zone

        df['is_chase'] = df['is_swing'] & ~df['is_in_zone']

        

        # Get pitch types

        pitch_types = df['pitch_type'].dropna().unique()

        if len(pitch_types) == 0:

            return jsonify({

                "error": "No pitch type data available",

                "batter": batter_name,

                "data": {}

            }), 200

        

        # Define location zones (simplified: In Zone vs Out of Zone)

        # Could expand to 9-zone grid later

        location_zones = ['In Zone', 'Out of Zone']

        

        # Calculate metrics by pitch type and location

        matrix_data = []

        

        for pitch_type in pitch_types:

            df_pitch = df[df['pitch_type'] == pitch_type]

            

            for zone_type in location_zones:

                if zone_type == 'In Zone':

                    df_zone = df_pitch[df_pitch['is_in_zone']]

                else:

                    df_zone = df_pitch[~df_pitch['is_in_zone']]

                

                if len(df_zone) == 0:

                    continue

                

                total_pitches = len(df_zone)

                swings = df_zone['is_swing'].sum()

                chases = df_zone['is_chase'].sum()

                contacts = df_zone['is_contact'].sum()

                

                # Calculate rates

                swing_rate = (swings / total_pitches * 100) if total_pitches > 0 else 0.0

                chase_rate = (chases / total_pitches * 100) if total_pitches > 0 else 0.0

                contact_rate = (contacts / swings * 100) if swings > 0 else None

                

                matrix_data.append({

                    'pitch_type': str(pitch_type),

                    'location': zone_type,

                    'total_pitches': int(total_pitches),

                    'swings': int(swings),

                    'chases': int(chases),

                    'contacts': int(contacts),

                    'swing_rate': round(swing_rate, 1),

                    'chase_rate': round(chase_rate, 1),

                    'contact_rate': round(contact_rate, 1) if contact_rate is not None else None

                })

        

        if not matrix_data:

            return jsonify({

                "error": f"No plate discipline data available for {batter_name}",

                "batter": batter_name,

                "data": {}

            }), 200

        

        # Get batter handedness

        batter_hand = 'R'  # Default

        if 'stand' in df.columns:

            stand_values = df['stand'].dropna()

            if len(stand_values) > 0:

                batter_hand = str(stand_values.mode().iloc[0]) if len(stand_values.mode()) > 0 else 'R'

        

        return jsonify({

            'batter': batter_name,

            'batter_hand': batter_hand,

            'season': season,

            'total_pitches': len(df),

            'matrix': matrix_data,

            'pitch_types': [str(pt) for pt in pitch_types],

            'location_zones': location_zones

        })

    except Exception as e:

        import traceback

        traceback.print_exc()

        return jsonify({"error": str(e)}), 500


@bp.route('/pitcher/<pitcher_name>/seasons', methods=['GET'])
def api_pitcher_seasons(pitcher_name):
    """Get available seasons for a specific pitcher"""
    try:
        from urllib.parse import unquote
        pitcher_name = unquote(pitcher_name)
        
        # Use CSV seasons endpoint logic
        if csv_loader:
            try:
                player_data = csv_loader.get_player_data(pitcher_name)
                if player_data and player_data.get('fangraphs'):
                    seasons = set()
                    for row in player_data['fangraphs']:
                        if 'Season' in row and row['Season'] is not None:
                            try:
                                seasons.add(int(row['Season']))
                            except (ValueError, TypeError):
                                pass
                    
                    if seasons:
                        seasons_str = sorted([str(s) for s in seasons], reverse=True)
                        return jsonify({
                            "pitcher": pitcher_name,
                            "seasons": seasons_str
                        })
            except Exception:
                pass
        
        # Fallback: return common seasons
        from datetime import datetime
        current_year = datetime.now().year
        seasons = [str(year) for year in range(2015, current_year + 1)]
        
        return jsonify({
            "pitcher": pitcher_name,
            "seasons": seasons
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

