"""An author-less StoryGraph record is accepted on an exact, specific title, and only then (task 182)."""
import pytest

pytest.importorskip("playwright")   # navigate_flow imports Playwright at module level

from storygraph.flows.navigate_flow import find_matching_book  # noqa: E402
from storygraph.models.book_search_result import BookSearchResult  # noqa: E402

SEVEN = "Seven Men for Seven Friends"
AUTHOR = "Elizabeth Manriquez"


def r(title, author, url, **kw):
    return BookSearchResult(query="q", title=title, author=author, url=url, **kw)


def test_sole_authorless_exact_title_is_accepted():
    # What StoryGraph returned every hour from 2026-09-09: one record, author line blank.
    got = find_matching_book([r(SEVEN, None, "/books/4826")], SEVEN, AUTHOR)
    assert got is not None and got.url == "/books/4826"


def test_desktop_and_mobile_copies_of_the_same_record_count_once():
    results = [r(SEVEN, None, "/books/4826"), r(SEVEN, "", "/books/4826")]
    assert find_matching_book(results, SEVEN, AUTHOR).url == "/books/4826"


def test_title_match_ignores_case_and_punctuation():
    got = find_matching_book([r("Seven men for seven friends!", None, "/b/1")], SEVEN, AUTHOR)
    assert got is not None


def test_authored_record_with_the_same_title_blocks_the_fallback():
    # A named author on the same title means a real book by someone else; ours may not be either.
    results = [r(SEVEN, None, "/b/1"), r(SEVEN, "Someone Else", "/b/2")]
    assert find_matching_book(results, SEVEN, AUTHOR) is None


def test_two_authorless_records_with_the_title_are_ambiguous():
    results = [r(SEVEN, None, "/b/1"), r(SEVEN, None, "/b/2")]
    assert find_matching_book(results, SEVEN, AUTHOR) is None


def test_partial_title_is_not_enough():
    assert find_matching_book([r("Seven Men", None, "/b/1")], SEVEN, AUTHOR) is None
    assert find_matching_book([r(SEVEN + ": A Novella", None, "/b/1")], SEVEN, AUTHOR) is None


def test_short_titles_never_match_without_an_author():
    assert find_matching_book([r("Home", None, "/b/1")], "Home", "Some Author") is None
    assert find_matching_book([r("The Fall", None, "/b/1")], "The Fall", "Some Author") is None


def test_a_real_author_match_still_wins():
    results = [r(SEVEN, None, "/b/1"), r(SEVEN, AUTHOR, "/b/2")]
    assert find_matching_book(results, SEVEN, AUTHOR).url == "/b/2"


def test_wrong_author_alone_is_still_rejected():
    assert find_matching_book([r(SEVEN, "Someone Else", "/b/2")], SEVEN, AUTHOR) is None
