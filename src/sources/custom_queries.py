from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sources.search_queries import SearchQueryCatalog


def _custom_scan_queries_path(root_dir: Path) -> Path:
    return root_dir / "data" / "custom_scan_queries.json"


def load_custom_scan_queries(root_dir: Path) -> list[str]:
    path = _custom_scan_queries_path(root_dir)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(payload, list):
        return []
    return [str(q).strip() for q in payload if str(q).strip()]


def save_custom_scan_queries(root_dir: Path, queries: list[str]) -> None:
    path = _custom_scan_queries_path(root_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = [str(q).strip() for q in queries if str(q).strip()]
    path.write_text(json.dumps(cleaned, indent=2), encoding="utf-8")


def apply_custom_queries_to_rules(rules: dict[str, Any], custom_queries: list[str]) -> dict[str, Any]:
    """Prioritize the owner's personalized scan queries ahead of the default catalog.

    config/rules.yaml's source_discovery.queries (if an owner sets it directly) is treated
    as an intentional full override and left alone. Otherwise custom queries are prepended
    to the full default catalog so they always fall within query_limit for a run, while the
    broad "gains of all kinds" default scanning keeps running alongside them.
    """
    merged = dict(rules)
    discovery_cfg = dict(merged.get("source_discovery") or {})
    if discovery_cfg.get("queries"):
        return merged
    if not custom_queries:
        return merged
    full_default = [
        *SearchQueryCatalog.SIMPLE_DIRECT_GAIN_QUERIES,
        *SearchQueryCatalog.FAST_DIRECT_GAIN_QUERIES,
        *SearchQueryCatalog.DEFAULT_QUERIES,
    ]
    discovery_cfg["queries"] = [*custom_queries, *full_default]
    merged["source_discovery"] = discovery_cfg
    return merged
