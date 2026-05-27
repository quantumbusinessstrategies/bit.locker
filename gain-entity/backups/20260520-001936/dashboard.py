from __future__ import annotations

import os
import json
import importlib
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from approval.final_approval_queue import (  # noqa: E402
    approval_result_note,
    approval_result_status,
    build_final_approval_queue,
    rows_for_final_approval,
)
from approval.submission_consent import SubmissionConsentStore, can_live_submit, new_consent  # noqa: E402
from autonomy.autonomous_worker import run_autonomous_queue_pass  # noqa: E402
from autofill.dependency_map import dependency_for_opportunity, dependency_graph_summary, dependency_map_for_opportunities  # noqa: E402
from autofill.autofill_planner import plan_autofill_for_opportunity, plan_autofill_for_opportunities, rows_for_autofill, summarize_autofill  # noqa: E402
from connectors.external_authorizations import (  # noqa: E402
    EXTERNAL_AUTHORIZATION_PROVIDERS,
    ExternalAuthorizationRecord,
    ExternalAuthorizationStore,
    external_authorization_rows,
)
from connectors.connector_status import connected_accounts, connector_statuses, missing_connectors  # noqa: E402
from storage.sqlite_store import SQLiteStore  # noqa: E402
from tracking.lifecycle_tracker import (  # noqa: E402
    TIME_WINDOWS as LIFECYCLE_TIME_WINDOWS,
    build_lifecycle_items,
    filter_lifecycle_items,
    lifecycle_summary,
    rows_for_lifecycle,
)
from tracking.received_paid import mark_received_paid, received_paid_rows  # noqa: E402
from intelligence import opportunity_ranker  # noqa: E402
from config import load_yaml_file  # noqa: E402
from discovery.diversity_guard import DiversityGuard  # noqa: E402
from execution.action_engine import ActionEngine  # noqa: E402
from execution.live_submit_worker import evaluate_live_submit  # noqa: E402
from security.credential_vault import CredentialVault, credential_vault_available  # noqa: E402
from user_context.action_center import (
    ACTION_BUCKETS,
    build_user_action_items,
    global_input_dependency_map,
    rows_for_action_center,
)  # noqa: E402
from user_context.completeness import SECTION_LABELS, compute_completeness  # noqa: E402
from user_context.redaction import redact_user_context  # noqa: E402
from user_context.required_inputs import input_status_badge  # noqa: E402
from user_context.schema import (
    ACCOUNT_FIELDS,
    AUTOMATION_LIMIT_FIELDS,
    BUSINESS_FIELDS,
    CRYPTO_WALLET_FIELDS,
    PAYOUT_FIELDS,
    PREFERENCE_FIELDS,
    PREFERENCE_PROFILE_MODES,
    PROFILE_FIELDS,
    SHIPPING_FIELDS,
    apply_open_to_everything_mode,
    apply_preference_profile,
    default_user_context,
)  # noqa: E402
from user_context.user_context_store import UserContextStore  # noqa: E402


DB_PATH = Path(os.getenv("DATABASE_PATH", ROOT_DIR / "data" / "gain_entity.sqlite3"))
AUTONOMY_STATUS_PATH = ROOT_DIR / "data" / "autonomy_status.json"
AUTORUN_CONTROL_PATH = ROOT_DIR / "data" / "autorun_control.json"
RULES_PATH = ROOT_DIR / "config" / "rules.yaml"
USER_CONTEXT_STORE = UserContextStore.for_root(ROOT_DIR)

AUTORUN_MODES = ["Conservative", "Balanced", "Aggressive", "Open-To-Everything"]
AUTORUN_EXECUTION_MODES = ["Dry Run", "Live Assist", "Live Submit With Final Approval"]
DEFAULT_AUTORUN_CONTROL = {"enabled": False, "mode": "Balanced", "execution_mode": "Dry Run"}
VAULT_FIELD_GROUPS = [
    "Basic Profile",
    "Shipping",
    "Payouts",
    "Crypto Wallets",
    "Accounts / Connectors",
    "Credentials / Submission Consent",
    "Business / Startup Info",
    "Preferences",
    "Automation Limits",
]

STATUS_ACTIONS = {
    "Approve": "Approved",
    "Reject": "Rejected",
    "Later": "Later",
    "Connect Needed": "Connect Needed",
    "Claim Submitted": "Submitted",
    "Ready to Accept": "Ready to Accept",
    "Accepted": "Accepted",
    "Received/Paid": "Received/Paid",
    "Dead End": "Dead End",
}

SOURCE_ACTIONS = {
    "Approve Source": "Approved",
    "Reject Source": "Rejected",
    "Later": "Later",
}


def _is_vault_route() -> bool:
    try:
        return str(st.query_params.get("page") or "").lower() == "vault"
    except Exception:  # noqa: BLE001
        return False


def show_standalone_vault_route() -> None:
    top_cols = st.columns([4, 1])
    top_cols[0].title("User Vault / Autofill Profile")
    try:
        top_cols[1].link_button("Back to Dashboard", "/", use_container_width=True)
    except Exception:  # noqa: BLE001
        top_cols[1].markdown("[Back to Dashboard](/)")

    if not DB_PATH.exists():
        st.info(f"No database found at {DB_PATH}. Run `python src/main.py` first.")
        return

    store = SQLiteStore(DB_PATH)
    store.init_db()
    store.normalize_required_inputs()
    store.normalize_execution_state()

    with connect() as conn:
        st.session_state["show_vault"] = True
        st.session_state["user_profile_vault_open"] = True
        if "vault_focus" not in st.session_state:
            st.session_state["vault_focus"] = "Credentials / Submission Consent"
            st.session_state["vault_field_group_selector"] = "Credentials / Submission Consent"
        show_user_profile_autofill_vault(conn)


def main() -> None:
    st.set_page_config(page_title="gain-entity", layout="wide")
    if _is_vault_route():
        show_standalone_vault_route()
        return

    header_cols = st.columns([5, 1.4])
    with header_cols[0]:
        st.title("gain-entity")
        st.caption("Self-Expanding Gain Acquisition Entity")

    if not DB_PATH.exists():
        st.info(f"No database found at {DB_PATH}. Run `python src/main.py` first.")
        return

    store = SQLiteStore(DB_PATH)
    store.init_db()
    store.normalize_required_inputs()
    store.normalize_execution_state()

    with connect() as conn:
        autonomy_summary = run_autonomous_queue_pass(conn, ROOT_DIR, load_autorun_control())
        conn.commit()
        with header_cols[1]:
            try:
                st.link_button("User Vault / Autofill Profile", "/?page=vault", use_container_width=True)
            except Exception:  # noqa: BLE001 - older Streamlit fallback
                st.button(
                    "User Vault / Autofill Profile",
                    use_container_width=True,
                    on_click=_set_vault_open,
                    args=("Overview",),
                    key="header_user_vault_button",
                )
            show_autorun_header_toggle()

        show_top_dashboard_metrics(conn)

        show_autorun_status_strip(conn)
        show_autonomous_work_summary(autonomy_summary)

        claim_status_control(conn)
        source_status_control(conn)

        st.markdown("**Gain Opportunities**")
        show_opportunities(conn)

        tabs = st.tabs(
            [
                "Gain Opportunities",
                "Claim Queue",
                "Source Candidates",
                "Discovery Graph",
                "Approved Sources",
                "Rejected Sources",
                "Needs Approval",
                "Approved / AI Work Continuing",
                "Execution Queue",
                "AI Working",
                "Paused Awaiting Input",
                "Ready To Accept",
                "Completed",
                "Destination Routing",
                "Ready to Accept",
                "Needs Connect",
                "Needs Shipping/Payout",
                "Received/Paid",
                "Lifecycle Tracker",
                "Received / Paid",
                "Dead Ends",
                "Opportunity Intelligence",
                "Autonomy Status",
                "User Action Center",
                "Connector + Autofill",
                "Final Approval Queue",
                "User Context",
                "Missing Inputs",
                "Ready for AI Work",
                "Final Approval Required",
            ]
        )

        with tabs[0]:
            show_opportunities(conn)

        with tabs[1]:
            show_queue(conn, order_by="cq.fastest_gain_score DESC, cq.highest_value_score DESC", limit=200)

        with tabs[2]:
            show_table(
                conn,
                """
                SELECT
                    id, status, title, url, domain, source_score_1_to_10,
                    expected_gain_potential_1_to_10, risk_level, login_required,
                    payment_required, real_asset_path_strength_1_to_10,
                    source_family, category_family, root_domain,
                    discovered_from, discovery_depth, source_lineage,
                    real_asset_path_signal, discovery_method, query, decision_reason,
                    created_at, updated_at
                FROM source_candidates
                ORDER BY updated_at DESC
                LIMIT 300
                """,
            )

        with tabs[3]:
            show_discovery_graph(conn)

        with tabs[4]:
            show_table(
                conn,
                """
                SELECT id, name, url, source_type, enabled, approved_at, updated_at
                FROM approved_sources
                ORDER BY updated_at DESC
                LIMIT 300
                """,
            )

        with tabs[5]:
            show_table(
                conn,
                """
                SELECT id, title, url, reason, created_at
                FROM rejected_sources
                ORDER BY created_at DESC
                LIMIT 300
                """,
            )

        with tabs[6]:
            show_queue(conn, statuses=["Needs Approval", "Connect Needed"], order_by="cq.fastest_gain_score DESC", limit=200)

        with tabs[7]:
            show_queue(conn, statuses=["Approved", "AI Work Started"], order_by="cq.updated_at DESC", limit=200)

        with tabs[8]:
            show_execution_statuses(conn, ["Execution Queue"], limit=200)

        with tabs[9]:
            show_execution_statuses(conn, ["AI Working"], limit=200)

        with tabs[10]:
            show_execution_statuses(conn, ["Paused Awaiting Input"], limit=200)

        with tabs[11]:
            show_execution_statuses(conn, ["Ready To Accept"], limit=200)

        with tabs[12]:
            show_execution_statuses(conn, ["Completed"], include_received=True, limit=200)

        with tabs[13]:
            show_destination_routing(conn)

        with tabs[14]:
            show_queue(conn, statuses=["Ready to Accept"], order_by="cq.fastest_gain_score DESC", limit=200)

        with tabs[15]:
            show_acceptance_statuses(conn, ["Needs Connect"], limit=200)

        with tabs[16]:
            show_acceptance_statuses(conn, ["Needs Shipping", "Needs Payout"], limit=200)

        with tabs[17]:
            show_table(conn, "SELECT * FROM received_log ORDER BY received_at DESC LIMIT 300")

        with tabs[18]:
            show_lifecycle_tracker(conn)

        with tabs[19]:
            show_received_paid_tracking(conn)

        with tabs[20]:
            show_table(
                conn,
                """
                SELECT d.*, o.title, o.url
                FROM dead_end_log d
                LEFT JOIN opportunities o ON o.id = d.opportunity_id
                ORDER BY d.created_at DESC
                LIMIT 300
                """,
            )
            st.markdown("**Claim Queue Dead Ends**")
            show_queue(conn, statuses=["Dead End"], order_by="cq.updated_at DESC", limit=200)

        with tabs[21]:
            show_opportunity_intelligence(conn)

        with tabs[22]:
            show_autonomy_status()

        with tabs[23]:
            show_user_action_center(conn)

        with tabs[24]:
            show_connector_autofill_readiness(conn)

        with tabs[25]:
            show_final_approval_queue(conn)

        with tabs[26]:
            show_user_context(conn)

        with tabs[27]:
            show_input_statuses(conn, ["missing_shipping", "missing_payout", "needs_connect", "blocked"], limit=200)

        with tabs[28]:
            show_input_statuses(conn, ["ready_for_ai_work"], limit=200)

        with tabs[29]:
            show_input_statuses(conn, ["final_approval_required"], limit=200)

        show_owner_setup_progress_panel(conn, include_status=False)
        show_top_level_user_action_center(conn)

        if st.session_state.get("show_vault") or st.session_state.get("user_profile_vault_open"):
            show_user_profile_autofill_vault(conn)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def load_metrics(conn: sqlite3.Connection) -> dict[str, int]:
    metrics = {}
    for table in [
        "opportunities",
        "claim_queue",
        "reject_log",
        "dead_end_log",
        "received_log",
        "source_candidates",
        "approved_sources",
        "rejected_sources",
    ]:
        metrics[table] = int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])
    return metrics


def show_top_dashboard_metrics(conn: sqlite3.Connection) -> None:
    context = USER_CONTEXT_STORE.load()
    completeness = compute_completeness(context)
    rows = rows_for_action_center(conn)
    dependencies = global_input_dependency_map(rows)
    metrics = load_metrics(conn)
    potential_unlocks = len({title for dependency in dependencies for title in dependency.blocks})

    cols = st.columns(4)
    cols[0].metric("Current Autonomy", f"{_current_autonomy_percent(rows, completeness):.1f}%")
    cols[1].metric("Context Completeness", f"{completeness.automation_readiness_score:.1f}%")
    cols[2].metric("Potential Unlocks", f"{potential_unlocks} opportunities")
    cols[3].metric("Received/Paid", metrics["received_log"])


def dashboard_rules() -> dict[str, object]:
    try:
        return load_yaml_file(RULES_PATH)
    except FileNotFoundError:
        return {}


def rank_opportunities(
    rows: list[object],
    time_window: str,
    rules: dict[str, object],
) -> list[dict[str, object]]:
    try:
        return opportunity_ranker.rank_opportunities(rows, time_window, rules)
    except TypeError:
        reloaded_ranker = importlib.reload(opportunity_ranker)
        return reloaded_ranker.rank_opportunities(rows, time_window, rules)


def show_autorun_header_toggle() -> None:
    control = load_autorun_control()
    enabled = bool(control.get("enabled"))
    st.caption("AUTORUN")
    new_enabled = st.toggle(
        "ON" if enabled else "OFF",
        value=enabled,
        key="autorun_header_toggle",
        label_visibility="visible",
    )
    if new_enabled != enabled:
        control["enabled"] = new_enabled
        save_autorun_control(control)


def show_autorun_status_strip(conn: sqlite3.Connection) -> None:
    control = load_autorun_control()
    enabled = bool(control.get("enabled"))
    current_mode = str(control.get("mode") or "Balanced")
    if current_mode not in AUTORUN_MODES:
        current_mode = "Balanced"
    current_execution_mode = str(control.get("execution_mode") or "Dry Run")
    if current_execution_mode not in AUTORUN_EXECUTION_MODES:
        current_execution_mode = "Dry Run"

    status = autorun_status_summary(conn)
    st.markdown("**AUTORUN STATUS**")
    cols = st.columns([1, 1.3, 1.8, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9])
    cols[0].metric("Autorun", "ON" if enabled else "OFF")
    selected_mode = cols[1].selectbox(
        "Strategy",
        options=AUTORUN_MODES,
        index=AUTORUN_MODES.index(current_mode),
        key="autorun_mode_select",
    )
    selected_execution_mode = cols[2].selectbox(
        "Execution",
        options=AUTORUN_EXECUTION_MODES,
        index=AUTORUN_EXECUTION_MODES.index(current_execution_mode),
        key="autorun_execution_mode_select",
    )
    if selected_mode != current_mode:
        control["mode"] = selected_mode
        save_autorun_control(control)
    if selected_execution_mode != current_execution_mode:
        control["execution_mode"] = selected_execution_mode
        save_autorun_control(control)
    cols[3].metric("Scanning", status["ai_currently_scanning"])
    cols[4].metric("Preparing", status["ai_preparing"])
    cols[5].metric("Executing", status["ai_executing"])
    cols[6].metric("Approval", status["waiting_approval"])
    cols[7].metric("Paused", status["paused"])
    cols[8].metric("Paid", status["received_paid"])

    st.caption("Execution modes: Dry Run | Live Assist | Live Submit With Final Approval")
    st.caption(_autorun_execution_mode_text(selected_execution_mode))
    st.caption(
        "Passwords may only be stored in the separate encrypted Credential Vault. Never store seed phrases, "
        "private keys, bank credentials, SSNs, identity docs, or wallet signing keys. Sensitive final actions "
        "remain approval-gated."
    )
    if status["sensitive_blockers"]:
        st.caption(f"{status['sensitive_blockers']} sensitive/high-risk items are waiting for final approval.")
    show_current_ai_task_card(conn)
    show_autorun_blocked_reasons(conn)


def show_autonomous_work_summary(summary: object) -> None:
    data = summary.to_dict() if hasattr(summary, "to_dict") else {}
    if not data or not int(data.get("scanned", 0) or 0):
        return
    with st.expander("Autonomous Work Pass", expanded=False):
        cols = st.columns(6)
        cols[0].metric("Scanned", data.get("scanned", 0))
        cols[1].metric("Safe Packets", data.get("safe_packets_prepared", 0))
        cols[2].metric("Advanced", data.get("approved_items_advanced", 0))
        cols[3].metric("Final Approval Ready", data.get("final_approval_ready", 0))
        cols[4].metric("Live Submit Staged", data.get("live_submit_staged", 0))
        cols[5].metric("Needs Connect", data.get("blocked_connector", 0))
        if data.get("blocked_missing_input"):
            st.caption(f"Missing-input blockers held: {data['blocked_missing_input']}")
        if data.get("blocked_sensitive"):
            st.caption(f"Sensitive/manual blockers held: {data['blocked_sensitive']}")
        for note in data.get("notes", []):
            st.caption(str(note))


def load_autorun_control() -> dict[str, object]:
    if not AUTORUN_CONTROL_PATH.exists():
        return dict(DEFAULT_AUTORUN_CONTROL)
    try:
        payload = json.loads(AUTORUN_CONTROL_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_AUTORUN_CONTROL)
    control = dict(DEFAULT_AUTORUN_CONTROL)
    if isinstance(payload, dict):
        control["enabled"] = bool(payload.get("enabled"))
        mode = str(payload.get("mode") or control["mode"])
        control["mode"] = mode if mode in AUTORUN_MODES else control["mode"]
        execution_mode = str(payload.get("execution_mode") or control["execution_mode"])
        control["execution_mode"] = (
            execution_mode if execution_mode in AUTORUN_EXECUTION_MODES else control["execution_mode"]
        )
    return control


def save_autorun_control(control: dict[str, object]) -> None:
    AUTORUN_CONTROL_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTORUN_CONTROL_PATH.write_text(json.dumps(control, indent=2), encoding="utf-8")


def _autorun_execution_mode_text(execution_mode: str) -> str:
    if execution_mode == "Dry Run":
        return (
            "Dry Run: simulate required inputs, autofill plan, next actions, and final approval screen. "
            "No external forms are submitted."
        )
    if execution_mode == "Live Assist":
        return (
            "Live Assist: open official links and prepare or fill safe fields where possible. "
            "Do not submit."
        )
    if execution_mode == "Live Submit With Final Approval":
        return "Live Submit With Final Approval: submit only after explicit final user approval."
    return "Approval-first execution mode. Sensitive or high-risk actions remain blocked."


def show_current_ai_task_card(conn: sqlite3.Connection) -> None:
    task = current_ai_task(conn)
    if not task:
        return
    st.markdown("**CURRENT AI TASK**")
    with st.container():
        cols = st.columns([3, 1.2, 1.6, 2.4])
        cols[0].markdown(f"**{task['title']}**")
        cols[1].metric("Phase", str(task["phase"]).title())
        cols[2].write(f"Source/domain: {task['source_domain']}")
        cols[3].write(f"Next required action: {task['next_required_action']}")

        cols = st.columns([2, 1.4, 2, 1.4])
        cols[0].write(f"Missing input: {task['missing_input']}")
        cols[1].write(f"Final approval required: {task['final_approval_required']}")
        cols[2].write(f"Estimated unlock impact: {task['estimated_unlock_impact']}")
        cols[3].write(f"Confidence: {task['confidence_level']}")


def current_ai_task(conn: sqlite3.Connection) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            cq.execution_status,
            cq.input_status,
            cq.required_inputs,
            cq.missing_inputs,
            cq.sensitive_inputs,
            cq.owner_input_required,
            cq.ai_next_action,
            cq.next_action,
            cq.exact_next_step,
            cq.final_acceptance_step,
            cq.expected_value_usd,
            cq.probability_score_1_to_10,
            cq.fastest_gain_score,
            cq.highest_value_score,
            o.title,
            o.url,
            o.domain,
            o.root_domain,
            o.source_name
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
        ORDER BY
            CASE
                WHEN cq.execution_status = 'AI Working' THEN 0
                WHEN cq.input_status = 'ready_for_ai_work' THEN 1
                WHEN cq.input_status = 'final_approval_required' THEN 2
                WHEN cq.execution_status = 'Paused Awaiting Input' THEN 3
                ELSE 4
            END,
            COALESCE(cq.fastest_gain_score, 0) DESC,
            COALESCE(cq.highest_value_score, 0) DESC,
            cq.updated_at DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return {}

    item = dict(row)
    phase = _current_task_phase(item)
    missing_input = str(item.get("missing_inputs") or "").strip() or "None detected"
    sensitive = str(item.get("sensitive_inputs") or "").strip()
    final_required = "yes" if sensitive or str(item.get("input_status") or "") == "final_approval_required" else "no"
    next_required_action = (
        str(item.get("owner_input_required") or item.get("ai_next_action") or item.get("next_action") or item.get("exact_next_step") or "")
        .strip()
        or "Continue AI-safe preparation."
    )
    source_domain = str(item.get("root_domain") or item.get("domain") or item.get("source_name") or item.get("url") or "Unknown")
    return {
        "title": str(item.get("title") or "Untitled opportunity"),
        "phase": phase,
        "source_domain": source_domain,
        "next_required_action": next_required_action,
        "missing_input": missing_input,
        "final_approval_required": final_required,
        "estimated_unlock_impact": _current_task_unlock_impact(item),
        "confidence_level": _confidence_label(item),
    }


def _current_task_phase(item: dict[str, object]) -> str:
    execution_status = str(item.get("execution_status") or "")
    input_status = str(item.get("input_status") or "")
    status = str(item.get("status") or "")
    if execution_status == "AI Working":
        return "executing"
    if input_status == "ready_for_ai_work" or execution_status == "Execution Queue":
        return "preparing"
    if input_status == "final_approval_required" or status in {"Needs Approval", "Connect Needed"}:
        return "awaiting approval"
    if input_status in {"missing_shipping", "missing_payout", "needs_connect", "blocked"}:
        return "awaiting input"
    if execution_status == "Paused Awaiting Input":
        return "paused"
    if status in {"Completed", "Accepted", "Received/Paid"}:
        return "completed"
    if status in {"Found", "Needs Review"}:
        return "vetting"
    return "scanning"


def _current_task_unlock_impact(item: dict[str, object]) -> str:
    value = _safe_float(item.get("expected_value_usd"))
    probability = _safe_float(item.get("probability_score_1_to_10"))
    if probability <= 0:
        probability = _safe_float(item.get("probability_score"))
    return f"+1 opportunity, +${value:,.0f}/month, confidence basis {probability:.1f}/10"


def show_autorun_blocked_reasons(conn: sqlite3.Connection) -> None:
    blockers = autorun_blocked_reasons(conn)
    if not blockers:
        return
    st.markdown("**BLOCKED:**")
    for index, blocker in enumerate(blockers[:8]):
        with st.container():
            cols = st.columns([2, 3.2, 1.2, 1.3, 1.5])
            cols[0].markdown(f"**{blocker['reason']}**")
            cols[1].write(f"Required action: {blocker['required_action']}")
            cols[2].metric("Unlocks", int(blocker["opportunities"]))
            cols[3].metric("Autonomy", f"+{float(blocker['autonomy_delta']):.1f}%")
            cols[4].write(f"Confidence: {blocker['confidence_level']}")
            affected = blocker.get("affected_opportunities") or []
            if affected:
                st.caption("Affected opportunities: " + "; ".join(str(item) for item in affected[:6]))
            st.caption(f"Source of calculation: {blocker.get('source_of_calculation', 'Dependency graph from current queue rows')}")


def autorun_blocked_reasons(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = rows_for_action_center(conn)
    context = USER_CONTEXT_STORE.load()
    dependencies = dependency_map_for_opportunities(rows, context)
    total_rows = max(1, len(rows))
    grouped: dict[str, dict[str, object]] = {}
    for row, dependency in zip(rows, dependencies):
        for reason in _blocked_reasons_for_dependency(dependency):
            item = grouped.setdefault(
                reason,
                {
                    "reason": reason,
                    "required_action": _blocked_required_action(reason, ""),
                    "opportunities": 0,
                    "monthly_gain": 0.0,
                    "autonomy_delta": 0.0,
                    "unlock_score": 0.0,
                    "confidence_level": _blocked_confidence_label(reason),
                    "affected_opportunities": [],
                    "source_of_calculation": "Dependency graph from current queue rows",
                },
            )
            item["opportunities"] = int(item["opportunities"]) + 1
            item["monthly_gain"] = float(item["monthly_gain"]) + _safe_float(row.get("expected_value_usd"))
            item["autonomy_delta"] = min(100.0, float(item["autonomy_delta"]) + (1 / total_rows * 100.0))
            item["unlock_score"] = float(item["unlock_score"]) + _dependency_graph_score(row, dependency)
            affected = item.setdefault("affected_opportunities", [])
            if isinstance(affected, list):
                affected.append(f"#{row.get('id')} {row.get('title') or 'Untitled opportunity'}")

    for reason, query in _non_dependency_blocker_queries().items():
        if reason in grouped:
            continue
        count = _count_sql(conn, query)
        if count <= 0:
            continue
        grouped[reason] = {
            "reason": reason,
            "required_action": _blocked_required_action(reason, ""),
            "opportunities": count,
            "monthly_gain": 0.0,
            "autonomy_delta": min(100.0, (count / total_rows) * 100.0),
            "unlock_score": float(count),
            "confidence_level": _blocked_confidence_label(reason),
            "affected_opportunities": [],
            "source_of_calculation": "Queue status query; no linked dependency fields detected",
        }

    return sorted(grouped.values(), key=lambda item: float(item["unlock_score"]), reverse=True)


def _blocked_reasons_for_dependency(dependency: object) -> list[str]:
    reasons = []
    missing = set(getattr(dependency, "missing_inputs", []))
    connectors = set(getattr(dependency, "connector_requirements", []))
    if "profile.email" in missing:
        reasons.append("Missing Email")
    if any(field.startswith("shipping.") for field in missing):
        reasons.append("Missing Shipping")
    if any(field.startswith("payouts.") for field in missing):
        reasons.append("Payment Routing Missing")
    if connectors:
        reasons.append("Site Login Needed")
    if getattr(dependency, "ready_for_approval", False):
        reasons.append("Final Approval Required")
    if getattr(dependency, "manual_only", False):
        reasons.append("Human Verification")
    return _dedupe(reasons)


def _dependency_graph_score(row: dict[str, object], dependency: object) -> float:
    value = _safe_float(row.get("highest_value_score")) or _safe_float(row.get("expected_value_usd"))
    probability = _safe_float(row.get("probability_score_1_to_10")) or _safe_float(row.get("probability_score"))
    dependency_count = len(getattr(dependency, "missing_inputs", [])) + len(getattr(dependency, "connector_requirements", []))
    return max(1.0, value) * max(1.0, probability) / max(1, dependency_count)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _legacy_autorun_blocked_reasons(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = rows_for_action_center(conn)
    dependencies = global_input_dependency_map(rows)
    total_rows = max(1, len(rows))
    grouped: dict[str, dict[str, object]] = {}
    for dependency in dependencies:
        reason = _blocked_reason_for_input(dependency.input_key)
        if not reason:
            continue
        item = grouped.setdefault(
            reason,
            {
                "reason": reason,
                "required_action": _blocked_required_action(reason, dependency.input_key),
                "opportunities": 0,
                "monthly_gain": 0.0,
                "autonomy_delta": 0.0,
                "unlock_score": 0.0,
                "confidence_level": _blocked_confidence_label(reason),
            },
        )
        item["opportunities"] = int(item["opportunities"]) + int(dependency.number_unblocked)
        item["monthly_gain"] = float(item["monthly_gain"]) + _dependency_monthly_gain(rows, dependency.blocks)
        item["autonomy_delta"] = min(100.0, float(item["autonomy_delta"]) + ((dependency.number_unblocked / total_rows) * 100.0))
        item["unlock_score"] = float(item["unlock_score"]) + float(dependency.unlock_score)

    for reason, query in _non_dependency_blocker_queries().items():
        if reason in grouped:
            continue
        count = _count_sql(conn, query)
        if count <= 0:
            continue
        grouped[reason] = {
            "reason": reason,
            "required_action": _blocked_required_action(reason, ""),
            "opportunities": count,
            "monthly_gain": 0.0,
            "autonomy_delta": min(100.0, (count / total_rows) * 100.0),
            "unlock_score": float(count),
            "confidence_level": _blocked_confidence_label(reason),
        }

    return sorted(grouped.values(), key=lambda item: float(item["unlock_score"]), reverse=True)


def _blocked_reason_for_input(input_key: str) -> str:
    if input_key == "email":
        return "Missing Email"
    if input_key == "shipping_address":
        return "Missing Shipping"
    if input_key in {"paypal_email", "venmo", "cashapp", "stripe_email", "payout_account"}:
        return "Payment Routing Missing"
    if input_key.endswith("_login") or input_key == "platform_login":
        return "Site Login Needed"
    if input_key in {"identity_sensitive", "wallet_signing"}:
        return "Human Verification"
    if input_key in {"tax_info", "legal_attestation", "purchase_required"}:
        return "Final Approval Required"
    return ""


def _blocked_required_action(reason: str, input_key: str) -> str:
    actions = {
        "Missing Email": "Add primary email in the vault.",
        "Missing Shipping": "Add default shipping address in the vault.",
        "Payment Routing Missing": "Add PayPal email or payout preference in the vault.",
        "Site Login Needed": "Connect or approve login for the required platform.",
        "Human Verification": "Complete the human verification or identity/wallet approval step yourself.",
        "Final Approval Required": "Review the prepared action and approve, reject, or mark later.",
        "External Wait": "Wait for the external site, shipment, payout, or review window to update.",
        "Legal Restriction": "Review legal/tax/payment terms manually before any continuation.",
    }
    if input_key == "github_login":
        return "Connect or approve GitHub login."
    return actions.get(reason, "Open the vault or final approval queue for the minimal required action.")


def _blocked_confidence_label(reason: str) -> str:
    if reason in {"Missing Email", "Missing Shipping", "Payment Routing Missing", "Site Login Needed", "Final Approval Required"}:
        return "High"
    if reason in {"Human Verification", "External Wait", "Legal Restriction"}:
        return "Medium"
    return "Experimental"


def _confidence_label(item: dict[str, object]) -> str:
    probability = _safe_float(item.get("probability_score_1_to_10"))
    if probability <= 0:
        probability = _safe_float(item.get("probability_score"))
    if probability >= 7:
        return "High"
    if probability >= 4:
        return "Medium"
    return "Experimental"


def _non_dependency_blocker_queries() -> dict[str, str]:
    return {
        "External Wait": """
            SELECT COUNT(*) FROM claim_queue
            WHERE status IN ('Submitted', 'Processing')
               OR execution_status IN ('Submitted', 'Processing')
        """,
        "Legal Restriction": """
            SELECT COUNT(*) FROM claim_queue
            WHERE sensitive_inputs LIKE '%legal_attestation%'
               OR sensitive_inputs LIKE '%tax_info%'
               OR sensitive_inputs LIKE '%payment_authorization%'
               OR sensitive_inputs LIKE '%purchase_required%'
        """,
    }


def _dependency_monthly_gain(rows: list[dict[str, object]], blocked_titles: list[str]) -> float:
    titles = set(blocked_titles)
    return sum(_safe_float(row.get("expected_value_usd")) for row in rows if str(row.get("title") or "Untitled opportunity") in titles)


def autorun_status_summary(conn: sqlite3.Connection) -> dict[str, int]:
    sensitive_terms = [
        "identity_sensitive",
        "legal_attestation",
        "tax_info",
        "wallet_signing",
        "payment_authorization",
        "purchase_required",
    ]
    sensitive_clause = " OR ".join(["cq.sensitive_inputs LIKE ?"] * len(sensitive_terms))
    sensitive_params = [f"%{term}%" for term in sensitive_terms]
    return {
        "ai_currently_scanning": _count_sql(
            conn,
            "SELECT COUNT(*) FROM source_candidates WHERE status IN ('Found', 'Approved', 'Needs Approval')",
        ),
        "ai_preparing": _count_sql(
            conn,
            """
            SELECT COUNT(*) FROM claim_queue cq
            WHERE cq.input_status = 'ready_for_ai_work'
               OR cq.execution_status IN ('Execution Queue', 'Ready To Accept')
            """,
        ),
        "ai_executing": _count_sql(
            conn,
            "SELECT COUNT(*) FROM claim_queue cq WHERE cq.execution_status = 'AI Working'",
        ),
        "waiting_approval": _count_sql(
            conn,
            """
            SELECT COUNT(*) FROM claim_queue cq
            WHERE cq.input_status = 'final_approval_required'
               OR cq.status IN ('Needs Approval', 'Connect Needed')
            """,
        ),
        "paused": _count_sql(
            conn,
            """
            SELECT COUNT(*) FROM claim_queue cq
            WHERE cq.execution_status = 'Paused Awaiting Input'
               OR cq.input_status IN ('missing_shipping', 'missing_payout', 'needs_connect', 'blocked')
            """,
        ),
        "received_paid": _count_sql(
            conn,
            """
            SELECT
                (SELECT COUNT(*) FROM claim_queue WHERE status = 'Received/Paid')
                + (SELECT COUNT(*) FROM received_log)
            """,
        ),
        "sensitive_blockers": _count_sql(
            conn,
            f"""
            SELECT COUNT(*) FROM claim_queue cq
            WHERE cq.input_status = 'final_approval_required'
               OR {sensitive_clause}
            """,
            sensitive_params,
        ),
    }


def _count_sql(conn: sqlite3.Connection, query: str, params: list[object] | None = None) -> int:
    row = conn.execute(query, params or []).fetchone()
    if row is None:
        return 0
    return int(row[0] or 0)


def show_owner_setup_progress_panel(
    conn: sqlite3.Connection,
    include_status: bool = True,
    include_actions: bool = True,
) -> None:
    context = USER_CONTEXT_STORE.load()
    completeness = compute_completeness(context)
    rows = rows_for_action_center(conn)
    dependencies = global_input_dependency_map(rows)
    potential_unlocks = len({title for dependency in dependencies for title in dependency.blocks})
    monthly_gain = _estimated_monthly_gain_potential(rows)

    if include_status:
        st.markdown("**Setup Progress Panel**")
        metric_cols = st.columns(4)
        metric_cols[0].metric("Current Autonomy", f"{_current_autonomy_percent(rows, completeness):.1f}%")
        metric_cols[1].metric("Current Context Completeness", f"{completeness.automation_readiness_score:.1f}%")
        metric_cols[2].metric("Potential Unlocks", f"{potential_unlocks} opportunities")
        metric_cols[3].metric("Estimated Monthly Gain Potential", f"${monthly_gain:,.0f}")

    if not include_actions:
        return

    st.markdown("**Owner Setup**")
    st.caption("Complete reusable information once. AI reuses across future opportunities.")
    action_cols = st.columns([2, 5])
    with action_cols[0]:
        if st.button(
            "User Vault / Autofill Profile",
            type="primary",
            use_container_width=True,
            key="top_user_vault_button",
            on_click=_set_vault_open,
            args=("Overview",),
        ):
            pass
    with action_cols[1]:
        st.caption("Open reusable profile, shipping, payout, connector, preference, and autofill settings.")

    st.markdown("**Recommended Next Actions**")
    if not dependencies:
        st.write("No repeated reusable inputs are currently blocking the queue.")
        return

    total_rows = max(1, len(rows))
    for index, dependency in enumerate(dependencies[:5], start=1):
        autonomy_delta = min(25.0, (dependency.number_unblocked / total_rows) * 100.0)
        impact = _setup_action_impact(dependency.unlock_score)
        cols = st.columns([4, 1, 1, 1, 1])
        cols[0].markdown(f"**{index}. {_recommended_action_label(dependency.input_key, dependency.display_name)}**")
        cols[1].write(f"+{dependency.number_unblocked} unlocks")
        cols[2].write(f"+{autonomy_delta:.1f}% autonomy")
        cols[3].write(f"impact: {impact}")
        cols[4].button(
            "Open Vault",
            key=f"setup_open_vault_{dependency.input_key}",
            on_click=_set_vault_open,
            args=(dependency.input_key,),
        )


def show_user_profile_autofill_vault(conn: sqlite3.Connection) -> None:
    context = USER_CONTEXT_STORE.load()
    completeness = compute_completeness(context)
    dependencies = global_input_dependency_map(rows_for_action_center(conn))

    with st.container():
        title_cols = st.columns([4, 1])
        title_cols[0].markdown("**User Context / Autofill Profile**")
        if title_cols[1].button("Close Vault", use_container_width=True):
            st.session_state["show_vault"] = False
            st.session_state["user_profile_vault_open"] = False
            st.rerun()

        focus = st.session_state.get("vault_focus") or st.session_state.get("user_profile_vault_focus")
        if focus:
            st.info(f"Vault focus: {focus}. Update this reusable section once, then blocked opportunities can resume through Required Inputs.")

        st.caption(
            "Reusable owner context for autofill, routing, shipping, payout, and safe opportunity execution. "
            "Passwords, full bank numbers, identity documents, and sensitive final actions are never stored here."
        )
        summary_cols = st.columns(4)
        summary_cols[0].metric("Overall completeness", f"{completeness.automation_readiness_score:.1f}%")
        summary_cols[1].metric("Missing fields", len(completeness.missing_inputs))
        summary_cols[2].metric(
            "Top unlock field",
            dependencies[0].display_name if dependencies else completeness.highest_impact_field_to_add_next,
        )
        summary_cols[3].metric("Unlocks", dependencies[0].number_unblocked if dependencies else 0)
        st.progress(min(100, max(0, int(completeness.automation_readiness_score))))

        overview_cols = st.columns(3)
        with overview_cols[0]:
            st.markdown("**Missing fields**")
            st.write(", ".join(completeness.missing_inputs[:12]) or "No reusable context gaps detected.")
        with overview_cols[1]:
            st.markdown("**Top fields to add next**")
            if dependencies:
                for dependency in dependencies[:4]:
                    st.write(f"{dependency.display_name}: Completing this unlocks {dependency.number_unblocked} opportunities.")
            else:
                st.write(completeness.highest_impact_field_to_add_next)
        with overview_cols[2]:
            st.markdown("**Current AI coverage**")
            st.write(", ".join(completeness.what_ai_can_already_do[:5]))

        with st.form("user_profile_autofill_vault_form"):
            profile = dict(context["profile"])
            shipping = dict(context["shipping"])
            payouts = dict(context["payouts"])
            wallets = dict(context["crypto_wallets"])
            accounts = dict(context["accounts"])
            business = dict(context.get("business", {}))
            preferences = dict(context["preferences"])
            automation = dict(context["automation_limits"])
            selected_group = _vault_selected_group()
            selected_group = st.radio(
                "Vault tabs",
                options=VAULT_FIELD_GROUPS,
                index=VAULT_FIELD_GROUPS.index(selected_group),
                horizontal=True,
                key="vault_field_group_selector",
            )
            st.session_state["vault_focus"] = selected_group
            st.session_state["user_profile_vault_focus"] = selected_group
            st.caption(f"Focused group: {selected_group}")

            if selected_group == "Basic Profile":
                profile["name"] = st.text_input("Full name", value=str(profile.get("name") or ""), key="vault_profile_name")
                profile["email"] = st.text_input("Email", value=str(profile.get("email") or ""), key="vault_profile_email")
                profile["phone"] = st.text_input("Phone", value=str(profile.get("phone") or ""), key="vault_profile_phone")
                profile["date_of_birth"] = st.text_input(
                    "Date of birth optional",
                    value=str(profile.get("date_of_birth") or ""),
                    placeholder="Sensitive - final approval only",
                    key="vault_profile_date_of_birth",
                )
                st.caption("Date of birth is sensitive context. It never authorizes identity verification or submission by itself.")

            elif selected_group == "Shipping":
                shipping["address_line_1"] = st.text_input(
                    "Address line 1",
                    value=str(shipping.get("address_line_1") or ""),
                    key="vault_shipping_address_line_1",
                )
                shipping["address_line_2"] = st.text_input(
                    "Address line 2",
                    value=str(shipping.get("address_line_2") or ""),
                    key="vault_shipping_address_line_2",
                )
                ship_cols = st.columns(4)
                shipping["city"] = ship_cols[0].text_input("City", value=str(shipping.get("city") or ""), key="vault_shipping_city")
                shipping["state"] = ship_cols[1].text_input("State", value=str(shipping.get("state") or ""), key="vault_shipping_state")
                shipping["zip"] = ship_cols[2].text_input("Zip", value=str(shipping.get("zip") or ""), key="vault_shipping_zip")
                shipping["country"] = ship_cols[3].text_input("Country", value=str(shipping.get("country") or ""), key="vault_shipping_country")
                shipping["full_name"] = st.text_input(
                    "Shipping full name",
                    value=str(shipping.get("full_name") or profile.get("name") or ""),
                    key="vault_shipping_full_name",
                )

            elif selected_group == "Payouts":
                payout_cols = st.columns(2)
                payouts["paypal_email"] = payout_cols[0].text_input(
                    "PayPal email",
                    value=str(payouts.get("paypal_email") or ""),
                    key="vault_payout_paypal_email",
                )
                payouts["cashapp"] = payout_cols[1].text_input(
                    "Cash App tag",
                    value=str(payouts.get("cashapp") or ""),
                    key="vault_payout_cashapp",
                )
                payouts["venmo"] = payout_cols[0].text_input("Venmo", value=str(payouts.get("venmo") or ""), key="vault_payout_venmo")
                payouts["stripe_email"] = payout_cols[1].text_input(
                    "Stripe email",
                    value=str(payouts.get("stripe_email") or ""),
                    key="vault_payout_stripe_email",
                )
                payouts["other_payout_note"] = st.text_area(
                    "Other payout note",
                    value=str(payouts.get("other_payout_note") or ""),
                    key="vault_payout_other_note",
                )
                st.caption("Do not enter full bank account or routing numbers. Bank labels only remain allowed elsewhere.")

            elif selected_group == "Crypto Wallets":
                wallet_cols = st.columns(2)
                wallets["btc_address"] = wallet_cols[0].text_input(
                    "BTC address",
                    value=str(wallets.get("btc_address") or ""),
                    key="vault_wallet_btc",
                )
                wallets["eth_address"] = wallet_cols[1].text_input(
                    "ETH address",
                    value=str(wallets.get("eth_address") or ""),
                    key="vault_wallet_eth",
                )
                wallets["sol_address"] = wallet_cols[0].text_input(
                    "SOL address",
                    value=str(wallets.get("sol_address") or ""),
                    key="vault_wallet_sol",
                )
                wallets["wallet_notes"] = st.text_area(
                    "General wallet note",
                    value=str(wallets.get("wallet_notes") or ""),
                    key="vault_wallet_notes",
                )
                st.warning("Wallet signing remains final-approval-only. Stored addresses never authorize signatures or transactions.")

            elif selected_group == "Accounts / Connectors":
                account_cols = st.columns(2)
                accounts["github_username"] = account_cols[0].text_input(
                    "GitHub username",
                    value=str(accounts.get("github_username") or ""),
                    key="vault_account_github_username",
                )
                accounts["google_email"] = account_cols[1].text_input(
                    "Google email",
                    value=str(accounts.get("google_email") or ""),
                    key="vault_account_google_email",
                )
                accounts["microsoft_email"] = account_cols[0].text_input(
                    "Microsoft email",
                    value=str(accounts.get("microsoft_email") or ""),
                    key="vault_account_microsoft_email",
                )
                accounts["amazon_email"] = account_cols[1].text_input(
                    "Amazon email",
                    value=str(accounts.get("amazon_email") or ""),
                    key="vault_account_amazon_email",
                )
                accounts["apple_email"] = account_cols[0].text_input(
                    "Apple email",
                    value=str(accounts.get("apple_email") or ""),
                    key="vault_account_apple_email",
                )
                accounts["paypal_email"] = account_cols[1].text_input(
                    "PayPal account email",
                    value=str(accounts.get("paypal_email") or ""),
                    key="vault_account_paypal_email",
                )
                connect_cols = st.columns(6)
                accounts["paypal_connected"] = connect_cols[0].checkbox(
                    "PayPal connected",
                    value=bool(accounts.get("paypal_connected")),
                    key="vault_account_paypal_connected",
                )
                accounts["gmail_connected"] = connect_cols[1].checkbox(
                    "Gmail connected",
                    value=bool(accounts.get("gmail_connected")),
                    key="vault_account_gmail_connected",
                )
                accounts["github_connected"] = connect_cols[2].checkbox(
                    "GitHub connected",
                    value=bool(accounts.get("github_connected")),
                    key="vault_account_github_connected",
                )
                accounts["microsoft_connected"] = connect_cols[3].checkbox(
                    "Microsoft connected",
                    value=bool(accounts.get("microsoft_connected")),
                    key="vault_account_microsoft_connected",
                )
                accounts["amazon_connected"] = connect_cols[4].checkbox(
                    "Amazon connected",
                    value=bool(accounts.get("amazon_connected")),
                    key="vault_account_amazon_connected",
                )
                accounts["apple_connected"] = connect_cols[5].checkbox(
                    "Apple connected",
                    value=bool(accounts.get("apple_connected")),
                    key="vault_account_apple_connected",
                )
                st.markdown("**Connector Status**")
                connector_rows = [status.to_dict() for status in connector_statuses({**context, "accounts": accounts})]
                show_dataframe(pd.DataFrame(connector_rows))
                accounts["future_connector_notes"] = st.text_area(
                    "Future connector placeholders",
                    value=str(accounts.get("future_connector_notes") or ""),
                    key="vault_account_future_connector_notes",
                )
                st.caption("Connector status is context only. The dashboard does not store passwords or bypass platform login rules.")

            elif selected_group == "Credentials / Submission Consent":
                show_external_authorization_hub()
                st.divider()
                show_credential_vault_panel()
                st.divider()
                show_submission_consent_policy_panel()

            elif selected_group == "Business / Startup Info":
                business["business_name"] = st.text_input(
                    "Business name",
                    value=str(business.get("business_name") or ""),
                    key="vault_business_name",
                )
                business["website_domain"] = st.text_input(
                    "Website/domain",
                    value=str(business.get("website_domain") or ""),
                    key="vault_business_website_domain",
                )
                business["founder_name"] = st.text_input(
                    "Founder name",
                    value=str(business.get("founder_name") or ""),
                    key="vault_business_founder_name",
                )
                business["company_description"] = st.text_area(
                    "Company description",
                    value=str(business.get("company_description") or ""),
                    key="vault_business_company_description",
                )
                business_cols = st.columns(2)
                business["startup_stage"] = business_cols[0].text_input(
                    "Startup stage",
                    value=str(business.get("startup_stage") or ""),
                    key="vault_business_startup_stage",
                )
                business["industry"] = business_cols[1].text_input(
                    "Industry",
                    value=str(business.get("industry") or ""),
                    key="vault_business_industry",
                )
                business["ein_tax_placeholder"] = ""
                st.text_input(
                    "EIN/tax info placeholder",
                    value="",
                    placeholder="Sensitive - final approval only - not stored",
                    disabled=True,
                    key="vault_business_ein_placeholder",
                )
                st.warning("Tax information is not stored in the vault. Tax actions remain final-approval-required.")

            elif selected_group == "Preferences":
                preferences["preference_profile"] = _preference_profile_selector(
                    "vault",
                    str(preferences.get("preference_profile") or "Balanced"),
                    context,
                    conn=conn,
                )
                is_custom = preferences.get("preference_profile") == "Custom"
                preferences["open_to_everything"] = st.checkbox(
                    "Open To Everything",
                    value=bool(preferences.get("open_to_everything")),
                    key="vault_preferences_open_to_everything",
                    disabled=not is_custom,
                )
                preferences = _checkbox_section(
                    "vault_preferences",
                    PREFERENCE_FIELDS,
                    preferences,
                    disabled=not is_custom,
                )

            elif selected_group == "Automation Limits":
                automation["allow_autofill"] = st.checkbox(
                    "Allow safe autofill",
                    value=bool(automation.get("allow_autofill")),
                    key="vault_automation_allow_autofill",
                    disabled=preferences.get("preference_profile") != "Custom",
                )
                automation["allow_prepare_forms"] = st.checkbox(
                    "Allow AI preparation",
                    value=bool(automation.get("allow_prepare_forms")),
                    key="vault_automation_allow_prepare_forms",
                    disabled=preferences.get("preference_profile") != "Custom",
                )
                automation["allow_connector_suggestions"] = st.checkbox(
                    "Allow connector suggestions",
                    value=bool(automation.get("allow_connector_suggestions")),
                    key="vault_automation_allow_connector_suggestions",
                    disabled=preferences.get("preference_profile") != "Custom",
                )
                st.checkbox("Require final approval for submit", value=True, disabled=True, key="vault_require_submit")
                st.checkbox("Require final approval for purchases", value=True, disabled=True, key="vault_require_purchases")
                st.checkbox(
                    "Require final approval for legal/tax/identity/wallet/payment actions",
                    value=True,
                    disabled=True,
                    key="vault_require_sensitive_actions",
                )
                automation["require_final_approval_for_submit"] = True
                automation["require_final_approval_for_purchases"] = True
                automation["require_final_approval_for_legal_tax_identity_wallet_payment"] = True
                automation["require_final_approval_for_sensitive"] = True
                automation["allow_submit_without_final_approval"] = False

            button_cols = st.columns([1, 1, 4])
            save_clicked = button_cols[0].form_submit_button("Save")
            reset_clicked = button_cols[1].form_submit_button("Clear/reset")

            if save_clicked:
                context["profile"] = profile
                context["shipping"] = shipping
                context["payouts"] = payouts
                context["crypto_wallets"] = wallets
                context["accounts"] = accounts
                context["business"] = business
                context["preferences"] = preferences
                context["automation_limits"] = automation
                USER_CONTEXT_STORE.save(apply_preference_profile(context))
                SQLiteStore(DB_PATH).normalize_required_inputs()
                st.success("User Profile / Autofill Vault saved and readiness refreshed.")
                st.rerun()

            if reset_clicked:
                USER_CONTEXT_STORE.save(default_user_context())
                SQLiteStore(DB_PATH).normalize_required_inputs()
                st.success("User Profile / Autofill Vault cleared and readiness refreshed.")
                st.rerun()


def show_top_level_user_action_center(conn: sqlite3.Connection) -> None:
    context = USER_CONTEXT_STORE.load()
    completeness = compute_completeness(context)
    dependencies = global_input_dependency_map(rows_for_action_center(conn))
    profile_percent = completeness.sections["profile"].completion_percent
    readiness = completeness.automation_readiness_score

    with st.expander("USER ACTION CENTER", expanded=False):
        _show_top_level_user_action_center_content(context, dependencies, profile_percent, readiness)


def _show_top_level_user_action_center_content(
    context: dict[str, object],
    dependencies: list[object],
    profile_percent: float,
    readiness: float,
) -> None:
    cols = st.columns([2, 3])
    cols[0].metric("Profile Completeness", f"{profile_percent:.1f}%")
    cols[1].markdown("**Context Completeness Score:**")
    cols[1].write(f"{_readiness_bar(readiness)} {readiness:.1f}%")
    cols[1].progress(min(100, max(0, int(readiness))))

    st.markdown("**Top Unlock Opportunities**")
    if dependencies:
        top_cols = st.columns(min(4, len(dependencies[:4])))
        for index, dependency in enumerate(dependencies[:4], start=1):
            with top_cols[index - 1]:
                st.markdown(f"**{index}. {dependency.input_key}**")
                st.write(f"Unlocks: {dependency.number_unblocked}")
                st.caption(dependency.prompt)
    else:
        st.write("No global missing-input dependencies are currently blocking the queue.")

    st.markdown("**Missing Inputs**")
    grouped = _group_dependencies_for_dashboard(dependencies)
    group_cols = st.columns(3)
    for index, group_name in enumerate(["Account Connectors", "Payment", "Identity", "Platform Access", "Tax", "Approval Needed"]):
        with group_cols[index % 3]:
            st.markdown(f"**{group_name}**")
            items = grouped.get(group_name, [])
            if not items:
                st.caption("None")
                continue
            for dependency in items[:5]:
                st.write(f"{dependency.display_name}: {dependency.prompt}")
                st.button(
                    "Open Vault",
                    key=f"top_resolve_{group_name}_{dependency.input_key}",
                    on_click=_set_vault_open,
                    args=(dependency.input_key,),
                )

    if st.session_state.get("profile_completion_center_open"):
        show_profile_completion_center(context)


def show_credential_vault_panel() -> None:
    st.markdown("**Encrypted Credential Vault**")
    st.caption(
        "Optional owner-controlled credential storage for faster login-assisted work. Passwords are encrypted locally "
        "with a master password and are not written to User Context."
    )
    if not credential_vault_available():
        st.warning("Install `cryptography` from requirements.txt to enable encrypted credential storage.")
        return

    vault = CredentialVault.for_root(ROOT_DIR)
    if not vault.exists():
        setup_password = st.text_input("Create master password", type="password", key="credential_vault_setup_password")
        setup_confirm = st.text_input("Confirm master password", type="password", key="credential_vault_setup_confirm")
        if st.form_submit_button("Create encrypted credential vault"):
            if setup_password != setup_confirm:
                st.error("Master passwords do not match.")
            else:
                try:
                    vault.setup(setup_password)
                    st.session_state["credential_vault_key"] = vault.unlock(setup_password)
                    st.success("Encrypted credential vault created and unlocked for this session.")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
        return

    if "credential_vault_key" not in st.session_state:
        unlock_password = st.text_input("Master password", type="password", key="credential_vault_unlock_password")
        if st.form_submit_button("Unlock credential vault"):
            try:
                st.session_state["credential_vault_key"] = vault.unlock(unlock_password)
                st.success("Credential vault unlocked for this session.")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
        return

    key = st.session_state["credential_vault_key"]
    records = vault.list_records(key)
    st.write(f"Unlocked credentials: {len(records)}")
    if records:
        show_dataframe(pd.DataFrame([record.to_dict() for record in records]))
    label = st.text_input("Credential label", key="credential_label")
    username = st.text_input("Username / email", key="credential_username")
    password = st.text_input("Password", type="password", key="credential_password")
    login_url = st.text_input("Login URL", key="credential_login_url")
    notes = st.text_area("Usage notes", key="credential_notes")
    cols = st.columns(2)
    if cols[0].form_submit_button("Save encrypted credential"):
        try:
            vault.save_record(key, label=label, username=username, password=password, login_url=login_url, notes=notes)
            st.success("Credential encrypted and saved.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
    delete_options = [""] + [record.key for record in records]
    delete_key = cols[1].selectbox("Delete credential", options=delete_options, key="credential_delete_key")
    if cols[1].form_submit_button("Delete selected credential"):
        if delete_key and vault.delete_record(key, delete_key):
            st.success("Credential deleted.")
            st.rerun()


def show_submission_consent_policy_panel() -> None:
    st.markdown("**AI Live Submit Consent Policy**")
    st.caption(
        "Low-risk prepared forms can be authorized for AI live-submit after explicit final approval. "
        "This does not include payment authorization, purchases, legal agreements, tax actions, identity verification, "
        "wallet signing, or account connection."
    )
    policy_rows = [
        {"action": "Safe prepared claim form", "AI live submit": "Allowed after explicit final approval"},
        {"action": "Payment / purchase", "AI live submit": "Blocked"},
        {"action": "Legal/tax/identity", "AI live submit": "Blocked"},
        {"action": "Wallet signing / private keys", "AI live submit": "Blocked"},
        {"action": "Login/account connection", "AI live submit": "Owner-controlled; credential vault can assist only after unlock"},
    ]
    show_dataframe(pd.DataFrame(policy_rows))


def show_external_authorization_hub() -> None:
    st.markdown("**External Authorization Hub**")
    st.caption(
        "Use provider-owned authorization where possible. This records that the owner connected or approved a provider externally; "
        "it does not store tokens, payment credentials, bank data, identity documents, or wallet keys."
    )
    rows = external_authorization_rows(ROOT_DIR)
    display_rows = []
    for row in rows:
        display_rows.append(
            {
                "provider": row["label"],
                "category": row["category"],
                "authorized": row["authorized"],
                "AI can use for": ", ".join(row["ai_can_use_for"]),
                "blocked actions": ", ".join(row["blocked_actions"]),
                "note": row["note"],
                "authorized at": row["authorized_at"],
            }
        )
    show_dataframe(pd.DataFrame(display_rows))

    st.markdown("**Provider Links + Owner Authorization**")
    store = ExternalAuthorizationStore.for_root(ROOT_DIR)
    existing = store.records()
    records: list[ExternalAuthorizationRecord] = []
    for provider in EXTERNAL_AUTHORIZATION_PROVIDERS:
        current = existing.get(provider.key)
        cols = st.columns([1.4, 1.5, 2.5, 1.2])
        cols[0].markdown(f"**{provider.label}**")
        cols[0].caption(provider.category)
        if provider.owner_link_url:
            cols[1].link_button("Open provider", provider.owner_link_url, use_container_width=True)
        else:
            cols[1].caption("No external link. Human verification pauses only.")
        authorized = cols[3].checkbox(
            "Authorized",
            value=bool(current.authorized) if current else False,
            key=f"external_auth_{provider.key}",
        )
        note = cols[2].text_input(
            "Authorization note",
            value=current.authorization_note if current else "",
            key=f"external_auth_note_{provider.key}",
            placeholder="Example: connected externally, payout destination approved, login owner-approved",
        )
        records.append(
            ExternalAuthorizationRecord(
                provider_key=provider.key,
                authorized=authorized,
                authorization_note=note,
                authorized_at=(current.authorized_at if current and current.authorized and authorized else ""),
            )
        )
    if st.form_submit_button("Save external authorizations"):
        now = datetime.now(timezone.utc).isoformat()
        normalized = [
            ExternalAuthorizationRecord(
                provider_key=record.provider_key,
                authorized=record.authorized,
                authorization_note=record.authorization_note,
                authorized_at=record.authorized_at or (now if record.authorized else ""),
            )
            for record in records
        ]
        store.save_records(normalized)
        st.success("External authorization choices saved.")
        st.rerun()


def _set_vault_open(focus_key: str = "Overview") -> None:
    focus_group = _vault_focus_group(focus_key)
    if focus_group == "Payment":
        focus_group = "Payouts"
    if focus_group not in VAULT_FIELD_GROUPS:
        focus_group = "Basic Profile"
    st.session_state["show_vault"] = True
    st.session_state["vault_focus"] = focus_group
    st.session_state["vault_field_group_selector"] = focus_group
    st.session_state["user_profile_vault_open"] = True
    st.session_state["user_profile_vault_focus"] = focus_group
    st.session_state["profile_completion_center_open"] = False


def _open_vault_for_section(section: str) -> None:
    _set_vault_open(section)
    st.rerun()


def _vault_focus_group(focus_key: str) -> str:
    key = str(focus_key or "Overview")
    normalized = key.lower().replace(" ", "_")
    focus_map = {
        "paypal_email": "Payment",
        "payout_account": "Payouts",
        "cashapp": "Payouts",
        "venmo": "Payouts",
        "stripe_email": "Payouts",
        "shipping_address": "Shipping",
        "needs_shipping": "Shipping",
        "shipping": "Shipping",
        "platform_login": "Accounts / Connectors",
        "github_login": "Accounts / Connectors",
        "google_login": "Accounts / Connectors",
        "microsoft_login": "Accounts / Connectors",
        "paypal_login": "Accounts / Connectors",
        "needs_connect": "Accounts / Connectors",
        "needs_login": "Accounts / Connectors",
        "credentials": "Credentials / Submission Consent",
        "credential_vault": "Credentials / Submission Consent",
        "submission_consent": "Credentials / Submission Consent",
        "email": "Basic Profile",
        "missing_email": "Basic Profile",
        "phone": "Basic Profile",
        "missing_phone": "Basic Profile",
        "tax_info": "Business / Startup Info",
        "missing_tax_information": "Business / Startup Info",
        "identity_sensitive": "Identity",
        "missing_identity": "Identity",
        "crypto_wallet": "Crypto Wallets",
        "btc_address": "Crypto Wallets",
        "eth_address": "Crypto Wallets",
        "sol_address": "Crypto Wallets",
        "usdc_address": "Crypto Wallets",
        "missing_wallet": "Crypto Wallets",
    }
    return focus_map.get(normalized, key)


def _vault_selected_group() -> str:
    focus = _vault_focus_group(
        str(st.session_state.get("vault_focus") or st.session_state.get("user_profile_vault_focus") or "Basic Profile")
    )
    if focus == "Payment":
        focus = "Payouts"
    return focus if focus in VAULT_FIELD_GROUPS else "Basic Profile"


def _current_autonomy_percent(rows: list[dict[str, object]], completeness: object) -> float:
    if not rows:
        return float(getattr(completeness, "automation_readiness_score", 0.0))
    ready = sum(1 for row in rows if str(row.get("input_status") or "") == "ready_for_ai_work")
    queue_readiness = (ready / len(rows)) * 100.0
    context_readiness = float(getattr(completeness, "automation_readiness_score", 0.0))
    return round((context_readiness * 0.7) + (queue_readiness * 0.3), 1)


def _estimated_monthly_gain_potential(rows: list[dict[str, object]]) -> float:
    return sum(_safe_float(row.get("expected_value_usd")) for row in rows)


def _setup_action_impact(unlock_score: float) -> str:
    if unlock_score >= 1000:
        return "high"
    if unlock_score >= 250:
        return "medium"
    return "low"


def _recommended_action_label(input_key: str, display_name: str) -> str:
    labels = {
        "paypal_email": "Add PayPal email",
        "payout_account": "Add payout defaults",
        "shipping_address": "Add shipping defaults",
        "platform_login": "Connect platform login",
        "github_login": "Connect GitHub login",
        "google_login": "Connect Google login",
        "microsoft_login": "Connect Microsoft login",
        "paypal_login": "Connect PayPal login",
        "email": "Add email",
        "phone": "Add phone",
        "crypto_wallet": "Add crypto wallet",
        "btc_address": "Add BTC wallet",
        "eth_address": "Add ETH wallet",
        "sol_address": "Add SOL wallet",
    }
    return labels.get(input_key, f"Add {display_name.lower()}")


def _autofill_readiness_label(plan: object) -> str:
    return _autofill_readiness_label_from_values(
        getattr(plan, "fields_missing", []),
        getattr(plan, "connector_needed", ""),
        bool(getattr(plan, "final_approval_required", False)),
        str(getattr(plan, "readiness", "")),
    )


def _autofill_readiness_label_from_values(
    missing_fields: list[str],
    connector_needed: str,
    final_approval_required: bool,
    readiness: str,
) -> str:
    if final_approval_required or readiness == "final_approval_required":
        return "Needs final approval"
    if connector_needed or readiness == "blocked_by_login":
        return "Needs connector"
    if missing_fields:
        return "Missing fields"
    if readiness == "autofill_ready":
        return "Ready"
    return "Manual only"


def show_vault_data_preview(claim: dict[str, object]) -> None:
    context = USER_CONTEXT_STORE.load()
    plan = plan_autofill_for_opportunity(claim, context)
    preview = _vault_preview_values(context, plan.fields_ai_can_autofill)
    st.markdown("**Use vault data for this claim - Dry Run Preview**")
    st.caption("This shows exactly what would be prepared. Dry Run never submits automatically.")
    if not preview:
        st.write("No safe vault fields are ready for this claim yet.")
        return
    show_dataframe(pd.DataFrame([preview]))


def _vault_preview_values(context: dict[str, object], fields: list[str]) -> dict[str, str]:
    profile = context.get("profile", {})
    shipping = context.get("shipping", {})
    payouts = context.get("payouts", {})
    wallets = context.get("crypto_wallets", {})
    preview: dict[str, str] = {}
    if "profile.name" in fields:
        preview["name"] = str(profile.get("name") or "")
    if "profile.email" in fields:
        preview["email"] = str(profile.get("email") or "")
    shipping_fields = ["shipping.full_name", "shipping.address_line_1", "shipping.city", "shipping.state", "shipping.zip", "shipping.country"]
    if any(field in fields for field in shipping_fields):
        preview["shipping"] = ", ".join(
            part
            for part in [
                str(shipping.get("full_name") or ""),
                str(shipping.get("address_line_1") or ""),
                str(shipping.get("address_line_2") or ""),
                str(shipping.get("city") or ""),
                str(shipping.get("state") or ""),
                str(shipping.get("zip") or ""),
                str(shipping.get("country") or ""),
            ]
            if part
        )
    if "payouts.paypal_email" in fields:
        preview["payout destination"] = str(payouts.get("paypal_email") or "")
    elif "payouts.stripe_email" in fields:
        preview["payout destination"] = str(payouts.get("stripe_email") or "")
    wallet_field = next((field for field in fields if field.startswith("crypto_wallets.")), "")
    if wallet_field:
        preview["public wallet address"] = str(wallets.get(wallet_field.split(".", 1)[1]) or "")
    return {key: value for key, value in preview.items() if value}


def _safe_float(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except ValueError:
        return 0.0


def _readiness_bar(percent: float, width: int = 10) -> str:
    filled = int(round((max(0.0, min(100.0, percent)) / 100.0) * width))
    return ("█" * filled) + ("░" * (width - filled))


def _group_dependencies_for_dashboard(dependencies: list[object]) -> dict[str, list[object]]:
    grouped = {
        "Account Connectors": [],
        "Payment": [],
        "Identity": [],
        "Platform Access": [],
        "Tax": [],
        "Approval Needed": [],
    }
    for dependency in dependencies:
        group = _dependency_group(str(dependency.input_key))
        grouped.setdefault(group, []).append(dependency)
    for group, items in grouped.items():
        grouped[group] = sorted(items, key=lambda item: item.unlock_score, reverse=True)
    return grouped


def _dependency_group(input_key: str) -> str:
    if input_key in {"paypal_email", "venmo", "cashapp", "stripe_email", "payout_account"}:
        return "Payment"
    if input_key in {"github_login", "google_login", "microsoft_login", "tiktok_login", "amazon_login", "paypal_login"}:
        return "Account Connectors"
    if input_key in {"platform_login", "email", "phone", "shipping_address", "btc_address", "eth_address", "sol_address", "usdc_address", "crypto_wallet"}:
        return "Platform Access"
    if input_key in {"identity_sensitive"}:
        return "Identity"
    if input_key in {"tax_info"}:
        return "Tax"
    if input_key in {"legal_attestation", "purchase_required"}:
        return "Approval Needed"
    return "Approval Needed"


def show_user_action_center(conn: sqlite3.Connection) -> None:
    context = USER_CONTEXT_STORE.load()
    rows = rows_for_action_center(conn)
    items = build_user_action_items(rows, context)
    dependencies = global_input_dependency_map(rows)
    st.caption("Central owner-required action queue. AI can prepare and stage safe fields, but final approval gates remain active.")
    if not items:
        st.write("No owner-required actions are currently queued.")
        show_profile_completion_center(context)
        return

    bucket_counts = {bucket: 0 for bucket in ACTION_BUCKETS}
    for item in items:
        bucket_counts[item.action_bucket] = bucket_counts.get(item.action_bucket, 0) + 1
    cols = st.columns(5)
    for index, bucket in enumerate(ACTION_BUCKETS):
        if bucket_counts.get(bucket, 0):
            cols[index % 5].metric(bucket, bucket_counts[bucket])

    selected_bucket = st.selectbox("Action bucket", ["All", *ACTION_BUCKETS])
    filtered = [item for item in items if selected_bucket == "All" or item.action_bucket == selected_bucket]
    show_global_input_dependency_map(dependencies)
    table_rows = []
    for item in filtered:
        table_rows.append(
            {
                "action_priority_score": item.action_priority_score,
                "Opportunity": item.opportunity,
                "Estimated gain": item.estimated_gain,
                "Missing requirement": item.missing_requirement,
                "Time required": item.time_required,
                "Completion %": item.completion_percent,
                "AI readiness": item.ai_readiness,
                "Readiness": item.readiness_badge,
                "Action": item.action_button_label,
                "Bucket": item.action_bucket,
            }
        )
    show_dataframe(pd.DataFrame(table_rows))

    st.markdown("**One-Click Actions**")
    for item in filtered[:25]:
        cols = st.columns([4, 2, 2])
        cols[0].write(f"{item.opportunity} - {item.readiness_badge}")
        cols[1].write(f"Priority {item.action_priority_score:.2f}")
        cols[2].button(
            item.action_button_label,
            key=f"user_action_{item.claim_queue_id}",
            on_click=_set_vault_open,
            args=(item.action_bucket,),
        )

    st.button(
        "Resolve Missing Inputs",
        on_click=_set_vault_open,
        args=("Overview",),
        key="user_action_resolve_missing_inputs",
    )
    if st.session_state.get("profile_completion_center_open"):
        show_profile_completion_center(context)


def show_connector_autofill_readiness(conn: sqlite3.Connection) -> None:
    context = USER_CONTEXT_STORE.load()
    rows = rows_for_autofill(conn)
    plans = plan_autofill_for_opportunities(rows, context)
    summary = summarize_autofill(plans, context)
    dependencies = dependency_map_for_opportunities(rows, context)
    graph_summary = dependency_graph_summary(dependencies)

    st.markdown("**Connector + Autofill Readiness**")
    metric_cols = st.columns(6)
    metric_cols[0].metric("Connected accounts", summary["connected_accounts"])
    metric_cols[1].metric("Missing connectors", summary["missing_connectors"])
    metric_cols[2].metric("Autofill-ready opportunities", summary["autofill_ready"])
    metric_cols[3].metric("Blocked by login", summary["blocked_by_login"])
    metric_cols[4].metric("Missing User Context", summary["blocked_by_missing_context"])
    metric_cols[5].metric("Final approval required", summary["final_approval_required"])

    graph_cols = st.columns(5)
    graph_cols[0].metric("READY", graph_summary["ready"])
    graph_cols[1].metric("MISSING_FIELDS", graph_summary["missing_fields"])
    graph_cols[2].metric("NEEDS_CONNECTOR", graph_summary["needs_connector"])
    graph_cols[3].metric("READY_FOR_APPROVAL", graph_summary["ready_for_approval"])
    graph_cols[4].metric("MANUAL_ONLY", graph_summary["manual_only"])

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Connected Accounts**")
        connected = [status.to_dict() for status in connected_accounts(context)]
        show_dataframe(pd.DataFrame(connected)) if connected else st.write("None yet.")
    with col2:
        st.markdown("**Missing Connectors**")
        missing = [status.to_dict() for status in missing_connectors(context)]
        show_dataframe(pd.DataFrame(missing)) if missing else st.write("None.")

    st.markdown("**Opportunity Autofill Plans**")
    plan_rows = []
    for plan, dependency in zip(plans, dependencies):
        fields_needed = sorted(set(plan.fields_ai_can_autofill) | set(plan.fields_missing))
        plan_rows.append(
            {
                "Autofill Readiness": dependency.autofill_readiness,
                "opportunity": plan.opportunity,
                "required_fields": ", ".join(dependency.required_fields or fields_needed),
                "optional_fields": ", ".join(dependency.optional_fields),
                "required_connectors": ", ".join(dependency.required_connectors),
                "fields needed": ", ".join(dependency.required_fields or fields_needed),
                "fields AI can autofill": ", ".join(plan.fields_ai_can_autofill),
                "fields already available from vault": ", ".join(plan.fields_ai_can_autofill),
                "fields missing": ", ".join(dependency.missing_inputs),
                "connector requirements": ", ".join(dependency.connector_requirements),
                "connector needed": plan.connector_needed,
                "connector needed yes/no": "yes" if plan.connector_needed else "no",
                "can AI prepare yes/no": "yes" if not dependency.manual_only else "no",
                "can AI live-assist yes/no": "yes" if dependency.ready else "no",
                "next safe AI action": plan.next_safe_ai_action,
                "final approval required": plan.final_approval_required,
                "final approval required yes/no": "yes" if plan.final_approval_required else "no",
                "execution eligibility": dependency.execution_eligibility,
                "READY": dependency.ready,
                "MISSING_FIELDS": dependency.missing_fields,
                "NEEDS_CONNECTOR": dependency.needs_connector,
                "READY_FOR_APPROVAL": dependency.ready_for_approval,
                "MANUAL_ONLY": dependency.manual_only,
                "readiness": plan.readiness,
            }
        )
    show_dataframe(pd.DataFrame(plan_rows))

    st.markdown("**Autofill-Ready Opportunities**")
    ready_rows = [row for row in plan_rows if row["readiness"] == "autofill_ready"]
    show_dataframe(pd.DataFrame(ready_rows)) if ready_rows else st.write("None yet.")

    st.markdown("**Opportunities Blocked By Login**")
    login_rows = [row for row in plan_rows if row["readiness"] == "blocked_by_login"]
    show_dataframe(pd.DataFrame(login_rows)) if login_rows else st.write("None.")

    st.markdown("**Opportunities Blocked By Missing User Context**")
    context_rows = [row for row in plan_rows if row["readiness"] == "blocked_by_missing_context"]
    show_dataframe(pd.DataFrame(context_rows)) if context_rows else st.write("None.")

    st.markdown("**Opportunities Requiring Final Approval**")
    final_rows = [row for row in plan_rows if row["final approval required"]]
    show_dataframe(pd.DataFrame(final_rows)) if final_rows else st.write("None.")


def show_final_approval_queue(conn: sqlite3.Connection) -> None:
    items = build_final_approval_queue(rows_for_final_approval(conn))
    st.markdown("**Final Approval Queue**")
    st.caption(
        "Prepared actions that still require owner consent. Sensitive actions are never auto-submitted."
    )
    if not items:
        st.write("No final approval items are currently queued.")
        return

    counts: dict[str, int] = {}
    for item in items:
        counts[item.final_action_type] = counts.get(item.final_action_type, 0) + 1
    cols = st.columns(min(5, max(1, len(counts))))
    for index, (action_type, count) in enumerate(sorted(counts.items())):
        cols[index % len(cols)].metric(action_type.replace("_", " ").title(), count)

    rows = []
    for item in items:
        rows.append(
            {
                "id": item.claim_queue_id,
                "opportunity title": item.opportunity_title,
                "expected gain/value": item.expected_gain_value,
                "risk level": item.risk_level,
                "why approval is required": item.why_approval_required,
                "what AI already prepared": item.what_ai_already_prepared,
                "what happens if approved": item.what_happens_if_approved,
                "what happens if rejected": item.what_happens_if_rejected,
                "official link": item.official_link,
                "final action type": item.final_action_type,
                "safe to mark submitted": item.safe_to_mark_submitted,
            }
        )
    show_dataframe(pd.DataFrame(rows))

    st.markdown("**Final Approval Actions**")
    labels = {
        item.claim_queue_id: f"{item.claim_queue_id} - {item.final_action_type.replace('_', ' ').title()} - {item.opportunity_title[:90]}"
        for item in items
    }
    selected_id = st.selectbox(
        "Final approval item",
        options=list(labels.keys()),
        format_func=lambda item_id: labels[item_id],
    )
    selected_item = next(item for item in items if item.claim_queue_id == selected_id)
    st.write(selected_item.why_approval_required)
    st.write(selected_item.what_ai_already_prepared)
    details = load_claim_detail(conn, selected_item.claim_queue_id)
    if details:
        show_vault_data_preview(dict(details))
    consent_store = SubmissionConsentStore.for_root(ROOT_DIR)
    existing_consent = consent_store.consent_for(selected_item.claim_queue_id)
    live_submit_checkbox = False
    if selected_item.safe_to_mark_submitted:
        st.markdown("**Optional AI Live Submit Authorization**")
        st.caption(
            "Authorize AI to complete this low-risk prepared form path after approval. "
            "This excludes payment, purchase, legal, tax, identity, wallet-signing, and account-connection actions."
        )
        live_submit_checkbox = st.checkbox(
            "I authorize AI live-submit for this selected low-risk prepared form after final approval.",
            value=bool(existing_consent.get("allowed")),
            key=f"live_submit_consent_{selected_item.claim_queue_id}",
        )
        if existing_consent.get("allowed"):
            st.caption(f"Existing live-submit consent recorded: {existing_consent.get('created_at')}")
    action = st.selectbox(
        "Final approval action",
        ["Approve Final Step", "Reject", "Later", "Needs More Info"],
    )
    if st.button("Apply final approval action"):
        live_submit_saved = False
        if action == "Approve Final Step" and live_submit_checkbox:
            allowed, reason = can_live_submit(selected_item.final_action_type, selected_item.risk_level, live_submit_checkbox)
            if allowed:
                consent_store.save_consent(
                    new_consent(
                        selected_item.claim_queue_id,
                        str(load_autorun_control().get("execution_mode") or "Live Submit With Final Approval"),
                        "Owner authorized AI live-submit for this low-risk prepared form after final approval.",
                    )
                )
                live_submit_saved = True
                st.info(reason)
            else:
                st.warning(reason)
        note = apply_final_approval_action(conn, selected_item.claim_queue_id, selected_item.final_action_type, action)
        if live_submit_saved:
            details_after = load_claim_detail(conn, selected_item.claim_queue_id)
            if details_after:
                live_result = evaluate_live_submit(dict(details_after), consent_store.consent_for(selected_item.claim_queue_id))
                if live_result.allowed:
                    _apply_live_submit_result(conn, selected_item.claim_queue_id, live_result)
                    note = f"{note} Live-submit staged for browser execution."
        st.success(note)
        st.rerun()


def show_global_input_dependency_map(dependencies: list[object]) -> None:
    st.markdown("**Global Input Dependency Map**")
    if not dependencies:
        st.write("No repeated missing inputs are blocking the current queue.")
        return
    rows = []
    for dependency in dependencies:
        rows.append(
            {
                "unlock_score": dependency.unlock_score,
                "input": dependency.display_name,
                "unlocks": dependency.number_unblocked,
                "prompt": dependency.prompt,
                "value_score": dependency.value_score,
                "probability_score": dependency.probability_score,
                "target_section": dependency.target_section,
                "blocks": ", ".join(dependency.blocks[:8]),
            }
        )
    show_dataframe(pd.DataFrame(rows))

    st.markdown("**Highest-Leverage Missing Inputs**")
    for dependency in dependencies[:10]:
        cols = st.columns([3, 2, 2])
        cols[0].write(f"{dependency.display_name}: {dependency.prompt}")
        cols[1].write(f"Unlock score {dependency.unlock_score:.2f}")
        cols[2].button(
            f"Resolve {dependency.display_name}",
            key=f"resolve_dependency_{dependency.input_key}",
            on_click=_set_vault_open,
            args=(dependency.input_key,),
        )


def show_profile_completion_center(context: dict[str, object]) -> None:
    st.markdown("**Profile Completion Center**")
    focus = st.session_state.get("profile_completion_focus")
    if focus:
        st.caption(f"Focused on: {focus}")
    st.caption(
        "Passwords, full bank numbers, tax identifiers, identity documents, legal attestations, and purchases remain final-approval-only."
    )
    st.caption(
        "Owner Interaction Principle: add reusable inputs once, store them globally, and resume all blocked claims that depend on them."
    )
    profile = dict(context["profile"])
    shipping = dict(context["shipping"])
    payouts = dict(context["payouts"])
    wallets = dict(context["crypto_wallets"])
    accounts = dict(context["accounts"])
    business = dict(context.get("business", {}))
    preferences = dict(context["preferences"])

    with st.form("profile_completion_center_form"):
        tabs = st.tabs(
            [
                "Identity",
                "Shipping",
                "Payments",
                "Crypto",
                "Email Accounts",
                "Phone",
                "Social Accounts",
                "Business",
                "Tax",
                "Preferences",
            ]
        )
        with tabs[0]:
            profile["name"] = st.text_input("Name", value=str(profile.get("name") or ""), key="pcc_name")
            profile["date_of_birth"] = st.text_input(
                "Date of birth optional",
                value=str(profile.get("date_of_birth") or ""),
                key="pcc_date_of_birth",
            )
        with tabs[1]:
            shipping = _text_section("pcc_shipping", SHIPPING_FIELDS, shipping)
        with tabs[2]:
            st.caption("Bank is label only. Do not enter account or routing numbers.")
            payouts = _text_section("pcc_payouts", PAYOUT_FIELDS, payouts)
        with tabs[3]:
            wallets = _text_section("pcc_crypto_wallets", CRYPTO_WALLET_FIELDS, wallets)
        with tabs[4]:
            profile["email"] = st.text_input("Primary email", value=str(profile.get("email") or ""), key="pcc_profile_email")
            accounts["google_email"] = st.text_input("Google email", value=str(accounts.get("google_email") or ""), key="pcc_google_email")
            accounts["microsoft_email"] = st.text_input(
                "Microsoft email",
                value=str(accounts.get("microsoft_email") or ""),
                key="pcc_microsoft_email",
            )
            accounts["amazon_email"] = st.text_input("Amazon email", value=str(accounts.get("amazon_email") or ""), key="pcc_amazon_email")
            accounts["paypal_email"] = st.text_input("PayPal email", value=str(accounts.get("paypal_email") or ""), key="pcc_paypal_email")
        with tabs[5]:
            profile["phone"] = st.text_input("Phone", value=str(profile.get("phone") or ""), key="pcc_phone")
        with tabs[6]:
            accounts["github_username"] = st.text_input(
                "GitHub username",
                value=str(accounts.get("github_username") or ""),
                key="pcc_github_username",
            )
            accounts["tiktok_username"] = st.text_input(
                "TikTok username",
                value=str(accounts.get("tiktok_username") or ""),
                key="pcc_tiktok_username",
            )
        with tabs[7]:
            business["business_name"] = st.text_input(
                "Business name",
                value=str(business.get("business_name") or ""),
                key="pcc_business_name",
            )
            business["website_domain"] = st.text_input(
                "Website/domain",
                value=str(business.get("website_domain") or ""),
                key="pcc_business_website_domain",
            )
            business["founder_name"] = st.text_input(
                "Founder name",
                value=str(business.get("founder_name") or ""),
                key="pcc_business_founder_name",
            )
            business["company_description"] = st.text_area(
                "Company description",
                value=str(business.get("company_description") or ""),
                key="pcc_business_company_description",
            )
            business["startup_stage"] = st.text_input(
                "Startup stage",
                value=str(business.get("startup_stage") or ""),
                key="pcc_business_startup_stage",
            )
            business["industry"] = st.text_input(
                "Industry",
                value=str(business.get("industry") or ""),
                key="pcc_business_industry",
            )
            business["ein_tax_placeholder"] = ""
            st.caption("Tax identifiers are not stored here. Tax-related opportunities remain final-approval-required.")
        with tabs[8]:
            st.warning("Tax information is not stored here. Tax-related opportunities remain final-approval-required.")
        with tabs[9]:
            preferences["preference_profile"] = _preference_profile_selector(
                "pcc",
                str(preferences.get("preference_profile") or "Balanced"),
                context,
            )
            preferences["open_to_everything"] = st.checkbox(
                f"Open To Everything Mode ({'● On' if preferences.get('open_to_everything') else '○ Off'})",
                value=bool(preferences.get("open_to_everything")),
                key="pcc_open_to_everything",
                disabled=preferences.get("preference_profile") != "Custom",
            )
            st.caption(
                "When enabled, AI may auto-discover, connect reusable context, pre-fill low-risk fields, and queue actions. "
                "Final submit still requires approval."
            )
            st.caption(
                "Sensitive actions remain blocked: identity, tax, payment authorization, purchase, legal agreement, and wallet signing."
            )
            preferences = _checkbox_section(
                "pcc_preferences",
                PREFERENCE_FIELDS,
                preferences,
                disabled=preferences.get("preference_profile") != "Custom",
            )

        if st.form_submit_button("Save Profile Completion Center"):
            context["profile"] = profile
            context["shipping"] = shipping
            context["payouts"] = payouts
            context["crypto_wallets"] = wallets
            context["accounts"] = accounts
            context["business"] = business
            context["preferences"] = preferences
            USER_CONTEXT_STORE.save(apply_preference_profile(context))
            SQLiteStore(DB_PATH).normalize_required_inputs()
            st.success("Profile Completion Center saved and action readiness refreshed.")
            st.rerun()


def show_user_context(conn: sqlite3.Connection) -> None:
    context = USER_CONTEXT_STORE.load()
    st.caption("Reusable owner context for safe preparation. Do not enter passwords or full bank account numbers.")
    show_open_to_everything_mode(context)
    show_user_context_completeness(context)

    with st.form("user_context_form"):
        st.markdown("**Profile**")
        context["profile"] = _text_section("profile", PROFILE_FIELDS, context["profile"])

        st.markdown("**Shipping**")
        context["shipping"] = _text_section("shipping", SHIPPING_FIELDS, context["shipping"])

        st.markdown("**Payouts**")
        st.caption("Bank is label only, such as 'primary checking'. Do not store account or routing numbers.")
        context["payouts"] = _text_section("payouts", PAYOUT_FIELDS, context["payouts"])

        st.markdown("**Crypto Wallets**")
        context["crypto_wallets"] = _text_section("crypto_wallets", CRYPTO_WALLET_FIELDS, context["crypto_wallets"])

        st.markdown("**Accounts / Connectors**")
        context["accounts"] = _text_section("accounts", ACCOUNT_FIELDS, context["accounts"])

        st.markdown("**Business / Startup Info**")
        context["business"] = _text_section(
            "business",
            [field for field in BUSINESS_FIELDS if field != "ein_tax_placeholder"],
            context.get("business", {}),
        )
        context["business"]["ein_tax_placeholder"] = ""
        st.text_input(
            "EIN/tax info placeholder",
            value="",
            placeholder="Sensitive - final approval only - not stored",
            disabled=True,
            key="business_ein_tax_placeholder_disabled",
        )
        st.caption("Tax identifiers are not stored here. Tax actions remain final-approval-required.")

        st.markdown("**Preferences**")
        preferences = dict(context["preferences"])
        preferences["preference_profile"] = _preference_profile_selector(
            "preferences",
            str(preferences.get("preference_profile") or "Balanced"),
            context,
            conn=conn,
        )
        is_custom = preferences.get("preference_profile") == "Custom"
        preferences["open_to_everything"] = st.checkbox(
            f"Open To Everything Mode ({'● On' if preferences.get('open_to_everything') else '○ Off'})",
            value=bool(preferences.get("open_to_everything")),
            key="preferences_open_to_everything_mode",
            disabled=not is_custom,
        )
        context["preferences"] = _checkbox_section(
            "preferences",
            PREFERENCE_FIELDS,
            preferences,
            disabled=not is_custom,
        )

        st.markdown("**Automation Limits**")
        automation = dict(context["automation_limits"])
        bool_fields = [field for field in AUTOMATION_LIMIT_FIELDS if field != "max_out_of_pocket_spend"]
        automation.update(
            _checkbox_section(
                "automation_limits",
                bool_fields,
                automation,
                disabled=context["preferences"].get("preference_profile") != "Custom",
            )
        )
        automation["max_out_of_pocket_spend"] = st.number_input(
            "Max out of pocket spend",
            min_value=0,
            value=int(automation.get("max_out_of_pocket_spend") or 0),
            step=1,
            key="automation_limits_max_out_of_pocket_spend",
            disabled=context["preferences"].get("preference_profile") != "Custom",
        )
        context["automation_limits"] = automation

        if st.form_submit_button("Save User Context"):
            USER_CONTEXT_STORE.save(apply_preference_profile(context))
            SQLiteStore(DB_PATH).normalize_required_inputs()
            st.success("User Context saved and input readiness refreshed.")
            st.rerun()

    st.markdown("**Redacted Preview**")
    st.json(redact_user_context(USER_CONTEXT_STORE.load()))


def show_open_to_everything_mode(context: dict[str, object]) -> None:
    enabled = bool(context.get("preferences", {}).get("open_to_everything"))
    marker = "● On" if enabled else "○ Off"
    st.markdown(f"**OPEN TO EVERYTHING MODE:** {marker}")
    if enabled:
        st.write(
            "AI may auto-discover, connect reusable context, pre-fill low-risk fields, and queue actions. "
            "Final submit still requires approval."
        )
    else:
        st.write("AI follows selected category preferences only.")
    st.caption(
        "Sensitive actions remain blocked: identity, tax, payment authorization, purchase, legal agreement, and wallet signing."
    )


def show_user_context_completeness(context: dict[str, object]) -> None:
    completeness = compute_completeness(context)
    st.markdown("**User Context Completeness**")
    score_cols = st.columns(4)
    score_cols[0].metric("Overall Automation Readiness", f"{completeness.automation_readiness_score:.1f}%")
    ordered_sections = [
        "profile",
        "shipping",
        "payouts",
        "crypto_wallets",
        "accounts",
        "business",
        "preferences",
        "automation_limits",
    ]
    for index, section in enumerate(ordered_sections):
        score_cols[(index + 1) % 4].metric(
            SECTION_LABELS[section],
            f"{completeness.sections[section].completion_percent:.1f}%",
        )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Missing Inputs**")
        if completeness.missing_inputs:
            st.write(", ".join(completeness.missing_inputs))
        else:
            st.write("No reusable context fields are currently missing.")
        st.markdown("**Highest-Impact Field To Add Next**")
        st.write(completeness.highest_impact_field_to_add_next)
        st.markdown("**Opportunity Categories Currently Blocked**")
        st.write(", ".join(completeness.blocked_opportunity_categories) or "None from selected preferences.")

    with col2:
        st.markdown("**What AI Can Already Do**")
        st.write(", ".join(completeness.what_ai_can_already_do))
        st.markdown("**What AI Cannot Do Yet**")
        st.write(", ".join(completeness.what_ai_cannot_do_yet))

    details = []
    for section in ordered_sections:
        item = completeness.sections[section]
        details.append(
            {
                "section": SECTION_LABELS[section],
                "completion_percent": item.completion_percent,
                "usable_for_ai_work": item.usable_for_ai_work,
                "missing_fields": ", ".join(item.missing_fields),
                "sensitive_blockers": ", ".join(item.sensitive_blockers),
                "recommended_next_inputs": ", ".join(item.recommended_next_inputs),
            }
        )
    show_dataframe(pd.DataFrame(details))


def _text_section(section: str, fields: list[str], values: dict[str, object]) -> dict[str, object]:
    updated = dict(values)
    cols = st.columns(2)
    for index, field in enumerate(fields):
        with cols[index % 2]:
            updated[field] = st.text_input(
                _label(field),
                value=str(values.get(field) or ""),
                key=f"{section}_{field}",
            )
    return updated


def _checkbox_section(
    section: str,
    fields: list[str],
    values: dict[str, object],
    disabled: bool = False,
) -> dict[str, object]:
    updated = dict(values)
    cols = st.columns(3)
    for index, field in enumerate(fields):
        with cols[index % 3]:
            updated[field] = st.checkbox(
                _label(field),
                value=bool(values.get(field)),
                key=f"{section}_{field}",
                disabled=disabled,
            )
    return updated


def _label(field: str) -> str:
    return field.replace("_", " ").title()


def _preference_profile_selector(
    key_prefix: str,
    current_profile: str,
    context: dict[str, object],
    conn: sqlite3.Connection | None = None,
) -> str:
    if current_profile not in PREFERENCE_PROFILE_MODES:
        current_profile = "Balanced"
    selected = st.radio(
        "Preference Profile",
        options=PREFERENCE_PROFILE_MODES,
        index=PREFERENCE_PROFILE_MODES.index(current_profile),
        format_func=lambda mode: f"{'●' if mode == current_profile else '○'} {mode}",
        key=f"{key_prefix}_preference_profile",
    )
    st.caption(_preference_profile_behavior(selected))
    impact = _preference_profile_impact(selected, context, conn)
    cols = st.columns(3)
    cols[0].metric("Expected unlocked opportunities", impact["expected_unlocked_opportunities"])
    cols[1].metric("Estimated workload reduction", f"{impact['estimated_workload_reduction_percent']:.0f}%")
    cols[2].metric("Estimated automation coverage", f"{impact['estimated_automation_coverage_percent']:.0f}%")
    return selected


def _preference_profile_behavior(profile: str) -> str:
    return {
        "Minimal Input": "Ask only critical questions, avoid optional setup, and maximize safe automation.",
        "Balanced": "Use the current default behavior.",
        "Open To Everything": "Allow AI prep and discovery, reusable context sharing, and final approval for sensitive actions.",
        "Aggressive Growth": "Prioritize highest unlock score and maximum gain while keeping final approval gates.",
        "Privacy Focused": "Minimize connector sharing and autofill while preserving final approval gates.",
        "Custom": "Manually select individual permissions and categories.",
    }.get(profile, "Use the current default behavior.")


def _preference_profile_impact(
    profile: str,
    context: dict[str, object],
    conn: sqlite3.Connection | None,
) -> dict[str, float]:
    projected = json.loads(json.dumps(context, ensure_ascii=True))
    projected.setdefault("preferences", {})["preference_profile"] = profile
    projected = apply_preference_profile(projected)
    if conn is None:
        with connect() as owned_conn:
            return _preference_profile_impact(profile, projected, owned_conn)

    rows = rows_for_action_center(conn)
    dependencies = global_input_dependency_map(rows)
    eligible = _eligible_dependencies_for_profile(profile, dependencies)
    unlocked = {title for dependency in eligible for title in dependency.blocks}
    total = max(1, len(rows))
    completeness = compute_completeness(projected)
    profile_bonus = {
        "Minimal Input": 20,
        "Balanced": 0,
        "Open To Everything": 15,
        "Aggressive Growth": 25,
        "Privacy Focused": -10,
        "Custom": 0,
    }.get(profile, 0)
    workload_reduction = min(100.0, (len(unlocked) / total) * 100.0)
    automation_coverage = min(100.0, completeness.automation_readiness_score + profile_bonus)
    return {
        "expected_unlocked_opportunities": float(len(unlocked)),
        "estimated_workload_reduction_percent": workload_reduction,
        "estimated_automation_coverage_percent": automation_coverage,
    }


def _eligible_dependencies_for_profile(profile: str, dependencies: list[object]) -> list[object]:
    sensitive = {"tax_info", "identity_sensitive", "legal_attestation", "wallet_signing", "purchase_required"}
    reusable = [item for item in dependencies if item.input_key not in sensitive]
    if profile == "Minimal Input":
        return reusable[:3]
    if profile == "Balanced":
        return reusable[:5]
    if profile == "Open To Everything":
        return reusable
    if profile == "Aggressive Growth":
        return dependencies
    return reusable


def claim_status_control(conn: sqlite3.Connection) -> None:
    claim_ids = pd.read_sql_query(
        """
        SELECT cq.id, cq.status, o.title, cq.expected_value_usd, cq.fastest_gain_score
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        ORDER BY cq.updated_at DESC
        """,
        conn,
    )
    if claim_ids.empty:
        return

    with st.expander("Claim Queue Status Control"):
        labels = {
            int(row.id): f"{int(row.id)} - {row.status} - ${float(row.expected_value_usd or 0):,.0f} - {row.title[:90]}"
            for row in claim_ids.itertuples()
        }
        selected_id = st.selectbox(
            "Claim queue item",
            options=list(labels.keys()),
            format_func=lambda item_id: labels[item_id],
        )
        selected_action = st.selectbox("Claim action", list(STATUS_ACTIONS.keys()))
        details = load_claim_detail(conn, selected_id)

        if selected_action == "Approve" and details:
            st.markdown("**Exact Next Action**")
            st.write(details["exact_next_step"] or "Not prepared.")
            show_vault_data_preview(dict(details))
            st.markdown("**Copy/Paste Text**")
            st.code(details["copy_paste_form_answers"] or "No safe copy/paste text prepared.", language="text")
            st.markdown("**Official Link**")
            official_link = details["official_link"] or details["url"]
            if official_link:
                st.markdown(f"[Open official path]({official_link})")
            st.markdown("**AI/System Can Do Next**")
            st.write(
                details["ai_work_possible_now"]
                or details["what_ai_can_do"]
                or "No additional AI prep available yet."
            )
            st.markdown("**Final Accept/Receive Step**")
            st.write(details["final_acceptance_step"] or "Not prepared.")

        if st.button("Apply claim action"):
            apply_claim_status(conn, selected_id, STATUS_ACTIONS[selected_action])
            st.success("Claim status updated.")
            st.rerun()


def source_status_control(conn: sqlite3.Connection) -> None:
    candidates = pd.read_sql_query(
        """
        SELECT id, status, title, url, source_score_1_to_10
        FROM source_candidates
        WHERE status IN ('Found', 'Needs Approval', 'Later')
        ORDER BY source_score_1_to_10 DESC, updated_at DESC
        LIMIT 200
        """,
        conn,
    )
    if candidates.empty:
        return

    with st.expander("Source Queue Status Control"):
        labels = {
            int(row.id): f"{int(row.id)} - {row.status} - score {float(row.source_score_1_to_10 or 0):.1f} - {row.title[:90]}"
            for row in candidates.itertuples()
        }
        selected_id = st.selectbox(
            "Source candidate",
            options=list(labels.keys()),
            format_func=lambda item_id: labels[item_id],
        )
        selected_action = st.selectbox("Source action", list(SOURCE_ACTIONS.keys()))
        if st.button("Apply source action"):
            apply_source_status(conn, selected_id, SOURCE_ACTIONS[selected_action])
            st.success("Source status updated.")
            st.rerun()


def show_opportunities(conn: sqlite3.Connection) -> None:
    show_table(
        conn,
        """
        SELECT
            id, status, title, url, source_name, source_type,
            source_family, category_family, domain, root_domain,
            discovered_from, discovery_depth, source_lineage,
            real_asset_path, destination, expected_delivery_method,
            upfront_payment_required, net_loss_possible,
            fastest_gain_score, highest_value_score,
            final_acceptance_step, ai_work_possible_now,
            ai_work_completed, user_approval_needed,
            created_at, updated_at
        FROM opportunities
        ORDER BY updated_at DESC
        LIMIT 300
        """,
    )


def show_autonomy_status() -> None:
    status = load_autonomy_status()
    if not status:
        st.info("No autonomy status yet. Run `python src/main.py` once.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Last Run", status.get("last_run", "unknown"))
    col2.metric("Next Run", status.get("next_run", "unknown"))
    col3.metric("Schedule", status.get("schedule_frequency", "unknown"))
    col4.metric("Autonomy", "Enabled" if status.get("autonomy_enabled") else "Disabled")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Sources Searched", int(status.get("sources_searched", 0) or 0))
    col6.metric("New Candidates", int(status.get("new_candidates", 0) or 0))
    col7.metric("Opportunities Found", int(status.get("opportunities_found", 0) or 0))
    col8.metric("AI Work Completed", int(status.get("ai_work_completed", 0) or 0))

    col9, col10, col11 = st.columns(3)
    col9.metric("Approvals Needed", int(status.get("approvals_needed", 0) or 0))
    col10.metric("Ready to Accept", int(status.get("ready_to_accept", 0) or 0))
    col11.metric("Received/Paid", int(status.get("received_paid", 0) or 0))

    cost_guard = status.get("cost_guard", {}) or {}
    st.markdown("**Cost Guard Usage**")
    st.json(cost_guard)


def show_discovery_graph(conn: sqlite3.Connection) -> None:
    rules = dashboard_rules()
    rows = load_graph_claims(conn)
    analysis = DiversityGuard(rules).analyze(rows)

    st.markdown("**Diversity Warnings**")
    if analysis["warnings"]:
        for warning in analysis["warnings"]:
            st.warning(warning)
    else:
        st.success("No source family or root domain is above the configured diversity limit.")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Source Family Distribution**")
        show_dataframe(pd.DataFrame(analysis["source_family_distribution"]))
    with col2:
        st.markdown("**Category Family Distribution**")
        show_dataframe(pd.DataFrame(analysis["category_family_distribution"]))

    col3, col4 = st.columns(2)
    with col3:
        st.markdown("**Dominant Sources**")
        dominant = analysis["dominant_families"] + analysis["dominant_domains"]
        show_dataframe(pd.DataFrame(dominant))
    with col4:
        st.markdown("**Underrepresented Categories**")
        show_dataframe(pd.DataFrame({"category_family": analysis["underrepresented_categories"]}))

    st.markdown("**Exploration Queue**")
    queue_df = pd.read_sql_query(
        """
        SELECT category_family, priority_score, suggested_query, reason, status, updated_at
        FROM exploration_queue
        ORDER BY priority_score DESC, updated_at DESC
        LIMIT 50
        """,
        conn,
    )
    if queue_df.empty and analysis["exploration_queue"]:
        queue_df = pd.DataFrame(analysis["exploration_queue"])
    show_dataframe(queue_df)

    st.markdown("**Source Lineage**")
    show_table(
        conn,
        """
        SELECT
            id, title, url, source_family, category_family, root_domain,
            discovered_from, discovery_depth, source_lineage, updated_at
        FROM source_candidates
        WHERE source_lineage IS NOT NULL AND source_lineage != ''
        ORDER BY discovery_depth DESC, updated_at DESC
        LIMIT 100
        """,
    )

    st.markdown("**Top New Source Candidates**")
    show_table(
        conn,
        """
        SELECT
            id, status, title, url, source_score_1_to_10,
            expected_gain_potential_1_to_10, risk_level,
            source_family, category_family, root_domain,
            discovered_from, discovery_depth, query, decision_reason, updated_at
        FROM source_candidates
        ORDER BY COALESCE(source_score_1_to_10, 0) DESC, updated_at DESC
        LIMIT 100
        """,
    )


def load_autonomy_status() -> dict[str, object]:
    if not AUTONOMY_STATUS_PATH.exists():
        return {}
    try:
        return json.loads(AUTONOMY_STATUS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def show_opportunity_intelligence(conn: sqlite3.Connection) -> None:
    rows = load_rankable_claims(conn)
    if not rows:
        st.write("None yet.")
        return

    time_window = st.radio(
        "Time filter",
        options=list(opportunity_ranker.TIME_WINDOWS.keys()),
        index=3,
        horizontal=True,
    )
    rules = dashboard_rules()
    ranked = rank_opportunities(rows, time_window, rules)
    if not ranked:
        st.write(f"No ranked opportunities inside {time_window}.")
        return

    sections = [
        ("Top Fastest Gains", opportunity_ranker.top_fastest(ranked)),
        ("Top Highest Probability", opportunity_ranker.top_probability(ranked)),
        ("Top Highest Value", opportunity_ranker.top_value(ranked)),
        ("Top AI-Completable", opportunity_ranker.top_ai_completable(ranked)),
        ("Top Immediate Actions", opportunity_ranker.top_immediate_actions(ranked)),
    ]
    for title, items in sections:
        st.markdown(f"**{title}**")
        show_ranked_dataframe(items)


def show_lifecycle_tracker(conn: sqlite3.Connection) -> None:
    items = build_lifecycle_items(rows_for_lifecycle(conn))
    window = st.radio(
        "Follow-up filter",
        options=list(LIFECYCLE_TIME_WINDOWS.keys()),
        index=2,
        horizontal=True,
        key="lifecycle_window",
    )
    filtered = filter_lifecycle_items(items, window)
    summary = lifecycle_summary(filtered if window != "All" else items)
    st.markdown("**Lifecycle Tracker**")
    cols = st.columns(7)
    cols[0].metric("Pending value", f"${summary['total_estimated_pending_value']:,.0f}")
    cols[1].metric("Submitted value", f"${summary['submitted_value']:,.0f}")
    cols[2].metric("Processing value", f"${summary['processing_value']:,.0f}")
    cols[3].metric("Received value", f"${summary['received_value']:,.0f}")
    cols[4].metric("Paid value", f"${summary['paid_value']:,.0f}")
    cols[5].metric("Rejected value", f"${summary['rejected_value']:,.0f}")
    cols[6].metric("Dead ends", summary["dead_ends"])
    st.metric("Next follow-ups due", summary["next_followups_due"])

    rows = [item.to_dict() for item in (filtered if window != "All" else items)]
    show_dataframe(pd.DataFrame(rows))


def show_received_paid_tracking(conn: sqlite3.Connection) -> None:
    st.markdown("**Received / Paid**")
    st.caption("Only mark received or paid when the owner explicitly confirms it or reliable tracking confirms it.")
    rows = received_paid_rows(conn)
    show_dataframe(pd.DataFrame(rows)) if rows else st.write("No received/paid records yet.")

    ready = pd.read_sql_query(
        """
        SELECT
            cq.id,
            o.title,
            cq.gain_type,
            cq.expected_value_usd,
            cq.destination,
            cq.asset_destination,
            cq.status
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status IN ('Ready to Accept', 'Accepted', 'Submitted', 'Approved')
        ORDER BY cq.updated_at DESC
        LIMIT 200
        """,
        conn,
    )
    if ready.empty:
        return
    st.markdown("**Mark Explicitly Received/Paid**")
    labels = {
        int(row.id): f"{int(row.id)} - {row.status} - {row.title[:90]}"
        for row in ready.itertuples()
    }
    selected_id = st.selectbox(
        "Claim queue item",
        options=list(labels.keys()),
        format_func=lambda item_id: labels[item_id],
        key="received_paid_claim_id",
    )
    selected = ready[ready["id"] == selected_id].iloc[0]
    received_type = st.text_input("Received type", value=str(selected.get("gain_type") or ""), key="received_type")
    estimated_value = st.number_input(
        "Estimated value USD",
        min_value=0.0,
        value=float(selected.get("expected_value_usd") or 0),
        step=1.0,
        key="received_value",
    )
    destination = st.text_input(
        "Destination",
        value=str(selected.get("asset_destination") or selected.get("destination") or ""),
        key="received_destination",
    )
    note = st.text_area("Proof or reference note", value="", key="received_note")
    if st.button("Mark Received/Paid"):
        mark_received_paid(conn, selected_id, received_type, estimated_value, destination, note)
        SQLiteStore(DB_PATH).normalize_required_inputs()
        st.success("Marked Received/Paid.")
        st.rerun()


def show_destination_routing(conn: sqlite3.Connection) -> None:
    rows = load_destination_claims(conn)
    if not rows:
        st.write("None yet.")
        return
    ranked = rank_opportunities(rows, "30 Days", dashboard_rules())[:50]
    st.caption("High-priority routed opportunities, sorted by current opportunity intelligence priority.")
    show_destination_dataframe(ranked)


def show_acceptance_statuses(conn: sqlite3.Connection, acceptance_statuses: list[str], limit: int = 200) -> None:
    rows = [
        row
        for row in load_destination_claims(conn, limit=limit)
        if row["acceptance_status"] in acceptance_statuses
    ]
    if not rows:
        st.write("None yet.")
        return
    ranked = rank_opportunities(rows, "30 Days", dashboard_rules())
    show_destination_dataframe(ranked)


def show_input_statuses(conn: sqlite3.Connection, input_statuses: list[str], limit: int = 200) -> None:
    placeholders = ",".join("?" for _ in input_statuses)
    params: list[object] = [*input_statuses, limit]
    df = pd.read_sql_query(
        f"""
        SELECT
            cq.id,
            cq.status,
            cq.input_status,
            o.title,
            o.url,
            cq.required_inputs,
            cq.available_inputs AS what_ai_already_has,
            cq.missing_inputs AS what_is_missing,
            cq.sensitive_inputs,
            cq.owner_input_required AS what_user_must_provide,
            cq.ai_next_action AS what_ai_can_do_next,
            cq.final_acceptance_step AS final_approval_needed,
            cq.acceptance_status,
            cq.destination_type,
            cq.asset_type,
            cq.asset_destination,
            cq.expected_value_usd,
            cq.probability_score_1_to_10,
            cq.fastest_gain_score,
            cq.highest_value_score,
            cq.exact_next_step,
            cq.official_link,
            cq.updated_at
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.input_status IN ({placeholders})
        ORDER BY cq.fastest_gain_score DESC, cq.probability_score_1_to_10 DESC, cq.updated_at DESC
        LIMIT ?
        """,
        conn,
        params=params,
    )
    if not df.empty:
        df.insert(3, "readiness_badge", df["input_status"].map(input_status_badge))
    show_dataframe(df)


def show_execution_statuses(
    conn: sqlite3.Connection,
    execution_statuses: list[str],
    include_received: bool = False,
    limit: int = 200,
) -> None:
    placeholders = ",".join("?" for _ in execution_statuses)
    params: list[object] = list(execution_statuses)
    status_clause = f"cq.execution_status IN ({placeholders})"
    if include_received:
        status_clause = f"({status_clause} OR cq.status IN ('Accepted', 'Received/Paid'))"
    params.append(limit)
    df = pd.read_sql_query(
        f"""
        SELECT
            cq.id,
            cq.status,
            cq.execution_status,
            o.title,
            o.url,
            cq.estimated_completion_percent,
            cq.estimated_time,
            cq.human_input_needed,
            cq.next_action,
            cq.ai_work_completed,
            cq.ai_work_possible_now,
            cq.exact_next_step,
            cq.official_link,
            cq.final_acceptance_step,
            cq.destination_type,
            cq.asset_type,
            cq.acceptance_status,
            cq.asset_destination,
            cq.input_status,
            cq.required_inputs,
            cq.available_inputs,
            cq.missing_inputs,
            cq.sensitive_inputs,
            cq.expected_value_usd,
            cq.probability_score_1_to_10,
            cq.fastest_gain_score,
            cq.highest_value_score,
            cq.last_execution_at,
            cq.updated_at
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE {status_clause}
        ORDER BY cq.estimated_completion_percent DESC, cq.updated_at DESC
        LIMIT ?
        """,
        conn,
        params=params,
    )
    if not df.empty and "input_status" in df.columns:
        df.insert(2, "readiness_badge", df["input_status"].map(input_status_badge))
        context = USER_CONTEXT_STORE.load()
        dependencies = [dependency_for_opportunity(row, context) for row in df.to_dict("records")]
        df.insert(3, "Autofill Readiness", [item.autofill_readiness for item in dependencies])
        df.insert(4, "READY", [item.ready for item in dependencies])
        df.insert(5, "MISSING_FIELDS", [item.missing_fields for item in dependencies])
        df.insert(6, "NEEDS_CONNECTOR", [item.needs_connector for item in dependencies])
        df.insert(7, "READY_FOR_APPROVAL", [item.ready_for_approval for item in dependencies])
        df.insert(8, "MANUAL_ONLY", [item.manual_only for item in dependencies])
    show_dataframe(df)


def load_destination_claims(conn: sqlite3.Connection, limit: int = 500) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            o.title,
            o.url,
            cq.gain_type,
            cq.expected_value_usd,
            cq.probability_score,
            cq.probability_score_1_to_10,
            cq.risk_level,
            cq.time_to_gain,
            cq.time_to_gain_days,
            cq.owner_effort_minutes,
            cq.effort_score_1_to_10,
            cq.ai_can_do_percentage,
            cq.ai_can_do_percent,
            cq.fastest_gain_score,
            cq.highest_value_score,
            cq.required_user_action,
            cq.real_asset_path,
            cq.what_this_gain_is,
            cq.exact_next_step,
            cq.official_link,
            cq.final_acceptance_step,
            cq.expected_delivery_method,
            cq.destination,
            cq.destination_type,
            cq.asset_type,
            cq.acceptance_status,
            cq.asset_destination,
            cq.owner_input_required,
            cq.ai_next_action,
            cq.post_approval_action,
            cq.received_tracking_note,
            cq.input_status,
            cq.required_inputs,
            cq.available_inputs,
            cq.missing_inputs,
            cq.sensitive_inputs,
            o.source_family,
            o.category_family,
            o.domain,
            o.root_domain,
            o.discovered_from,
            o.discovery_depth,
            o.source_lineage,
            cq.updated_at
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later')
        ORDER BY cq.fastest_gain_score DESC, cq.highest_value_score DESC, cq.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["expected_asset"] = item.get("what_this_gain_is") or item.get("gain_type") or item.get("title")
    return items


def load_graph_claims(conn: sqlite3.Connection, limit: int = 500) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            o.title,
            o.url,
            cq.gain_type,
            cq.expected_value_usd,
            cq.probability_score_1_to_10,
            cq.risk_level,
            cq.time_to_gain_days,
            cq.effort_score_1_to_10,
            cq.ai_can_do_percent,
            cq.fastest_gain_score,
            cq.highest_value_score,
            o.source_family,
            o.category_family,
            o.domain,
            o.root_domain,
            o.discovered_from,
            o.discovery_depth,
            o.source_lineage
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later')
        ORDER BY cq.fastest_gain_score DESC, cq.highest_value_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def show_destination_dataframe(items: list[dict[str, object]]) -> None:
    if not items:
        st.write("None yet.")
        return
    columns = [
        "priority_score",
        "status",
        "acceptance_status",
        "title",
        "expected_asset",
        "asset_type",
        "destination_type",
        "asset_destination",
        "owner_input_required",
        "input_status",
        "available_inputs",
        "missing_inputs",
        "sensitive_inputs",
        "ai_next_action",
        "post_approval_action",
        "final_acceptance_step",
        "received_tracking_note",
        "official_link",
        "expected_value_usd",
        "time_to_gain_days",
        "ranking_reason",
        "source_family",
        "category_family",
        "root_domain",
    ]
    df = pd.DataFrame(items)
    display_columns = [column for column in columns if column in df.columns]
    show_dataframe(df[display_columns])


def load_rankable_claims(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            o.title,
            o.url,
            cq.gain_type,
            cq.expected_value_usd,
            cq.probability_score,
            cq.probability_score_1_to_10,
            cq.risk_level,
            cq.time_to_gain,
            cq.time_to_gain_days,
            cq.owner_effort_minutes,
            cq.effort_score_1_to_10,
            cq.ai_can_do_percentage,
            cq.ai_can_do_percent,
            cq.fastest_gain_score,
            cq.highest_value_score,
            cq.required_user_action,
            cq.real_asset_path,
            cq.exact_next_step,
            cq.official_link,
            cq.final_acceptance_step,
            cq.expected_delivery_method,
            cq.destination,
            cq.destination_type,
            cq.asset_type,
            cq.acceptance_status,
            cq.asset_destination,
            cq.owner_input_required,
            cq.ai_next_action,
            cq.post_approval_action,
            cq.received_tracking_note,
            cq.input_status,
            cq.required_inputs,
            cq.available_inputs,
            cq.missing_inputs,
            cq.sensitive_inputs,
            o.source_family,
            o.category_family,
            o.domain,
            o.root_domain,
            o.discovered_from,
            o.discovery_depth,
            o.source_lineage,
            cq.updated_at
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later')
        ORDER BY cq.updated_at DESC
        LIMIT 500
        """
    ).fetchall()
    return list(rows)


def show_ranked_dataframe(items: list[dict[str, object]]) -> None:
    if not items:
        st.write("None yet.")
        return
    columns = [
        "priority_score",
        "value_score",
        "speed_score",
        "success_probability",
        "ai_completion_percent",
        "risk_score",
        "effort_required",
        "base_priority_score",
        "diversity_adjustment",
        "diversity_reason",
        "ranking_reason",
        "source_family",
        "category_family",
        "root_domain",
        "status",
        "title",
        "expected_value_usd",
        "time_to_gain_days",
        "input_status",
        "missing_inputs",
        "sensitive_inputs",
        "exact_next_step",
        "official_link",
        "destination",
    ]
    df = pd.DataFrame(items)
    display_columns = [column for column in columns if column in df.columns]
    show_dataframe(df[display_columns])


def show_queue(
    conn: sqlite3.Connection,
    statuses: list[str] | None = None,
    order_by: str = "cq.updated_at DESC",
    limit: int = 50,
) -> None:
    where = "WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later')"
    params: list[object] = []
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        where = f"WHERE cq.status IN ({placeholders})"
        params.extend(statuses)
    params.append(limit)

    df = pd.read_sql_query(
        f"""
        SELECT
            cq.id,
            cq.status,
            o.title,
            o.url,
            cq.gain_type,
            cq.expected_value_usd,
            cq.probability_score_1_to_10,
            cq.risk_level,
            cq.time_to_gain,
            cq.time_to_gain_days,
            cq.effort_score_1_to_10,
            cq.ai_can_do_percent,
            cq.fastest_gain_score,
            cq.highest_value_score,
            cq.real_asset_path,
            cq.destination,
            cq.expected_delivery_method,
            cq.what_this_gain_is,
            cq.why_real_asset_value,
            cq.exact_next_step,
            cq.ai_work_possible_now,
            cq.ai_work_completed,
            cq.user_approval_needed,
            cq.copy_paste_form_answers,
            cq.claim_instructions,
            cq.official_link,
            cq.final_acceptance_step,
            cq.follow_up_tracking_step,
            cq.recommended_status,
            cq.execution_status,
            cq.estimated_completion_percent,
            cq.estimated_time,
            cq.human_input_needed,
            cq.next_action,
            cq.last_execution_at,
            cq.destination_type,
            cq.asset_type,
            cq.acceptance_status,
            cq.asset_destination,
            cq.owner_input_required,
            cq.ai_next_action,
            cq.post_approval_action,
            cq.received_tracking_note,
            cq.input_status,
            cq.required_inputs,
            cq.available_inputs,
            cq.missing_inputs,
            cq.sensitive_inputs,
            o.source_family,
            o.category_family,
            o.domain,
            o.root_domain,
            o.discovered_from,
            o.discovery_depth,
            o.source_lineage,
            cq.updated_at
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        {where}
        ORDER BY {order_by}
        LIMIT ?
        """,
        conn,
        params=params,
    )
    if not df.empty and "input_status" in df.columns:
        df.insert(2, "readiness_badge", df["input_status"].map(input_status_badge))
    show_dataframe(df)


def show_table(conn: sqlite3.Connection, query: str) -> None:
    show_dataframe(pd.read_sql_query(query, conn))


def show_dataframe(df: pd.DataFrame) -> None:
    if df.empty:
        st.write("None yet.")
        return
    st.dataframe(df, width="stretch", hide_index=True)


def load_claim_detail(conn: sqlite3.Connection, claim_queue_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT cq.*, o.title, o.url
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.id=?
        """,
        (claim_queue_id,),
    ).fetchone()


def apply_claim_status(conn: sqlite3.Connection, claim_queue_id: int, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    opportunity = conn.execute(
        "SELECT opportunity_id FROM claim_queue WHERE id=?",
        (claim_queue_id,),
    ).fetchone()
    conn.execute(
        "UPDATE claim_queue SET status=?, updated_at=? WHERE id=?",
        (status, now, claim_queue_id),
    )
    if opportunity:
        conn.execute(
            "UPDATE opportunities SET status=?, updated_at=? WHERE id=?",
            (status, now, opportunity["opportunity_id"]),
        )
    if status == "Received/Paid":
        existing = conn.execute(
            "SELECT id FROM received_log WHERE claim_queue_id=?",
            (claim_queue_id,),
        ).fetchone()
        if not existing:
            claim = conn.execute(
                "SELECT gain_type, expected_value_usd, destination FROM claim_queue WHERE id=?",
                (claim_queue_id,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO received_log (
                    claim_queue_id, received_type, estimated_value_usd,
                    destination, notes, received_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_queue_id,
                    claim["gain_type"] if claim else None,
                    claim["expected_value_usd"] if claim else None,
                    claim["destination"] if claim else None,
                    "Marked Received/Paid from dashboard.",
                    now,
                ),
            )
    if status == "Approved":
        details = load_claim_detail(conn, claim_queue_id)
        if details:
            result = ActionEngine().evaluate(dict(details))
            claim_status = result.claim_status
            if claim_status and claim_status != status:
                conn.execute(
                    "UPDATE claim_queue SET status=?, updated_at=? WHERE id=?",
                    (claim_status, now, claim_queue_id),
                )
                if opportunity:
                    conn.execute(
                        "UPDATE opportunities SET status=?, updated_at=? WHERE id=?",
                        (claim_status, now, opportunity["opportunity_id"]),
                    )
            conn.execute(
                """
                UPDATE claim_queue
                SET
                    execution_status=?,
                    estimated_completion_percent=?,
                    estimated_time=?,
                    human_input_needed=?,
                    next_action=?,
                    action_engine_json=?,
                    ai_work_completed=COALESCE(NULLIF(?, ''), ai_work_completed),
                    last_execution_at=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    result.execution_status,
                    result.estimated_completion_percent,
                    result.estimated_time,
                    result.human_input_needed,
                    result.next_action,
                    result.action_engine_json,
                    result.ai_work_completed,
                    now,
                    now,
                    claim_queue_id,
                ),
            )
    conn.commit()
    SQLiteStore(DB_PATH).normalize_required_inputs()


def apply_final_approval_action(
    conn: sqlite3.Connection,
    claim_queue_id: int,
    final_action_type: str,
    action: str,
) -> str:
    status = approval_result_status(final_action_type, action)
    note = approval_result_note(final_action_type, action)
    now = datetime.now(timezone.utc).isoformat()
    opportunity = conn.execute(
        "SELECT opportunity_id FROM claim_queue WHERE id=?",
        (claim_queue_id,),
    ).fetchone()
    conn.execute(
        """
        UPDATE claim_queue
        SET status=?, next_action=?, updated_at=?
        WHERE id=?
        """,
        (status, note, now, claim_queue_id),
    )
    if opportunity:
        conn.execute(
            "UPDATE opportunities SET status=?, updated_at=? WHERE id=?",
            (status, now, opportunity["opportunity_id"]),
        )
    conn.commit()
    SQLiteStore(DB_PATH).normalize_required_inputs()
    return note


def _apply_live_submit_result(conn: sqlite3.Connection, claim_queue_id: int, result: object) -> None:
    now = datetime.now(timezone.utc).isoformat()
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
            getattr(result, "status", "Processing"),
            getattr(result, "execution_status", "Processing"),
            getattr(result, "next_action", ""),
            getattr(result, "note", ""),
            getattr(result, "payload_json", "{}"),
            now,
            now,
            claim_queue_id,
        ),
    )
    conn.commit()


def apply_source_status(conn: sqlite3.Connection, source_candidate_id: int, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    candidate = conn.execute(
        "SELECT * FROM source_candidates WHERE id=?",
        (source_candidate_id,),
    ).fetchone()
    if not candidate:
        return

    conn.execute(
        "UPDATE source_candidates SET status=?, updated_at=? WHERE id=?",
        (status, now, source_candidate_id),
    )
    if status == "Approved":
        conn.execute(
            """
            INSERT INTO approved_sources (
                source_candidate_id, name, url, source_type, enabled,
                score_json, metadata, approved_at, updated_at
            )
            VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(url)
            DO UPDATE SET
                name=excluded.name,
                source_type=excluded.source_type,
                enabled=1,
                score_json=excluded.score_json,
                metadata=excluded.metadata,
                updated_at=excluded.updated_at
            """,
            (
                source_candidate_id,
                candidate["title"],
                candidate["url"],
                candidate["likely_source_type"] or "configured_url",
                candidate["score_json"],
                json.dumps(
                    {
                        "raw": json.loads(candidate["raw_json"] or "{}"),
                        "source_family": candidate["source_family"],
                        "category_family": candidate["category_family"],
                        "root_domain": candidate["root_domain"],
                        "discovered_from": candidate["discovered_from"],
                        "discovery_depth": candidate["discovery_depth"],
                        "source_lineage": candidate["source_lineage"],
                    },
                    ensure_ascii=True,
                ),
                now,
                now,
            ),
        )
    elif status == "Rejected":
        conn.execute(
            """
            INSERT OR IGNORE INTO rejected_sources (
                source_candidate_id, title, url, reason, score_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source_candidate_id,
                candidate["title"],
                candidate["url"],
                "Rejected from dashboard.",
                candidate["score_json"],
                now,
            ),
        )
    conn.commit()


if __name__ == "__main__":
    main()
