from playwright.sync_api import sync_playwright

from storygraph import config
from storygraph.flows import ensure_logged_in, search_books
from storygraph.flows.navigate_flow import (
    find_matching_book,
    navigate_to_book,
    update_reading_progress,
)
from storygraph.main import get_storage_state_path


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

        ensure_logged_in(
            page,
            config.STORYGRAPH_EMAIL,
            config.STORYGRAPH_PASSWORD,
        )

        if storage_state_path:
            context.storage_state(path=storage_state_path)

        for book in books:
            title = book["title"]
            author = book["authors"]
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
