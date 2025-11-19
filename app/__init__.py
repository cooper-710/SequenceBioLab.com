"""
Flask application factory for SequenceBioLab
"""
import logging
from flask import Flask
from app.config import Config
from app.middleware.auth import setup_auth_middleware, ensure_default_admin
from app.middleware.context import setup_context_processors
from app.routes import register_routes


def create_app(config=None):
    """
    Create and configure Flask application
    
    Args:
        config: Optional configuration class (defaults to Config)
    
    Returns:
        Flask application instance
    """
    app = Flask(__name__, template_folder=str(Config.ROOT_DIR / 'templates'), static_folder=str(Config.ROOT_DIR / 'static'))
    
    # Load configuration
    if config is None:
        config = Config
    
    app.config.from_object(config)
    app.config['SECRET_KEY'] = Config.SECRET_KEY
    app.config['DEBUG'] = Config.DEBUG
    app.config['USE_MOCK_SCHEDULE'] = Config.USE_MOCK_SCHEDULE
    
    # Ensure directories exist
    Config.ensure_directories()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO if not Config.DEBUG else logging.DEBUG,
        format='%(asctime)s %(levelname)s %(name)s %(message)s'
    )
    
    # Setup middleware
    try:
        setup_auth_middleware(app)
        setup_context_processors(app)
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Error setting up middleware: {e}")
    
    # Ensure default admin exists
    try:
        ensure_default_admin()
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Error ensuring default admin: {e}")
    
    # Register routes (may be empty if routes are still in app.py)
    try:
        register_routes(app)
    except Exception as e:
        # Routes may still be in app.py - that's OK for gradual migration
        logger = logging.getLogger(__name__)
        logger.debug(f"Routes not yet migrated to blueprints: {e}")
    
    # Register error handlers
    @app.errorhandler(404)
    def not_found(error):
        from flask import render_template
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        from flask import render_template
        logger = logging.getLogger(__name__)
        logger.error(f"Internal server error: {error}", exc_info=True)
        return render_template('errors/500.html'), 500
    
    return app
