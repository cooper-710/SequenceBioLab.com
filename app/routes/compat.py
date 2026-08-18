"""Compatibility routes retained during the factory cutover.

These paths are part of the working legacy application's public surface but
their canonical handlers now live in the admin API blueprint. Keeping the
aliases here lets the factory-only application preserve existing links while
the old ``app.py`` entry point remains available for rollback.
"""

from flask import Blueprint

from app.routes.api import admin


bp = Blueprint("compat", __name__)


@bp.route("/api/workouts/latest", methods=["GET"])
def api_workouts_latest():
    return admin.api_workouts_latest()


@bp.route("/player-docs/<int:doc_id>", methods=["GET"])
def download_player_document(doc_id: int):
    return admin.download_player_document(doc_id)


@bp.route("/workout-docs/<int:doc_id>", methods=["GET"])
def view_workout_document(doc_id: int):
    return admin.view_workout_document(doc_id)
