import json
from datetime import datetime, UTC
from pathlib import Path

STATUS_FILE = Path("status/status.json")

CRON_SCHEDULES = {
    "kim": "0 * * * *",
    "justin": "55 11,23 * * *",
}


def _next_run(cron: str, now: datetime) -> str:
    """Compute next run time for the two known cron schedules."""
    if cron == "0 * * * *":
        candidate = now.replace(minute=0, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate.replace(hour=candidate.hour + 1)
            if candidate.hour == 0:
                candidate = candidate.replace(
                    day=candidate.day + 1, hour=0
                )
        return candidate.isoformat()

    if cron == "55 11,23 * * *":
        today_1155 = now.replace(hour=11, minute=55, second=0, microsecond=0)
        today_2355 = now.replace(hour=23, minute=55, second=0, microsecond=0)
        if now < today_1155:
            return today_1155.isoformat()
        if now < today_2355:
            return today_2355.isoformat()
        tomorrow = now.replace(day=now.day + 1, hour=11, minute=55, second=0, microsecond=0)
        return tomorrow.isoformat()

    return ""


def _load() -> dict:
    if STATUS_FILE.exists():
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    return {}


def write_status(profile: str, data: dict) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)

    status = _load()
    cron = CRON_SCHEDULES.get(profile, "")

    status[profile] = {
        **data,
        "last_run": now.isoformat(),
        "cron_schedule": cron,
        "next_run": _next_run(cron, now),
    }

    STATUS_FILE.write_text(
        json.dumps(status, indent=2),
        encoding="utf-8",
    )
