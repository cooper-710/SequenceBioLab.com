#!/usr/bin/env python3
"""
WSGI entry point for Gunicorn
"""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import the app from app.py (the root file, not the app package)
# We need to import the file directly, not the package
import importlib.util
app_py_path = Path(__file__).parent / "app.py"
spec = importlib.util.spec_from_file_location("app_py", app_py_path)
app_py = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app_py)
app = app_py.app

# Ensure we're not in debug mode for production
if os.environ.get('FLASK_ENV') != 'development':
    app.config['DEBUG'] = False

# The app object is what Gunicorn will use
application = app

if __name__ == "__main__":
    # For local testing
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port)

