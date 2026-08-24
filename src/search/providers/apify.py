from __future__ import annotations

import os

from search.providers.base import SearchProviderResult


class ApifyProvider:
    name = "Apify"

    def __init__(self, api_key: str | None = None, **_: object) -> None:
        self.api_key = api_key or os.getenv("APIFY_API_TOKEN")

    def available(self) -> bool:
        return bool(self.api_key)

    def search(self, queries: list[str], results_per_query: int) -> list[SearchProviderResult]:
        # Interface placeholder. Add Apify actor/client implementation when a token is configured.
        return []

    def manual_queries(self, queries: list[str]) -> list[str]:
        return queries
