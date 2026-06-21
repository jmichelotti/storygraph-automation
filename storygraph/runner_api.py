import re
from contextlib import contextmanager
from pathlib import Path
from playwright.sync_api import sync_playwright

from profiles.load_profile import load_profile
from storygraph.flows import ensure_logged_in, search_books
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
) -> set[str]:
    """
    Update StoryGraph progress for multiple books in a single browser session.

    Each book dict must contain:
      - title
      - authors
      - percent_complete

    Returns the set of titles whose progress was actually written and verified.
    Books that were skipped (no match) or failed to write are NOT included, so
    the caller can avoid advancing sync state for them and retry next run.
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

            percent = int(round(book["percent_complete"]))

            print(f"\n Updating StoryGraph: {title} -> {percent}%")

            # Guard each book so one failure (a flaky page, a duplicate that
            # can't be disambiguated) can never abort the whole run or be
            # silently recorded as synced — log it and move on; an unsynced
            # book is simply retried next run.
            try:
                results = search_books(
                    page,
                    [f"{title} {author}"],
                    max_results_per_title=3,
                )

                match = find_progress_match(
                    page,
                    results,
                    expected_title=title,
                    expected_author=author,
                )

                if not match:
                    _log(f"FAILED (no match): {title} -> {percent}% (will retry next run)")
                    print(f"WARNING! No StoryGraph match for '{title}' — skipping")
                    continue

                navigate_to_book(page, match)

                # Set to currently-reading before updating progress
                # (required for new books that don't have a progress tracker yet)
                set_reading_status(page, "currently-reading")

                success = update_reading_progress(
                    page,
                    percent,
                    progress_type="percentage",
                )

                if success:
                    applied.add(title)
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
                query = f"{title} {author}" if author else title

                _log(
                    f"SG SEARCH -> '{query}' "
                    f"(raw author: '{raw_author}' -> normalized: '{author}')"
                )
                print(
                    f"SEARCH QUERY -> '{query}' "
                    f"(title='{title}' author='{author}')"
                )

                results = search_books(
                    page,
                    [query],
                    max_results_per_title=3,
                )

                _log(f"SG RESULTS -> {len(results)} result(s): "
                     + ", ".join(f"'{r.title}' by '{r.author}'" for r in results))

                match = find_matching_book(
                    results,
                    expected_title=title,
                    expected_author=author,
                )

                # Fallback: StoryGraph truncates searches at '&', returning unrelated
                # results. If no match was found and the query contains '&', retry
                # with 'and' before giving up.
                if not match and "&" in query:
                    fallback_query = query.replace("&", "and")
                    _log(f"SG SEARCH FALLBACK (& -> and) -> '{fallback_query}'")
                    print(f"RETRY SEARCH (& -> and) -> '{fallback_query}'")
                    results = search_books(
                        page,
                        [fallback_query],
                        max_results_per_title=3,
                    )
                    _log(f"SG FALLBACK RESULTS -> {len(results)} result(s): "
                         + ", ".join(f"'{r.title}' by '{r.author}'" for r in results))
                    match = find_matching_book(
                        results,
                        expected_title=title,
                        expected_author=author,
                    )

                # Fallback: StoryGraph truncates searches at ',' so titles with
                # parentheticals like "(The Selvaren, #1)" return no results.
                # Strip the parenthetical and retry with just the base title.
                if not match and re.search(r'\(', title):
                    stripped_title = re.sub(r'\s*\([^)]*\)', '', title).strip()
                    if stripped_title and stripped_title != title:
                        fallback_query = f"{stripped_title} {author}" if author else stripped_title
                        _log(f"SG SEARCH FALLBACK (strip parens) -> '{fallback_query}'")
                        print(f"RETRY SEARCH (strip parens) -> '{fallback_query}'")
                        results = search_books(
                            page,
                            [fallback_query],
                            max_results_per_title=3,
                        )
                        _log(f"SG FALLBACK RESULTS (strip parens) -> {len(results)} result(s): "
                             + ", ".join(f"'{r.title}' by '{r.author}'" for r in results))
                        match = find_matching_book(
                            results,
                            expected_title=title,
                            expected_author=author,
                        )

                # Fallback: Goodreads often appends a subtitle after a colon
                # (e.g. "Annie Knows Everything: A Novel") that StoryGraph does not
                # index, so the full query returns no results. Strip everything from
                # the first colon onward and retry with just the main title.
                if not match and ":" in title:
                    stripped_title = title.split(":", 1)[0].strip()
                    if stripped_title and stripped_title != title:
                        fallback_query = f"{stripped_title} {author}" if author else stripped_title
                        _log(f"SG SEARCH FALLBACK (strip subtitle) -> '{fallback_query}'")
                        print(f"RETRY SEARCH (strip subtitle) -> '{fallback_query}'")
                        results = search_books(
                            page,
                            [fallback_query],
                            max_results_per_title=3,
                        )
                        _log(f"SG FALLBACK RESULTS (strip subtitle) -> {len(results)} result(s): "
                             + ", ".join(f"'{r.title}' by '{r.author}'" for r in results))
                        match = find_matching_book(
                            results,
                            expected_title=title,
                            expected_author=author,
                        )

                if not match:
                    _log(f"WARNING! No StoryGraph match for '{title}' by '{author}'")
                    print(f"WARNING! No exact StoryGraph match found for '{title}'")
                    continue

                _log(f"SG MATCH -> '{match.title}' by '{match.author}' @ {match.url}")

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
            except Exception as exc:
                _log(f"ERROR! Failed to sync '{title}': {exc!r} — skipping (will retry next run)")
                print(f"ERROR! Failed to sync '{title}': {exc!r} — skipping")
                continue

    return applied