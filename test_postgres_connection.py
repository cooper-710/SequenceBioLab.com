#!/usr/bin/env python3
"""
Test script to verify PostgreSQL connection
"""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Set your database URL (for testing)
# In production, this should be set as an environment variable
DATABASE_URL = "postgresql://postgres:Comet%402009@db.hbrjrbuvslkmmzjptont.supabase.co:5432/postgres"

def test_connection():
    """Test database connection"""
    print("Testing PostgreSQL connection...")
    print(f"Database URL: {DATABASE_URL[:50]}...")
    
    # Set environment variable
    os.environ['DATABASE_URL'] = DATABASE_URL
    
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

if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)

