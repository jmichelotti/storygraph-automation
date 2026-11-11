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
    monkeypatch.setattr(runner, "export_read_all", lambda profile, page, log: events.append("read-all-export") or {})
    monkeypatch.setattr(runner, "write_status", lambda *a, **k: None)
    return events


def test_export_runs_after_list_and_before_review_pages(wired):
    runner._run(profile="kim", dry_run=False)
    assert wired.index("list-loaded") < wired.index("read-export") < wired.index("review-page")


def test_export_skipped_on_dry_run_and_seed(wired):
    runner._run(profile="kim", dry_run=True)
    assert "read-export" not in wired


def test_read_all_export_runs_after_review_pages_before_browser_closes(wired):
    runner._run(profile="kim", dry_run=False)
    assert wired.index("review-page") < wired.index("read-all-export") < wired.index("close")


def test_read_all_export_skipped_on_dry_run(wired):
    runner._run(profile="kim", dry_run=True)
    assert "read-all-export" not in wired


def test_unsynced_book_is_counted_in_state_and_status_until_it_applies(wired, monkeypatch):
    """Task 182: a book skipped every run is listed in status.json, with its attempt count."""
    import json

    monkeypatch.setattr(runner, "fetch_review_details", lambda page, book: {
        "title": "T", "author": "A", "date_started": None, "date_read": "2026-09-09"})
    statuses = []
    monkeypatch.setattr(runner, "write_status", lambda profile, data: statuses.append(data))
    applied = set()
    monkeypatch.setattr(runner, "update_books_read", lambda **kw: set(applied))
    state_path = runner.get_state_path("kim")

    runner._run(profile="kim", dry_run=False)
    runner._run(profile="kim", dry_run=False)
    stuck = statuses[-1]["books_not_synced"]
    assert [(b["review_id"], b["title"], b["attempts"]) for b in stuck] == [("9", "T", 2)]
    assert json.loads(state_path.read_text())["unsynced"]["9"]["attempts"] == 2

    applied.add("9")
    runner._run(profile="kim", dry_run=False)
    assert statuses[-1]["books_not_synced"] == []
    state = json.loads(state_path.read_text())
    assert "unsynced" not in state and state["processed_reviews"] == ["9"]
