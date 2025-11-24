"""
Data formatting utilities
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from app.constants import JOURNAL_VISIBILITY_OPTIONS, MAX_JOURNAL_TIMELINE_ENTRIES
from app.utils.helpers import clean_str


def normalize_journal_visibility(value: Optional[str], default: str = "private") -> str:
    """Normalize journal visibility value."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized not in JOURNAL_VISIBILITY_OPTIONS:
        return default
    return normalized


def prepare_journal_timeline(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group journal entries by date and prepare display metadata."""
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    
    for entry in entries:
        entry_date = (entry.get("entry_date") or "").strip()
        if not entry_date:
            continue
        
        normalized_visibility = normalize_journal_visibility(entry.get("visibility"), "private")
        body_text = entry.get("body") or ""
        preview = body_text.strip()
        max_preview = 160
        if len(preview) > max_preview:
            preview = preview[:max_preview].rstrip() + "…"
        
        try:
            display_date = datetime.strptime(entry_date, "%Y-%m-%d").strftime("%b %d, %Y")
        except ValueError:
            display_date = entry_date
        
        updated_at_ts = entry.get("updated_at")
        updated_at_human = None
        if updated_at_ts:
            try:
                updated_at_human = datetime.fromtimestamp(updated_at_ts).strftime("%b %d, %Y %I:%M %p")
            except (ValueError, OSError):
                updated_at_human = None
        
        grouped[entry_date].append({
            **entry,
            "visibility": normalized_visibility,
            "display_date": display_date,
            "preview": preview,
            "updated_at_human": updated_at_human,
        })
    
    timeline: List[Dict[str, Any]] = []
    for date_key in sorted(grouped.keys(), reverse=True):
        timeline.append({
            "date": date_key,
            "display_date": grouped[date_key][0].get("display_date"),
            "entries": sorted(grouped[date_key], key=lambda item: item["visibility"]),
        })
    
    return timeline[:MAX_JOURNAL_TIMELINE_ENTRIES]


def augment_journal_entry(entry: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Add display metadata to a single journal entry."""
    if not entry:
        return None
    
    enriched = dict(entry)
    entry_date = (enriched.get("entry_date") or "").strip()
    try:
        enriched["display_date"] = datetime.strptime(entry_date, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        enriched["display_date"] = entry_date
    
    updated_at_ts = enriched.get("updated_at")
    if updated_at_ts:
        try:
            enriched["updated_at_human"] = datetime.fromtimestamp(updated_at_ts).strftime("%b %d, %Y %I:%M %p")
        except (ValueError, OSError):
            enriched["updated_at_human"] = None
    else:
        enriched["updated_at_human"] = None
    
    enriched["visibility"] = normalize_journal_visibility(enriched.get("visibility"), default="private")
    return enriched


def format_journal_date(date_str: Optional[str]) -> Optional[str]:
    """Format a journal date string."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return date_str


def coerce_utc_datetime(value) -> Optional[datetime]:
    """Coerce a value into a UTC datetime."""
    if not value:
        return None
    
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
        except ValueError:
            for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    else:
        return None
    
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def extract_game_datetime(game: Dict[str, Any]) -> Optional[datetime]:
    """Extract datetime from a game dictionary."""
    for key in ("game_datetime_iso", "game_datetime", "game_date_iso"):
        dt = coerce_utc_datetime(game.get(key))
        if dt:
            return dt
    return None





