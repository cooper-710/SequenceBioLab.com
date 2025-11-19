"""
Cache service for application caching
"""
from typing import Dict, Any
from datetime import datetime, timedelta
from collections import defaultdict


class CacheService:
    """Simple in-memory cache service (replace with Redis in production)"""
    
    def __init__(self):
        self._caches: Dict[str, Dict[Any, Any]] = defaultdict(dict)
    
    def get(self, cache_name: str, key: Any) -> Any:
        """Get a value from cache."""
        cache = self._caches.get(cache_name, {})
        entry = cache.get(key)
        if not entry:
            return None
        
        value, expires_at = entry
        if expires_at and expires_at > datetime.utcnow():
            return value
        
        # Expired, remove it
        cache.pop(key, None)
        return None
    
    def set(self, cache_name: str, key: Any, value: Any, ttl_seconds: int) -> None:
        """Set a value in cache with TTL."""
        cache = self._caches[cache_name]
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        cache[key] = (value, expires_at)
    
    def clear(self, cache_name: str = None) -> None:
        """Clear cache(s)."""
        if cache_name:
            self._caches.pop(cache_name, None)
        else:
            self._caches.clear()


# Global cache service instance
cache_service = CacheService()

# Cache names
CACHE_UPCOMING_GAMES = "upcoming_games"
CACHE_LEAGUE_LEADERS = "league_leaders"
CACHE_STANDINGS = "standings"
CACHE_TEAM_METADATA = "team_metadata"
CACHE_PLAYER_NEWS = "player_news"

