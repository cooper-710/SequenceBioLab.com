# Scheduling Setup Guide

## macOS Full Disk Access Requirement

**IMPORTANT**: macOS requires "Full Disk Access" for launchd to access files in the Desktop directory. You'll need to grant this permission before scheduling will work.

## Option 1: Grant Full Disk Access (Recommended)

1. Open **System Settings** (or System Preferences on older macOS)
2. Go to **Privacy & Security** → **Full Disk Access**
3. Click the **+** button
4. Navigate to `/usr/sbin/launchd` and add it
5. Make sure the checkbox is enabled
6. Restart your Mac or log out/in for changes to take effect

**Alternative**: You can also grant Full Disk Access to Terminal if you're testing from Terminal.

## Option 2: Use Cron (Alternative)

Cron may work better for Desktop access. See the cron setup below.

## Setup Instructions

### 1. Create the Production Plist

The production plist file is created at:
`~/Library/LaunchAgents/com.sequencebiolab.update-data.plist`

### 2. Load the Job

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.sequencebiolab.update-data.plist
```

### 3. Verify It's Loaded

```bash
launchctl list | grep sequencebiolab
```

### 4. Check Logs

Logs will be written to:
- `logs/data_update.log` - Standard output
- `logs/data_update_error.log` - Errors

### 5. Unload (if needed)

```bash
launchctl bootout gui/$(id -u)/com.sequencebiolab.update-data
```

## Testing

A test plist has been created that runs every 60 seconds:
`~/Library/LaunchAgents/com.sequencebiolab.update-data-test-immediate.plist`

This will help verify the scheduling works before setting up the daily schedule.

## Troubleshooting

If you see "Operation not permitted" errors:
1. Grant Full Disk Access (see above)
2. Restart your Mac
3. Try again

If dependencies fail:
- The script will try to install them automatically
- Make sure you have internet access
- Check the error logs for specific issues

