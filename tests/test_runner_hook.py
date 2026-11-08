"""The read export runs inside the sync's browser, while the read shelf is still the open page."""
import contextlib

import pytest

pytest.importorskip("playwright")   # runner imports Playwright at module level

from goodreads import runner  # noqa: E402
from goodreads.library import GoodreadsBookStub  # noqa: E402


@pytest.fixture
def wired(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    events = []

    class Page:
        url = "list"

    class Ctx:
        def new_page(self):
            return Page()

        def close(self):
            events.append("close")

    @contextlib.contextmanager
    def fake_pw():
        yield object()

    monkeypatch.setattr(runner, "sync_playwright", fake_pw)
    monkeypatch.setattr(runner, "get_browser", lambda p, profile, headless: (Ctx(), Ctx()))
    monkeypatch.setattr(runner, "ensure_logged_in", lambda page, ctx, profile: None)

    def fetch(page):
        events.append("list-loaded")
        return [GoodreadsBookStub("1", "9", "T", "A", "u")]
    monkeypatch.setattr(runner, "fetch_read_books", fetch)

    def details(page, book):
        events.append("review-page")
        return {"title": "T", "author": "A", "date_started": None, "date_read": None}
    monkeypatch.setattr(runner, "fetch_review_details", details)
    monkeypatch.setattr(runner, "export_read", lambda profile, page, log: events.append("read-export") or {})
    monkeypatch.setattr(runner, "write_status", lambda *a, **k: None)
    return events


def test_export_runs_after_list_and_before_review_pages(wired):
    runner._run(profile="kim", dry_run=False)
    assert wired.index("list-loaded") < wired.index("read-export") < wired.index("review-page")


def test_export_skipped_on_dry_run_and_seed(wired):
    runner._run(profile="kim", dry_run=True)
    assert "read-export" not in wired
