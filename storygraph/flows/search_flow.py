from typing import Iterable, List
from playwright.sync_api import Page

from storygraph.pages.search_page import SearchPage
from storygraph.models.book_search_result import BookSearchResult


def search_books(
    page: Page,
    titles: Iterable[str],
    max_results_per_title: int = 3,
) -> List[BookSearchResult]:
    """
    Search each title and log the top N results (title + author).
    Returns structured data for future flows.
    """
    search_page = SearchPage(page)
    all_results: List[BookSearchResult] = []

    for query in titles:
        query = query.strip()
        if not query:
            continue

        print(f"\n Searching for: {query}")

        search_page.search(query)
        top_results = search_page.get_top_results(max_results=max_results_per_title)

        for idx, item in enumerate(top_results, start=1):
            all_results.append(
                BookSearchResult(
                    query=query,
                    title=item["title"],
                    author=item["author"],
                    url=item["url"],
                )
            )

    return all_results
