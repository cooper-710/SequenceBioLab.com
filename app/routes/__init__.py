"""
Route registration
"""


def register_routes(app):
    """Register the complete factory-owned route surface.

    Registration is intentionally fail-fast. A process that starts without an
    auth, admin, reporting, or analytics route group is less safe than a
    process that refuses to start and can be rolled back.
    """
    from app.routes import auth, compat, pages, reports
    from app.routes.api import admin, analytics, players, settings, upload, visuals

    app.register_blueprint(reports.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(pages.bp)
    app.register_blueprint(admin.bp, url_prefix="/api/admin")
    app.register_blueprint(upload.bp)
    app.register_blueprint(players.bp, url_prefix="/api")
    app.register_blueprint(analytics.bp, url_prefix="/api")
    app.register_blueprint(visuals.bp, url_prefix="/api")
    app.register_blueprint(compat.bp)
