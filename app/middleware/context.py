"""
Request context processors
"""
from flask import g
from app.config import Config
from app.middleware.csrf import generate_csrf_token


def setup_context_processors(app):
    """Setup context processors"""
    
    @app.before_request
    def attach_settings_to_request():
        """Attach settings to request context"""
        g.app_settings = Config.get_settings()
        generate_csrf_token()  # Ensure CSRF token exists
    
    @app.context_processor
    def inject_app_settings():
        """Inject app settings and theme into templates"""
        settings = getattr(g, "app_settings", None) or Config.get_settings()
        general = settings.get("general", {}) if isinstance(settings, dict) else {}
        theme = general.get("theme", "dark")
        user = getattr(g, "user", None)
        
        user_theme = (user or {}).get("theme_preference")
        if user_theme:
            theme = user_theme
        
        return {
            "app_settings": settings,
            "app_theme": theme,
            "csrf_token": generate_csrf_token(),
            "current_user": user
        }

