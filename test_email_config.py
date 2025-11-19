#!/usr/bin/env python3
"""
Test script to verify SMTP email configuration
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.email_service import EmailService

def test_smtp_config():
    """Test SMTP configuration"""
    print("=" * 60)
    print("Testing SMTP Configuration")
    print("=" * 60)
    
    config = EmailService.get_smtp_config()
    
    print(f"\nSMTP Host: {config['host']}")
    print(f"SMTP Port: {config['port']}")
    print(f"SMTP Username: {config['username'] or '(NOT SET)'}")
    print(f"SMTP Password: {'SET' if config['password'] else '(NOT SET)'}")
    print(f"Use TLS: {config['use_tls']}")
    print(f"From Email: {config['from_email']}")
    print(f"From Name: {config['from_name']}")
    
    if not config['username'] or not config['password']:
        print("\n❌ ERROR: SMTP credentials are not configured!")
        print("\nTo fix this, edit config/settings.json and add:")
        print('  "smtp": {')
        print('    "host": "smtp.example.com",')
        print('    "port": 587,')
        print('    "username": "your-email@example.com",')
        print('    "password": "your-password",')
        print('    "use_tls": true,')
        print('    "from_email": "your-email@example.com",')
        print('    "from_name": "Your Name"')
        print('  }')
        print("\nFor Gmail:")
        print("1. Enable 2-Factor Authentication")
        print("2. Generate an App Password: https://myaccount.google.com/apppasswords")
        print("3. Use the App Password (not your regular password)")
        return False
    
    print("\n✅ SMTP credentials are configured!")
    print("\nTesting email send...")
    
    # Test sending an email
    try:
        result = EmailService.send_verification_email(
            "test@example.com",
            "Test User",
            "test-token-12345",
            "http://localhost:5001"
        )
        if result:
            print("✅ Email service is working correctly!")
        else:
            print("❌ Email service returned False (check logs above for details)")
        return result
    except Exception as e:
        print(f"❌ Error testing email: {e}")
        return False

if __name__ == "__main__":
    success = test_smtp_config()
    sys.exit(0 if success else 1)

