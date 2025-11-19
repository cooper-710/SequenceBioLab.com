#!/usr/bin/env python3
"""
WSGI entry point for Gunicorn
"""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import the app from app.py
# This will create the Flask app instance
from app import app

# Ensure we're not in debug mode for production
if os.environ.get('FLASK_ENV') != 'development':
    app.config['DEBUG'] = False

# The app object is what Gunicorn will use
application = app

if __name__ == "__main__":
    # For local testing
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

