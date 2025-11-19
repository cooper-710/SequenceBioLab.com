"""
Box score service for fetching and formatting MLB game box scores
"""
from typing import Dict, Any, Optional, List
import statsapi
import logging

logger = logging.getLogger(__name__)


def get_box_score(game_pk: int) -> Optional[Dict[str, Any]]:
    """Fetch and format box score data for a game."""
    try:
        game_data = statsapi.get('game', {'gamePk': game_pk})
        
        if not game_data:
            return None
        
        game_info = game_data.get('gameData', {})
        live_data = game_data.get('liveData', {})
        boxscore = live_data.get('boxscore', {})
        linescore = live_data.get('linescore', {})
        
        # Game info
        teams = game_info.get('teams', {})
        away_team_data = teams.get('away', {})
        home_team_data = teams.get('home', {})
        
        away_team = away_team_data.get('name', 'TBD')
        home_team = home_team_data.get('name', 'TBD')
        away_id = away_team_data.get('id')
        home_id = home_team_data.get('id')
        
        # Game status
        status = game_info.get('status', {}).get('detailedState', 'Scheduled')
        
        # Scores and linescore
        away_score = linescore.get('teams', {}).get('away', {}).get('runs', 0)
        home_score = linescore.get('teams', {}).get('home', {}).get('runs', 0)
        
        # Inning info
        innings = linescore.get('innings', [])
        current_inning = linescore.get('currentInning', 0)
        inning_state = linescore.get('inningState', '').lower()
        
        # Venue
        venue = game_info.get('venue', {}).get('name', 'TBD')
        
        # Game date
        game_date = None
        game_datetime = game_info.get('datetime', {})
        if game_datetime:
            # Try different date fields
            game_date_str = (game_datetime.get('originalDate') or 
                           game_datetime.get('dateTime') or
                           game_datetime.get('date'))
            if game_date_str:
                try:
                    # Parse ISO format date
                    from datetime import datetime
                    if 'T' in game_date_str:
                        dt = datetime.fromisoformat(game_date_str.replace('Z', '+00:00'))
                    else:
                        dt = datetime.fromisoformat(game_date_str)
                    game_date = dt.strftime("%A, %B %d, %Y")
                except Exception:
                    pass
        
        # Box score teams data
        boxscore_teams = boxscore.get('teams', {})
        away_box = boxscore_teams.get('away', {})
        home_box = boxscore_teams.get('home', {})
        
        # Batting stats
        away_batters = away_box.get('batters', [])
        home_batters = home_box.get('batters', [])
        away_pitchers = away_box.get('pitchers', [])
        home_pitchers = home_box.get('pitchers', [])
        
        # Get player details
        players = game_info.get('players', {})
        
        def get_player_batting_stats(player_id: int, team_box: Dict, players_dict: Dict) -> Dict[str, Any]:
            """Get individual player batting stats from boxscore."""
            # Try different key formats
            player_key = f'ID{player_id}'
            player_key_alt = str(player_id)
            
            # Try to get player info with different key formats
            player_info = players_dict.get(player_key, {})
            if not player_info:
                player_info = players_dict.get(player_key_alt, {})
            
            # Try multiple paths for person info
            person_info = player_info.get('person', {}) if player_info else {}
            if not person_info and player_info:
                # Sometimes person info is directly in player_info
                person_info = player_info
            
            # Get player data from boxscore - try different key formats
            box_players = team_box.get('players', {})
            box_player = box_players.get(player_key, {})
            if not box_player:
                box_player = box_players.get(player_key_alt, {})
            
            # Also try box_player for person info
            if not person_info and box_player and 'person' in box_player:
                person_info = box_player.get('person', {})
            
            # Try multiple paths for batting stats
            stats = {}
            if 'stats' in box_player:
                batting_data = box_player.get('stats', {}).get('batting', {})
                if batting_data:
                    stats = batting_data
            elif 'batting' in box_player:
                stats = box_player.get('batting', {})
            
            # Try alternate stat locations
            if not stats:
                # Try seasonStats
                season_stats = box_player.get('seasonStats', {}).get('batting', {})
                if season_stats:
                    stats = season_stats
            
            # Get position - try from boxscore first, then player info
            position = ''
            
            # Try boxscore position
            if 'position' in box_player:
                pos_info = box_player.get('position', {})
                if isinstance(pos_info, dict):
                    position = pos_info.get('abbreviation', '') or pos_info.get('code', '') or pos_info.get('name', '')
            
            # Try player info position
            if not position and 'position' in player_info:
                pos_info = player_info.get('position', {})
                if isinstance(pos_info, dict):
                    position = pos_info.get('abbreviation', '') or pos_info.get('code', '') or pos_info.get('name', '')
            
            # Try primary position from person info
            if not position:
                pos_info = person_info.get('primaryPosition', {})
                if isinstance(pos_info, dict):
                    position = pos_info.get('abbreviation', '') or pos_info.get('code', '')
            
            # Get batting stats with multiple fallback options
            at_bats = stats.get('atBats') or stats.get('ab') or stats.get('at_bats') or 0
            runs = stats.get('runs') or stats.get('r') or 0
            hits = stats.get('hits') or stats.get('h') or 0
            rbi = stats.get('rbi') or stats.get('RBI') or stats.get('runsBattedIn') or 0
            home_runs = stats.get('homeRuns') or stats.get('hr') or stats.get('home_runs') or 0
            walks = stats.get('baseOnBalls') or stats.get('bb') or stats.get('walks') or stats.get('baseOnBalls') or 0
            strikeouts = stats.get('strikeOuts') or stats.get('so') or stats.get('strikeouts') or stats.get('k') or 0
            
            # Convert to int if possible
            try:
                at_bats = int(at_bats) if at_bats else 0
                runs = int(runs) if runs else 0
                hits = int(hits) if hits else 0
                rbi = int(rbi) if rbi else 0
                home_runs = int(home_runs) if home_runs else 0
                walks = int(walks) if walks else 0
                strikeouts = int(strikeouts) if strikeouts else 0
            except (ValueError, TypeError):
                at_bats = runs = hits = rbi = home_runs = walks = strikeouts = 0
            
            # Get player name - try multiple paths
            name = None
            
            # Try person_info first
            if person_info:
                name = (person_info.get('fullName') or 
                       person_info.get('fullDisplayName') or
                       person_info.get('name') or
                       person_info.get('displayName'))
            
            # Try player_info directly
            if not name and player_info:
                name = (player_info.get('fullName') or
                       player_info.get('fullDisplayName') or
                       player_info.get('name'))
            
            # Try box_player
            if not name and box_player:
                box_person = box_player.get('person', {})
                if box_person:
                    name = (box_person.get('fullName') or
                           box_person.get('fullDisplayName') or
                           box_person.get('name'))
                else:
                    name = (box_player.get('fullName') or
                           box_player.get('fullDisplayName') or
                           box_player.get('name'))
            
            # Final fallback - try to get from person endpoint if we have player_id
            if not name or name == 'Unknown':
                try:
                    person_data = statsapi.get('person', {'personId': player_id})
                    if person_data and 'people' in person_data and len(person_data['people']) > 0:
                        person = person_data['people'][0]
                        name = (person.get('fullName') or
                               person.get('fullDisplayName') or
                               person.get('name') or
                               name)
                except Exception:
                    pass
            
            # Last resort
            if not name:
                name = 'Unknown'
            
            # Display 0 if player had at-bats but no stats, otherwise show dash
            # If at_bats > 0, show actual values (even if 0)
            # If at_bats == 0 and it's a starting lineup player, might still show 0
            # Otherwise show dash for no data
            
            return {
                'id': player_id,
                'name': name,
                'position': position if position else '-',
                'at_bats': at_bats if at_bats > 0 else ('-' if at_bats == 0 and not stats else '0'),
                'runs': runs if runs > 0 else ('0' if at_bats > 0 else '-'),
                'hits': hits if hits > 0 else ('0' if at_bats > 0 else '-'),
                'rbi': rbi if rbi > 0 else ('0' if at_bats > 0 else '-'),
                'home_runs': home_runs if home_runs > 0 else ('0' if at_bats > 0 else '-'),
                'walks': walks if walks > 0 else ('0' if at_bats > 0 else '-'),
                'strikeouts': strikeouts if strikeouts > 0 else ('0' if at_bats > 0 else '-'),
            }
        
        # Get pitcher IDs for filtering
        away_pitcher_ids = set(away_pitchers) if away_pitchers else set()
        home_pitcher_ids = set(home_pitchers) if home_pitchers else set()
        
        # Get ALL players who appeared in the game (including substitutions, PH, PR, etc.)
        def get_all_players_with_stats(team_box: Dict, players_dict: Dict, batters_list: List[int], pitcher_ids_set: set) -> List[Dict[str, Any]]:
            """Get all players who appeared in the game with their stats."""
            all_players = []
            seen_player_ids = set()
            
            # Get all players from the boxscore who have stats or appeared
            box_players = team_box.get('players', {})
            for player_key, player_data in box_players.items():
                # Extract player ID from key (ID123456 or just 123456)
                try:
                    if player_key.startswith('ID'):
                        player_id = int(player_key[2:])
                    else:
                        player_id = int(player_key)
                    
                    if player_id in seen_player_ids:
                        continue
                    
                    # Check if player has batting stats or is in batters list
                    stats = player_data.get('stats', {}).get('batting', {})
                    if stats or player_id in batters_list:
                        # Player appeared in the game
                        try:
                            player = get_player_batting_stats(player_id, team_box, players_dict)
                            all_players.append(player)
                            seen_player_ids.add(player_id)
                        except Exception as e:
                            logger.warning(f"Error getting stats for player {player_id}: {e}")
                            # Fallback
                            name = 'Unknown'
                            try:
                                person_data = statsapi.get('person', {'personId': player_id})
                                if person_data and 'people' in person_data and len(person_data['people']) > 0:
                                    person = person_data['people'][0]
                                    name = person.get('fullName') or person.get('fullDisplayName') or 'Unknown'
                            except Exception:
                                pass
                            
                            player_key_fmt = f'ID{player_id}'
                            player_info = players_dict.get(player_key_fmt, {})
                            person_info = player_info.get('person', {}) if player_info else {}
                            position = person_info.get('primaryPosition', {}).get('abbreviation', '-') if person_info else '-'
                            
                            all_players.append({
                                'id': player_id,
                                'name': name,
                                'position': position,
                                'at_bats': '-',
                                'runs': '-',
                                'hits': '-',
                                'rbi': '-',
                                'home_runs': '-',
                                'walks': '-',
                                'strikeouts': '-',
                            })
                            seen_player_ids.add(player_id)
                except (ValueError, TypeError):
                    continue
            
            # Also include any batters from the batters list that we might have missed
            for batter_id in batters_list:
                if batter_id not in seen_player_ids:
                    try:
                        player = get_player_batting_stats(batter_id, team_box, players_dict)
                        all_players.append(player)
                        seen_player_ids.add(batter_id)
                    except Exception as e:
                        logger.warning(f"Error getting stats for batter {batter_id}: {e}")
                        # Fallback
                        name = 'Unknown'
                        try:
                            person_data = statsapi.get('person', {'personId': batter_id})
                            if person_data and 'people' in person_data and len(person_data['people']) > 0:
                                person = person_data['people'][0]
                                name = person.get('fullName') or person.get('fullDisplayName') or 'Unknown'
                        except Exception:
                            pass
                        
                        player_key_fmt = f'ID{batter_id}'
                        player_info = players_dict.get(player_key_fmt, {})
                        person_info = player_info.get('person', {}) if player_info else {}
                        position = person_info.get('primaryPosition', {}).get('abbreviation', '-') if person_info else '-'
                        
                        all_players.append({
                            'id': batter_id,
                            'name': name,
                            'position': position,
                            'at_bats': '-',
                            'runs': '-',
                            'hits': '-',
                            'rbi': '-',
                            'home_runs': '-',
                            'walks': '-',
                            'strikeouts': '-',
                        })
                        seen_player_ids.add(batter_id)
            
            # Filter out pitchers who didn't bat (unless they have batting stats)
            filtered_players = []
            
            for player in all_players:
                # Check if player is a pitcher
                position = player.get('position', '').upper()
                is_pitcher = position == 'P' or player['id'] in pitcher_ids_set
                
                # If pitcher, check if they actually batted
                if is_pitcher:
                    at_bats = player.get('at_bats', '-')
                    hits = player.get('hits', '-')
                    runs = player.get('runs', '-')
                    rbi = player.get('rbi', '-')
                    home_runs = player.get('home_runs', '-')
                    walks = player.get('walks', '-')
                    
                    # Check if player has any batting stats (at-bats > 0 or any positive stat)
                    has_at_bats = False
                    if isinstance(at_bats, int) and at_bats > 0:
                        has_at_bats = True
                    elif isinstance(at_bats, str) and at_bats.isdigit() and int(at_bats) > 0:
                        has_at_bats = True
                    
                    has_any_batting_stats = (
                        has_at_bats or
                        (isinstance(hits, int) and hits > 0) or
                        (isinstance(hits, str) and hits.isdigit() and int(hits) > 0) or
                        (isinstance(runs, int) and runs > 0) or
                        (isinstance(runs, str) and runs.isdigit() and int(runs) > 0) or
                        (isinstance(rbi, int) and rbi > 0) or
                        (isinstance(rbi, str) and rbi.isdigit() and int(rbi) > 0) or
                        (isinstance(home_runs, int) and home_runs > 0) or
                        (isinstance(home_runs, str) and home_runs.isdigit() and int(home_runs) > 0) or
                        (isinstance(walks, int) and walks > 0) or
                        (isinstance(walks, str) and walks.isdigit() and int(walks) > 0)
                    )
                    
                    # Only include pitcher if they actually batted
                    if has_any_batting_stats:
                        filtered_players.append(player)
                    # Otherwise, exclude them from batting stats
                else:
                    # Not a pitcher, include them
                    filtered_players.append(player)
            
            # Sort players: starting lineup first (by batting order), then others
            def sort_key(p):
                # Check if player is in starting lineup (first 9 batters)
                is_starter = p['id'] in batters_list[:9]
                # Get batting order if available
                order = batters_list.index(p['id']) if p['id'] in batters_list else 999
                # Prioritize starters, then by order
                return (0 if is_starter else 1, order)
            
            filtered_players.sort(key=sort_key)
            return filtered_players
        
        # Get all players for both teams (excluding pitchers who didn't bat)
        away_batters_list = get_all_players_with_stats(away_box, players, away_batters, away_pitcher_ids)
        home_batters_list = get_all_players_with_stats(home_box, players, home_batters, home_pitcher_ids)
        
        # Get ALL pitchers who appeared in the game
        def get_pitcher_stats(pitcher_id: int, team_box: Dict, players_dict: Dict) -> Dict[str, Any]:
            """Get individual pitcher stats from boxscore."""
            # Try different key formats
            pitcher_key = f'ID{pitcher_id}'
            pitcher_key_alt = str(pitcher_id)
            
            # Try to get player info with different key formats
            player_info = players_dict.get(pitcher_key, {})
            if not player_info:
                player_info = players_dict.get(pitcher_key_alt, {})
            
            # Try multiple paths for person info
            person_info = player_info.get('person', {}) if player_info else {}
            if not person_info and player_info:
                person_info = player_info
            
            # Get pitcher data from boxscore - try different key formats
            box_players = team_box.get('players', {})
            box_pitcher = box_players.get(pitcher_key, {})
            if not box_pitcher:
                box_pitcher = box_players.get(pitcher_key_alt, {})
            
            # Also try box_pitcher for person info
            if not person_info and box_pitcher and 'person' in box_pitcher:
                person_info = box_pitcher.get('person', {})
            
            # Get pitching stats with multiple fallback options
            stats = {}
            if 'stats' in box_pitcher:
                pitching_data = box_pitcher.get('stats', {}).get('pitching', {})
                if pitching_data:
                    stats = pitching_data
            elif 'pitching' in box_pitcher:
                stats = box_pitcher.get('pitching', {})
            
            # Get pitcher stats
            innings_pitched = stats.get('inningsPitched') or stats.get('ip') or stats.get('innings_pitched') or '0.0'
            hits = stats.get('hits') or stats.get('h') or 0
            runs = stats.get('runs') or stats.get('r') or 0
            earned_runs = stats.get('earnedRuns') or stats.get('er') or stats.get('earned_runs') or 0
            walks = stats.get('baseOnBalls') or stats.get('bb') or stats.get('walks') or 0
            strikeouts = stats.get('strikeOuts') or stats.get('so') or stats.get('strikeouts') or stats.get('k') or 0
            home_runs = stats.get('homeRuns') or stats.get('hr') or stats.get('home_runs') or 0
            pitches = stats.get('pitchesThrown') or stats.get('pitches') or stats.get('np') or 0
            strikes = stats.get('strikes') or stats.get('strikesCalled') or 0
            hit_by_pitch = stats.get('hitByPitch') or stats.get('hbp') or 0
            balks = stats.get('balks') or stats.get('bk') or 0
            wild_pitches = stats.get('wildPitches') or stats.get('wp') or 0
            
            # Format innings pitched (convert to float if needed)
            try:
                if isinstance(innings_pitched, str):
                    # Handle format like "6.1" or "6 1/3"
                    innings_pitched = float(innings_pitched)
                innings_display = f"{innings_pitched:.1f}".rstrip('0').rstrip('.')
            except (ValueError, TypeError):
                innings_display = '0.0'
            
            # Get player name - try multiple paths
            name = None
            
            # Try person_info first
            if person_info:
                name = (person_info.get('fullName') or 
                       person_info.get('fullDisplayName') or
                       person_info.get('name') or
                       person_info.get('displayName'))
            
            # Try player_info directly
            if not name and player_info:
                name = (player_info.get('fullName') or
                       player_info.get('fullDisplayName') or
                       player_info.get('name'))
            
            # Try box_pitcher
            if not name and box_pitcher:
                box_person = box_pitcher.get('person', {})
                if box_person:
                    name = (box_person.get('fullName') or
                           box_person.get('fullDisplayName') or
                           box_person.get('name'))
                else:
                    name = (box_pitcher.get('fullName') or
                           box_pitcher.get('fullDisplayName') or
                           box_pitcher.get('name'))
            
            # Final fallback - try to get from person endpoint if we have pitcher_id
            if not name or name == 'Unknown':
                try:
                    person_data = statsapi.get('person', {'personId': pitcher_id})
                    if person_data and 'people' in person_data and len(person_data['people']) > 0:
                        person = person_data['people'][0]
                        name = (person.get('fullName') or
                               person.get('fullDisplayName') or
                               person.get('name') or
                               name)
                except Exception:
                    pass
            
            # Last resort
            if not name:
                name = 'Unknown'
            
            # Convert stats to int if possible
            try:
                hits = int(hits) if hits else 0
                runs = int(runs) if runs else 0
                earned_runs = int(earned_runs) if earned_runs else 0
                walks = int(walks) if walks else 0
                strikeouts = int(strikeouts) if strikeouts else 0
                home_runs = int(home_runs) if home_runs else 0
                pitches = int(pitches) if pitches else 0
                strikes = int(strikes) if strikes else 0
                hit_by_pitch = int(hit_by_pitch) if hit_by_pitch else 0
                balks = int(balks) if balks else 0
                wild_pitches = int(wild_pitches) if wild_pitches else 0
            except (ValueError, TypeError):
                hits = runs = earned_runs = walks = strikeouts = home_runs = pitches = strikes = hit_by_pitch = balks = wild_pitches = 0
            
            return {
                'id': pitcher_id,
                'name': name,
                'innings_pitched': innings_display if innings_display != '0.0' or stats else '-',
                'hits': hits if hits > 0 else ('0' if stats else '-'),
                'runs': runs if runs > 0 else ('0' if stats else '-'),
                'earned_runs': earned_runs if earned_runs > 0 else ('0' if stats else '-'),
                'walks': walks if walks > 0 else ('0' if stats else '-'),
                'strikeouts': strikeouts if strikeouts > 0 else ('0' if stats else '-'),
                'home_runs': home_runs if home_runs > 0 else ('0' if stats else '-'),
                'pitches': pitches if pitches > 0 else ('0' if stats else '-'),
                'strikes': strikes if strikes > 0 else ('0' if stats else '-'),
                'hit_by_pitch': hit_by_pitch if hit_by_pitch > 0 else ('0' if stats else '-'),
                'balks': balks if balks > 0 else ('0' if stats else '-'),
                'wild_pitches': wild_pitches if wild_pitches > 0 else ('0' if stats else '-'),
            }
        
        def get_all_pitchers_with_stats(team_box: Dict, players_dict: Dict, pitchers_list: List[int]) -> List[Dict[str, Any]]:
            """Get all pitchers who appeared in the game with their stats."""
            all_pitchers = []
            seen_pitcher_ids = set()
            
            # Get all pitchers from the pitchers list
            for pitcher_id in pitchers_list:
                if pitcher_id in seen_pitcher_ids:
                    continue
                
                try:
                    pitcher = get_pitcher_stats(pitcher_id, team_box, players_dict)
                    all_pitchers.append(pitcher)
                    seen_pitcher_ids.add(pitcher_id)
                except Exception as e:
                    logger.warning(f"Error getting stats for pitcher {pitcher_id}: {e}")
                    # Fallback
                    name = 'Unknown'
                    try:
                        person_data = statsapi.get('person', {'personId': pitcher_id})
                        if person_data and 'people' in person_data and len(person_data['people']) > 0:
                            person = person_data['people'][0]
                            name = person.get('fullName') or person.get('fullDisplayName') or 'Unknown'
                    except Exception:
                        pass
                    
                    all_pitchers.append({
                        'id': pitcher_id,
                        'name': name,
                        'innings_pitched': '-',
                        'hits': '-',
                        'runs': '-',
                        'earned_runs': '-',
                        'walks': '-',
                        'strikeouts': '-',
                        'home_runs': '-',
                        'pitches': '-',
                        'strikes': '-',
                        'hit_by_pitch': '-',
                        'balks': '-',
                        'wild_pitches': '-',
                    })
                    seen_pitcher_ids.add(pitcher_id)
            
            return all_pitchers
        
        # Get all pitchers for both teams
        away_pitchers_list = get_all_pitchers_with_stats(away_box, players, away_pitchers)
        home_pitchers_list = get_all_pitchers_with_stats(home_box, players, home_pitchers)
        
        # For backward compatibility, also set starter pitcher names
        away_pitcher_id = away_pitchers[0] if away_pitchers else None
        home_pitcher_id = home_pitchers[0] if home_pitchers else None
        
        away_pitcher_name = away_pitchers_list[0]['name'] if away_pitchers_list else None
        home_pitcher_name = home_pitchers_list[0]['name'] if home_pitchers_list else None
        
        return {
            'game_pk': game_pk,
            'away_team': away_team,
            'home_team': home_team,
            'away_id': away_id,
            'home_id': home_id,
            'away_score': away_score,
            'home_score': home_score,
            'status': status,
            'venue': venue,
            'game_date': game_date,
            'innings': innings,
            'current_inning': current_inning,
            'inning_state': inning_state,
            'away_batters': away_batters_list,
            'home_batters': home_batters_list,
            'away_pitchers': away_pitchers_list,
            'home_pitchers': home_pitchers_list,
            'away_pitcher': away_pitcher_name,
            'home_pitcher': home_pitcher_name,
            'boxscore_data': boxscore,  # Raw boxscore for detailed stats
        }
        
    except Exception as e:
        logger.error(f"Error fetching box score for game {game_pk}: {e}")
        import traceback
        traceback.print_exc()
        return None
