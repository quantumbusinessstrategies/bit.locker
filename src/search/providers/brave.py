from __future__ import annotations

import os
import time

import requests

from search.providers.base import SearchProviderResult

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveProvider:
    name = "Brave"

    def __init__(self, api_key: str | None = None, **_: object) -> None:
        self.api_key = api_key or os.getenv("BRAVE_SEARCH_API_KEY")

    def available(self) -> bool:
        return bool(self.api_key)

    def search(self, queries: list[str], results_per_query: int) -> list[SearchProviderResult]:
        if not self.available():
            return []

        results: list[SearchProviderResult] = []
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key,
        }

        for query in queries:
            try:
                response = requests.get(
                    BRAVE_ENDPOINT,
                    headers=headers,
                    params={"q": query, "count": min(results_per_query, 20)},
                    timeout=20,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError):
                # Free tier rate limit is 1 req/sec - back off and skip this query on failure
                # rather than crashing the whole discovery run.
                time.sleep(1)
                continue

            web_results = payload.get("web", {}).get("results", [])
            for item in web_results[:results_per_query]:
                results.append(
                    SearchProviderResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("description", ""),
                        query=query,
                        provider=self.name,
                    )
                )

            # Brave's free tier is rate-limited to 1 request/second.
            time.sleep(1.1)

        return results

    def manual_queries(self, queries: list[str]) -> list[str]:
        return queries
