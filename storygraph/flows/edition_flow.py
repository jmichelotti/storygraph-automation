"""
Force a book's *format* on StoryGraph.

On StoryGraph the format (paperback / hardcover / digital-ebook / audio) is a
property of the **edition** on your shelf, not of the book or the read instance.
When we mark a book read / in-progress we inherit whatever edition StoryGraph
happened to pick, which is inconsistent (sometimes an audiobook for a book read
in print). To make the format deterministic we go to the book's editions page
and, if the current edition is the wrong kind, switch to a matching one via the
``/switch-editions`` form — which "moves your reading history to this edition",
preserving status, read dates and progress.

``ensure_book_format`` is best-effort: format is a secondary attribute, so it
never raises. One book that can't be re-formatted is logged and left as-is
rather than aborting the surrounding sync (mirrors the per-book try/except in
``runner_api.py``).
"""
import re
from typing import Callable, Optional

from playwright.sync_api import Page

# StoryGraph edition "Format:" values, grouped by the family we care about.
PHYSICAL_FORMATS = {"paperback", "hardcover"}
AUDIO_FORMATS = {"audio"}

# Editions are paginated (~20 per page). Popular titles list every common format
# on page 1; we scan a few more as a safety net for sparser catalogues.
MAX_EDITION_PAGES = 4

BOOK_URL_PREFIX = "https://app.thestorygraph.com/books/"


def _desired_set(desired: str) -> set[str]:
    """Map a caller-facing format name to the set of acceptable edition formats."""
    d = (desired or "").strip().lower()
    if d in ("audio", "audiobook"):
        return set(AUDIO_FORMATS)
    # "physical" / "print" / "normal" -> a real, non-audio, non-digital book
    return set(PHYSICAL_FORMATS)


def _editions_url(book_url: str, page_num: int = 1) -> str:
    base = book_url.rstrip("/") + "/editions"
    return base if page_num == 1 else f"{base}?page={page_num}"


def _info_field(pane, label: str) -> Optional[str]:
    """Read a value (e.g. "Format", "Language") from an edition's hidden
    ``.edition-info`` block. The block is ``display:hidden`` but present in the
    DOM, so ``text_content`` (not ``inner_text``) is required."""
    info = pane.locator("div.edition-info")
    if info.count() == 0:
        return None
    fields = info.first.locator("p")
    for i in range(fields.count()):
        text = (fields.nth(i).text_content() or "").strip()
        if text.lower().startswith(label.lower()):
            return text[len(label):].strip().lstrip(":").strip()
    return None


def _current_edition_format(page: Page) -> Optional[str]:
    """The current (shelved) edition is the only ``book-pane`` on page 1 with no
    "switch to this edition" form (you can't switch to the edition you're on)."""
    panes = page.locator("div.book-pane")
    for i in range(panes.count()):
        pane = panes.nth(i)
        if pane.locator("form[action='/switch-editions']").count() == 0:
            fmt = _info_field(pane, "Format")
            if fmt:
                return fmt.lower()
    return None


def _collect_candidates(page: Page) -> list[dict]:
    """Switchable editions on the current page: their target id, format, language."""
    out: list[dict] = []
    panes = page.locator("div.book-pane")
    for i in range(panes.count()):
        pane = panes.nth(i)
        form = pane.locator("form[action='/switch-editions']")
        if form.count() == 0:
            continue
        to_id_loc = form.first.locator("input[name='to_book_id']")
        if to_id_loc.count() == 0:
            continue
        to_id = to_id_loc.first.get_attribute("value")
        if not to_id:
            continue
        out.append({
            "to_id": to_id,
            "format": (_info_field(pane, "Format") or "").lower(),
            "language": (_info_field(pane, "Language") or "").lower(),
        })
    return out


def _do_switch(
    page: Page,
    book_url: str,
    to_id: str,
    desired_set: set[str],
    emit: Callable[[str], None],
) -> str:
    """Submit the switch-editions form for ``to_id`` and verify it took.
    Returns the URL of the edition now on the shelf."""
    form = page.locator("form[action='/switch-editions']").filter(
        has=page.locator(f"input[name='to_book_id'][value='{to_id}']")
    )
    if form.count() == 0:
        emit(f"FORMAT -> switch form for edition {to_id} not found; leaving as-is")
        return book_url

    form.first.locator("button[type='submit']").first.click()
    page.wait_for_load_state("load")
    page.wait_for_timeout(1000)

    new_url = BOOK_URL_PREFIX + to_id
    # Verify on the new edition's own editions page — the post-switch redirect
    # target isn't reliably the editions list, so re-open it to read the result.
    new_fmt = None
    try:
        page.goto(_editions_url(new_url, 1), wait_until="domcontentloaded")
        page.wait_for_selector("div.browse-editions", timeout=15000)
        page.wait_for_timeout(500)
        new_fmt = _current_edition_format(page)
    except Exception:
        pass

    if new_fmt and new_fmt in desired_set:
        emit(f"FORMAT -> switched to {new_fmt} edition")
    else:
        emit(f"FORMAT -> switch submitted (now shows {new_fmt or 'unknown'})")
    return new_url


def ensure_book_format(
    page: Page,
    book_url: str,
    desired: str,
    log: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Ensure the edition on the shelf for ``book_url`` matches ``desired``
    ("physical" or "audiobook"). If it already does, do nothing. Otherwise scan
    the editions page for a matching (preferably English) edition and switch to
    it, which carries the reading history over.

    Returns the URL of the edition now holding the reading history — the input
    ``book_url`` if unchanged, or the new edition's URL after a switch. Callers
    on the repeating progress path persist this so subsequent runs go straight
    to the right edition. Never raises.
    """
    def emit(msg: str) -> None:
        print(msg)
        if log:
            log(msg)

    desired_set = _desired_set(desired)

    try:
        page.goto(_editions_url(book_url, 1), wait_until="domcontentloaded")
        page.wait_for_selector("div.browse-editions", timeout=20000)
        page.wait_for_timeout(800)
    except Exception as exc:
        emit(f"FORMAT -> could not open editions page ({exc!r}); leaving as-is")
        return book_url

    try:
        current_fmt = _current_edition_format(page)
        emit(f"FORMAT -> current edition is '{current_fmt or 'unknown'}', want {desired}")
        if current_fmt and current_fmt in desired_set:
            emit("FORMAT -> already correct; no switch needed")
            return book_url

        # first desired-format edition of any language: (page_num, to_id)
        fallback: Optional[tuple[int, str]] = None
        for page_num in range(1, MAX_EDITION_PAGES + 1):
            if page_num > 1:
                try:
                    page.goto(_editions_url(book_url, page_num),
                              wait_until="domcontentloaded")
                    page.wait_for_selector("div.browse-editions", timeout=15000)
                    page.wait_for_timeout(600)
                except Exception:
                    break

            candidates = _collect_candidates(page)
            if not candidates and page_num > 1:
                break  # ran past the last page of editions

            desired_cands = [c for c in candidates if c["format"] in desired_set]
            english = [c for c in desired_cands if "english" in c["language"]]

            if english:
                return _do_switch(page, book_url, english[0]["to_id"],
                                  desired_set, emit)
            if desired_cands and fallback is None:
                fallback = (page_num, desired_cands[0]["to_id"])

        if fallback:
            # No English edition of the desired format — fall back to the first
            # one we saw (re-navigate to its page so its switch form is present).
            fb_page, fb_id = fallback
            page.goto(_editions_url(book_url, fb_page), wait_until="domcontentloaded")
            page.wait_for_selector("div.browse-editions", timeout=15000)
            page.wait_for_timeout(600)
            return _do_switch(page, book_url, fb_id, desired_set, emit)

        emit(f"FORMAT -> no {desired} edition available; leaving as-is")
        return book_url
    except Exception as exc:
        emit(f"FORMAT -> error while setting format ({exc!r}); leaving as-is")
        return book_url
