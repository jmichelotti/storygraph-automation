import subprocess
from pathlib import Path
from datetime import timedelta
import csv
import sys

EXPORT_PATH = Path("library.tsv")


def export_library() -> None:
    """
    Export Audible library to TSV.
    Assumes Audible has already been authenticated via `audible quickstart`.
    """
    print(" Exporting Audible library...")
    try:
        subprocess.run(
            ["audible", "library", "export", "--output", str(EXPORT_PATH)],
            check=True,
        )
    except subprocess.CalledProcessError:
        print()
        print("❌ Audible authentication not found.")
        print()
        print(" Please run this once:")
        print()
        print("   audible quickstart")
        print()
        print("Then re-run this script.")
        print()
        sys.exit(1)


def fmt_minutes(minutes_str: str) -> str:
    if not minutes_str:
        return "N/A"
    minutes = float(minutes_str)
    return str(timedelta(minutes=int(minutes)))


def get_in_progress_books() -> list[dict]:
    """
    Return a list of in-progress Audible books as structured data.
    """
    if not EXPORT_PATH.exists() or EXPORT_PATH.stat().st_size == 0:
        raise RuntimeError("Library export failed or produced an empty file")

    in_progress: list[dict] = []

    with EXPORT_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")

        for row in reader:
            is_finished = row.get("is_finished", "").lower() == "true"
            percent = float(row.get("percent_complete") or 0)

            if not is_finished and percent > 0:
                in_progress.append(
                    {
                        "title": row["title"],
                        "authors": row["authors"],
                        "percent_complete": percent,
                        "runtime_minutes": (
                            int(float(row["runtime_length_min"]))
                            if row.get("runtime_length_min")
                            else None
                        ),
                        "date_added": row.get("date_added"),
                    }
                )

    return in_progress


def print_in_progress_books(books: list[dict]) -> None:
    """
    Pretty-print in-progress Audible books.
    """
    print(f"\n In-progress audiobooks ({len(books)}):\n")

    for book in books:
        print(f"• {book['title']}")
        print(f"  Author(s): {book['authors']}")
        print(f"  Progress : {book['percent_complete']}%")
        if book["runtime_minutes"] is not None:
            print(f"  Runtime  : {timedelta(minutes=book['runtime_minutes'])}")
        print(f"  Added    : {book['date_added']}")
        print()


def main():
    export_library()
    books = get_in_progress_books()
    print_in_progress_books(books)


if __name__ == "__main__":
    main()
