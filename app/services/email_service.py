"""
Email service for sending verification emails
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import os
import logging
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)

class EmailService:
    """Service for sending emails"""
    
    @staticmethod
    def get_smtp_config():
        """Get SMTP configuration from environment variables or settings file"""
        # First try environment variables (highest priority)
        smtp_host = os.environ.get('SMTP_HOST')
        smtp_port = os.environ.get('SMTP_PORT')
        smtp_username = os.environ.get('SMTP_USERNAME')
        smtp_password = os.environ.get('SMTP_PASSWORD')
        smtp_use_tls = os.environ.get('SMTP_USE_TLS')
        smtp_from_email = os.environ.get('SMTP_FROM_EMAIL')
        smtp_from_name = os.environ.get('SMTP_FROM_NAME')
        
        # Always try to load from settings file as fallback
        try:
            import settings_manager
            settings = settings_manager.load_settings()
            smtp_config = settings.get('smtp', {})
            
            # Use settings file values only if not set in environment variables
            if not smtp_host:
                smtp_host = smtp_config.get('host')
            if not smtp_port:
                smtp_port = smtp_config.get('port')
            if not smtp_username:
                smtp_username = smtp_config.get('username')
            if not smtp_password:
                smtp_password = smtp_config.get('password')
            if smtp_use_tls is None:
                smtp_use_tls = smtp_config.get('use_tls')
            # Always check settings for from_email and from_name if not in env
            # Check if from_email exists in settings (even if empty string)
            if smtp_from_email is None:
                settings_from_email = smtp_config.get('from_email')
                if settings_from_email:  # Only use if it's a non-empty string
                    smtp_from_email = settings_from_email
            if smtp_from_name is None:
                settings_from_name = smtp_config.get('from_name')
                if settings_from_name:  # Only use if it's a non-empty string
                    smtp_from_name = settings_from_name
                
            logger.info(f"SMTP config loaded - from_email={smtp_from_email}, from_name={smtp_from_name}, settings_from_email={smtp_config.get('from_email')}")
            print(f"DEBUG: SMTP config - from_email={smtp_from_email}, settings_from_email={smtp_config.get('from_email')}")
        except Exception as e:
            logger.error(f"Could not load SMTP config from settings: {e}")
            print(f"ERROR loading SMTP from settings: {e}")
        
        # Handle use_tls - can be bool, string, or None
        if smtp_use_tls is None:
            use_tls = True
        elif isinstance(smtp_use_tls, str):
            use_tls = smtp_use_tls.lower() in ('true', '1', 'yes', 'on')
        else:
            use_tls = bool(smtp_use_tls)
        
        # Handle port - default to 587 if not specified (standard SMTP port, not a credential)
        port = 587
        if smtp_port:
            try:
                port = int(smtp_port)
            except (ValueError, TypeError):
                port = 587
        
        # No hardcoded fallbacks for credentials or email addresses
        return {
            'host': smtp_host or '',
            'port': port,
            'username': smtp_username or '',
            'password': smtp_password or '',
            'use_tls': use_tls,
            'from_email': smtp_from_email or '',
            'from_name': smtp_from_name or ''
        }
    
    @staticmethod
    def send_verification_email(user_email: str, user_name: str, verification_token: str, base_url: str = None):
        """Send email verification email"""
        config = EmailService.get_smtp_config()
        
        # Debug: Print config (without password)
        logger.info(f"SMTP Config: host={config['host']}, port={config['port']}, username={config['username']}, use_tls={config['use_tls']}, from_email={config['from_email']}, from_name={config['from_name']}")
        print(f"DEBUG: SMTP Config - host={config['host']}, port={config['port']}, username={config['username']}, password_set={bool(config['password'])}, from_email={config['from_email']}, from_name={config['from_name']}")
        
        if not config['username'] or not config['password']:
            error_msg = "SMTP not configured. Cannot send verification email. Please set SMTP_USERNAME and SMTP_PASSWORD environment variables or configure in config/settings.json"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}")
            print(f"DEBUG: username='{config['username']}', password_set={bool(config['password'])}")
            return False
        
        if not config['from_email']:
            error_msg = "SMTP from_email not configured. Cannot send verification email. Please set SMTP_FROM_EMAIL environment variable or configure in config/settings.json"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}")
            return False
        
        if not config['host']:
            error_msg = "SMTP host not configured. Cannot send verification email. Please set SMTP_HOST environment variable or configure in config/settings.json"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}")
            return False
        
        try:
            # Generate verification URL
            if not base_url:
                base_url = os.environ.get('BASE_URL', 'http://localhost:5001')
            verification_url = f"{base_url}/verify-email?token={verification_token}"
            
            # Create email with related parts for inline images
            msg = MIMEMultipart('related')
            msg['Subject'] = 'Verify Your Email - Sequence BioLab'
            # Format From header - use name if provided, otherwise just email
            if config['from_name']:
                msg['From'] = f"{config['from_name']} <{config['from_email']}>"
            else:
                msg['From'] = config['from_email']
            msg['To'] = user_email
            
            # Create alternative part for text and HTML
            msg_alternative = MIMEMultipart('alternative')
            msg.attach(msg_alternative)
            
            # Email body (plain text)
            text_body = f"""
Hello {user_name},

Thank you for creating an account with Sequence BioLab!

Please verify your email address by clicking the link below:

{verification_url}

This link will expire in 24 hours.

If you didn't create this account, you can safely ignore this email.

Best regards,
Sequence BioLab Team
"""
            
            # Load and attach logo as inline image
            logo_cid = None
            try:
                # Try multiple possible paths (relative to project root)
                possible_paths = [
                    Path(__file__).parent.parent.parent / "static" / "sequence-logo.png",  # From app/services/email_service.py -> project root
                    Path("static") / "sequence-logo.png",  # Relative to current working directory
                ]
                
                logo_path = None
                for path in possible_paths:
                    if path.exists():
                        logo_path = path
                        break
                
                if logo_path:
                    with open(logo_path, 'rb') as f:
                        logo_data = f.read()
                    
                    # Create unique Content-ID for the logo
                    logo_cid = f"logo_{uuid.uuid4().hex[:8]}@sequencebiolab.com"
                    
                    # Attach logo as inline image
                    logo_img = MIMEImage(logo_data)
                    logo_img.add_header('Content-ID', f'<{logo_cid}>')
                    logo_img.add_header('Content-Disposition', 'inline', filename='sequence-logo.png')
                    msg.attach(logo_img)
                    
                    logger.info(f"Logo attached successfully from {logo_path} (size: {len(logo_data)} bytes, CID: {logo_cid})")
                    print(f"DEBUG: Logo attached - {len(logo_data)} bytes, CID: {logo_cid}")
                else:
                    logger.warning(f"Logo file not found. Tried paths: {possible_paths}")
                    print(f"DEBUG: Logo file not found")
            except Exception as e:
                logger.warning(f"Could not attach logo: {e}", exc_info=True)
                print(f"DEBUG: Error attaching logo: {e}")
            
            # Use CID reference if logo was attached, otherwise fallback to URL
            if logo_cid:
                logo_src = f"cid:{logo_cid}"
            else:
                logo_src = f"{base_url}/static/sequence-logo.png"
            
            html_body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verify Your Email - Sequence BioLab</title>
    <!--[if mso]>
    <style type="text/css">
        body, table, td {{ font-family: Arial, sans-serif !important; }}
    </style>
    <![endif]-->
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #1f2937;
            background-color: #f4f5f9;
            padding: 0;
            margin: 0;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }}
        .email-wrapper {{
            background: linear-gradient(135deg, #f4f5f9 0%, #f9fafc 100%);
            min-height: 100vh;
            padding: 60px 20px;
        }}
        .email-container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: #ffffff;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.18);
        }}
        .email-header {{
            background: linear-gradient(135deg, #ffffff 0%, #f9fafc 100%);
            padding: 50px 40px 40px;
            text-align: center;
            border-bottom: 2px solid #f1f3f8;
        }}
        .logo-container {{
            margin-bottom: 20px;
        }}
        .logo-img {{
            height: 80px;
            width: auto;
            max-width: 200px;
        }}
        .email-title {{
            font-size: 28px;
            font-weight: 700;
            color: #1f2937;
            margin-bottom: 8px;
            letter-spacing: -0.5px;
        }}
        .email-subtitle {{
            color: #6b7280;
            font-size: 15px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 1.2px;
        }}
        .email-content {{
            padding: 50px 40px;
        }}
        .greeting {{
            font-size: 26px;
            font-weight: 600;
            color: #1f2937;
            margin-bottom: 24px;
            line-height: 1.3;
        }}
        .message {{
            color: #374151;
            font-size: 16px;
            line-height: 1.8;
            margin-bottom: 24px;
        }}
        .highlight-box {{
            background: linear-gradient(135deg, rgba(255, 127, 0, 0.08) 0%, rgba(255, 127, 0, 0.04) 100%);
            border-left: 4px solid #ff7f00;
            padding: 20px 24px;
            margin: 32px 0;
            border-radius: 8px;
        }}
        .highlight-text {{
            color: #374151;
            font-size: 15px;
            line-height: 1.7;
            margin: 0;
        }}
        .button-container {{
            text-align: center;
            margin: 40px 0;
        }}
        .verify-button {{
            display: inline-block;
            padding: 18px 48px;
            background: linear-gradient(135deg, #ff7f00 0%, #ff8f1a 100%);
            color: #000000;
            text-decoration: none;
            border-radius: 10px;
            font-weight: 700;
            font-size: 17px;
            letter-spacing: 0.3px;
            box-shadow: 0 6px 20px rgba(255, 127, 0, 0.35);
            transition: all 0.3s ease;
        }}
        .verify-button:hover {{
            background: linear-gradient(135deg, #ff8f1a 0%, #ff9f2a 100%);
            box-shadow: 0 8px 24px rgba(255, 127, 0, 0.45);
            transform: translateY(-2px);
        }}
        .link-fallback {{
            margin-top: 36px;
            padding: 24px;
            background-color: #f9fafc;
            border-radius: 10px;
            border: 1px solid #d4d8e1;
        }}
        .link-fallback-title {{
            color: #6b7280;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            margin-bottom: 14px;
        }}
        .link-fallback-url {{
            color: #ff7f00;
            font-size: 13px;
            word-break: break-all;
            font-family: 'Courier New', 'Monaco', monospace;
            line-height: 1.8;
            text-decoration: none;
        }}
        .info-section {{
            margin-top: 40px;
            padding-top: 32px;
            border-top: 1px solid #e5e7eb;
        }}
        .info-item {{
            display: flex;
            align-items: flex-start;
            margin-bottom: 20px;
        }}
        .info-icon {{
            color: #ff7f00;
            font-size: 20px;
            margin-right: 12px;
            margin-top: 2px;
            flex-shrink: 0;
        }}
        .info-text {{
            color: #4b5563;
            font-size: 14px;
            line-height: 1.7;
            flex: 1;
        }}
        .email-footer {{
            background: linear-gradient(135deg, #f9fafc 0%, #f4f5f9 100%);
            padding: 40px;
            text-align: center;
            border-top: 2px solid #f1f3f8;
        }}
        .footer-text {{
            color: #6b7280;
            font-size: 14px;
            line-height: 1.8;
            margin-bottom: 8px;
        }}
        .footer-brand {{
            color: #ff7f00;
            font-weight: 700;
            font-size: 16px;
        }}
        .footer-tagline {{
            color: #9ca3af;
            font-size: 12px;
            margin-top: 12px;
        }}
        @media only screen and (max-width: 600px) {{
            .email-wrapper {{
                padding: 30px 15px;
            }}
            .email-header {{
                padding: 40px 25px 30px;
            }}
            .email-content {{
                padding: 40px 25px;
            }}
            .greeting {{
                font-size: 22px;
            }}
            .message {{
                font-size: 15px;
            }}
            .verify-button {{
                padding: 16px 36px;
                font-size: 16px;
            }}
            .logo-img {{
                height: 60px;
            }}
        }}
    </style>
</head>
<body>
    <div class="email-wrapper">
        <div class="email-container">
            <div class="email-header">
                <div class="logo-container">
                    <img src="{logo_src}" alt="Sequence BioLab" class="logo-img" style="height: 80px; width: auto; max-width: 200px; display: block; margin: 0 auto;" width="80" height="80" border="0">
                </div>
                <h1 class="email-title">Welcome to Sequence BioLab</h1>
                <p class="email-subtitle">Analytics Platform</p>
            </div>
            
            <div class="email-content">
                <h1 class="greeting">Hello {user_name},</h1>
                
                <p class="message">
                    Thank you for creating an account with Sequence BioLab! We're thrilled to have you join our analytics platform.
                </p>
                
                <div class="highlight-box">
                    <p class="highlight-text">
                        <strong>Almost there!</strong> To complete your registration and start exploring powerful analytics tools, please verify your email address.
                    </p>
                </div>
                
                <div class="button-container">
                    <a href="{verification_url}" class="verify-button" style="display: inline-block; padding: 18px 48px; background: linear-gradient(135deg, #ff7f00 0%, #ff8f1a 100%); color: #000000; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 17px; letter-spacing: 0.3px; box-shadow: 0 6px 20px rgba(255, 127, 0, 0.35);">Verify Email Address</a>
                </div>
                
                <div class="link-fallback">
                    <div class="link-fallback-title">Or copy and paste this link into your browser:</div>
                    <a href="{verification_url}" class="link-fallback-url">{verification_url}</a>
                </div>
                
                <div class="info-section">
                    <div class="info-item">
                        <span class="info-icon">⏱️</span>
                        <p class="info-text">This verification link will expire in <strong>24 hours</strong> for security purposes.</p>
                    </div>
                    <div class="info-item">
                        <span class="info-icon">🔒</span>
                        <p class="info-text">If you didn't create this account, you can safely ignore this email.</p>
                    </div>
                </div>
            </div>
            
            <div class="email-footer">
                <p class="footer-text">
                    Best regards,<br>
                    <span class="footer-brand">Sequence BioLab</span> Team
                </p>
                <p class="footer-tagline">Empowering data-driven decisions in baseball analytics</p>
            </div>
        </div>
    </div>
</body>
</html>
"""
            
            part1 = MIMEText(text_body, 'plain')
            part2 = MIMEText(html_body, 'html')
            
            msg_alternative.attach(part1)
            msg_alternative.attach(part2)
            
            # Send email
            with smtplib.SMTP(config['host'], config['port'], timeout=10) as server:
                if config['use_tls']:
                    server.starttls()
                server.login(config['username'], config['password'])
                server.send_message(msg)
            
            logger.info(f"Verification email sent successfully to {user_email}")
            print(f"SUCCESS: Verification email sent to {user_email}")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            error_msg = f"SMTP authentication failed. Check your SMTP_USERNAME and SMTP_PASSWORD. Error: {e}"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}")
            return False
        except smtplib.SMTPException as e:
            error_msg = f"SMTP error while sending email to {user_email}: {e}"
            logger.error(error_msg)
            print(f"ERROR: {error_msg}")
            return False
        except Exception as e:
            error_msg = f"Failed to send verification email to {user_email}: {e}"
            logger.error(error_msg, exc_info=True)
            print(f"ERROR: {error_msg}")
            return False

