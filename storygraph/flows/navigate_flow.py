import re
from typing import Optional
from playwright.sync_api import Page, expect, TimeoutError

from storygraph.models.book_search_result import BookSearchResult
from storygraph.pages.search_page import SearchPage


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\(.*?\)", " ", text)   # remove parentheticals
    text = re.sub(r"[^\w\s]", " ", text)   # remove punctuation
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokens(text: str) -> set[str]:
    return set(normalize(text).split())


def find_matching_book(
    results: list[BookSearchResult],
    expected_title: str,
    expected_author: Optional[str],
) -> Optional[BookSearchResult]:
    expected_title_tokens = tokens(expected_title)

    expected_author_last = None
    if expected_author:
        expected_author_last = normalize(expected_author).split()[-1]

    for r in results:
        if not r.title:
            continue

        result_title_tokens = tokens(r.title)

        # Title overlap check
        if not expected_title_tokens.intersection(result_title_tokens):
            continue

        # Author check (last name containment)
        if expected_author_last and r.author:
            if expected_author_last not in normalize(r.author):
                continue

        return r  # FIRST confident match wins

    return None


def navigate_to_book(page: Page, book: BookSearchResult) -> None:
    """
    Navigate to the book's page, wait for the StoryGraph preview pane,
    then wait an additional 3 seconds before returning.
    """
    page.goto(book.url, wait_until="domcontentloaded")

    # Basic sanity check: page title contains book title
    if normalize(book.title) not in page.title().lower():
        print(f"WARNING! Warning: navigated page title did not match expected book: {book.title}")

    # GOOD! Wait for the StoryGraph preview pane to appear
    page.wait_for_selector(
        "#storygraph-preview-pane-desktop",
        timeout=30000,
    )

    print("GOOD! StoryGraph preview pane loaded")

def set_reading_status(page: Page, status: str) -> None:
    """
    Set the reading status for the currently opened book.

    Valid statuses:
      - "to read"
      - "currently reading"
      - "read"
      - "did not finish"
    """

    status = status.lower().strip()

    # 1️⃣ Click the *visible* expand dropdown button
    expand_button = page.locator("button.expand-dropdown-button:visible")
    expect(expand_button).to_have_count(1, timeout=15000)
    expand_button.click()

    # 2️⃣ Wait for the *visible* dropdown content
    dropdown = page.locator("div.read-status-dropdown-content:visible")
    expect(dropdown).to_have_count(1, timeout=5000)

    # 3️⃣ Click the desired status option by visible text
    option = dropdown.locator("button", has_text=status)
    expect(option).to_be_visible(timeout=5000)
    option.click()

    print(f"GOOD! Set reading status to '{status}'")
    page.wait_for_timeout(3000)

def update_reading_progress(
    page: Page,
    value: int,
    progress_type: str = "pages",
) -> bool:
    """
    Attempts to update progress and verify it.
    Returns True if verified, False otherwise.
    """

    def attempt_set_progress() -> bool:
        trigger = page.locator(
            "button.track-progress-button:visible, button.edit-progress:visible"
        )

        if trigger.count() < 1:
            return False

        trigger.first.click()

        form = page.locator("div.progress-tracking-form:visible")
        try:
            form.wait_for(timeout=5000)
        except TimeoutError:
            return False

        form.locator("input.read-status-progress-number").fill(str(value))

        select = form.locator("select.read-status-progress-type")
        if select.count() == 1:
            select.select_option(
                "percentage" if progress_type == "percentage" else "pages"
            )
        else:
            print("INFO! Progress type selector not present — assuming default")

        form.locator("input.progress-tracker-update-button").click()

        page.wait_for_selector("div.progress-bar span", timeout=5000)
        return True


    # --- First attempt ---
    if not attempt_set_progress():
        print("INFO! No progress UI — setting status to currently reading")

        try:
            set_reading_status(page, "currently reading")
            page.wait_for_timeout(500)
        except Exception:
            print("WARNING! Failed to set reading status")
            return False

        # --- Retry after escalation ---
        if not attempt_set_progress():
            print("WARNING! Still could not open progress form after status change")
            return False

    # --- Verification ---
    actual = get_current_progress_percentage(page)
    if actual is not None and abs(actual - value) <= 1:
        print(f"GOOD! Verified progress: {actual}%")
        return True

    # --- Retry once ---
    print(f" Progress mismatch (expected {value}%, got {actual}%) — retrying")
    page.wait_for_timeout(1500)

    if not attempt_set_progress():
        return False

    actual_retry = get_current_progress_percentage(page)
    if actual_retry is not None and abs(actual_retry - value) <= 1:
        print(f"GOOD! Verified after retry: {actual_retry}%")
        return True

    print(
        f"WARNING! Progress verification failed after retry "
        f"(expected {value}%, got {actual_retry}%)"
    )
    return False


def get_current_progress_percentage(page: Page) -> int | None:
    """
    Reads the visible progress percentage from the progress bar.
    Returns an int (e.g. 25) or None if not found.
    """
    try:
        progress_text = (
            page.locator("div.progress-bar span")
            .filter(has_text="%")
            .first
        )

        if not progress_text.is_visible():
            return None

        raw = progress_text.inner_text().strip()
        return int(raw.replace("%", ""))

    except Exception:
        return None
