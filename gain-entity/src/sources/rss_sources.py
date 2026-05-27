from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class SourceCandidate:
    source_name: str
    source_type: str
    title: str
    url: str
    summary: str
    content_text: str
    published_at: str | None
    fetched_at: str
    tags: list[str]
    raw: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        basis = json.dumps(
            {
                "source_name": self.source_name,
                "source_type": self.source_type,
                "title": self.title,
                "url": self.url,
            },
            sort_keys=True,
        )
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True)
class SourceFetchResult:
    candidates: list[SourceCandidate]
    errors: list[str]


class SourceSwarm:
    def __init__(
        self,
        sources_config: dict[str, Any],
        max_candidates_per_source: int,
        request_timeout_seconds: int,
        user_agent: str,
    ) -> None:
        self.sources_config = sources_config
        self.max_candidates_per_source = max_candidates_per_source
        self.request_timeout_seconds = request_timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def fetch_all(self) -> SourceFetchResult:
        candidates: list[SourceCandidate] = []
        errors: list[str] = []

        for feed in self.sources_config.get("rss_feeds", []):
            if not feed.get("enabled", True):
                continue
            try:
                candidates.extend(self._fetch_rss(feed))
            except Exception as exc:  # noqa: BLE001 - source failures should not stop the swarm
                errors.append(f"RSS source {feed.get('name', feed.get('url'))}: {exc}")

        for page in self.sources_config.get("configured_urls", []):
            if not page.get("enabled", True):
                continue
            try:
                candidates.extend(self._fetch_configured_url(page))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Configured URL {page.get('name', page.get('url'))}: {exc}")

        for seed in self.sources_config.get("manual_seed_links", []):
            if not seed.get("enabled", True):
                continue
            try:
                candidates.append(self._fetch_manual_seed(seed))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Manual seed {seed.get('name', seed.get('url'))}: {exc}")

        future_web = self.sources_config.get("future_web_search", {})
        if future_web.get("enabled"):
            errors.append("future_web_search is enabled, but no provider implementation is configured yet.")

        future_inbox = self.sources_config.get("future_inbox_import", {})
        if future_inbox.get("enabled"):
            errors.append("future_inbox_import is enabled, but no approved inbox connector is configured yet.")

        return SourceFetchResult(candidates=self._dedupe(candidates), errors=errors)

    def source_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for source_type, key in [
            ("rss", "rss_feeds"),
            ("configured_url", "configured_urls"),
            ("manual_seed", "manual_seed_links"),
        ]:
            for source in self.sources_config.get(key, []):
                records.append(
                    {
                        "name": source.get("name", source.get("url", "Unnamed source")),
                        "source_type": source_type,
                        "url": source.get("url", ""),
                        "enabled": bool(source.get("enabled", True)),
                        "metadata": source,
                    }
                )
        return records

    def _fetch_rss(self, feed: dict[str, Any]) -> list[SourceCandidate]:
        response = self.session.get(feed["url"], timeout=self.request_timeout_seconds)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        fetched_at = _utc_now()
        candidates: list[SourceCandidate] = []

        for entry in parsed.entries[: self.max_candidates_per_source]:
            title = _clean_text(entry.get("title", "Untitled RSS item"))
            url = entry.get("link") or feed["url"]
            summary_html = entry.get("summary") or entry.get("description") or ""
            summary = _html_to_text(summary_html)
            published_at = (
                entry.get("published")
                or entry.get("updated")
                or _struct_time_to_iso(entry.get("published_parsed"))
                or _struct_time_to_iso(entry.get("updated_parsed"))
            )
            candidates.append(
                SourceCandidate(
                    source_name=feed.get("name", feed["url"]),
                    source_type="rss",
                    title=title,
                    url=url,
                    summary=summary[:1200],
                    content_text=f"{title}\n\n{summary}"[:5000],
                    published_at=published_at,
                    fetched_at=fetched_at,
                    tags=list(feed.get("tags", [])),
                    raw={
                        "feed_url": feed["url"],
                        "entry": _small_entry_payload(entry),
                        "bozo": bool(parsed.get("bozo", False)),
                    },
                )
            )
        return candidates

    def _fetch_configured_url(self, page: dict[str, Any]) -> list[SourceCandidate]:
        response = self.session.get(page["url"], timeout=self.request_timeout_seconds)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        title = _page_title(soup, page.get("name", page["url"]))
        text = _visible_text(soup)
        fetched_at = _utc_now()
        tags = list(page.get("tags", []))
        candidates = [
            SourceCandidate(
                source_name=page.get("name", page["url"]),
                source_type="configured_url",
                title=title,
                url=page["url"],
                summary=text[:1200],
                content_text=text[:5000],
                published_at=None,
                fetched_at=fetched_at,
                tags=tags,
                raw={"configured_url": page["url"]},
            )
        ]

        if page.get("extract_links", False):
            candidates.extend(self._extract_link_candidates(page, soup, title, fetched_at))

        return candidates[: self.max_candidates_per_source]

    def _extract_link_candidates(
        self,
        page: dict[str, Any],
        soup: BeautifulSoup,
        parent_title: str,
        fetched_at: str,
    ) -> list[SourceCandidate]:
        keywords = [word.lower() for word in self.sources_config.get("link_keywords", [])]
        base_url = page["url"]
        base_domain = urlparse(base_url).netloc
        only_same_domain = bool(page.get("only_same_domain", False))
        seen: set[str] = set()
        candidates: list[SourceCandidate] = []

        for anchor in soup.find_all("a", href=True):
            label = _clean_text(anchor.get_text(" ", strip=True))
            if len(label) < 4:
                continue
            href = urljoin(base_url, anchor["href"])
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"}:
                continue
            if only_same_domain and parsed.netloc != base_domain:
                continue
            keyword_blob = f"{label} {parsed.path} {parsed.query}".lower()
            if keywords and not any(keyword in keyword_blob for keyword in keywords):
                continue
            if href in seen:
                continue
            seen.add(href)
            candidates.append(
                SourceCandidate(
                    source_name=page.get("name", base_url),
                    source_type="configured_url_link",
                    title=label[:240],
                    url=href,
                    summary=f"Relevant link discovered on {parent_title}: {label}",
                    content_text=f"Parent page: {parent_title}\nDiscovered link: {label}\nURL: {href}",
                    published_at=None,
                    fetched_at=fetched_at,
                    tags=list(page.get("tags", [])),
                    raw={"parent_url": base_url, "anchor_text": label},
                )
            )
            if len(candidates) >= self.max_candidates_per_source:
                break
        return candidates

    def _fetch_manual_seed(self, seed: dict[str, Any]) -> SourceCandidate:
        fetched_at = _utc_now()
        try:
            response = self.session.get(seed["url"], timeout=self.request_timeout_seconds)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            title = _page_title(soup, seed.get("name", seed["url"]))
            text = _visible_text(soup)
        except Exception as exc:  # noqa: BLE001 - store the seed even if fetch is blocked
            title = seed.get("name", seed["url"])
            text = f"Manual seed could not be fetched automatically: {exc}"

        return SourceCandidate(
            source_name=seed.get("name", seed["url"]),
            source_type="manual_seed",
            title=title,
            url=seed["url"],
            summary=text[:1200],
            content_text=text[:5000],
            published_at=None,
            fetched_at=fetched_at,
            tags=list(seed.get("tags", [])),
            raw={"manual_seed": seed},
        )

    @staticmethod
    def _dedupe(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
        seen: set[str] = set()
        deduped: list[SourceCandidate] = []
        for candidate in candidates:
            if candidate.fingerprint in seen:
                continue
            seen.add(candidate.fingerprint)
            deduped.append(candidate)
        return deduped


def _visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return _clean_text(soup.get_text(" ", strip=True))


def _html_to_text(html: str) -> str:
    return _clean_text(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))


def _page_title(soup: BeautifulSoup, fallback: str) -> str:
    if soup.title and soup.title.string:
        return _clean_text(soup.title.string)
    heading = soup.find(["h1", "h2"])
    if heading:
        return _clean_text(heading.get_text(" ", strip=True))
    return fallback


def _clean_text(text: str) -> str:
    return " ".join((text or "").split())


def _struct_time_to_iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        return None


def _small_entry_payload(entry: Any) -> dict[str, Any]:
    return {
        "title": entry.get("title"),
        "link": entry.get("link"),
        "published": entry.get("published"),
        "updated": entry.get("updated"),
        "id": entry.get("id"),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
