"""
Request context processors
"""
from flask import g, url_for
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
        
        def avatar_url(target_user=None) -> str:
            """Return best avatar URL for a user (DB-backed or static fallback)."""
            u = target_user or user or {}
            if not u:
                return url_for("static", filename="sequence-logo.png")

            profile_path = (u.get("profile_image_path") or "").strip()
            user_id = u.get("id")

            # Prefer DB-backed avatars when marker is present, or for legacy Render file paths
            # (Render filesystem is ephemeral, so old static upload paths will 404).
            use_db_avatar = (
                profile_path.startswith("avatar:")
                or profile_path == "avatar"
                or profile_path.startswith("uploads/profile_photos/")
            )

            try:
                version = int(float(u.get("updated_at") or 0))
            except Exception:
                version = int(user_id or 0)

            if user_id and use_db_avatar:
                return f"{url_for('pages.user_avatar', user_id=int(user_id))}?v={version}"

            if profile_path:
                return f"{url_for('static', filename=profile_path)}?v={version}"

            return url_for("static", filename="sequence-logo.png")

        return {
            "app_settings": settings,
            "app_theme": theme,
            "csrf_token": generate_csrf_token(),
            "current_user": user,
            "avatar_url": avatar_url,
        }

