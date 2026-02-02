from dataclasses import dataclass
from typing import Optional

@dataclass
class GoodreadsBookStub:
    book_id: str
    review_id: str
    title: str
    author: str
    url: str


# Force sort by "Date Read" (most recent first)
READ_SHELF_URL = (
    "https://www.goodreads.com/review/list"
    "?shelf=read"
    "&sort=date_read"
    "&order=d"
)


def fetch_read_books(page):
    page.goto(
        READ_SHELF_URL,
        wait_until="domcontentloaded",
        timeout=30_000,
    )

    page.wait_for_selector("tr.bookalike.review", timeout=30_000)

    rows = page.locator("tr.bookalike.review")
    count = rows.count()

    print(f"Found {count} read books (sorted by date read)")

    books = []

    for i in range(count):
        row = rows.nth(i)

        # review_<id>
        review_attr = row.get_attribute("id")
        if not review_attr:
            continue

        review_id = review_attr.replace("review_", "")

        # Title + book id
        title_link = row.locator("td.field.title a").first
        title = title_link.inner_text().strip()
        href = title_link.get_attribute("href")

        if not href or "/book/show/" not in href:
            continue

        book_id = href.split("/book/show/")[1].split("-")[0]
        book_url = f"https://www.goodreads.com{href}"

        author = row.locator("td.field.author a").inner_text().strip()

        books.append(
            GoodreadsBookStub(
                book_id=book_id,
                review_id=review_id,
                title=title,
                author=author,
                url=book_url,
            )
        )

    return books
