from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchProviderResult:
    title: str
    url: str
    snippet: str
    query: str
    provider: str


class SearchProvider(Protocol):
    name: str

    def available(self) -> bool:
        """Return true when the provider can search now without additional setup."""
        ...

    def search(self, queries: list[str], results_per_query: int) -> list[SearchProviderResult]:
        """Search the provider and return normalized results."""
        ...

    def manual_queries(self, queries: list[str]) -> list[str]:
        """Return query strings an operator can run manually when provider search is unavailable."""
        ...
