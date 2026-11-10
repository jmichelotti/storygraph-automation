"""The StoryGraph read-shelf export (Vikunja Dev task 180): parsing, completeness, publishing.

Every book here is invented. The page is never driven: the pure parts are tested directly.
"""
import json
import os
from datetime import datetime, UTC

import pytest

from storygraph import read_shelf_export as rse


def raw(book_id="b1", **over):
    base = {"id": book_id, "title": f"Invented Book {book_id}", "authors": ["Jordan Example"],
            "series": ["The Glass Orchard", "#2"], "edition": "412 pages • hardcover • 2021",
            "genres": ["Fiction", "Science Fiction"], "moods": ["adventurous", "medium-paced"],
            "rating": "4.25", "finished": ["Finished Nov 7, 2026"],
            "cover": "https://cdn.thestorygraph.com/example.jpg"}
    base.update(over)
    return base


def test_normalize_reads_every_field():
    b = rse.normalize(raw())
    assert b == {"sg_book_id": "b1", "title": "Invented Book b1", "authors": ["Jordan Example"],
                 "series": "The Glass Orchard", "series_number": "2", "pages": 412,
                 "format": "hardcover", "rating": 4.25, "date_finished": "2026-11-07",
                 "genres": ["fiction", "science fiction"], "moods": ["adventurous", "medium-paced"],
                 "cover_url": "https://cdn.thestorygraph.com/example.jpg"}


@pytest.mark.parametrize("texts,expected", [
    (["Finished Jan 3, 2026"], "2026-01-03"),
    (["Finished Sep 30, 2025", "Finished Feb 1, 2026"], "2026-02-01"),   # latest wins
    (["Finished Sept 9, 2026"], "2026-09-09"),
    (["Finished Nov 2026"], None),                                       # month only: undated
    ([], None), (None, None),
])
def test_parse_finished(texts, expected):
    assert rse.parse_finished(texts) == expected


@pytest.mark.parametrize("text,expected", [
    ("1,024 pages • paperback • 2019", (1024, "paperback")),
    ("audio • 2020", (None, "audio")),
    (None, (None, None)),
])
def test_parse_edition(text, expected):
    assert rse.parse_edition(text) == expected


@pytest.mark.parametrize("text,expected", [("3.75", 3.75), ("5.0", 5.0), ("0", None), ("", None),
                                           ("see review", None), (None, None), ("7", None)])
def test_parse_rating(text, expected):
    assert rse.parse_rating(text) == expected


def test_parse_series_without_number():
    assert rse.parse_series(["Standalone Saga"]) == ("Standalone Saga", None)
    assert rse.parse_series([]) == (None, None)


def seen(books, displayed=None, end_seen=True, title="handle - Read Books | The StoryGraph"):
    return {"page_title": title, "displayed": len(books) if displayed is None else displayed,
            "end_seen": end_seen, "scrolls": 3, "stalled": False, "books": books}


def test_validate_accepts_a_complete_shelf():
    assert rse.validate("handle", seen([rse.normalize(raw("a")), rse.normalize(raw("b"))])) is None


@pytest.mark.parametrize("s,needle", [
    (seen([], title="Sign in | The StoryGraph"), "not a read shelf"),
    (seen([{"title": "x"}], displayed=2), "page says 2"),
    (seen([{"title": "x"}], end_seen=False), "never reached the end"),
    (seen([{"title": None}]), "no title"),
])
def test_validate_refuses_incomplete(s, needle):
    s = dict(s)
    if s["page_title"].startswith("Sign in"):
        s["displayed"] = None
    assert needle in rse.validate("handle", s)


def test_validate_needs_a_count():
    assert "no book count" in rse.validate("handle", seen([], displayed=None) | {"displayed": None})


def test_publish_is_private_and_atomic(tmp_path, monkeypatch):
    monkeypatch.setattr(rse, "EXPORT_DIR", tmp_path)
    books = [rse.normalize(raw("a"))]
    path = rse.publish("someone", "handle", seen(books), datetime(2026, 11, 9, tzinfo=UTC))
    assert path == tmp_path / "someone-read.json"
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert not (tmp_path / "someone-read.json.new").exists()
    doc = json.loads(path.read_text())
    assert doc["schema"] == "storygraph-read/1" and doc["complete"] is True and doc["count"] == 1
    assert doc["books"][0]["date_finished"] == "2026-11-07"


def test_missing_session_fails_without_a_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(rse, "EXPORT_DIR", tmp_path)
    monkeypatch.setattr(rse, "STATE_DIR", tmp_path / "nostate")
    result = rse.export_read_shelf("someone", log=lambda *_: None)
    assert result["status"] == "failed" and "no saved StoryGraph session" in result["error"]
    assert list(tmp_path.iterdir()) == []
