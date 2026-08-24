from __future__ import annotations

import hashlib
import json
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from discovery.source_graph import GraphSearchQuery, SourceGraph
from search.providers import get_provider
from sources.search_queries import SearchQueryCatalog


@dataclass(frozen=True)
class DiscoveredSourceCandidate:
    title: str
    url: str
    snippet: str
    discovery_method: str
    query: str
    domain: str
    fetched_at: str
    raw: dict[str, Any]
    source_family: str = ""
    category_family: str = ""
    root_domain: str = ""
    discovered_from: str = ""
    discovery_depth: int = 1
    source_lineage: str = ""

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.url.strip().lower().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True)
class SourceDiscoveryResult:
    candidates: list[DiscoveredSourceCandidate]
    queries_run: int
    errors: list[str]


class SourceDiscoveryEngine:
    def __init__(
        self,
        rules: dict[str, Any],
        request_timeout_seconds: int,
        user_agent: str,
    ) -> None:
        discovery_config = rules.get("source_discovery", {})
        self.enabled = bool(rules.get("source_discovery_enabled", discovery_config.get("enabled", True)))
        self.query_limit = int(discovery_config.get("query_limit", 8))
        self.results_per_query = int(discovery_config.get("results_per_query", 4))
        self.max_candidates = int(discovery_config.get("max_candidates_per_run", 25))
        self.search_endpoint = discovery_config.get("search_endpoint", "https://duckduckgo.com/html/")
        self.provider_name = discovery_config.get("provider", rules.get("search_provider", "ManualQueryMode"))
        self.manual_query_output = Path(discovery_config.get("manual_query_output", "data/manual_search_queries.csv"))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.request_timeout_seconds = request_timeout_seconds
        self.configured_queries = discovery_config.get("queries")

    def discover(
        self,
        known_urls: set[str],
        extra_queries: list[GraphSearchQuery] | None = None,
    ) -> SourceDiscoveryResult:
        if not self.enabled:
            return SourceDiscoveryResult(candidates=[], queries_run=0, errors=[])

        candidates: list[DiscoveredSourceCandidate] = []
        errors: list[str] = []
        seen = {normalize_url(url) for url in known_urls}
        queries = SearchQueryCatalog.get_queries(self.configured_queries, self.query_limit)
        query_metadata: dict[str, GraphSearchQuery] = {}
        for graph_query in extra_queries or []:
            cleaned = " ".join(str(graph_query.query).split())
            if not cleaned or cleaned in queries:
                continue
            queries.append(cleaned)
            query_metadata[cleaned] = graph_query
        provider = get_provider(self.provider_name)

        if provider.available():
            try:
                provider_results = provider.search(queries, self.results_per_query)
                for result in provider_results:
                    normalized = normalize_url(result.url)
                    if not normalized or normalized in seen:
                        continue
                    seen.add(normalized)
                    candidates.append(
                        self._candidate_from_result(
                            title=result.title,
                            url=result.url,
                            snippet=result.snippet,
                            discovery_method=result.provider,
                            query=result.query,
                            raw={"provider": result.provider, "query": result.query},
                            graph_query=query_metadata.get(result.query),
                        )
                    )
                    if len(candidates) >= self.max_candidates:
                        break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"provider search {self.provider_name}: {exc}")
        else:
            self._write_manual_queries(provider.manual_queries(queries))

        for query in queries:
            if len(candidates) >= self.max_candidates:
                break
            try:
                results = self._search_duckduckgo(query)
            except Exception as exc:  # noqa: BLE001 - search failure should not break the run
                errors.append(f"source search {query!r}: {exc}")
                continue

            for result in results:
                normalized = normalize_url(result["url"])
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append(
                    self._candidate_from_result(
                        title=result["title"],
                        url=result["url"],
                        snippet=result["snippet"],
                        discovery_method="duckduckgo_html_search",
                        query=query,
                        raw=result,
                        graph_query=query_metadata.get(query),
                    )
                )
                if len(candidates) >= self.max_candidates:
                    break

        return SourceDiscoveryResult(
            candidates=candidates,
            queries_run=len(queries),
            errors=errors,
        )

    def _candidate_from_result(
        self,
        *,
        title: str,
        url: str,
        snippet: str,
        discovery_method: str,
        query: str,
        raw: dict[str, str],
        graph_query: GraphSearchQuery | None = None,
    ) -> DiscoveredSourceCandidate:
        graph = SourceGraph().enrich_source_candidate_payload(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "query": query,
                "discovery_method": discovery_method,
                "raw": {
                    "graph": {
                        "discovered_from": graph_query.discovered_from,
                        "discovery_depth": graph_query.discovery_depth,
                        "source_lineage": graph_query.source_lineage,
                    }
                    if graph_query
                    else {}
                },
            }
        )
        raw_payload: dict[str, Any] = dict(raw)
        raw_payload["graph"] = {
            "discovered_from": graph_query.discovered_from,
            "discovery_depth": graph_query.discovery_depth,
            "source_lineage": graph_query.source_lineage,
            "source_family": graph_query.source_family,
            "category_family": graph_query.category_family,
        } if graph_query else {
            "discovered_from": graph["discovered_from"],
            "discovery_depth": graph["discovery_depth"],
            "source_lineage": graph["source_lineage"],
        }
        return DiscoveredSourceCandidate(
            title=title,
            url=url,
            snippet=snippet,
            discovery_method=discovery_method,
            query=query,
            domain=urlparse(url).netloc.lower(),
            fetched_at=_utc_now(),
            raw=raw_payload,
            source_family=graph["source_family"],
            category_family=graph_query.category_family if graph_query else graph["category_family"],
            root_domain=graph["root_domain"],
            discovered_from=graph_query.discovered_from if graph_query else graph["discovered_from"],
            discovery_depth=graph_query.discovery_depth if graph_query else graph["discovery_depth"],
            source_lineage=graph_query.source_lineage if graph_query else graph["source_lineage"],
        )

    def _write_manual_queries(self, queries: list[str]) -> None:
        self.manual_query_output.parent.mkdir(parents=True, exist_ok=True)
        now = _utc_now()
        existing: set[tuple[str, str]] = set()
        if self.manual_query_output.exists():
            with self.manual_query_output.open("r", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    existing.add((row.get("query", ""), row.get("provider", "")))
        write_header = not self.manual_query_output.exists()
        with self.manual_query_output.open("a", encoding="utf-8", newline="") as handle:
            fieldnames = ["created_at", "provider", "query", "status", "notes"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            for query in queries:
                key = (query, self.provider_name)
                if key in existing:
                    continue
                writer.writerow(
                    {
                        "created_at": now,
                        "provider": self.provider_name,
                        "query": query,
                        "status": "manual_search_needed",
                        "notes": "No configured search provider API key. Run this query manually or add a provider later.",
                    }
                )

    def _search_duckduckgo(self, query: str) -> list[dict[str, str]]:
        url = f"{self.search_endpoint}?q={quote_plus(query)}"
        response = self.session.get(url, timeout=self.request_timeout_seconds)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        results: list[dict[str, str]] = []

        result_nodes = soup.select(".result")
        if not result_nodes:
            result_nodes = soup.select("div.web-result")

        for node in result_nodes:
            anchor = node.select_one("a.result__a") or node.find("a", href=True)
            if not anchor:
                continue
            raw_url = anchor.get("href", "")
            resolved_url = _resolve_duckduckgo_url(raw_url)
            parsed = urlparse(resolved_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            title = _clean_text(anchor.get_text(" ", strip=True))
            snippet_node = node.select_one(".result__snippet")
            snippet = _clean_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")
            if not title:
                continue
            results.append({"title": title[:240], "url": resolved_url, "snippet": snippet[:1200]})
            if len(results) >= self.results_per_query:
                break
        return results


def normalize_url(url: str) -> str:
    parsed = urlparse(str(url).strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _resolve_duckduckgo_url(raw_url: str) -> str:
    if raw_url.startswith("//"):
        raw_url = f"https:{raw_url}"
    parsed = urlparse(raw_url)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return unquote(query["uddg"][0])
    return raw_url


def _clean_text(text: str) -> str:
    return " ".join((text or "").split())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
