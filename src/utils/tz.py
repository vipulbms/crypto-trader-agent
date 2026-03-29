"""Timezone utility — Singapore Standard Time (SGT, UTC+8)."""

from datetime import datetime, timedelta, timezone

SGT = timezone(timedelta(hours=8), name="SGT")


def now_sgt() -> datetime:
    """Return current datetime in Singapore time."""
    return datetime.now(SGT)


def now_sgt_iso() -> str:
    """Return current Singapore time as ISO 8601 string."""
    return now_sgt().isoformat()


def to_sgt(dt: datetime) -> datetime:
    """Convert any aware datetime to Singapore time."""
    return dt.astimezone(SGT)
