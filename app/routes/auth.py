"""
Authentication routes
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, g
from werkzeug.security import generate_password_hash, check_password_hash
from app.middleware.csrf import validate_csrf, generate_csrf_token
from app.utils.validators import validate_auth_form_fields
from app.utils.helpers import clean_str, get_safe_redirect, parse_device_name
from app.config import Config
import sys
import secrets
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

# repo_root/app/routes/auth.py -> repo_root is 3 levels up
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
try:
    from database import PlayerDB
except ImportError:
    PlayerDB = None

bp = Blueprint('auth', __name__)

# Rate limiting for resend verification (3 requests per hour per email)
_resend_verification_attempts = defaultdict(list)
_RESEND_VERIFICATION_LIMIT = 3
_RESEND_VERIFICATION_WINDOW = timedelta(hours=1)

# Rate limiting for forgot password (3 requests per hour per email)
_forgot_password_attempts = defaultdict(list)
_FORGOT_PASSWORD_LIMIT = 3
_FORGOT_PASSWORD_WINDOW = timedelta(hours=1)

def _check_resend_rate_limit(email: str) -> tuple[bool, str]:
    """Check if email has exceeded rate limit for resend verification.
    Returns (allowed, message) tuple."""
    now = datetime.now()
    email_lower = email.lower()
    
    # Clean old attempts outside the window
    _resend_verification_attempts[email_lower] = [
        attempt_time for attempt_time in _resend_verification_attempts[email_lower]
        if now - attempt_time < _RESEND_VERIFICATION_WINDOW
    ]
    
    # Check if limit exceeded
    if len(_resend_verification_attempts[email_lower]) >= _RESEND_VERIFICATION_LIMIT:
        oldest_attempt = min(_resend_verification_attempts[email_lower])
        time_until_reset = _RESEND_VERIFICATION_WINDOW - (now - oldest_attempt)
        minutes_left = int(time_until_reset.total_seconds() / 60) + 1
        return False, f"Too many verification email requests. Please wait {minutes_left} minute(s) before requesting again."
    
    # Record this attempt
    _resend_verification_attempts[email_lower].append(now)
    return True, ""


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login"""
    if request.method == 'GET':
        return render_template('login.html')
    
    # POST request
    if not validate_csrf(request.form.get("csrf_token")):
        flash("Invalid form submission. Please try again.", "error")
        return redirect(url_for('auth.login'))
    
    email = clean_str(request.form.get('email', '')).lower()
    password = request.form.get('password', '')
    
    if not email or not password:
        flash("Email and password are required.", "error")
        return redirect(url_for('auth.login', next=request.form.get('next')))
    
    if not PlayerDB:
        flash("Database unavailable. Please contact support.", "error")
        return redirect(url_for('auth.login'))
    
    try:
        # Use threading timeout for cross-platform compatibility
        # This prevents the login from hanging indefinitely if database connection times out
        import threading
        import queue
        
        result_queue = queue.Queue()
        error_queue = queue.Queue()
        
        def db_operation():
            try:
                db = PlayerDB()
                user = db.get_user_by_email(email)
                db.close()
                result_queue.put(user)
            except Exception as e:
                error_queue.put(e)
        
        # Start database operation in a thread
        db_thread = threading.Thread(target=db_operation)
        db_thread.daemon = True
        db_thread.start()
        db_thread.join(timeout=15)  # 15 second timeout
        
        if db_thread.is_alive():
            # Thread is still running, operation timed out
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Login timeout for email: {email}")
            flash("Database connection timed out. Please try again in a moment.", "error")
            return redirect(url_for('auth.login'))
        
        # Check for errors
        if not error_queue.empty():
            raise error_queue.get()
        
        # Get result
        if result_queue.empty():
            user = None
        else:
            user = result_queue.get()
        
        if not user or not check_password_hash(user.get("password_hash", ""), password):
            flash("Invalid email or password.", "error")
            return redirect(url_for('auth.login', next=request.form.get('next')))
        
        # Check if account is deactivated (but skip check for admins)
        if not user.get("is_admin"):
            is_active = user.get("is_active")
            if is_active is not None and not is_active:
                flash("Your account has been deactivated. Please contact an administrator.", "error")
                return redirect(url_for('auth.account_deactivated'))
            
            # Check email verification
            email_verified = user.get("email_verified", 0)
            if not email_verified:
                flash("Please verify your email address before signing in. Check your inbox for the verification link.", "warning")
                return redirect(url_for('auth.verify_email_pending', email=email))

        # --- Device limit check ---
        device_id = request.cookies.get("device_id") or getattr(g, "_new_device_id", None) or str(__import__("uuid").uuid4())
        is_admin = bool(user.get("is_admin", False))

        if not is_admin:
            try:
                db2 = PlayerDB()
                active_sessions = db2.get_active_sessions(user["id"])
                already_active = any(s["device_id"] == device_id for s in active_sessions)
                device_count = len({s["device_id"] for s in active_sessions})

                if not already_active and device_count >= Config.MAX_DEVICES_PER_USER:
                    db2.close()
                    return redirect(url_for("auth.manage_devices_login"))

                db2.close()
            except Exception:
                pass  # Fail-open: allow login if device check fails

        # --- Create device session record ---
        import time as _time
        session_token = secrets.token_urlsafe(32)
        try:
            db3 = PlayerDB()
            ua = request.headers.get("User-Agent", "")
            db3.create_user_session(
                user_id=user["id"],
                device_id=device_id,
                session_token=session_token,
                device_name=parse_device_name(ua),
                user_agent=ua,
                ip_address=request.remote_addr,
            )
            db3.cleanup_expired_sessions()
            db3.close()
        except Exception:
            pass  # Fail-open

        # Set session
        session.pop('csrf_token', None)
        session['user_id'] = user['id']
        session['first_name'] = user.get('first_name', '')
        session['last_name'] = user.get('last_name', '')
        session['is_admin'] = is_admin
        session['_session_token'] = session_token
        session['_device_id'] = device_id
        session.permanent = True  # Make session persist across browser restarts

        # Cache full user object (exclude password_hash for security)
        user_cache = {k: v for k, v in user.items() if k != "password_hash"}
        session["_cached_user"] = user_cache
        session["_user_cache_timestamp"] = _time.time()

        generate_csrf_token()

        flash("Signed in successfully.", "success")
        # Try to redirect to pages.home, fallback to home
        try:
            return redirect(get_safe_redirect("pages.home"))
        except:
            return redirect(get_safe_redirect("home"))
    
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Login error: {exc}", exc_info=True)
        # Check if it's a connection/timeout error
        error_msg = str(exc).lower()
        if "timeout" in error_msg or "connection" in error_msg:
            flash("Database connection failed. Please try again in a moment.", "error")
        else:
            flash("An error occurred during login. Please try again.", "error")
        return redirect(url_for('auth.login'))


@bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration"""
    if request.method == 'GET':
        return render_template('register.html', csrf_token=generate_csrf_token())
    
    # POST request
    if not validate_csrf(request.form.get("csrf_token")):
        flash("Invalid form submission. Please try again.", "error")
        return redirect(url_for('auth.register'))
    
    email = clean_str(request.form.get('email', '')).lower()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    first_name = clean_str(request.form.get('first_name', ''))
    last_name = clean_str(request.form.get('last_name', ''))
    invite_code = clean_str(request.form.get('invite_code', '')).upper().strip()
    
    # Validate invite code
    if not invite_code:
        flash("Invite code is required to create an account.", "error")
        return redirect(url_for('auth.register', next=request.form.get('next')))
    
    errors = validate_auth_form_fields(email, password, first_name, last_name, confirm_password)
    if errors:
        for error in errors:
            flash(error, "error")
        return redirect(url_for('auth.register', next=request.form.get('next')))
    
    if not PlayerDB:
        flash("Database unavailable. Please contact support.", "error")
        return redirect(url_for('auth.register'))
    
    try:
        db = PlayerDB()
        
        # Check if invite code is valid
        invite = db.get_invite_code(invite_code)
        if not invite:
            flash("Invalid invite code. Please check and try again.", "error")
            db.close()
            return redirect(url_for('auth.register', next=request.form.get('next')))
        
        if not invite.get("is_active") or invite.get("used_at"):
            flash("This invite code has already been used or is no longer active.", "error")
            db.close()
            return redirect(url_for('auth.register', next=request.form.get('next')))
        
        existing = db.get_user_by_email(email)
        if existing:
            flash("An account with that email already exists. Please sign in.", "error")
            db.close()
            return redirect(url_for('auth.login'))
        
        # Check if email is from sequencebiolab.com domain - auto-admin
        # Security: Use exact domain match (email is already lowercased)
        ADMIN_DOMAIN = '@sequencebiolab.com'
        is_admin = email.endswith(ADMIN_DOMAIN) and email.count('@') == 1
        
        # Auto-verify email for admin accounts since they're trusted
        email_verified = is_admin
        
        password_hash = generate_password_hash(password)
        user_id = db.create_user(email, password_hash, first_name, last_name, is_admin=is_admin, email_verified=email_verified)
        
        # Log admin account creation for audit purposes
        if is_admin:
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Admin account auto-created: {email} (user_id: {user_id})")
        
        # Mark invite code as used
        db.use_invite_code(invite_code, user_id)
        
        # Generate verification token (only needed for non-admin accounts)
        import secrets
        from app.services.email_service import EmailService
        verification_token = secrets.token_urlsafe(32)
        db.create_verification_token(user_id, verification_token, expires_in_hours=24)
        
        # Send verification email (skip for admin accounts)
        base_url = request.host_url.rstrip('/')
        email_sent = True
        if not is_admin:
            email_sent = EmailService.send_verification_email(
                email, 
                f"{first_name} {last_name}", 
                verification_token,
                base_url
            )
        
        db.delete_expired_tokens()  # Cleanup old tokens
        db.close()
        
        # Redirect based on account type
        if is_admin:
            flash("Admin account created successfully! You can now sign in.", "success")
            return redirect(url_for('auth.login'))
        elif email_sent:
            flash("Account created! Please check your email to verify your account.", "success")
        else:
            flash("Account created! However, we couldn't send the verification email. Please use the resend button below or contact support.", "warning")
        return redirect(url_for('auth.verify_email_pending', email=email))
    
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Registration error: {exc}", exc_info=True)
        flash(f"Could not create account: {exc}", "error")
        return redirect(url_for('auth.register'))


@bp.route('/logout', methods=['POST'])
def logout():
    """User logout"""
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400, description="Invalid CSRF token")

    # Revoke device session in DB
    session_token = session.get("_session_token")
    user_id = session.get("user_id")
    if session_token and user_id and PlayerDB:
        try:
            db = PlayerDB()
            db_sess = db.get_session_by_token(session_token)
            if db_sess:
                db.revoke_session(db_sess["id"], user_id)
            db.close()
        except Exception:
            pass

    for key in ("user_id", "first_name", "last_name", "is_admin", "_session_token", "_device_id"):
        session.pop(key, None)
    # Clear user cache
    session.pop("_cached_user", None)
    session.pop("_user_cache_timestamp", None)
    session.pop("_user_cache_version", None)
    session.pop('csrf_token', None)
    generate_csrf_token()

    flash("You have been logged out.", "info")
    return redirect(url_for('pages.home'))


@bp.route('/manage-devices-login', methods=['GET'])
def manage_devices_login():
    """Shown when a login is blocked because the device limit is reached."""
    return render_template("manage_devices_login.html")


@bp.route('/verify-email', methods=['GET'])
def verify_email():
    """Handle email verification"""
    token = request.args.get('token')
    
    if not token:
        flash("Invalid verification link.", "error")
        return redirect(url_for('auth.login'))
    
    if not PlayerDB:
        flash("Database unavailable. Please contact support.", "error")
        return redirect(url_for('auth.login'))
    
    try:
        db = PlayerDB()
        token_record = db.get_verification_token(token)
        
        if not token_record:
            flash("Invalid or expired verification link. Please request a new one.", "error")
            db.close()
            return redirect(url_for('auth.login'))
        
        user_id = token_record['user_id']
        
        # Mark email as verified
        db.mark_email_verified(user_id)
        db.mark_token_used(token_record['id'])
        db.delete_expired_tokens()  # Cleanup
        db.close()
        
        flash("Email verified successfully! You can now sign in.", "success")
        return redirect(url_for('auth.login'))
        
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Email verification error: {exc}", exc_info=True)
        flash("An error occurred during verification. Please try again.", "error")
        return redirect(url_for('auth.login'))


@bp.route('/verify-email-pending', methods=['GET'])
def verify_email_pending():
    """Show pending verification page"""
    from app.middleware.csrf import generate_csrf_token
    email = request.args.get('email', '')
    return render_template('verify_email_pending.html', email=email, csrf_token=generate_csrf_token())


@bp.route('/resend-verification', methods=['POST'])
def resend_verification():
    """Resend verification email with rate limiting"""
    if not validate_csrf(request.form.get("csrf_token")):
        flash("Invalid form submission. Please try again.", "error")
        return redirect(url_for('auth.verify_email_pending'))
    
    email = clean_str(request.form.get('email', '')).lower()
    
    if not email:
        flash("Email is required.", "error")
        return redirect(url_for('auth.verify_email_pending'))
    
    # Check rate limit
    allowed, rate_limit_msg = _check_resend_rate_limit(email)
    if not allowed:
        flash(rate_limit_msg, "error")
        return redirect(url_for('auth.verify_email_pending', email=email))
    
    if not PlayerDB:
        flash("Database unavailable. Please contact support.", "error")
        return redirect(url_for('auth.verify_email_pending', email=email))
    
    try:
        db = PlayerDB()
        user = db.get_user_by_email(email)
        
        if not user:
            flash("No account found with that email.", "error")
            db.close()
            return redirect(url_for('auth.verify_email_pending', email=email))
        
        if user.get('email_verified'):
            flash("This email is already verified. You can sign in.", "info")
            db.close()
            return redirect(url_for('auth.login'))
        
        # Generate new token
        import secrets
        from app.services.email_service import EmailService
        verification_token = secrets.token_urlsafe(32)
        db.create_verification_token(user['id'], verification_token, expires_in_hours=24)
        
        # Send email
        base_url = request.host_url.rstrip('/')
        email_sent = EmailService.send_verification_email(
            email,
            f"{user.get('first_name', '')} {user.get('last_name', '')}",
            verification_token,
            base_url
        )
        
        db.delete_expired_tokens()  # Cleanup
        db.close()
        
        if email_sent:
            flash("Verification email sent! Please check your inbox.", "success")
        else:
            flash("Failed to send verification email. Please check your SMTP configuration or contact support.", "error")
        return redirect(url_for('auth.verify_email_pending', email=email))
        
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Resend verification error: {exc}", exc_info=True)
        flash("An error occurred. Please try again.", "error")
        return redirect(url_for('auth.verify_email_pending', email=email))


@bp.route('/account-deactivated', methods=['GET'])
def account_deactivated():
    """Display deactivated account page"""
    return render_template('account_deactivated.html')


def _check_forgot_password_rate_limit(email: str) -> tuple[bool, str]:
    """Check if email has exceeded rate limit for forgot password requests.
    Returns (allowed, message) tuple."""
    now = datetime.now()
    email_lower = email.lower()

    # Clean old attempts outside the window
    _forgot_password_attempts[email_lower] = [
        attempt_time for attempt_time in _forgot_password_attempts[email_lower]
        if now - attempt_time < _FORGOT_PASSWORD_WINDOW
    ]

    # Check if limit exceeded
    if len(_forgot_password_attempts[email_lower]) >= _FORGOT_PASSWORD_LIMIT:
        oldest_attempt = min(_forgot_password_attempts[email_lower])
        time_until_reset = _FORGOT_PASSWORD_WINDOW - (now - oldest_attempt)
        minutes_left = int(time_until_reset.total_seconds() / 60) + 1
        return False, f"Too many password reset requests. Please wait {minutes_left} minute(s) before trying again."

    # Record this attempt
    _forgot_password_attempts[email_lower].append(now)
    return True, ""


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Forgot password — request a reset link"""
    if request.method == 'GET':
        return render_template('forgot_password.html', csrf_token=generate_csrf_token())

    # POST request
    if not validate_csrf(request.form.get("csrf_token")):
        flash("Invalid form submission. Please try again.", "error")
        return redirect(url_for('auth.forgot_password'))

    email = clean_str(request.form.get('email', '')).lower()

    if not email:
        flash("Email address is required.", "error")
        return redirect(url_for('auth.forgot_password'))

    # Always redirect to the same confirmation page regardless of whether the
    # email exists — this prevents email enumeration attacks.
    SAFE_RESPONSE = redirect(url_for('auth.forgot_password_sent'))

    # Rate limit check (still return safe response on failure to avoid enumeration)
    allowed, rate_limit_msg = _check_forgot_password_rate_limit(email)
    if not allowed:
        flash(rate_limit_msg, "error")
        return redirect(url_for('auth.forgot_password'))

    if not PlayerDB:
        return SAFE_RESPONSE

    try:
        db = PlayerDB()
        user = db.get_user_by_email(email)

        # Only send if the user exists and has a verified email
        if user and user.get('email_verified') and user.get('is_active', 1):
            import secrets as _secrets
            from app.services.email_service import EmailService
            reset_token = _secrets.token_urlsafe(32)
            db.create_password_reset_token(user['id'], reset_token, expires_in_hours=1)

            base_url = request.host_url.rstrip('/')
            EmailService.send_password_reset_email(
                email,
                f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                reset_token,
                base_url
            )

        db.close()
    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Forgot password error: {exc}", exc_info=True)
        # Still show the safe response — don't leak errors to the user

    return SAFE_RESPONSE


@bp.route('/forgot-password-sent', methods=['GET'])
def forgot_password_sent():
    """Confirmation page shown after submitting a forgot-password request"""
    return render_template('forgot_password_sent.html')


@bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    """Reset password using a token from email"""
    if request.method == 'GET':
        token = request.args.get('token', '').strip()

        if not token:
            flash("Invalid or missing reset link.", "error")
            return redirect(url_for('auth.forgot_password'))

        if not PlayerDB:
            flash("Database unavailable. Please contact support.", "error")
            return redirect(url_for('auth.login'))

        try:
            db = PlayerDB()
            token_record = db.get_password_reset_token(token)
            db.close()
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Reset password token lookup error: {exc}", exc_info=True)
            flash("An error occurred. Please try again.", "error")
            return redirect(url_for('auth.forgot_password'))

        if not token_record:
            flash("This password reset link is invalid or has expired. Please request a new one.", "error")
            return redirect(url_for('auth.forgot_password'))

        return render_template('reset_password.html', token=token, csrf_token=generate_csrf_token())

    # POST request
    if not validate_csrf(request.form.get("csrf_token")):
        flash("Invalid form submission. Please try again.", "error")
        return redirect(url_for('auth.forgot_password'))

    token = request.form.get('token', '').strip()
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')

    if not token:
        flash("Invalid reset link. Please request a new one.", "error")
        return redirect(url_for('auth.forgot_password'))

    # Validate password
    if not new_password:
        flash("Password is required.", "error")
        return render_template('reset_password.html', token=token, csrf_token=generate_csrf_token())

    if len(new_password) < 8:
        flash("Password must be at least 8 characters.", "error")
        return render_template('reset_password.html', token=token, csrf_token=generate_csrf_token())

    if new_password != confirm_password:
        flash("Passwords do not match.", "error")
        return render_template('reset_password.html', token=token, csrf_token=generate_csrf_token())

    if not PlayerDB:
        flash("Database unavailable. Please contact support.", "error")
        return redirect(url_for('auth.login'))

    try:
        db = PlayerDB()
        token_record = db.get_password_reset_token(token)

        if not token_record:
            db.close()
            flash("This password reset link is invalid or has expired. Please request a new one.", "error")
            return redirect(url_for('auth.forgot_password'))

        user_id = token_record['user_id']

        # Update the password
        new_hash = generate_password_hash(new_password)
        db.update_user_password(user_id, new_hash)

        # Mark the token as used
        db.mark_reset_token_used(token_record['id'])

        # Revoke ALL active sessions for this user (security: sign out all devices)
        db.revoke_all_sessions(user_id, except_session_token=None)

        db.close()

        # Clear the current Flask session in case the user happened to be logged in
        session.clear()
        generate_csrf_token()

        flash("Your password has been reset successfully. Please sign in with your new password.", "success")
        return redirect(url_for('auth.login'))

    except Exception as exc:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Reset password error: {exc}", exc_info=True)
        flash("An error occurred while resetting your password. Please try again.", "error")
        return redirect(url_for('auth.forgot_password'))

