from typing import Optional
import re
from datetime import datetime
from playwright.sync_api import TimeoutError


def fetch_review_details(page, book):
    review_url = f"https://www.goodreads.com/review/show/{book.review_id}"

    page.goto(review_url, wait_until="domcontentloaded")

    # Force lazy content to load (important for Task Scheduler runs)
    page.mouse.wheel(0, 2000)
    page.wait_for_timeout(1500)

    try:
        page.wait_for_selector(
            ".readingTimeline__row",
            timeout=20_000,
        )
    except TimeoutError:
        print(
            f"WARNING! Reading timeline not visible — skipping dates: {review_url}"
        )
        return {
            "title": book.title,
            "author": book.author,
            "date_started": None,
            "date_read": None,
        }

    started = None
    finished = None

    rows = page.locator(".readingTimeline__row")
    count = rows.count()

    for i in range(count):
        row = rows.nth(i)
        text = row.inner_text().strip()

        if "Started Reading" in text:
            started = extract_date(text)
        elif "Finished Reading" in text:
            finished = extract_date(text)

    return {
        "title": book.title,
        "author": book.author,
        "date_started": started,
        "date_read": finished,
    }


def extract_date(text: str) -> Optional[str]:
    """
    Extracts 'January 11, 2026' -> '2026-01-11'
    """
    match = re.search(
        r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}",
        text,
    )
    if not match:
        return None

    return datetime.strptime(match.group(0), "%B %d, %Y").date().isoformat()
