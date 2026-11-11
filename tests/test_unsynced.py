"""Books the sync keeps failing are counted and listed in status.json (task 182)."""
from goodreads.unsynced import status_list, track_unsynced


def upd(rid, title="T"):
    return {"review_id": rid, "title": title, "author": "A"}


def test_first_failure_starts_a_counter():
    got = track_unsynced({}, [upd("1")], set(), "2026-11-10T20:00:00-08:00")
    assert got == {"1": {"title": "T", "author": "A", "first_failed": "2026-11-10T20:00:00-08:00",
                         "last_failed": "2026-11-10T20:00:00-08:00", "attempts": 1}}


def test_repeat_failure_keeps_first_failed_and_counts_up():
    prev = track_unsynced({}, [upd("1")], set(), "2026-11-10T20:00:00-08:00")
    got = track_unsynced(prev, [upd("1")], set(), "2026-11-10T21:00:00-08:00")
    assert got["1"]["attempts"] == 2
    assert got["1"]["first_failed"] == "2026-11-10T20:00:00-08:00"
    assert got["1"]["last_failed"] == "2026-11-10T21:00:00-08:00"


def test_applied_book_drops_out():
    prev = track_unsynced({}, [upd("1"), upd("2")], set(), "t1")
    got = track_unsynced(prev, [upd("1"), upd("2")], {"1"}, "t2")
    assert list(got) == ["2"]


def test_book_no_longer_queued_drops_out():
    prev = track_unsynced({}, [upd("1")], set(), "t1")
    assert track_unsynced(prev, [upd("2")], set(), "t2") == {"2": {
        "title": "T", "author": "A", "first_failed": "t2", "last_failed": "t2", "attempts": 1}}


def test_status_list_puts_the_longest_stuck_first():
    unsynced = {"a": {"title": "New", "attempts": 1}, "b": {"title": "Old", "attempts": 1321}}
    assert [row["review_id"] for row in status_list(unsynced)] == ["b", "a"]
    assert status_list(None) == []
