import json
import traceback
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


def write_failure_status(
    profile: str,
    error: BaseException,
    duration_seconds: float,
    log_file: Path | None = None,
) -> None:
    """
    Record a run that died on an unhandled exception.

    Both runners only wrote status on their success paths, so a crash (expired
    StoryGraph session, Playwright timeout, Audible CLI failure) left the status
    file frozen at the last good run while the traceback went to cron's
    discarded stderr — a broken sync looked exactly like one that hadn't run
    yet. This writes status "failed" plus the error, and appends the full
    traceback to the run log.
    """
    detail = f"{type(error).__name__}: {error}".strip()
    summary = detail.splitlines()[0][:300] if detail else type(error).__name__

    if log_file is not None:
        tb = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"\nRUN FAILED — {summary}\n")
            f.write(tb)
            f.write(f"RUN END — duration: {duration_seconds:.1f}s (failed)\n\n")

    write_status(profile, {
        "status": "failed",
        "duration_seconds": round(duration_seconds, 1),
        "error": summary,
    })
