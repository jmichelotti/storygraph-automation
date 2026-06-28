import re
from contextlib import contextmanager
from pathlib import Path
from playwright.sync_api import sync_playwright

from profiles.load_profile import load_profile
from storygraph.flows import ensure_logged_in, search_books, ensure_book_format
from storygraph.flows.navigate_flow import (
    find_matching_book,
    find_progress_match,
    navigate_to_book,
    set_reading_status,
    update_reading_progress,
)
from storygraph.main import get_storage_state_path
from storygraph.flows.read_dates_flow import set_read_dates


def normalize_author_for_search(author: str | None) -> str | None:
    """
    Convert Goodreads-style 'Last, First' -> 'First Last'
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


def search_book_with_fallbacks(page, title, author, match_fn, log=None):
    """
    Search StoryGraph for a book, retrying with progressively simplified queries
    to work around StoryGraph's search quirks:
      - it truncates at '&'              -> retry with 'and'
      - it drops parenthetical series tags like '(The Selvaren, #1)'
      - it doesn't index ':' subtitles  -> e.g. 'Allegiance: Star Wars Legends',
        'Annie Knows Everything: A Novel'

    `match_fn(results)` selects the match from a result list — pass
    `find_matching_book` for reads or a `find_progress_match` closure for
    progress. Returns the matched BookSearchResult or None. Used by both the
    Goodreads (read) and Audible (progress) paths so the quirk handling stays in
    one place.
    """
    def emit(msg: str) -> None:
        print(msg)
        if log:
            log(msg)

    base = f"{title} {author}" if author else title
    attempts = [("initial", base)]
    if "&" in base:
        attempts.append(("& -> and", base.replace("&", "and")))
    if re.search(r"\(", title):
        stripped = re.sub(r"\s*\([^)]*\)", "", title).strip()
        if stripped and stripped != title:
            attempts.append(
                ("strip parens", f"{stripped} {author}" if author else stripped)
            )
    if ":" in title:
        stripped = title.split(":", 1)[0].strip()
        if stripped and stripped != title:
            attempts.append(
                ("strip subtitle", f"{stripped} {author}" if author else stripped)
            )

    for label, query in attempts:
        emit(f"SG SEARCH ({label}) -> '{query}'")
        results = search_books(page, [query], max_results_per_title=3)
        emit(
            f"SG RESULTS -> {len(results)} result(s): "
            + ", ".join(f"'{r.title}' by '{r.author}'" for r in results)
        )
        match = match_fn(results)
        if match:
            emit(f"SG MATCH -> '{match.title}' by '{match.author}' @ {match.url}")
            return match

    emit(f"SG NO MATCH for '{title}' by '{author}'")
    return None


@contextmanager
def storygraph_session(profile: str, headless: bool = False):
    """
    Launch a Playwright browser, log into StoryGraph, and yield the page.
    Saves session state and closes the browser on exit (even on error).
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        storage_state_path = get_storage_state_path(profile)

        if storage_state_path and storage_state_path.exists():
            print(f" Using StoryGraph browser state: {storage_state_path.name}")
            context = browser.new_context(storage_state=storage_state_path)
        else:
            print("Starting new StoryGraph browser session")
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

        try:
            yield page
        finally:
            context.close()
            browser.close()


def update_books_progress(
    books: list[dict],
    profile: str,
    headless: bool = False,
    log_file: Path | None = None,
) -> dict[str, str]:
    """
    Update StoryGraph progress for multiple books in a single browser session.

    Each book dict must contain:
      - title
      - authors
      - percent_complete
      - book_url (optional): the edition URL we settled on a previous run. When
        present we navigate straight to it instead of searching — this both skips
        the (sometimes ambiguous) title search and keeps us on the audiobook
        edition we previously switched to.

    Returns a mapping of title -> settled edition URL for every book whose
    progress was actually written and verified. Books that were skipped (no
    match) or failed to write are NOT included, so the caller can avoid advancing
    sync state for them and retry next run. The settled URL is the audiobook
    edition the book now lives on, which the caller persists for next time.
    """
    def _log(msg: str = "") -> None:
        if log_file:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")

    applied: dict[str, str] = {}

    with storygraph_session(profile, headless) as page:
        for book in books:
            title = book["title"]
            raw_author = book.get("authors") or book.get("author")
            author = normalize_author_for_search(raw_author)
            stored_url = book.get("book_url")

            percent = int(round(book["percent_complete"]))

            print(f"\n Updating StoryGraph: {title} -> {percent}%")

            # Guard each book so one failure (a flaky page, a duplicate that
            # can't be disambiguated) can never abort the whole run or be
            # silently recorded as synced — log it and move on; an unsynced
            # book is simply retried next run.
            try:
                if stored_url:
                    # We already know the exact edition for this book — go there
                    # directly rather than searching again.
                    print(f"INFO! Using stored edition -> {stored_url}")
                    _log(f"SG DIRECT -> {title} @ {stored_url}")
                    page.goto(stored_url, wait_until="domcontentloaded")
                    page.wait_for_selector(
                        "#storygraph-preview-pane-desktop", timeout=30000
                    )
                    match_url = stored_url
                else:
                    match = search_book_with_fallbacks(
                        page,
                        title,
                        author,
                        lambda results: find_progress_match(
                            page, results, expected_title=title, expected_author=author
                        ),
                        log=_log,
                    )

                    if not match:
                        _log(f"FAILED (no match): {title} -> {percent}% (will retry next run)")
                        print(f"WARNING! No StoryGraph match for '{title}' — skipping")
                        continue

                    navigate_to_book(page, match)
                    match_url = match.url

                # Set to currently-reading before updating progress
                # (required for new books that don't have a progress tracker yet)
                set_reading_status(page, "currently-reading")

                success = update_reading_progress(
                    page,
                    percent,
                    progress_type="percentage",
                )

                if success:
                    # Audible books are audiobooks — make sure StoryGraph shows
                    # them as one. ensure_book_format moves the (just-written)
                    # progress to an audio edition and returns its URL, which we
                    # persist so the next run goes straight there.
                    settled_url = ensure_book_format(
                        page, match_url, "audiobook", log=_log
                    )
                    applied[title] = settled_url
                    _log(f"OK (synced): {title} -> {percent}%")
                    print(f"GOOD! Synced '{title}' -> {percent}%")
                else:
                    _log(f"FAILED (write): {title} -> {percent}% (will retry next run)")
                    print(f"WARNING! Progress update failed for '{title}'")
            except Exception as e:
                _log(f"FAILED (error): {title} -> {percent}% — {e} (will retry next run)")
                print(f"WARNING! Error updating '{title}': {e}")
                continue

    return applied


def update_books_read(
    books: list[dict],
    profile: str,
    headless: bool = False,
    log_file: Path | None = None,
) -> set[str]:
    """
    Mark books as READ on StoryGraph and set start / finish dates.

    Each book dict must contain:
      - title
      - authors
      - date_started (YYYY-MM-DD | None)
      - date_finished (YYYY-MM-DD)
    """
    def _log(msg: str = "") -> None:
        if log_file:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")

    applied: set[str] = set()

    with storygraph_session(profile, headless) as page:
        for book in books:
            title = book["title"]
            raw_author = book.get("authors") or book.get("author")
            author = normalize_author_for_search(raw_author)

            date_started = book.get("date_started")
            date_finished = book.get("date_finished")

            print(f"\n Updating StoryGraph (READ): {title}")

            # Guard each book so one failure (a flaky page, an unexpected
            # StoryGraph state) can never abort the whole run — log it and
            # move on; an unsynced book is simply retried next run.
            try:
                _log(f"SG AUTHOR raw '{raw_author}' -> normalized '{author}'")

                match = search_book_with_fallbacks(
                    page,
                    title,
                    author,
                    lambda results: find_matching_book(
                        results, expected_title=title, expected_author=author
                    ),
                    log=_log,
                )

                if not match:
                    print(f"WARNING! No exact StoryGraph match found for '{title}'")
                    continue

                navigate_to_book(page, match)

                set_reading_status(page, "read")

                set_read_dates(
                    page,
                    start_date=date_started,
                    finish_date=date_finished,
                )

                print("GOOD! Book marked as read with dates")
                _log(f"GOOD! Marked as read: '{title}' (start={date_started}, finish={date_finished})")
                applied.add(book["review_id"])

                # Goodreads books are read in print — force a physical edition so
                # they don't land on StoryGraph as audiobooks. Best-effort: the
                # book is already (verified) marked read above, so a format
                # failure here only logs and never un-does the sync.
                ensure_book_format(page, match.url, "physical", log=_log)
            except Exception as exc:
                _log(f"ERROR! Failed to sync '{title}': {exc!r} — skipping (will retry next run)")
                print(f"ERROR! Failed to sync '{title}': {exc!r} — skipping")
                continue

    return applied