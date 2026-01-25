"""
Persistent cache backed by the primary database (Supabase/Postgres).

This is used for expensive-to-compute / slow-to-fetch payloads that need to
survive process restarts and be shared across workers/instances.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional


def _stable_hash_key(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_json(cache_name: str, key_payload: Any) -> Optional[Any]:
    """Return cached JSON if present and not expired."""
    try:
        # PlayerDB lives in /src, and the app already adds that path in many modules.
        from database import PlayerDB  # type: ignore
    except Exception:
        return None

    cache_key = _stable_hash_key(key_payload)
    db = None
    try:
        db = PlayerDB()
        raw = db.cache_get(cache_name, cache_key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None
    except Exception:
        return None
    finally:
        try:
            if db:
                db.close()
        except Exception:
            pass


def set_json(cache_name: str, key_payload: Any, value: Any, ttl_seconds: int) -> None:
    """Upsert cached JSON with TTL. Best-effort."""
    try:
        from database import PlayerDB  # type: ignore
    except Exception:
        return

    cache_key = _stable_hash_key(key_payload)
    db = None
    try:
        db = PlayerDB()
        raw = json.dumps(value, default=str)
        db.cache_set(cache_name, cache_key, raw, ttl_seconds=ttl_seconds)
    except Exception:
        return
    finally:
        try:
            if db:
                db.close()
        except Exception:
            pass

