"""
Route registration
"""
def register_routes(app):
    """Register all blueprints"""
    # Register reports blueprint
    try:
        from app.routes import reports
        app.register_blueprint(reports.bp)
    except (ImportError, AttributeError) as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Reports routes not available: {e}")
    
    # Register settings blueprint
    try:
        from app.routes.api import settings
        app.register_blueprint(settings.bp)
    except (ImportError, AttributeError) as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Settings routes not available: {e}")
    
    # Register auth blueprint
    try:
        from app.routes import auth
        app.register_blueprint(auth.bp)
    except (ImportError, AttributeError) as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Auth routes not yet migrated: {e}")
    
    # Register pages blueprint
    try:
        from app.routes import pages
        app.register_blueprint(pages.bp)
    except (ImportError, AttributeError) as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Pages routes not yet migrated: {e}")
    
    # Register API blueprints
    # Register admin FIRST to ensure invite codes work, even if other blueprints fail
    try:
        from app.routes.api import admin
        app.register_blueprint(admin.bp, url_prefix='/api/admin')
        import logging
        logger = logging.getLogger(__name__)
        invite_routes = [r for r in app.url_map.iter_rules() if 'invite' in r.rule.lower()]
        if invite_routes:
            logger.info(f"Invite code routes registered: {[r.rule for r in invite_routes]}")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to register admin blueprint: {e}", exc_info=True)
    
    # Register other API blueprints
    try:
        from app.routes.api import players, analytics, visuals
        app.register_blueprint(players.bp, url_prefix='/api')
        app.register_blueprint(analytics.bp, url_prefix='/api')
        try:
            app.register_blueprint(visuals.bp, url_prefix='/api')
        except AssertionError as e:
            # Handle duplicate endpoint gracefully
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Visuals blueprint has duplicate endpoints, skipping: {e}")
    except (ImportError, AttributeError) as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Some API routes not available: {e}")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Error registering some API blueprints: {e}")

