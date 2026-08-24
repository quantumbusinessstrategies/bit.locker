from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from autofill.autofill_planner import plan_autofill_for_opportunity
from autofill.autofill_safety import final_approval_required_for


@dataclass(frozen=True)
class AutofillExecutionPacket:
    can_prepare: bool
    fields_ready: list[str]
    fields_missing: list[str]
    connector_needed: str
    final_approval_required: bool
    final_action_type: str
    next_safe_action: str
    prepared_summary: str
    value_preview: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_autofill_execution_packet(item: dict[str, Any], user_context: dict[str, Any]) -> AutofillExecutionPacket:
    plan = plan_autofill_for_opportunity(item, user_context)
    final_required = bool(plan.final_approval_required or final_approval_required_for(item) or _looks_like_submit(item))
    can_prepare = not plan.fields_missing and not plan.connector_needed and (
        bool(plan.fields_ai_can_autofill)
        or bool(item.get("official_link") or item.get("url") or item.get("exact_next_step"))
    )
    final_action_type = _final_action_type(item, final_required)
    next_safe_action = _next_safe_action(can_prepare, plan.connector_needed, plan.fields_missing, final_required)
    return AutofillExecutionPacket(
        can_prepare=can_prepare,
        fields_ready=plan.fields_ai_can_autofill,
        fields_missing=plan.fields_missing,
        connector_needed=plan.connector_needed,
        final_approval_required=final_required,
        final_action_type=final_action_type,
        next_safe_action=next_safe_action,
        prepared_summary=_prepared_summary(can_prepare, plan.fields_ai_can_autofill, final_required),
        value_preview=_safe_value_preview(plan.fields_ai_can_autofill, user_context),
    )


def safe_context_covers_owner_blocker(item: dict[str, Any], user_context: dict[str, Any]) -> bool:
    packet = build_autofill_execution_packet(item, user_context)
    if packet.connector_needed or packet.fields_missing:
        return False
    text = _blob(item)
    safe_blockers = [
        "shipping",
        "mailing address",
        "payout",
        "paypal",
        "stripe",
        "wallet address",
        "email",
        "phone",
        "business",
        "company",
        "startup",
    ]
    unsafe_blockers = [
        "password",
        "credential",
        "identity verification",
        "verify identity",
        "kyc",
        "tax",
        "w-9",
        "1099",
        "accept terms",
        "legal",
        "purchase",
        "payment authorization",
        "wallet signing",
        "sign transaction",
    ]
    return any(term in text for term in safe_blockers) and not any(term in text for term in unsafe_blockers)


def _next_safe_action(can_prepare: bool, connector_needed: str, missing: list[str], final_required: bool) -> str:
    if connector_needed:
        return f"Owner connects or logs into {connector_needed}; AI resumes with prepared safe field packet."
    if missing:
        return "Collect missing reusable vault fields, then prepare the safe field packet."
    if can_prepare and final_required:
        return "Prepare safe autofill packet and route to Final Approval Queue before submission."
    if can_prepare:
        return "Prepare safe autofill packet for live assist; do not submit without owner approval."
    return "Prepare claim instructions and wait for owner approval."


def _prepared_summary(can_prepare: bool, fields: list[str], final_required: bool) -> str:
    if not can_prepare:
        return "Autofill packet is not complete yet."
    suffix = " Final approval is still required before submission." if final_required else " Ready for AI-safe live assist."
    return f"Prepared safe autofill packet for {len(fields)} reusable field(s).{suffix}"


def _final_action_type(item: dict[str, Any], final_required: bool) -> str:
    text = _blob(item)
    if "wallet" in text and "sign" in text:
        return "wallet_signing"
    if "identity" in text or "kyc" in text:
        return "identity_verification"
    if re.search(r"\b(tax|w-?9|1099)\b", text):
        return "tax_action"
    if "purchase" in text or "payment authorization" in text:
        return "payment_authorization"
    if "accept terms" in text or "legal agreement" in text or "legal attestation" in text:
        return "legal_agreement"
    if final_required or _looks_like_submit(item):
        return "final_submit"
    return "safe_autofill_prepare"


def _looks_like_submit(item: dict[str, Any]) -> bool:
    text = _blob(item)
    return any(term in text for term in ["submit claim", "submit application", "final submit", "claim form", "application form"])


def _safe_value_preview(fields: list[str], context: dict[str, Any]) -> dict[str, str]:
    preview: dict[str, str] = {}
    for field in fields:
        value = _field_value(field, context)
        if value:
            preview[field] = _redact(value)
    return preview


def _field_value(field: str, context: dict[str, Any]) -> str:
    section, _, key = field.partition(".")
    values = context.get(section, {})
    if not isinstance(values, dict):
        return ""
    return str(values.get(key) or "").strip()


def _redact(value: str) -> str:
    if "@" in value:
        name, _, domain = value.partition("@")
        return f"{name[:2]}***@{domain}"
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


def _blob(item: dict[str, Any]) -> str:
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
    ]
    return " ".join(str(item.get(key) or "") for key in keys).lower()
