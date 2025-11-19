"""
Analytics API routes
"""
from flask import Blueprint, request, jsonify
import sys
from pathlib import Path

bp = Blueprint('analytics', __name__)

# Import CSV data loader if available
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
    from csv_data_loader import CSVDataLoader
    from app.config import Config
    csv_loader = CSVDataLoader(str(Config.ROOT_DIR))
except (ImportError, Exception):
    csv_loader = None


@bp.route('/analytics/players', methods=['GET'])
def api_analytics_players():
    """Get all players with basic stats for filtering"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        players = csv_loader.get_all_players_summary()
        
        # Get unique teams and positions for filters
        teams = sorted(list(set(p['team'] for p in players if p['team'])))
        positions = sorted(list(set(p['position'] for p in players if p['position'])))
        all_seasons = sorted(list(set(season for p in players for season in p['seasons'])))
        
        return jsonify({
            "players": players,
            "filters": {
                "teams": teams,
                "positions": positions,
                "seasons": all_seasons
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.route('/analytics/trends', methods=['GET'])
def api_analytics_trends():
    """Get player performance trends over seasons"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        player_name = request.args.get('player', '').strip()
        if not player_name:
            return jsonify({"error": "Player name is required"}), 400
        
        stats = request.args.getlist('stats')
        if not stats:
            stats = None
        
        season_start = request.args.get('season_start', type=int)
        season_end = request.args.get('season_end', type=int)
        
        trends = csv_loader.get_player_trends(
            player_name=player_name,
            stats=stats,
            season_start=season_start,
            season_end=season_end
        )
        
        return jsonify(trends)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.route('/analytics/comparisons', methods=['GET'])
def api_analytics_comparisons():
    """Compare multiple players across selected metrics"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        players = request.args.getlist('players')
        if not players:
            return jsonify({"error": "At least one player is required"}), 400
        
        stats = request.args.getlist('stats')
        if not stats:
            return jsonify({"error": "At least one stat is required"}), 400
        
        season = request.args.get('season', type=int)
        
        comparison = csv_loader.compare_players(
            player_names=players,
            stats=stats,
            season=season
        )
        
        return jsonify(comparison)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.route('/analytics/leaders', methods=['GET'])
def api_analytics_leaders():
    """Get league leaders for various stats"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        stat = request.args.get('stat', '').strip()
        if not stat:
            return jsonify({"error": "Stat is required"}), 400
        
        limit = request.args.get('limit', default=10, type=int)
        season = request.args.get('season', type=int)
        position = request.args.get('position', '').strip() or None
        team = request.args.get('team', '').strip() or None
        
        leaders = csv_loader.get_league_leaders(
            stat=stat,
            limit=limit,
            season=season,
            position=position,
            team=team
        )
        
        return jsonify({"leaders": leaders, "stat": stat})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@bp.route('/analytics/distributions', methods=['GET'])
def api_analytics_distributions():
    """Get statistical distributions for metrics"""
    if not csv_loader:
        return jsonify({"error": "CSV data loader not available"}), 500
    
    try:
        stat = request.args.get('stat', '').strip()
        if not stat:
            return jsonify({"error": "Stat is required"}), 400
        
        season = request.args.get('season', type=int)
        position = request.args.get('position', '').strip() or None
        team = request.args.get('team', '').strip() or None
        bins = request.args.get('bins', default=20, type=int)
        
        distribution = csv_loader.get_stat_distribution(
            stat=stat,
            season=season,
            position=position,
            team=team,
            bins=bins
        )
        
        return jsonify(distribution)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
