"""When the kim-read export is due: one scheduler for both routes (reading-cards round table, A10).

Two routes make an export due:
  monday - the newest success predates this week's anchor (Monday 00:00 America/New_York, which is
           Sunday 21:00 on Wild-Karrde's Pacific clock) and fewer than 3 attempts were made since
           that anchor, so reading-cards' Sunday-night card sees the finished week;
  daily  - the newest success is more than 20 hours old.
One 3-hour cooldown after any failed attempt applies to both, so neither route can turn a failing
Goodreads page into an hourly retry storm.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DAILY = timedelta(hours=20)
COOLDOWN = timedelta(hours=3)
MONDAY_ATTEMPTS = 3


def monday_anchor(now: datetime) -> datetime:
    """The latest Monday 00:00 America/New_York at or before `now` (aware)."""
    local = now.astimezone(ET)
    monday = (local - timedelta(days=local.weekday())).date()
    return datetime(monday.year, monday.month, monday.day, tzinfo=ET)


def _ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _attempts(block: dict, anchor: datetime) -> int:
    recorded = _ts(block.get("anchor"))
    if recorded is None or recorded != anchor:
        return 0
    try:
        return int(block.get("attempts_for_anchor") or 0)
    except (TypeError, ValueError):
        return 0


def read_export_due(block: dict, now: datetime) -> tuple[bool, str]:
    """(due, reason); reason is monday | daily | cooldown | monday-cap | fresh."""
    last_attempt = _ts(block.get("last_attempt"))
    if block.get("last_status") == "failed" and last_attempt and now - last_attempt < COOLDOWN:
        return False, "cooldown"
    anchor = monday_anchor(now)
    last_success = _ts(block.get("last_success"))
    before_anchor = last_success is None or last_success < anchor
    if before_anchor and _attempts(block, anchor) < MONDAY_ATTEMPTS:
        return True, "monday"
    if last_success is None or now - last_success > DAILY:
        return True, "daily"
    if before_anchor:
        return False, "monday-cap"
    return False, "fresh"


def next_block(block: dict, now: datetime, ok: bool, detail: dict) -> dict:
    """The status block after one attempt at `now`."""
    anchor = monday_anchor(now)
    out = {**block, **detail}
    out["anchor"] = anchor.isoformat()
    out["attempts_for_anchor"] = _attempts(block, anchor) + 1
    out["last_attempt"] = now.isoformat()
    out["last_status"] = "success" if ok else "failed"
    if ok:
        out["last_success"] = now.isoformat()
    return out
