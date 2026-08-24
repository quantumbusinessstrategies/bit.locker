from __future__ import annotations

from search.providers.base import SearchProviderResult


class ManualQueryModeProvider:
    name = "ManualQueryMode"

    def __init__(self, **_: object) -> None:
        pass

    def available(self) -> bool:
        return False

    def search(self, queries: list[str], results_per_query: int) -> list[SearchProviderResult]:
        return []

    def manual_queries(self, queries: list[str]) -> list[str]:
        return queries
