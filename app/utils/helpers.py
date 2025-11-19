"""
General helper utilities
"""
import re
from typing import Optional
from flask import g, request, url_for
from app.config import Config


def parse_bool(value, default=False):
    """Coerce a value into a boolean with a default fallback."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def clean_str(value):
    """Return a trimmed string representation or empty string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def sanitize_filename_component(value: str) -> str:
    """Sanitize a filename component by removing invalid characters."""
    return re.sub(r'[\\/:*?"<>|]+', "", (value or "")).strip()


def get_safe_redirect(default_endpoint: str = "pages.home") -> str:
    """Return a safe redirect target within this application."""
    target = request.args.get("next") or request.form.get("next")
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for(default_endpoint)


def current_player_full_name() -> Optional[str]:
    """Get the current player's full name from request context."""
    user = getattr(g, "user", None)
    if not user:
        return None
    first = (user.get("first_name") or "").strip()
    last = (user.get("last_name") or "").strip()
    parts = [part for part in (first, last) if part]
    if not parts:
        return None
    return " ".join(parts)


def resolve_default_season_start() -> str:
    """Resolve the default season start date from settings."""
    settings = getattr(g, "app_settings", {}) or Config.get_settings()
    report_defaults = settings.get("reports", {}) if isinstance(settings, dict) else {}
    return clean_str(report_defaults.get("default_season_start")) or "2025-03-20"



