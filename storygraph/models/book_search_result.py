from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class BookSearchResult:
    query: str
    title: str
    author: Optional[str]
    url: str
