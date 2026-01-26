import argparse
import json
from pathlib import Path
from datetime import datetime, UTC

from storygraph.runner_api import update_books_progress
from audible.audible_in_progress import export_library, get_in_progress_books


def parse_args():
    parser = argparse.ArgumentParser(
        description="Diff Audible in-progress books vs last sync state"
    )
    parser.add_argument(
        "--profile",
        required=True,
        help="StoryGraph profile name (used for sync state)",
    )
    return parser.parse_args()


def get_sync_state_path(profile: str) -> Path:
    state_dir = Path("storygraph/state")
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"sync_{profile}.json"


def load_sync_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def save_sync_state(path: Path, audible_books: list[dict]) -> None:
    state = {}

    for book in audible_books:
        state[book["title"]] = {
            "percent_complete": book["percent_complete"],
            "updated_at": datetime.now(UTC).isoformat(),
        }

    path.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8",
    )

def diff_audible_vs_sync(
    audible_books: list[dict],
    sync_state: dict,
) -> tuple[list[dict], list[dict]]:
    """
    Returns:
      - updates: books whose progress changed or are new
      - unchanged: books whose progress is unchanged
    """
    updates = []
    unchanged = []

    for book in audible_books:
        title = book["title"]
        current_percent = book["percent_complete"]

        previous = sync_state.get(title)
        previous_percent = (
            previous["percent_complete"] if previous else None
        )

        if previous_percent is None:
            updates.append(
                {
                    **book,
                    "reason": "new",
                    "previous_percent": None,
                }
            )
        elif abs(current_percent - previous_percent) > 0.01:
            updates.append(
                {
                    **book,
                    "reason": "changed",
                    "previous_percent": previous_percent,
                }
            )
        else:
            unchanged.append(book)

    return updates, unchanged


def print_diff(updates: list[dict], unchanged: list[dict]) -> None:
    print("\n Audible -> StoryGraph diff\n")

    if updates:
        print("Will update:\n")
        for book in updates:
            if book["reason"] == "new":
                print(f"• {book['title']} (new)")
                print(f"  Progress : {book['percent_complete']}%")
            else:
                print(f"• {book['title']}")
                print(
                    f"  Progress : {book['previous_percent']}% -> {book['percent_complete']}%"
                )
            print()
    else:
        print("No updates needed.\n")

    if unchanged:
        print("Skipping (unchanged):\n")
        for book in unchanged:
            print(f"• {book['title']} ({book['percent_complete']}%)")
        print()


def main():
    args = parse_args()
    profile = args.profile

    sync_state_path = get_sync_state_path(profile)
    sync_state = load_sync_state(sync_state_path)

    export_library()
    audible_books = get_in_progress_books()

    updates, unchanged = diff_audible_vs_sync(
        audible_books,
        sync_state,
    )

    print_diff(updates, unchanged)

    if not updates:
        print("GOOD! Nothing to update in StoryGraph.")
        return

    print("\n Applying updates to StoryGraph...\n")
    update_books_progress(
        books=updates,
        profile=profile,
        headless=False,
    )

    print("\n Saving sync state...")
    save_sync_state(sync_state_path, audible_books)
    print("GOOD! Sync state saved")

if __name__ == "__main__":
    main()
