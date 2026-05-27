from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from autofill.autofill_planner import plan_autofill_for_opportunity
from connectors.connector_status import connector_status_map


@dataclass(frozen=True)
class OpportunityDependency:
    claim_queue_id: int
    opportunity: str
    required_fields: list[str]
    optional_fields: list[str]
    required_connectors: list[str]
    missing_inputs: list[str]
    connector_requirements: list[str]
    autofill_readiness: str
    execution_eligibility: str
    ready: bool
    missing_fields: bool
    needs_connector: bool
    ready_for_approval: bool
    manual_only: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


OPTIONAL_FIELDS = {
    "profile.phone",
    "shipping.address_line_2",
    "payouts.stripe_email",
    "payouts.cashapp",
    "payouts.venmo",
    "crypto_wallets.usdc_address",
    "business.website_domain",
    "business.company_description",
}


def dependency_for_opportunity(row: dict[str, Any], user_context: dict[str, Any]) -> OpportunityDependency:
    plan = plan_autofill_for_opportunity(row, user_context)
    required_fields = sorted(set(plan.fields_ai_can_autofill) | set(plan.fields_missing))
    optional_fields = sorted(field for field in OPTIONAL_FIELDS if _field_available(field, user_context) and field not in required_fields)
    required_connectors = _required_connectors(row)
    missing_connectors = _missing_connectors(required_connectors, user_context)
    final_required = bool(plan.final_approval_required)
    missing_fields = bool(plan.fields_missing)
    needs_connector = bool(missing_connectors or plan.connector_needed)
    ready = not missing_fields and not needs_connector and not final_required
    ready_for_approval = final_required and not missing_fields and not needs_connector
    manual_only = _manual_only(row, final_required, missing_fields, needs_connector)
    readiness = _readiness_label(ready, missing_fields, needs_connector, ready_for_approval, manual_only)
    return OpportunityDependency(
        claim_queue_id=int(row.get("id") or 0),
        opportunity=str(row.get("title") or "Untitled opportunity"),
        required_fields=required_fields,
        optional_fields=optional_fields,
        required_connectors=required_connectors,
        missing_inputs=sorted(set(plan.fields_missing)),
        connector_requirements=missing_connectors,
        autofill_readiness=readiness,
        execution_eligibility=_execution_eligibility(ready, ready_for_approval, manual_only),
        ready=ready,
        missing_fields=missing_fields,
        needs_connector=needs_connector,
        ready_for_approval=ready_for_approval,
        manual_only=manual_only,
    )


def dependency_map_for_opportunities(rows: list[dict[str, Any]], user_context: dict[str, Any]) -> list[OpportunityDependency]:
    return [dependency_for_opportunity(row, user_context) for row in rows]


def dependency_graph_summary(dependencies: list[OpportunityDependency]) -> dict[str, int]:
    return {
        "ready": sum(1 for item in dependencies if item.ready),
        "missing_fields": sum(1 for item in dependencies if item.missing_fields),
        "needs_connector": sum(1 for item in dependencies if item.needs_connector),
        "ready_for_approval": sum(1 for item in dependencies if item.ready_for_approval),
        "manual_only": sum(1 for item in dependencies if item.manual_only),
    }


def _required_connectors(row: dict[str, Any]) -> list[str]:
    text = _blob(row)
    connectors = []
    for key, label in [
        ("github", "GitHub"),
        ("google", "Google"),
        ("microsoft", "Microsoft"),
        ("apple", "Apple"),
        ("amazon", "Amazon"),
        ("paypal", "PayPal"),
        ("tiktok", "TikTok"),
    ]:
        if key in text:
            connectors.append(label)
    if "platform_login" in _csv(row.get("required_inputs")) or str(row.get("input_status") or "") == "needs_connect":
        connectors.append("Platform account")
    return _dedupe(connectors)


def _missing_connectors(required_connectors: list[str], user_context: dict[str, Any]) -> list[str]:
    statuses = connector_status_map(user_context)
    missing = []
    by_label = {status.label: status for status in statuses.values()}
    for connector in required_connectors:
        status = by_label.get(connector)
        if connector == "Platform account" and not _generic_platform_access_available(user_context):
            missing.append(connector)
        elif status and not status.connected:
            missing.append(connector)
    return _dedupe(missing)


def _generic_platform_access_available(user_context: dict[str, Any]) -> bool:
    accounts = user_context.get("accounts", {})
    if not isinstance(accounts, dict):
        return False
    if str(accounts.get("connection_status") or "").strip():
        return True
    return any(
        bool(accounts.get(key))
        for key in [
            "paypal_connected",
            "gmail_connected",
            "github_connected",
            "microsoft_connected",
            "amazon_connected",
            "apple_connected",
        ]
    )


def _manual_only(row: dict[str, Any], final_required: bool, missing_fields: bool, needs_connector: bool) -> bool:
    text = _blob(row)
    high_risk = any(
        term in text
        for term in [
            "identity_sensitive",
            "identity verification",
            "legal_attestation",
            "legal agreement",
            "wallet_signing",
            "payment_authorization",
            "purchase_required",
            "human verification",
            "captcha",
        ]
    ) or bool(re.search(r"\b(tax_info|tax|w-?9|1099)\b", text))
    return high_risk or (final_required and (missing_fields or needs_connector))


def _readiness_label(
    ready: bool,
    missing_fields: bool,
    needs_connector: bool,
    ready_for_approval: bool,
    manual_only: bool,
) -> str:
    if ready:
        return "Ready"
    if manual_only:
        return "Manual only"
    if ready_for_approval:
        return "Needs final approval"
    if needs_connector:
        return "Needs connector"
    if missing_fields:
        return "Missing fields"
    return "Manual only"


def _execution_eligibility(ready: bool, ready_for_approval: bool, manual_only: bool) -> str:
    if ready:
        return "AI-safe continuation"
    if ready_for_approval:
        return "Prepared; awaiting final approval"
    if manual_only:
        return "Manual only"
    return "Blocked until dependency resolved"


def _field_available(field: str, user_context: dict[str, Any]) -> bool:
    section, _, key = field.partition(".")
    values = user_context.get(section, {})
    if not isinstance(values, dict):
        return False
    return bool(str(values.get(key) or "").strip())


def _blob(row: dict[str, Any]) -> str:
    keys = [
        "status",
        "input_status",
        "acceptance_status",
        "destination_type",
        "asset_type",
        "asset_destination",
        "owner_input_required",
        "user_approval_needed",
        "what_user_must_approve",
        "required_user_action",
        "gain_type",
        "title",
        "what_this_gain_is",
        "real_asset_path",
        "destination",
        "expected_delivery_method",
        "exact_next_step",
        "claim_instructions",
        "final_acceptance_step",
        "official_link",
        "url",
        "required_inputs",
        "missing_inputs",
        "sensitive_inputs",
    ]
    return " ".join(str(row.get(key) or "") for key in keys).lower()


def _csv(value: Any) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
