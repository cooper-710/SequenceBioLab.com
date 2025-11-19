"""
Input validation utilities
"""
from typing import List
from app.utils.helpers import clean_str


def validate_auth_form_fields(
    email: str, 
    password: str, 
    first_name: str = "", 
    last_name: str = "", 
    confirm: str = ""
) -> List[str]:
    """Perform basic validation for authentication forms."""
    errors = []
    
    email = clean_str(email)
    if not email:
        errors.append("Email is required.")
    elif "@" not in email or "." not in email.split("@")[-1]:
        errors.append("Please enter a valid email address.")
    
    first_name = clean_str(first_name)
    last_name = clean_str(last_name)
    if first_name is not None and not first_name:
        errors.append("First name is required.")
    if last_name is not None and not last_name:
        errors.append("Last name is required.")
    
    if not password or len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    
    if confirm and password != confirm:
        errors.append("Password confirmation does not match.")
    
    return errors


def detect_image_type(data: bytes) -> str:
    """Detect image type for a small subset of formats using magic headers."""
    if not data or len(data) < 4:
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None



