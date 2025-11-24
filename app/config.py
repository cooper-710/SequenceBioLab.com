"""
Application configuration management
"""
import os
from pathlib import Path
from functools import lru_cache
import secrets
import settings_manager


def _get_secret_key_from_settings() -> str:
    """Get secret key from settings or generate new one"""
    settings = settings_manager.load_settings()
    general = settings.get("general", {})
    secret_key = general.get("secret_key")
    
    if secret_key:
        return secret_key
    
    # Generate new secret key
    secret_key = secrets.token_hex(32)
    try:
        settings_manager.update_settings({"general": {"secret_key": secret_key}})
    except Exception:
        pass  # Best effort
    
    return secret_key


class Config:
    """Application configuration"""
    
    # Base directories
    ROOT_DIR = Path(__file__).parent.parent.resolve()
    
    # Database
    DATABASE_PATH = ROOT_DIR / "build" / "database" / "players.db"
    
    # Data directories
    DATA_DIR = ROOT_DIR / "data"
    PDF_OUTPUT_DIR = ROOT_DIR / "build" / "pdf"
    UPLOAD_DIR = ROOT_DIR / "static" / "uploads" / "profile_photos"
    PLAYER_DOCS_DIR = ROOT_DIR / "build" / "player_documents"
    WORKOUT_DOCS_DIR = ROOT_DIR / "build" / "workouts"
    CACHE_DIR = ROOT_DIR / "build" / "cache"
    
    # Application settings - lazy loaded to avoid circular import issues
    _secret_key = None
    
    @classmethod
    def _get_secret_key(cls):
        """Lazy load secret key"""
        if cls._secret_key is None:
            cls._secret_key = os.environ.get("SECRET_KEY") or _get_secret_key_from_settings()
        return cls._secret_key
    
    @classmethod
    def get_secret_key(cls):
        """Get secret key - use this method instead of SECRET_KEY attribute"""
        return cls._get_secret_key()
    
    # For backward compatibility, we'll set SECRET_KEY after class definition
    DEBUG = os.environ.get("FLASK_ENV", "development") != "production"
    PORT = int(os.environ.get("PORT", 5001))
    
    # File uploads
    MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB
    ALLOWED_PROFILE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    ALLOWED_PROFILE_TYPES = {"png", "jpeg", "gif", "webp"}
    WORKOUT_ALLOWED_EXTENSIONS = {".pdf"}
    WORKOUT_CATEGORY = "workout"
    
    # Report generation
    REPORT_TIMEOUT = 600  # 10 minutes
    REPORT_LEAD_DAYS = 5
    
    # Job queue
    JOB_STATUS_MAX_AGE = 3600  # 1 hour
    
    # MLB API
    USE_MOCK_SCHEDULE = os.environ.get("USE_MOCK_SCHEDULE", "0").strip().lower() in {"1", "true", "yes", "on"}
    
    # Default admin
    DEFAULT_ADMIN_EMAIL = os.environ.get("DEFAULT_ADMIN_EMAIL", "admin@sequencebiolab.com")
    DEFAULT_ADMIN_PASSWORD = os.environ.get("DEFAULT_ADMIN_PASSWORD", "1234")
    
    # Contact information
    CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "cooperrobinson@sequencebiolab.com")
    
    # Series management
    SERIES_AUTO_DELETE_GRACE_SECONDS = 0
    
    @classmethod
    def ensure_directories(cls):
        """Create required directories"""
        for dir_path in [
            cls.DATA_DIR, cls.PDF_OUTPUT_DIR, cls.UPLOAD_DIR,
            cls.PLAYER_DOCS_DIR, cls.WORKOUT_DOCS_DIR, cls.CACHE_DIR,
            cls.DATABASE_PATH.parent
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    @lru_cache(maxsize=1)
    def get_settings(cls):
        """Get cached application settings"""
        return settings_manager.load_settings()
    
    @classmethod
    def refresh_settings_cache(cls):
        """Clear settings cache"""
        cls.get_settings.cache_clear()


# Set SECRET_KEY as class attribute after class definition to avoid circular import issues
Config.SECRET_KEY = Config._get_secret_key()

