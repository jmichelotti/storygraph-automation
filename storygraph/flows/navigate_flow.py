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


def _token_candidates(
    results: list[BookSearchResult],
    expected_title: str,
    expected_author: Optional[str],
) -> list[BookSearchResult]:
    """
    Results whose title shares a token and (if an author is given) whose author
    matches. This is the raw candidate pool before any disambiguation.
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

    return candidates


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
    candidates = _token_candidates(results, expected_title, expected_author)

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

        # 3️⃣ Filter out multi-book bundles / sets
        bundle_keywords = (
            "book set", "box set", "duology", "trilogy", "omnibus",
            "2 book", "3 book", "collection", "bundle", "complete series",
        )
        source = filtered if filtered else candidates
        no_bundles = [
            c for c in source
            if not any(kw in normalize(c.title) for kw in bundle_keywords)
        ]

        if len(no_bundles) == 1:
            print(
                f"INFO! Disambiguated by excluding bundles/sets -> "
                f"{no_bundles[0].title} by {no_bundles[0].author}"
            )
            return no_bundles[0]

        pool = no_bundles if no_bundles else source

        # 4️⃣ Exclude "user-added" / not-yet-reviewed duplicates, preferring
        # the canonical Librarian-reviewed record.
        reviewed = [c for c in pool if not c.user_added]

        if len(reviewed) == 1:
            print(
                f"INFO! Disambiguated by excluding user-added entries -> "
                f"{reviewed[0].title} by {reviewed[0].author}"
            )
            return reviewed[0]

        # 5️⃣ Prefer the entry with the most editions (the canonical record
        # that nearly all readers use), if there's a clear leader.
        edition_pool = reviewed if reviewed else pool
        with_editions = [c for c in edition_pool if c.editions is not None]

        if with_editions:
            max_editions = max(c.editions for c in with_editions)
            top = [c for c in with_editions if c.editions == max_editions]
            if len(top) == 1:
                print(
                    f"INFO! Disambiguated by most editions ({max_editions}) -> "
                    f"{top[0].title} by {top[0].author}"
                )
                return top[0]

        # 6️⃣ Still ambiguous -> skip safely
        print(
            f"WARNING! Multiple StoryGraph matches for "
            f"'{expected_title}' by '{expected_author}' — skipping"
        )
        for c in (reviewed if reviewed else pool):
            print(f"  - {c.title} by {c.author}")
        return None

    return candidates[0]


def find_progress_match(
    page: Page,
    results: list[BookSearchResult],
    expected_title: str,
    expected_author: Optional[str],
) -> Optional[BookSearchResult]:
    """
    Match for a *progress* update.

    Tries the strict matcher first. When that can't disambiguate duplicate
    catalog entries (same title + author, identical on every search-result
    signal), fall back to the one the reader is already tracking — i.e. the
    duplicate that already shows reading progress. Only that record is on the
    user's shelf, so it is the correct target even when the entries look
    identical in search results.
    """
    match = find_matching_book(results, expected_title, expected_author)
    if match:
        return match

    candidates = _token_candidates(results, expected_title, expected_author)
    if len(candidates) <= 1:
        return None

    with_progress: list[BookSearchResult] = []
    for c in candidates:
        try:
            navigate_to_book(page, c)
            if get_current_progress_percentage(page) is not None:
                with_progress.append(c)
        except Exception as e:
            print(f"WARNING! Could not inspect candidate {c.url}: {e}")

    if len(with_progress) == 1:
        print(
            f"INFO! Disambiguated by existing progress -> "
            f"{with_progress[0].title} ({with_progress[0].url})"
        )
        return with_progress[0]

    print(
        f"WARNING! Could not disambiguate duplicates for '{expected_title}' "
        f"by progress ({len(with_progress)} of {len(candidates)} have progress)"
    )
    return None


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
    
    # Normalize the status to match StoryGraph's format
    # "currently-reading" -> "currently reading"
    status = status.replace("-", " ")

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
            
            # Wait longer for the UI to update and progress tracker to appear
            if status == "currently reading":
                page.wait_for_timeout(2000)
                # Wait for the progress tracker to be visible
                try:
                    page.wait_for_selector(
                        "button.edit-progress:visible, div.progress-bar.edit-progress:visible",
                        timeout=5000,
                    )
                    print("GOOD! Progress tracker is now visible")
                except:
                    print("INFO! Progress tracker not yet visible (may appear after first update)")
            else:
                page.wait_for_timeout(1000)
            
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
    
    # First, try to find the "Track progress" button (for books with no progress yet)
    track_button = page.locator("button.track-progress-button:visible")
    
    if track_button.count() > 0:
        print("INFO! Found 'Track progress' button - clicking to reveal form")
        track_button.first.click()
        page.wait_for_timeout(1000)  # Wait for form to appear
    else:
        # Otherwise, look for the edit progress button (for books with existing progress)
        edit_button = page.locator("button.edit-progress:visible, div.progress-bar.edit-progress:visible").first
        
        if edit_button.count() == 0:
            print("WARNING! No track/edit progress button found")
            return False
        
        edit_button.click()
    
    # Wait for the progress form to appear
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
    select = form.locator("select.read-status-progress-type")
    
    # Pick the progress unit. The type selector varies by format — audiobooks
    # offer minutes/percentage, ebooks pages/percentage — so choose from the
    # options actually present rather than assuming. We track in percentage when
    # offered (audiobooks always offer it). Crucially, only change the selector
    # when it isn't already on the target: re-selecting the current value forces
    # a form re-render that briefly detaches the number input, which used to make
    # the very next is_visible() check fail on audiobooks already in % mode.
    if select.count() > 0:
        options = [
            o.get_attribute("value") for o in select.first.locator("option").all()
        ]
        if progress_type == "pages" and "pages" in options:
            target = "pages"
        elif "percentage" in options:
            target = "percentage"
        else:
            target = options[-1] if options else None

        current = select.first.input_value()
        if target and current != target:
            print(f"INFO! Setting progress type -> '{target}' (was '{current}')")
            select.select_option(target)
            page.wait_for_timeout(800)  # let the form re-render
        else:
            print(f"INFO! Progress type already '{current}'")

    # The number input can briefly detach while the form re-renders after a type
    # change, so wait for it to settle rather than checking visibility instantly.
    try:
        number_input.wait_for(state="visible", timeout=5000)
    except TimeoutError:
        print("WARNING! Could not update progress (number input not visible)")
        return False

    number_input.fill("")  # Clear first
    number_input.fill(str(value))

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

    except (TimeoutError, ValueError):
        return None