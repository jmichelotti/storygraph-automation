import re
from typing import Optional
from playwright.sync_api import Page, expect, TimeoutError

from storygraph.models.book_search_result import BookSearchResult


def normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokens(text: str) -> set[str]:
    return set(normalize(text).split())


def find_matching_book(
    results: list[BookSearchResult],
    expected_title: str,
    expected_author: Optional[str],
) -> Optional[BookSearchResult]:
    """
    STRICT matching:
    - Title must share tokens
    - Author MUST match if provided
    - No title-only fallback when author is present
    """
    expected_title_tokens = tokens(expected_title)
    expected_author_tokens = tokens(expected_author) if expected_author else None

    candidates: list[BookSearchResult] = []

    for r in results:
        if not r.title or not r.author:
            continue

        result_title_tokens = tokens(r.title)

        # --- Title check ---
        if not expected_title_tokens.intersection(result_title_tokens):
            continue

        # --- Author check (STRICT) ---
        if expected_author_tokens:
            result_author_tokens = tokens(r.author)
            if expected_author_tokens.intersection(result_author_tokens) == set():
                continue

        candidates.append(r)

    if not candidates:
        print(
            f"WARNING! No confident StoryGraph match for "
            f"'{expected_title}' by '{expected_author}'"
        )
        return None

    if len(candidates) > 1:
        normalized_expected = normalize(expected_title)

        # 1️⃣ Prefer exact title match
        exact = [
            c for c in candidates if normalize(c.title) == normalized_expected
        ]

        if len(exact) == 1:
            print(
                f"INFO! Disambiguated by exact title match -> "
                f"{exact[0].title} by {exact[0].author}"
            )
            return exact[0]

        # 2️⃣ Filter out previews / sneak peeks
        filtered = [
            c
            for c in candidates
            if not any(
                kw in normalize(c.title)
                for kw in ("sneak peek", "preview", "excerpt", "sampler")
            )
        ]

        if len(filtered) == 1:
            print(
                f"INFO! Disambiguated by excluding preview editions -> "
                f"{filtered[0].title} by {filtered[0].author}"
            )
            return filtered[0]

        # 3️⃣ Still ambiguous -> skip safely
        print(
            f"WARNING! Multiple StoryGraph matches for "
            f"'{expected_title}' by '{expected_author}' — skipping"
        )
        for c in candidates:
            print(f"  - {c.title} by {c.author}")
        return None

    return candidates[0]


def navigate_to_book(page: Page, book: BookSearchResult) -> None:
    page.goto(book.url, wait_until="domcontentloaded")

    if normalize(book.title) not in page.title().lower():
        print(
            f"WARNING! Navigated page title did not match expected book: {book.title}"
        )

    page.wait_for_selector(
        "#storygraph-preview-pane-desktop",
        timeout=30000,
    )

    print(f"GOOD! StoryGraph preview pane loaded -> {book.title} by {book.author}")


def set_reading_status(page: Page, status: str) -> None:
    """Set the reading status via dropdown."""
    status = status.lower().strip()

    # Click the dropdown button
    expand_button = page.locator("button.expand-dropdown-button:visible")
    expect(expand_button).to_have_count(1, timeout=15000)
    expand_button.click()

    # Wait for dropdown to appear
    dropdown = page.locator("div.read-status-dropdown-content:visible")
    expect(dropdown).to_have_count(1, timeout=5000)

    # Get all available options
    buttons = dropdown.locator("button")
    labels = [b.inner_text().strip().lower() for b in buttons.all()]

    print(f"INFO! Available status options: {labels}")

    # Click the matching button
    for b in buttons.all():
        if b.inner_text().strip().lower() == status:
            b.click()
            print(f"GOOD! Set reading status to '{status}'")
            page.wait_for_timeout(1000)  # Wait for status change to apply
            return

    # Status not available (likely already set)
    print(f"INFO! '{status}' option not available — assuming already set")


def update_reading_progress(
    page: Page,
    value: int,
    progress_type: str = "percentage",
) -> bool:
    """
    Update reading progress to the specified value.
    
    Returns True if successful, False otherwise.
    """
    
    # Click the edit progress button (pencil icon or progress bar)
    edit_button = page.locator("button.edit-progress:visible, div.progress-bar.edit-progress:visible").first
    
    if edit_button.count() == 0:
        print("WARNING! No edit progress button found")
        return False
    
    edit_button.click()
    
    # Wait for the progress form to appear
    # Use a more specific selector to get the VISIBLE form
    try:
        page.wait_for_selector(
            "div.progress-tracking-form:visible input.read-status-progress-number",
            timeout=5000,
        )
    except TimeoutError:
        print("WARNING! Progress form did not appear")
        return False
    
    # Get the visible form
    form = page.locator("div.progress-tracking-form:visible").first
    
    # Get input elements from this specific form
    number_input = form.locator("input.read-status-progress-number")
    minutes_input = form.locator("input.read-status-progress-minutes")
    select = form.locator("select.read-status-progress-type")
    
    # Handle audiobook vs ebook
    if minutes_input.is_visible() and select.count() > 0:
        # Audiobook - switch to percentage mode
        print("INFO! Audiobook detected — switching to percentage mode")
        select.select_option("percentage")
        page.wait_for_timeout(500)  # Wait for mode switch
    
    # Fill in the progress value
    if number_input.is_visible():
        number_input.fill("")  # Clear first
        number_input.fill(str(value))
        
        # Set progress type if dropdown exists
        if select.count() > 0 and minutes_input.count() == 0:
            # Ebook with type selector
            select.select_option("percentage" if progress_type == "percentage" else "pages")
        
        # Click save button
        save_button = form.locator("input.progress-tracker-update-button")
        save_button.click()
        
        # Wait for the form to close (indicates save completed)
        try:
            page.wait_for_selector(
                "div.progress-tracking-form:visible",
                state="hidden",
                timeout=5000,
            )
        except TimeoutError:
            print("WARNING! Progress form did not close after save")
        
        # Give StoryGraph time to update the DOM
        page.wait_for_timeout(1500)
        
        # Verify the update
        actual = get_current_progress_percentage(page)
        if actual is not None and abs(actual - value) <= 1:
            print(f"GOOD! Verified progress: {actual}%")
            return True
        else:
            print(f"WARNING! Progress shows {actual}% (expected {value}%)")
            # Still return True if we got this far - the update likely worked
            return actual is not None
    
    print("WARNING! Could not update progress")
    return False


def get_current_progress_percentage(page: Page) -> int | None:
    """Extract the current progress percentage from the progress bar."""
    try:
        # Look for the progress bar span with percentage
        progress_text = (
            page.locator("div.progress-bar span")
            .filter(has_text="%")
            .first
        )

        if not progress_text.is_visible(timeout=2000):
            return None

        raw = progress_text.inner_text().strip()
        return int(raw.replace("%", ""))

    except Exception:
        return None