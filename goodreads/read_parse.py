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
    rating: int | None
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


# Goodreads' own words for each star count, as its rating widgets title them.
_RATING_WORDS = {"did not like it": 1, "it was ok": 2, "liked it": 3, "really liked it": 4, "it was amazing": 5}


def normalize_author(raw: str | None) -> str:
    """List view writes "Last, First" and marks Goodreads authors with a trailing "*"."""
    name = re.sub(r"\s*\*\s*$", "", (raw or "").strip())
    if name.count(",") == 1:
        last, first = (p.strip() for p in name.split(","))
        if last and first:
            return f"{first} {last}"
    return name


def parse_rating(title_text: str | None, filled: int | None) -> int | None:
    """The reader's own star rating from the rating cell: its title words, else its filled stars."""
    words = (title_text or "").strip().lower()
    if words in _RATING_WORDS:
        return _RATING_WORDS[words]
    if isinstance(filled, int) and 1 <= filled <= 5:
        return filled
    return None
