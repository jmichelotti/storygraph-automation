import json
from pathlib import Path
from playwright.sync_api import sync_playwright
import argparse
from datetime import date, datetime
import time

from goodreads.auth import get_browser, ensure_logged_in
from goodreads.library import fetch_read_books
from goodreads.book_details import fetch_review_details

from storygraph.runner_api import update_books_read


# ---------- Logging helpers ----------

def get_log_path(profile: str) -> Path:
    log_dir = Path("logs/goodreads")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{profile}.log"


def log_line(log_file: Path, message: str = ""):
    with log_file.open("a", encoding="utf-8") as f:
        f.write(message + "\n")


# ---------- Profile-scoped state helpers ----------

def get_state_path(profile: str) -> Path:
    state_dir = Path("goodreads/state")
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"state_{profile}.json"


def load_state(profile: str) -> dict:
    path = get_state_path(profile)

    if not path.exists() or path.stat().st_size == 0:
        return {"processed_reviews": []}

    return json.loads(path.read_text(encoding="utf-8"))


def save_state(profile: str, state: dict) -> None:
    path = get_state_path(profile)
    path.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8",
    )


# ---------- Main runner ----------

def run(
    profile: str,
    headless: bool = False,
    dry_run: bool = True,
    seed_before: date | None = None,
):
    log_file = get_log_path(profile)
    run_started_at = datetime.now()
    start_ts = time.time()

    # ----- Log run header -----
    log_line(log_file, "=" * 60)
    log_line(log_file, f"RUN START — {run_started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    log_line(log_file, f"Profile: {profile}")
    log_line(log_file, f"Mode: {'APPLY' if not dry_run else 'DRY RUN'}")
    log_line(
        log_file,
        f"Seed before: {seed_before.isoformat() if seed_before else 'none'}",
    )
    log_line(log_file, "=" * 60)
    log_line(log_file)

    state = load_state(profile)
    processed = set(state.get("processed_reviews", []))

    updates: list[dict] = []
    newly_seeded = 0

    # ---------- PHASE 1: Goodreads ----------
    with sync_playwright() as p:
        browser, context = get_browser(
            p,
            profile=profile,
            headless=headless,
        )
        page = context.new_page()

        ensure_logged_in(page, context, profile=profile)

        goodreads_books = fetch_read_books(page)
        print(f"Found {len(goodreads_books)} read books")
        log_line(log_file, f"Found {len(goodreads_books)} read books")

        for book in goodreads_books:
            if book.review_id in processed:
                continue

            details = fetch_review_details(page, book)
            if not details.get("author"):
                log_line(
                    log_file,
                    f"WARNING! Goodreads author missing — "
                    f"title='{details.get('title')}' review_id={book.review_id}"
                )
            else:
                log_line(
                    log_file,
                    f"DEBUG Goodreads author OK — "
                    f"title='{details['title']}' author='{details['author']}'"
                )

            finished = details["date_read"]

            print(f"\n→ Processing: {details['title']}")

            log_line(
                log_file,
                f"BOOK: {details['title']} | "
                f"start={details['date_started']} | "
                f"finish={details['date_read']}",
            )

            # Skip if Goodreads failed to provide dates
            if not details["date_started"] and not details["date_read"]:
                log_line(
                    log_file,
                    f"SKIP — no dates found: {details['title']}",
                )
                continue

            log_line(log_file, f"→ Processing: {details['title']}")

            # ---------- SEED MODE ----------
            if seed_before:
                if not finished:
                    log_line(log_file, "  Skipped (no finish date)")
                    continue

                finished_date = date.fromisoformat(finished)
                if finished_date < seed_before:
                    processed.add(book.review_id)
                    newly_seeded += 1
                    log_line(
                        log_file,
                        f"  ACTION: seeded (finished {finished})",
                    )
                continue

            # ---------- NORMAL MODE ----------
            log_line(
                log_file,
                f"DEBUG Passing to StoryGraph — "
                f"title='{details['title']}' author='{details.get('author')}'"
            )

            updates.append(
                {
                    "title": details["title"],
                    "author": details["author"],
                    "date_started": details["date_started"],
                    "date_finished": finished,
                    "review_id": book.review_id,
                }
            )

            log_line(
                log_file,
                f"  start={details['date_started']} finish={finished}",
            )

        context.close()
        browser.close()

    # ---------- SEED-ONLY EXIT ----------
    if seed_before:
        state["processed_reviews"] = sorted(processed)
        save_state(profile, state)

        msg = (
            f"GOOD! Seeded {newly_seeded} books "
            f"finished before {seed_before.isoformat()}"
        )
        print(msg)
        log_line(log_file)
        log_line(log_file, msg)

        duration = time.time() - start_ts
        log_line(log_file, f"RUN END — duration: {duration:.1f}s")
        log_line(log_file)
        return

    # ---------- DRY RUN ----------
    if dry_run:
        if updates:
            print("\nDRY RUN — would update the following books on StoryGraph:\n")
            log_line(log_file)
            log_line(log_file, "DRY RUN — books that would be updated:")

            for b in updates:
                line = (
                    f"• {b['title']} "
                    f"(start={b['date_started']}, finish={b['date_finished']})"
                )
                print(line)
                log_line(log_file, line)
        else:
            print("\nNo new Goodreads books to sync.")
            log_line(log_file, "No new Goodreads books to sync.")

        duration = time.time() - start_ts
        log_line(log_file)
        log_line(log_file, f"RUN END — duration: {duration:.1f}s")
        log_line(log_file)
        return

    if not updates:
        print("\nNo new Goodreads books to sync.")
        log_line(log_file, "No new Goodreads books to sync.")

        duration = time.time() - start_ts
        log_line(log_file)
        log_line(log_file, f"RUN END — duration: {duration:.1f}s")
        log_line(log_file)
        return

    # ---------- PHASE 2: StoryGraph ----------
    print("\n Applying updates to StoryGraph...\n")
    log_line(log_file)
    log_line(log_file, "Applying updates to StoryGraph...")

    update_books_read(
        books=updates,
        profile=profile,
        headless=headless,
    )

    # ---------- Persist state ----------
    for b in updates:
        processed.add(b["review_id"])
        log_line(log_file, f"  ACTION: applied → {b['title']}")

    state["processed_reviews"] = sorted(processed)
    save_state(profile, state)

    print("\nGOOD! Goodreads sync complete and state updated")
    log_line(log_file)
    log_line(log_file, "GOOD! Goodreads sync complete and state updated")

    duration = time.time() - start_ts
    log_line(log_file, f"RUN END — duration: {duration:.1f}s")
    log_line(log_file)


# ---------- CLI ----------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sync Goodreads read books to StoryGraph"
    )

    parser.add_argument(
        "--profile",
        required=True,
        help="Profile name (matches profiles/{profile}.json)",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to StoryGraph (default is dry-run)",
    )

    parser.add_argument(
        "--seed-before",
        help="Seed state with all books finished before YYYY-MM-DD",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode",
    )

    args = parser.parse_args()

    seed_date = (
        date.fromisoformat(args.seed_before)
        if args.seed_before
        else None
    )

    run(
        profile=args.profile,
        headless=args.headless,
        dry_run=not args.apply,
        seed_before=seed_date,
    )
