"""Books the hourly sync keeps failing to put on StoryGraph, so they stop being invisible (task 182).

A book that update_books_read does not apply (no StoryGraph match, or an error on its page) is
retried next run, because its review id never reaches `processed_reviews`. That retry is right,
but it used to be silent: the run still reported success with 0 synced, so 'Seven Men for Seven
Friends' was skipped every hour for two months and 'The Remnant Within' for a month before anyone
noticed. Each such book now gets a counter in the sync state (`unsynced`, keyed by review id),
and the runner copies the list into status.json as `books_not_synced`.

Only books in this run's update list are kept: every unprocessed book is queued again each run,
so a book missing from the list has synced, lost its dates or left the read shelf.
"""


def track_unsynced(
    previous: dict,
    updates: list[dict],
    applied_ids: set[str],
    now_iso: str,
) -> dict:
    """The new `unsynced` map after a run that tried `updates` and applied `applied_ids`."""
    tracked: dict = {}
    for b in updates:
        rid = b["review_id"]
        if rid in applied_ids:
            continue
        before = previous.get(rid) or {}
        tracked[rid] = {
            "title": b.get("title"),
            "author": b.get("author"),
            "first_failed": before.get("first_failed") or now_iso,
            "last_failed": now_iso,
            "attempts": int(before.get("attempts") or 0) + 1,
        }
    return tracked


def status_list(unsynced: dict) -> list[dict]:
    """status.json's `books_not_synced`: most attempts first."""
    rows = [{"review_id": rid, **entry} for rid, entry in (unsynced or {}).items()]
    return sorted(rows, key=lambda r: (-int(r.get("attempts") or 0), r.get("title") or ""))
