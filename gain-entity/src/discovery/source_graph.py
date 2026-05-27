from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


EXPLORATION_CATEGORIES = [
    "cash_rewards",
    "paypal_rewards",
    "gift_cards",
    "fast_signup_bonuses",
    "rebates_refunds",
    "creator_incentives",
    "affiliate_programs",
    "free_physical_goods",
    "product_testing",
    "surveys_research",
    "user_testing",
    "beta_tests",
    "swag_rewards",
    "software_licenses",
    "ai_credits",
    "cloud_credits",
    "developer_credits",
    "crypto_rewards_low_risk",
    "grants_prizes",
    "local_assets_disabled_until_enabled",
    "tickets",
    "memberships",
    "other_assets",
]

EXPLORATION_QUERIES = {
    "cash_rewards": "official cash rewards signup bonus claim no purchase required",
    "paypal_rewards": "official PayPal reward payout bonus claim",
    "gift_cards": "official gift card reward claim free application",
    "fast_signup_bonuses": "official signup bonus instant reward no deposit required",
    "rebates_refunds": "official rebate refund claim form cash prepaid card open",
    "creator_incentives": "official creator fund incentive payout application",
    "affiliate_programs": "official affiliate program payout application no fee",
    "free_physical_goods": "official product testing free samples shipped application",
    "product_testing": "official product tester panel free full size products shipped application",
    "surveys_research": "paid online research study PayPal gift card application official",
    "user_testing": "paid website app user testing application PayPal official",
    "beta_tests": "official beta tester rewards gift card early access application",
    "swag_rewards": "official developer community swag rewards program application",
    "software_licenses": "official free software license developer startup program",
    "ai_credits": "official AI credits startup developer application",
    "cloud_credits": "official cloud credits startup developer application",
    "developer_credits": "official developer credits student startup pack application",
    "crypto_rewards_low_risk": "official crypto rewards no deposit educational claim",
    "grants_prizes": "official prize challenge grant award open application no fee",
    "local_assets_disabled_until_enabled": "official local free assets pickup community program",
    "tickets": "official free ticket giveaway claim application",
    "memberships": "official free membership trial credit application",
    "other_assets": "official free asset grant reward claim application",
}


@dataclass(frozen=True)
class GraphSearchQuery:
    query: str
    discovered_from: str
    discovery_depth: int
    source_lineage: str
    category_family: str
    source_family: str


class SourceGraph:
    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules = rules or {}
        self.max_depth = int(self.rules.get("max_discovery_depth", 3) or 3)

    def classify(self, *, url: str = "", title: str = "", text: str = "", source_type: str = "") -> dict[str, Any]:
        domain = _domain(url)
        root_domain = root_domain_from_url(url)
        blob = f"{domain} {root_domain} {title} {text} {source_type}".lower()

        source_family = "other_sources"
        category_family = "other_assets"

        if any(term in blob for term in ["classaction", "class-action", "settlement", "settlements", "claimdepot"]):
            source_family = "class_action_settlements"
            category_family = "cash_rewards"
        elif any(term in blob for term in ["unclaimed", "missingmoney", "naupa", "treasury hunt", "pbgc"]):
            source_family = "unclaimed_property"
            category_family = "other_assets"
        elif any(term in blob for term in ["irs.gov", "tax credit", "credits-deductions", "rebate finder"]):
            source_family = "tax_credits"
            category_family = "cash_rewards"
        elif any(term in blob for term in ["paypal"]):
            source_family = "paypal_rewards"
            category_family = "paypal_rewards"
        elif any(term in blob for term in ["gift card", "egift", "e-gift"]):
            source_family = "gift_card_rewards"
            category_family = "gift_cards"
        elif any(term in blob for term in ["rebate", "refund", "cash back", "cashback", "prepaid card"]):
            source_family = "rebates_refunds"
            category_family = "rebates_refunds"
        elif any(term in blob for term in ["affiliate", "partner program", "referral"]):
            source_family = "affiliate_programs"
            category_family = "affiliate_programs"
        elif any(term in blob for term in ["creator fund", "creator payout", "creator incentive"]):
            source_family = "creator_incentives"
            category_family = "creator_incentives"
        elif any(term in blob for term in ["product tester", "product testing", "review program", "tester panel"]):
            source_family = "product_testing"
            category_family = "product_testing"
        elif any(term in blob for term in ["free sample", "samples by mail", "freebie", "shipped", "free product"]):
            source_family = "free_physical_goods"
            category_family = "free_physical_goods"
        elif any(term in blob for term in ["survey", "research study", "focus group", "respondent", "prolific"]):
            source_family = "surveys_research"
            category_family = "surveys_research"
        elif any(term in blob for term in ["user testing", "website test", "app test", "usability test"]):
            source_family = "user_testing"
            category_family = "user_testing"
        elif any(term in blob for term in ["beta test", "beta tester", "early access"]):
            source_family = "beta_tests"
            category_family = "beta_tests"
        elif any(term in blob for term in ["swag", "merch", "sticker", "t-shirt", "tshirt"]):
            source_family = "swag_rewards"
            category_family = "swag_rewards"
        elif any(term in blob for term in ["software license", "license key", "free software", "saas credit"]):
            source_family = "software_licenses"
            category_family = "software_licenses"
        elif any(term in blob for term in ["ai credit", "openai", "anthropic", "model credit"]):
            source_family = "platform_credits"
            category_family = "ai_credits"
        elif any(term in blob for term in ["cloud credit", "aws", "azure", "google cloud", "cloud.google.com", "vultr"]):
            source_family = "platform_credits"
            category_family = "cloud_credits"
        elif any(term in blob for term in ["developer credit", "developer pack", "github education", "startupcredits"]):
            source_family = "platform_credits"
            category_family = "developer_credits"
        elif any(term in blob for term in ["signup bonus", "sign-up bonus", "welcome bonus"]):
            source_family = "signup_bonuses"
            category_family = "fast_signup_bonuses"
        elif any(term in blob for term in ["crypto", "token", "stablecoin", "wallet"]):
            source_family = "crypto_rewards"
            category_family = "crypto_rewards_low_risk"
        elif any(term in blob for term in ["local pickup", "pickup", "free local"]):
            source_family = "local_assets"
            category_family = "local_assets_disabled_until_enabled"
        elif "ticket" in blob:
            source_family = "tickets"
            category_family = "tickets"
        elif "membership" in blob:
            source_family = "memberships"
            category_family = "memberships"
        elif any(term in blob for term in ["grant", "challenge.gov", "prize challenge", "funding opportunity"]):
            source_family = "grants_and_prizes"
            category_family = "grants_prizes"

        return {
            "source_family": source_family,
            "category_family": category_family,
            "domain": domain,
            "root_domain": root_domain,
        }

    def enrich_opportunity_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = _loads(payload.get("raw") or payload.get("raw_json"))
        graph = raw.get("graph", {}) if isinstance(raw, dict) else {}
        classification = self.classify(
            url=str(payload.get("url") or ""),
            title=str(payload.get("title") or ""),
            text=" ".join(
                str(payload.get(key) or "")
                for key in ["summary", "content_text", "source_name", "source_type"]
            ),
            source_type=str(payload.get("source_type") or ""),
        )
        depth = int(graph.get("discovery_depth", _default_depth(payload.get("source_type"))) or 0)
        discovered_from = str(graph.get("discovered_from") or payload.get("source_name") or "seed_source")
        return {
            **classification,
            "discovered_from": discovered_from,
            "discovery_depth": min(depth, self.max_depth),
            "source_lineage": graph.get("source_lineage")
            or self.source_lineage(
                discovered_from=discovered_from,
                root_domain=classification["root_domain"],
                source_family=classification["source_family"],
                category_family=classification["category_family"],
                discovery_depth=depth,
            ),
        }

    def enrich_source_candidate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = _loads(payload.get("raw") or payload.get("raw_json"))
        graph = raw.get("graph", {}) if isinstance(raw, dict) else {}
        classification = self.classify(
            url=str(payload.get("url") or ""),
            title=str(payload.get("title") or ""),
            text=" ".join(str(payload.get(key) or "") for key in ["snippet", "query", "discovery_method"]),
            source_type=str(payload.get("discovery_method") or ""),
        )
        depth = int(graph.get("discovery_depth", 1) or 1)
        discovered_from = str(graph.get("discovered_from") or payload.get("query") or "source_discovery")
        return {
            **classification,
            "discovered_from": discovered_from,
            "discovery_depth": min(depth, self.max_depth),
            "source_lineage": graph.get("source_lineage")
            or self.source_lineage(
                discovered_from=discovered_from,
                root_domain=classification["root_domain"],
                source_family=classification["source_family"],
                category_family=classification["category_family"],
                discovery_depth=depth,
            ),
        }

    def source_lineage(
        self,
        *,
        discovered_from: str,
        root_domain: str,
        source_family: str,
        category_family: str,
        discovery_depth: int,
        parent_lineage: str | None = None,
    ) -> str:
        lineage = _loads(parent_lineage) if parent_lineage else []
        if not isinstance(lineage, list):
            lineage = []
        lineage.append(
            {
                "depth": discovery_depth,
                "from": discovered_from,
                "root_domain": root_domain,
                "source_family": source_family,
                "category_family": category_family,
            }
        )
        return json.dumps(lineage[-self.max_depth - 1 :], ensure_ascii=True)

    def recursive_queries(
        self,
        approved_sources: list[dict[str, Any]],
        exploration_items: list[dict[str, Any]] | None = None,
        limit: int = 8,
    ) -> list[GraphSearchQuery]:
        queries: list[GraphSearchQuery] = []
        seen: set[str] = set()

        for item in exploration_items or []:
            category = str(item.get("category_family") or "").strip()
            query = EXPLORATION_QUERIES.get(category)
            if not query or query.lower() in seen:
                continue
            seen.add(query.lower())
            queries.append(
                GraphSearchQuery(
                    query=query,
                    discovered_from="exploration_queue",
                    discovery_depth=1,
                    source_lineage=self.source_lineage(
                        discovered_from="exploration_queue",
                        root_domain="",
                        source_family="exploration",
                        category_family=category,
                        discovery_depth=1,
                    ),
                    category_family=category,
                    source_family="exploration",
                )
            )
            if len(queries) >= limit:
                return queries

        for source in approved_sources:
            url = str(source.get("url") or "")
            metadata = _loads(source.get("metadata"))
            score = metadata.get("score", {}) if isinstance(metadata, dict) else {}
            parent_lineage = metadata.get("source_lineage") if isinstance(metadata, dict) else None
            depth = int(metadata.get("discovery_depth", 0) if isinstance(metadata, dict) else 0)
            if depth >= self.max_depth:
                continue
            classification = self.classify(
                url=url,
                title=str(source.get("name") or ""),
                text=json.dumps(score, ensure_ascii=True) if score else "",
                source_type=str(source.get("source_type") or ""),
            )
            category = classification["category_family"]
            category_query = EXPLORATION_QUERIES.get(category, EXPLORATION_QUERIES["other_assets"])
            root_domain = classification["root_domain"]
            query = f"{category_query} -site:{root_domain}" if root_domain else category_query
            if query.lower() in seen:
                continue
            seen.add(query.lower())
            next_depth = depth + 1
            queries.append(
                GraphSearchQuery(
                    query=query,
                    discovered_from=url,
                    discovery_depth=next_depth,
                    source_lineage=self.source_lineage(
                        discovered_from=url,
                        root_domain=root_domain,
                        source_family=classification["source_family"],
                        category_family=category,
                        discovery_depth=next_depth,
                        parent_lineage=parent_lineage,
                    ),
                    category_family=category,
                    source_family=classification["source_family"],
                )
            )
            if len(queries) >= limit:
                break

        return queries


def root_domain_from_url(url: str) -> str:
    domain = _domain(url)
    if not domain:
        return ""
    parts = domain.split(".")
    if len(parts) <= 2:
        return domain
    if parts[-2] in {"co", "com", "org", "net", "gov", "ac"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _domain(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    netloc = parsed.netloc or parsed.path.split("/")[0]
    return netloc.lower().removeprefix("www.")


def _default_depth(source_type: Any) -> int:
    source_type_text = str(source_type or "").lower()
    if "link" in source_type_text:
        return 1
    if "search" in source_type_text:
        return 1
    return 0


def _loads(value: Any) -> Any:
    if not value:
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
