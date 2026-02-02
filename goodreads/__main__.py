import argparse
from datetime import date

from goodreads.runner import run


def main():
    parser = argparse.ArgumentParser(
        description="Goodreads → StoryGraph automation"
    )

    parser.add_argument(
        "--profile",
        required=True,
        help="Profile name (matches profiles/{profile}.json)",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to StoryGraph (default is dry-run)",
    )

    parser.add_argument(
        "--seed-before",
        help="Seed Goodreads state with books finished before YYYY-MM-DD",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode",
    )

    args = parser.parse_args()

    seed_date = (
        date.fromisoformat(args.seed_before)
        if args.seed_before
        else None
    )

    run(
        profile=args.profile,
        headless=args.headless,
        dry_run=not args.apply,
        seed_before=seed_date,
    )


if __name__ == "__main__":
    main()
