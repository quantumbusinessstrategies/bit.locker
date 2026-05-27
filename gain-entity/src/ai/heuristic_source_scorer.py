from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from ai.source_scorer import normalize_source_score


OFFICIAL_DOMAINS = {
    "gov",
    "edu",
}

TRUSTED_GAIN_TERMS = [
    "claim",
    "apply",
    "application",
    "rebate",
    "refund",
    "settlement",
    "unclaimed",
    "benefit",
    "grant",
    "challenge",
    "prize",
    "credit",
    "startup",
    "developer",
    "sample",
    "product testing",
    "tester",
    "research",
    "survey",
    "reward",
    "payout",
    "gift card",
    "cash",
]

RISK_TERMS = [
    "casino",
    "gambling",
    "betting",
    "loan",
    "credit card",
    "deposit required",
    "buy now",
    "purchase required",
    "investment",
    "trading",
    "margin",
    "forex",
    "adult",
    "resale",
    "arbitrage",
    "job board",
]

LOGIN_TERMS = ["login", "sign in", "account required", "connect account"]
PAYMENT_TERMS = ["payment required", "purchase required", "credit card", "deposit required", "buy now"]


def heuristic_source_score(source_candidate: Any) -> dict[str, Any]:
    payload = source_candidate.to_dict() if hasattr(source_candidate, "to_dict") else dict(source_candidate)
    title = str(payload.get("title") or "")
    url = str(payload.get("url") or "")
    snippet = str(payload.get("snippet") or payload.get("summary") or "")
    query = str(payload.get("query") or "")
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    blob = f"{title} {url} {snippet} {query} {' '.join(str(tag) for tag in tags)}".lower()
    parsed = urlparse(url)
    domain = parsed.netloc.lower().removeprefix("www.")
    suffix = domain.rsplit(".", 1)[-1] if "." in domain else domain

    official = suffix in OFFICIAL_DOMAINS or any(term in domain for term in ["treasury", "irs", "ftc", "benefits"])
    gain_hits = sum(1 for term in TRUSTED_GAIN_TERMS if term in blob)
    risk_hits = [term for term in RISK_TERMS if term in blob]
    payment_required = any(term in blob for term in PAYMENT_TERMS)
    login_required = any(term in blob for term in LOGIN_TERMS)
    has_real_path = gain_hits >= 2 or official

    source_score = 4.0 + min(gain_hits, 5) * 0.8
    if official:
        source_score += 1.5
    if "official" in blob:
        source_score += 0.5
    if risk_hits:
        source_score -= 3.0
    if payment_required:
        source_score -= 2.0

    expected_gain = 4.0 + min(gain_hits, 6) * 0.7
    if any(term in blob for term in ["grant", "startup", "cloud", "developer", "settlement", "unclaimed"]):
        expected_gain += 1.0
    risk_level = "medium" if login_required else "low"
    if risk_hits or payment_required:
        risk_level = "high"

    return normalize_source_score(
        {
            "source_score_1_to_10": source_score,
            "expected_gain_potential_1_to_10": expected_gain,
            "risk_level": risk_level,
            "freshness_score_1_to_10": 7 if has_real_path else 5,
            "searchability_score_1_to_10": 8 if has_real_path else 5,
            "login_required": login_required,
            "payment_required": payment_required,
            "real_asset_path_strength_1_to_10": 7 if has_real_path else 4,
            "real_asset_path_signal": "heuristic safe-source path: " + _path_signal(blob),
            "likely_source_type": "configured_url",
            "auto_approve_recommended": not risk_hits and not payment_required and has_real_path,
            "reason": "Deterministic wide-net source triage from URL/title/snippet/tags.",
            "tags": _tags(blob, tags),
            "rejection_reasons": risk_hits,
        }
    )


def _path_signal(blob: str) -> str:
    for term in ["claim", "apply", "application", "rebate", "refund", "settlement", "sample", "reward", "credit"]:
        if term in blob:
            return term
    return "discoverable gain path"


def _tags(blob: str, existing: list[Any]) -> list[str]:
    tags = {str(tag).strip().lower() for tag in existing if str(tag).strip()}
    for term, tag in [
        ("settlement", "settlement"),
        ("refund", "refund"),
        ("rebate", "rebate"),
        ("sample", "free-physical-goods"),
        ("product testing", "product-testing"),
        ("survey", "surveys"),
        ("research", "paid-research"),
        ("startup", "startup-credits"),
        ("developer", "developer-credits"),
        ("crypto", "crypto-rewards"),
        ("gift card", "gift-cards"),
    ]:
        if term in blob:
            tags.add(tag)
    return sorted(tags)
