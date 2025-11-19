"""
Settings API routes
"""
from flask import Blueprint, request, jsonify, render_template
import settings_manager
from app.config import Config

bp = Blueprint('settings', __name__)


@bp.route('/settings')
def settings_page():
    """Settings page"""
    return render_template('settings.html')


@bp.route('/api/settings', methods=['GET', 'PUT', 'PATCH', 'POST', 'DELETE'])
def api_settings():
    """Retrieve or update application settings."""
    try:
        if request.method == 'GET':
            return jsonify(Config.get_settings())

        if request.method == 'DELETE':
            defaults = settings_manager.reset_settings()
            Config.refresh_settings_cache()
            return jsonify(defaults)

        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"error": "Request body must be valid JSON"}), 400
        if not isinstance(payload, dict):
            return jsonify({"error": "Settings payload must be a JSON object"}), 400

        updated = settings_manager.update_settings(payload)
        Config.refresh_settings_cache()
        return jsonify(updated)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Failed to process settings: {exc}"}), 500
