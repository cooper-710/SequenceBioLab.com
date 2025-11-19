#!/bin/bash
# Repository cleanup script
# This script organizes files and creates the proper directory structure

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "=========================================="
echo "Repository Cleanup Script"
echo "=========================================="
echo ""

# Create directory structure
echo "1. Creating directory structure..."
mkdir -p data/backups
mkdir -p logs
mkdir -p config/backups
mkdir -p docs
mkdir -p scripts
echo "   ✓ Directories created"

# Move CSV files to data/
echo ""
echo "2. Moving CSV data files to data/..."
[ -f fangraphs.csv ] && mv fangraphs.csv data/ && echo "   ✓ Moved fangraphs.csv"
[ -f fangraphs_pitchers.csv ] && mv fangraphs_pitchers.csv data/ && echo "   ✓ Moved fangraphs_pitchers.csv"
[ -f Positions.csv ] && mv Positions.csv data/ && echo "   ✓ Moved Positions.csv"
[ -f statscast.csv ] && mv statscast.csv data/ && echo "   ✓ Moved statscast.csv"

# Move backup files to data/backups/
echo ""
echo "3. Moving CSV backup files to data/backups/..."
for file in *.csv.backup_* *_backup_*.csv; do
    if [ -f "$file" ]; then
        mv "$file" data/backups/
        echo "   ✓ Moved $file"
    fi
done

# Move log files to logs/
echo ""
echo "4. Moving log files to logs/..."
for file in *.log scheduled_update_*.log test_*.log; do
    if [ -f "$file" ]; then
        mv "$file" logs/
        echo "   ✓ Moved $file"
    fi
done

# Move documentation to docs/
echo ""
echo "5. Moving documentation to docs/..."
[ -f SCHEDULING_IMPLEMENTED.md ] && mv SCHEDULING_IMPLEMENTED.md docs/ && echo "   ✓ Moved SCHEDULING_IMPLEMENTED.md"
[ -f SCHEDULING_SETUP.md ] && mv SCHEDULING_SETUP.md docs/ && echo "   ✓ Moved SCHEDULING_SETUP.md"
[ -f SCHEDULING_TEST_RESULTS.md ] && mv SCHEDULING_TEST_RESULTS.md docs/ && echo "   ✓ Moved SCHEDULING_TEST_RESULTS.md"
[ -f CRON_SETUP.md ] && mv CRON_SETUP.md docs/ && echo "   ✓ Moved CRON_SETUP.md"
[ -f TEST_RESULTS.md ] && mv TEST_RESULTS.md docs/ && echo "   ✓ Moved TEST_RESULTS.md"
[ -f DESKTOP_APP.md ] && mv DESKTOP_APP.md docs/ && echo "   ✓ Moved DESKTOP_APP.md"
[ -f README_WEB_UI.md ] && mv README_WEB_UI.md docs/ && echo "   ✓ Moved README_WEB_UI.md"
[ -f test_results_mlb_api.md ] && mv test_results_mlb_api.md docs/ && echo "   ✓ Moved test_results_mlb_api.md"

# Move utility scripts to scripts/
echo ""
echo "6. Moving utility scripts to scripts/..."
[ -f backup_player_data.py ] && mv backup_player_data.py scripts/ && echo "   ✓ Moved backup_player_data.py"
[ -f migrate_sportradar_to_player_id.py ] && mv migrate_sportradar_to_player_id.py scripts/ && echo "   ✓ Moved migrate_sportradar_to_player_id.py"
[ -f update_csv_data.py ] && mv update_csv_data.py scripts/ && echo "   ✓ Moved update_csv_data.py"
[ -f update_player_teams.py ] && mv update_player_teams.py scripts/ && echo "   ✓ Moved update_player_teams.py"
[ -f update_data_daily.sh ] && mv update_data_daily.sh scripts/ && echo "   ✓ Moved update_data_daily.sh"
[ -f test_scheduling.sh ] && mv test_scheduling.sh scripts/ && echo "   ✓ Moved test_scheduling.sh"

# Move test files to tests/
echo ""
echo "7. Moving test files to tests/..."
[ -f test_mlb_schedule.py ] && mv test_mlb_schedule.py tests/ && echo "   ✓ Moved test_mlb_schedule.py"

# Delete accidental files
echo ""
echo "8. Removing accidental files..."
[ -f Terminal ] && rm -f Terminal && echo "   ✓ Removed Terminal"
[ -d "~" ] && rm -rf "~" && echo "   ✓ Removed ~/ directory"

# Delete backup Python file
echo ""
echo "9. Removing backup Python files..."
[ -f src/generate_report.backup.py ] && rm -f src/generate_report.backup.py && echo "   ✓ Removed src/generate_report.backup.py"

# Move settings backup if it exists
echo ""
echo "10. Moving settings backups to config/backups/..."
for file in config/*.backup.json; do
    if [ -f "$file" ]; then
        mv "$file" config/backups/
        echo "   ✓ Moved $(basename $file)"
    fi
done

echo ""
echo "=========================================="
echo "Cleanup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Code has been updated to use new paths"
echo "2. Update script references in cron jobs/launch agents if needed"
echo "3. Test the application to ensure everything works"
echo "4. Commit changes: git add -A && git commit -m 'Organize repository structure'"
echo ""

