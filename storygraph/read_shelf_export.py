"""
Export a reader's whole StoryGraph read shelf to a file another tool can read.

reading-cards (~/dev/reading-cards) draws Justin's 2026 year card from it (Vikunja Dev task 180,
operator rulings 2026-11-09, R1-R10). Justin marks finishes on StoryGraph himself, so StoryGraph
is his reading record (R1, R3), and this repo is the only one holding his session (R4).

The contract:
- Read-only on StoryGraph. It opens the read shelf and scrolls; it never clicks, submits a form or
  logs in. It loads the saved session in `storygraph/state/` and **never saves it back**. If that
  session no longer signs in, it stops with an error instead of falling back to the password, the
  way `storygraph_session` would.
- Writes `exports/<profile>-read.json` (`storygraph-read/1`) and nothing else: no status.json
  block, because it runs by hand (R4). The file holds no credentials and no session, is 0600,
  owned by whoever owns `exports/`, and is written to `.new` and then renamed.
- Publishes only a provably complete shelf: the "More..." link `#next_link` has stopped being a
  link, the unique books equal the count the page prints ("75 books"), and every book has a title.
  Anything else keeps the last good file.

What one pane carries (probed 2026-11-09): cover (`cdn.thestorygraph.com`), title, authors,
series name and number, the shelved edition's "<n> pages • <format> • <year>", genre tags (teal)
and mood/pace tags (pink), and in the reader's own action menu their rating (quarter stars) and
the latest read instance's "Finished <Mon d, yyyy>". A pane shows one finish date per book, so a
re-read keeps only its latest finish. There are no start dates on the list.

Manual run (reads StoryGraph only):
  docker compose run --rm -v ./exports:/app/exports audible-justin \
    python -m storygraph.read_shelf_export --profile justin --headless
"""
import argparse
import json
import os
import re
import time
from datetime import date, datetime, UTC
from pathlib import Path

BASE = "https://app.thestorygraph.com"
EXPORT_DIR = Path("exports")
STATE_DIR = Path(__file__).parent / "state"
SCHEMA = "storygraph-read/1"
MAX_SCROLLS = 200      # ten books per load; 2,000 books
STALL_LIMIT = 8
SCROLL_WAIT_MS = 2500

MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1)}

# One entry per book pane. StoryGraph renders tags twice (desktop and mobile), so only the
# desktop block is read; panes themselves can repeat, so callers dedupe by id.
_COLLECT_JS = r"""
() => [...document.querySelectorAll('.book-pane-content')].map(p => {
  const q = s => p.querySelector(s);
  const txt = el => el ? el.textContent.replace(/\s+/g, ' ').trim() : null;
  const idEl = q('[data-book-id]');
  const head = q('.book-title-author-and-series');
  const series = head ? [...head.querySelectorAll('a[href^="/series/"]')].map(txt) : [];
  const authors = head ? [...new Set([...head.querySelectorAll('a[href^="/authors/"]')]
    .map(txt).filter(Boolean))] : [];
  const tagBox = q('.book-pane-tag-section > div');
  const tags = cls => tagBox ? [...tagBox.querySelectorAll('span.' + cls)].map(txt).filter(Boolean) : [];
  const menu = q('.action-menu');
  const finished = menu ? [...menu.querySelectorAll('a[href*="read_instance_id"]')].map(txt) : [];
  const img = q('.book-cover img');
  return {
    id: idEl ? idEl.getAttribute('data-book-id') : null,
    title: txt(head && head.querySelector('h3 a[href^="/books/"]')),
    authors, series,
    edition: txt(q('.toggle-edition-info-link')),
    genres: tags('text-teal-700'), moods: tags('text-pink-500'),
    rating: txt(menu && menu.querySelector('[class~="-ml-1"]')),
    finished,
    cover: img ? img.getAttribute('src') : null,
  };
})
"""


def parse_finished(texts: list[str]) -> str | None:
    """The latest full 'Finished Mon d, yyyy' as an ISO date; month-only or missing gives None."""
    found = []
    for t in texts or []:
        m = re.search(r"Finished\s+([A-Z][a-z]{2})[a-z]*\s+(\d{1,2}),\s+(\d{4})", t or "")
        if m and m.group(1) in MONTHS:
            found.append(date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))))
    return max(found).isoformat() if found else None


def parse_edition(text: str | None) -> tuple[int | None, str | None]:
    """'423 pages • hardcover • 2022' -> (423, 'hardcover'). Audio editions may print no pages."""
    if not text:
        return None, None
    pages = re.search(r"(\d[\d,]*)\s+pages", text)
    fmt = re.search(r"\b(hardcover|paperback|digital|audio)\b", text)
    return (int(pages.group(1).replace(",", "")) if pages else None,
            fmt.group(1) if fmt else None)


def parse_rating(text: str | None) -> float | None:
    """The reader's own rating from their action menu: 0.25 to 5.0, else None."""
    try:
        value = float(text) if text else None
    except ValueError:
        return None
    return value if value is not None and 0 < value <= 5 else None


def parse_series(parts: list[str]) -> tuple[str | None, str | None]:
    """['The Glass Orchard', '#3.5'] -> ('The Glass Orchard', '3.5')."""
    name = next((p for p in parts or [] if p and not p.startswith("#")), None)
    number = next((p[1:] for p in parts or [] if p and p.startswith("#")), None)
    return name, number


def normalize(raw: dict) -> dict:
    pages, fmt = parse_edition(raw.get("edition"))
    series, number = parse_series(raw.get("series"))
    return {
        "sg_book_id": raw["id"], "title": raw.get("title"), "authors": raw.get("authors") or [],
        "series": series, "series_number": number, "pages": pages, "format": fmt,
        "rating": parse_rating(raw.get("rating")),
        "date_finished": parse_finished(raw.get("finished")),
        "genres": [g.lower() for g in raw.get("genres") or []][:8],
        "moods": [m.lower() for m in raw.get("moods") or []][:8],
        "cover_url": raw.get("cover"),
    }


def find_handle(page) -> str:
    """The signed-in reader's handle. Raises, without logging in, if the session is signed out."""
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    if "sign_in" in page.url or page.locator("#user_email").count():
        raise RuntimeError("saved StoryGraph session is signed out; not logging in (refresh it "
                           "with a normal sync run)")
    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
    handles = sorted({m.group(1) for h in hrefs if h and (m := re.match(r"^/profile/([^/?#]+)", h))}
                     - {"edit", "settings"})
    if len(handles) != 1:
        raise RuntimeError(f"expected one profile handle in the nav, found {len(handles)}")
    return handles[0]


def read_shelf(page, handle: str) -> dict:
    page.goto(f"{BASE}/books-read/{handle}", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    title = page.title()
    match = re.search(r"(\d[\d,]*)\s+books?\b", page.inner_text(".books-list-header")
                      if page.locator(".books-list-header").count() else "")
    displayed = int(match.group(1).replace(",", "")) if match else None

    def ended() -> bool:
        return page.locator("a#next_link[href]").count() == 0

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
    page.wait_for_timeout(SCROLL_WAIT_MS)
    books: dict[str, dict] = {}
    for raw in page.evaluate(_COLLECT_JS):
        if raw["id"] and raw["id"] not in books:
            books[raw["id"]] = normalize(raw)
    return {"page_title": title, "displayed": displayed, "end_seen": ended(), "scrolls": scrolls,
            "stalled": still >= STALL_LIMIT, "books": list(books.values())}


def validate(handle: str, seen: dict) -> str | None:
    """Why this reading is not provably the whole shelf, or None when it is."""
    if "Read Books" not in seen["page_title"]:
        return f"not a read shelf: page title {seen['page_title']!r}"
    if seen["displayed"] is None:
        return "the page shows no book count, so completeness cannot be checked"
    if not seen["end_seen"]:
        why = "stalled" if seen["stalled"] else f"stopped after {seen['scrolls']} scrolls"
        return f"never reached the end of the list ({why}; {len(seen['books'])} of {seen['displayed']})"
    if len(seen["books"]) != seen["displayed"]:
        return f"read {len(seen['books'])} unique books but the page says {seen['displayed']}"
    untitled = sum(1 for b in seen["books"] if not b["title"])
    if untitled:
        return f"{untitled} books had no title; the page layout may have changed"
    return None


def publish(profile: str, handle: str, seen: dict, now: datetime) -> Path:
    payload = {"schema": SCHEMA, "profile": profile, "handle": handle,
               "scraped_at": now.isoformat(), "displayed_count": seen["displayed"],
               "count": len(seen["books"]), "complete": True, "books": seen["books"]}
    final = EXPORT_DIR / f"{profile}-read.json"
    tmp = final.with_name(final.name + ".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    if os.geteuid() == 0:
        owner = EXPORT_DIR.stat()
        os.chown(tmp, owner.st_uid, owner.st_gid)
    os.replace(tmp, final)
    return final


def export_read_shelf(profile: str, headless: bool = True, log=print) -> dict:
    if not EXPORT_DIR.is_dir():
        return {"status": "failed", "error": "no exports/ directory mounted"}
    state = STATE_DIR / f".storygraph_state_{profile}.json"
    if not state.exists():
        return {"status": "failed", "error": f"no saved StoryGraph session for {profile}"}
    now, start = datetime.now(UTC), time.time()
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                page = browser.new_context(storage_state=str(state)).new_page()
                handle = find_handle(page)
                seen = read_shelf(page, handle)
            finally:
                browser.close()          # the context's state is never written back
        problem = validate(handle, seen)
        if problem:
            result = {"status": "failed", "error": problem}
        else:
            path = publish(profile, handle, seen, now)
            dated = sum(1 for b in seen["books"] if b["date_finished"])
            result = {"status": "success", "path": str(path), "count": len(seen["books"]),
                      "with_finish_date": dated}
    except Exception as exc:  # noqa: BLE001 — report, keep the last good file
        result = {"status": "failed", "error": f"{type(exc).__name__}: {exc}".splitlines()[0][:300]}
    result["duration_seconds"] = round(time.time() - start, 1)
    log(f"READ SHELF EXPORT — {result['status']}: {result.get('error') or result.get('path')}")
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Export a StoryGraph read shelf to exports/<profile>-read.json")
    p.add_argument("--profile", required=True)
    p.add_argument("--headless", action="store_true")
    args = p.parse_args()
    result = export_read_shelf(args.profile, headless=args.headless)
    print(json.dumps(result, indent=1))
    raise SystemExit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
