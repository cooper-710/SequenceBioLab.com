#!/bin/bash
# Start the Scouting Report Web UI

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Load environment variables from .env file if it exists
if [ -f ".env" ]; then
    echo "Loading environment variables from .env file..."
    set -a  # Automatically export all variables
    source .env
    set +a  # Stop automatically exporting
fi

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Install dependencies if needed
python3 -m pip install -r requirements-web.txt --quiet 2>/dev/null || true

# Use live data (disable mock schedule)
export USE_MOCK_SCHEDULE=0

# Check if Gunicorn is available and USE_GUNICORN is set
if command -v gunicorn &> /dev/null && [ "${USE_GUNICORN:-0}" = "1" ]; then
    echo "Starting with Gunicorn (production mode)..."
    echo "Using live MLB schedule data from MLB StatsAPI"
    PORT=${PORT:-5000}
    echo "Server will be available at http://0.0.0.0:${PORT}"
    echo ""
    gunicorn -w 2 -b 0.0.0.0:${PORT} --timeout 600 wsgi:application
else
    # Start the Flask app (development mode)
    echo "Starting Scouting Report Web UI (development mode)..."
    echo "Using live MLB schedule data from MLB StatsAPI"
    echo "Open http://127.0.0.1:5000 in your browser"
    echo ""
    echo "To use Gunicorn: export USE_GUNICORN=1 && ./start_ui.sh"
    echo ""
    python3 app.py
fi

