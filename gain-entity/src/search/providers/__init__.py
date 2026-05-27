from __future__ import annotations

from search.providers.apify import ApifyProvider
from search.providers.base import SearchProvider, SearchProviderResult
from search.providers.brave import BraveProvider
from search.providers.manual import ManualQueryModeProvider
from search.providers.serpapi import SerpAPIProvider
from search.providers.tavily import TavilyProvider


PROVIDERS = {
    "Brave": BraveProvider,
    "Tavily": TavilyProvider,
    "SerpAPI": SerpAPIProvider,
    "Apify": ApifyProvider,
    "ManualQueryMode": ManualQueryModeProvider,
}


def get_provider(name: str | None, **kwargs: object) -> SearchProvider:
    provider_name = name or "ManualQueryMode"
    provider_cls = PROVIDERS.get(provider_name, ManualQueryModeProvider)
    return provider_cls(**kwargs)


__all__ = [
    "SearchProvider",
    "SearchProviderResult",
    "get_provider",
]
