"""Small time helpers for database values and Discord timestamps."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_db_timestamp(value: str | datetime | None) -> datetime | None:
    """Parse stored timestamps as UTC-aware datetimes."""
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = value.strip()
        if not normalized:
            return None
        if "T" not in normalized and " " in normalized:
            normalized = normalized.replace(" ", "T", 1)
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"

        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def unix_timestamp(value: str | datetime | None) -> int | None:
    """Return a Unix timestamp for Discord's <t:...> formatting."""
    parsed = parse_db_timestamp(value)
    if parsed is None:
        return None
    return int(parsed.timestamp())
