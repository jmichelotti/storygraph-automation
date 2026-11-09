"""Pure parsing for the kim-read export: no Playwright, so it is testable on any host.

reading-cards round table (katana-fleet round-table/2026-11-07-reading-cards), D2 and A1. The
browser layer (goodreads/read_export.py) turns each list-view row into plain strings; this module
decides what they mean and whether a walk of the shelf is provably complete.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

# "(The Lantern Keepers, #2)" and "(Inspector Vale #20)", at the very end of the title.
_SERIES = re.compile(r"\s*\((?P<name>[^()]*?),?\s+#(?P<number>\d+(?:\.\d+)?)\)\s*$")
_FULL_DATE = re.compile(r"^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$")
_PARTIAL_DATE = re.compile(r"^(?:[A-Z][a-z]{2} )?\d{4}$")
_PAGES = re.compile(r"^(\d+)\s*pp$")


@dataclass(frozen=True)
class Row:
    """One read-shelf row as the browser saw it. Dates are Goodreads' own text."""
    gr_book_id: str
    review_id: str
    title_full: str
    author: str
    date_read: str | None
    date_started: str | None
    rating: float | None
    pages: int | None
    cover_url: str | None


def split_series(title_full: str) -> tuple[str, dict | None]:
    """Strip a trailing series tag: ("Quiet Harbor", {"name": "The Lantern Keepers", "number": "2"})."""
    m = _SERIES.search(title_full)
    if not m or not m.group("name").strip():
        return title_full.strip(), None
    return title_full[:m.start()].strip(), {"name": m.group("name").strip(), "number": m.group("number")}


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("[edit]", "")).strip()


def parse_gr_date(text: str | None) -> tuple[str | None, str]:
    """Goodreads date text -> (ISO date or None, kind). kind: ok | unset | partial | unparsed.

    A month-only or year-only date is a real Goodreads state (the reader set no day), so it is
    "partial", not a scraping failure: such a row has no read date for the card's purposes.
    """
    t = _clean(text)
    if not t or t.lower() == "not set":
        return None, "unset"
    m = _FULL_DATE.match(t)
    if m:
        try:
            return datetime.strptime(t, "%b %d, %Y").date().isoformat(), "ok"
        except ValueError:
            return None, "unparsed"
    if _PARTIAL_DATE.match(t):
        return None, "partial"
    return None, "unparsed"


def parse_pages(text: str | None) -> int | None:
    m = _PAGES.match(_clean(text))
    return int(m.group(1)) if m else None


def check_complete(pages: list[list[Row]], cutoff: date, printed_count: int | None,
                   has_next: bool) -> tuple[bool, str]:
    """Is this walk of the read shelf (newest first) provably complete back to `cutoff`?

    Rows without a full read date are skipped for ordering and for the cutoff. Any date text that
    is not a recognised Goodreads form means the page did not render as expected, so nothing is
    published.
    """
    last: str | None = None
    total = 0
    reached_cutoff = False
    for page in pages:
        for r in page:
            total += 1
            iso, kind = parse_gr_date(r.date_read)
            if kind == "unparsed":
                return False, "unparsed-date"
            if iso is None:
                continue
            if last is not None and iso > last:
                return False, "order"
            last = iso
            if date.fromisoformat(iso) < cutoff:
                reached_cutoff = True
    if reached_cutoff:
        return True, "ok-cutoff"
    if not has_next and printed_count is not None and total == printed_count:
        return True, "ok-exhausted"
    return False, "short"


def normalize_author(raw: str | None) -> str:
    """List view writes "Last, First" and marks Goodreads authors with a trailing "*"."""
    name = re.sub(r"\s*\*\s*$", "", (raw or "").strip())
    if name.count(",") == 1:
        last, first = (p.strip() for p in name.split(","))
        if last and first:
            return f"{first} {last}"
    return name


def parse_rating(data_rating: str | None) -> float | None:
    """The reader's own rating from the stars widget's data-rating ("4.0", "3.5"; probed 2026-11-07).

    Every star link carries a title ("did not like it" ... "it was amazing") whether or not it is
    filled, so the titles say nothing about the rating. No attribute (a pre-release edition) or 0
    means unrated.
    """
    try:
        value = float(str(data_rating).strip())
    except (TypeError, ValueError):
        return None
    if not 0.5 <= value <= 5.0:
        return None
    return round(value * 2) / 2



# ----------------------------------------------------------------------------
# Whole read shelf (goodreads-read-all/1, Vikunja task 187)
# ----------------------------------------------------------------------------

PER_PAGE = 100   # the list view's ceiling: per_page=200 still serves 100 rows (probed 2026-11-08)


@dataclass(frozen=True)
class ShelfRow:
    """One read-shelf row for the whole-shelf export. `dates` holds one text per reading session."""
    gr_book_id: str
    review_id: str
    title: str
    author: str
    author_id: str | None
    rating: float | None
    dates: tuple[str, ...]
    read_count: int | None


def newest_read(dates) -> tuple[str | None, bool]:
    """(newest full read date as ISO, every date recognised?). A re-read has one date per session."""
    best = None
    for text in dates:
        iso, kind = parse_gr_date(text)
        if kind == "unparsed":
            return None, False
        if iso and (best is None or iso > best):
            best = iso
    return best, True


def parse_count(text: str | None) -> int | None:
    m = re.search(r"\d+", _clean(text))
    return int(m.group(0)) if m else None


def check_whole_shelf(pages: list[list[ShelfRow]], printed: list[int | None],
                      last_has_next: bool) -> tuple[bool, str]:
    """Is this page-by-page walk provably the whole read shelf? (ok, reason)

    `printed` is the shelf count each page printed. Any page that shows a different count, a short
    page before the last, a duplicate review, or a row the list view did not fill in means the
    shelf moved or rendered differently mid-walk, so the walk is not trusted.
    """
    if not pages or not printed or any(p is None for p in printed):
        return False, "no-count"
    total = printed[0]
    if any(p != total for p in printed):
        return False, "count-changed"
    if last_has_next:
        return False, "more-pages"
    expected_pages = max(1, -(-total // PER_PAGE))
    if len(pages) != expected_pages:
        return False, "page-count"
    for i, page in enumerate(pages):
        want = PER_PAGE if i < expected_pages - 1 else total - PER_PAGE * (expected_pages - 1)
        if len(page) != want:
            return False, f"page-{i + 1}-rows"
    rows = [r for page in pages for r in page]
    if len({r.review_id for r in rows}) != total or len({r.gr_book_id for r in rows}) != total:
        return False, "duplicates"
    for r in rows:
        if not r.gr_book_id or not r.review_id or not r.author:
            return False, "blank-row"
        if not newest_read(r.dates)[1]:
            return False, "unparsed-date"
    return True, "ok"


def unparsed_dates(pages: list[list[ShelfRow]], limit: int = 10) -> list[str]:
    """Every distinct date text not in a recognised form, as "p<page>: <text>", for the log."""
    seen: list[str] = []
    for i, page in enumerate(pages):
        for r in page:
            for text in r.dates:
                if parse_gr_date(text)[1] == "unparsed":
                    entry = f"p{i + 1}: {_clean(text)[:60]!r}"
                    if entry not in seen and len(seen) < limit:
                        seen.append(entry)
    return seen
