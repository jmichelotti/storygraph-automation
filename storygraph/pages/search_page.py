from playwright.sync_api import Page, TimeoutError

class SearchPage:
    def __init__(self, page: Page):
        self.page = page

        # Search UI
        self.search_input = "input[type=search]"

        # Anchor that confirms the results UI is present
        self.results_heading = "#search-results-for"

        # Paragraph shown when search returns no matches at all
        self.no_results_message = "p.mt-8"

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

        # Wait for either the results heading OR the "no results" paragraph.
        # When StoryGraph finds nothing it shows p.mt-8 instead of #search-results-for,
        # so waiting only for the heading would time out (20 s) on zero-result searches.
        self.page.wait_for_selector(
            f"{self.results_heading}, {self.no_results_message}",
            timeout=20000,
        )

        # Only validate the heading if it actually appeared (it won't on no-results pages)
        if self.page.locator(self.results_heading).count() > 0:
            heading_text = self.page.locator(self.results_heading).inner_text().lower()
            if "search results for" not in heading_text:
                raise RuntimeError(f"Results heading didn't look right: {heading_text}")

    def get_top_results(self, max_results: int = 3):
        """
        Extract exactly the top N *unique* book results.
        Deduplicates by (title, author, url).
        """

        # Wait for at least one book pane to render — the results heading can
        # appear before the individual book cards are in the DOM.
        try:
            self.page.wait_for_selector("div.book-pane-content", timeout=10000)
        except TimeoutError:
            return []

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

            # --- Author (join all listed authors) ---
            author = None
            author_links = pane.locator('h3 a[href^="/authors/"]')
            if author_links.count() > 0:
                names = [a.inner_text().strip() for a in author_links.all()]
                author = ", ".join(names)

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
