from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from approval.final_approval_queue import final_action_type
from autofill.autofill_planner import plan_autofill_for_opportunity
from autofill.dependency_map import dependency_for_opportunity
from execution.action_engine import ActionEngine
from execution.autofill_execution import build_autofill_execution_packet
from routing.destination_router import DestinationRouter
from user_context.required_inputs import detect_required_inputs, result_payload


TERMINAL_STATUSES = {"Reject", "Rejected", "Dead End", "Paid Mode Later", "Received/Paid"}
OWNER_APPROVAL_STATUSES = {"Needs Approval", "Later", "Qualified", "Connect Needed", ""}
SENSITIVE_FINAL_ACTIONS = {
    "payment_authorization",
    "purchase",
    "legal_agreement",
    "tax_action",
    "identity_verification",
    "wallet_signing",
    "account_connection",
}


@dataclass(frozen=True)
class CompletionEngineSummary:
    scanned: int
    input_synced: int
    destination_synced: int
    dependency_synced: int
    safe_packets_prepared: int
    ready_for_approval: int
    ai_work_advanced: int
    blocked_missing_fields: int
    blocked_connectors: int
    blocked_sensitive: int
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_completion_engine_pass(
    conn: Any,
    user_context: dict[str, Any],
    *,
    mode: str = "Dry Run",
    limit: int = 500,
    commit: bool = False,
) -> CompletionEngineSummary:
    """Synchronize existing queue rows with the existing utility layers.

    This is intentionally a coordinator only. It does not discover, rank, approve,
    submit, or route around safety gates; it writes derived state from the current
    queue row, User Context, Required Inputs, Autofill Planner, Action Engine,
    Destination Router, and Final Approval detector back onto the existing queue.
    """

    rows = _active_rows(conn, limit)
    engine = ActionEngine(user_context)
    router = DestinationRouter()
    now = _utc_now()
    stats = {
        "input_synced": 0,
        "destination_synced": 0,
        "dependency_synced": 0,
        "safe_packets_prepared": 0,
        "ready_for_approval": 0,
        "ai_work_advanced": 0,
        "blocked_missing_fields": 0,
        "blocked_connectors": 0,
        "blocked_sensitive": 0,
    }

    for row in rows:
        item = dict(row)
        if str(item.get("status") or "") in {"Submitted", "Processing"}:
            stats["ai_work_advanced"] += 1
            continue
        required_payload = result_payload(detect_required_inputs(item, user_context))
        destination = router.route(item)
        autofill_plan = plan_autofill_for_opportunity(item, user_context)
        dependency = dependency_for_opportunity(item, user_context)
        packet = build_autofill_execution_packet(item, user_context)
        final_type = final_action_type({**item, **required_payload, **destination})
        action_result = engine.evaluate({**item, **required_payload, **destination})
        target = _target_state(
            item=item,
            required_payload=required_payload,
            destination=destination,
            dependency=dependency,
            packet=packet,
            final_type=final_type,
            action_result=action_result,
            mode=mode,
            now=now,
        )

        stats["input_synced"] += int(_input_changed(item, required_payload))
        stats["destination_synced"] += int(_destination_changed(item, destination))
        stats["dependency_synced"] += 1
        stats["safe_packets_prepared"] += int(target["completion_engine_event"] == "safe_packet_prepared")
        stats["ready_for_approval"] += int(target["completion_engine_event"] == "ready_for_final_approval")
        stats["ai_work_advanced"] += int(target["completion_engine_event"] == "ai_work_advanced")
        stats["blocked_missing_fields"] += int(dependency.missing_fields)
        stats["blocked_connectors"] += int(dependency.needs_connector)
        stats["blocked_sensitive"] += int(target["completion_engine_event"] == "blocked_sensitive")

        if commit:
            _write_target(conn, int(item["id"]), target)

    if commit:
        conn.commit()

    notes = [
        f"Mode: {mode}.",
        "External forms were not submitted.",
        "Queue/database state remains the source of truth.",
    ]
    if not commit:
        notes.append("Dry run only; no queue rows were changed.")
    else:
        notes.append("Safe derived queue state was synchronized from existing utility layers.")
    return CompletionEngineSummary(scanned=len(rows), notes=notes, **stats)


def _active_rows(conn: Any, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT cq.*, o.title, o.url, o.root_domain, o.source_name
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
        ORDER BY cq.fastest_gain_score DESC, cq.highest_value_score DESC, cq.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _target_state(
    *,
    item: dict[str, Any],
    required_payload: dict[str, Any],
    destination: dict[str, str],
    dependency: Any,
    packet: Any,
    final_type: str,
    action_result: Any,
    mode: str,
    now: str,
) -> dict[str, Any]:
    current_status = str(item.get("status") or "")
    event = "dependency_synced"
    status = current_status or "Needs Approval"
    execution_status = str(action_result.execution_status or item.get("execution_status") or "Execution Queue")
    completion = float(action_result.estimated_completion_percent or item.get("estimated_completion_percent") or 0)
    estimated_time = str(action_result.estimated_time or item.get("estimated_time") or "")
    human_input = str(action_result.human_input_needed or "")
    next_action = str(action_result.next_action or packet.next_safe_action or "")
    ai_completed = str(action_result.ai_work_completed or item.get("ai_work_completed") or "")

    if dependency.needs_connector:
        event = "blocked_connector"
        status = "Connect Needed"
        execution_status = "Paused Awaiting Input"
        human_input = "Connect or approve the required platform account, then AI can resume."
        next_action = packet.next_safe_action
        completion = max(completion, 35.0)
        estimated_time = "Paused until connector/login is resolved"
    elif dependency.missing_fields:
        event = "blocked_missing_fields"
        execution_status = "Paused Awaiting Input"
        human_input = "Add reusable Vault fields: " + ", ".join(dependency.missing_inputs)
        next_action = packet.next_safe_action
        completion = max(completion, 40.0)
        estimated_time = "Paused until reusable input is added"
    elif final_type in SENSITIVE_FINAL_ACTIONS or dependency.manual_only:
        event = "blocked_sensitive"
        execution_status = "Ready To Accept"
        status = "Ready to Accept" if current_status in OWNER_APPROVAL_STATUSES else status
        human_input = "Owner final approval/action required for sensitive step."
        next_action = packet.next_safe_action
        completion = max(completion, 88.0)
        estimated_time = "Ready now"
    elif packet.final_approval_required or dependency.ready_for_approval or final_type in {"final_submit", "sensitive_claim"}:
        event = "ready_for_final_approval"
        execution_status = "Ready To Accept"
        status = "Ready to Accept" if current_status in OWNER_APPROVAL_STATUSES | {"Approved", "AI Working"} else status
        human_input = ""
        next_action = packet.next_safe_action
        completion = max(completion, 88.0)
        estimated_time = "Ready now"
        ai_completed = _append_summary(ai_completed, packet.prepared_summary)
    elif packet.can_prepare:
        event = "safe_packet_prepared"
        if mode != "Dry Run" and current_status in OWNER_APPROVAL_STATUSES:
            status = "AI Working"
            execution_status = "AI Working"
        elif mode != "Dry Run":
            execution_status = "AI Working"
        completion = max(completion, 76.0)
        estimated_time = "AI-safe preparation ready"
        next_action = packet.next_safe_action
        ai_completed = _append_summary(ai_completed, packet.prepared_summary)
    elif action_result.can_continue_alone:
        event = "ai_work_advanced"

    details = _merge_action_details(
        item.get("action_engine_json"),
        {
            "completion_engine": {
                "synced_at": now,
                "event": event,
                "mode": mode,
                "dependency": dependency.to_dict(),
                "autofill_plan": autofill_plan_dict(packet),
                "final_action_type": final_type,
                "destination": destination,
                "approval_first": True,
                "external_submission": "not_performed",
            },
            "action_engine": _json_loads(action_result.action_engine_json),
        },
    )
    return {
        **required_payload,
        **destination,
        "status": status,
        "execution_status": execution_status,
        "estimated_completion_percent": round(max(0.0, min(100.0, completion)), 1),
        "estimated_time": estimated_time,
        "human_input_needed": human_input,
        "next_action": next_action,
        "ai_work_completed": ai_completed,
        "action_engine_json": json.dumps(details, ensure_ascii=True, sort_keys=True),
        "last_execution_at": now,
        "updated_at": now,
        "completion_engine_event": event,
    }


def autofill_plan_dict(packet: Any) -> dict[str, Any]:
    return packet.to_dict() if hasattr(packet, "to_dict") else {}


def _write_target(conn: Any, claim_queue_id: int, target: dict[str, Any]) -> None:
    conn.execute(
        """
        UPDATE claim_queue
        SET
            status=?,
            input_status=?,
            required_inputs=?,
            available_inputs=?,
            missing_inputs=?,
            sensitive_inputs=?,
            input_summary=?,
            destination_type=?,
            asset_type=?,
            acceptance_status=?,
            asset_destination=?,
            owner_input_required=?,
            ai_next_action=?,
            post_approval_action=?,
            received_tracking_note=?,
            execution_status=?,
            estimated_completion_percent=?,
            estimated_time=?,
            human_input_needed=?,
            next_action=?,
            ai_work_completed=COALESCE(NULLIF(?, ''), ai_work_completed),
            action_engine_json=?,
            last_execution_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            target["status"],
            target["input_status"],
            target["required_inputs"],
            target["available_inputs"],
            target["missing_inputs"],
            target["sensitive_inputs"],
            target["input_summary"],
            target["destination_type"],
            target["asset_type"],
            target["acceptance_status"],
            target["asset_destination"],
            target["owner_input_required"],
            target["ai_next_action"],
            target["post_approval_action"],
            target["received_tracking_note"],
            target["execution_status"],
            target["estimated_completion_percent"],
            target["estimated_time"],
            target["human_input_needed"],
            target["next_action"],
            target["ai_work_completed"],
            target["action_engine_json"],
            target["last_execution_at"],
            target["updated_at"],
            claim_queue_id,
        ),
    )


def _input_changed(item: dict[str, Any], required_payload: dict[str, Any]) -> bool:
    return any(str(item.get(key) or "") != str(required_payload.get(key) or "") for key in required_payload)


def _destination_changed(item: dict[str, Any], destination: dict[str, str]) -> bool:
    return any(str(item.get(key) or "") != str(value or "") for key, value in destination.items())


def _append_summary(existing: str, summary: str) -> str:
    existing = existing.strip()
    summary = summary.strip()
    if not summary:
        return existing
    if summary in existing:
        return existing
    return f"{existing} {summary}".strip()


def _merge_action_details(existing_json: Any, payload: dict[str, Any]) -> dict[str, Any]:
    existing = _json_loads(existing_json)
    existing.update(payload)
    return existing


def _json_loads(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {"previous_raw": str(value)}
    return parsed if isinstance(parsed, dict) else {"previous": parsed}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
