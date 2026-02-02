import json
from datetime import date
from pathlib import Path
from playwright.sync_api import sync_playwright

from goodreads.auth import get_browser, ensure_logged_in
from goodreads.library import fetch_read_books
from goodreads.book_details import fetch_review_details

STATE_PATH = Path("goodreads/state.json")

# 🔧 CHANGE THIS
CUTOFF_DATE = date.fromisoformat("2025-12-31")

def load_state():
    if not STATE_PATH.exists():
        return {"processed_reviews": []}

    with STATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def run():
    state = load_state()
    processed = set(state.get("processed_reviews", []))

    with sync_playwright() as p:
        browser, context = get_browser(p, headless=False)
        page = context.new_page()

        ensure_logged_in(page, context, profile)

        books = fetch_read_books(page)
        print(f"Evaluating {len(books)} Goodreads reviews")

        added = 0

        for book in books:
            if book.review_id in processed:
                continue

            details = fetch_review_details(page, book)
            date_read = details.get("date_read")

            if not date_read:
                continue

            finished = date.fromisoformat(date_read)

            if finished <= CUTOFF_DATE:
                processed.add(book.review_id)
                added += 1
                print(
                    f"[BOOTSTRAP] {details['title']} "
                    f"({date_read}) → marked as processed"
                )

        state["processed_reviews"] = sorted(processed)
        save_state(state)

        print(f"\nBootstrapped {added} reviews into state")
        browser.close()

if __name__ == "__main__":
    run()
