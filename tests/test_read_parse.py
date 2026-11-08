"""Pure parsing for the kim-read export (reading-cards round table, D2/A1)."""
from datetime import date

from goodreads.read_parse import Row, check_complete, parse_gr_date, parse_pages, split_series


def row(book_id, date_read, title="A Book", date_started=None):
    return Row(gr_book_id=book_id, review_id="r" + book_id, title_full=title, author="Some Author",
               date_read=date_read, date_started=date_started, rating=None, pages=None, cover_url=None)


CUTOFF = date(2026, 10, 12)


def test_split_series_both_forms():
    assert split_series("Quiet Harbor (The Lantern Keepers, #2)") == (
        "Quiet Harbor", {"name": "The Lantern Keepers", "number": "2"})
    assert split_series("The Glass Ledger (Inspector Vale #20)") == (
        "The Glass Ledger", {"name": "Inspector Vale", "number": "20"})
    assert split_series("Second Fiddle (The Understudy Papers, #2.5)")[1] == {
        "name": "The Understudy Papers", "number": "2.5"}


def test_split_series_keeps_non_series_paren():
    assert split_series("Field Notes (Illustrated Edition)") == ("Field Notes (Illustrated Edition)", None)
    assert split_series("Lantern Season") == ("Lantern Season", None)


def test_parse_gr_date_forms():
    assert parse_gr_date("Nov 05, 2026 [edit]") == ("2026-11-05", "ok")
    assert parse_gr_date("Nov 02, 2026       [edit]") == ("2026-11-02", "ok")
    assert parse_gr_date("not set") == (None, "unset")
    assert parse_gr_date("") == (None, "unset")
    assert parse_gr_date("Nov 2026") == (None, "partial")
    assert parse_gr_date("2026") == (None, "partial")
    assert parse_gr_date("yesterday-ish") == (None, "unparsed")


def test_parse_pages():
    assert parse_pages("318         pp") == 318
    assert parse_pages("unknown") is None
    assert parse_pages("") is None


def test_complete_by_cutoff():
    pages = [[row("1", "Nov 05, 2026"), row("2", "Nov 02, 2026")],
             [row("3", "Oct 20, 2026"), row("4", "Oct 01, 2026")]]
    assert check_complete(pages, CUTOFF, printed_count=1369, has_next=True) == (True, "ok-cutoff")


def test_row_on_the_cutoff_day_does_not_prove_coverage():
    # The window includes the cutoff day itself; only a strictly older row shows nothing was missed.
    pages = [[row("1", "Nov 05, 2026"), row("2", "Oct 12, 2026")]]
    assert check_complete(pages, CUTOFF, printed_count=1369, has_next=True) == (False, "short")


def test_not_complete_when_cutoff_not_reached_and_more_pages():
    pages = [[row("1", "Nov 05, 2026"), row("2", "Oct 20, 2026")]]
    assert check_complete(pages, CUTOFF, printed_count=1369, has_next=True) == (False, "short")


def test_complete_by_exhaustion_short_shelf():
    pages = [[row("1", "Nov 05, 2026"), row("2", "Nov 02, 2026"), row("3", "Oct 30, 2026")]]
    assert check_complete(pages, CUTOFF, printed_count=3, has_next=False) == (True, "ok-exhausted")
    assert check_complete([[]], CUTOFF, printed_count=0, has_next=False) == (True, "ok-exhausted")


def test_exhaustion_needs_matching_count():
    pages = [[row("1", "Nov 05, 2026"), row("2", "Nov 02, 2026")]]
    assert check_complete(pages, CUTOFF, printed_count=3, has_next=False) == (False, "short")
    assert check_complete(pages, CUTOFF, printed_count=None, has_next=False) == (False, "short")


def test_incomplete_when_order_breaks_across_pages():
    pages = [[row("1", "Nov 05, 2026"), row("2", "Oct 20, 2026")],
             [row("3", "Nov 01, 2026"), row("4", "Oct 01, 2026")]]
    assert check_complete(pages, CUTOFF, printed_count=1369, has_next=True) == (False, "order")


def test_incomplete_unparsed_date():
    pages = [[row("1", "Nov 05, 2026"), row("2", "sometime"), row("3", "Oct 01, 2026")]]
    assert check_complete(pages, CUTOFF, printed_count=1369, has_next=True) == (False, "unparsed-date")


def test_undated_rows_ignored_for_order():
    # Goodreads puts read-without-date and month-only rows in the list too; they neither break the
    # descending order nor count as the cutoff row.
    pages = [[row("1", "Nov 05, 2026"), row("2", "not set"), row("3", "Nov 2026"),
              row("4", "Oct 20, 2026"), row("5", "Oct 01, 2026")]]
    assert check_complete(pages, CUTOFF, printed_count=1369, has_next=True) == (True, "ok-cutoff")


def test_title_with_ampersand_and_emoji_survives():
    assert split_series("Salt & Honey 🍯: A Novel (Sweet Things, #3)") == (
        "Salt & Honey 🍯: A Novel", {"name": "Sweet Things", "number": "3"})
