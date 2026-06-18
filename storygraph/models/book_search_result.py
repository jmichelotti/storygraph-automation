from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class BookSearchResult:
    query: str
    title: str
    author: Optional[str]
    url: str
    # Disambiguation signals for duplicate entries (same title + author).
    editions: Optional[int] = None      # edition count, e.g. "37 editions"
    user_added: bool = False            # flagged "user-added" / not Librarian-reviewed
