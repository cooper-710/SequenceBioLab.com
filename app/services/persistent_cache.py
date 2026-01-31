"""
Persistent cache backed by the primary database (Supabase/Postgres).

This is used for expensive-to-compute / slow-to-fetch payloads that need to
survive process restarts and be shared across workers/instances.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional


def _stable_hash_key(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _advisory_lock_id(cache_name: str, cache_key: str) -> int:
    """
    Derive a stable signed 63-bit integer for Postgres advisory locks.
    """
    digest = hashlib.sha256(f"{cache_name}|{cache_key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) & ((1 << 63) - 1)


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


def get_or_set_json(
    cache_name: str,
    key_payload: Any,
    ttl_seconds: int,
    builder,
    *,
    lock_wait_seconds: float = 3.0,
):
    """
    Get cached JSON, or build it once and store it.

    On Postgres, uses an advisory lock keyed by (cache_name, cache_key) so multiple
    workers don't all fetch the same upstream data concurrently.
    """
    try:
        from database import PlayerDB  # type: ignore
    except Exception:
        return builder()

    cache_key = _stable_hash_key(key_payload)
    db = None
    try:
        db = PlayerDB()

        raw = db.cache_get(cache_name, cache_key)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return builder()

        if getattr(db, "is_postgres", False):
            lock_id = _advisory_lock_id(cache_name, cache_key)
            cur = db.conn.cursor()

            acquired = False
            start = time.time()
            while (time.time() - start) < max(lock_wait_seconds, 0):
                try:
                    db._execute(cur, "SELECT pg_try_advisory_lock(%s) AS locked", (lock_id,))
                    row = cur.fetchone()
                    acquired = bool((row or {}).get("locked")) if hasattr(row, "get") else bool(row[0])
                except Exception:
                    acquired = False

                if acquired:
                    break

                time.sleep(0.25)
                raw = db.cache_get(cache_name, cache_key)
                if raw:
                    try:
                        return json.loads(raw)
                    except Exception:
                        return builder()

            if acquired:
                try:
                    raw = db.cache_get(cache_name, cache_key)
                    if raw:
                        try:
                            return json.loads(raw)
                        except Exception:
                            return builder()

                    value = builder()
                    try:
                        db.cache_set(cache_name, cache_key, json.dumps(value, default=str), ttl_seconds=ttl_seconds)
                    except Exception:
                        pass
                    return value
                finally:
                    try:
                        cur2 = db.conn.cursor()
                        db._execute(cur2, "SELECT pg_advisory_unlock(%s)", (lock_id,))
                    except Exception:
                        pass

        value = builder()
        try:
            db.cache_set(cache_name, cache_key, json.dumps(value, default=str), ttl_seconds=ttl_seconds)
        except Exception:
            pass
        return value
    finally:
        try:
            if db:
                db.close()
        except Exception:
            pass

