#!/usr/bin/env python3
"""
Interactive script to set up SMTP configuration
"""
import json
import sys
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / "config" / "settings.json"

def setup_smtp():
    """Interactive SMTP setup"""
    print("=" * 60)
    print("SMTP Email Configuration Setup")
    print("=" * 60)
    print("\nThis will help you configure SMTP settings for email verification.")
    print("\nFor Gmail users:")
    print("1. Enable 2-Factor Authentication on your Google account")
    print("2. Generate an App Password: https://myaccount.google.com/apppasswords")
    print("3. Select 'Mail' and your device, then copy the 16-character password")
    print("\n" + "=" * 60)
    
    # Load existing settings
    if SETTINGS_PATH.exists():
        with open(SETTINGS_PATH, 'r') as f:
            settings = json.load(f)
    else:
        settings = {}
    
    if 'smtp' not in settings:
        settings['smtp'] = {}
    
    # Get SMTP settings
    print("\nSMTP Configuration:")
    print("(Press Enter to keep current value or use default)")
    
    current_host = settings['smtp'].get('host', '')
    host = input(f"SMTP Host [{current_host or '(required)'}]: ").strip() or current_host
    
    current_port = settings['smtp'].get('port', 587)
    port_input = input(f"SMTP Port [{current_port}]: ").strip()
    port = int(port_input) if port_input else current_port
    
    current_username = settings['smtp'].get('username', '')
    username = input(f"SMTP Username (email) [{current_username}]: ").strip() or current_username
    
    current_password = settings['smtp'].get('password', '')
    if current_password:
        password = input("SMTP Password (leave blank to keep current): ").strip() or current_password
    else:
        password = input("SMTP Password (App Password for Gmail): ").strip()
    
    current_from_email = settings['smtp'].get('from_email', username)
    from_email = input(f"From Email [{current_from_email}]: ").strip() or current_from_email
    
    current_from_name = settings['smtp'].get('from_name', '')
    from_name = input(f"From Name [{current_from_name or '(optional)'}]: ").strip() or current_from_name
    
    # Update settings
    settings['smtp'] = {
        'host': host,
        'port': port,
        'username': username,
        'password': password,
        'use_tls': True,
        'from_email': from_email,
        'from_name': from_name
    }
    
    # Save settings
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, 'w') as f:
        json.dump(settings, f, indent=2)
    
    print("\n✅ SMTP configuration saved!")
    print(f"\nSettings saved to: {SETTINGS_PATH}")
    print("\nYou can now restart your application and emails should work.")
    
    # Test if credentials are set
    if username and password:
        print("\nWould you like to test the email configuration? (y/n): ", end='')
        test = input().strip().lower()
        if test == 'y':
            print("\nTesting email configuration...")
            try:
                from app.services.email_service import EmailService
                config = EmailService.get_smtp_config()
                print(f"✅ Configuration loaded: {config['username']} @ {config['host']}:{config['port']}")
                print("\nNote: To fully test, try registering a new account.")
            except Exception as e:
                print(f"⚠️  Could not test configuration: {e}")

if __name__ == "__main__":
    try:
        setup_smtp()
    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

