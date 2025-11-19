"""
Live scores service for fetching current MLB game scores
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timezone
import statsapi
import logging
from app.services.schedule_service import team_abbr_from_id

logger = logging.getLogger(__name__)


def get_games_for_date(target_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """Fetch games for a specific date with live scores and status."""
    if target_date is None:
        target_date = date.today()
    
    try:
        # Get schedule for the target date
        schedule = statsapi.schedule(
            start_date=target_date.isoformat(),
            end_date=target_date.isoformat()
        )
    except Exception as e:
        logger.warning(f"Error fetching schedule: {e}")
        return []
    
    if not schedule:
        return []
    
    games = []
    for game in schedule:
        try:
            game_pk = game.get('game_id') or game.get('game_pk')
            if not game_pk:
                continue
            
            # Get detailed game data for live scores
            try:
                game_data = statsapi.get('game', {'gamePk': game_pk})
                live_data = game_data.get('liveData', {})
                game_info = game_data.get('gameData', {})
                boxscore = live_data.get('boxscore', {})
                linescore = live_data.get('linescore', {})
                
                # Extract team info
                away_team = game.get('away_name', 'TBD')
                home_team = game.get('home_name', 'TBD')
                away_id = game.get('away_id')
                home_id = game.get('home_id')
                
                # Get scores
                away_score = linescore.get('teams', {}).get('away', {}).get('runs', 0)
                home_score = linescore.get('teams', {}).get('home', {}).get('runs', 0)
                
                # Get current inning info
                current_inning = linescore.get('currentInning', 0)
                inning_state = linescore.get('inningState', '').lower()  # 'top', 'bottom', 'end', 'middle'
                inning_label = _format_inning(current_inning, inning_state)
                
                # Get game status
                status = game.get('status', 'Scheduled')
                game_status = _normalize_status(status, linescore)
                
                # Get game time
                game_time = game.get('game_datetime') or game.get('gameDate')
                display_time = _format_game_time(game_time)
                
                # Get venue
                venue = game.get('venue_name', 'TBD')
                
                # Get team abbreviations for logos
                away_abbr = team_abbr_from_id(away_id)
                home_abbr = team_abbr_from_id(home_id)
                
                # Determine if game is live
                # Consider game live if it's actually in progress or delayed (not just warmup/scheduled)
                is_live = game_status in ('Live', 'Delayed', 'In Progress') or (
                    game_status == 'Warmup' and current_inning > 0
                )
                
                # Get pitchers if available
                away_pitcher_ids = boxscore.get('teams', {}).get('away', {}).get('pitchers', [])
                home_pitcher_ids = boxscore.get('teams', {}).get('home', {}).get('pitchers', [])
                
                away_pitcher_name = None
                home_pitcher_name = None
                
                # Get pitcher names from players data
                players = game_info.get('players', {})
                
                if away_pitcher_ids and len(away_pitcher_ids) > 0:
                    try:
                        pitcher_id = away_pitcher_ids[0]
                        # Try different ID formats
                        for id_format in [f'ID{pitcher_id}', str(pitcher_id), f'id{pitcher_id}']:
                            pitcher_data = players.get(id_format, {})
                            if pitcher_data:
                                away_pitcher_name = pitcher_data.get('fullName') or pitcher_data.get('fullDisplayName')
                                if away_pitcher_name:
                                    break
                    except Exception:
                        pass
                
                if home_pitcher_ids and len(home_pitcher_ids) > 0:
                    try:
                        pitcher_id = home_pitcher_ids[0]
                        # Try different ID formats
                        for id_format in [f'ID{pitcher_id}', str(pitcher_id), f'id{pitcher_id}']:
                            pitcher_data = players.get(id_format, {})
                            if pitcher_data:
                                home_pitcher_name = pitcher_data.get('fullName') or pitcher_data.get('fullDisplayName')
                                if home_pitcher_name:
                                    break
                    except Exception:
                        pass
                
                games.append({
                    'game_pk': game_pk,
                    'away_team': away_team,
                    'home_team': home_team,
                    'away_id': away_id,
                    'home_id': home_id,
                    'away_abbr': away_abbr,
                    'home_abbr': home_abbr,
                    'away_score': away_score,
                    'home_score': home_score,
                    'current_inning': current_inning,
                    'inning_state': inning_state,
                    'inning_label': inning_label,
                    'status': game_status,
                    'status_detail': status,
                    'game_time': display_time,
                    'venue': venue,
                    'is_live': is_live,
                    'away_pitcher': away_pitcher_name,
                    'home_pitcher': home_pitcher_name,
                })
            except Exception as e:
                # Fallback to basic schedule data if detailed fetch fails
                logger.warning(f"Error fetching detailed game data for {game_pk}: {e}")
                away_id_fallback = game.get('away_id')
                home_id_fallback = game.get('home_id')
                games.append({
                    'game_pk': game_pk,
                    'away_team': game.get('away_name', 'TBD'),
                    'home_team': game.get('home_name', 'TBD'),
                    'away_id': away_id_fallback,
                    'home_id': home_id_fallback,
                    'away_abbr': team_abbr_from_id(away_id_fallback),
                    'home_abbr': team_abbr_from_id(home_id_fallback),
                    'away_score': None,
                    'home_score': None,
                    'current_inning': None,
                    'inning_state': None,
                    'inning_label': None,
                    'status': game.get('status', 'Scheduled'),
                    'status_detail': game.get('status', 'Scheduled'),
                    'game_time': _format_game_time(game.get('game_datetime') or game.get('gameDate')),
                    'venue': game.get('venue_name', 'TBD'),
                    'is_live': False,
                    'away_pitcher': None,
                    'home_pitcher': None,
                })
        except Exception as e:
            logger.warning(f"Error processing game: {e}")
            continue
    
    # Sort games: live games first, then by start time
    games.sort(key=lambda g: (
        0 if g.get('is_live') else 1,  # Live games first
        g.get('game_time', '')
    ))
    
    return games


def _format_inning(inning: int, state: str) -> str:
    """Format inning display (e.g., 'Top 3rd', 'Bottom 9th', 'Final')"""
    if not inning or inning == 0:
        return ''
    
    inning_ordinals = {
        1: '1st', 2: '2nd', 3: '3rd', 4: '4th', 5: '5th',
        6: '6th', 7: '7th', 8: '8th', 9: '9th', 10: '10th',
        11: '11th', 12: '12th', 13: '13th', 14: '14th', 15: '15th'
    }
    
    if inning > 15:
        ordinal = f"{inning}th"
    else:
        ordinal = inning_ordinals.get(inning, f"{inning}th")
    
    if state == 'top':
        return f"Top {ordinal}"
    elif state == 'bottom':
        return f"Bot {ordinal}"
    elif state == 'end':
        return f"End {ordinal}"
    elif state == 'middle':
        return f"Mid {ordinal}"
    else:
        return ordinal


def _normalize_status(status: str, linescore: Dict) -> str:
    """Normalize game status to standard display format."""
    status_lower = status.lower()
    
    if 'final' in status_lower or 'game over' in status_lower:
        return 'Final'
    elif 'live' in status_lower or 'in progress' in status_lower:
        return 'Live'
    elif 'delayed' in status_lower:
        return 'Delayed'
    elif 'postponed' in status_lower:
        return 'Postponed'
    elif 'suspended' in status_lower:
        return 'Suspended'
    elif 'warmup' in status_lower or 'pre-game' in status_lower:
        return 'Warmup'
    elif 'scheduled' in status_lower or 'preview' in status_lower:
        return 'Scheduled'
    else:
        return status


def _format_game_time(game_time: Optional[str]) -> str:
    """Format game time for display."""
    if not game_time:
        return 'TBD'
    
    try:
        # Handle different time formats
        if 'T' in game_time:
            dt = datetime.fromisoformat(game_time.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(game_time)
        
        # Convert to local time
        if dt.tzinfo:
            dt = dt.astimezone()
        
        return dt.strftime("%I:%M %p")
    except Exception:
        return game_time if game_time else 'TBD'

