"""
Input validation utilities
"""
from typing import List, Optional
from io import BytesIO
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


def detect_image_type(data: bytes) -> Optional[str]:
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
    # HEIC/HEIF detection (starts with ftyp box)
    if len(data) >= 12:
        # HEIC files start with ftyp box, check for 'heic', 'heif', 'mif1', 'msf1'
        if data[4:8] == b"ftyp":
            brand = data[8:12].lower()
            if brand in [b"heic", b"heif", b"mif1", b"msf1"]:
                return "heic"
    return None


def convert_heic_to_jpeg(data: bytes) -> Optional[bytes]:
    """
    Convert HEIC/HEIF image data to JPEG format.
    Returns JPEG bytes if successful, None otherwise.
    """
    try:
        from PIL import Image
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            # pillow-heif not available, return None
            return None
        
        # Open HEIC image from bytes
        img = Image.open(BytesIO(data))
        
        # Convert to RGB if necessary (HEIC might have alpha channel)
        if img.mode in ('RGBA', 'LA', 'P'):
            # Create white background for transparency
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = rgb_img
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Save as JPEG to bytes
        output = BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        return output.getvalue()
    except Exception:
        # If conversion fails for any reason, return None
        return None







