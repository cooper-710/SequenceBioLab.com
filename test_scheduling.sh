#!/bin/bash
# Test script to verify scheduling works
# This will manually trigger the update to test if permissions are working

echo "Testing scheduled update script..."
echo "=================================="
echo ""

# Get the directory where this script is located, then go to repo root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# Test with dry-run first
echo "1. Testing with --dry-run..."
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/update_csv_data.py --dry-run

echo ""
echo "2. If dry-run worked, testing actual update (will only update current season)..."
echo "   Press Ctrl+C to cancel, or wait 5 seconds..."
sleep 5

/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/update_csv_data.py

echo ""
echo "=================================="
echo "Test complete! Check the logs above for any errors."
echo ""
echo "If you see 'Operation not permitted' errors, you need to:"
echo "1. Go to System Settings → Privacy & Security → Full Disk Access"
echo "2. Add /usr/sbin/launchd"
echo "3. Restart your Mac"

