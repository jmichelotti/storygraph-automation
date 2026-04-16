import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from croniter import croniter
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = ROOT / "logs"
GOODREADS_STATE_DIR = ROOT / "goodreads" / "state"
STORYGRAPH_STATE_DIR = ROOT / "storygraph" / "state"
SCHEDULES_FILE = Path(__file__).resolve().parent / "schedules.yml"

RUN_START_RE = re.compile(r"RUN START — (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
RUN_END_RE = re.compile(r"RUN END — duration:\s*([\d.]+)s")
KIM_APPLIED_PREFIX = "ACTION: applied"
JUSTIN_APPLIED_PREFIX = "UPDATE"

app = FastAPI(title="StoryGraphAutomation Dashboard")


def tail_text(path: Path, max_bytes: int = 200_000) -> str:
    size = path.stat().st_size
    if size <= max_bytes:
        return path.read_text(encoding="utf-8", errors="replace")
    with path.open("rb") as f:
        f.seek(-max_bytes, 2)
        return f.read().decode("utf-8", errors="replace")


def parse_runs(log_path: Path) -> list[dict]:
    """Walk a log file and return a list of run records, oldest first."""
    if not log_path.exists():
        return []

    text = tail_text(log_path)
    runs: list[dict] = []
    current: dict | None = None

    for line in text.splitlines():
        m = RUN_START_RE.search(line)
        if m:
            if current is not None:
                runs.append(current)
            current = {
                "start": m.group(1),
                "completed": False,
                "duration_s": None,
                "applied_titles": [],
            }
            continue

        m = RUN_END_RE.search(line)
        if m and current is not None:
            current["duration_s"] = float(m.group(1))
            current["completed"] = True
            runs.append(current)
            current = None
            continue

        if current is None:
            continue

        if KIM_APPLIED_PREFIX in line:
            title = _title_after_arrow(line)
            if title:
                current["applied_titles"].append(title)
        elif line.startswith("UPDATE (new):") or line.startswith("UPDATE (changed):"):
            title = _title_after_colon(line)
            if title:
                current["applied_titles"].append(title)

    if current is not None:
        runs.append(current)

    return runs


def _title_after_arrow(line: str) -> str | None:
    parts = re.split(r"[→>]+\s*", line, maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip() or None


def _title_after_colon(line: str) -> str | None:
    after = line.split(":", 1)[1].strip() if ":" in line else ""
    return after.split(" -> ")[0].strip() or None


def last_run_summary(log_path: Path) -> dict:
    runs = parse_runs(log_path)
    if not runs:
        return {
            "last_run_start": None,
            "last_run_completed": False,
            "last_run_duration_s": None,
            "status": "never_run",
            "last_run_applied_count": 0,
            "last_run_applied_titles": [],
        }

    latest = runs[-1]
    status = "success" if latest["completed"] else "in_progress_or_failed"
    return {
        "last_run_start": latest["start"],
        "last_run_completed": latest["completed"],
        "last_run_duration_s": latest["duration_s"],
        "status": status,
        "last_run_applied_count": len(latest["applied_titles"]),
        "last_run_applied_titles": latest["applied_titles"],
    }


def kim_status() -> dict:
    summary = last_run_summary(LOGS_DIR / "goodreads" / "kim.log")

    total_applied = 0
    state_path = GOODREADS_STATE_DIR / "state_kim.json"
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            total_applied = len(data.get("processed_reviews", []))
        except (json.JSONDecodeError, OSError):
            pass

    return {
        **summary,
        "source": "goodreads",
        "total_books_applied": total_applied,
    }


def justin_status() -> dict:
    summary = last_run_summary(LOGS_DIR / "runner" / "justin.log")

    in_progress: list[dict] = []
    last_updated_at: str | None = None

    state_path = STORYGRAPH_STATE_DIR / "sync_justin.json"
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            for title, entry in data.items():
                in_progress.append({
                    "title": title,
                    "percent_complete": entry.get("percent_complete"),
                    "updated_at": entry.get("updated_at"),
                })
            in_progress.sort(key=lambda b: b.get("updated_at") or "", reverse=True)
            updated_ats = [b["updated_at"] for b in in_progress if b.get("updated_at")]
            if updated_ats:
                last_updated_at = max(updated_ats)
        except (json.JSONDecodeError, OSError):
            pass

    return {
        **summary,
        "source": "audible",
        "in_progress_books": in_progress,
        "last_book_updated_at": last_updated_at,
    }


def load_schedules() -> dict[str, Any]:
    if not SCHEDULES_FILE.exists():
        return {}
    return yaml.safe_load(SCHEDULES_FILE.read_text(encoding="utf-8")) or {}


def next_runs() -> dict[str, dict]:
    schedules = load_schedules().get("profiles", {})
    now = datetime.now()
    out: dict[str, dict] = {}

    for name, cfg in schedules.items():
        cron_expr = cfg.get("cron")
        description = cfg.get("description")
        next_dt: str | None = None
        if cron_expr:
            try:
                next_dt = croniter(cron_expr, now).get_next(datetime).isoformat(timespec="seconds")
            except (ValueError, KeyError):
                next_dt = None
        out[name] = {
            "cron": cron_expr,
            "description": description,
            "next_run": next_dt,
        }
    return out


@app.get("/")
def root() -> dict:
    return {"endpoints": ["/status", "/healthz"]}


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/status")
def status() -> dict:
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "profiles": {
            "kim": kim_status(),
            "justin": justin_status(),
        },
        "schedules": next_runs(),
    }
