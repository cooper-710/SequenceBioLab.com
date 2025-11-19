# SMTP Email Setup Instructions

## For Google Workspace / Gmail Accounts

Your email `cooperrobinson@sequencebiolab.com` appears to be a Google Workspace account. To send emails, you need to use an **App Password** instead of your regular password.

### Steps to Generate an App Password:

1. **Enable 2-Factor Authentication** (if not already enabled):
   - Go to: https://myaccount.google.com/security
   - Enable 2-Step Verification

2. **Generate an App Password**:
   - Go to: https://myaccount.google.com/apppasswords
   - Select "Mail" as the app
   - Select your device
   - Click "Generate"
   - Copy the 16-character password (format: `abcd efgh ijkl mnop`)

3. **Update the config file**:
   - Edit `config/settings.json`
   - Replace the `password` field with your App Password (remove spaces)
   - Example: `"password": "abcdefghijklmnop"`

4. **Restart your Flask application**

### Alternative: If you're using a different email provider

If `sequencebiolab.com` is NOT using Google Workspace, you may need different SMTP settings:

- **Office 365 / Outlook**: 
  - Host: `smtp.office365.com`
  - Port: `587`
  
- **Custom SMTP Server**: 
  - Contact your email provider for SMTP settings

### Testing

After updating the password, run:
```bash
python3 test_email_config.py
```

This will test if the email configuration is working.

