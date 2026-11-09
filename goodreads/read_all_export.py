"""Kim's whole Goodreads read shelf for book-events: exports/<profile>-read-all.json.

Vikunja task 187 (2026-11-08). Goodreads closed per-shelf RSS around 2026-11-02, so book-events'
ranked "top" authors (her most-finished authors, which aim its search tier) could no longer
refresh. book-events' import-watchlist.py reads this file (--goodreads-read-all) and rebuilds "top".

Operator rulings, 2026-11-08: walk the list view (read-only; not the Export Library button, which
is an action on her account, and not StoryGraph, whose ratings this repo never writes); monthly,
or by hand with --force.

It runs inside the hourly sync's own signed-in Goodreads browser, after the sync's own Goodreads
work, on --apply runs only. The list view serves at most 100 rows a page (per_page=200 still
serves 100; probed 2026-11-08), so 1,369 books is 14 pages of about 870 KB each. Every navigation
goes through read_export.Budget: at most ceil(count / 100) + 2, never more than MAX_NAV, at least
MIN_GAP_S apart. Published only if read_parse.check_whole_shelf proves the walk is the whole shelf;
anything else keeps the last good file. Read-only on Goodreads, never touches StoryGraph, and
never raises into the sync.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from goodreads.read_export import EXPORT_DIR, Budget, BudgetExceeded, _write_private
from goodreads.read_parse import (PER_PAGE, ShelfRow, check_whole_shelf, newest_read, unparsed_dates, normalize_author,
                                  parse_count, parse_rating)
from status import read_export_block, write_export_block

SCHEMA = "goodreads-read-all/1"
STATUS_KEY = "read_all_export"
INTERVAL = timedelta(days=28)
COOLDOWN = timedelta(hours=3)
LONG_COOLDOWN = timedelta(hours=24)   # after LONG_AFTER failures in a row: a broken page waits a day
LONG_AFTER = 3
RETRY_WAIT_S = 20.0                   # one retry per page, inside the same budget
MIN_GAP_S = 6.0
MAX_NAV = 25            # 2,400 books plus slack; a bigger shelf fails loudly rather than walk on
LIST_URL = ("https://www.goodreads.com/review/list?shelf=read&sort=date_read&order=d"
            f"&per_page={PER_PAGE}&page={{n}}")

# One object per row. Each reading session is a div.date_row holding a span.date_read_value
# (probed 2026-11-08), so a re-read carries several; the author link's text is the name alone,
# the Goodreads-author "*" being a separate span.
_ROWS_JS = """() => {
  const txt = (el) => el ? el.innerText.replace(/\\s+/g, ' ').trim() : '';
  const rows = [...document.querySelectorAll('tr.bookalike.review')].map((tr) => {
    const a = tr.querySelector('td.field.title a');
    const au = tr.querySelector('td.field.author a');
    const stars = tr.querySelector('td.field.rating div.stars');
    const cell = tr.querySelector('td.field.date_read .value');
    // One text per session: its date span, or the row's own text ("not set") when it has none.
    // A re-read with no dates is two date_rows and no span (page 12, 2026-11-08): reading the
    // whole cell then gave "not set not set".
    const sessions = [...tr.querySelectorAll('td.field.date_read .date_row')];
    let dates = sessions.map((row) => txt(row.querySelector('.date_read_value') || row));
    if (!dates.length) dates = [txt(cell)];
    return {
      review_id: tr.id || '', href: a ? a.getAttribute('href') : '', title: a ? txt(a) : '',
      author: txt(au), author_href: au ? au.getAttribute('href') : '',
      rating: stars ? stars.getAttribute('data-rating') : null, dates,
      read_count: txt(tr.querySelector('td.field.read_count .value')),
    };
  });
  const shelf = document.querySelector('.selectedShelf');
  return {rows, printed: shelf ? shelf.innerText : '', has_next: !!document.querySelector('a.next_page')};
}"""


@dataclass
class Walk:
    pages: list[list[ShelfRow]]
    printed: list[int | None]
    has_next: bool
    navigations: int


def export_path(profile: str):
    return EXPORT_DIR / f"{profile}-read-all.json"


def _ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def read_all_due(block: dict, now: datetime) -> tuple[bool, str]:
    """(due, reason): reason is cooldown | fresh | monthly."""
    last_attempt = _ts(block.get("last_attempt"))
    try:
        failures = int(block.get("consecutive_failures") or 0)
    except (TypeError, ValueError):
        failures = 0
    cooldown = LONG_COOLDOWN if failures >= LONG_AFTER else COOLDOWN
    if block.get("last_status") == "failed" and last_attempt and now - last_attempt < cooldown:
        return False, "cooldown"
    last_success = _ts(block.get("last_success"))
    if last_success and now - last_success < INTERVAL:
        return False, "fresh"
    return True, "monthly"


def _to_row(raw: dict) -> ShelfRow:
    m = re.search(r"/book/show/(\d+)", raw.get("href") or "")
    a = re.search(r"/author/show/(\d+)", raw.get("author_href") or "")
    return ShelfRow(gr_book_id=m.group(1) if m else "",
                    review_id=(raw.get("review_id") or "").replace("review_", ""),
                    title=raw.get("title") or "", author=normalize_author(raw.get("author")),
                    author_id=a.group(1) if a else None, rating=parse_rating(raw.get("rating")),
                    dates=tuple(d for d in (raw.get("dates") or []) if isinstance(d, str)),
                    read_count=parse_count(raw.get("read_count")))


def _read_page(page) -> tuple[list[ShelfRow], int | None, bool]:
    data = page.evaluate(_ROWS_JS)
    m = re.search(r"\((\d[\d,]*)\)", data.get("printed") or "")
    printed = int(m.group(1).replace(",", "")) if m else None
    return [_to_row(x) for x in data.get("rows") or []], printed, bool(data.get("has_next"))


def _goto(page, budget: Budget, url: str) -> None:
    """One retry after RETRY_WAIT_S: a slow Goodreads page timed out on 2026-11-08 (page 14 of 14)."""
    try:
        budget.goto(page, url)
    except BudgetExceeded:
        raise
    except Exception:  # noqa: BLE001 — Playwright's timeout or an aborted navigation
        time.sleep(RETRY_WAIT_S)
        budget.goto(page, url)


def walk_shelf(page, budget: Budget) -> Walk:
    """Page 1 says how many books there are; then exactly that many pages, and no more."""
    _goto(page, budget, LIST_URL.format(n=1))
    rows, printed, has_next = _read_page(page)
    walk = Walk(pages=[rows], printed=[printed], has_next=has_next, navigations=budget.used)
    if printed is None:
        return walk
    pages = max(1, -(-printed // PER_PAGE))
    budget.max_nav = min(MAX_NAV, pages + 2)
    for n in range(2, pages + 1):
        _goto(page, budget, LIST_URL.format(n=n))   # raises BudgetExceeded past the cap
        rows, printed, has_next = _read_page(page)
        walk.pages.append(rows)
        walk.printed.append(printed)
        walk.has_next = has_next
    walk.navigations = budget.used
    return walk


def build_payload(profile: str, walk: Walk, now: datetime) -> dict:
    books = []
    for r in (r for p in walk.pages for r in p):
        books.append({"gr_book_id": r.gr_book_id, "review_id": r.review_id, "title": r.title,
                      "author": r.author, "author_id": r.author_id, "rating": r.rating,
                      "date_read": newest_read(r.dates)[0], "read_count": r.read_count, "shelf": "read"})
    return {"schema": SCHEMA, "profile": profile, "scraped_at": now.isoformat(), "complete": True,
            "shelf": "read", "printed_count": walk.printed[0], "count": len(books),
            "navigations": walk.navigations, "books": books}


def export_read_all(profile: str, page, now: datetime | None = None, force: bool = False, log=print) -> dict:
    """Run one whole-shelf export if due, in the sync's browser `page`. Never raises; returns the block."""
    try:
        if not EXPORT_DIR.is_dir():
            return {"skipped": "no exports/ directory mounted"}
        now = now or datetime.now(UTC)
        block = read_export_block(profile, STATUS_KEY)
        if not force:
            due, why = read_all_due(block, now)
            if not due:
                return {"skipped": why}
    except Exception as exc:  # noqa: BLE001
        log(f"READ-ALL EXPORT — could not check schedule: {type(exc).__name__}: {exc}")
        return {"skipped": "status-unreadable"}
    log("READ-ALL EXPORT — start")
    start = time.time()
    budget = Budget(max_nav=MAX_NAV, min_gap_s=MIN_GAP_S)
    ok = False
    detail: dict = {}
    try:
        walk = walk_shelf(page, budget)
        complete, reason = check_whole_shelf(walk.pages, walk.printed, walk.has_next)
        if complete:
            payload = build_payload(profile, walk, now)
            path = export_path(profile)
            _write_private(path, payload)
            ok = True
            detail = {"count": payload["count"], "printed_count": payload["printed_count"], "error": None}
            log(f"READ-ALL EXPORT — published {payload['count']} books to {path} ({budget.used} page loads)")
        else:
            detail = {"error": reason, "printed_count": walk.printed[0]}
            if reason == "unparsed-date":
                detail["unparsed_dates"] = unparsed_dates(walk.pages)
            log(f"READ-ALL EXPORT — not published, last good file kept: {reason}"
                + (f" {detail['unparsed_dates']}" if detail.get("unparsed_dates") else ""))
    except BudgetExceeded:
        detail = {"error": "navigation-budget"}
        log(f"READ-ALL EXPORT — over {budget.max_nav} page loads; last good file kept")
    except Exception as exc:  # noqa: BLE001 — the export must never fail the sync
        detail = {"error": f"{type(exc).__name__}: {exc}".splitlines()[0][:300]}
        log(f"READ-ALL EXPORT — failed, last good file kept: {detail['error']}")
    # Only the last good run's facts carry over; everything else describes this attempt.
    kept = {k: block[k] for k in ("last_success", "count") if k in block}
    failures = 0 if ok else int(block.get("consecutive_failures") or 0) + 1
    new = {**kept, **detail, "consecutive_failures": failures, "navigations": budget.used,
           "duration_seconds": round(time.time() - start, 1), "last_attempt": now.isoformat(),
           "last_status": "success" if ok else "failed"}
    if ok:
        new["last_success"] = now.isoformat()
    try:
        write_export_block(profile, STATUS_KEY, new)
    except OSError as exc:
        log(f"READ-ALL EXPORT — status not written: {exc}")
    return new


def main() -> None:
    p = argparse.ArgumentParser(description="Export Kim's whole read shelf to exports/<profile>-read-all.json")
    p.add_argument("--profile", required=True)
    p.add_argument("--force", action="store_true", help="run even if not due")
    args = p.parse_args()
    # Imported here so this module's logic tests without a browser stack.
    from playwright.sync_api import sync_playwright
    from goodreads.auth import ensure_logged_in, get_browser
    with sync_playwright() as pw:
        browser, context = get_browser(pw, profile=args.profile, headless=False)
        try:
            page = context.new_page()
            ensure_logged_in(page, context, profile=args.profile)
            print(json.dumps(export_read_all(args.profile, page, force=args.force), indent=1))
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
