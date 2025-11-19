#!/usr/bin/env python3
"""
Web UI for Scouting Report Generator - Refactored version
"""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import the app factory
from app import create_app
from app.config import Config

# Create the app
app = create_app()

# Import routes from original app.py to maintain functionality
# This is a bridge - routes will be migrated to blueprints gradually
import app_legacy_routes

# Register legacy routes on the app
# This maintains backward compatibility while we migrate
app_legacy_routes.register_legacy_routes(app)


if __name__ == '__main__':
    import socket
    
    def find_free_port(start_port=5000):
        for port in range(start_port, start_port + 100):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('127.0.0.1', port))
                    return port
            except OSError:
                continue
        return 5001
    
    port = find_free_port(5001)
    
    print(f"Starting Scouting Report Web UI...")
    print(f"Reports will be saved to: {Config.PDF_OUTPUT_DIR}")
    print(f"Open http://127.0.0.1:{port} in your browser")
    app.run(debug=Config.DEBUG, host='127.0.0.1', port=port)



