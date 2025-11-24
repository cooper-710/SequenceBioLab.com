# Cron Setup Complete ✅

## Status: **ACTIVE**

The automated CSV data update system is now scheduled using **cron** (simpler than launchd, no Full Disk Access needed).

## Schedule

- **Time**: Daily at 6:00 AM
- **Command**: Updates all CSV files (fangraphs, fangraphs_pitchers, Positions, statscast)
- **Logs**: `data_update.log` and `data_update_error.log`

## Current Cron Job

```bash
0 6 * * * cd /Users/cooperrobinson/Desktop/SequenceBioLab-main && /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /Users/cooperrobinson/bin/update_csv_data.py >> /Users/cooperrobinson/Desktop/SequenceBioLab-main/data_update.log 2>&1
```

## View Your Cron Jobs

```bash
crontab -l
```

## Edit Cron Schedule

```bash
crontab -e
```

### Common Schedule Examples:
- `0 6 * * *` - Daily at 6:00 AM (current)
- `0 */6 * * *` - Every 6 hours
- `0 6 * * 1` - Every Monday at 6:00 AM
- `30 3 * * *` - Daily at 3:30 AM

## View Logs

```bash
# Standard output
tail -f data_update.log

# Errors
tail -f data_update_error.log

# Last 50 lines
tail -50 data_update.log
```

## Test Manually

```bash
# Run the update script manually
python3 update_csv_data.py

# Or use the test script
./test_scheduling.sh
```

## Remove Cron Job (if needed)

```bash
crontab -e
# Then delete the line with update_csv_data.py
```

## What Gets Updated

1. **fangraphs.csv** - Hitter statistics (incremental: only current season)
2. **fangraphs_pitchers.csv** - Pitcher statistics (incremental: only current season)
3. **Positions.csv** - Player positions by season (incremental: only current season)
4. **statscast.csv** - Statcast advanced metrics (incremental: only current season)

## First Run

The job will run automatically tomorrow at 6:00 AM. You can also run it manually anytime with:

```bash
python3 update_csv_data.py
```

## Troubleshooting

### Check if cron is running:
```bash
# macOS cron service status
sudo launchctl list | grep cron
```

### If updates don't run:
1. Check logs: `tail -f data_update_error.log`
2. Verify Python path: `which python3`
3. Test manually: `python3 update_csv_data.py`
4. Check cron logs: `grep CRON /var/log/system.log` (may require sudo)

### Verify cron job is active:
```bash
crontab -l | grep update_csv_data
```

---

**Setup Date**: 2025-11-13
**Method**: Cron (no Full Disk Access required)
**Status**: ✅ Active





