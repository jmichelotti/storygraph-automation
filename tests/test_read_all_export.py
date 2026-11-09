"""The whole-read-shelf export for book-events' "top" authors (Vikunja task 187).

A fake page serves read-shelf list pages by page number, the way Goodreads does: 100 rows a page,
the shelf count printed on every page, and a.next_page on every page but the last.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from goodreads import read_all_export as rae
from goodreads import read_export
from goodreads.read_parse import ShelfRow, check_whole_shelf, newest_read

NOW = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)


def raw(i, dates=None, rating="4.0", author="Example, Jordan", read_count="1"):
    return {"review_id": f"review_{9000 + i}", "href": f"/book/show/{100 + i}-slug", "title": f"Book {i}",
            "author": author, "author_href": f"/author/show/{50 + i % 7}.Someone", "rating": rating,
            "dates": dates if dates is not None else ["Nov 06, 2026"], "read_count": read_count}


def shelf(total, overrides=None):
    rows = [raw(i, dates=["not set"] if i > total - 5 else None) for i in range(total)]
    for i, r in (overrides or {}).items():
        rows[i] = r
    return rows


class FakeShelf:
    """Serves LIST_URL page n from `rows`; `printed` may be a callable of the page number."""

    def __init__(self, rows, printed=None, extra_next=False):
        self.rows, self.printed, self.extra_next = rows, printed, extra_next
        self.navigations = []
        self.n = None

    def goto(self, url, **kw):
        self.navigations.append(url)
        self.n = int(url.rsplit("page=", 1)[1])

    def evaluate(self, script):
        assert script is rae._ROWS_JS
        start = (self.n - 1) * 100
        count = len(self.rows)
        shown = self.printed(self.n) if callable(self.printed) else (self.printed or count)
        return {"rows": self.rows[start:start + 100], "printed": f"Read ‎({shown:,})",
                "has_next": self.extra_next or start + 100 < count}


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "exports").mkdir()
    (tmp_path / "status").mkdir()
    import status
    monkeypatch.setattr(status, "STATUS_FILE", tmp_path / "status" / "status.json")
    monkeypatch.setattr(read_export, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(rae, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(read_export.time, "sleep", lambda s: None)
    return tmp_path


def run(page, now=NOW, force=False):
    return rae.export_read_all("kim", page, now=now, force=force, log=lambda m: None)


def published(workdir):
    return json.loads((workdir / "exports" / "kim-read-all.json").read_text(encoding="utf-8"))


def test_whole_shelf_publishes_atomically_0600(workdir):
    page = FakeShelf(shelf(1369))
    block = run(page)
    assert block["last_status"] == "success" and block["count"] == 1369 and block["navigations"] == 14
    assert len(page.navigations) == 14 and "per_page=100" in page.navigations[0]
    files = sorted(p.name for p in (workdir / "exports").iterdir())
    assert files == ["kim-read-all.json"]
    if os.name == "posix":
        assert (workdir / "exports" / "kim-read-all.json").stat().st_mode & 0o777 == 0o600
    doc = published(workdir)
    assert doc["schema"] == "goodreads-read-all/1" and doc["complete"] is True
    assert doc["count"] == doc["printed_count"] == len(doc["books"]) == 1369
    assert doc["scraped_at"] == NOW.isoformat()


def test_book_fields(workdir):
    rows = shelf(150, {0: raw(0, dates=["Jan 02, 2019", "Nov 03, 2026"], rating="3.5",
                              author="Berry, Lucinda", read_count="2"),
                       1: raw(1, dates=["Oct 2026"], rating="0.0"),
                       2: raw(2, dates=[""], rating=None)})
    run(FakeShelf(rows))
    books = published(workdir)["books"]
    b = books[0]
    assert b == {"gr_book_id": "100", "review_id": "9000", "title": "Book 0", "author": "Lucinda Berry",
                 "author_id": "50", "rating": 3.5, "date_read": "2026-11-03", "read_count": 2, "shelf": "read"}
    assert books[1]["rating"] is None and books[1]["date_read"] is None   # unrated, month-only date
    assert books[2]["rating"] is None and books[2]["date_read"] is None


@pytest.mark.parametrize("case,page,error", [
    ("count moved mid-walk", lambda: FakeShelf(shelf(250), printed=lambda n: 250 if n == 1 else 251),
     "count-changed"),
    ("shelf longer than printed", lambda: FakeShelf(shelf(250), extra_next=True), "more-pages"),
    ("a row shifted to the next page", lambda: FakeShelf(shelf(250, {150: raw(149)})), "duplicates"),
    ("short middle page", lambda: FakeShelf(shelf(250)[:120] + shelf(250)[121:], printed=250), "page-3-rows"),
    ("unrecognised date", lambda: FakeShelf(shelf(250, {7: raw(7, dates=["sometime"])})), "unparsed-date"),
    ("blank author", lambda: FakeShelf(shelf(250, {9: raw(9, author="")})), "blank-row"),
])
def test_doubt_keeps_last_good_file(workdir, case, page, error):
    run(FakeShelf(shelf(250)))
    before = (workdir / "exports" / "kim-read-all.json").read_bytes()
    block = run(page(), now=NOW + timedelta(days=1), force=True)
    assert block["last_status"] == "failed" and block["error"] == error, case
    assert block["last_success"] == NOW.isoformat()
    assert (workdir / "exports" / "kim-read-all.json").read_bytes() == before


def test_no_printed_count_fails(workdir):
    page = FakeShelf(shelf(50))
    page.evaluate = lambda s: {"rows": shelf(50), "printed": "", "has_next": False}
    assert run(page)["error"] == "no-count"
    assert not (workdir / "exports" / "kim-read-all.json").exists()


def test_huge_shelf_hits_the_navigation_cap(workdir):
    page = FakeShelf(shelf(3000))
    block = run(page)
    assert block["error"] == "navigation-budget" and len(page.navigations) == rae.MAX_NAV
    assert not (workdir / "exports" / "kim-read-all.json").exists()


def test_navigation_error_is_recorded_not_raised(workdir):
    class Broken(FakeShelf):
        def goto(self, url, **kw):
            raise RuntimeError("net::ERR_ABORTED at https://www.goodreads.com/review/list")
    block = run(Broken(shelf(10)))
    assert block["last_status"] == "failed" and "ERR_ABORTED" in block["error"]


def test_pages_are_spaced(workdir, monkeypatch):
    waits = []
    monkeypatch.setattr(read_export.time, "sleep", waits.append)
    run(FakeShelf(shelf(300)))
    assert len(waits) == 2 and all(w > 5 for w in waits)


def test_monthly_schedule_and_cooldown(workdir):
    run(FakeShelf(shelf(10)))
    page = FakeShelf(shelf(10))
    assert run(page, now=NOW + timedelta(days=27)) == {"skipped": "fresh"} and page.navigations == []
    assert run(page, now=NOW + timedelta(days=29))["last_status"] == "success"
    failing = FakeShelf(shelf(10), extra_next=True)
    t = NOW + timedelta(days=60)
    assert run(failing, now=t)["last_status"] == "failed"
    assert run(page, now=t + timedelta(hours=2)) == {"skipped": "cooldown"}
    assert run(page, now=t + timedelta(hours=4))["last_status"] == "success"


def test_force_runs_when_fresh(workdir):
    run(FakeShelf(shelf(10)))
    assert run(FakeShelf(shelf(10)), now=NOW + timedelta(hours=1), force=True)["last_status"] == "success"


def test_without_exports_dir_it_skips(workdir, monkeypatch):
    monkeypatch.setattr(rae, "EXPORT_DIR", workdir / "missing")
    page = FakeShelf(shelf(10))
    assert run(page) == {"skipped": "no exports/ directory mounted"} and page.navigations == []


def test_status_block_survives_a_sync_status_write(workdir):
    import status
    run(FakeShelf(shelf(10)))
    status.write_status("kim", {"status": "success"})
    assert status.read_export_block("kim", "read_all_export")["count"] == 10


def test_empty_shelf_is_complete():
    assert check_whole_shelf([[]], [0], False) == (True, "ok")


def test_newest_read_takes_latest_session():
    assert newest_read(["Mar 05, 2015", "Jan 01, 2020 [edit]"]) == ("2020-01-01", True)
    assert newest_read(["not set"]) == (None, True)
    assert newest_read(["Jan 01, 2020", "garbled"]) == (None, False)


def test_rows_are_shelfrows():
    r = rae._to_row(raw(3))
    assert isinstance(r, ShelfRow) and r.gr_book_id == "103" and r.review_id == "9003"


def test_unparsed_dates_are_reported(workdir):
    block = run(FakeShelf(shelf(250, {107: raw(107, dates=["sometime"])})))
    assert block["error"] == "unparsed-date" and block["unparsed_dates"] == ["p2: 'sometime'"]


def test_a_timed_out_page_is_retried_once(workdir):
    class Flaky(FakeShelf):
        failed = False

        def goto(self, url, **kw):
            if url.endswith("page=3") and not self.failed:
                self.failed = True
                self.navigations.append(url)
                raise TimeoutError("Page.goto: Timeout 60000ms exceeded.")
            super().goto(url, **kw)
    page = Flaky(shelf(250))
    block = run(page)
    assert block["last_status"] == "success" and len(page.navigations) == 4


def test_a_page_that_keeps_failing_fails_the_export(workdir):
    class Dead(FakeShelf):
        def goto(self, url, **kw):
            if url.endswith("page=2"):
                raise TimeoutError("Page.goto: Timeout 60000ms exceeded.")
            super().goto(url, **kw)
    block = run(Dead(shelf(250)))
    assert block["last_status"] == "failed" and "Timeout" in block["error"]


def test_an_attempt_does_not_inherit_the_last_attempts_details(workdir):
    run(FakeShelf(shelf(250, {107: raw(107, dates=["sometime"])})))
    block = run(FakeShelf(shelf(250), extra_next=True), now=NOW + timedelta(hours=4))
    assert block["error"] == "more-pages" and "unparsed_dates" not in block
    assert run(FakeShelf(shelf(250)), now=NOW + timedelta(hours=8))["error"] is None


def test_repeated_failures_back_off_to_a_day(workdir):
    t = NOW
    for _ in range(3):
        assert run(FakeShelf(shelf(10), extra_next=True), now=t)["last_status"] == "failed"
        t += timedelta(hours=4)
    page = FakeShelf(shelf(10))
    assert run(page, now=t) == {"skipped": "cooldown"}
    block = run(page, now=t + timedelta(hours=21))
    assert block["last_status"] == "success" and block["consecutive_failures"] == 0
