"""
CSRF protection utilities
"""
import secrets
from flask import session


def generate_csrf_token() -> str:
    """Generate or retrieve CSRF token from session"""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["csrf_token"] = token
    return token


def validate_csrf(token: str) -> bool:
    """Validate CSRF token"""
    if not token:
        return False
    return token == session.get("csrf_token")



