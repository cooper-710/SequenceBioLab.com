#!/usr/bin/env python3
"""
Test script to verify PostgreSQL connection
"""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def check_connection():
    """Test database connection"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is not configured.")
        return False

    print("Testing PostgreSQL connection...")
    print("Using DATABASE_URL from the environment.")

    try:
        from database import PlayerDB
        
        print("\n1. Creating database connection...")
        db = PlayerDB()
        
        print(f"   ✓ Connected successfully!")
        print(f"   ✓ Using PostgreSQL: {db.is_postgres}")
        
        print("\n2. Testing schema initialization...")
        # Schema is initialized in __init__, so if we got here, it worked
        print("   ✓ Schema initialized")
        
        print("\n3. Testing basic query...")
        teams = db.get_all_teams()
        print(f"   ✓ Query successful (found {len(teams)} teams)")
        
        print("\n4. Testing user operations...")
        # Try to list users (should work even if empty)
        users = db.list_users()
        print(f"   ✓ User operations work (found {len(users)} users)")
        
        db.close()
        print("\n✅ All tests passed! PostgreSQL connection is working.")
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_connection():
    """Run only when live database verification is explicitly requested."""
    import pytest

    if os.environ.get("RUN_LIVE_POSTGRES_TEST") != "1":
        pytest.skip("live PostgreSQL test; set RUN_LIVE_POSTGRES_TEST=1 to enable")
    assert check_connection()

if __name__ == "__main__":
    success = check_connection()
    sys.exit(0 if success else 1)
