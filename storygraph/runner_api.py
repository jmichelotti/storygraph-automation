from playwright.sync_api import sync_playwright

from profiles.load_profile import load_profile
from storygraph.flows import ensure_logged_in, search_books
from storygraph.flows.navigate_flow import (
    find_matching_book,
    navigate_to_book,
    update_reading_progress,
)
from storygraph.main import get_storage_state_path
from datetime import date

from storygraph.flows.navigate_flow import (
    set_reading_status,
)
from storygraph.flows.read_dates_flow import set_read_dates

def normalize_author_for_search(author: str | None) -> str | None:
    """
    Convert Goodreads-style 'Last, First' → 'First Last'
    Leaves already-normalized names untouched.
    """
    if not author:
        return None

    author = author.strip()

    if "," in author:
        last, first = [p.strip() for p in author.split(",", 1)]
        if first and last:
            return f"{first} {last}"

    return author

def update_books_progress(
    books: list[dict],
    profile: str,
    headless: bool = False,
) -> None:
    """
    Update StoryGraph progress for multiple books in a single browser session.

    Each book dict must contain:
      - title
      - authors
      - percent_complete
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        storage_state_path = get_storage_state_path(profile)

        if storage_state_path and storage_state_path.exists():
            print(f" Using StoryGraph browser state: {storage_state_path.name}")
            context = browser.new_context(storage_state=storage_state_path)
        else:
            print("🆕 Starting new StoryGraph browser session")
            context = browser.new_context()

        page = context.new_page()

        creds = load_profile(profile)

        ensure_logged_in(
            page,
            creds["storygraph_email"],
            creds["storygraph_password"],
        )

        if storage_state_path:
            context.storage_state(path=storage_state_path)

        for book in books:
            title = book["title"]
            raw_author = book.get("authors") or book.get("author")
            author = normalize_author_for_search(raw_author)

            percent = int(round(book["percent_complete"]))

            print(f"\n Updating StoryGraph: {title} -> {percent}%")

            results = search_books(
                page,
                [f"{title} {author}"],
                max_results_per_title=3,
            )

            match = find_matching_book(
                results,
                expected_title=title,
                expected_author=author,
            )

            if not match:
                print(f"WARNING! No exact StoryGraph match found for '{title}'")
                continue

            navigate_to_book(page, match)
            success = update_reading_progress(
                page,
                percent,
                progress_type="percentage",
            )

            if not success:
                print(f"⏭️ Skipped progress update for '{title}'")

        context.close()
        browser.close()

def update_books_read(
    books: list[dict],
    profile: str,
    headless: bool = False,
) -> None:
    """
    Mark books as READ on StoryGraph and set start / finish dates.

    Each book dict must contain:
      - title
      - authors
      - date_started (YYYY-MM-DD | None)
      - date_finished (YYYY-MM-DD)
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        storage_state_path = get_storage_state_path(profile)

        if storage_state_path and storage_state_path.exists():
            print(f" Using StoryGraph browser state: {storage_state_path.name}")
            context = browser.new_context(storage_state=storage_state_path)
        else:
            print("🆕 Starting new StoryGraph browser session")
            context = browser.new_context()

        page = context.new_page()

        creds = load_profile(profile)

        ensure_logged_in(
            page,
            creds["storygraph_email"],
            creds["storygraph_password"],
        )

        if storage_state_path:
            context.storage_state(path=storage_state_path)

        for book in books:
            title = book["title"]
            raw_author = book.get("authors") or book.get("author")
            author = normalize_author_for_search(raw_author)

            date_started = book.get("date_started")
            date_finished = book.get("date_finished")

            print(f"\n Updating StoryGraph (READ): {title}")

            # 🔍 Search using existing, battle-tested helper
            query = f"{title} {author}" if author else title

            print(
                f"SEARCH QUERY → '{query}' "
                f"(title='{title}' author='{author}')"
            )

            results = search_books(
                page,
                [query],
                max_results_per_title=3,
            )

            match = find_matching_book(
                results,
                expected_title=title,
                expected_author=author,
            )

            if not match:
                print(f"WARNING! No exact StoryGraph match found for '{title}'")
                continue

            navigate_to_book(page, match)

            # 📘 Set status to READ
            set_reading_status(page, "read")

            # 📅 Set dates (if provided)
            set_read_dates(
                page,
                start_date=date_started,
                finish_date=date_finished,
            )

            print("GOOD! Book marked as read with dates")

        context.close()
        browser.close()
