import re
from typing import Optional
from playwright.sync_api import Page, expect, TimeoutError

from storygraph.models.book_search_result import BookSearchResult
from storygraph.pages.search_page import SearchPage


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

            # Require last-name equality
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
            c for c in candidates
            if normalize(c.title) == normalized_expected
        ]

        if len(exact) == 1:
            print(
                f"INFO! Disambiguated by exact title match -> "
                f"{exact[0].title} by {exact[0].author}"
            )
            return exact[0]

        # 2️⃣ Filter out previews / sneak peeks
        filtered = [
            c for c in candidates
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
    status = status.lower().strip()

    expand_button = page.locator("button.expand-dropdown-button:visible")
    expect(expand_button).to_have_count(1, timeout=15000)
    expand_button.click()

    dropdown = page.locator("div.read-status-dropdown-content:visible")
    expect(dropdown).to_have_count(1, timeout=5000)

    buttons = dropdown.locator("button")

    labels = [
        b.inner_text().strip().lower()
        for b in buttons.all()
    ]

    print(f"INFO! Available status options: {labels}")

    # 🎯 If "read" is present, ALWAYS click it
    if status == "read" and "read" in labels:
        for b in buttons.all():
            if b.inner_text().strip().lower() == "read":
                b.click()
                print("GOOD! Explicitly clicked 'read' button")
                print("GOOD! Explicitly set status to 'read'")
                return

        raise RuntimeError("Expected 'read' button not found")

    # 🚫 If "read" is not available, assume already read
    if status == "read":
        print("INFO! 'read' option not available — assuming already read")
        return

    # 🎯 Other statuses (currently reading / did not finish)
    for b in buttons.all():
        if b.inner_text().strip().lower() == status:
            b.click()
            print(f"GOOD! Set reading status to '{status}'")
            return

    print(
        f"INFO! '{status}' option not available — assuming already set"
    )


def update_reading_progress(
    page: Page,
    value: int,
    progress_type: str = "percentage",
) -> bool:
    """
    Updates reading progress.

    Supports:
    - Ebook: percentage / pages
    - Audiobook: percentage (via selector toggle)
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

        number_input = form.locator("input.read-status-progress-number")
        minutes_input = form.locator("input.read-status-progress-minutes")
        select = form.locator("select.read-status-progress-type")

        # 🎧 Audiobook flow
        if minutes_input.is_visible() and select.count() == 1:
            print("INFO! Audiobook detected — switching progress mode to percentage")

            select.select_option("percentage")

            try:
                expect(number_input).to_be_visible(timeout=3000)
            except TimeoutError:
                print("WARNING! Percentage input did not appear for audiobook")
                return False

            number_input.fill(str(value))
            form.locator("input.progress-tracker-update-button").click()
            return True

        # 📖 Ebook flow
        if number_input.is_visible():
            number_input.fill(str(value))

            if select.count() == 1:
                select.select_option(
                    "percentage" if progress_type == "percentage" else "pages"
                )

            form.locator("input.progress-tracker-update-button").click()
            return True

        print("WARNING! No usable progress input found")
        return False

    # --- First attempt ---
    if attempt_set_progress():
        pass
    else:
        print("INFO! Progress update failed — setting status to currently reading")

        try:
            set_reading_status(page, "currently reading")

            # Wait for StoryGraph to re-mount the progress UI
            page.wait_for_selector(
                "button.track-progress-button, button.edit-progress",
                timeout=5000,
            )
        except Exception:
            return False

        if not attempt_set_progress():
            return False

    # --- Verification ---
    actual = get_current_progress_percentage(page)
    if actual is not None and abs(actual - value) <= 1:
        print(f"GOOD! Verified progress: {actual}%")
        return True

    print(
        f"WARNING! Progress verification failed "
        f"(expected {value}%, got {actual})"
    )
    return False


def get_current_progress_percentage(page: Page) -> int | None:
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
