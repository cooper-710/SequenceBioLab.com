#!/usr/bin/env python3
"""Test MLB StatsAPI schedule data"""
import sys
from datetime import datetime, timedelta, timezone
sys.path.insert(0, 'src')

import statsapi
from next_opponent import next_games, _resolve_team_id

def test_mlb_schedule():
    """Test if MLB StatsAPI is returning schedule data"""
    print("Testing MLB StatsAPI schedule data...")
    print("=" * 60)
    
    # Test 1: Direct API call
    print("\n1. Testing direct statsapi.schedule() call...")
    try:
        today = datetime.now(timezone.utc).date()
        end_date = today + timedelta(days=14)
        
        print(f"   Querying schedule from {today} to {end_date}")
        
        # Test with a known team (Mets)
        schedule = statsapi.schedule(
            start_date=today.isoformat(),
            end_date=end_date.isoformat(),
            team=121  # NY Mets
        )
        
        if schedule:
            print(f"   ✓ Success! Got {len(schedule)} games")
            if len(schedule) > 0:
                game = schedule[0]
                print(f"   First game: {game.get('game_date')} - {game.get('away_name')} @ {game.get('home_name')}")
                print(f"   Status: {game.get('status', 'N/A')}")
        else:
            print("   ⚠ No games returned (this might be normal if no games scheduled)")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 2: Using next_games function
    print("\n2. Testing next_games() function...")
    try:
        games = next_games("NYM", days_ahead=14, include_started=True)
        
        if games:
            print(f"   ✓ Success! Got {len(games)} games")
            for i, game in enumerate(games[:3], 1):
                print(f"   Game {i}: {game.get('game_date')} - {game.get('opponent_name')} ({'Home' if game.get('is_home') else 'Away'}) - Status: {game.get('status', 'N/A')}")
        else:
            print("   ⚠ No games returned")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test 3: Test with different teams
    print("\n3. Testing with different teams...")
    teams = ["NYY", "LAD", "ATL"]
    for team in teams:
        try:
            games = next_games(team, days_ahead=7, include_started=True)
            print(f"   {team}: {len(games)} games found")
            if games:
                print(f"      Next game: {games[0].get('game_date')} vs {games[0].get('opponent_name')}")
        except Exception as e:
            print(f"   {team}: ✗ Error - {e}")
    
    # Test 4: Check if we can get all teams
    print("\n4. Testing team lookup...")
    try:
        teams_data = statsapi.get('teams', {'sportId': 1})
        if teams_data and 'teams' in teams_data:
            print(f"   ✓ Success! Found {len(teams_data['teams'])} teams")
            # Show a few examples
            for team in teams_data['teams'][:3]:
                print(f"      {team.get('teamName')} (ID: {team.get('id')})")
        else:
            print("   ⚠ No teams data returned")
    except Exception as e:
        print(f"   ✗ Failed: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("Test complete!")
    return True

if __name__ == "__main__":
    test_mlb_schedule()

