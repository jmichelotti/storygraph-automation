import argparse
from pathlib import Path
from typing import List

from playwright.sync_api import sync_playwright

from storygraph import config
from storygraph.flows import ensure_logged_in, search_books
from storygraph.flows.navigate_flow import find_matching_book, navigate_to_book, set_reading_status, update_reading_progress


def parse_args():
    p = argparse.ArgumentParser(description="StoryGraph automation: login + search book titles")
    p.add_argument("--title", type=str, help="Single book title to search")
    p.add_argument("--author", type=str, help="Author name to refine the search")
    p.add_argument("--titles", nargs="*", help="Multiple book titles to search (space-separated)")
    p.add_argument("--file", type=str, help="Path to a text file with one title per line")
    p.add_argument("--headless", action="store_true", help="Run browser in headless mode")
    p.add_argument("--max-results", type=int, default=3, help="Max results per title")
    p.add_argument(
        "--profile",
        type=str,
        help="Optional browser profile name (e.g. justin). Enables session persistence.",
    )

    progress = p.add_mutually_exclusive_group()
    progress.add_argument("--pages", type=int, help="Update reading progress by pages")
    progress.add_argument("--percent", type=int, help="Update reading progress by percentage")

    return p.parse_args()

def get_storage_state_path(profile: str | None) -> Path | None:
    if not profile:
        return None

    state_dir = Path(__file__).parent / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    return state_dir / f".storygraph_state_{profile}.json"

def load_titles(args) -> List[str]:
    titles: List[str] = []

    if args.title:
        titles.append(args.title)

    if args.titles:
        titles.extend(args.titles)

    if args.file:
        path = Path(args.file)
        if not path.exists():
            raise FileNotFoundError(f"--file not found: {path}")
        titles.extend([line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])

    # De-dupe while preserving order
    seen = set()
    deduped = []
    for t in titles:
        if t not in seen:
            seen.add(t)
            deduped.append(t)

    return deduped


def main():
    args = parse_args()

    if args.pages is not None:
        if args.pages < 0:
            raise ValueError("--pages must be >= 0")

    if args.percent is not None:
        if not (0 <= args.percent <= 100):
            raise ValueError("--percent must be between 0 and 100")

    if not config.STORYGRAPH_EMAIL or not config.STORYGRAPH_PASSWORD:
        raise RuntimeError(
            "Missing STORYGRAPH_EMAIL or STORYGRAPH_PASSWORD environment variables. "
            "Set them and restart your terminal."
        )

    titles = load_titles(args)
    if not titles:
        raise RuntimeError("No titles provided. Use --title, --titles, or --file.")

    author = args.author.strip() if args.author else None

    if author:
        titles = [f"{title} {author}" for title in titles]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        storage_state_path = get_storage_state_path(args.profile)

        if storage_state_path and storage_state_path.exists():
            print(f" Using existing browser state: {storage_state_path.name}")
            context = browser.new_context(storage_state=storage_state_path)
        else:
            print("🆕 Starting new browser session")
            context = browser.new_context()
        page = context.new_page()

        ensure_logged_in(page, config.STORYGRAPH_EMAIL, config.STORYGRAPH_PASSWORD)

        if storage_state_path:
            print(f" Saving browser state to {storage_state_path.name}")
            context.storage_state(path=storage_state_path)

        results = search_books(page, titles, max_results_per_title=args.max_results)

        if args.title and args.author:
            match = find_matching_book(
                results,
                expected_title=args.title,
                expected_author=args.author,
            )

            if match:
                print("\nGOOD! Found exact match — navigating to book page")
                navigate_to_book(page, match)

                if args.pages is not None:
                    update_reading_progress(
                        page,
                        args.pages,
                        progress_type="pages",
                    )

                elif args.percent is not None:
                    update_reading_progress(
                        page,
                        args.percent,
                        progress_type="percentage",
                    )

                else:
                    print("INFO! No progress update requested")
            else:
                print("\n❌ No exact match found for title + author")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
