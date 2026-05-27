from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from execution.autofill_execution import build_autofill_execution_packet


@dataclass(frozen=True)
class LiveAssistSession:
    claim_queue_id: int
    title: str
    official_link: str
    selected_path: str
    mode: str
    ai_can_do_now: list[str]
    owner_must_do: list[str]
    safe_fields_to_prefill: list[str]
    missing_fields: list[str]
    connector_needed: str
    stop_flags: list[str]
    readiness: str
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_live_assist_session(
    item: dict[str, Any],
    user_context: dict[str, Any],
    *,
    execution_mode: str = "Live Assist",
) -> LiveAssistSession:
    inspection = _inspection_payload(item)
    packet = build_autofill_execution_packet(item, user_context)
    cta_links = inspection.get("cta_links") if isinstance(inspection, dict) else []
    selected_path = _selected_path(item, cta_links if isinstance(cta_links, list) else [])
    stop_flags = [str(flag) for flag in inspection.get("stop_flags", [])] if isinstance(inspection, dict) else []
    missing = sorted(set(packet.fields_missing + [str(field) for field in inspection.get("missing_fields", [])])) if isinstance(inspection, dict) else packet.fields_missing
    ai_can_do = [
        "open official public page",
        "inspect claim/apply path",
        "prepare safe autofill values",
        "stage final approval packet",
        "record proof/reference notes",
    ]
    if selected_path and selected_path != str(item.get("official_link") or item.get("url") or ""):
        ai_can_do.append("follow detected claim/apply CTA in Live Assist")
    owner_must = ["approve final submit before external submission"]
    if packet.connector_needed:
        owner_must.append(f"connect or approve {packet.connector_needed}")
    if missing:
        owner_must.append("add missing reusable Vault fields")
    if stop_flags:
        owner_must.append("clear sensitive stop flags manually")
    if packet.final_approval_required:
        owner_must.append(f"approve final action: {packet.final_action_type}")
    readiness = _readiness(packet.connector_needed, missing, stop_flags, packet.fields_ready, selected_path)
    return LiveAssistSession(
        claim_queue_id=int(item.get("id") or item.get("claim_queue_id") or 0),
        title=str(item.get("title") or "Untitled opportunity"),
        official_link=str(item.get("official_link") or item.get("url") or ""),
        selected_path=selected_path,
        mode=execution_mode,
        ai_can_do_now=ai_can_do,
        owner_must_do=_dedupe(owner_must),
        safe_fields_to_prefill=packet.fields_ready,
        missing_fields=missing,
        connector_needed=packet.connector_needed,
        stop_flags=stop_flags,
        readiness=readiness,
        next_action=_next_action(readiness, selected_path, packet.connector_needed, missing, stop_flags),
    )


def _inspection_payload(item: dict[str, Any]) -> dict[str, Any]:
    details = _json_loads(item.get("action_engine_json"))
    payload = details.get("browser_form_inspection", {})
    return payload if isinstance(payload, dict) else {}


def _selected_path(item: dict[str, Any], cta_links: list[Any]) -> str:
    for cta in cta_links:
        if isinstance(cta, dict) and cta.get("url"):
            return str(cta["url"])
    return str(item.get("official_link") or item.get("url") or "")


def _readiness(
    connector_needed: str,
    missing_fields: list[str],
    stop_flags: list[str],
    safe_fields: list[str],
    selected_path: str,
) -> str:
    if stop_flags:
        return "owner_review_required"
    if connector_needed:
        return "needs_connector"
    if missing_fields:
        return "needs_vault_fields"
    if selected_path and safe_fields:
        return "ready_for_live_assist"
    if selected_path:
        return "ready_for_public_review"
    return "needs_official_path"


def _next_action(
    readiness: str,
    selected_path: str,
    connector_needed: str,
    missing_fields: list[str],
    stop_flags: list[str],
) -> str:
    if readiness == "owner_review_required":
        return "Owner review required before continuing: " + ", ".join(stop_flags[:6])
    if readiness == "needs_connector":
        return f"Owner connects or authorizes {connector_needed}; AI resumes Live Assist."
    if readiness == "needs_vault_fields":
        return "Add Vault fields once: " + ", ".join(missing_fields[:8])
    if readiness == "ready_for_live_assist":
        return f"AI can open {selected_path}, prefill safe fields, then stop before final submit."
    if readiness == "ready_for_public_review":
        return f"AI can open {selected_path}, inspect the path, and build the final approval packet."
    return "Find or confirm the official claim/apply path."


def _json_loads(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
