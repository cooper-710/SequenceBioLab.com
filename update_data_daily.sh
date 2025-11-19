#!/bin/bash
# Daily CSV data update script
# This script activates the virtual environment and runs the update

set -euo pipefail

# Get the directory where this script is located, then go to repo root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run the update script
python3 scripts/update_csv_data.py

# Exit with the script's exit code
exit $?

