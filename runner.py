import argparse
import json
from pathlib import Path
from datetime import datetime, UTC
import time

from storygraph.runner_api import update_books_progress
from audible.audible_in_progress import export_library, get_in_progress_books
from status import write_status, write_failure_status


def parse_args():
    parser = argparse.ArgumentParser(
        description="Diff Audible in-progress books vs last sync state"
    )
    parser.add_argument(
        "--profile",
        required=True,
        help="StoryGraph profile name (used for sync state)",
    )
    return parser.parse_args()


# ---------- Logging helpers ----------

def get_log_path(profile: str) -> Path:
    log_dir = Path("logs/runner")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{profile}.log"


def log_line(log_file: Path, message: str = ""):
    with log_file.open("a", encoding="utf-8") as f:
        f.write(message + "\n")


def get_sync_state_path(profile: str) -> Path:
    state_dir = Path("storygraph/state")
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"sync_{profile}.json"


def load_sync_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def save_sync_state(path: Path, books: list[dict]) -> None:
    state = {}

    for book in books:
        record = {
            "percent_complete": book["percent_complete"],
            "updated_at": datetime.now(UTC).isoformat(),
        }
        # The edition URL we settled on (the audiobook edition) so the next run
        # can go straight to it instead of searching by title again.
        if book.get("book_url"):
            record["book_url"] = book["book_url"]
        state[book["title"]] = record

    path.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8",
    )

def persisted_books(
    audible_books: list[dict],
    failed: list[dict],
    sync_state: dict,
    settled_urls: dict[str, str],
) -> list[dict]:
    """
    Build the book list to persist to sync state.

    Books that failed to sync are held at their previously-synced percent (or
    omitted entirely if they were never synced before) so the next run re-attempts
    them, rather than silently advancing the stored value and treating them as
    done.

    Each book's edition URL is carried forward: the one we settled on this run if
    it was synced, otherwise whatever was previously stored.
    """
    failed_titles = {b["title"] for b in failed}
    out: list[dict] = []
    for book in audible_books:
        title = book["title"]
        prev = sync_state.get(title) or {}
        book_url = settled_urls.get(title) or prev.get("book_url")
        if title in failed_titles:
            if not prev:
                continue  # never synced before -> retry as new next run
            out.append({
                **book,
                "percent_complete": prev["percent_complete"],
                "book_url": book_url,
            })
        else:
            out.append({**book, "book_url": book_url})
    return out


def diff_audible_vs_sync(
    audible_books: list[dict],
    sync_state: dict,
) -> tuple[list[dict], list[dict]]:
    """
    Returns:
      - updates: books whose progress changed or are new
      - unchanged: books whose progress is unchanged
    """
    updates = []
    unchanged = []

    for book in audible_books:
        title = book["title"]
        current_percent = book["percent_complete"]

        previous = sync_state.get(title)
        previous_percent = (
            previous["percent_complete"] if previous else None
        )
        # Carry the previously-settled edition URL into the update so the writer
        # can navigate straight to it instead of re-searching by title.
        previous_url = previous.get("book_url") if previous else None

        if previous_percent is None:
            updates.append(
                {
                    **book,
                    "reason": "new",
                    "previous_percent": None,
                    "book_url": previous_url,
                }
            )
        elif abs(current_percent - previous_percent) > 0.01:
            updates.append(
                {
                    **book,
                    "reason": "changed",
                    "previous_percent": previous_percent,
                    "book_url": previous_url,
                }
            )
        else:
            unchanged.append(book)

    return updates, unchanged


def print_diff(updates: list[dict], unchanged: list[dict]) -> None:
    print("\n Audible -> StoryGraph diff\n")

    if updates:
        print("Will update:\n")
        for book in updates:
            if book["reason"] == "new":
                print(f"• {book['title']} (new)")
                print(f"  Progress : {book['percent_complete']}%")
            else:
                print(f"• {book['title']}")
                print(
                    f"  Progress : {book['previous_percent']}% -> {book['percent_complete']}%"
                )
            print()
    else:
        print("No updates needed.\n")

    if unchanged:
        print("Skipping (unchanged):\n")
        for book in unchanged:
            print(f"• {book['title']} ({book['percent_complete']}%)")
        print()


def main():
    """
    Run the sync, recording a "failed" status if it dies.

    Without this an exception (expired StoryGraph session, Playwright timeout,
    Audible CLI failure) escapes to cron's discarded stderr and status.json just
    stops updating. The exception is re-raised so the run script exits non-zero.
    """
    args = parse_args()
    profile = args.profile

    log_file = get_log_path(profile)
    start_ts = time.time()

    try:
        _run(profile, log_file, start_ts)
    except Exception as exc:
        write_failure_status(profile, exc, time.time() - start_ts, log_file)
        raise


def _run(profile: str, log_file: Path, start_ts: float):
    log_line(log_file, "=" * 60)
    log_line(log_file, f"RUN START — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log_line(log_file, f"Profile: {profile}")
    log_line(log_file, "=" * 60)
    log_line(log_file)

    sync_state_path = get_sync_state_path(profile)
    sync_state = load_sync_state(sync_state_path)

    export_library()
    audible_books = get_in_progress_books()

    updates, unchanged = diff_audible_vs_sync(
        audible_books,
        sync_state,
    )

    print_diff(updates, unchanged)

    for book in updates:
        if book["reason"] == "new":
            log_line(log_file, f"UPDATE (new): {book['title']} -> {book['percent_complete']}%")
        else:
            log_line(log_file, f"UPDATE (changed): {book['title']} -> {book['previous_percent']}% -> {book['percent_complete']}%")

    if not updates:
        print("GOOD! Nothing to update in StoryGraph.")
        log_line(log_file, "No updates needed.")
        log_line(log_file, f"RUN END — duration: {time.time() - start_ts:.1f}s")
        log_line(log_file)
        write_status(profile, {
            "status": "success",
            "duration_seconds": round(time.time() - start_ts, 1),
            "books_updated": 0,
            "books_failed": [],
            "books_in_progress": [
                {"title": b["title"], "percent_complete": b["percent_complete"]}
                for b in audible_books
            ],
        })
        return

    print("\n Applying updates to StoryGraph...\n")
    log_line(log_file, "Applying updates to StoryGraph...")

    succeeded_urls = update_books_progress(
        books=updates,
        profile=profile,
        headless=False,
        log_file=log_file,
    )

    failed = [u for u in updates if u["title"] not in succeeded_urls]

    # Only advance sync state for books we actually wrote. Failed books keep
    # their previous value (or are dropped) so they're retried next run instead
    # of being silently treated as synced.
    print("\n Saving sync state...")
    save_sync_state(
        sync_state_path,
        persisted_books(audible_books, failed, sync_state, succeeded_urls),
    )

    duration = round(time.time() - start_ts, 1)

    if failed:
        log_line(log_file, f"PARTIAL — {len(succeeded_urls)} synced, {len(failed)} failed (will retry):")
        for u in failed:
            log_line(log_file, f"  FAILED: {u['title']} -> {u['percent_complete']}%")
    else:
        log_line(log_file, f"GOOD! All {len(succeeded_urls)} update(s) synced and state saved")

    log_line(log_file, f"RUN END — duration: {duration:.1f}s")
    log_line(log_file)

    write_status(profile, {
        "status": "success" if not failed else "partial",
        "duration_seconds": duration,
        "books_updated": len(succeeded_urls),
        "books_failed": [
            {"title": u["title"], "percent_complete": u["percent_complete"]}
            for u in failed
        ],
        "books_in_progress": [
            {"title": b["title"], "percent_complete": b["percent_complete"]}
            for b in audible_books
        ],
    })

if __name__ == "__main__":
    main()
