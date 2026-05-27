from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from autonomy.autonomous_worker import run_autonomous_queue_pass
from autonomy.completion_engine import run_completion_engine_pass
from autonomy.magic_money_scout import run_magic_money_scout
from execution.browser_execution import (
    build_browser_execution_plan,
    inspect_official_form,
    record_browser_execution_run,
    rows_for_browser_execution_candidates,
)
from execution.live_assist_session import build_live_assist_session
from storage.sqlite_store import SQLiteStore
from user_context.user_context_store import UserContextStore
from connectors.connector_status import apply_external_authorizations
from connectors.external_authorizations import external_authorization_rows


@dataclass(frozen=True)
class AutonomyPumpSummary:
    magic_lanes_scanned: int
    magic_queue_created: int
    completion_scanned: int
    completion_ready_for_approval: int
    autonomous_scanned: int
    autonomous_safe_packets: int
    forms_inspected: int
    forms_live_assist_ready: int
    forms_blocked: int
    queue_rows_updated: int
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_autonomy_pump(
    *,
    root_dir: Path,
    database_path: Path,
    control: dict[str, Any] | None = None,
    inspect_limit: int = 12,
) -> AutonomyPumpSummary:
    """Run the broadest safe local autonomy pass.

    This pass does not submit external forms. It does local/source/queue prep,
    maps official forms where reachable, and routes blockers or final approvals
    back into the existing queue.
    """

    control = control or {"enabled": True, "mode": "Open-To-Everything", "execution_mode": "Live Assist"}
    user_context = apply_external_authorizations(
        UserContextStore.for_root(root_dir).load(),
        external_authorization_rows(root_dir),
    )
    store = SQLiteStore(database_path)
    store.init_db()
    magic = run_magic_money_scout(store, promote_to_queue=True)
    store.refresh_exploration_queue()
    store.normalize_required_inputs()

    queue_rows_updated = 0
    forms_inspected = 0
    forms_live_assist_ready = 0
    forms_blocked = 0
    notes = [
        "No external submissions were performed.",
        "Payment, purchase, legal, tax, identity, wallet signing, and login gates remain approval/manual.",
    ]

    with _connect(database_path) as conn:
        completion = run_completion_engine_pass(
            conn,
            user_context,
            mode=str(control.get("execution_mode") or "Live Assist"),
            commit=True,
        )
        autonomy = run_autonomous_queue_pass(conn, root_dir, {**control, "enabled": True})

        candidates = rows_for_browser_execution_candidates(conn, limit=inspect_limit)
        for row in candidates:
            item = dict(row)
            plan = build_browser_execution_plan(item, user_context, str(control.get("execution_mode") or "Live Assist"))
            inspection = inspect_official_form(plan, user_context, timeout_seconds=7)
            cta_ready = bool(inspection.cta_links)
            forms_inspected += 1
            forms_live_assist_ready += int(inspection.can_live_assist or cta_ready)
            forms_blocked += int(not inspection.can_live_assist and not cta_ready)
            status = (
                "live_form_ready"
                if inspection.can_live_assist
                else "cta_path_ready"
                if cta_ready
                else "blocked_or_manual_inspection"
            )
            record_browser_execution_run(root_dir, plan, status, inspection.note)
            queue_rows_updated += _write_form_inspection(conn, item, inspection.to_dict(), user_context)

        conn.commit()

    return AutonomyPumpSummary(
        magic_lanes_scanned=magic.lanes_scanned,
        magic_queue_created=magic.queue_items_created,
        completion_scanned=completion.scanned,
        completion_ready_for_approval=completion.ready_for_approval,
        autonomous_scanned=autonomy.scanned,
        autonomous_safe_packets=autonomy.safe_packets_prepared,
        forms_inspected=forms_inspected,
        forms_live_assist_ready=forms_live_assist_ready,
        forms_blocked=forms_blocked,
        queue_rows_updated=queue_rows_updated,
        notes=notes + magic.notes[-3:] + completion.notes[-2:] + autonomy.notes[-2:],
    )


def _write_form_inspection(
    conn: Any,
    item: dict[str, Any],
    inspection: dict[str, Any],
    user_context: dict[str, Any],
) -> int:
    claim_queue_id = int(item["id"])
    now = datetime.now(timezone.utc).isoformat()
    current = conn.execute(
        "SELECT action_engine_json, execution_status, status FROM claim_queue WHERE id=?",
        (claim_queue_id,),
    ).fetchone()
    if not current:
        return 0

    details = _json_loads(current["action_engine_json"])
    details["browser_form_inspection"] = {
        "inspected_at": now,
        **inspection,
    }
    item_with_inspection = {**item, "action_engine_json": json.dumps(details, ensure_ascii=True, sort_keys=True)}
    live_session = build_live_assist_session(item_with_inspection, user_context, execution_mode="Live Assist")
    details["live_assist_session"] = live_session.to_dict()
    reachable = bool(inspection.get("reachable"))
    can_live_assist = bool(inspection.get("can_live_assist"))
    missing_fields = inspection.get("missing_fields") or []
    stop_flags = inspection.get("stop_flags") or []
    cta_links = inspection.get("cta_links") or []

    if can_live_assist and not missing_fields:
        execution_status = "Ready To Accept"
        status = "Ready to Accept"
        next_action = "Official form mapped. Review final approval packet before any final submit."
        human_input = ""
        completion = 92.0
    elif missing_fields:
        execution_status = "Paused Awaiting Input"
        status = str(current["status"] or "Needs Approval")
        next_action = "Add missing Vault fields: " + ", ".join(str(field) for field in missing_fields)
        human_input = next_action
        completion = 55.0
    elif stop_flags:
        execution_status = "Ready To Accept"
        status = "Ready to Accept"
        next_action = "Sensitive stop flags detected. Owner must review before continuing."
        human_input = "Owner final approval required: " + ", ".join(str(flag) for flag in stop_flags[:6])
        completion = 88.0
    elif reachable:
        execution_status = str(current["execution_status"] or "AI Working")
        status = str(current["status"] or "Needs Approval")
        if cta_links:
            first = cta_links[0] if isinstance(cta_links[0], dict) else {}
            next_action = "Official page reachable. Next claim/apply path found: " + str(first.get("label") or first.get("url") or "review detected CTA")
        else:
            next_action = "Official page reachable. No simple HTML form mapped; use browser/live assist review."
        human_input = ""
        completion = 76.0 if cta_links else 70.0
    else:
        execution_status = "Paused Awaiting Input"
        status = str(current["status"] or "Needs Approval")
        next_action = str(inspection.get("note") or "Official path could not be inspected.")
        human_input = next_action
        completion = 45.0

    conn.execute(
        """
        UPDATE claim_queue
        SET
            status=?,
            execution_status=?,
            estimated_completion_percent=MAX(COALESCE(estimated_completion_percent, 0), ?),
            human_input_needed=?,
            next_action=?,
            action_engine_json=?,
            last_execution_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            status,
            execution_status,
            completion,
            human_input,
            next_action,
            json.dumps(details, ensure_ascii=True, sort_keys=True),
            now,
            now,
            claim_queue_id,
        ),
    )
    return 1


def _connect(database_path: Path) -> Any:
    import sqlite3

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    return conn


def _json_loads(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}
