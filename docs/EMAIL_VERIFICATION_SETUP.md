# Secure Email Verification Setup Guide

This guide will help you securely configure the email verification system for Sequence BioLab.

## Security Features

The email verification system includes the following security measures:

✅ **Cryptographically Secure Tokens**: Uses `secrets.token_urlsafe(32)` for token generation
✅ **Token Expiration**: Tokens expire after 24 hours
✅ **Single-Use Tokens**: Tokens are marked as used after verification
✅ **SQL Injection Protection**: All database queries use parameterized statements
✅ **CSRF Protection**: All forms include CSRF token validation
✅ **Rate Limiting**: Resend verification endpoint has rate limiting (3 requests per hour per email)
✅ **Automatic Cleanup**: Expired and used tokens are automatically cleaned up

## Setup Instructions

### Option 1: Using Environment Variables (Recommended for Production)

Set the following environment variables:

```bash
export SMTP_HOST="smtp.example.com"
export SMTP_PORT="587"
export SMTP_USERNAME="your-email@example.com"
export SMTP_PASSWORD="your-app-password"
export SMTP_USE_TLS="true"
export SMTP_FROM_EMAIL="noreply@sequencebiolab.com"
export SMTP_FROM_NAME="Sequence BioLab"
export BASE_URL="https://your-domain.com"
```

**For Gmail:**
1. Enable 2-Factor Authentication on your Google account
2. Generate an App Password: https://myaccount.google.com/apppasswords
3. Select "Mail" and your device, then copy the 16-character password
4. Use the App Password (not your regular password) for `SMTP_PASSWORD`

### Option 2: Using Settings File

Edit `config/settings.json`:

```json
{
  "smtp": {
    "host": "smtp.example.com",
    "port": 587,
    "username": "your-email@example.com",
    "password": "your-app-password",
    "use_tls": true,
    "from_email": "noreply@sequencebiolab.com",
    "from_name": "Sequence BioLab"
  }
}
```

**⚠️ Security Warning**: The settings file is stored in plain text. For production, prefer environment variables or use file permissions to restrict access:

```bash
chmod 600 config/settings.json
```

### Option 3: Using Setup Script

Run the interactive setup script:

```bash
python3 setup_smtp.py
```

This will guide you through configuring all SMTP settings.

## Testing the Configuration

Test your email configuration:

```bash
python3 test_email_config.py
```

This will:
- Verify SMTP credentials are configured
- Test sending a verification email
- Show any configuration errors

## Security Best Practices

### 1. Use App Passwords (Gmail/Google Workspace)

Never use your main account password. Always use app-specific passwords:
- More secure (can be revoked individually)
- Doesn't require disabling "Less secure app access"
- Better audit trail

### 2. Use Environment Variables in Production

Environment variables are more secure than config files:
- Not stored in version control
- Can be managed by your deployment platform
- Easier to rotate credentials

### 3. Use TLS/SSL

Always enable TLS (`use_tls: true`) to encrypt email transmission.

### 4. Restrict File Permissions

If using `config/settings.json`, restrict access:

```bash
chmod 600 config/settings.json
chown your-user:your-group config/settings.json
```

### 5. Use a Dedicated Email Address

Use a dedicated email address for sending verification emails:
- `noreply@yourdomain.com` or similar
- Easier to monitor and manage
- Better deliverability

### 6. Monitor Email Sending

Check logs regularly for:
- Failed email sends
- Unusual patterns (potential abuse)
- SMTP authentication errors

## Troubleshooting

### "SMTP not configured" Error

- Check that all required fields are set (host, username, password, from_email)
- Verify environment variables are exported (use `env | grep SMTP`)
- Check `config/settings.json` if not using environment variables

### "SMTP authentication failed" Error

- Verify username and password are correct
- For Gmail, ensure you're using an App Password, not your regular password
- Check that 2FA is enabled (required for App Passwords)
- Verify the account isn't locked or suspended

### Emails Not Being Received

- Check spam/junk folder
- Verify `from_email` is a valid, verified email address
- Check SMTP server logs
- Verify `BASE_URL` is correct (affects verification link)
- Test with a different email provider

### Rate Limiting Issues

The resend verification endpoint is rate-limited to 3 requests per hour per email address. If you hit this limit:
- Wait 1 hour before requesting again
- Check your email spam folder for the original verification email
- Contact support if you need assistance

## Database Schema

The verification tokens are stored in the `email_verification_tokens` table:

- `id`: Primary key
- `user_id`: Foreign key to users table
- `token`: The verification token (URL-safe, 32 bytes)
- `created_at`: Timestamp when token was created
- `expires_at`: Timestamp when token expires (24 hours from creation)
- `used_at`: Timestamp when token was used (NULL if unused)

Expired and used tokens are automatically cleaned up.

## Security Considerations

1. **Token Length**: 32 bytes (256 bits) provides excellent security
2. **Token Expiration**: 24 hours balances security and usability
3. **Single Use**: Tokens cannot be reused after verification
4. **Rate Limiting**: Prevents abuse of resend functionality
5. **No Token Enumeration**: Tokens are cryptographically random, preventing guessing

## Additional Security Recommendations

1. **HTTPS Only**: Always use HTTPS in production (set `BASE_URL` to HTTPS)
2. **Email Domain Verification**: Consider implementing SPF, DKIM, and DMARC records
3. **Monitoring**: Set up alerts for failed verification attempts
4. **Logging**: Review logs regularly for suspicious activity
5. **Token Rotation**: Consider rotating SMTP credentials periodically

