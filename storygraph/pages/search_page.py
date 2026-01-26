from playwright.sync_api import Page

class SearchPage:
    def __init__(self, page: Page):
        self.page = page

        # Search UI
        self.search_input = "input[type=search]"

        # Anchor that confirms the results UI is present
        self.results_heading = "#search-results-for"

        # Book link patterns
        # - good: /books/<uuid>
        # - bad: /books/<uuid>/editions, /books/new
        self.book_link_in_results = (
            f"{self.results_heading} >> xpath=following::a"
        )

    def goto(self) -> None:
        self.page.goto(
            "https://app.thestorygraph.com/browse",
            wait_until="domcontentloaded",
        )

    def search(self, query: str) -> None:
        self.goto()

        self.page.wait_for_selector(self.search_input, timeout=15000)
        self.page.fill(self.search_input, query)
        self.page.press(self.search_input, "Enter")

        # GOOD! Wait for the *actual* “Search results for 'query'” heading
        self.page.wait_for_selector(self.results_heading, timeout=20000)

        # Optional extra safety: make sure it contains “Search results for”
        # (Prevents false positives if the element exists but results didn’t refresh)
        heading_text = self.page.locator(self.results_heading).inner_text().lower()
        if "search results for" not in heading_text:
            raise RuntimeError(f"Results heading didn't look right: {heading_text}")

    def get_top_results(self, max_results: int = 3):
        """
        Extract exactly the top N *unique* book results.
        Deduplicates by (title, author, url).
        """

        book_panes = self.page.locator("div.book-pane-content")

        results = []
        seen = set()  # (title, author, url)

        pane_count = book_panes.count()

        for i in range(pane_count):
            pane = book_panes.nth(i)

            # --- Title + URL ---
            title_link = pane.locator('h3 a[href^="/books/"]').first
            if title_link.count() == 0:
                continue

            title = title_link.inner_text().strip()
            href = title_link.get_attribute("href")
            if not href:
                continue

            url = f"https://app.thestorygraph.com{href}"

            # --- Author ---
            author = None
            author_link = pane.locator('h3 a[href^="/authors/"]')
            if author_link.count() > 0:
                author = author_link.first.inner_text().strip()

            key = (title, author, url)
            if key in seen:
                continue  #  duplicate (desktop/mobile/etc.)

            seen.add(key)
            results.append({
                "title": title,
                "author": author,
                "url": url,
            })

            # GOOD! Explicitly stop at top N unique results
            if len(results) >= max_results:
                break

        return results


