"""When the kim-read export is due (reading-cards round table, A10)."""
from datetime import datetime, timedelta, timezone

from goodreads.read_schedule import monday_anchor, next_block, read_export_due

PT = timezone(timedelta(hours=-8))      # PST, the box's clock in November
EST = timezone(timedelta(hours=-5))


def at(y, mo, d, h, mi=0, tz=PT):
    return datetime(y, mo, d, h, mi, tzinfo=tz)


def block(**kw):
    base = {"last_success": None, "last_attempt": None, "last_status": None,
            "anchor": None, "attempts_for_anchor": 0}
    base.update({k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in kw.items()})
    return base


def test_monday_anchor_is_monday_midnight_eastern():
    # Sunday 2026-11-08 21:00 PST is Monday 2026-11-09 00:00 EST.
    assert monday_anchor(at(2026, 11, 8, 21, 0)) == datetime(2026, 11, 9, 0, 0, tzinfo=EST)
    # One minute earlier it is still the previous week's anchor.
    assert monday_anchor(at(2026, 11, 8, 20, 59)) == datetime(2026, 11, 2, 0, 0, tzinfo=EST)


def test_due_at_sunday_2100_pt_monday_anchor():
    # Last success Sunday 15:00 PT: only six hours old, but before this week's anchor.
    b = block(last_success=at(2026, 11, 8, 15), last_attempt=at(2026, 11, 8, 15), last_status="success")
    assert read_export_due(b, at(2026, 11, 8, 21, 0)) == (True, "monday")
    assert read_export_due(b, at(2026, 11, 8, 20, 0)) == (False, "fresh")


def test_cooldown_blocks_monday_retry_within_3h():
    b = block(last_success=at(2026, 11, 8, 15), last_attempt=at(2026, 11, 8, 21), last_status="failed",
              anchor=datetime(2026, 11, 9, 0, 0, tzinfo=EST), attempts_for_anchor=1)
    assert read_export_due(b, at(2026, 11, 8, 23, 0)) == (False, "cooldown")
    assert read_export_due(b, at(2026, 11, 9, 0, 0)) == (True, "monday")


def test_monday_cap_after_three_failures():
    b = block(last_success=at(2026, 11, 8, 15), last_status="success")
    for t in (at(2026, 11, 8, 21), at(2026, 11, 9, 0), at(2026, 11, 9, 3)):
        assert read_export_due(b, t)[0] is True
        b = next_block(b, t, ok=False, detail={"error": "x"})
    assert b["attempts_for_anchor"] == 3
    # Cooldown over, success only 15 hours old: the Monday route is spent and daily is not due.
    assert read_export_due(b, at(2026, 11, 9, 6, 1)) == (False, "monday-cap")


def test_daily_after_20h():
    b = block(last_success=at(2026, 11, 5, 10), last_attempt=at(2026, 11, 5, 10), last_status="success",
              anchor=datetime(2026, 11, 2, 0, 0, tzinfo=EST))
    assert read_export_due(b, at(2026, 11, 6, 5, 59)) == (False, "fresh")
    assert read_export_due(b, at(2026, 11, 6, 6, 1)) == (True, "daily")


def test_success_records_time_and_clears_failure():
    b = next_block(block(), at(2026, 11, 8, 21), ok=True, detail={"count": 7})
    assert b["last_success"] == at(2026, 11, 8, 21).isoformat()
    assert b["last_status"] == "success" and b["count"] == 7
    assert read_export_due(b, at(2026, 11, 8, 22)) == (False, "fresh")


def test_anchor_change_resets_attempts():
    b = block(last_success=at(2026, 11, 1, 15), last_status="failed", last_attempt=at(2026, 11, 2, 3),
              anchor=datetime(2026, 11, 2, 0, 0, tzinfo=EST), attempts_for_anchor=3)
    nb = next_block(b, at(2026, 11, 8, 21), ok=False, detail={})
    assert nb["anchor"] == datetime(2026, 11, 9, 0, 0, tzinfo=EST).isoformat()
    assert nb["attempts_for_anchor"] == 1


def test_dst_spring_forward_anchor():
    # US clocks moved on Sunday 2027-03-14; Monday 03-15 00:00 is EDT, i.e. Sunday 21:00 PDT.
    pdt, edt = timezone(timedelta(hours=-7)), timezone(timedelta(hours=-4))
    assert monday_anchor(datetime(2027, 3, 14, 21, 0, tzinfo=pdt)) == datetime(2027, 3, 15, 0, 0, tzinfo=edt)
    assert monday_anchor(datetime(2027, 3, 14, 20, 59, tzinfo=pdt)) == datetime(2027, 3, 8, 0, 0,
                                                                              tzinfo=timezone(timedelta(hours=-5)))
