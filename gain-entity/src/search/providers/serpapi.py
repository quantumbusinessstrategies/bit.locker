from __future__ import annotations

import os

from search.providers.base import SearchProviderResult


class SerpAPIProvider:
    name = "SerpAPI"

    def __init__(self, api_key: str | None = None, **_: object) -> None:
        self.api_key = api_key or os.getenv("SERPAPI_API_KEY")

    def available(self) -> bool:
        return bool(self.api_key)

    def search(self, queries: list[str], results_per_query: int) -> list[SearchProviderResult]:
        # Interface placeholder. Add SerpAPI implementation when a key is configured.
        return []

    def manual_queries(self, queries: list[str]) -> list[str]:
        return queries
