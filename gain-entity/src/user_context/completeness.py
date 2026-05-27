from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from user_context.schema import (
    ACCOUNT_FIELDS,
    AUTOMATION_LIMIT_FIELDS,
    BUSINESS_FIELDS,
    CRYPTO_WALLET_FIELDS,
    PAYOUT_FIELDS,
    PREFERENCE_FIELDS,
    PROFILE_FIELDS,
    SHIPPING_FIELDS,
    truthy,
)


SECTION_WEIGHTS = {
    "profile": 15,
    "shipping": 20,
    "payouts": 20,
    "crypto_wallets": 10,
    "accounts": 20,
    "business": 10,
    "preferences": 10,
    "automation_limits": 5,
}

SECTION_LABELS = {
    "profile": "Profile",
    "shipping": "Shipping",
    "payouts": "Payouts",
    "crypto_wallets": "Crypto Wallets",
    "accounts": "Accounts / Connectors",
    "business": "Business / Startup Info",
    "preferences": "Preferences",
    "automation_limits": "Automation Limits",
}

CATEGORY_INPUTS = {
    "physical_goods": ["shipping"],
    "cash_rewards": ["payouts"],
    "crypto": ["crypto_wallets"],
    "gift_cards": ["profile"],
    "cloud_ai_credits": ["accounts"],
    "developer_credits": ["accounts"],
    "creator_programs": ["accounts", "payouts"],
    "affiliate_referral": ["accounts", "payouts"],
    "startup_credits": ["accounts", "business"],
    "class_actions": ["profile", "payouts"],
    "surveys": ["profile"],
    "beta_tests": ["profile", "accounts"],
    "local_pickup": ["profile"],
    "travel_events": ["profile"],
    "requires_purchase": ["automation_limits"],
}


@dataclass(frozen=True)
class SectionCompleteness:
    completion_percent: float
    missing_fields: list[str]
    usable_for_ai_work: bool
    sensitive_blockers: list[str]
    recommended_next_inputs: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UserContextCompleteness:
    automation_readiness_score: float
    sections: dict[str, SectionCompleteness]
    missing_inputs: list[str]
    highest_impact_field_to_add_next: str
    what_ai_can_already_do: list[str]
    what_ai_cannot_do_yet: list[str]
    blocked_opportunity_categories: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "automation_readiness_score": self.automation_readiness_score,
            "sections": {key: value.to_dict() for key, value in self.sections.items()},
            "missing_inputs": self.missing_inputs,
            "highest_impact_field_to_add_next": self.highest_impact_field_to_add_next,
            "what_ai_can_already_do": self.what_ai_can_already_do,
            "what_ai_cannot_do_yet": self.what_ai_cannot_do_yet,
            "blocked_opportunity_categories": self.blocked_opportunity_categories,
        }


def compute_completeness(context: dict[str, Any]) -> UserContextCompleteness:
    sections = {
        "profile": _score_required_fields(context, "profile", PROFILE_FIELDS, optional={"date_of_birth"}),
        "shipping": _score_required_fields(context, "shipping", SHIPPING_FIELDS, optional={"address_line_2"}),
        "payouts": _score_any_of(context, "payouts", PAYOUT_FIELDS),
        "crypto_wallets": _score_any_of(context, "crypto_wallets", CRYPTO_WALLET_FIELDS, optional={"wallet_notes"}),
        "accounts": _score_any_of(context, "accounts", ACCOUNT_FIELDS),
        "business": _score_any_of(context, "business", BUSINESS_FIELDS, optional={"ein_tax_placeholder"}),
        "preferences": _score_preferences(context),
        "automation_limits": _score_automation_limits(context),
    }
    weighted = 0.0
    total_weight = 0
    for section, weight in SECTION_WEIGHTS.items():
        weighted += sections[section].completion_percent * weight
        total_weight += weight
    score = round(weighted / total_weight, 1) if total_weight else 0.0
    missing_inputs = _all_missing(sections)
    return UserContextCompleteness(
        automation_readiness_score=score,
        sections=sections,
        missing_inputs=missing_inputs,
        highest_impact_field_to_add_next=_highest_impact_field(sections),
        what_ai_can_already_do=_ai_can_do(sections, context),
        what_ai_cannot_do_yet=_ai_cannot_do(sections),
        blocked_opportunity_categories=_blocked_categories(sections, context),
    )


def _score_required_fields(
    context: dict[str, Any],
    section: str,
    fields: list[str],
    optional: set[str] | None = None,
) -> SectionCompleteness:
    optional = optional or set()
    values = context.get(section, {})
    required_fields = [field for field in fields if field not in optional]
    missing = [f"{section}.{field}" for field in required_fields if not _has_value(values.get(field))]
    present = len(required_fields) - len(missing)
    percent = _percent(present, len(required_fields))
    return SectionCompleteness(
        completion_percent=percent,
        missing_fields=missing,
        usable_for_ai_work=not missing,
        sensitive_blockers=[],
        recommended_next_inputs=missing[:3],
    )


def _score_any_of(
    context: dict[str, Any],
    section: str,
    fields: list[str],
    optional: set[str] | None = None,
) -> SectionCompleteness:
    optional = optional or set()
    values = context.get(section, {})
    candidate_fields = [field for field in fields if field not in optional]
    present = [field for field in candidate_fields if _has_value(values.get(field))]
    missing = [] if present else [f"{section}.{field}" for field in candidate_fields]
    percent = 100.0 if present else 0.0
    return SectionCompleteness(
        completion_percent=percent,
        missing_fields=missing,
        usable_for_ai_work=bool(present),
        sensitive_blockers=[],
        recommended_next_inputs=missing[:3],
    )


def _score_preferences(context: dict[str, Any]) -> SectionCompleteness:
    values = context.get("preferences", {})
    if truthy(values.get("open_to_everything")):
        return SectionCompleteness(100.0, [], True, [], [])
    toggles = [field for field in PREFERENCE_FIELDS if field != "open_to_everything"]
    enabled = [field for field in toggles if truthy(values.get(field))]
    missing = [] if enabled else [f"preferences.{field}" for field in ["open_to_everything", "cash_rewards", "physical_goods"]]
    return SectionCompleteness(
        completion_percent=100.0 if enabled else 0.0,
        missing_fields=missing,
        usable_for_ai_work=bool(enabled),
        sensitive_blockers=[],
        recommended_next_inputs=missing[:3],
    )


def _score_automation_limits(context: dict[str, Any]) -> SectionCompleteness:
    values = context.get("automation_limits", {})
    required = ["allow_open_links", "allow_prepare_forms", "require_final_approval_for_sensitive"]
    present = [field for field in required if _has_value(values.get(field))]
    missing = [f"automation_limits.{field}" for field in required if field not in present]
    blockers = []
    if truthy(values.get("allow_submit_without_final_approval")):
        blockers.append("automation_limits.allow_submit_without_final_approval should remain false")
    if _number(values.get("max_out_of_pocket_spend")) > 0:
        blockers.append("automation_limits.max_out_of_pocket_spend allows paid paths")
    percent = _percent(len(present), len(required))
    if blockers:
        percent = min(percent, 50.0)
    return SectionCompleteness(
        completion_percent=percent,
        missing_fields=missing,
        usable_for_ai_work=not missing and not blockers,
        sensitive_blockers=blockers,
        recommended_next_inputs=(missing + blockers)[:3],
    )


def _all_missing(sections: dict[str, SectionCompleteness]) -> list[str]:
    missing: list[str] = []
    for section in SECTION_WEIGHTS:
        missing.extend(sections[section].missing_fields)
    return missing


def _highest_impact_field(sections: dict[str, SectionCompleteness]) -> str:
    candidates = []
    for section, weight in SECTION_WEIGHTS.items():
        details = sections[section]
        if details.usable_for_ai_work or not details.recommended_next_inputs:
            continue
        candidates.append((weight, details.recommended_next_inputs[0]))
    if not candidates:
        return "No high-impact reusable field is missing."
    return sorted(candidates, reverse=True)[0][1]


def _ai_can_do(sections: dict[str, SectionCompleteness], context: dict[str, Any]) -> list[str]:
    capabilities = []
    if sections["profile"].usable_for_ai_work:
        capabilities.append("reuse profile contact fields")
    if sections["shipping"].usable_for_ai_work:
        capabilities.append("prepare shipping-based physical-good claims")
    if sections["payouts"].usable_for_ai_work:
        capabilities.append("prepare payout destination instructions")
    if sections["crypto_wallets"].usable_for_ai_work:
        capabilities.append("prepare crypto wallet destination instructions")
    if sections["accounts"].usable_for_ai_work:
        capabilities.append("route connector/login-required items for owner approval")
    if sections["business"].usable_for_ai_work:
        capabilities.append("prepare startup and business-profile applications")
    automation = context.get("automation_limits", {})
    if truthy(automation.get("allow_open_links")):
        capabilities.append("open official links")
    if truthy(automation.get("allow_prepare_forms")):
        capabilities.append("prepare form drafts")
    if truthy(automation.get("allow_autofill")):
        capabilities.append("autofill safe reusable fields after approval")
    if truthy(automation.get("allow_connector_suggestions")):
        capabilities.append("suggest additional connectors")
    if truthy(automation.get("queue_low_risk_tasks_automatically")):
        capabilities.append("queue low-risk tasks automatically")
    if truthy(context.get("preferences", {}).get("open_to_everything")):
        capabilities.append("auto-discover broadly and queue safe actions")
    return capabilities or ["prepare general instructions and approval packets"]


def _ai_cannot_do(sections: dict[str, SectionCompleteness]) -> list[str]:
    blocked = []
    for section, label in SECTION_LABELS.items():
        if not sections[section].usable_for_ai_work:
            blocked.append(f"use {label} without more context")
    blocked.append("submit payment, legal, tax, identity, wallet-signing, purchase, or sensitive claims without final approval")
    return blocked


def _blocked_categories(sections: dict[str, SectionCompleteness], context: dict[str, Any]) -> list[str]:
    preferences = context.get("preferences", {})
    blocked = []
    for category, required_sections in CATEGORY_INPUTS.items():
        opted_in = truthy(preferences.get("open_to_everything")) or truthy(preferences.get(category))
        section_missing = any(not sections[section].usable_for_ai_work for section in required_sections)
        if opted_in and section_missing:
            blocked.append(category)
    return blocked


def _has_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value > 0
    return bool(str(value).strip())


def _percent(present: int, total: int) -> float:
    if total <= 0:
        return 100.0
    return round((present / total) * 100.0, 1)


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return 0.0
