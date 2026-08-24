from __future__ import annotations

from collections import Counter
from typing import Any

from discovery.source_graph import EXPLORATION_CATEGORIES, EXPLORATION_QUERIES, SourceGraph


class DiversityGuard:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules = rules or {}
        self.max_family_percent = float(self.rules.get("max_same_source_family_percent", 20) or 20)
        self.max_domain_percent = float(self.rules.get("max_same_domain_percent", 15) or 15)
        self.exploration_weight = float(self.rules.get("exploration_weight", 0.35) or 0.35)
        self.exploitation_weight = float(self.rules.get("exploitation_weight", 0.65) or 0.65)
        self.boost_underrepresented = bool(self.rules.get("boost_underrepresented_categories", True))
        self.graph = SourceGraph(self.rules)

    def analyze(self, rows: list[Any]) -> dict[str, Any]:
        enriched = [self._with_graph_fields(row) for row in rows]
        total = len(enriched)
        source_counts = Counter(item["source_family"] for item in enriched if item.get("source_family"))
        category_counts = Counter(item["category_family"] for item in enriched if item.get("category_family"))
        domain_counts = Counter(item["root_domain"] for item in enriched if item.get("root_domain"))

        source_distribution = _distribution(source_counts, total, "source_family")
        category_distribution = _distribution(category_counts, total, "category_family")
        domain_distribution = _distribution(domain_counts, total, "root_domain")
        dominant_families = [
            item for item in source_distribution if item["percent"] > self.max_family_percent
        ]
        dominant_domains = [
            item for item in domain_distribution if item["percent"] > self.max_domain_percent
        ]
        represented = {item["category_family"] for item in enriched if item.get("category_family")}
        underrepresented = [
            category
            for category in EXPLORATION_CATEGORIES
            if category not in represented or _percent(category_counts.get(category, 0), total) < 5
        ]
        warnings = []
        for item in dominant_families:
            warnings.append(
                f"{item['source_family']} is {item['percent']:.1f}% of active intelligence results "
                f"(limit {self.max_family_percent:.1f}%)."
            )
        for item in dominant_domains:
            warnings.append(
                f"{item['root_domain']} is {item['percent']:.1f}% of active intelligence results "
                f"(limit {self.max_domain_percent:.1f}%)."
            )

        return {
            "total": total,
            "source_family_distribution": source_distribution,
            "category_family_distribution": category_distribution,
            "root_domain_distribution": domain_distribution,
            "dominant_families": dominant_families,
            "dominant_domains": dominant_domains,
            "underrepresented_categories": underrepresented,
            "exploration_queue": self.exploration_queue(underrepresented, category_counts, total),
            "warnings": warnings,
        }

    def adjust_rankings(self, ranked_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        analysis = self.analyze(ranked_items)
        family_percent = {
            item["source_family"]: item["percent"]
            for item in analysis["source_family_distribution"]
        }
        domain_percent = {
            item["root_domain"]: item["percent"]
            for item in analysis["root_domain_distribution"]
        }
        underrepresented = set(analysis["underrepresented_categories"])

        adjusted: list[dict[str, Any]] = []
        for item in ranked_items:
            enriched = self._with_graph_fields(item)
            base_priority = float(enriched.get("priority_score") or 0)
            family = str(enriched.get("source_family") or "other_sources")
            category = str(enriched.get("category_family") or "other_assets")
            root_domain = str(enriched.get("root_domain") or "")

            family_overage = max(0.0, family_percent.get(family, 0.0) - self.max_family_percent)
            domain_overage = max(0.0, domain_percent.get(root_domain, 0.0) - self.max_domain_percent)
            family_penalty = family_overage * self.exploitation_weight
            domain_penalty = domain_overage * self.exploitation_weight
            exploration_boost = 0.0
            if self.boost_underrepresented and category in underrepresented:
                exploration_boost = 100.0 * self.exploration_weight

            diversity_adjustment = round(exploration_boost - family_penalty - domain_penalty, 2)
            enriched["base_priority_score"] = round(base_priority, 2)
            enriched["diversity_adjustment"] = diversity_adjustment
            enriched["priority_score"] = round(base_priority + diversity_adjustment, 2)
            enriched["diversity_reason"] = self._reason(
                family=family,
                category=category,
                root_domain=root_domain,
                family_penalty=family_penalty,
                domain_penalty=domain_penalty,
                exploration_boost=exploration_boost,
            )
            existing_reason = str(enriched.get("ranking_reason") or "")
            enriched["ranking_reason"] = (
                f"{existing_reason}; diversity {enriched['diversity_reason']}"
                if existing_reason
                else enriched["diversity_reason"]
            )
            adjusted.append(enriched)

        return sorted(adjusted, key=lambda item: item["priority_score"], reverse=True)

    def exploration_queue(
        self,
        underrepresented: list[str],
        category_counts: Counter[str],
        total: int,
    ) -> list[dict[str, Any]]:
        queue = []
        for index, category in enumerate(underrepresented):
            current_percent = _percent(category_counts.get(category, 0), total)
            priority = round((100.0 - current_percent) * self.exploration_weight, 2)
            queue.append(
                {
                    "category_family": category,
                    "priority_score": priority,
                    "suggested_query": EXPLORATION_QUERIES.get(category, EXPLORATION_QUERIES["other_assets"]),
                    "reason": f"{category} is underrepresented at {current_percent:.1f}% of active results.",
                    "status": "Explore",
                    "rank": index + 1,
                }
            )
        return sorted(queue, key=lambda item: item["priority_score"], reverse=True)

    def _with_graph_fields(self, row: Any) -> dict[str, Any]:
        item = dict(row) if not isinstance(row, dict) else dict(row)
        if item.get("source_family") and item.get("category_family") and item.get("root_domain"):
            return item
        graph_fields = self.graph.enrich_opportunity_payload(item)
        for key, value in graph_fields.items():
            item.setdefault(key, value)
            if item.get(key) in {None, ""}:
                item[key] = value
        return item

    @staticmethod
    def _reason(
        *,
        family: str,
        category: str,
        root_domain: str,
        family_penalty: float,
        domain_penalty: float,
        exploration_boost: float,
    ) -> str:
        parts = []
        if family_penalty:
            parts.append(f"source family {family} penalty -{family_penalty:.1f}")
        if domain_penalty:
            parts.append(f"root domain {root_domain} penalty -{domain_penalty:.1f}")
        if exploration_boost:
            parts.append(f"underrepresented category {category} boost +{exploration_boost:.1f}")
        if not parts:
            return "no diversity adjustment"
        return ", ".join(parts)


def _distribution(counter: Counter[str], total: int, label_key: str) -> list[dict[str, Any]]:
    rows = []
    for key, count in counter.most_common():
        if not key:
            continue
        rows.append({label_key: key, "count": count, "percent": _percent(count, total)})
    return rows


def _percent(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((count / total) * 100.0, 2)
