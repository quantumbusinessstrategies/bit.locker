from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autofill.dependency_map import dependency_for_opportunity
from approval.submission_consent import SubmissionConsentStore
from connectors.connector_status import apply_external_authorizations
from connectors.external_authorizations import external_authorization_rows
from execution.action_engine import ActionEngine
from execution.autofill_execution import build_autofill_execution_packet
from execution.live_submit_worker import evaluate_live_submit
from user_context.user_context_store import UserContextStore


SAFE_PREP_STATUSES = {"Needs Approval", "Later"}
EXECUTION_STATUSES = {"Approved", "AI Working", "Submitted", "Ready to Accept"}
SENSITIVE_ACTIONS = {
    "identity_verification",
    "tax_action",
    "legal_agreement",
    "wallet_signing",
    "payment_authorization",
    "purchase",
}


@dataclass(frozen=True)
class AutonomousRunSummary:
    scanned: int
    safe_packets_prepared: int
    approved_items_advanced: int
    final_approval_ready: int
    live_submit_staged: int
    blocked_missing_input: int
    blocked_connector: int
    blocked_sensitive: int
    dry_run: bool
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_autonomous_queue_pass(conn: Any, root_dir: Path, control: dict[str, Any]) -> AutonomousRunSummary:
    enabled = bool(control.get("enabled"))
    execution_mode = str(control.get("execution_mode") or "Dry Run")
    mode = str(control.get("mode") or "Balanced")
    dry_run = execution_mode == "Dry Run"
    if not enabled:
        return AutonomousRunSummary(0, 0, 0, 0, 0, 0, 0, dry_run=True, notes=["AUTORUN is off."])

    context = apply_external_authorizations(
        UserContextStore.for_root(root_dir).load(),
        external_authorization_rows(root_dir),
    )
    consent_store = SubmissionConsentStore.for_root(root_dir)
    rows = _queue_rows(conn)
    stats = {
        "safe_packets_prepared": 0,
        "approved_items_advanced": 0,
        "final_approval_ready": 0,
        "live_submit_staged": 0,
        "blocked_missing_input": 0,
        "blocked_connector": 0,
        "blocked_sensitive": 0,
    }
    notes: list[str] = []
    for row in rows:
        item = dict(row)
        dependency = dependency_for_opportunity(item, context)
        packet = build_autofill_execution_packet(item, context)
        if dependency.missing_fields:
            stats["blocked_missing_input"] += 1
            continue
        if dependency.needs_connector:
            stats["blocked_connector"] += 1
            continue
        if packet.final_action_type in SENSITIVE_ACTIONS or dependency.manual_only:
            stats["blocked_sensitive"] += 1
            continue

        status = str(item.get("status") or "")
        if status == "Submitted":
            if execution_mode == "Live Submit With Final Approval":
                consent = consent_store.consent_for(int(item["id"]))
                result = evaluate_live_submit(item, consent)
                if result.allowed and not dry_run:
                    _write_live_submit_result(conn, int(item["id"]), result)
                    stats["live_submit_staged"] += 1
            elif not dry_run:
                result = ActionEngine(context).evaluate(item)
                _write_execution_result(conn, int(item["id"]), result)
                stats["approved_items_advanced"] += 1
            continue

        if status in EXECUTION_STATUSES:
            if not dry_run:
                result = ActionEngine(context).evaluate(item)
                _write_execution_result(conn, int(item["id"]), result)
            stats["approved_items_advanced"] += 1
            if packet.final_approval_required:
                stats["final_approval_ready"] += 1
            continue

        if status in SAFE_PREP_STATUSES and packet.can_prepare:
            stats["safe_packets_prepared"] += 1
            if packet.final_approval_required:
                stats["final_approval_ready"] += 1
            if not dry_run:
                _write_prepared_packet(conn, item, packet, mode)
            continue

    notes.append(f"Mode: {mode}; execution: {execution_mode}.")
    if dry_run:
        notes.append("Dry Run computed actions only; no queue rows were changed.")
    else:
        notes.append("Live Assist prepared safe local packets only; no external forms were submitted.")
    return AutonomousRunSummary(
        scanned=len(rows),
        dry_run=dry_run,
        notes=notes,
        **stats,
    )


def _queue_rows(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT cq.*, o.title, o.url
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
        ORDER BY cq.fastest_gain_score DESC, cq.highest_value_score DESC, cq.updated_at DESC
        LIMIT 500
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _write_live_submit_result(conn: Any, claim_queue_id: int, result: Any) -> None:
    now = _utc_now()
    conn.execute(
        """
        UPDATE claim_queue
        SET
            status=?,
            execution_status=?,
            next_action=?,
            ai_work_completed=COALESCE(NULLIF(?, ''), ai_work_completed),
            action_engine_json=?,
            last_execution_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            result.status,
            result.execution_status,
            result.next_action,
            result.note,
            _merged_action_engine_json(conn, claim_queue_id, result.payload_json),
            now,
            now,
            claim_queue_id,
        ),
    )


def _write_prepared_packet(conn: Any, item: dict[str, Any], packet: Any, mode: str) -> None:
    now = _utc_now()
    payload = {
        "autonomous_prepared_at": now,
        "mode": mode,
        "can_continue_alone": True,
        "execution_status": "Ready To Accept" if packet.final_approval_required else "AI Working",
        "claim_status": item.get("status") or "Needs Approval",
        "autofill": packet.to_dict(),
    }
    conn.execute(
        """
        UPDATE claim_queue
        SET
            execution_status=?,
            estimated_completion_percent=?,
            estimated_time=?,
            human_input_needed='',
            next_action=?,
            ai_work_completed=?,
            action_engine_json=?,
            last_execution_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            payload["execution_status"],
            88.0 if packet.final_approval_required else 76.0,
            "Ready now" if packet.final_approval_required else "AI-safe preparation ready",
            packet.next_safe_action,
            packet.prepared_summary,
            json.dumps(payload, ensure_ascii=True, sort_keys=True),
            now,
            now,
            int(item["id"]),
        ),
    )


def _write_execution_result(conn: Any, claim_queue_id: int, result: Any) -> None:
    now = _utc_now()
    conn.execute(
        """
        UPDATE claim_queue
        SET
            status=?,
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
            result.claim_status,
            result.execution_status,
            result.estimated_completion_percent,
            result.estimated_time,
            result.human_input_needed,
            result.next_action,
            result.ai_work_completed,
            _merged_action_engine_json(conn, claim_queue_id, result.action_engine_json),
            now,
            now,
            claim_queue_id,
        ),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merged_action_engine_json(conn: Any, claim_queue_id: int, new_json: str) -> str:
    """Preserve site-inspection evidence when later autonomy passes rewrite state."""

    try:
        incoming = json.loads(new_json or "{}")
    except json.JSONDecodeError:
        incoming = {"raw_action_engine_json": new_json}

    current_row = conn.execute(
        "SELECT action_engine_json FROM claim_queue WHERE id=?",
        (claim_queue_id,),
    ).fetchone()
    if not current_row:
        return json.dumps(incoming, ensure_ascii=True, sort_keys=True)
    try:
        existing = json.loads(_row_value(current_row, "action_engine_json") or "{}")
    except (json.JSONDecodeError, TypeError, KeyError):
        existing = {}

    for key in ["browser_form_inspection", "live_assist_session"]:
        if key in existing and key not in incoming:
            incoming[key] = existing[key]
    return json.dumps(incoming, ensure_ascii=True, sort_keys=True)


def _row_value(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        try:
            return row[0]
        except (TypeError, IndexError):
            return None
