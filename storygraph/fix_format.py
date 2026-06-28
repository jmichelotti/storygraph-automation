"""
One-off helper to fix a single book's format on StoryGraph.

Resolves a title (optionally + author) to its StoryGraph book, then switches it
to the desired edition format via the same ``ensure_book_format`` flow the
syncs use. Used to backfill books synced before format defaults existed — e.g.
Kim's last Goodreads book that landed as an audiobook:

    python -m storygraph.fix_format --profile kim --title "The Book" --format physical

The edition switch carries the reading history over, so read dates / progress
are preserved.
"""
import argparse

from storygraph.runner_api import storygraph_session, normalize_author_for_search
from storygraph.flows import search_books, ensure_book_format
from storygraph.flows.navigate_flow import find_matching_book


def parse_args():
    p = argparse.ArgumentParser(
        description="Force a single book's StoryGraph format by switching editions"
    )
    p.add_argument("--profile", required=True, help="Profile name (e.g. kim)")
    p.add_argument("--title", required=True, help="Book title to fix")
    p.add_argument("--author", help="Author, to disambiguate the search")
    p.add_argument(
        "--format",
        default="physical",
        choices=["physical", "audiobook"],
        help="Desired format (default: physical)",
    )
    p.add_argument("--headless", action="store_true", help="Run browser headless")
    return p.parse_args()


def main():
    args = parse_args()

    author = normalize_author_for_search(args.author) if args.author else None
    query = f"{args.title} {author}" if author else args.title

    with storygraph_session(args.profile, headless=args.headless) as page:
        results = search_books(page, [query], max_results_per_title=5)
        match = find_matching_book(
            results,
            expected_title=args.title,
            expected_author=author,
        )

        if not match:
            print(f"❌ No confident StoryGraph match for '{args.title}'")
            return

        print(f"GOOD! Match -> {match.title} by {match.author} @ {match.url}")

        new_url = ensure_book_format(page, match.url, args.format)
        print(f"DONE. Book now lives on edition: {new_url}")


if __name__ == "__main__":
    main()
