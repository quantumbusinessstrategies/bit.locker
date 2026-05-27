from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from autofill.autofill_planner import plan_autofill_for_opportunity
from execution.autofill_execution import build_autofill_execution_packet


@dataclass(frozen=True)
class FinalApprovalPacket:
    claim_queue_id: int
    opportunity_title: str
    exact_fields_ai_prepared: list[str]
    prepared_value_preview: dict[str, str]
    source_url: str
    destination: str
    what_will_be_submitted: str
    what_user_must_verify: list[str]
    risk_safety_flags: list[str]
    final_action_type: str
    dry_run_only: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_final_approval_packet(row: dict[str, Any], user_context: dict[str, Any]) -> FinalApprovalPacket:
    plan = plan_autofill_for_opportunity(row, user_context)
    packet = build_autofill_execution_packet(row, user_context)
    action_json = _action_json(row)
    prepared_fragments = _prepared_fragments(action_json)
    fields = sorted(set(plan.fields_ai_can_autofill) | _prepared_field_set(prepared_fragments))
    value_preview = _prepared_value_preview(packet.value_preview, prepared_fragments)
    return FinalApprovalPacket(
        claim_queue_id=int(row.get("id") or 0),
        opportunity_title=str(row.get("title") or "Untitled opportunity"),
        exact_fields_ai_prepared=fields,
        prepared_value_preview=value_preview,
        source_url=str(row.get("official_link") or row.get("url") or ""),
        destination=_destination_text(row),
        what_will_be_submitted=_submission_text(row, fields),
        what_user_must_verify=_verification_items(row, fields),
        risk_safety_flags=_risk_flags(row, packet.final_action_type),
        final_action_type=packet.final_action_type,
        dry_run_only=True,
    )


def _destination_text(row: dict[str, Any]) -> str:
    parts = [
        str(row.get("destination_type") or "").strip(),
        str(row.get("asset_type") or "").strip(),
        str(row.get("asset_destination") or row.get("destination") or "").strip(),
    ]
    return " / ".join(part for part in parts if part) or "Not specified"


def _submission_text(row: dict[str, Any], fields: list[str]) -> str:
    instructions = str(row.get("claim_instructions") or "").strip()
    final_step = str(row.get("final_acceptance_step") or row.get("exact_next_step") or "").strip()
    field_text = ", ".join(fields) if fields else "No safe fields prepared"
    if instructions:
        return f"Prepared fields: {field_text}. Instructions: {instructions}"
    if final_step:
        return f"Prepared fields: {field_text}. Final step: {final_step}"
    return f"Prepared fields: {field_text}."


def _verification_items(row: dict[str, Any], fields: list[str]) -> list[str]:
    items = [
        "Confirm the official source URL is correct.",
        "Confirm the opportunity eligibility is truthful and current.",
        "Confirm prepared fields match what you want submitted.",
    ]
    if any(field.startswith("shipping.") for field in fields):
        items.append("Verify shipping destination before any final submit.")
    if any(field.startswith("payouts.") for field in fields):
        items.append("Verify payout destination before any final submit.")
    if str(row.get("safety_notes") or "").strip():
        items.append(str(row["safety_notes"]).strip())
    return _dedupe(items)


def _risk_flags(row: dict[str, Any], final_action_type: str) -> list[str]:
    flags = []
    risk = str(row.get("risk_level") or "").strip()
    if risk:
        flags.append(f"Risk level: {risk}")
    sensitive = _csv(row.get("sensitive_inputs"))
    for item in sensitive:
        flags.append(f"Sensitive blocker: {item}")
    if final_action_type != "final_submit":
        flags.append(f"Final action type: {final_action_type}")
    if _contains_any(row, ["payment authorization", "purchase", "tax", "identity verification", "wallet signing", "legal agreement"]):
        flags.append("Sensitive terms detected; owner-only final action may be required.")
    flags.append("Dry Run / Live Assist only; no external submission from this packet.")
    return _dedupe(flags)


def _action_json(row: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(str(row.get("action_engine_json") or "{}"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _prepared_fragments(action_json: dict[str, Any]) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    for value in [
        action_json.get("autofill"),
        action_json.get("details", {}).get("autofill") if isinstance(action_json.get("details"), dict) else {},
        action_json.get("completion_engine", {}).get("autofill_plan") if isinstance(action_json.get("completion_engine"), dict) else {},
        action_json.get("action_engine", {}).get("details", {}).get("autofill")
        if isinstance(action_json.get("action_engine"), dict)
        and isinstance(action_json.get("action_engine", {}).get("details"), dict)
        else {},
    ]:
        if isinstance(value, dict):
            fragments.append(value)
    return fragments


def _prepared_field_set(fragments: list[dict[str, Any]]) -> set[str]:
    fields: set[str] = set()
    for fragment in fragments:
        for key in ["fields_ready", "fields_ai_can_autofill", "safe_fields_to_prefill"]:
            values = fragment.get(key)
            if isinstance(values, list):
                fields.update(str(value) for value in values if value)
    return fields


def _prepared_value_preview(base: dict[str, str], fragments: list[dict[str, Any]]) -> dict[str, str]:
    preview = dict(base or {})
    for fragment in fragments:
        values = fragment.get("value_preview") or fragment.get("prepared_value_preview") or {}
        if isinstance(values, dict):
            preview.update({str(key): str(value) for key, value in values.items()})
    return preview


def _contains_any(row: dict[str, Any], terms: list[str]) -> bool:
    text = " ".join(str(row.get(key) or "") for key in ["safety_notes", "claim_instructions", "final_acceptance_step", "owner_input_required"]).lower()
    return any(term in text for term in terms)


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
