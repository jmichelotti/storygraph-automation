"""Kim's finished books for reading-cards: exports/<profile>-read.json.

Designed in katana-fleet's round table `round-table/2026-11-07-reading-cards/` (D2, A1, A2, A10).
reading-cards draws a weekly card of what Kim finished; it reads only the file this writes.

It runs inside the hourly Goodreads sync's own browser, right after the sync has loaded the read
shelf (newest first), so the list itself normally costs no extra page load. Only books it has not
seen before cost one book-page visit each, for their genres, which are cached for good. It is
read-only on Goodreads, never touches StoryGraph, and never raises into the sync.

Published only when provably complete back to the cutoff (21 days before this week's Monday
00:00 America/New_York): see read_parse.check_complete. Anything else keeps the last good file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from goodreads.read_parse import (Row, check_complete, normalize_author, parse_gr_date, parse_pages,
                                  parse_rating, split_series)
from goodreads.read_schedule import monday_anchor, next_block, read_export_due
from status import read_export_block, write_export_block

EXPORT_DIR = Path("exports")
SCHEMA = "goodreads-read/1"
STATUS_KEY = "read_export"
WINDOW = timedelta(days=21)
MAX_NAV = 10
MIN_GAP_S = 3.0
MAX_LIST_PAGES = 3
MAX_GENRES = 5
LIST_URL = "https://www.goodreads.com/review/list?shelf=read&sort=date_read&order=d&per_page=100&page={n}"
BOOK_URL = "https://www.goodreads.com/book/show/{id}"

# One object per list-view row; the cells were confirmed on Kim's shelf on 2026-11-07.
_ROWS_JS = """() => {
  const txt = (el) => el ? el.innerText.replace(/\\s+/g, ' ').trim() : '';
  const rows = [...document.querySelectorAll('tr.bookalike.review')].map((tr) => {
    const a = tr.querySelector('td.field.title a');
    const stars = tr.querySelector('td.field.rating .staticStars, td.field.rating [title]');
    const img = tr.querySelector('td.field.cover img');
    return {
      review_id: tr.id || '', href: a ? a.getAttribute('href') : '', title: a ? txt(a) : '',
      author: txt(tr.querySelector('td.field.author a')),
      date_read: txt(tr.querySelector('td.field.date_read .value')),
      date_started: txt(tr.querySelector('td.field.date_started .value')),
      pages: txt(tr.querySelector('td.field.num_pages .value')),
      rating_title: stars ? (stars.getAttribute('title') || '') : '',
      rating_filled: tr.querySelectorAll('td.field.rating .staticStar.p10').length,
      cover: img ? img.getAttribute('src') : '',
    };
  });
  const shelf = document.querySelector('.selectedShelf');
  return {rows, printed: shelf ? shelf.innerText : '', has_next: !!document.querySelector('a.next_page')};
}"""

# Genre names from a book page: every link into /genres/, in page order. Both Goodreads page
# designs link genres that way, so this does not depend on one layout's class names.
_GENRES_JS = """() => [...document.querySelectorAll('a[href*="/genres/"]')]
  .map((a) => a.innerText.replace(/\\s+/g, ' ').trim()).filter((t) => t)"""


class BudgetExceeded(Exception):
    pass


@dataclass
class Budget:
    """Every Goodreads navigation this export makes goes through here (A10)."""
    max_nav: int = MAX_NAV
    min_gap_s: float = MIN_GAP_S
    used: int = 0
    _last: float | None = None

    def goto(self, page, url: str) -> None:
        if self.used >= self.max_nav:
            raise BudgetExceeded(url)
        if self._last is not None:
            wait = self.min_gap_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
        self.used += 1
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        self._last = time.monotonic()


@dataclass
class Collection:
    rows: list[Row]
    complete: bool
    reason: str
    exhausted: bool
    navigations: int
    genres: dict[str, list[str]] = field(default_factory=dict)


def export_path(profile: str) -> Path:
    return EXPORT_DIR / f"{profile}-read.json"


def _genre_cache_path() -> Path:
    return EXPORT_DIR / ".genre-cache.json"


def _write_private(path: Path, payload) -> None:
    tmp = path.with_name(path.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    if getattr(os, "geteuid", lambda: 1)() == 0:   # the container is root; book-events reads as talon
        owner = EXPORT_DIR.stat()
        os.chown(tmp, owner.st_uid, owner.st_gid)
    os.replace(tmp, path)


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _to_row(raw: dict) -> Row | None:
    href = raw.get("href") or ""
    m = re.search(r"/book/show/(\d+)", href)
    if not m:
        return None
    return Row(gr_book_id=m.group(1), review_id=(raw.get("review_id") or "").replace("review_", ""),
               title_full=raw.get("title") or "", author=normalize_author(raw.get("author")),
               date_read=raw.get("date_read"), date_started=raw.get("date_started"),
               rating=parse_rating(raw.get("rating_title"), raw.get("rating_filled")),
               pages=parse_pages(raw.get("pages")), cover_url=raw.get("cover") or None)


def _read_list(page) -> tuple[list[Row], int | None, bool]:
    data = page.evaluate(_ROWS_JS)
    rows = [r for r in (_to_row(x) for x in data.get("rows") or []) if r is not None]
    m = re.search(r"\((\d[\d,]*)\)", data.get("printed") or "")
    printed = int(m.group(1).replace(",", "")) if m else None
    return rows, printed, bool(data.get("has_next"))


def _in_window(rows: list[Row], cutoff) -> list[Row]:
    out = []
    for r in rows:
        iso, _ = parse_gr_date(r.date_read)
        if iso and iso >= cutoff.isoformat():
            out.append(r)
    return out


def collect_read(page, cutoff, budget: Budget, genre_cache: dict) -> Collection:
    """Walk the read shelf back to `cutoff`, then fetch genres for books not yet cached.

    Starts from the page the sync already has open. Only if that page cannot prove coverage does it
    walk the 100-per-page list from the start. Genres fetched before a budget overrun stay in
    `genre_cache`, so the next attempt needs fewer page loads.
    """
    rows, printed, has_next = _read_list(page)
    ok, reason = check_complete([rows], cutoff, printed, has_next)
    if not ok and reason == "short":
        walked: list[list[Row]] = []
        for n in range(1, MAX_LIST_PAGES + 1):
            budget.goto(page, LIST_URL.format(n=n))
            rows_n, printed, has_next = _read_list(page)
            walked.append(rows_n)
            ok, reason = check_complete(walked, cutoff, printed, has_next)
            if ok or reason != "short" or not has_next:
                break
        rows = [r for p in walked for r in p]
    if not ok:
        return Collection(rows=rows, complete=False, reason=reason, exhausted=False, navigations=budget.used)
    window = _in_window(rows, cutoff)
    for r in window:
        if r.gr_book_id in genre_cache:
            continue
        budget.goto(page, BOOK_URL.format(id=r.gr_book_id))
        names: list[str] = []
        for g in page.evaluate(_GENRES_JS) or []:
            g = g.strip().lower()
            if g and g not in names:
                names.append(g)
        genre_cache[r.gr_book_id] = names[:MAX_GENRES]
    return Collection(rows=window, complete=True, reason=reason, exhausted=(reason == "ok-exhausted"),
                      navigations=budget.used,
                      genres={r.gr_book_id: genre_cache.get(r.gr_book_id, []) for r in window})


def publish_read(profile: str, col: Collection, cutoff, now: datetime) -> Path:
    books = []
    for r in col.rows:
        title, series = split_series(r.title_full)
        books.append({
            "gr_book_id": r.gr_book_id, "review_id": r.review_id, "title": title,
            "title_full": r.title_full, "author": r.author, "series": series, "rating": r.rating,
            "pages": r.pages, "date_started": parse_gr_date(r.date_started)[0],
            "date_read": parse_gr_date(r.date_read)[0], "cover_url": r.cover_url,
            "genres": col.genres.get(r.gr_book_id, []),
        })
    payload = {
        "schema": SCHEMA, "profile": profile, "scraped_at": now.isoformat(), "complete": True,
        "coverage_from": cutoff.isoformat(), "exhausted": col.exhausted,
        "oldest_date_read": min((b["date_read"] for b in books), default=None),
        "navigations": col.navigations, "books": books,
    }
    path = export_path(profile)
    _write_private(path, payload)
    return path


def export_read(profile: str, page, now: datetime | None = None, force: bool = False, log=print) -> dict:
    """Run one export if due, using the sync's open `page`. Never raises; returns the status block."""
    try:
        if not EXPORT_DIR.is_dir():
            return {"skipped": "no exports/ directory mounted"}
        now = now or datetime.now(UTC)
        block = read_export_block(profile, STATUS_KEY)
        if not force:
            due, why = read_export_due(block, now)
            if not due:
                return {"skipped": why}
    except Exception as exc:  # noqa: BLE001
        log(f"READ EXPORT — could not check schedule: {type(exc).__name__}: {exc}")
        return {"skipped": "status-unreadable"}
    start = time.time()
    cutoff = (monday_anchor(now) - WINDOW).date()
    budget = Budget()
    cache = _load_json(_genre_cache_path())
    detail: dict = {}
    ok = False
    try:
        col = collect_read(page, cutoff, budget, cache)
        if col.complete:
            path = publish_read(profile, col, cutoff, now)
            ok = True
            detail = {"count": len(col.rows), "error": None}
            log(f"READ EXPORT — published {len(col.rows)} books to {path} ({col.navigations} page loads)")
        else:
            detail = {"error": col.reason}
            log(f"READ EXPORT — not published, last good file kept: {col.reason}")
    except BudgetExceeded:
        detail = {"error": "navigation-budget"}
        log(f"READ EXPORT — over {MAX_NAV} page loads; last good file kept (genres so far are cached)")
    except Exception as exc:  # noqa: BLE001 — the export must never fail the sync
        detail = {"error": f"{type(exc).__name__}: {exc}".splitlines()[0][:300]}
        log(f"READ EXPORT — failed, last good file kept: {detail['error']}")
    try:
        if cache:
            _write_private(_genre_cache_path(), cache)
    except OSError as exc:
        log(f"READ EXPORT — genre cache not saved: {exc}")
    detail.update(navigations=budget.used, duration_seconds=round(time.time() - start, 1))
    new = next_block(block, now, ok=ok, detail=detail)
    try:
        write_export_block(profile, STATUS_KEY, new)
    except OSError as exc:
        log(f"READ EXPORT — status not written: {exc}")
    return new


def main() -> None:
    p = argparse.ArgumentParser(description="Export Kim's finished books to exports/<profile>-read.json")
    p.add_argument("--profile", required=True)
    p.add_argument("--force", action="store_true", help="run even if not due")
    args = p.parse_args()
    # Imported here so this module's logic tests without a browser stack.
    from playwright.sync_api import sync_playwright
    from goodreads.auth import ensure_logged_in, get_browser
    from goodreads.library import fetch_read_books
    with sync_playwright() as pw:
        browser, context = get_browser(pw, profile=args.profile, headless=False)
        try:
            page = context.new_page()
            ensure_logged_in(page, context, profile=args.profile)
            fetch_read_books(page)   # leaves the read shelf open, as the sync does
            print(json.dumps(export_read(args.profile, page, force=args.force), indent=1))
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
