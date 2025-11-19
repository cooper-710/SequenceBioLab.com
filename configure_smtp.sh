#!/bin/bash
# Quick SMTP configuration script

echo "=========================================="
echo "SMTP Email Configuration"
echo "=========================================="
echo ""
echo "This script will help you configure SMTP settings for email verification."
echo ""
echo "For Gmail:"
echo "1. Enable 2-Factor Authentication"
echo "2. Generate App Password: https://myaccount.google.com/apppasswords"
echo "3. Select 'Mail' and your device"
echo ""
echo "=========================================="
echo ""

read -p "Enter your SMTP email (e.g., your-email@gmail.com): " SMTP_USERNAME
read -sp "Enter your SMTP password (App Password for Gmail): " SMTP_PASSWORD
echo ""
read -p "Enter SMTP host (required): " SMTP_HOST
read -p "Enter SMTP port [587]: " SMTP_PORT
SMTP_PORT=${SMTP_PORT:-587}
read -p "Enter from email [$SMTP_USERNAME]: " FROM_EMAIL
FROM_EMAIL=${FROM_EMAIL:-$SMTP_USERNAME}

# Update settings.json
python3 << EOF
import json
from pathlib import Path

settings_path = Path("config/settings.json")

# Load existing settings
if settings_path.exists():
    with open(settings_path, 'r') as f:
        settings = json.load(f)
else:
    settings = {}

# Update SMTP settings
settings['smtp'] = {
    'host': '$SMTP_HOST',
    'port': int('$SMTP_PORT'),
    'username': '$SMTP_USERNAME',
    'password': '$SMTP_PASSWORD',
    'use_tls': True,
    'from_email': '$FROM_EMAIL',
    'from_name': ''
}

# Save settings
settings_path.parent.mkdir(parents=True, exist_ok=True)
with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=2)

print("✅ SMTP configuration saved to config/settings.json")
print("")
print("Configuration:")
print(f"  Host: $SMTP_HOST")
print(f"  Port: $SMTP_PORT")
print(f"  Username: $SMTP_USERNAME")
print(f"  From Email: $FROM_EMAIL")
print("")
print("Restart your Flask application for changes to take effect.")
EOF

echo ""
echo "Would you like to test the email configuration? (y/n): "
read -p "> " TEST_EMAIL
if [ "$TEST_EMAIL" = "y" ]; then
    python3 test_email_config.py
fi

