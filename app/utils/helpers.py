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


def parse_device_name(user_agent: str) -> str:
    """Parse a User-Agent string into a friendly device name like 'Chrome on macOS'."""
    if not user_agent:
        return "Unknown device"
    ua = user_agent

    # Detect browser
    browser = "Unknown browser"
    if "Edg/" in ua or "Edge/" in ua:
        browser = "Edge"
    elif "OPR/" in ua or "Opera" in ua:
        browser = "Opera"
    elif "Chrome/" in ua and "Safari/" in ua:
        browser = "Chrome"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Safari/" in ua and "Chrome/" not in ua:
        browser = "Safari"
    elif "MSIE" in ua or "Trident/" in ua:
        browser = "Internet Explorer"

    # Detect OS
    os_name = "Unknown OS"
    if "iPhone" in ua:
        os_name = "iPhone"
    elif "iPad" in ua:
        os_name = "iPad"
    elif "Android" in ua:
        os_name = "Android"
    elif "Mac OS X" in ua or "Macintosh" in ua:
        os_name = "macOS"
    elif "Windows" in ua:
        os_name = "Windows"
    elif "Linux" in ua:
        os_name = "Linux"
    elif "CrOS" in ua:
        os_name = "ChromeOS"

    return f"{browser} on {os_name}"


def resolve_default_season_start() -> str:
    """Resolve the default season start date from settings."""
    settings = getattr(g, "app_settings", {}) or Config.get_settings()
    report_defaults = settings.get("reports", {}) if isinstance(settings, dict) else {}
    return clean_str(report_defaults.get("default_season_start")) or "2025-03-20"





