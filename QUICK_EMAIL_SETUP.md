# Quick Email Setup Guide

## Step 1: Get Your Gmail App Password

1. Go to: **https://myaccount.google.com/apppasswords**
2. Sign in to your Google account (the one you want to use for sending emails)
3. Select **"Mail"** from the dropdown
4. Select your device (or choose "Other" and type "Sequence BioLab")
5. Click **"Generate"**
6. Copy the 16-character password (it will look like: `abcd efgh ijkl mnop`)

**Important:** You must have 2-Factor Authentication enabled on your Google account to generate App Passwords.

## Step 2: Create Your .env File

Create a file named `.env` in the project root with the following content:

```bash
# Email Verification SMTP Configuration
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USE_TLS="true"
export SMTP_USERNAME="your-gmail@gmail.com"
export SMTP_PASSWORD="your-16-character-app-password"
export SMTP_FROM_EMAIL="noreply@sequencebiolab.com"
export SMTP_FROM_NAME="Sequence BioLab"
export BASE_URL="http://localhost:5001"
```

**Replace:**
- `your-gmail@gmail.com` with your actual Gmail address
- `your-16-character-app-password` with the App Password from Step 1 (remove any spaces)

## Step 3: Test Your Configuration

After creating the `.env` file, test it:

```bash
source .env
python3 test_email_config.py
```

## Step 4: Start Your Application

The start script will automatically load your `.env` file:

```bash
./start_ui.sh
```

## Troubleshooting

### "SMTP authentication failed"
- Make sure you're using an **App Password**, not your regular Gmail password
- Verify 2-Factor Authentication is enabled
- Check that the App Password doesn't have spaces (remove them if present)

### "SMTP not configured"
- Make sure the `.env` file exists in the project root
- Verify all variables are set (run `env | grep SMTP` to check)
- Make sure you ran `source .env` or restarted your terminal

### Emails not being received
- Check your spam folder
- Verify the `BASE_URL` is correct (should be `http://localhost:5001` for development)
- Check the application logs for error messages

## Security Notes

- The `.env` file is already in `.gitignore` - it won't be committed to version control
- Never share your App Password
- For production, use environment variables set by your hosting platform instead of a `.env` file

