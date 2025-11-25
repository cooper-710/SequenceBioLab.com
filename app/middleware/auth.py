"""
Authentication middleware and decorators
"""
from functools import wraps
from flask import session, g, redirect, url_for, flash, request, abort
from app.config import Config
from app.constants import AUTH_EXEMPT_ENDPOINTS
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
try:
    from database import PlayerDB
except ImportError:
    PlayerDB = None


def setup_auth_middleware(app):
    """Setup authentication middleware"""
    
    @app.before_request
    def load_authenticated_user():
        """Load authenticated user for request"""
        g.user = None
        session.setdefault("is_admin", False)
        user_id = session.get("user_id")
        
        if not user_id or not PlayerDB:
            session["is_admin"] = False
            return
        
        try:
            db = PlayerDB()
            g.user = db.get_user_by_id(user_id)
            db.close()
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to load user {user_id}: {exc}")
            g.user = None
            # Don't clear session on transient connection errors
            # Only clear if it's a permanent auth failure
            if "timeout" not in str(exc).lower() and "connection" not in str(exc).lower():
                session.clear()
        
        # Check if account is deactivated (but skip check for admins)
        if g.user and not g.user.get("is_admin"):
            is_active = g.user.get("is_active")
            if is_active is not None and not is_active:
                # Clear session and redirect to deactivated page
                session.clear()
                endpoint = request.endpoint or ""
                # Allow access to deactivated page and auth endpoints
                if endpoint not in {"auth.account_deactivated", "auth.login", "auth.register", "auth.verify_email", 
                                    "auth.verify_email_pending", "auth.resend_verification", "static"}:
                    from flask import redirect, url_for
                    return redirect(url_for("auth.account_deactivated"))
        
        session["is_admin"] = bool(g.user.get("is_admin")) if g.user else False
        if g.user:
            session["first_name"] = g.user.get("first_name", "")
            session["last_name"] = g.user.get("last_name", "")
            if g.user.get("theme_preference"):
                session["theme_preference"] = g.user["theme_preference"]
    
    @app.before_request
    def enforce_global_authentication():
        """Redirect unauthenticated users to login"""
        if session.get("user_id"):
            return
        
        endpoint = request.endpoint or ""
        
        # Allow access to exempt endpoints
        if endpoint in AUTH_EXEMPT_ENDPOINTS:
            return
        
        # Allow access to static files
        if endpoint.startswith("static"):
            return
        
        # Allow access to favicon and auth endpoints (both old and new)
        if endpoint in {"favicon", "login", "register", "auth.login", "auth.register", "auth.account_deactivated", 
                        "auth.verify_email", "auth.verify_email_pending", "auth.resend_verification"}:
            return
        
        # For routes still in app.py (not yet migrated), use old endpoint names
        # This is a temporary bridge until all routes are migrated to blueprints
        next_path = request.path
        try:
            # Try new blueprint routes first
            login_url = url_for("auth.login")
            register_url = url_for("auth.register")
            if next_path in {login_url, register_url}:
                next_path = None
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=next_path))
        except Exception:
            # Fallback to old routes in app.py
            if next_path in {"/login", "/register"}:
                next_path = None
            flash("Please log in to continue.", "warning")
            return redirect(f"/login?next={next_path}" if next_path else "/login")


def login_required(fn):
    """Decorator to require authentication"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    """Decorator to require admin privileges"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            # For API endpoints, return JSON error instead of redirect
            if request.path.startswith('/api/'):
                from flask import jsonify
                return jsonify({"error": "Authentication required"}), 401
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.path))
        if not session.get("is_admin"):
            # For API endpoints, return JSON error instead of redirect
            if request.path.startswith('/api/'):
                from flask import jsonify
                return jsonify({"error": "Admin privileges required"}), 403
            flash("Admin privileges are required to access that page.", "error")
            return redirect(url_for("pages.home"))
        return fn(*args, **kwargs)
    return wrapper


def ensure_default_admin():
    """Ensure default admin user exists"""
    if not PlayerDB:
        return
    
    from werkzeug.security import generate_password_hash, check_password_hash
    import logging
    import time
    
    logger = logging.getLogger(__name__)
    
    default_email = Config.DEFAULT_ADMIN_EMAIL
    default_password = Config.DEFAULT_ADMIN_PASSWORD
    
    if not default_password:
        logger.warning("DEFAULT_ADMIN_PASSWORD not set. Admin creation skipped.")
        return
    
    max_retries = 3
    retry_delay = 2.0
    
    for attempt in range(max_retries):
        try:
            db = PlayerDB()
            existing = db.get_user_by_email(default_email)
            password_hash = generate_password_hash(default_password)
            
            if not existing:
                db.create_user(
                    email=default_email,
                    password_hash=password_hash,
                    first_name="Sequence",
                    last_name="Admin",
                    is_admin=True,
                    email_verified=True  # Admin accounts are pre-verified
                )
                logger.info(f"Default admin user created: {default_email}")
            else:
                if not existing.get("is_admin"):
                    db.set_user_admin(existing["id"], True)
                if not check_password_hash(existing.get("password_hash", ""), default_password):
                    db.update_user_password(existing["id"], password_hash)
            db.close()
            break  # Success, exit retry loop
        except Exception as exc:
            if attempt < max_retries - 1:
                logger.warning(f"Unable to ensure default admin user (attempt {attempt + 1}/{max_retries}): {exc}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue
            # Log but don't crash - app can start without admin user
            # Admin can be created manually if needed
            logger.error(f"Unable to ensure default admin user after {max_retries} attempts: {exc}")
            logger.warning("App will continue without default admin. Check DATABASE_URL configuration.")

