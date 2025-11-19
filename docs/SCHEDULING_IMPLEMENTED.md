# Scheduling Implementation Complete ✅

## Status: **IMPLEMENTED**

The automated CSV data update system has been set up and scheduled.

## What's Running

### Production Schedule
- **Job Name**: `com.sequencebiolab.update-data`
- **Schedule**: Daily at 6:00 AM
- **Status**: Loaded and ready (will run once Full Disk Access is granted)

### What It Does
- Updates `fangraphs.csv` (only fetches current season)
- Updates `fangraphs_pitchers.csv` (only fetches current season)
- Updates `Positions.csv` (only fetches current season)
- Incremental updates: Only fetches missing historical seasons + always updates current season

## Required: Grant Full Disk Access

**IMPORTANT**: macOS requires Full Disk Access for launchd to access Desktop directory.

### Steps:
1. Open **System Settings** (or System Preferences)
2. Go to **Privacy & Security** → **Full Disk Access**
3. Click the **+** button
4. Navigate to `/usr/sbin/launchd` and add it
5. Make sure the checkbox is **enabled**
6. **Restart your Mac** or log out/in

### Verify It's Working

After granting Full Disk Access and restarting:

```bash
# Check if job is loaded
launchctl list | grep sequencebiolab

# Check job status
launchctl print gui/$(id -u)/com.sequencebiolab.update-data

# View logs (after it runs)
tail -f data_update.log
```

## Manual Commands

### Check Status
```bash
launchctl list | grep sequencebiolab
```

### View Logs
```bash
# Standard output
tail -f data_update.log

# Errors
tail -f data_update_error.log
```

### Unload (if needed)
```bash
launchctl bootout gui/$(id -u)/com.sequencebiolab.update-data
```

### Reload (after changes)
```bash
launchctl bootout gui/$(id -u)/com.sequencebiolab.update-data
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.sequencebiolab.update-data.plist
```

### Run Manually (for testing)
```bash
./test_scheduling.sh
# or
python3 update_csv_data.py
```

## Schedule Details

- **Time**: 6:00 AM daily
- **Timezone**: Your system timezone
- **First Run**: Will run tomorrow at 6:00 AM (after Full Disk Access is granted)

## What Happens on Each Run

1. Checks existing CSV files for what seasons are present
2. Fetches only:
   - Missing historical seasons (one-time fetch)
   - Current season (always fetched for latest stats)
3. Merges new data with existing (removes old current season, adds fresh)
4. Creates timestamped backups before updating
5. Logs everything to `data_update.log`

## Files

- **Script**: `update_csv_data.py` (also in `~/bin/`)
- **Wrapper**: `update_data_daily.sh`
- **Plist**: `~/Library/LaunchAgents/com.sequencebiolab.update-data.plist`
- **Logs**: `data_update.log`, `data_update_error.log`

## Troubleshooting

### If updates don't run:
1. Verify Full Disk Access is granted
2. Check logs: `tail -f data_update_error.log`
3. Verify job is loaded: `launchctl list | grep sequencebiolab`
4. Try running manually: `python3 update_csv_data.py`

### If you see "Operation not permitted":
- Full Disk Access not granted or Mac not restarted
- Grant access and restart

### To change schedule time:
Edit `~/Library/LaunchAgents/com.sequencebiolab.update-data.plist`:
- Change `Hour` and `Minute` values
- Reload: `launchctl bootout ... && launchctl bootstrap ...`

## Next Steps

1. ✅ Grant Full Disk Access (see above)
2. ✅ Restart your Mac
3. ✅ Wait for first run (tomorrow at 6:00 AM)
4. ✅ Check logs to verify it worked

---

**Implementation Date**: 2025-11-13
**Status**: Ready to run (pending Full Disk Access)

