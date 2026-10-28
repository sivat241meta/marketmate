"""One relative-time helper used by every web module."""

from __future__ import annotations

from datetime import datetime


def format_relative(when: datetime, now: datetime) -> str:
    """Friendly age: "just now", "1 minute ago", "yesterday", "3 days ago"."""
    seconds = max(0, int((now - when).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return "1 minute ago" if minutes == 1 else f"{minutes} minutes ago"
    hours = minutes // 60
    if hours < 24:
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    days = hours // 24
    return "yesterday" if days == 1 else f"{days} days ago"
