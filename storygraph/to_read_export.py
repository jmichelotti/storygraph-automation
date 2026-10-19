"""
Export a reader's StoryGraph To-Read Pile to a file another tool can read.

book-events (~/dev/book-events) searches for authors newly added to Kim's To-Read Pile. She adds
them on StoryGraph, which has no API and no feed, and this repo is the only one holding her
StoryGraph session, so the export lives here and book-events reads only the file it writes.
Ruled 2026-10-19 in book-events' round table `round-table/2026-10-19-book-fairs-and-to-read/`.

The contract (codex-a/O7 there):
- Read-only on StoryGraph: it opens the To-Read Pile and scrolls; it never clicks anything.
- Writes `exports/<profile>-to-read.json` and nothing else. The file holds no credentials, no
  email and no session, is mode 0600 and owned by whoever owns `exports/` (the container runs as
  root; book-events reads it as talon). Written to `.new`, then renamed.
- Publishes only a provably complete list: the "More..." link (`#next_link`) has become an empty
  span, and the number of unique books equals the count the page prints ("803 books"). Anything
  else keeps the last good file. An empty list is published only when the page says "0 books".
- At most once per 20 hours, and a failed attempt waits 3 hours before the next.
- Never raises into the sync: every outcome lands in status.json under the profile's
  `to_read_export` block, and finished-book syncing is unaffected.
- Runs only where `exports/` exists, which is mounted for `goodreads-kim` alone.
"""
import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta, UTC
from pathlib import Path

from status import read_export_status, write_export_status

BASE = "https://app.thestorygraph.com"
EXPORT_DIR = Path("exports")
SCHEMA = "storygraph-to-read/1"
MIN_INTERVAL = timedelta(hours=20)
RETRY_INTERVAL = timedelta(hours=3)
# The pile loads ten books per scroll; 600 scrolls is 6,000 books, eight times today's 803.
MAX_SCROLLS = 600
STALL_LIMIT = 8
SCROLL_WAIT_MS = 2500

# One entry per book pane. StoryGraph renders every book twice (two layouts), so callers dedupe
# by id. The cover link carries no text, so the title is the first /books/ link that does.
_COLLECT_JS = """
() => [...document.querySelectorAll('.book-pane-content')].map(p => {
  const idEl = p.querySelector('[data-book-id]');
  const title = [...p.querySelectorAll('a[href^="/books/"]')]
    .map(a => a.textContent.trim()).find(t => t);
  const authors = [...new Set([...p.querySelectorAll('a[href^="/authors/"]')]
    .map(a => a.textContent.trim()).filter(Boolean))];
  return {id: idEl ? idEl.getAttribute('data-book-id') : null, title: title || null, authors};
})
"""


def export_path(profile: str) -> Path:
    return EXPORT_DIR / f"{profile}-to-read.json"


def export_due(profile: str, now: datetime) -> tuple[bool, str]:
    block = read_export_status(profile)
    last_ok = _parse(block.get("last_success"))
    last_try = _parse(block.get("last_attempt"))
    if last_ok and now - last_ok < MIN_INTERVAL:
        return False, f"last export {last_ok.isoformat()} is under {MIN_INTERVAL} old"
    if last_try and block.get("status") == "failed" and now - last_try < RETRY_INTERVAL:
        return False, f"last attempt failed at {last_try.isoformat()}; retrying after {RETRY_INTERVAL}"
    return True, ""


def _parse(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def find_handle(page) -> str:
    """The signed-in reader's handle, from the /profile/<handle> link in the nav."""
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
    # /profile/edit is the settings page, not a handle.
    handles = sorted({m.group(1) for h in hrefs if h and (m := re.match(r"^/profile/([^/?#]+)", h))}
                     - {"edit", "settings"})
    if len(handles) != 1:
        raise RuntimeError(f"expected one profile handle in the nav, found {handles}")
    return handles[0]


def read_pile(page, handle: str) -> dict:
    """Scroll the whole To-Read Pile. Returns what was seen; `validate` decides if it is whole."""
    page.goto(f"{BASE}/to-read/{handle}", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    title = page.title()
    match = re.search(r"\((\d[\d,]*) books?\)", page.inner_text("body"))
    displayed = int(match.group(1).replace(",", "")) if match else None

    def ended() -> bool:
        return page.locator("#next_link").count() > 0 and page.locator("a#next_link[href]").count() == 0

    def unique() -> int:
        return len({b["id"] for b in page.evaluate(_COLLECT_JS) if b["id"]})

    seen, still, scrolls = unique(), 0, 0
    while not ended() and scrolls < MAX_SCROLLS and still < STALL_LIMIT:
        page.mouse.wheel(0, 20000)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(SCROLL_WAIT_MS)
        scrolls += 1
        now = unique()
        still = still + 1 if now == seen else 0
        seen = now
    page.wait_for_timeout(SCROLL_WAIT_MS)  # let the last page finish rendering

    books: dict[str, dict] = {}
    for entry in page.evaluate(_COLLECT_JS):
        if entry["id"] and entry["id"] not in books:
            books[entry["id"]] = entry
    return {"page_title": title, "displayed": displayed, "end_seen": ended(),
            "scrolls": scrolls, "stalled": still >= STALL_LIMIT,
            "books": list(books.values()), "untitled": sum(1 for b in books.values() if not b["title"])}


def validate(handle: str, seen: dict) -> str | None:
    """Why this reading is not provably the whole pile, or None when it is."""
    if not seen["page_title"].startswith(f"{handle} - To-Read Pile"):
        return f"not the To-Read Pile of {handle}: page title {seen['page_title']!r}"
    if seen["displayed"] is None:
        return "the page shows no book count, so completeness cannot be checked"
    if not seen["end_seen"]:
        why = "stalled" if seen["stalled"] else f"stopped after {seen['scrolls']} scrolls"
        return f"never reached the end of the list ({why}; {len(seen['books'])} of {seen['displayed']} books)"
    if len(seen["books"]) != seen["displayed"]:
        return f"read {len(seen['books'])} unique books but the page says {seen['displayed']}"
    if seen["untitled"]:
        return f"{seen['untitled']} books had no title; the page layout may have changed"
    return None


def publish(profile: str, handle: str, seen: dict, now: datetime) -> Path:
    payload = {
        "schema": SCHEMA, "profile": profile, "handle": handle,
        "scraped_at": now.isoformat(), "displayed_count": seen["displayed"],
        "count": len(seen["books"]), "complete": True,
        "books": [{"id": b["id"], "title": b["title"], "authors": b["authors"]} for b in seen["books"]],
    }
    final = export_path(profile)
    tmp = final.with_name(final.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    owner = EXPORT_DIR.stat()
    if os.geteuid() == 0:
        os.chown(tmp, owner.st_uid, owner.st_gid)
    os.replace(tmp, final)
    return final


def export_to_read(profile: str, headless: bool = False, log=print, force: bool = False) -> dict:
    """Run one export if it is due. Never raises: the outcome is returned and written to status."""
    if not EXPORT_DIR.is_dir():
        return {"status": "skipped", "reason": "no exports/ directory mounted"}
    now = datetime.now(UTC)
    if not force:
        due, why = export_due(profile, now)
        if not due:
            return {"status": "skipped", "reason": why}
    previous = read_export_status(profile)
    block = {"last_attempt": now.isoformat(), "last_success": previous.get("last_success")}
    start = time.time()
    log("TO-READ EXPORT — start")
    try:
        # Imported here so the module loads (and its pure parts test) without a browser stack.
        from storygraph.runner_api import storygraph_session
        with storygraph_session(profile, headless=headless) as page:
            handle = find_handle(page)
            seen = read_pile(page, handle)
        problem = validate(handle, seen)
        if problem:
            block.update(status="failed", error=problem, books_read=len(seen["books"]),
                         displayed_count=seen["displayed"])
            log(f"TO-READ EXPORT — not published, last good file kept: {problem}")
        else:
            path = publish(profile, handle, seen, now)
            block.update(status="success", last_success=now.isoformat(), count=len(seen["books"]),
                         error=None)
            log(f"TO-READ EXPORT — published {len(seen['books'])} books to {path}")
    except Exception as exc:  # noqa: BLE001 — the export must never fail the sync
        block.update(status="failed", error=f"{type(exc).__name__}: {exc}".splitlines()[0][:300])
        log(f"TO-READ EXPORT — failed, last good file kept: {block['error']}")
    block["duration_seconds"] = round(time.time() - start, 1)
    write_export_status(profile, block)
    return block


def main() -> None:
    p = argparse.ArgumentParser(description="Export a StoryGraph To-Read Pile to exports/<profile>-to-read.json")
    p.add_argument("--profile", required=True)
    p.add_argument("--force", action="store_true", help="run even if an export is not yet due")
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()
    result = export_to_read(args.profile, headless=args.headless, force=args.force)
    print(json.dumps(result, indent=1))
    raise SystemExit(0 if result.get("status") in ("success", "skipped") else 1)


if __name__ == "__main__":
    main()
