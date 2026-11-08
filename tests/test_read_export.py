"""The kim-read export: collection, completeness and publishing (reading-cards round table D2, A1, A2, A10).

A fake page stands in for Playwright. It answers the module's two extraction scripts with plain
data the way the real list and book pages would, and records every navigation.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from goodreads import read_export
from goodreads.read_parse import normalize_author, parse_rating

PT = timezone(timedelta(hours=-8))
NOW = datetime(2026, 11, 8, 21, 5, tzinfo=PT)        # Sunday 21:05 PST = Monday 00:05 EST
# This week's anchor is Mon 2026-11-09 00:00 ET; the card's week is Nov 2-8; cutoff = Oct 19.


def gr_row(book_id, date_read, title=None, date_started="not set", pages="300 pp", rating_title="it was amazing"):
    return {"review_id": "review_" + book_id, "href": f"/book/show/{book_id}-slug",
            "title": title or f"Book {book_id}", "author": "Example, Jordan *",
            "date_read": date_read + " [edit]", "date_started": date_started, "pages": pages,
            "rating_title": rating_title, "rating_filled": 5,
            "cover": f"https://i.gr-assets.com/images/S/compressed.photo.goodreads.com/books/{book_id}._SY75_.jpg"}


LIST_OK = {"rows": [gr_row("11", "Nov 05, 2026", title="Quiet Harbor (The Lantern Keepers, #2)",
                           date_started="Nov 02, 2026"),
                    gr_row("12", "Nov 02, 2026"),
                    gr_row("13", "Oct 30, 2026"),
                    gr_row("14", "Oct 01, 2026")],
           "printed": "Read ‎(1369)", "has_next": True}


class FakePage:
    def __init__(self, list_data, genres=None):
        self.list_data = list_data
        self.genres = genres or {}
        self.url = "https://www.goodreads.com/review/list?shelf=read&sort=date_read&order=d"
        self.navigations = []

    def goto(self, url, **kw):
        self.navigations.append(url)
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        if script is read_export._ROWS_JS:
            return self.list_data
        if script is read_export._GENRES_JS:
            book_id = self.url.rsplit("/", 1)[-1]
            return self.genres.get(book_id, ["Fiction", "Thriller"])
        raise AssertionError("unexpected script")


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "exports").mkdir()
    (tmp_path / "status").mkdir()
    import status
    monkeypatch.setattr(status, "STATUS_FILE", tmp_path / "status" / "status.json")
    monkeypatch.setattr(read_export, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(read_export.time, "sleep", lambda s: None)
    return tmp_path


def run(page, now=NOW, force=False):
    return read_export.export_read("kim", page, now=now, force=force, log=lambda m: None)


def published(workdir):
    return json.loads((workdir / "exports" / "kim-read.json").read_text(encoding="utf-8"))


def test_publish_is_atomic_0600(workdir):
    page = FakePage(LIST_OK)
    block = run(page)
    assert block["last_status"] == "success"
    files = sorted(p.name for p in (workdir / "exports").iterdir())
    assert "kim-read.json" in files and not [f for f in files if f.endswith(".new")]
    if os.name == "posix":
        assert (workdir / "exports" / "kim-read.json").stat().st_mode & 0o777 == 0o600
    doc = published(workdir)
    assert doc["schema"] == "goodreads-read/1" and doc["complete"] is True
    assert doc["coverage_from"] == "2026-10-19"
    assert doc["scraped_at"] == NOW.isoformat()


def test_books_carry_the_card_fields(workdir):
    run(FakePage(LIST_OK))
    books = {b["gr_book_id"]: b for b in published(workdir)["books"]}
    assert set(books) == {"11", "12", "13"}           # Oct 01 is before the cutoff
    b = books["11"]
    assert b["title"] == "Quiet Harbor" and b["series"] == {"name": "The Lantern Keepers", "number": "2"}
    assert b["title_full"] == "Quiet Harbor (The Lantern Keepers, #2)"
    assert b["author"] == "Jordan Example"
    assert b["date_read"] == "2026-11-05" and b["date_started"] == "2026-11-02"
    assert b["pages"] == 300 and b["rating"] == 5
    assert b["genres"] == ["fiction", "thriller"]
    assert b["cover_url"].startswith("https://i.gr-assets.com/")
    assert books["12"]["date_started"] is None


def test_complete_current_page_costs_no_list_navigation(workdir):
    page = FakePage(LIST_OK)
    run(page)
    assert all("/book/show/" in u for u in page.navigations)   # only genre pages
    assert len(page.navigations) == 3


def test_genre_cache_hit_costs_no_navigation(workdir):
    run(FakePage(LIST_OK))
    page = FakePage(LIST_OK)
    run(page, now=NOW + timedelta(hours=21), force=True)
    assert page.navigations == []


def test_incomplete_keeps_last_good_file(workdir):
    run(FakePage(LIST_OK))
    before = (workdir / "exports" / "kim-read.json").read_bytes()
    broken = {"rows": [gr_row("21", "Nov 07, 2026"), gr_row("22", "garbled")], "printed": "Read (1369)",
              "has_next": True}
    block = run(FakePage(broken), now=NOW + timedelta(hours=21), force=True)
    assert block["last_status"] == "failed" and block["error"] == "unparsed-date"
    assert (workdir / "exports" / "kim-read.json").read_bytes() == before


def test_short_page_walks_to_the_next_list_page(workdir):
    short = {"rows": [gr_row("31", "Nov 05, 2026")], "printed": "Read (1369)", "has_next": True}
    page = FakePage(short)
    pages = iter([short, LIST_OK])
    page.evaluate = (lambda orig: (lambda s: next(pages) if s is read_export._ROWS_JS else orig(s)))(page.evaluate)
    block = run(page)
    assert block["last_status"] == "success"
    assert any("per_page=100" in u and "page=1" in u for u in page.navigations)


def test_budget_exceeded_keeps_last_good_file(workdir):
    run(FakePage(LIST_OK))
    before = (workdir / "exports" / "kim-read.json").read_bytes()
    # Twelve uncached books inside the window (Nov 08 down to Oct 28), then one before the cutoff:
    # twelve genre pages against a budget of ten.
    days = [datetime(2026, 11, 8) - timedelta(days=i) for i in range(12)]
    many = {"rows": [gr_row(str(100 + i), d.strftime("%b %d, %Y")) for i, d in enumerate(days)]
            + [gr_row("99", "Oct 01, 2026")], "printed": "Read (1369)", "has_next": True}
    block = run(FakePage(many), now=NOW + timedelta(hours=21), force=True)
    assert block["last_status"] == "failed" and block["error"] == "navigation-budget"
    assert (workdir / "exports" / "kim-read.json").read_bytes() == before


def test_not_due_does_nothing(workdir):
    run(FakePage(LIST_OK))
    page = FakePage(LIST_OK)
    block = run(page, now=NOW + timedelta(hours=1))
    assert block == {"skipped": "fresh"} and page.navigations == []


def test_export_never_raises_into_sync(workdir):
    class Exploding(FakePage):
        def evaluate(self, script):
            raise RuntimeError("page crashed")
    block = run(Exploding(LIST_OK))
    assert block["last_status"] == "failed" and "RuntimeError" in block["error"]


def test_normalize_author():
    assert normalize_author("Rivera, Ana") == "Ana Rivera"
    assert normalize_author("Example, Jordan *") == "Jordan Example"
    assert normalize_author("Madonna") == "Madonna"


def test_parse_rating():
    assert parse_rating("really liked it", 4) == 4
    assert parse_rating("", 3) == 3
    assert parse_rating("", 0) is None
    assert parse_rating(None, None) is None
