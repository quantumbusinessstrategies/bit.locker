from __future__ import annotations

import os
import json
import html
import hashlib
import hmac
import importlib
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from approval.final_approval_queue import (  # noqa: E402
    approval_result_note,
    approval_result_status,
    build_final_approval_queue,
    final_action_type,
    rows_for_final_approval,
)
from approval.final_approval_packet import build_final_approval_packet  # noqa: E402
from approval.submission_consent import SubmissionConsentStore, can_live_submit, new_consent  # noqa: E402
from autonomy.completion_engine import run_completion_engine_pass  # noqa: E402
from autonomy.autonomous_worker import run_autonomous_queue_pass  # noqa: E402
from autonomy.autonomy_pump import run_autonomy_pump  # noqa: E402
from autonomy.magic_money_scout import magic_money_lane_rows, run_magic_money_scout  # noqa: E402
from autofill.dependency_map import dependency_for_opportunity, dependency_graph_summary, dependency_map_for_opportunities  # noqa: E402
from autofill.autofill_planner import plan_autofill_for_opportunity, plan_autofill_for_opportunities, rows_for_autofill, summarize_autofill  # noqa: E402
from connectors.external_authorizations import (  # noqa: E402
    EXTERNAL_AUTHORIZATION_PROVIDERS,
    ExternalAuthorizationRecord,
    ExternalAuthorizationStore,
    external_authorization_rows,
)
from connectors.live_connector_sessions import (  # noqa: E402
    LIVE_CONNECTOR_PROVIDERS,
    live_connector_profile_dir,
    live_connector_rows,
    profile_for_url,
)
from connectors.connector_status import apply_external_authorizations, connected_accounts, connector_statuses, missing_connectors  # noqa: E402
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
import execution.browser_execution as browser_execution  # noqa: E402
import execution.browser_driver as browser_driver  # noqa: E402
from execution.live_submit_worker import evaluate_live_submit  # noqa: E402
from execution.live_assist_session import build_live_assist_session  # noqa: E402
from security.access_control import configured_users, user_lookup, verify_password  # noqa: E402
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
from user_context.external_wallet_routes import (  # noqa: E402
    apply_external_wallet_routes,
    load_external_wallet_routes,
    wallet_route_for_text,
)
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

connector_registry_module = importlib.reload(importlib.import_module("connectors.connector_registry"))
connector_status_module = importlib.reload(importlib.import_module("connectors.connector_status"))
required_inputs_module = importlib.reload(importlib.import_module("user_context.required_inputs"))
final_approval_queue_module = importlib.reload(importlib.import_module("approval.final_approval_queue"))
autofill_safety_module = importlib.reload(importlib.import_module("autofill.autofill_safety"))
autofill_planner_module = importlib.reload(importlib.import_module("autofill.autofill_planner"))
dependency_map_module = importlib.reload(importlib.import_module("autofill.dependency_map"))
autofill_execution_module = importlib.reload(importlib.import_module("execution.autofill_execution"))
account_worker_module = importlib.reload(importlib.import_module("execution.account_worker"))
routing_worker_module = importlib.reload(importlib.import_module("execution.routing_worker"))
form_worker_module = importlib.reload(importlib.import_module("execution.form_worker"))
browser_worker_module = importlib.reload(importlib.import_module("execution.browser_worker"))
browser_driver_module = importlib.reload(browser_driver)
submission_worker_module = importlib.reload(importlib.import_module("execution.submission_worker"))
live_assist_session_module = importlib.reload(importlib.import_module("execution.live_assist_session"))
action_engine_module = importlib.reload(importlib.import_module("execution.action_engine"))
autonomous_worker_module = importlib.reload(importlib.import_module("autonomy.autonomous_worker"))
completion_engine_module = importlib.reload(importlib.import_module("autonomy.completion_engine"))
autonomy_pump_module = importlib.reload(importlib.import_module("autonomy.autonomy_pump"))
magic_money_scout_module = importlib.reload(importlib.import_module("autonomy.magic_money_scout"))
sqlite_store_module = importlib.reload(importlib.import_module("storage.sqlite_store"))
browser_execution = importlib.reload(browser_execution)
SQLiteStore = sqlite_store_module.SQLiteStore
approval_result_note = final_approval_queue_module.approval_result_note
approval_result_status = final_approval_queue_module.approval_result_status
build_final_approval_queue = final_approval_queue_module.build_final_approval_queue
final_action_type = final_approval_queue_module.final_action_type
rows_for_final_approval = final_approval_queue_module.rows_for_final_approval
connected_accounts = connector_status_module.connected_accounts
connector_statuses = connector_status_module.connector_statuses
missing_connectors = connector_status_module.missing_connectors
apply_external_authorizations = connector_status_module.apply_external_authorizations
run_autonomous_queue_pass = autonomous_worker_module.run_autonomous_queue_pass
run_completion_engine_pass = completion_engine_module.run_completion_engine_pass
run_autonomy_pump = autonomy_pump_module.run_autonomy_pump
run_magic_money_scout = magic_money_scout_module.run_magic_money_scout
magic_money_lane_rows = magic_money_scout_module.magic_money_lane_rows
ActionEngine = action_engine_module.ActionEngine
dependency_for_opportunity = dependency_map_module.dependency_for_opportunity
dependency_graph_summary = dependency_map_module.dependency_graph_summary
dependency_map_for_opportunities = dependency_map_module.dependency_map_for_opportunities
plan_autofill_for_opportunity = autofill_planner_module.plan_autofill_for_opportunity
plan_autofill_for_opportunities = autofill_planner_module.plan_autofill_for_opportunities
rows_for_autofill = autofill_planner_module.rows_for_autofill
summarize_autofill = autofill_planner_module.summarize_autofill
input_status_badge = required_inputs_module.input_status_badge
BrowserExecutionStore = browser_execution.BrowserExecutionStore
build_browser_execution_plan = browser_execution.build_browser_execution_plan
build_live_assist_session = live_assist_session_module.build_live_assist_session
execute_safe_official_form = browser_execution.execute_safe_official_form
inspect_official_form = browser_execution.inspect_official_form
record_browser_execution_run = browser_execution.record_browser_execution_run
rows_for_browser_execution = browser_execution.rows_for_browser_execution
rows_for_browser_execution_candidates = browser_execution.rows_for_browser_execution_candidates
browser_driver_status = browser_driver_module.browser_driver_status
inspect_with_playwright = browser_driver_module.inspect_with_playwright


DB_PATH = Path(os.getenv("DATABASE_PATH", ROOT_DIR / "data" / "gain_entity.sqlite3"))
AUTONOMY_STATUS_PATH = ROOT_DIR / "data" / "autonomy_status.json"
AUTORUN_CONTROL_PATH = ROOT_DIR / "data" / "autorun_control.json"
DREAM_ASSETS_PATH = ROOT_DIR / "data" / "dream_assets.json"
AI_LABOR_RISK_CONSENT_PATH = ROOT_DIR / "data" / "ai_labor_risk_consent.json"
ENTITY_TREASURY_PATH = ROOT_DIR / "data" / "entity_treasury.json"
CHAOS_MODE_PATH = ROOT_DIR / "data" / "chaos_mode.json"
CHAOS_WORKER_STATUS_PATH = ROOT_DIR / "data" / "chaos_worker_status.json"
RULES_PATH = ROOT_DIR / "config" / "rules.yaml"
USER_CONTEXT_STORE = UserContextStore.for_root(ROOT_DIR)

AUTORUN_MODES = ["Conservative", "Balanced", "Aggressive", "Open-To-Everything"]
AUTORUN_EXECUTION_MODES = ["Dry Run", "Live Assist", "Live Submit With Final Approval"]
DEFAULT_AUTORUN_CONTROL = {"enabled": False, "mode": "Balanced", "execution_mode": "Dry Run"}
ACCESS_PIN_ENV_KEYS = ["QUANTUMGAINS_ACCESS_PIN", "GAIN_ENTITY_ACCESS_PIN", "STREAMLIT_ACCESS_PIN"]
ACCESS_PIN_HASH_ENV_KEYS = ["QUANTUMGAINS_ACCESS_PIN_HASH", "GAIN_ENTITY_ACCESS_PIN_HASH", "STREAMLIT_ACCESS_PIN_HASH"]
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
    if st.session_state.pop("force_dashboard_route", False):
        try:
            st.query_params.clear()
        except Exception:  # noqa: BLE001
            pass
        return False
    try:
        return str(st.query_params.get("page") or "").lower() == "vault"
    except Exception:  # noqa: BLE001
        return False


def _is_easy_route() -> bool:
    try:
        return str(st.query_params.get("page") or "").lower() == "easy"
    except Exception:  # noqa: BLE001
        return False


def _is_ai_labor_route() -> bool:
    try:
        return str(st.query_params.get("page") or "").lower() in {"ai_labor", "labor"}
    except Exception:  # noqa: BLE001
        return False


def _is_treasury_route() -> bool:
    try:
        return str(st.query_params.get("page") or "").lower() in {"treasury", "entity_treasury"}
    except Exception:  # noqa: BLE001
        return False


def _is_chaos_route() -> bool:
    try:
        return str(st.query_params.get("page") or "").lower() in {"chaos", "chaos_mode"}
    except Exception:  # noqa: BLE001
        return False


def _is_connectors_route() -> bool:
    try:
        return str(st.query_params.get("page") or "").lower() in {"connectors", "live_connectors"}
    except Exception:  # noqa: BLE001
        return False


def _go_to_dashboard() -> None:
    st.session_state["force_dashboard_route"] = True
    st.session_state["show_vault"] = False
    st.session_state["user_profile_vault_open"] = False
    st.session_state["operator_active_view"] = "opportunities"
    try:
        st.query_params.clear()
    except Exception:  # noqa: BLE001
        pass


def show_standalone_vault_route() -> None:
    top_cols = st.columns([4, 1])
    top_cols[0].title("QuantumGains Vault / Autofill Profile")
    with top_cols[1]:
        _dashboard_escape_button("Back to Dashboard")

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
            st.session_state["vault_focus"] = "Basic Profile"
            st.session_state["vault_field_group_selector"] = "Basic Profile"
        show_vault_operations_page(conn)
        show_global_page_links("vault")


def show_easy_asset_acquisition_route() -> None:
    top_cols = st.columns([3, 1, 1])
    top_cols[0].markdown(
        """
        <div class="easy-title-shell">
          <div class="easy-title">EASY ASSET ACQUISITION</div>
          <div class="easy-subtitle">Select assets -> push what can move -> route the rest -> approve final packets.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with top_cols[1]:
        st.link_button("Vault", "/?page=vault", use_container_width=True)
    with top_cols[2]:
        _dashboard_escape_button("Back")

    if not DB_PATH.exists():
        st.info(f"No database found at {DB_PATH}. Run `python src/main.py` first.")
        return

    store = SQLiteStore(DB_PATH)
    store.init_db()
    store.normalize_required_inputs()
    store.normalize_execution_state()

    with connect() as conn:
        rows = _easy_asset_rows(conn)
        ready_rows = _easy_ready_rows(conn)
        cols = st.columns(5)
        cols[0].metric("Asset Possibilities", len(rows))
        cols[1].metric("Ready / Approval", len(ready_rows))
        cols[2].metric("Ready For AI", sum(1 for row in rows if row.get("input_status") == "ready_for_ai_work"))
        cols[3].metric("Needs User Step", sum(1 for row in rows if row.get("input_status") in {"final_approval_required", "needs_connect", "missing_shipping", "missing_payout", "blocked"}))
        cols[4].metric("Value Surface", f"${sum(float(row.get('expected_value_usd') or 0) for row in rows):,.0f}")

        st.markdown(
            """
            <div class="easy-note">
              The big button advances every selected row as far as the current safety gates allow.
              Legal, tax, identity, payment authorization, purchases, wallet signing, and login gates are routed for owner action.
            </div>
            """,
            unsafe_allow_html=True,
        )
        _show_easy_autonomy_launchpad(conn)

        select_all = st.checkbox("Select all asset possibilities", key="easy_select_all_assets")
        selected_ids = _easy_asset_selector(rows, select_all)
        override_note = st.text_area(
            "Optional destination / payout / shipping note for selected assets",
            placeholder="Example: use default Vault shipping, PayPal in Vault, or route physical goods to the shipping address on file.",
            key="easy_destination_override",
        )
        run_options = st.columns([1.2, 1.2, 2.6])
        include_scout = run_options[0].checkbox(
            "Scout new easy routes",
            value=True,
            key="easy_include_scout",
            help="Adds another local scout pass before pushing the queue forward.",
        )
        allow_low_risk_live_submit = run_options[1].checkbox(
            "Try low-risk live submits",
            value=True,
            key="easy_allow_low_risk_live_submit",
            help=(
                "This records consent for selected low-risk final-submit rows only. "
                "Payment, purchase, legal, tax, identity, wallet signing, login, and human verification remain blocked."
            ),
        )
        run_options[2].caption(
            "No selection means EASY uses all visible asset rows. Mash repeatedly: it will keep moving safe work and route hard stops."
        )

        button_cols = st.columns([1, 2, 1])
        if button_cols[1].button("EASY ASSET ACQUISITION", key="easy_push_button", use_container_width=True):
            target_ids = selected_ids or [int(row["id"]) for row in rows]
            if not target_ids:
                st.warning("No asset rows are queued yet. Run scout first or add sources.")
            else:
                with st.spinner("Pushing gain engine until it hits a real safety/input gate..."):
                    result = _run_easy_gain_mash(
                        conn,
                        target_ids,
                        override_note,
                        include_scout=include_scout,
                        allow_low_risk_live_submit=allow_low_risk_live_submit,
                    )
                st.session_state["easy_last_result"] = result
                st.rerun()

        full_auto_cols = st.columns([1, 2, 1])
        if full_auto_cols[1].button("FULL AUTO UNTIL BLOCKED", key="easy_full_auto_until_blocked", use_container_width=True):
            with st.spinner("Running repeated safe acquisition passes until movement stops or an owner gate blocks the path..."):
                result = _run_easy_until_blocked(
                    conn,
                    selected_ids,
                    override_note,
                    include_scout=include_scout,
                    allow_low_risk_live_submit=allow_low_risk_live_submit,
                    use_all_visible=not bool(selected_ids),
                    max_rounds=4,
                )
            st.session_state["easy_last_result"] = result
            st.rerun()

        _show_easy_last_result()

        ready_cols = st.columns([1.4, 4])
        if ready_cols[0].button("READY NOW", key="easy_ready_now", use_container_width=True):
            st.session_state["easy_show_ready_panel"] = True
            st.rerun()
        ready_cols[1].caption(
            "Open final-disbursement approval for rows that are ready to accept, submit, process, or route to official final approval."
        )

        if st.session_state.get("easy_show_ready_panel"):
            _show_easy_ready_panel(conn, ready_rows, override_note)
        show_global_page_links("easy")


def show_ai_labor_engine_route() -> None:
    top_cols = st.columns([3, 1, 1])
    top_cols[0].markdown(
        """
        <div class="easy-title-shell ai-labor-title-shell">
          <div class="easy-title">AI LABOR ENGINE</div>
          <div class="easy-subtitle">Scan work -> seed executable labor -> AI preps/executes safe tasks -> route payouts and blockers.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with top_cols[1]:
        st.link_button("Vault", "/?page=vault", use_container_width=True)
    with top_cols[2]:
        _dashboard_escape_button("Back")

    if not DB_PATH.exists():
        st.info(f"No database found at {DB_PATH}. Run `python src/main.py` first.")
        return

    store = SQLiteStore(DB_PATH)
    store.init_db()
    store.normalize_required_inputs()
    store.normalize_execution_state()

    with connect() as conn:
        risk_consent = _load_ai_labor_risk_consent()
        risk_on_active = bool(risk_consent.get("risk_on_enabled"))
        snapshot = _ai_labor_snapshot(conn)
        cols = st.columns(5)
        cols[0].metric("Labor Lanes", len(_ai_labor_lanes(risk_on_active)))
        cols[1].metric("Queued Labor", snapshot["queued"])
        cols[2].metric("AI-Solo Candidates", snapshot["ai_solo"])
        cols[3].metric("Ready/Approval", snapshot["ready"])
        cols[4].metric("Submitted/Processing", snapshot["submitted_processing"])

        st.markdown(
            """
            <div class="easy-ready-panel ai-labor-panel">
              <div class="easy-ready-title">WORK THE INTERNET</div>
              <div class="easy-note">
                This pushes every AI-doable labor lane the system knows: gigs, bounties, paid research,
                testing, asset monetization, speculative watches, crypto/freebie quests, and reusable application work.
                Risk-on mode widens the net; sensitive/illegal/platform-bypass actions still stop.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        _show_ai_labor_risk_consent_panel(risk_consent)
        risk_consent = _load_ai_labor_risk_consent()
        risk_on_active = bool(risk_consent.get("risk_on_enabled"))

        option_cols = st.columns([1.2, 1.2, 1.2, 1.2, 2.4])
        vault_access = option_cols[0].toggle(
            "Vault access",
            value=bool(st.session_state.get("ai_labor_vault_access", True)),
            key="ai_labor_vault_access",
            help="Allows safe reusable Vault fields for prep/autofill. Does not expose passwords, private keys, SSNs, or bank numbers.",
        )
        live_submit = option_cols[1].toggle(
            "Low-risk live submit",
            value=bool(st.session_state.get("ai_labor_live_submit", False)),
            key="ai_labor_live_submit",
            help="Consent-gated attempts only for low-risk final_submit rows. No sensitive submits.",
        )
        risk_on = option_cols[2].toggle(
            "Risk-on lanes",
            value=risk_on_active,
            disabled=not risk_on_active,
            key="ai_labor_risk_on_toggle",
            help="Requires the signed risk consent below. Adds speculative/high-friction lanes and aggressive queueing.",
        )
        rescan_later = option_cols[3].toggle(
            "Rescan blocked later",
            value=True,
            key="ai_labor_rescan_later",
            help="Marks unfinished labor rows with explicit next actions instead of dropping them.",
        )
        option_cols[4].caption(
            "Turn Vault access on when you want AI to reuse safe profile/payout/public wallet/business fields. "
            "Risk-on adds volatile/high-friction work, but still routes authority-only gates to you."
        )
        treasury_route = st.text_area(
            "Treasury route / asset landing instruction",
            value=str(risk_consent.get("treasury_route") or ""),
            placeholder=(
                "Example: route cash to Vault payout preference, crypto to public wallet in Vault, "
                "credits to my platform accounts, physical goods to Vault shipping after approval."
            ),
            key="ai_labor_treasury_route",
        )
        st.caption(
            "Treasury routing is an instruction for asset landing/tracking. It is not a bank credential, seed phrase, private key, or payment authorization."
        )

        button_cols = st.columns([1, 2, 1])
        if button_cols[1].button("WORK THE INTERNET", key="ai_labor_work_button", use_container_width=True):
            with st.spinner("Scanning and pushing AI labor lanes through the safe acquisition pipeline..."):
                result = _run_ai_labor_engine(
                    conn,
                    vault_access=vault_access,
                    allow_low_risk_live_submit=live_submit,
                    mark_blocked_for_rescan=rescan_later,
                    risk_on=risk_on,
                    treasury_route=treasury_route,
                )
            st.session_state["ai_labor_last_result"] = result
            st.rerun()

        _show_ai_labor_result()
        _show_ai_labor_tables(conn)
        show_global_page_links("ai_labor")


def show_entity_treasury_route() -> None:
    top_cols = st.columns([3, 1, 1])
    top_cols[0].markdown(
        """
        <div class="easy-title-shell treasury-title-shell">
          <div class="easy-title">ENTITY TREASURY</div>
          <div class="easy-subtitle">One receiving layer for cash, credits, crypto, physical goods, and access-controlled assets.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with top_cols[1]:
        st.link_button("Vault", "/?page=vault", use_container_width=True)
    with top_cols[2]:
        _dashboard_escape_button("Back")

    if not DB_PATH.exists():
        st.info(f"No database found at {DB_PATH}. Run `python src/main.py` first.")
        return

    store = SQLiteStore(DB_PATH)
    store.init_db()
    store.normalize_required_inputs()
    store.normalize_execution_state()

    with connect() as conn:
        routes = _load_entity_treasury_routes()
        summary = _entity_treasury_summary(conn)
        st.markdown(
            """
            <div class="easy-ready-panel treasury-panel">
              <div class="easy-ready-title">WITHDRAWABLE PIGGY BANK</div>
              <div class="easy-note">
                Confirmed received/paid is the only number treated as withdrawable. Submitted/processing and ready/approval
                are pipeline value, not spendable money. This page routes assets like an entity account layer without storing
                passwords, seed phrases, full bank numbers, SSNs, or wallet signing keys.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        cols = st.columns(5)
        cols[0].metric("Withdrawable Now", f"${summary['withdrawable_value']:,.2f}", summary["withdrawable_count"])
        cols[1].metric("Submitted/Processing", f"${summary['submitted_value']:,.2f}", summary["submitted_count"])
        cols[2].metric("Ready To Authorize", f"${summary['ready_value']:,.2f}", summary["ready_count"])
        cols[3].metric("AI Labor Surface", f"${summary['ai_labor_value']:,.2f}", summary["ai_labor_count"])
        cols[4].metric("Treasury Routes", summary["configured_routes"])

        _show_entity_treasury_routes_editor(routes)
        updated_routes = _load_entity_treasury_routes()
        control_cols = st.columns([1.4, 1.4, 3])
        if control_cols[0].button("Apply Treasury Routes", use_container_width=True):
            changed = _apply_entity_treasury_routes(conn, updated_routes)
            st.success(f"Treasury routing applied to {changed} active queue rows.")
            st.rerun()
        if control_cols[1].button("Open Ready $$$", use_container_width=True):
            st.session_state["easy_show_ready_panel"] = True
            st.link_button("Go to EASY Ready", "/?page=easy", use_container_width=True)
        control_cols[2].caption(
            "Best practical setup: put PayPal/Stripe/Cash App/public wallet/shipping/business profile in Vault, then set this page as the default landing map."
        )

        _show_entity_treasury_real_rows(conn)
        _show_entity_treasury_setup_checklist(updated_routes)
        show_global_page_links("treasury")


def show_chaos_mode_route() -> None:
    top_cols = st.columns([3, 1, 1, 1])
    top_cols[0].markdown(
        """
        <div class="easy-title-shell chaos-title-shell">
          <div class="easy-title">CHAOS MODE</div>
          <div class="easy-subtitle">One switch: scan, seed, prep, route, execute consented safe work, treasury sync, repeat until stopped.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with top_cols[1]:
        st.link_button("Treasury", "/?page=treasury", use_container_width=True)
    with top_cols[2]:
        st.link_button("Connectors", "/?page=connectors", use_container_width=True)
    with top_cols[3]:
        _dashboard_escape_button("Back")

    if not DB_PATH.exists():
        st.info(f"No database found at {DB_PATH}. Run `python src/main.py` first.")
        return

    store = SQLiteStore(DB_PATH)
    store.init_db()
    store.normalize_required_inputs()
    store.normalize_execution_state()

    with connect() as conn:
        control = _load_chaos_control()
        risk_consent = _load_ai_labor_risk_consent()
        treasury = _entity_treasury_summary(conn)
        st.markdown(
            """
            <div class="chaos-panel">
              <div class="chaos-warning">WARNING: CHAOS MODE is aggressive automation, not guaranteed profit.</div>
              <div class="easy-note">
                It runs broad safe acquisition passes, AI labor lanes, treasury routing, final-approval routing,
                and consented low-risk browser execution. It still stops on illegal actions, fake identity, captcha/human
                bypass, platform-rule evasion, tax/legal/identity claims, payments, purchases, wallet signing, private keys,
                seed phrases, or full bank credentials.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        cols = st.columns(5)
        cols[0].metric("Chaos", "ON" if control.get("enabled") else "OFF")
        cols[1].metric("Cycles", int(control.get("cycle_count") or 0))
        cols[2].metric("Withdrawable", f"${float(treasury['withdrawable_value']):,.2f}")
        cols[3].metric("Submitted", f"${float(treasury['submitted_value']):,.2f}", treasury["submitted_count"])
        cols[4].metric("Ready", f"${float(treasury['ready_value']):,.2f}", treasury["ready_count"])

        config_cols = st.columns([1.2, 1.2, 1.2, 1.2, 2.2])
        use_vault = config_cols[0].toggle("Vault safe fields", value=bool(control.get("use_vault", True)), key="chaos_use_vault")
        live_submit = config_cols[1].toggle("Low-risk live submit", value=bool(control.get("low_risk_live_submit", False)), key="chaos_live_submit")
        risk_on = config_cols[2].toggle(
            "Risk-on lanes",
            value=bool(control.get("risk_on", False)) and bool(risk_consent.get("risk_on_enabled")),
            disabled=not bool(risk_consent.get("risk_on_enabled")),
            key="chaos_risk_on",
        )
        deep_scan = config_cols[3].toggle("Deep scan", value=bool(control.get("deep_scan", False)), key="chaos_deep_scan")
        interval_seconds = config_cols[4].selectbox(
            "Cycle interval",
            [60, 120, 300, 900],
            index=[60, 120, 300, 900].index(int(control.get("interval_seconds") or 120)) if int(control.get("interval_seconds") or 120) in [60, 120, 300, 900] else 1,
            format_func=lambda seconds: f"{seconds // 60} min" if seconds >= 60 else f"{seconds} sec",
            key="chaos_interval_seconds",
        )
        st.caption(
            "Deep scan can be slow. Low-risk live submit only attempts consented simple forms. Risk-on requires the AI Labor RISK-ON consent panel."
        )

        button_cols = st.columns([1, 2.5, 1])
        if control.get("enabled"):
            if button_cols[1].button("STOP CHAOS MODE", key="chaos_stop_button", use_container_width=True):
                control.update({"enabled": False, "stopped_at": datetime.now(timezone.utc).isoformat()})
                _save_chaos_control(control)
                st.rerun()
        else:
            if button_cols[1].button("CHAOS MODE", key="chaos_start_button", use_container_width=True):
                control.update(
                    {
                        "enabled": True,
                        "use_vault": bool(use_vault),
                        "low_risk_live_submit": bool(live_submit),
                        "risk_on": bool(risk_on),
                        "deep_scan": bool(deep_scan),
                        "interval_seconds": int(interval_seconds),
                        "started_at": datetime.now(timezone.utc).isoformat(),
                        "legal_warning_ack": True,
                    }
                )
                _save_chaos_control(control)
                st.rerun()

        run_cols = st.columns([1.2, 1.2, 3])
        force_run = run_cols[0].button("Run One Cycle Now", key="chaos_run_once", use_container_width=True)
        run_cols[1].link_button("Risk Consent", "/?page=ai_labor", use_container_width=True)
        run_cols[2].caption("Use Run One Cycle for supervised testing. Leave CHAOS MODE on only when you accept the warning and can monitor the machine.")

        _show_chaos_worker_controls(
            control,
            use_vault=bool(use_vault),
            low_risk_live_submit=bool(live_submit),
            risk_on=bool(risk_on),
            deep_scan=bool(deep_scan),
            interval_seconds=int(interval_seconds),
        )

        should_run, reason = _chaos_should_run(control, force_run)
        if should_run:
            with st.spinner("CHAOS MODE cycle running: scan -> seed -> prep -> route -> execute safe work -> treasury sync..."):
                result = _run_chaos_cycle(
                    conn,
                    use_vault=bool(use_vault),
                    low_risk_live_submit=bool(live_submit),
                    risk_on=bool(risk_on),
                    deep_scan=bool(deep_scan),
                )
                _record_chaos_result(control, result)
                st.session_state["chaos_last_result"] = result
            st.rerun()
        else:
            st.caption(reason)

        _show_chaos_last_result()
        _show_chaos_cycle_log()
        if control.get("enabled"):
            _chaos_auto_refresh(int(interval_seconds))
        show_global_page_links("chaos")


def show_live_connectors_route() -> None:
    top_cols = st.columns([3, 1, 1])
    top_cols[0].markdown(
        """
        <div class="easy-title-shell">
          <div class="easy-title">LIVE CONNECTORS</div>
          <div class="easy-subtitle">Log in once, save a local browser session, then Live Assist can reuse it for approved work.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    top_cols[1].link_button("Vault", "/?page=vault", use_container_width=True)
    with top_cols[2]:
        _dashboard_escape_button("Back")
    show_external_authorization_hub()
    show_global_page_links("connectors")


def _easy_asset_rows(conn: sqlite3.Connection, limit: int = 500) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            cq.execution_status,
            cq.input_status,
            cq.gain_type,
            o.title,
            o.root_domain,
            cq.expected_value_usd,
            cq.probability_score_1_to_10,
            cq.probability_score,
            cq.fastest_gain_score,
            cq.estimated_completion_percent,
            cq.asset_type,
            cq.destination_type,
            cq.destination,
            cq.asset_destination,
            cq.owner_effort_minutes,
            cq.time_to_gain_days,
            cq.missing_inputs,
            cq.sensitive_inputs,
            cq.next_action,
            cq.human_input_needed,
            cq.official_link,
            cq.updated_at
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
        ORDER BY
            CASE
                WHEN cq.input_status='ready_for_ai_work' THEN 0
                WHEN cq.execution_status='Ready To Accept' OR cq.status='Ready to Accept' THEN 1
                WHEN cq.input_status='final_approval_required' THEN 2
                WHEN cq.input_status IN ('needs_connect', 'missing_shipping', 'missing_payout', 'blocked') THEN 3
                ELSE 4
            END,
            COALESCE(cq.fastest_gain_score, 0) DESC,
            COALESCE(cq.expected_value_usd, 0) DESC,
            cq.updated_at DESC
        LIMIT ?
        """,
        (max(limit * 4, limit),),
    ).fetchall()
    ranked = sorted((dict(row) for row in rows), key=_instant_gain_priority)
    return ranked[:limit]


def _instant_gain_priority(row: dict[str, object]) -> tuple[object, ...]:
    """Rank rows for the actual run loop: instant-ish real assets first, biggest first, then random fallback."""
    primary_blob = _primary_signal_blob(row)
    blob = _row_blob(row)
    value = _safe_float(row.get("expected_value_usd"))
    probability = _safe_float(row.get("probability_score_1_to_10")) or _safe_float(row.get("probability_score"))
    effort_minutes = _safe_float(row.get("owner_effort_minutes"))
    time_days = _safe_float(row.get("time_to_gain_days"))
    ready = str(row.get("input_status") or "") == "ready_for_ai_work"
    ready_to_accept = str(row.get("execution_status") or "") == "Ready To Accept" or str(row.get("status") or "") == "Ready to Accept"
    instant_signal = _has_any(primary_blob, INSTANT_GAIN_TERMS)
    direct_asset_signal = _has_any(primary_blob, DIRECT_ASSET_TERMS) or (
        instant_signal and _has_any(blob, DIRECT_ASSET_TERMS)
    )
    slow_or_paper_signal = _has_any(primary_blob, SLOW_OR_PAPER_TERMS)
    credit_only_signal = _has_any(primary_blob, CREDIT_ONLY_TERMS)
    noise_or_info_signal = _has_any(primary_blob, NOISE_OR_INFO_TERMS)
    sensitive_signal = _has_any(primary_blob, SENSITIVE_APPROVAL_TERMS) or bool(str(row.get("sensitive_inputs") or "").strip())

    if noise_or_info_signal and not instant_signal:
        bucket = 6
    elif instant_signal and direct_asset_signal and not sensitive_signal and not slow_or_paper_signal:
        bucket = 0
    elif instant_signal and not sensitive_signal and not slow_or_paper_signal and not credit_only_signal:
        bucket = 1
    elif ready and ready_to_accept and not sensitive_signal and not slow_or_paper_signal:
        bucket = 2
    elif credit_only_signal:
        bucket = 4
    elif slow_or_paper_signal or sensitive_signal:
        bucket = 5
    else:
        bucket = 3

    effort_penalty = 0 if effort_minutes <= 5 else 1 if effort_minutes <= 15 else 2
    timing_penalty = 0 if time_days <= 0.25 else 1 if time_days <= 3 else 2
    random_rank = _stable_random_rank(row.get("id"))
    if bucket <= 2:
        return (
            bucket,
            -value,
            effort_penalty,
            timing_penalty,
            -probability,
            random_rank,
        )
    return (bucket, random_rank, -probability, -min(value, 500.0))


def _instant_gain_ids(conn: sqlite3.Connection, limit: int = 500) -> list[int]:
    return [int(row["id"]) for row in _easy_asset_rows(conn, limit=limit)]


def _claim_ids_not_browser_submitted(conn: sqlite3.Connection, claim_ids: list[int]) -> list[int]:
    clean_ids = list(dict.fromkeys(int(claim_id) for claim_id in claim_ids if str(claim_id).isdigit()))
    if not clean_ids:
        return []
    placeholders = ",".join("?" for _ in clean_ids)
    rows = conn.execute(
        f"SELECT id, status, execution_status, action_engine_json FROM claim_queue WHERE id IN ({placeholders})",
        clean_ids,
    ).fetchall()
    submitted = {int(row["id"]) for row in rows if _previous_browser_execution_submitted(dict(row))}
    return [claim_id for claim_id in clean_ids if claim_id not in submitted]


def _prioritized_claim_ids(conn: sqlite3.Connection, claim_ids: list[int], limit: int | None = None) -> list[int]:
    clean_ids = list(dict.fromkeys(int(claim_id) for claim_id in claim_ids if str(claim_id).isdigit()))
    if not clean_ids:
        return []
    placeholders = ",".join("?" for _ in clean_ids)
    rows = conn.execute(
        f"""
        SELECT
            cq.id,
            cq.status,
            cq.execution_status,
            cq.input_status,
            cq.gain_type,
            o.title,
            o.root_domain,
            cq.expected_value_usd,
            cq.probability_score_1_to_10,
            cq.probability_score,
            cq.fastest_gain_score,
            cq.asset_type,
            cq.destination_type,
            cq.destination,
            cq.asset_destination,
            cq.owner_effort_minutes,
            cq.time_to_gain_days,
            cq.missing_inputs,
            cq.sensitive_inputs,
            cq.next_action,
            cq.human_input_needed,
            cq.official_link
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.id IN ({placeholders})
        """,
        clean_ids,
    ).fetchall()
    ranked = [int(row["id"]) for row in sorted((dict(row) for row in rows), key=_instant_gain_priority)]
    return ranked[:limit] if limit else ranked


def _row_blob(row: dict[str, object]) -> str:
    keys = [
        "title",
        "root_domain",
        "gain_type",
        "asset_type",
        "destination_type",
        "destination",
        "asset_destination",
        "missing_inputs",
        "sensitive_inputs",
        "next_action",
        "human_input_needed",
        "official_link",
        "status",
        "execution_status",
        "input_status",
    ]
    return " ".join(str(row.get(key) or "") for key in keys).lower()


def _primary_signal_blob(row: dict[str, object]) -> str:
    keys = [
        "title",
        "root_domain",
        "gain_type",
        "next_action",
        "human_input_needed",
        "official_link",
    ]
    return " ".join(str(row.get(key) or "") for key in keys).lower()


def _has_any(blob: str, terms: tuple[str, ...]) -> bool:
    return any(term in blob for term in terms)


def _stable_random_rank(row_id: object) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    digest = hashlib.sha256(f"{today}:{row_id}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


INSTANT_GAIN_TERMS = (
    "cash",
    "paypal",
    "venmo",
    "payout",
    "paid study",
    "paid research",
    "survey",
    "focus group",
    "user testing",
    "usability",
    "reward",
    "gift card",
    "bounty",
    "freelance",
    "microtask",
    "sample",
    "freebie",
    "product test",
    "product testing",
    "tester",
    "beta",
)

DIRECT_ASSET_TERMS = (
    "paypal",
    "venmo",
    "cash",
    "gift card",
    "wallet",
    "crypto",
    "physical",
    "shipping",
    "sample",
    "freebie",
    "product",
    "payout",
)

NOISE_OR_INFO_TERMS = (
    "documentation",
    "overview",
    "skip to main content",
    "api reference",
    "developer docs",
    "docs",
    "guide",
    "learn",
    "pricing",
    "privacy",
    "terms of service",
    "wallet pass",
    "wallet passes",
    "health insurance cards",
    "hotel keys",
    "digital car keys",
    "multi-family keys",
)

CREDIT_ONLY_TERMS = (
    "cloud credit",
    "startup credit",
    "developer credit",
    "aws",
    "google cloud",
    "microsoft for startups",
    "vultr",
    "mongodb",
    "copilot",
)

SLOW_OR_PAPER_TERMS = (
    "class action",
    "settlement",
    "lawsuit",
    "legal",
    "unclaimed",
    "grant",
    "loan",
    "refund policy",
    "reimbursement",
    "mystery box",
    "sweepstakes",
    "lottery",
    "casino",
    "gambling",
    "sportsbook",
    "betting",
)

SENSITIVE_APPROVAL_TERMS = (
    "tax",
    "ssn",
    "social security",
    "identity",
    "kyc",
    "legal_attestation",
    "purchase",
    "payment authorization",
    "wallet signing",
)

LIVE_SUBMIT_DIRECT_ACTION_TERMS = (
    "request sample",
    "sample request",
    "free sample",
    "product testing",
    "product tester",
    "tester application",
    "paid study",
    "paid research",
    "user testing",
    "usability test",
    "focus group",
    "gift card",
    "reward",
    "redeem",
    "claim reward",
    "get paid",
    "apply",
    "sign up",
    "signup",
    "register",
    "join",
    "/claim",
    "/apply",
    "/signup",
    "/sign-up",
    "/register",
    "/join",
    "/redeem",
    "/samples",
    "/request",
    "request-sample",
    "product-testing",
    "participant",
)

LIVE_SUBMIT_TRUSTED_GAIN_URL_TERMS = (
    "centercode.com/tester-network",
    "usertesting.com/tester",
    "userinterviews.com/participants",
    "swagbucks.com",
    "dscout.com/participate",
    "respondent.io",
    "prolific.com",
    "trymata.com",
    "intellizoom.com",
    "usercrowd.com",
    "hometesterclub.com",
    "sampler.io",
    "product-testing.com/registration",
    "productsamples.com/join",
    "merchology.com/pages/free-sample-program",
    "letshighlight.com/apply-to-be-a-free-product-tester",
)

DISCOVERY_ONLY_LIVE_SUBMIT_TERMS = (
    "moneypantry.com",
    "thefreebieguy.com",
    "mysavings.com",
    "freebfinder.com",
    "moneypilot.com",
    "dollarbreak.com",
    "usatoday.com",
    "newsweek.com",
    "forbes.com",
    "guru99.com",
    "hip2save.com",
    "freestuffanddeals.com",
    "soscip.org",
    "xenonstack.com",
    "sammyapproves.com",
    "thewaystowealth.com",
    "sidehustles.com",
    "consumerfinance.gov/data-research",
    "costco.com/executive-rewards",
    "developers.google.com/wallet",
    "product-testing.com/products-samples",
    "linkedin.com/pulse",
    "linkedin.com/redir",
    "devpost.com/hackathons",
    "openclassactions.com",
    "classaction.org",
    "startupcredits.dev",
    "/blog",
    "/blogs",
    "/post",
    "/posts",
    "/article",
    "/articles",
    "/category",
    "/categories",
    "/news",
    "/faq",
    "/terms",
    "faq.asp",
    "membership terms",
    "skip to content",
    "page load link",
    "clinical trials",
)


def _easy_ready_rows(conn: sqlite3.Connection, limit: int = 250) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            cq.execution_status,
            cq.input_status,
            o.title,
            o.root_domain,
            cq.expected_value_usd,
            cq.asset_type,
            cq.destination_type,
            cq.destination,
            cq.asset_destination,
            cq.official_link,
            cq.next_action,
            cq.human_input_needed
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
          AND (
            cq.status IN ('Ready to Accept', 'Accepted', 'Submitted', 'Processing')
            OR cq.execution_status IN ('Ready To Accept', 'Processing')
            OR cq.input_status='final_approval_required'
          )
        ORDER BY COALESCE(cq.expected_value_usd, 0) DESC, cq.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _easy_asset_selector(rows: list[dict[str, object]], select_all: bool) -> list[int]:
    if not rows:
        st.write("No asset possibilities are currently queued.")
        return []
    df = pd.DataFrame(rows)
    display = pd.DataFrame(
        {
            "select": bool(select_all),
            "id": df["id"],
            "status": df["status"],
            "readiness": df["input_status"],
            "asset": df["title"],
            "value": df["expected_value_usd"].fillna(0),
            "probability": df["probability_score_1_to_10"].fillna(0),
            "asset_type": df["asset_type"].fillna(""),
            "destination": df["asset_destination"].fillna(df["destination"].fillna("")),
            "next": df["next_action"].fillna(df["human_input_needed"].fillna("")),
        }
    )
    edited = st.data_editor(
        display,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        disabled=[column for column in display.columns if column != "select"],
        column_config={
            "select": st.column_config.CheckboxColumn("Select"),
        },
        key=f"easy_asset_editor_{int(select_all)}",
    )
    return _selected_bulk_approval_ids(edited)


def _apply_easy_asset_push(
    conn: sqlite3.Connection,
    selected_ids: list[int],
    override_note: str,
) -> dict[str, object]:
    if override_note.strip():
        _apply_easy_destination_note(conn, selected_ids, override_note.strip())
    result = _apply_operator_selected_action(conn, selected_ids, "approve_possible_route_rest")
    output = str(result.get("output") or "")
    output += "\n\nEASY route: selected assets were pushed to the next safe system step."
    result["label"] = "EASY ASSET ACQUISITION"
    result["output"] = output
    return result


def _apply_easy_destination_note(conn: sqlite3.Connection, selected_ids: list[int], note: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for claim_id in selected_ids:
        conn.execute(
            """
            UPDATE claim_queue
            SET asset_destination=COALESCE(NULLIF(asset_destination, ''), ?),
                next_action=COALESCE(NULLIF(next_action, ''), ?),
                updated_at=?
            WHERE id=?
            """,
            (note, f"Use owner-provided EASY destination note: {note}", now, int(claim_id)),
        )
    conn.commit()


def _show_easy_last_result() -> None:
    result = st.session_state.get("easy_last_result")
    if not isinstance(result, dict):
        return
    output = str(result.get("output") or "")
    applied = _extract_result_count(output, "Applied")
    routed = _extract_result_count(output, "Routed")
    skipped = _extract_result_count(output, "Skipped")
    submitted_external = int(result.get("submitted_external") or _extract_result_count(output, "Submitted External"))
    if applied or routed or submitted_external:
        st.success(
            f"EASY push finished: {applied} advanced, {routed} routed, "
            f"{submitted_external} externally submitted, {skipped} skipped."
        )
    else:
        st.warning(f"EASY push ran, but nothing advanced. Skipped: {skipped}.")
    before = result.get("snapshot_before")
    after = result.get("snapshot_after")
    if isinstance(before, dict) and isinstance(after, dict):
        cols = st.columns(5)
        cols[0].metric("Queue Rows", after.get("claim_queue", 0), int(after.get("claim_queue", 0) or 0) - int(before.get("claim_queue", 0) or 0))
        cols[1].metric("Ready AI", after.get("ready_for_ai_work", 0), int(after.get("ready_for_ai_work", 0) or 0) - int(before.get("ready_for_ai_work", 0) or 0))
        cols[2].metric("Ready/Approval", after.get("ready_accept", 0), int(after.get("ready_accept", 0) or 0) - int(before.get("ready_accept", 0) or 0))
        cols[3].metric("Submitted", after.get("submitted", 0), int(after.get("submitted", 0) or 0) - int(before.get("submitted", 0) or 0))
        cols[4].metric("Received/Paid", after.get("received_paid", 0), int(after.get("received_paid", 0) or 0) - int(before.get("received_paid", 0) or 0))
    with st.expander("EASY push details", expanded=False):
        st.code(output[-6000:] or "No details.", language="text")


def _show_easy_ready_panel(
    conn: sqlite3.Connection,
    rows: list[dict[str, object]],
    override_note: str,
) -> None:
    st.markdown(
        """
        <div class="easy-ready-panel">
          <div class="easy-ready-title">FINAL DISBURSEMENT APPROVAL</div>
          <div class="easy-note">
            Review ready rows before the final push. The $$$ button approves safe final packets and routes owner-only gates;
            it does not bypass payment, legal, tax, identity, wallet signing, purchase, login, or platform rules.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not rows:
        st.info("Nothing is ready for final approval/disbursement yet.")
        return
    select_all = st.checkbox("Select all ready items", value=True, key="easy_ready_select_all")
    df = pd.DataFrame(rows)
    display = pd.DataFrame(
        {
            "select": bool(select_all),
            "id": df["id"],
            "status": df["status"],
            "readiness": df["input_status"],
            "asset": df["title"],
            "value": df["expected_value_usd"].fillna(0),
            "destination": df["asset_destination"].fillna(df["destination"].fillna("")),
            "next": df["next_action"].fillna(df["human_input_needed"].fillna("")),
        }
    )
    edited = st.data_editor(
        display,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        disabled=[column for column in display.columns if column != "select"],
        column_config={"select": st.column_config.CheckboxColumn("Select")},
        key=f"easy_ready_editor_{int(select_all)}",
    )
    selected_ids = _selected_bulk_approval_ids(edited)
    cols = st.columns([1, 2, 1])
    if cols[1].button("$$$", key="easy_money_button", use_container_width=True):
        if not selected_ids:
            st.warning("Select at least one ready item for final approval routing.")
        else:
            result = _apply_easy_final_money_push(conn, selected_ids, override_note)
            st.session_state["easy_last_result"] = result
            st.session_state["easy_show_ready_panel"] = True
            st.rerun()


def _apply_easy_final_money_push(
    conn: sqlite3.Connection,
    selected_ids: list[int],
    override_note: str,
) -> dict[str, object]:
    before = _easy_system_snapshot(conn)
    if override_note.strip():
        _apply_easy_destination_note(conn, selected_ids, override_note.strip())
    consent_summary = _grant_easy_low_risk_submit_consent(conn, selected_ids)
    result = _apply_operator_selected_action(conn, selected_ids, "approve_possible_route_rest")
    browser_result = _run_safe_browser_execution_batch(
        conn,
        limit=24,
        execution_mode_override="Live Submit With Final Approval",
    )
    submitted_external = _extract_json_int(str(browser_result.get("output") or ""), "submitted_external")
    after = _easy_system_snapshot(conn)
    result["label"] = "EASY FINAL $$$"
    result["submitted_external"] = submitted_external
    result["snapshot_before"] = before
    result["snapshot_after"] = after
    result["output"] = "\n".join(
        [
            str(result.get("output") or ""),
            "",
            "Low-risk live-submit consent:",
            json.dumps(consent_summary, ensure_ascii=True, indent=2),
            "",
            "Browser/live-submit execution:",
            str(browser_result.get("output") or "")[-5000:],
            "",
            "$$$ final push: safe final approvals were advanced; consented low-risk browser submits were attempted; owner-only gates were routed for explicit approval.",
            f"Submitted External: {submitted_external}",
        ]
    )
    return result


def _show_easy_autonomy_launchpad(conn: sqlite3.Connection) -> None:
    snapshot = _easy_system_snapshot(conn)
    actions = _easy_owner_next_actions(conn)
    ai_push_now = int(snapshot.get("ready_for_ai_work", 0) or 0)
    ready_accept = int(snapshot.get("ready_accept", 0) or 0)
    blocked = int(snapshot.get("blocked_or_input", 0) or 0)
    submitted = int(snapshot.get("submitted", 0) or 0) + int(snapshot.get("processing", 0) or 0)
    st.markdown(
        """
        <div class="easy-ready-panel">
          <div class="easy-ready-title">ONE BUTTON ACQUISITION LAUNCHPAD</div>
          <div class="easy-note">
            Goal: AI does all safe work, then collapses the rest into the smallest possible owner actions.
            Press FULL AUTO UNTIL BLOCKED, resolve the top blocker once, then press it again.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    cols[0].metric("AI Can Push Now", ai_push_now)
    cols[1].metric("Approval Clicks Waiting", ready_accept)
    cols[2].metric("Owner Blockers", blocked)
    cols[3].metric("Submitted/Processing", submitted)
    if not actions:
        st.success("No owner blocker is visible right now. Press FULL AUTO UNTIL BLOCKED to keep moving.")
        return
    st.markdown("**Exact Next Owner Moves**")
    for item in actions[:5]:
        with st.container(border=True):
            action_cols = st.columns([1.4, .7, .8, 2.2])
            action_cols[0].markdown(f"**{html.escape(str(item['label']))}**")
            action_cols[1].metric("Rows", int(item["count"]))
            action_cols[2].metric("Value", f"${float(item['value']):,.0f}")
            action_cols[3].write(str(item["action"]))
            st.caption("Examples: " + "; ".join(str(title) for title in item["examples"]))


def _run_easy_gain_mash(
    conn: sqlite3.Connection,
    selected_ids: list[int],
    override_note: str,
    *,
    include_scout: bool,
    allow_low_risk_live_submit: bool,
) -> dict[str, object]:
    selected_ids = _prioritized_claim_ids(conn, selected_ids, limit=len(selected_ids))
    before = _easy_system_snapshot(conn)
    output_parts: list[str] = [
        "EASY ASSET ACQUISITION - INSTANT/LARGEST FIRST",
        f"Selected/visible targets: {len(selected_ids)}",
        "Strategy: direct cash/withdrawable/physical assets first, largest first; slow/legal/credit-only lanes demoted.",
        "Timebox: no five-minute batch cap; fastest real-gain priority stays active.",
        f"Scout new easy routes: {include_scout}",
        f"Consent-gated low-risk live submit attempts: {allow_low_risk_live_submit}",
        "",
    ]

    if include_scout:
        conn.commit()
        scout_result = _run_magic_money_scout()
        output_parts.append("Scout pass:")
        output_parts.append(str(scout_result.get("output") or "")[-3000:])
        output_parts.append("")

    if override_note.strip():
        _apply_easy_destination_note(conn, selected_ids, override_note.strip())

    if allow_low_risk_live_submit:
        consent_summary = _grant_easy_low_risk_submit_consent(conn, selected_ids)
        output_parts.append("Low-risk live-submit consent:")
        output_parts.append(json.dumps(consent_summary, ensure_ascii=True, indent=2))
        output_parts.append("")

    triage_result = _apply_operator_selected_action(conn, selected_ids, "approve_possible_route_rest")
    triage_output = str(triage_result.get("output") or "")
    output_parts.append("Queue triage:")
    output_parts.append(triage_output[-5000:])
    output_parts.append("")

    context = load_effective_user_context()
    completion = run_completion_engine_pass(conn, context, mode="Live Assist", commit=True)
    autonomy = run_autonomous_queue_pass(
        conn,
        ROOT_DIR,
        {"enabled": True, "mode": "Open-To-Everything", "execution_mode": "Live Assist"},
    )
    conn.commit()
    output_parts.append("Completion engine:")
    output_parts.append(json.dumps(completion.to_dict(), ensure_ascii=True, indent=2))
    output_parts.append("")
    output_parts.append("Autonomous worker:")
    output_parts.append(json.dumps(autonomy.to_dict(), ensure_ascii=True, indent=2))
    output_parts.append("")

    if allow_low_risk_live_submit:
        browser_result = _run_safe_browser_execution_batch(
            conn,
            limit=18,
            execution_mode_override="Live Submit With Final Approval",
            batch_deadline_seconds=0,
        )
    else:
        browser_result = {
            "returncode": 0,
            "output": json.dumps(
                {
                    "submitted_external": 0,
                    "skipped": "Low-risk live-submit attempts were not enabled for this EASY press.",
                    "safety": "No external forms submitted.",
                },
                ensure_ascii=True,
                indent=2,
            ),
        }
    output_parts.append("Browser/live-submit execution:")
    output_parts.append(str(browser_result.get("output") or "")[-5000:])
    output_parts.append("")

    after = _easy_system_snapshot(conn)
    applied = _extract_result_count(triage_output, "Applied")
    routed = _extract_result_count(triage_output, "Routed")
    skipped = _extract_result_count(triage_output, "Skipped")
    submitted_external = _extract_json_int(str(browser_result.get("output") or ""), "submitted_external")
    deltas = {
        key: int(after.get(key, 0)) - int(before.get(key, 0))
        for key in ["claim_queue", "ready_for_ai_work", "ready_accept", "submitted", "processing", "received_paid"]
    }
    output_parts.append("Real movement summary:")
    output_parts.append(json.dumps({"before": before, "after": after, "delta": deltas}, ensure_ascii=True, indent=2))
    output_parts.append("")
    output_parts.append(f"Applied: {applied}")
    output_parts.append(f"Routed: {routed}")
    output_parts.append(f"Skipped: {skipped}")
    output_parts.append(f"Submitted External: {submitted_external}")
    output_parts.append(
        "Hard truth: assets only land when an official site accepts a low-risk submit or the owner completes/approves the blocked final step."
    )
    return {
        "label": "EASY ASSET ACQUISITION",
        "returncode": 0,
        "output": "\n".join(output_parts),
        "snapshot_before": before,
        "snapshot_after": after,
        "submitted_external": submitted_external,
    }


def _run_easy_until_blocked(
    conn: sqlite3.Connection,
    selected_ids: list[int],
    override_note: str,
    *,
    include_scout: bool,
    allow_low_risk_live_submit: bool,
    use_all_visible: bool,
    max_rounds: int = 4,
) -> dict[str, object]:
    overall_before = _easy_system_snapshot(conn)
    output_parts: list[str] = [
        "FULL AUTO UNTIL BLOCKED",
        f"Max rounds: {max_rounds}",
        f"Use all visible rows: {use_all_visible}",
        "",
    ]
    total_submitted_external = 0
    total_applied = 0
    total_routed = 0
    total_skipped = 0
    rounds: list[dict[str, object]] = []

    for round_number in range(1, max_rounds + 1):
        current_ids = (
            _instant_gain_ids(conn, limit=300)
            if use_all_visible
            else _prioritized_claim_ids(conn, [int(claim_id) for claim_id in selected_ids], limit=300)
        )
        if not current_ids:
            output_parts.append(f"Round {round_number}: no queued rows available.")
            break
        result = _run_easy_gain_mash(
            conn,
            current_ids,
            override_note,
            include_scout=include_scout and round_number == 1,
            allow_low_risk_live_submit=allow_low_risk_live_submit,
        )
        output = str(result.get("output") or "")
        applied = _extract_result_count(output, "Applied")
        routed = _extract_result_count(output, "Routed")
        skipped = _extract_result_count(output, "Skipped")
        submitted_external = int(result.get("submitted_external") or _extract_result_count(output, "Submitted External"))
        before = result.get("snapshot_before") if isinstance(result.get("snapshot_before"), dict) else {}
        after = result.get("snapshot_after") if isinstance(result.get("snapshot_after"), dict) else {}
        count_delta = sum(
            abs(int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0))
            for key in ["ready_for_ai_work", "ready_accept", "submitted", "processing", "received_paid", "blocked_or_input"]
        )
        movement = applied + routed + submitted_external + count_delta
        total_applied += applied
        total_routed += routed
        total_skipped += skipped
        total_submitted_external += submitted_external
        rounds.append(
            {
                "round": round_number,
                "targets": len(current_ids),
                "applied": applied,
                "routed": routed,
                "skipped": skipped,
                "submitted_external": submitted_external,
                "movement_score": movement,
            }
        )
        output_parts.append(f"Round {round_number}:")
        output_parts.append(output[-4500:])
        output_parts.append("")
        if movement <= 0:
            output_parts.append(f"Stopped after round {round_number}: no additional safe movement detected.")
            break

    overall_after = _easy_system_snapshot(conn)
    next_actions = _easy_owner_next_actions(conn)
    output_parts.append("FULL AUTO SUMMARY:")
    output_parts.append(json.dumps({"rounds": rounds, "before": overall_before, "after": overall_after}, ensure_ascii=True, indent=2))
    output_parts.append("")
    output_parts.append("TOP OWNER BLOCKERS:")
    output_parts.append(json.dumps(next_actions[:8], ensure_ascii=True, indent=2))
    output_parts.append("")
    output_parts.append(f"Applied: {total_applied}")
    output_parts.append(f"Routed: {total_routed}")
    output_parts.append(f"Skipped: {total_skipped}")
    output_parts.append(f"Submitted External: {total_submitted_external}")
    output_parts.append(
        "Operating rule: repeat this after resolving the top blocker. That is the one/two-click loop until an external site or owner-only gate stops it."
    )
    return {
        "label": "FULL AUTO UNTIL BLOCKED",
        "returncode": 0,
        "output": "\n".join(output_parts),
        "snapshot_before": overall_before,
        "snapshot_after": overall_after,
        "submitted_external": total_submitted_external,
    }


def _easy_system_snapshot(conn: sqlite3.Connection) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS claim_queue,
            SUM(CASE WHEN input_status='ready_for_ai_work' THEN 1 ELSE 0 END) AS ready_for_ai_work,
            SUM(CASE WHEN input_status='final_approval_required' OR execution_status='Ready To Accept' OR status='Ready to Accept' THEN 1 ELSE 0 END) AS ready_accept,
            SUM(CASE WHEN input_status IN ('needs_connect', 'missing_shipping', 'missing_payout', 'missing_inputs', 'blocked') OR execution_status='Paused Awaiting Input' THEN 1 ELSE 0 END) AS blocked_or_input,
            SUM(CASE WHEN status='Submitted' THEN 1 ELSE 0 END) AS submitted,
            SUM(CASE WHEN status='Processing' OR execution_status='Processing' THEN 1 ELSE 0 END) AS processing,
            SUM(CASE WHEN status='Received/Paid' THEN 1 ELSE 0 END) AS received_paid,
            COALESCE(SUM(expected_value_usd), 0) AS value_surface
        FROM claim_queue
        WHERE status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later')
        """
    ).fetchone()
    return {key: row[key] for key in row.keys()}


def _easy_owner_next_actions(conn: sqlite3.Connection, limit: int = 300) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            cq.execution_status,
            cq.input_status,
            cq.expected_value_usd,
            cq.missing_inputs,
            cq.sensitive_inputs,
            cq.human_input_needed,
            cq.next_action,
            o.title
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
        ORDER BY COALESCE(cq.expected_value_usd, 0) DESC, cq.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        item = dict(row)
        label, action = _easy_next_action_bucket(item)
        if not label:
            continue
        bucket = grouped.setdefault(label, {"label": label, "action": action, "count": 0, "value": 0.0, "examples": []})
        bucket["count"] = int(bucket["count"]) + 1
        bucket["value"] = float(bucket["value"]) + float(item.get("expected_value_usd") or 0)
        examples = bucket["examples"]
        if isinstance(examples, list) and len(examples) < 4:
            examples.append(f"#{int(item.get('id') or 0)} {item.get('title') or 'Untitled'}")
    return sorted(
        grouped.values(),
        key=lambda entry: (int(entry["count"]) * max(float(entry["value"]), 1.0)),
        reverse=True,
    )


def _easy_next_action_bucket(item: dict[str, object]) -> tuple[str, str]:
    status = str(item.get("status") or "").lower()
    execution = str(item.get("execution_status") or "").lower()
    input_status = str(item.get("input_status") or "").lower()
    text = " ".join(
        str(item.get(key) or "")
        for key in ["missing_inputs", "sensitive_inputs", "human_input_needed", "next_action", "status", "execution_status", "input_status"]
    ).lower()
    if "ready to accept" in status or "ready to accept" in execution or input_status == "final_approval_required":
        return (
            "Final approval / accept click",
            "Press READY NOW, review prepared packets, then use $$$ for safe final pushes or item-level approval for sensitive gates.",
        )
    if "connect" in input_status or "login" in text or "connect" in text:
        return ("Connect or approve login", "Open Vault -> Accounts / Connectors, connect once, then rerun FULL AUTO UNTIL BLOCKED.")
    if "shipping" in input_status or "shipping" in text or "address" in text:
        return ("Add shipping once", "Open Vault -> Shipping, save default address, then rerun FULL AUTO UNTIL BLOCKED.")
    if "payout" in input_status or "paypal" in text or "venmo" in text or "cashapp" in text:
        return ("Add payout route once", "Open Vault -> Payouts, save PayPal/Cash App/Venmo preference, then rerun FULL AUTO UNTIL BLOCKED.")
    if "email" in text:
        return ("Add email once", "Open Vault -> Basic Profile, save email, then rerun FULL AUTO UNTIL BLOCKED.")
    if "phone" in text:
        return ("Add phone once", "Open Vault -> Basic Profile, save phone, then rerun FULL AUTO UNTIL BLOCKED.")
    if any(term in text for term in ["legal", "tax", "identity", "wallet", "purchase", "payment", "captcha", "human verification"]):
        return ("Manual hard gate", "Open the approval packet or official site. AI cannot ethically/technically bypass this gate.")
    if input_status == "ready_for_ai_work":
        return ("AI-ready work waiting", "Press FULL AUTO UNTIL BLOCKED again.")
    if "submitted" in status or "processing" in status or "processing" in execution:
        return ("Track submitted/processing", "Wait for confirmation, shipment, email, account credit, or payout; mark received/paid only when verified.")
    return ("Queue cleanup / more info", "Open the row details, review next action, or run scout/prep again.")


def _grant_easy_low_risk_submit_consent(
    conn: sqlite3.Connection,
    selected_ids: list[int],
) -> dict[str, object]:
    consent_store = SubmissionConsentStore.for_root(ROOT_DIR)
    granted: list[int] = []
    blocked: list[dict[str, object]] = []
    for claim_id in selected_ids:
        detail = load_claim_detail(conn, int(claim_id))
        if not detail:
            blocked.append({"claim_queue_id": int(claim_id), "reason": "row not found"})
            continue
        detail_dict = dict(detail)
        action_type = final_action_type(detail_dict) or "final_submit"
        risk = str(detail_dict.get("risk_level") or "low")
        allowed, reason = can_live_submit(action_type, risk, explicit_terms_checked=True)
        sensitive_text = " ".join(
            str(detail_dict.get(key) or "")
            for key in ["sensitive_inputs", "human_input_needed", "next_action", "claim_instructions", "safety_notes"]
        ).lower()
        if any(
            term in sensitive_text
            for term in ["payment", "purchase", "legal", "tax", "identity", "wallet", "signature", "captcha", "login"]
        ):
            allowed = False
            reason = "Sensitive/manual stop term is present in the prepared packet."
        if not allowed:
            blocked.append({"claim_queue_id": int(claim_id), "action_type": action_type, "reason": reason})
            continue
        consent_store.save_consent(
            new_consent(
                int(claim_id),
                "EASY low-risk live-submit",
                (
                    "Owner pressed EASY ASSET ACQUISITION with low-risk live-submit enabled. "
                    "Consent applies only to non-sensitive final_submit rows and does not include payment, purchase, "
                    "legal, tax, identity, wallet signing, login, or human-verification actions."
                ),
            )
        )
        granted.append(int(claim_id))
    return {"granted": len(granted), "granted_ids": granted[:50], "blocked": blocked[:50]}


def _extract_json_int(text: str, key: str) -> int:
    try:
        payload = json.loads(text)
    except Exception:  # noqa: BLE001
        match = re.search(rf'"{re.escape(key)}"\s*:\s*(\d+)', text)
        return int(match.group(1)) if match else 0
    value = payload.get(key) if isinstance(payload, dict) else 0
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


DEFAULT_ENTITY_TREASURY: dict[str, object] = {
    "entity_label": "QuantumGains Entity Treasury",
    "cash_route": "",
    "crypto_route": "",
    "credits_route": "",
    "physical_route": "",
    "digital_asset_route": "",
    "treasury_note": "",
}


def _load_entity_treasury_routes() -> dict[str, object]:
    routes = dict(DEFAULT_ENTITY_TREASURY)
    if ENTITY_TREASURY_PATH.exists():
        try:
            payload = json.loads(ENTITY_TREASURY_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            routes.update({key: payload.get(key, value) for key, value in DEFAULT_ENTITY_TREASURY.items()})
    context = load_effective_user_context()
    payouts = context.get("payouts", {}) if isinstance(context.get("payouts"), dict) else {}
    crypto = context.get("crypto_wallets", {}) if isinstance(context.get("crypto_wallets"), dict) else {}
    shipping = context.get("shipping", {}) if isinstance(context.get("shipping"), dict) else {}
    business = context.get("business", {}) if isinstance(context.get("business"), dict) else {}
    if not routes["cash_route"]:
        routes["cash_route"] = _first_nonempty(
            payouts.get("paypal_email"),
            payouts.get("stripe_email"),
            payouts.get("cashapp"),
            payouts.get("venmo"),
            payouts.get("bank_label"),
            payouts.get("other_payout_note"),
        )
    if not routes["crypto_route"]:
        routes["crypto_route"] = _first_nonempty(
            crypto.get("usdc_address"),
            crypto.get("eth_address"),
            crypto.get("btc_address"),
            crypto.get("sol_address"),
            crypto.get("wallet_notes"),
        )
    if not routes["physical_route"]:
        routes["physical_route"] = _format_shipping_route(shipping)
    if not routes["credits_route"]:
        routes["credits_route"] = _first_nonempty(
            business.get("business_name"),
            business.get("website_domain"),
            context.get("accounts", {}).get("google_email") if isinstance(context.get("accounts"), dict) else "",
            context.get("accounts", {}).get("microsoft_email") if isinstance(context.get("accounts"), dict) else "",
        )
    return routes


def _save_entity_treasury_routes(routes: dict[str, object]) -> None:
    payload = dict(DEFAULT_ENTITY_TREASURY)
    payload.update({key: str(routes.get(key) or "") for key in DEFAULT_ENTITY_TREASURY})
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    ENTITY_TREASURY_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENTITY_TREASURY_PATH.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _show_entity_treasury_routes_editor(routes: dict[str, object]) -> None:
    with st.form("entity_treasury_routes_form"):
        st.markdown("**Entity Receiving Routes**")
        cols = st.columns(2)
        entity_label = cols[0].text_input("Entity label", value=str(routes.get("entity_label") or ""))
        cash_route = cols[1].text_input("Cash / payout route", value=str(routes.get("cash_route") or ""))
        crypto_route = cols[0].text_input("Crypto public receiving route", value=str(routes.get("crypto_route") or ""))
        credits_route = cols[1].text_input("Credits / platform account route", value=str(routes.get("credits_route") or ""))
        physical_route = cols[0].text_input("Physical goods route", value=str(routes.get("physical_route") or ""))
        digital_asset_route = cols[1].text_input("Digital/domain asset route", value=str(routes.get("digital_asset_route") or ""))
        treasury_note = st.text_area("Treasury note", value=str(routes.get("treasury_note") or ""))
        st.caption("Do not enter full bank numbers, passwords, private keys, seed phrases, SSNs, or identity documents here.")
        if st.form_submit_button("Save Entity Treasury Routes", use_container_width=True):
            _save_entity_treasury_routes(
                {
                    "entity_label": entity_label,
                    "cash_route": cash_route,
                    "crypto_route": crypto_route,
                    "credits_route": credits_route,
                    "physical_route": physical_route,
                    "digital_asset_route": digital_asset_route,
                    "treasury_note": treasury_note,
                }
            )
            st.success("Entity treasury routes saved.")
            st.rerun()


def _entity_treasury_summary(conn: sqlite3.Connection) -> dict[str, object]:
    received = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(estimated_value_usd),0) AS v FROM received_log").fetchone()
    submitted = conn.execute(
        """
        SELECT COUNT(*) AS n, COALESCE(SUM(expected_value_usd),0) AS v
        FROM claim_queue
        WHERE status IN ('Submitted','Processing') OR execution_status='Processing'
        """
    ).fetchone()
    ready = conn.execute(
        """
        SELECT COUNT(*) AS n, COALESCE(SUM(expected_value_usd),0) AS v
        FROM claim_queue
        WHERE status='Ready to Accept' OR execution_status='Ready To Accept' OR input_status='final_approval_required'
        """
    ).fetchone()
    labor = conn.execute(
        """
        SELECT COUNT(*) AS n, COALESCE(SUM(cq.expected_value_usd),0) AS v
        FROM claim_queue cq
        JOIN opportunities o ON o.id=cq.opportunity_id
        WHERE o.source_name='AI LABOR ENGINE' OR o.source_type='ai_labor_lane' OR o.tags LIKE '%ai-labor-engine%'
        """
    ).fetchone()
    routes = _load_entity_treasury_routes()
    configured_routes = sum(1 for key in ["cash_route", "crypto_route", "credits_route", "physical_route", "digital_asset_route"] if str(routes.get(key) or "").strip())
    return {
        "withdrawable_count": int(received["n"] or 0),
        "withdrawable_value": float(received["v"] or 0),
        "submitted_count": int(submitted["n"] or 0),
        "submitted_value": float(submitted["v"] or 0),
        "ready_count": int(ready["n"] or 0),
        "ready_value": float(ready["v"] or 0),
        "ai_labor_count": int(labor["n"] or 0),
        "ai_labor_value": float(labor["v"] or 0),
        "configured_routes": configured_routes,
    }


def _apply_entity_treasury_routes(conn: sqlite3.Connection, routes: dict[str, object]) -> int:
    rows = conn.execute(
        """
        SELECT id, gain_type, asset_type, destination_type, destination
        FROM claim_queue
        WHERE status NOT IN ('Reject','Rejected','Dead End','Received/Paid')
        """
    ).fetchall()
    changed = 0
    now = datetime.now(timezone.utc).isoformat()
    external_wallet_routes = load_external_wallet_routes(ROOT_DIR)
    for row in rows:
        route = _route_for_treasury_row(dict(row), routes, external_wallet_routes)
        if not route:
            continue
        conn.execute(
            """
            UPDATE claim_queue
            SET asset_destination=?,
                destination=COALESCE(NULLIF(destination, ''), ?),
                updated_at=?
            WHERE id=?
            """,
            (route, route, now, int(row["id"])),
        )
        changed += 1
    conn.commit()
    return changed


def _route_for_treasury_row(
    row: dict[str, object],
    routes: dict[str, object],
    external_wallet_routes: object | None = None,
) -> str:
    text = " ".join(str(row.get(key) or "") for key in ["gain_type", "asset_type", "destination_type", "destination"]).lower()
    if any(term in text for term in ["physical", "sample", "goods", "ship"]):
        return str(routes.get("physical_route") or "")
    if any(term in text for term in ["crypto", "wallet", "token", "airdrop"]):
        if external_wallet_routes and hasattr(external_wallet_routes, "route_for_text"):
            external_route = external_wallet_routes.route_for_text(text)
        else:
            external_route = wallet_route_for_text(ROOT_DIR, text)
        if external_route:
            return str(external_route)
        return str(routes.get("crypto_route") or "")
    if any(term in text for term in ["credit", "developer", "cloud", "startup"]):
        return str(routes.get("credits_route") or "")
    if any(term in text for term in ["domain", "digital_asset", "marketplace"]):
        return str(routes.get("digital_asset_route") or "")
    return str(routes.get("cash_route") or "")


def _show_entity_treasury_real_rows(conn: sqlite3.Connection) -> None:
    st.markdown("**Confirmed Received / Paid**")
    received = pd.DataFrame(received_paid_rows(conn, limit=200))
    if received.empty:
        st.info("No confirmed received/paid assets yet. This is the real withdrawable number, and right now it is zero.")
    else:
        show_dataframe(received)

    st.markdown("**Pending: Submitted / Processing**")
    pending = pd.read_sql_query(
        """
        SELECT
            cq.id,
            o.title,
            cq.status,
            cq.execution_status,
            cq.expected_value_usd,
            cq.asset_type,
            cq.destination,
            cq.asset_destination,
            cq.received_tracking_note,
            cq.official_link,
            cq.updated_at
        FROM claim_queue cq
        JOIN opportunities o ON o.id=cq.opportunity_id
        WHERE cq.status IN ('Submitted','Processing') OR cq.execution_status='Processing'
        ORDER BY COALESCE(cq.expected_value_usd,0) DESC, cq.updated_at DESC
        LIMIT 200
        """,
        conn,
    )
    show_dataframe(pending)

    st.markdown("**Ready To Authorize / Final Gate**")
    ready = pd.read_sql_query(
        """
        SELECT
            cq.id,
            o.title,
            cq.status,
            cq.execution_status,
            cq.input_status,
            cq.expected_value_usd,
            cq.asset_type,
            cq.asset_destination,
            cq.next_action,
            cq.human_input_needed,
            cq.official_link
        FROM claim_queue cq
        JOIN opportunities o ON o.id=cq.opportunity_id
        WHERE cq.status='Ready to Accept' OR cq.execution_status='Ready To Accept' OR cq.input_status='final_approval_required'
        ORDER BY COALESCE(cq.expected_value_usd,0) DESC, cq.updated_at DESC
        LIMIT 200
        """,
        conn,
    )
    show_dataframe(ready)


def _show_entity_treasury_setup_checklist(routes: dict[str, object]) -> None:
    context = load_effective_user_context()
    payouts = context.get("payouts", {}) if isinstance(context.get("payouts"), dict) else {}
    crypto = context.get("crypto_wallets", {}) if isinstance(context.get("crypto_wallets"), dict) else {}
    business = context.get("business", {}) if isinstance(context.get("business"), dict) else {}
    checks = [
        {"Setup": "Cash payout route", "Ready": bool(str(routes.get("cash_route") or "").strip()), "Use": "PayPal/Stripe/Cash App/Venmo/bank label"},
        {"Setup": "Crypto public receiving route", "Ready": bool(str(routes.get("crypto_route") or "").strip()), "Use": "Public wallet address only; no keys/signing"},
        {"Setup": "Physical shipping route", "Ready": bool(str(routes.get("physical_route") or "").strip()), "Use": "Samples/goods after shipping approval"},
        {"Setup": "Business/platform route", "Ready": bool(str(routes.get("credits_route") or "").strip()), "Use": "Developer/startup credits and SaaS accounts"},
        {"Setup": "Business profile in Vault", "Ready": any(str(business.get(key) or "").strip() for key in BUSINESS_FIELDS), "Use": "Applications, credits, grants, entity identity"},
        {"Setup": "Payout profile in Vault", "Ready": any(str(payouts.get(key) or "").strip() for key in PAYOUT_FIELDS), "Use": "Cash/rewards payout routing"},
        {"Setup": "Wallet profile in Vault", "Ready": any(str(crypto.get(key) or "").strip() for key in CRYPTO_WALLET_FIELDS), "Use": "Public receive addresses"},
    ]
    st.markdown("**Entity Setup Checklist**")
    show_dataframe(pd.DataFrame(checks))


def _first_nonempty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _format_shipping_route(shipping: dict[str, object]) -> str:
    parts = [
        shipping.get("full_name"),
        shipping.get("address_line_1"),
        shipping.get("address_line_2"),
        shipping.get("city"),
        shipping.get("state"),
        shipping.get("zip"),
        shipping.get("country"),
    ]
    return ", ".join(str(part).strip() for part in parts if str(part or "").strip())


def _load_chaos_control() -> dict[str, object]:
    default = {
        "enabled": False,
        "use_vault": True,
        "low_risk_live_submit": False,
        "risk_on": False,
        "deep_scan": False,
        "interval_seconds": 120,
        "cycle_count": 0,
        "last_run_at": "",
        "log": [],
    }
    if CHAOS_MODE_PATH.exists():
        try:
            payload = json.loads(CHAOS_MODE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            default.update(payload)
    return default


def _save_chaos_control(control: dict[str, object]) -> None:
    payload = dict(control)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    CHAOS_MODE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHAOS_MODE_PATH.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _chaos_should_run(control: dict[str, object], force_run: bool) -> tuple[bool, str]:
    if force_run:
        return True, "Manual cycle requested."
    if not control.get("enabled"):
        return False, "CHAOS MODE is off."
    last = str(control.get("last_run_at") or "")
    interval = int(control.get("interval_seconds") or 120)
    if not last:
        return True, "First enabled cycle."
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return True, "Last cycle timestamp was invalid."
    elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
    if elapsed >= interval:
        return True, f"Interval elapsed: {elapsed:.0f}s."
    return False, f"Next cycle in about {max(0, int(interval - elapsed))} seconds."


def _run_chaos_cycle(
    conn: sqlite3.Connection,
    *,
    use_vault: bool,
    low_risk_live_submit: bool,
    risk_on: bool,
    deep_scan: bool,
) -> dict[str, object]:
    before = {
        "treasury": _entity_treasury_summary(conn),
        "easy": _easy_system_snapshot(conn),
        "labor": _ai_labor_snapshot(conn),
    }
    routes = _load_entity_treasury_routes()
    output_parts: list[str] = ["CHAOS MODE CYCLE", ""]
    if deep_scan:
        deep_result = _run_broad_fetch_scan()
        output_parts.append("Deep scan:")
        output_parts.append(str(deep_result.get("output") or "")[-3500:])
        output_parts.append("")

    store = SQLiteStore(DB_PATH)
    store.init_db()
    magic = run_magic_money_scout(store, promote_to_queue=True)
    labor_seed = _seed_ai_labor_lanes(store, risk_on=risk_on)
    store.refresh_exploration_queue()
    store.normalize_required_inputs()
    store.normalize_execution_state()

    context = load_effective_user_context() if use_vault else default_user_context()
    completion = run_completion_engine_pass(conn, context, mode="Live Assist", commit=True)
    autonomy = run_autonomous_queue_pass(
        conn,
        ROOT_DIR,
        {"enabled": True, "mode": "Open-To-Everything", "execution_mode": "Live Assist"},
    )

    easy_ids = _claim_ids_not_browser_submitted(conn, _instant_gain_ids(conn, limit=500))
    labor_ids = _claim_ids_not_browser_submitted(conn, _ai_labor_claim_ids(conn))
    if easy_ids:
        _apply_operator_selected_action(conn, easy_ids, "approve_possible_route_rest")
    if labor_ids:
        _apply_operator_selected_action(conn, labor_ids, "approve_possible_route_rest")
    changed_routes = _apply_entity_treasury_routes(conn, routes)

    consent_summary = {"granted": 0, "granted_ids": [], "blocked": []}
    submitted_external = 0
    browser_result: dict[str, object] = {
        "returncode": 0,
        "output": json.dumps({"submitted_external": 0, "skipped": "Low-risk live submit disabled."}, ensure_ascii=True, indent=2),
    }
    if low_risk_live_submit:
        consent_ids = list(dict.fromkeys(easy_ids[:300] + _prioritized_claim_ids(conn, labor_ids, limit=120)))
        consent_summary = _grant_easy_low_risk_submit_consent(conn, consent_ids)
        browser_result = _run_safe_browser_execution_batch(
            conn,
            limit=18,
            execution_mode_override="Live Submit With Final Approval",
            context_override=context,
            batch_deadline_seconds=0,
        )
        submitted_external = _extract_json_int(str(browser_result.get("output") or ""), "submitted_external")
    conn.commit()

    after = {
        "treasury": _entity_treasury_summary(conn),
        "easy": _easy_system_snapshot(conn),
        "labor": _ai_labor_snapshot(conn),
    }
    payload = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "use_vault": use_vault,
        "low_risk_live_submit": low_risk_live_submit,
        "risk_on": risk_on,
        "deep_scan": deep_scan,
        "magic_money": magic.to_dict(),
        "labor_seed": labor_seed,
        "completion": completion.to_dict(),
        "autonomy": autonomy.to_dict(),
        "easy_targets": len(easy_ids),
        "labor_targets": len(labor_ids),
        "treasury_routes_applied": changed_routes,
        "consent": consent_summary,
        "browser_execution": json.loads(str(browser_result.get("output") or "{}"))
        if str(browser_result.get("output") or "{}").strip().startswith("{")
        else str(browser_result.get("output") or ""),
        "submitted_external": submitted_external,
        "before": before,
        "after": after,
        "warning": "No illegal/sensitive/platform-bypass actions are executed. Confirmed received/paid remains the only withdrawable value.",
    }
    return {
        "label": "CHAOS MODE",
        "returncode": 0,
        "output": json.dumps(payload, ensure_ascii=True, indent=2),
        "snapshot_before": before.get("treasury", {}),
        "snapshot_after": after.get("treasury", {}),
        "submitted_external": submitted_external,
    }


def _record_chaos_result(control: dict[str, object], result: dict[str, object]) -> None:
    control = dict(control)
    now = datetime.now(timezone.utc).isoformat()
    before = result.get("snapshot_before") if isinstance(result.get("snapshot_before"), dict) else {}
    after = result.get("snapshot_after") if isinstance(result.get("snapshot_after"), dict) else {}
    entry = {
        "at": now,
        "submitted_external": int(result.get("submitted_external") or 0),
        "withdrawable_value": float(after.get("withdrawable_value") or 0),
        "submitted_value": float(after.get("submitted_value") or 0),
        "ready_value": float(after.get("ready_value") or 0),
        "delta_withdrawable": float(after.get("withdrawable_value") or 0) - float(before.get("withdrawable_value") or 0),
        "delta_submitted": float(after.get("submitted_value") or 0) - float(before.get("submitted_value") or 0),
    }
    log = control.get("log") if isinstance(control.get("log"), list) else []
    control["log"] = [entry, *log][:30]
    control["last_run_at"] = now
    control["cycle_count"] = int(control.get("cycle_count") or 0) + 1
    _save_chaos_control(control)


def _show_chaos_worker_controls(
    control: dict[str, object],
    *,
    use_vault: bool,
    low_risk_live_submit: bool,
    risk_on: bool,
    deep_scan: bool,
    interval_seconds: int,
) -> None:
    st.markdown("**ENTITY WORKER**")
    active_workers = _chaos_worker_process_count()
    cols = st.columns([1.1, 1.1, 1.1, 2.7])
    if cols[0].button(
        "Start Worker",
        key="chaos_start_worker",
        use_container_width=True,
        disabled=active_workers > 0,
    ):
        worker_control = {
            **control,
            "enabled": True,
            "use_vault": use_vault,
            "low_risk_live_submit": low_risk_live_submit,
            "risk_on": risk_on,
            "deep_scan": deep_scan,
            "interval_seconds": interval_seconds,
            "worker_requested_at": datetime.now(timezone.utc).isoformat(),
        }
        proc = _start_chaos_worker_process(worker_control)
        worker_control["worker_pid"] = proc.pid
        _save_chaos_control(worker_control)
        st.success(f"Background worker started as PID {proc.pid}.")
        st.rerun()
    if cols[1].button("Stop Worker", key="chaos_stop_worker", use_container_width=True):
        stopped = {**control, "enabled": False, "worker_stop_requested_at": datetime.now(timezone.utc).isoformat()}
        _save_chaos_control(stopped)
        stopped_count = _stop_chaos_worker_processes()
        _save_chaos_worker_status(
            {
                "state": "stopped",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "last_message": f"Stop requested from dashboard. Stopped worker processes: {stopped_count}.",
            }
        )
        st.warning(f"Stop requested. Stopped worker processes: {stopped_count}.")
        st.rerun()
    if cols[2].button("Open Log", key="chaos_open_log", use_container_width=True):
        st.session_state["show_chaos_worker_log"] = not bool(st.session_state.get("show_chaos_worker_log"))

    status = _load_chaos_worker_status()
    cols[3].caption(
        f"Worker status: {status.get('state', 'not started')} | "
        f"PID: {status.get('pid', control.get('worker_pid', 'n/a'))} | "
        f"active processes: {active_workers} | "
        f"{status.get('last_message', 'No worker message yet.')}"
    )
    if st.session_state.get("show_chaos_worker_log"):
        with st.expander("CHAOS worker log", expanded=True):
            st.code(_tail_text(ROOT_DIR / "data" / "chaos_worker.log", max_lines=80), language="text")


def _start_chaos_worker_process(control: dict[str, object]) -> subprocess.Popen:
    _save_chaos_control(control)
    python_path = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    python = str(python_path if python_path.exists() else sys.executable)
    script = ROOT_DIR / "scripts" / "chaos_worker.py"
    command = [
        python,
        str(script),
        "--root",
        str(ROOT_DIR),
        "--duration-seconds",
        "3600",
        "--interval-seconds",
        str(int(control.get("interval_seconds") or 120)),
        "--enable",
    ]
    command.append("--use-vault" if control.get("use_vault", True) else "--no-use-vault")
    if control.get("low_risk_live_submit"):
        command.append("--low-risk-live-submit")
    if control.get("risk_on"):
        command.append("--risk-on")
    if control.get("deep_scan"):
        command.append("--deep-scan")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    return subprocess.Popen(
        command,
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def _load_chaos_worker_status() -> dict[str, object]:
    if not CHAOS_WORKER_STATUS_PATH.exists():
        return {}
    try:
        payload = json.loads(CHAOS_WORKER_STATUS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_chaos_worker_status(payload: dict[str, object]) -> None:
    existing = _load_chaos_worker_status()
    existing.update(payload)
    CHAOS_WORKER_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHAOS_WORKER_STATUS_PATH.write_text(json.dumps(existing, ensure_ascii=True, indent=2), encoding="utf-8")


def _chaos_worker_process_count() -> int:
    if os.name != "nt":
        return 0
    script = str(ROOT_DIR / "scripts" / "chaos_worker.py").replace("'", "''")
    command = (
        "$script = '" + script + "'; "
        "@(Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -like \"*$script*\" -and $_.Name -like 'python*' }).Count"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return 0
    try:
        return int((proc.stdout or "0").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def _stop_chaos_worker_processes() -> int:
    if os.name != "nt":
        return 0
    script = str(ROOT_DIR / "scripts" / "chaos_worker.py").replace("'", "''")
    command = (
        "$script = '" + script + "'; "
        "$workers = @(Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -like \"*$script*\" -and $_.Name -like 'python*' }); "
        "$workers | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; "
        "$workers.Count"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return 0
    try:
        return int((proc.stdout or "0").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def _start_live_connector_session(provider_key: str) -> subprocess.Popen:
    python_path = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    python = str(python_path if python_path.exists() else sys.executable)
    script = ROOT_DIR / "scripts" / "live_connector_session.py"
    command = [
        python,
        str(script),
        "--root",
        str(ROOT_DIR),
        "--provider",
        str(provider_key),
        "--duration-seconds",
        "900",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    return subprocess.Popen(
        command,
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def _tail_text(path: Path, *, max_lines: int = 60) -> str:
    if not path.exists():
        return "No log file yet."
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:]) or "Log file is empty."


def _show_chaos_last_result() -> None:
    result = st.session_state.get("chaos_last_result")
    if not isinstance(result, dict):
        return
    after = result.get("snapshot_after") if isinstance(result.get("snapshot_after"), dict) else {}
    submitted = int(result.get("submitted_external") or 0)
    st.success(
        f"CHAOS cycle finished. External low-risk submits: {submitted}. "
        f"Withdrawable: ${float(after.get('withdrawable_value') or 0):,.2f}; "
        f"Submitted: ${float(after.get('submitted_value') or 0):,.2f}."
    )
    with st.expander("CHAOS cycle details", expanded=False):
        st.code(str(result.get("output") or "")[-10000:], language="json")


def _show_chaos_cycle_log() -> None:
    control = _load_chaos_control()
    log = control.get("log") if isinstance(control.get("log"), list) else []
    st.markdown("**CHAOS Cycle Log**")
    if not log:
        st.info("No CHAOS cycles recorded yet.")
        return
    show_dataframe(pd.DataFrame(log))


def _chaos_auto_refresh(interval_seconds: int) -> None:
    components.html(
        f"""
        <script>
          setTimeout(function() {{
            const url = new URL(window.parent.location.href);
            url.searchParams.set('_chaos_tick', Date.now().toString());
            window.parent.location.href = url.toString();
          }}, {max(30, int(interval_seconds)) * 1000});
        </script>
        """,
        height=0,
    )


AI_LABOR_LANES: list[dict[str, object]] = [
    {
        "name": "AI Programming Bounty Sweep",
        "category": "programming_bounties",
        "url": "https://algora.io/bounties",
        "summary": "Open-source programming bounty lane. AI can identify approachable issues, draft fixes locally, and route PR/final submit to owner.",
        "asset_type": "cash_rewards",
        "expected_value_usd": 75,
        "probability": 4,
        "effort": 6,
        "ai_percent": 82,
        "stops_on": ["account login", "repository permission", "final PR submit", "payment/tax profile"],
    },
    {
        "name": "Bug Bounty Recon / Low-Severity Triage",
        "category": "bug_bounties",
        "url": "https://www.hackerone.com/opportunities/all",
        "summary": "Bug bounty lane for public-scope recon, duplicate checking, and report drafting. Owner controls account submit and any testing boundaries.",
        "asset_type": "cash_rewards",
        "expected_value_usd": 100,
        "probability": 3,
        "effort": 7,
        "ai_percent": 70,
        "stops_on": ["platform login", "program rules", "final report submit", "legal scope boundaries"],
    },
    {
        "name": "Paid User Testing Applications",
        "category": "paid_testing",
        "url": "https://www.usertesting.com/get-paid-to-test",
        "summary": "Paid testing lane. AI can find tests, prepare profile/screener packets, and track payouts; human test portions route to owner.",
        "asset_type": "cash_rewards",
        "expected_value_usd": 20,
        "probability": 6,
        "effort": 4,
        "ai_percent": 64,
        "stops_on": ["human test", "screen recording consent", "identity/tax profile", "final submit"],
    },
    {
        "name": "Paid Research Panel Stack",
        "category": "paid_research",
        "url": "https://www.respondent.io/respondents",
        "summary": "Paid research lane. AI can match studies, prepare applications, route payout needs, and schedule follow-ups.",
        "asset_type": "cash_rewards",
        "expected_value_usd": 45,
        "probability": 5,
        "effort": 5,
        "ai_percent": 68,
        "stops_on": ["human interview", "identity verification", "tax profile", "final submit"],
    },
    {
        "name": "Freelance Micro-Gig Proposal Factory",
        "category": "freelance_gigs",
        "url": "https://www.upwork.com/freelance-jobs/",
        "summary": "Gig scout lane. AI can search fitting tasks, draft proposals/work plans, and route owner approval for account submission.",
        "asset_type": "cash_rewards",
        "expected_value_usd": 50,
        "probability": 3,
        "effort": 6,
        "ai_percent": 76,
        "stops_on": ["platform login", "terms", "client communication", "final proposal submit", "tax/payment profile"],
    },
    {
        "name": "Domain Monetization / Sale Prep",
        "category": "digital_asset_monetization",
        "url": "https://www.afternic.com/",
        "summary": "Domain asset lane. AI can draft listings, suggested prices, descriptions, outreach copy, and track marketplace tasks.",
        "asset_type": "digital_asset_value",
        "expected_value_usd": 100,
        "probability": 3,
        "effort": 4,
        "ai_percent": 86,
        "stops_on": ["marketplace login", "DNS/account change", "final listing agreement", "sale acceptance"],
    },
    {
        "name": "Dataset / Labeling Platform Finder",
        "category": "microtasks",
        "url": "https://www.toloka.ai/tolokers",
        "summary": "Microtask lane. AI can find platforms and prep profiles; task completion only proceeds where terms allow automation.",
        "asset_type": "cash_rewards",
        "expected_value_usd": 10,
        "probability": 5,
        "effort": 5,
        "ai_percent": 54,
        "stops_on": ["platform terms", "captcha", "human verification", "tax/payment profile"],
    },
    {
        "name": "Crypto Learn / Quest Watch",
        "category": "crypto_freebies",
        "url": "https://www.coinbase.com/learning-rewards",
        "summary": "Crypto reward watch lane. AI can identify official rewards and prepare public wallet/profile data; signing/KYC remains owner-only.",
        "asset_type": "crypto",
        "expected_value_usd": 5,
        "probability": 4,
        "effort": 4,
        "ai_percent": 58,
        "stops_on": ["wallet signing", "KYC", "account login", "tax action", "final submit"],
    },
    {
        "name": "Free Credit Application Stack",
        "category": "startup_credits",
        "url": "https://www.f6s.com/deals",
        "summary": "Startup/dev credit lane. AI can reuse business profile fields, draft applications, and track credit delivery.",
        "asset_type": "developer_credits",
        "expected_value_usd": 500,
        "probability": 5,
        "effort": 5,
        "ai_percent": 78,
        "stops_on": ["login", "business verification", "terms", "final submit"],
    },
    {
        "name": "No-Purchase Freebie / Sample Work Queue",
        "category": "physical_goods",
        "url": "https://www.hometesterclub.com/",
        "summary": "Physical sample/product testing lane. AI can prepare safe profile/shipping fields and track shipment/follow-up.",
        "asset_type": "physical_goods",
        "expected_value_usd": 15,
        "probability": 6,
        "effort": 4,
        "ai_percent": 74,
        "stops_on": ["shipping approval", "final submit", "review obligation", "purchase/payment"],
    },
]

SPECULATIVE_AI_LABOR_LANES: list[dict[str, object]] = [
    {
        "name": "Risk-On Airdrop / Quest Grinder",
        "category": "speculative_crypto_quests",
        "url": "https://layer3.xyz/",
        "summary": "Speculative crypto quest lane. AI scouts, scores, prepares non-signing tasks, and routes wallet/KYC/signing steps to owner.",
        "asset_type": "crypto",
        "expected_value_usd": 20,
        "probability": 3,
        "effort": 7,
        "ai_percent": 66,
        "risk_level": "medium",
        "stops_on": ["wallet signing", "token approval", "KYC", "purchase/swap/bridge", "platform login"],
    },
    {
        "name": "Affiliate / Referral Funnel Builder",
        "category": "affiliate_referral",
        "url": "https://www.impact.com/",
        "summary": "Affiliate/referral lane. AI scouts programs, drafts applications/content, prepares referral assets, and tracks conversion tasks.",
        "asset_type": "cash_rewards",
        "expected_value_usd": 50,
        "probability": 3,
        "effort": 6,
        "ai_percent": 84,
        "risk_level": "medium",
        "stops_on": ["program terms", "platform login", "final application submit", "tax/payment profile"],
    },
    {
        "name": "Hackathon / Prize Submission Factory",
        "category": "prize_competitions",
        "url": "https://devpost.com/hackathons",
        "summary": "Prize competition lane. AI finds contests, drafts project plans/submissions, builds starter assets, and routes final submit.",
        "asset_type": "cash_rewards",
        "expected_value_usd": 250,
        "probability": 2,
        "effort": 8,
        "ai_percent": 78,
        "risk_level": "medium",
        "stops_on": ["competition rules", "IP/license terms", "team/account login", "final submit"],
    },
    {
        "name": "Grant / Credit Application Swarm",
        "category": "grant_credit_apps",
        "url": "https://www.helloalice.com/grants",
        "summary": "Grant and credit lane. AI drafts reusable narratives/applications and routes legal/tax/business verification.",
        "asset_type": "cash_rewards",
        "expected_value_usd": 500,
        "probability": 2,
        "effort": 7,
        "ai_percent": 80,
        "risk_level": "medium",
        "stops_on": ["legal attestation", "tax/business verification", "identity verification", "final submit"],
    },
    {
        "name": "Content Monetization Assembly Line",
        "category": "content_monetization",
        "url": "https://medium.com/creators",
        "summary": "Content lane. AI drafts assets, publishing plans, SEO/referral material, and routes account/payment gates.",
        "asset_type": "cash_rewards",
        "expected_value_usd": 25,
        "probability": 4,
        "effort": 6,
        "ai_percent": 88,
        "risk_level": "medium",
        "stops_on": ["platform terms", "account login", "payment profile", "human review"],
    },
    {
        "name": "Marketplace Listing / Digital Asset Liquidation",
        "category": "asset_liquidation",
        "url": "https://flippa.com/",
        "summary": "Digital asset listing lane. AI prepares listings, valuations, copy, screenshots/checklists, and routes owner listing approval.",
        "asset_type": "digital_asset_value",
        "expected_value_usd": 150,
        "probability": 3,
        "effort": 5,
        "ai_percent": 86,
        "risk_level": "medium",
        "stops_on": ["marketplace login", "listing agreement", "sale acceptance", "domain/account transfer"],
    },
    {
        "name": "High-Risk Opportunity Watchtower",
        "category": "high_risk_watch",
        "url": "https://galxe.com/",
        "summary": "Watch-only speculative lane for volatile opportunities. AI researches and prepares packets; no autonomous trading/signing/buying.",
        "asset_type": "crypto",
        "expected_value_usd": 0,
        "probability": 1,
        "effort": 9,
        "ai_percent": 55,
        "risk_level": "high",
        "stops_on": ["wallet signing", "purchase", "swap", "bridge", "token approval", "financial decision"],
    },
]


def _ai_labor_lanes(risk_on: bool = False) -> list[dict[str, object]]:
    return AI_LABOR_LANES + (SPECULATIVE_AI_LABOR_LANES if risk_on else [])


def _load_ai_labor_risk_consent() -> dict[str, object]:
    if not AI_LABOR_RISK_CONSENT_PATH.exists():
        return {"risk_on_enabled": False, "treasury_route": ""}
    try:
        payload = json.loads(AI_LABOR_RISK_CONSENT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"risk_on_enabled": False, "treasury_route": ""}
    return payload if isinstance(payload, dict) else {"risk_on_enabled": False, "treasury_route": ""}


def _save_ai_labor_risk_consent(payload: dict[str, object]) -> None:
    payload = dict(payload)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    AI_LABOR_RISK_CONSENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AI_LABOR_RISK_CONSENT_PATH.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _show_ai_labor_risk_consent_panel(current: dict[str, object]) -> None:
    with st.expander("Risk-On Autonomy Consent", expanded=not bool(current.get("risk_on_enabled"))):
        st.warning(
            "Risk-on mode widens discovery and queues speculative/high-friction work. "
            "It can waste time, produce no payout, get rejected by platforms, or require owner action. "
            "It still cannot bypass laws, platform rules, login security, captcha/human checks, legal/tax/identity gates, "
            "payments, purchases, or wallet signing."
        )
        cols = st.columns([1.5, 1.2, 1.2])
        accepts = cols[0].checkbox(
            "I accept speculative AI labor risk",
            value=bool(current.get("risk_on_enabled")),
            key="ai_labor_risk_accept_checkbox",
        )
        typed = cols[1].text_input(
            "Type RISK-ON",
            value="RISK-ON" if current.get("risk_on_enabled") else "",
            key="ai_labor_risk_accept_text",
        )
        if cols[2].button("Sign / Update Consent", use_container_width=True):
            enabled = bool(accepts and typed.strip().upper() == "RISK-ON")
            _save_ai_labor_risk_consent(
                {
                    **current,
                    "risk_on_enabled": enabled,
                    "signed_text": typed.strip(),
                    "consent_note": (
                        "Owner accepts speculative AI labor risk while preserving stops for illegal/sensitive/platform-rule gates."
                    ),
                    "signed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            if enabled:
                st.success("Risk-on AI labor consent saved. Risk-on lanes are available.")
            else:
                st.info("Risk-on consent is off. Type RISK-ON and check the box to enable speculative lanes.")
            st.rerun()
        if current.get("risk_on_enabled"):
            st.success("Risk-on consent is currently active.")
        else:
            st.caption("Risk-on lanes stay disabled until signed here.")


def _run_ai_labor_engine(
    conn: sqlite3.Connection,
    *,
    vault_access: bool,
    allow_low_risk_live_submit: bool,
    mark_blocked_for_rescan: bool,
    risk_on: bool = False,
    treasury_route: str = "",
) -> dict[str, object]:
    before = _ai_labor_snapshot(conn)
    store = SQLiteStore(DB_PATH)
    store.init_db()
    _save_ai_labor_risk_consent(
        {
            **_load_ai_labor_risk_consent(),
            "risk_on_enabled": bool(risk_on),
            "treasury_route": treasury_route.strip(),
            "last_run_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    seeded = _seed_ai_labor_lanes(store, risk_on=risk_on)
    conn.commit()
    context = load_effective_user_context() if vault_access else default_user_context()
    labor_ids = _ai_labor_claim_ids(conn)
    if treasury_route.strip() and labor_ids:
        _apply_ai_labor_treasury_route(conn, treasury_route.strip(), labor_ids)
    consent_summary = {"granted": 0, "granted_ids": [], "blocked": []}
    if allow_low_risk_live_submit and labor_ids:
        consent_summary = _grant_easy_low_risk_submit_consent(conn, labor_ids)
    completion = run_completion_engine_pass(conn, context, mode="Live Assist", commit=True)
    autonomy = run_autonomous_queue_pass(
        conn,
        ROOT_DIR,
        {"enabled": True, "mode": "Open-To-Everything", "execution_mode": "Live Assist"},
    )
    conn.commit()
    browser_result = (
        _run_safe_browser_execution_batch(
            conn,
            limit=30,
            execution_mode_override="Live Submit With Final Approval",
            context_override=context,
        )
        if allow_low_risk_live_submit
        else {
            "returncode": 0,
            "output": json.dumps(
                {
                    "submitted_external": 0,
                    "skipped": "Low-risk live submit toggle is off.",
                    "safety": "No external forms submitted.",
                },
                ensure_ascii=True,
                indent=2,
            ),
        }
    )
    if mark_blocked_for_rescan:
        _mark_ai_labor_rescan_later(conn)
    after = _ai_labor_snapshot(conn)
    submitted_external = _extract_json_int(str(browser_result.get("output") or ""), "submitted_external")
    output = {
        "seeded": seeded,
        "vault_safe_field_access": vault_access,
        "low_risk_live_submit": allow_low_risk_live_submit,
        "risk_on": risk_on,
        "treasury_route": treasury_route.strip(),
        "consent": consent_summary,
        "completion_engine": completion.to_dict(),
        "autonomous_worker": autonomy.to_dict(),
        "browser_execution": json.loads(str(browser_result.get("output") or "{}"))
        if str(browser_result.get("output") or "{}").strip().startswith("{")
        else str(browser_result.get("output") or ""),
        "before": before,
        "after": after,
        "submitted_external": submitted_external,
        "safety": (
            "AI Labor can scout, prepare, draft, inspect, autofill safe fields, and attempt consented low-risk submits. "
            "It does not bypass login, captcha/human tests, platform rules, tax, legal, identity, payment, purchase, or wallet signing gates."
        ),
    }
    return {
        "label": "AI LABOR ENGINE",
        "returncode": 0,
        "output": json.dumps(output, ensure_ascii=True, indent=2),
        "snapshot_before": before,
        "snapshot_after": after,
        "submitted_external": submitted_external,
    }


def _seed_ai_labor_lanes(store: SQLiteStore, *, risk_on: bool = False) -> dict[str, int]:
    created = 0
    updated = 0
    now = datetime.now(timezone.utc).isoformat()
    lanes = _ai_labor_lanes(risk_on)
    for lane in lanes:
        fingerprint = hashlib.sha256(
            json.dumps({"source": "AI LABOR ENGINE", "name": lane["name"], "url": lane["url"]}, sort_keys=True).encode("utf-8")
        ).hexdigest()
        candidate = {
            "source_name": "AI LABOR ENGINE",
            "source_type": "ai_labor_lane",
            "title": str(lane["name"]),
            "url": str(lane["url"]),
            "summary": str(lane["summary"]),
            "content_text": (
                f"{lane['summary']}\n"
                f"Category: {lane['category']}\n"
                f"AI labor path: scan -> prepare -> execute safe work -> route payout/approval -> track.\n"
                f"Stops on: {', '.join(str(x) for x in lane['stops_on'])}"
            ),
            "published_at": None,
            "fetched_at": now,
            "tags": ["ai-labor-engine", str(lane["category"]), str(lane["asset_type"])],
            "fingerprint": fingerprint,
            "raw": lane,
        }
        opportunity_id, is_new = store.save_candidate(candidate)
        score = _ai_labor_score(lane)
        prep = _ai_labor_prep(lane)
        store.update_opportunity_score(opportunity_id, score, "Needs Approval")
        _, queue_created = store.save_queue_item(opportunity_id, score, prep, "Needs Approval")
        created += int(queue_created or is_new)
        updated += int(not queue_created and not is_new)
    return {"lanes": len(lanes), "risk_on": risk_on, "created_or_new": created, "updated": updated}


def _ai_labor_score(lane: dict[str, object]) -> dict[str, object]:
    value = float(lane.get("expected_value_usd") or 0)
    probability = float(lane.get("probability") or 4)
    effort = float(lane.get("effort") or 5)
    ai_percent = float(lane.get("ai_percent") or 60)
    risk_level = str(lane.get("risk_level") or ("low" if "wallet" not in " ".join(str(x).lower() for x in lane.get("stops_on", [])) else "medium"))
    return {
        "gain_type": str(lane.get("asset_type") or "cash_rewards"),
        "expected_value_usd": value,
        "expected_value_rationale": "AI Labor lane estimate; real payout depends on external platform acceptance.",
        "probability_score_1_to_10": probability,
        "risk_level": risk_level,
        "risk_rationale": "Labor lane keeps platform/login/sensitive gates routed to owner approval; risk-on lanes are speculative.",
        "time_to_gain": "same day to weeks",
        "time_to_gain_days": 7,
        "owner_effort_required": "Minimal when safe; owner approves platform, login, payout, or final submit gates.",
        "owner_effort_minutes": effort * 3,
        "effort_score_1_to_10": effort,
        "ai_can_do_percent": ai_percent,
        "upfront_payment_required": False,
        "net_loss_possible": False,
        "illegal": False,
        "terms_violating": False,
        "scammy_or_terms_violating": False,
        "job_task_grind": True,
        "official_platform_action_required": True,
        "required_user_action": "approve",
        "real_asset_path": f"AI labor path can produce {lane.get('asset_type')} through {lane.get('url')}",
        "destination": _ai_labor_destination(str(lane.get("asset_type") or "")),
        "expected_delivery_method": _ai_labor_destination(str(lane.get("asset_type") or "")),
        "should_add_to_claim_queue": True,
        "fastest_gain_score": round((probability * max(value, 10.0)) / max(effort, 1.0), 2),
        "highest_value_score": round(value * max(probability, 1.0), 2),
        "summary": str(lane.get("summary") or ""),
        "disqualification_reasons": [],
    }


def _ai_labor_prep(lane: dict[str, object]) -> dict[str, str]:
    stops = ", ".join(str(x) for x in lane.get("stops_on", []))
    risk = str(lane.get("risk_level") or "low")
    return {
        "what_this_gain_is": f"{lane['name']} is an AI-labor acquisition lane.",
        "why_it_may_produce_real_asset_value": str(lane["summary"]),
        "exact_next_step": "AI scans the lane, prepares work/applications/submissions, attempts only safe consented execution, and routes blockers.",
        "ai_work_possible_now": "AI can scout, rank, draft, inspect forms, prepare safe fields, produce deliverables, and track payout/asset status.",
        "ai_work_completed": "Seeded into AI Labor Engine. Ready for dependency detection, autofill prep, and approval routing.",
        "user_approval_needed": f"Owner approval required for: {stops}.",
        "copy_paste_form_answers": "",
        "claim_instructions": f"Use official/public path only: {lane['url']}",
        "official_link": str(lane["url"]),
        "final_acceptance_step": "Owner reviews prepared labor packet and approves safe final submit or handles platform-only gate.",
        "asset_landing": _ai_labor_destination(str(lane.get("asset_type") or "")),
        "expected_delivery_method": _ai_labor_destination(str(lane.get("asset_type") or "")),
        "follow_up_tracking_step": "Track proposal/application/task/submission/payout until received or paid.",
        "recommended_status": "Needs Approval",
        "safety_notes": f"AI Labor risk={risk}. Stops on {stops}. No sensitive bypass, fake identity, or platform-rule evasion.",
    }


def _ai_labor_destination(asset_type: str) -> str:
    if asset_type == "physical_goods":
        return "Owner shipping address after approval"
    if asset_type == "crypto":
        return "Owner public wallet or platform account after owner-approved wallet/account step"
    if asset_type == "developer_credits":
        return "Owner platform account / business account"
    if asset_type == "digital_asset_value":
        return "Owner domain/marketplace account"
    return "Owner payout account, PayPal, platform wallet, or claim portal"


def _ai_labor_claim_ids(conn: sqlite3.Connection, limit: int = 400) -> list[int]:
    rows = conn.execute(
        """
        SELECT cq.id
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE o.source_name='AI LABOR ENGINE' OR o.source_type='ai_labor_lane' OR o.tags LIKE '%ai-labor-engine%'
        ORDER BY COALESCE(cq.fastest_gain_score, 0) DESC, COALESCE(cq.expected_value_usd, 0) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [int(row["id"]) for row in rows]


def _ai_labor_snapshot(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS queued,
            SUM(CASE WHEN cq.ai_can_do_percent >= 70 THEN 1 ELSE 0 END) AS ai_solo,
            SUM(CASE WHEN cq.execution_status='Ready To Accept' OR cq.status='Ready to Accept' OR cq.input_status='final_approval_required' THEN 1 ELSE 0 END) AS ready,
            SUM(CASE WHEN cq.status IN ('Submitted', 'Processing') OR cq.execution_status='Processing' THEN 1 ELSE 0 END) AS submitted_processing,
            SUM(CASE WHEN cq.execution_status='Paused Awaiting Input' OR cq.input_status IN ('needs_connect', 'missing_shipping', 'missing_payout', 'blocked') THEN 1 ELSE 0 END) AS blocked,
            SUM(CASE WHEN cq.status='Received/Paid' THEN 1 ELSE 0 END) AS received_paid
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE o.source_name='AI LABOR ENGINE' OR o.source_type='ai_labor_lane' OR o.tags LIKE '%ai-labor-engine%'
        """
    ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def _mark_ai_labor_rescan_later(conn: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE claim_queue
        SET next_action=COALESCE(NULLIF(next_action, ''), 'AI Labor: rescan this row after owner resolves the blocker or platform state changes.'),
            recommended_status=COALESCE(NULLIF(recommended_status, ''), 'Rescan Later'),
            updated_at=?
        WHERE id IN (
            SELECT cq.id
            FROM claim_queue cq
            JOIN opportunities o ON o.id = cq.opportunity_id
            WHERE (o.source_name='AI LABOR ENGINE' OR o.source_type='ai_labor_lane' OR o.tags LIKE '%ai-labor-engine%')
              AND (
                cq.execution_status='Paused Awaiting Input'
                OR cq.input_status IN ('needs_connect', 'missing_shipping', 'missing_payout', 'blocked', 'final_approval_required')
              )
        )
        """,
        (now,),
    )
    conn.commit()


def _apply_ai_labor_treasury_route(
    conn: sqlite3.Connection,
    treasury_route: str,
    claim_ids: list[int],
) -> None:
    if not claim_ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    placeholders = ",".join("?" for _ in claim_ids)
    conn.execute(
        f"""
        UPDATE claim_queue
        SET asset_destination=?,
            destination=COALESCE(NULLIF(destination, ''), ?),
            next_action=COALESCE(NULLIF(next_action, ''), 'AI Labor: route asset/payout/credit to treasury instruction after approval or reliable confirmation.'),
            updated_at=?
        WHERE id IN ({placeholders})
        """,
        [treasury_route, treasury_route, now, *claim_ids],
    )
    conn.commit()


def _show_ai_labor_result() -> None:
    result = st.session_state.get("ai_labor_last_result")
    if not isinstance(result, dict):
        return
    submitted = int(result.get("submitted_external") or 0)
    before = result.get("snapshot_before") if isinstance(result.get("snapshot_before"), dict) else {}
    after = result.get("snapshot_after") if isinstance(result.get("snapshot_after"), dict) else {}
    st.success(f"AI Labor pass finished. External low-risk submissions: {submitted}.")
    cols = st.columns(5)
    for index, key in enumerate(["queued", "ai_solo", "ready", "submitted_processing", "blocked"]):
        cols[index].metric(key.replace("_", " ").title(), after.get(key, 0), int(after.get(key, 0) or 0) - int(before.get(key, 0) or 0))
    with st.expander("AI Labor run details", expanded=False):
        st.code(str(result.get("output") or "")[-8000:], language="json")


def _show_ai_labor_tables(conn: sqlite3.Connection) -> None:
    st.markdown("**AI Labor Work Queue**")
    df = pd.read_sql_query(
        """
        SELECT
            cq.id,
            cq.status,
            cq.execution_status,
            cq.input_status AS readiness,
            o.title,
            cq.expected_value_usd,
            cq.probability_score_1_to_10,
            cq.risk_level,
            cq.ai_can_do_percent,
            cq.asset_type,
            cq.destination,
            cq.asset_destination,
            cq.next_action,
            cq.human_input_needed,
            cq.official_link
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE o.source_name='AI LABOR ENGINE' OR o.source_type='ai_labor_lane' OR o.tags LIKE '%ai-labor-engine%'
        ORDER BY COALESCE(cq.ai_can_do_percent, 0) DESC, COALESCE(cq.expected_value_usd, 0) DESC
        LIMIT 200
        """,
        conn,
    )
    show_dataframe(df)
    blocked = df[
        df["execution_status"].fillna("").str.contains("Paused", case=False, na=False)
        | df["readiness"].fillna("").isin(["needs_connect", "missing_shipping", "missing_payout", "blocked", "final_approval_required"])
    ] if not df.empty else df
    if not blocked.empty:
        st.markdown("**INDENTURED AI SERVITUDE - Needs Owner / Later Rescan**")
        st.caption(
            "These are the rows AI keeps warm but cannot ethically or technically finish alone yet: accept/approve gates, "
            "human tasks, login/platform gates, payout/tax/legal/identity/wallet authority, or external waits."
        )
        show_dataframe(blocked[["id", "status", "readiness", "risk_level", "title", "next_action", "human_input_needed", "official_link"]])


def show_global_page_links(active: str = "") -> None:
    links = [
        ("dashboard", "Main Dashboard", "/"),
        ("easy", "EASY", "/?page=easy"),
        ("ai_labor", "AI LABOR ENGINE", "/?page=ai_labor"),
        ("treasury", "Entity Treasury", "/?page=treasury"),
        ("chaos", "CHAOS MODE", "/?page=chaos"),
        ("connectors", "Live Connectors", "/?page=connectors"),
        ("vault", "Vault", "/?page=vault"),
        ("fastest", "Fastest Gains", "/?view=fastest&sort=fastest#active-operator-table"),
        ("approvals", "Approvals", "/?view=approvals&sort=value#active-operator-table"),
        ("execution", "Execution", "/?view=execution&sort=updated#active-operator-table"),
        ("ready", "Ready / $$$", "/?view=ready&sort=value#active-operator-table"),
        ("blocked", "Blocked", "/?view=blocked&sort=readiness#active-operator-table"),
    ]
    body = "".join(
        f'<a class="retro-tool retro-action-link {"active" if key == active else ""}" target="_self" href="{href}">{label}</a>'
        for key, label, href in links
    )
    st.markdown(
        f"""
        <div class="global-page-links">
          <div class="operator-workbench-title">NAVIGATION.NET</div>
          <div class="retro-toolbar">{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _dashboard_escape_button(label: str) -> None:
    components.html(
        f"""
        <button
          style="
            width:100%;
            padding:8px 10px;
            border:2px solid #555;
            background:#e8e8e8;
            box-shadow:inset 1px 1px 0 #fff,inset -1px -1px 0 #555;
            color:#005f87;
            font-family:monospace;
            font-weight:800;
            cursor:pointer;
          "
          onclick="window.top.location.href='http://localhost:8501/?view=opportunities&sort=value#active-operator-table';"
        >{html.escape(label)}</button>
        """,
        height=48,
    )


def show_external_wallet_routes_panel() -> None:
    routes = load_external_wallet_routes(ROOT_DIR)
    st.markdown("**External Public Wallet Routes**")
    st.caption(
        "Reads public receiving addresses from the external crypto acquirer folder and optional wallet route files. "
        "Passwords, private keys, seed phrases, recovery phrases, SSNs, and bank credentials are ignored."
    )
    metric_cols = st.columns(4)
    metric_cols[0].metric("Public routes found", routes.found_count)
    metric_cols[1].metric("Source files", len(routes.source_files))
    metric_cols[2].metric("Ignored secret-like fields", len(routes.ignored))
    metric_cols[3].metric("Warnings", len(routes.warnings))

    if routes.source_files:
        st.caption("Sources: " + " | ".join(str(Path(path).name) for path in routes.source_files))
    if routes.found_count:
        show_dataframe(pd.DataFrame(routes.redacted_rows()))
        st.info(
            "These routes are available to User Context, Required Inputs, autofill previews, and destination routing as "
            "public receiving addresses only. Wallet signing remains owner-only."
        )
    else:
        st.warning(
            "No public wallet routes were detected. Add rows to the external crypto_tool.db wallets table or create "
            "data/external_wallet_routes.json / Desktop/free_crypto_acquirer_pure/wallet_routes.json."
        )

    if routes.warnings:
        with st.expander("Wallet route warnings", expanded=False):
            for warning in routes.warnings[:25]:
                st.write(warning)
    if routes.ignored:
        with st.expander("Ignored secret-like fields", expanded=False):
            for ignored in routes.ignored[:25]:
                st.write(ignored)

    if routes.found_count and st.button("Sync Public Wallet Routes Into Vault", key="sync_external_wallet_routes", use_container_width=True):
        stored = USER_CONTEXT_STORE.load()
        synced = apply_external_wallet_routes(stored, ROOT_DIR, overwrite=True)
        USER_CONTEXT_STORE.save(synced)
        st.success("Public wallet receiving routes synced into the safe User Vault fields.")
        st.rerun()


def show_vault_operations_page(conn: sqlite3.Connection) -> None:
    context = load_effective_user_context()
    completeness = compute_completeness(context)
    dependencies = global_input_dependency_map(rows_for_action_center(conn))
    st.caption(
        "Owner-controlled setup for reusable safe autofill, external account authorization, optional encrypted credentials, "
        "and final-submit consent policy. This page does not store SSNs, identity documents, seed phrases, private keys, "
        "full bank numbers, or wallet signing keys."
    )
    cols = st.columns(4)
    cols[0].metric("Context Completeness", f"{completeness.automation_readiness_score:.1f}%")
    cols[1].metric("Missing Inputs", len(completeness.missing_inputs))
    cols[2].metric("Top Unlocks", dependencies[0].number_unblocked if dependencies else 0)
    cols[3].metric("Blocked Groups", len(dependencies))

    tabs = st.tabs(
        [
            "Safe Autofill Profile",
            "External Wallet Routes",
            "Credential Sign-In",
            "External Connectors",
            "Submit Consent",
            "Unlock Map",
        ]
    )
    with tabs[0]:
        show_user_profile_autofill_vault(conn, standalone=False)
    with tabs[1]:
        show_external_wallet_routes_panel()
    with tabs[2]:
        st.markdown("**Credential Sign-In Vault**")
        st.caption(
            "Optional, owner-controlled encrypted credential storage. AI can only use this after you unlock it in-session "
            "and only for login-assisted prep; sensitive final actions still stop."
        )
        show_credential_vault_panel()
    with tabs[3]:
        show_external_authorization_hub()
    with tabs[4]:
        show_submission_consent_policy_panel()
        st.info(
            "Low-risk live-submit authorization is per final approval packet. Payment, legal, tax, identity, purchase, "
            "wallet signing, and account connection remain blocked."
        )
    with tabs[5]:
        show_global_input_dependency_map(dependencies)


def process_operator_action(conn: sqlite3.Connection) -> None:
    try:
        action = str(st.query_params.get("operator_action") or "")
    except Exception:  # noqa: BLE001
        action = ""
    if not action:
        return

    _set_operator_route_for_action(action)
    result: dict[str, object] | None = None
    if action == "review_task":
        st.session_state["operator_show_review_task"] = True
        st.session_state["operator_show_dependencies"] = False
        result = {"label": "Review Task", "message": "Current task panel opened.", "status": "ok"}
    elif action == "dependencies":
        st.session_state["operator_show_dependencies"] = True
        st.session_state["operator_show_review_task"] = False
        result = {"label": "Dependencies", "message": "Dependency workbench opened.", "status": "ok"}
    elif action == "discovery":
        command_result = _run_broad_fetch_scan()
        result = {"label": "Discovery scan", **command_result}
    elif action == "completion_sync":
        summary = run_completion_engine_pass(
            conn,
            load_effective_user_context(),
            mode="Live Assist",
            commit=True,
        )
        conn.commit()
        result = {
            "label": "Completion sync",
            "returncode": 0,
            "output": json.dumps(summary.to_dict(), ensure_ascii=True, indent=2),
        }
    elif action == "live_assist_prep":
        completion = run_completion_engine_pass(
            conn,
            load_effective_user_context(),
            mode="Live Assist",
            commit=True,
        )
        autonomy = run_autonomous_queue_pass(
            conn,
            ROOT_DIR,
            {"enabled": True, "mode": "Open-To-Everything", "execution_mode": "Live Assist"},
        )
        conn.commit()
        result = {
            "label": "Live Assist prep",
            "returncode": 0,
            "output": json.dumps(
                {
                    "completion_engine": completion.to_dict(),
                    "autonomous_worker": autonomy.to_dict(),
                    "external_submission": "not_performed",
                },
                ensure_ascii=True,
                indent=2,
            ),
        }
    elif action == "browser_execute_safe_batch":
        result = {"label": "Safe browser execute", **_run_safe_browser_execution_batch(conn)}
    elif action == "safe_auto_cycle":
        command_result = _run_safe_automation_cycle()
        result = {"label": "Safe automation cycle", **command_result}
    elif action == "magic_money_scout":
        command_result = _run_magic_money_scout()
        result = {"label": "MAGIC FAIRYTALE MONIES!", **command_result}
    elif action == "autonomy_pump":
        command_result = _run_autonomy_pump()
        result = {"label": "Autonomy pump", **command_result}
    elif action == "autonomy_boost":
        command_result = _run_autonomy_boost()
        result = {"label": "Autonomy boost", **command_result}
    elif action == "completion_pass":
        summary = run_completion_engine_pass(
            conn,
            load_effective_user_context(),
            mode=str(load_autorun_control().get("execution_mode") or "Dry Run"),
            commit=str(load_autorun_control().get("execution_mode") or "Dry Run") != "Dry Run",
        )
        conn.commit()
        result = {
            "label": "Completion pass",
            "returncode": 0,
            "output": json.dumps(summary.to_dict(), ensure_ascii=True, indent=2),
        }
    elif action == "fast_path_accept_all_safe":
        items = build_final_approval_queue(rows_for_final_approval(conn, limit=1000))
        bulk_safe_items = [
            item for item in items if item.safe_to_mark_submitted and item.final_action_type == "final_submit"
        ]
        result = _apply_bulk_final_approval(
            conn,
            bulk_safe_items,
            "Approve Final Step",
            only_bulk_safe=True,
        )
        st.session_state["operator_active_view"] = "execution"
        st.session_state["operator_active_sort"] = "updated"
        st.session_state["operator_focus_message"] = "Fast Path accepted all bulk-safe final-submit packets."
    elif action == "fastest_triage_all":
        rows = _fastest_gain_rows(conn)
        result = _apply_operator_selected_action(
            conn,
            [int(row["id"]) for row in rows],
            "approve_possible_route_rest",
        )
        st.session_state["operator_active_view"] = "fastest"
        st.session_state["operator_active_sort"] = "fastest"
        st.session_state["operator_focus_message"] = "Fastest Gains triage ran: safe items advanced, owner-gated items routed to next steps."
    else:
        result = {"label": action, "returncode": 1, "output": "Unknown operator action."}

    st.session_state["operator_last_result"] = result
    st.session_state["operator_last_action"] = action
    try:
        st.query_params.clear()
    except Exception:  # noqa: BLE001
        pass
    st.rerun()


APPROVAL_ACTIONS = {
    "approve": "Approve Final Step",
    "reject": "Reject",
    "later": "Later",
    "more_info": "Needs More Info",
}


def process_approval_action(conn: sqlite3.Connection) -> None:
    action_key = _query_param("approval_action")
    if not action_key:
        return

    action = APPROVAL_ACTIONS.get(action_key)
    result: dict[str, object]
    try:
        claim_queue_id = int(_query_param("claim_id", "0"))
    except ValueError:
        claim_queue_id = 0

    if not action or claim_queue_id <= 0:
        result = {
            "label": "Final approval",
            "returncode": 1,
            "output": "Final approval action was missing a valid action or claim id.",
        }
    else:
        detail = load_claim_detail(conn, claim_queue_id)
        if not detail:
            result = {
                "label": "Final approval",
                "returncode": 1,
                "output": f"No claim queue row found for id {claim_queue_id}.",
            }
        else:
            action_type = _query_param("final_action_type") or final_action_type(dict(detail)) or "final_submit"
            note = apply_final_approval_action(conn, claim_queue_id, action_type, action)
            conn.commit()
            _set_operator_route_after_approval(action_key)
            result = {
                "label": "Final approval",
                "returncode": 0,
                "output": (
                    f"{action} recorded for claim #{claim_queue_id} ({action_type}).\n"
                    f"{note}\n"
                    "Sensitive final actions still require owner execution inside the official platform."
                ),
            }

    st.session_state["operator_last_result"] = result
    st.session_state["operator_last_action"] = f"approval:{action_key}"
    try:
        st.query_params.clear()
    except Exception:  # noqa: BLE001
        pass
    st.rerun()


def process_dream_action() -> None:
    raw = _query_param("dream_asset")
    if not raw:
        return
    assets = _load_dream_assets()
    existing_keys = {str(asset.get("key") or "") for asset in assets}
    added = 0
    for asset_text in _split_dream_inputs(raw):
        assessed = _assess_dream_asset(asset_text)
        if assessed["key"] in existing_keys:
            continue
        assets.append(assessed)
        existing_keys.add(str(assessed["key"]))
        added += 1
    _save_dream_assets(assets)
    st.session_state["dream_last_result"] = f"DREAM! added {added} asset{'s' if added != 1 else ''}."
    st.session_state["operator_active_view"] = "opportunities"
    try:
        st.query_params.clear()
    except Exception:  # noqa: BLE001
        pass
    st.rerun()


def load_effective_user_context() -> dict[str, Any]:
    context = apply_external_authorizations(USER_CONTEXT_STORE.load(), external_authorization_rows(ROOT_DIR))
    return apply_external_wallet_routes(context, ROOT_DIR)


def _set_operator_route_for_action(action: str) -> None:
    view_by_action = {
        "review_task": "ready",
        "dependencies": "blocked",
        "discovery": "sources",
        "completion_sync": "claim_queue",
        "completion_pass": "claim_queue",
        "live_assist_prep": "execution",
        "safe_auto_cycle": "ready",
        "magic_money_scout": "opportunities",
        "autonomy_pump": "execution",
        "autonomy_boost": "ready",
    }
    sort_by_action = {
        "review_task": "value",
        "dependencies": "readiness",
        "discovery": "updated",
        "completion_sync": "readiness",
        "completion_pass": "readiness",
        "live_assist_prep": "updated",
        "safe_auto_cycle": "value",
        "magic_money_scout": "updated",
        "autonomy_pump": "updated",
        "autonomy_boost": "value",
    }
    view = view_by_action.get(action, "opportunities")
    st.session_state["operator_active_view"] = view
    st.session_state["operator_active_sort"] = sort_by_action.get(action, "value")
    st.session_state["operator_focus_message"] = f"Routed by {action.replace('_', ' ').title()}."


def _set_operator_route_after_approval(action_key: str) -> None:
    if action_key == "approve":
        st.session_state["operator_active_view"] = "execution"
        st.session_state["operator_active_sort"] = "updated"
    elif action_key == "reject":
        st.session_state["operator_active_view"] = "history"
        st.session_state["operator_active_sort"] = "updated"
    else:
        st.session_state["operator_active_view"] = "approvals"
        st.session_state["operator_active_sort"] = "updated"
    st.session_state["operator_focus_message"] = f"Approval action routed to {ROUTE_VIEWS.get(st.session_state['operator_active_view'], 'table')}."


def show_broad_gain_sweep_control(conn: sqlite3.Connection) -> None:
    counts = {
        "opportunities": _count_rows(conn, "opportunities"),
        "claim_queue": _count_rows(conn, "claim_queue"),
        "source_candidates": _count_rows(conn, "source_candidates"),
        "approved_sources": _count_rows(conn, "approved_sources"),
    }
    with st.expander("Broad Gain Sweep", expanded=False):
        st.caption(
            "Runs the existing discovery pipeline with the expanded wide-net source graph. "
            "This fetches and stores candidates only; scoring, approval, autofill, and final submission gates stay unchanged."
        )
        metric_cols = st.columns(4)
        metric_cols[0].metric("Opportunities", counts["opportunities"])
        metric_cols[1].metric("Claim Queue", counts["claim_queue"])
        metric_cols[2].metric("Source Candidates", counts["source_candidates"])
        metric_cols[3].metric("Approved Sources", counts["approved_sources"])
        run_cols = st.columns([1, 1, 2])
        if run_cols[0].button("Run Broad Fetch Scan", key="run_broad_gain_sweep", use_container_width=True):
            result = _run_broad_fetch_scan()
            if result["returncode"] == 0:
                st.success("Broad fetch scan finished. Refreshing dashboard data.")
            else:
                st.warning("Broad fetch scan finished with warnings/errors.")
            if result["output"]:
                st.code(str(result["output"])[-4000:], language="text")
            st.rerun()
        if run_cols[1].button("Run Autonomy Boost", key="run_autonomy_boost", use_container_width=True):
            result = _run_autonomy_boost()
            if result["returncode"] == 0:
                st.success("Autonomy boost finished. Safe local prep was advanced.")
            else:
                st.warning("Autonomy boost finished with warnings/errors.")
            if result["output"]:
                st.code(str(result["output"])[-5000:], language="text")
            st.rerun()
        run_cols[2].caption(
            "Best used with Open-To-Everything discovery and Dry Run execution: find broadly, rank safely, prepare locally, then ask only when needed."
        )


def show_retro_adapter_contract() -> None:
    st.markdown('<div id="command-os-adapter-contract"></div>', unsafe_allow_html=True)
    with st.expander("Command OS Adapter Contract", expanded=False):
        st.caption(
            "Visual and interaction map adapted from the supplied React retro command OS. "
            "Buttons below are either wired to existing Python behavior or explicitly marked not wired yet."
        )
        contract_rows = [
            {
                "UI action": "Open official path",
                "Adapter": "open_source(opportunity_id)",
                "Current Streamlit behavior": "Official links open through existing link buttons in queue/detail views.",
                "Status": "wired",
            },
            {
                "UI action": "Build autofill plan",
                "Adapter": "autofill_planner.build_plan(claim_id, user_context)",
                "Current Streamlit behavior": "Connector + Autofill Readiness and dependency map call real planner code.",
                "Status": "wired",
            },
            {
                "UI action": "Save vault section",
                "Adapter": "UserContextStore.save(section, payload)",
                "Current Streamlit behavior": "User Vault / Autofill Profile writes safe User Context fields.",
                "Status": "wired",
            },
            {
                "UI action": "Apply queue action",
                "Adapter": "claim_queue.apply_action(row_id, action)",
                "Current Streamlit behavior": "Claim Queue Status Control updates queue statuses.",
                "Status": "wired",
            },
            {
                "UI action": "Mark received/paid",
                "Adapter": "received_paid.mark(row_id, receipt_payload)",
                "Current Streamlit behavior": "Received / Paid tracking uses received_paid.mark_received_paid.",
                "Status": "wired",
            },
            {
                "UI action": "Approve final packet",
                "Adapter": "final_approval_queue.approve(packet_id)",
                "Current Streamlit behavior": "Final Approval Queue and Ready To Accept packet actions are approval-gated.",
                "Status": "wired",
            },
            {
                "UI action": "Popup mini-windows",
                "Adapter": "retro window manager",
                "Current Streamlit behavior": "Streamlit expanders/tabs used instead.",
                "Status": "not wired yet",
            },
        ]
        show_dataframe(pd.DataFrame(contract_rows))
        st.caption(
            "Safety contract: no passwords, seed phrases, SSNs, full bank numbers, identity documents, wallet signing keys, "
            "payment authorization, purchases, or external final submissions are stored or executed here."
        )


def show_completion_engine_control(conn: sqlite3.Connection, preview_summary: object | None = None) -> None:
    with st.expander("Completion Engine Pass", expanded=False):
        st.caption(
            "Coordinates the existing queue, Required Inputs, User Context, dependency map, autofill planner, "
            "destination routing, Action Engine, and Final Approval detector. It writes safe local prep state only; "
            "no external forms are submitted."
        )
        if preview_summary:
            _show_work_summary_metrics(preview_summary)

        control = load_autorun_control()
        mode = str(control.get("execution_mode") or "Dry Run")
        dry_run = st.checkbox(
            "Dry run only",
            value=True,
            key="completion_engine_dry_run_only",
            help="When enabled, computes the pass without changing queue rows.",
        )
        cols = st.columns([1, 1, 3])
        if cols[0].button("Run Completion Pass", key="run_completion_engine_pass", use_container_width=True):
            summary = run_completion_engine_pass(
                conn,
                load_effective_user_context(),
                mode=mode,
                commit=not dry_run,
            )
            if dry_run:
                st.info("Completion pass dry run finished. No queue rows changed.")
            else:
                st.success("Completion pass synchronized safe local queue state.")
            _show_work_summary_metrics(summary)
            st.rerun()
        if cols[1].button("Run Live Assist Prep", key="run_completion_engine_live_assist", use_container_width=True):
            summary = run_completion_engine_pass(
                conn,
                load_effective_user_context(),
                mode="Live Assist",
                commit=True,
            )
            st.success("Live Assist prep synchronized. External submissions remain blocked.")
            _show_work_summary_metrics(summary)
            st.rerun()
        cols[2].caption(
            "This is the utility bridge: safe reusable data gets prepared once, blockers become explicit, "
            "ready items route to final approval packets, and queue rows stay the source of truth."
        )


def show_operator_command_center(
    conn: sqlite3.Connection,
    autonomy_summary: object | None = None,
    completion_summary: object | None = None,
) -> None:
    st.markdown(
        """
        <div id="operator-console" class="operator-console">
          <div class="operator-console-title">OPERATOR CONSOLE.EXE - REAL CONTROLS</div>
          <div class="operator-console-note">
            Discovery -> dependency sync -> safe autofill prep -> approval packets -> tracking. External submit remains blocked unless explicitly approved.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metrics = load_metrics(conn)
    status = autorun_status_summary(conn)
    dependencies = global_input_dependency_map(rows_for_action_center(conn))
    top_cols = st.columns(6)
    top_cols[0].metric("Opportunities", metrics["opportunities"])
    top_cols[1].metric("Claim Queue", metrics["claim_queue"])
    top_cols[2].metric("Ready/Approval", status["waiting_approval"])
    top_cols[3].metric("AI Preparing", status["ai_preparing"])
    top_cols[4].metric("Paused", status["paused"])
    top_cols[5].metric("Blockers", len(dependencies))

    st.markdown(
        """
        <div class="retro-toolbar" style="margin:8px 0;">
          <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=discovery">Fetch Scan</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=autonomy_boost">Autonomy Boost</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=completion_pass">Completion Pass</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=completion_sync">Completion Sync</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=live_assist_prep">Live Assist Prep</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=browser_execute_safe_batch">Safe Browser Execute</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=safe_auto_cycle">Safe Auto Cycle</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=autonomy_pump">Autonomy Pump</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=magic_money_scout">MAGIC FAIRYTALE MONIES!</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?page=vault">Open Vault</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=review_task">Review Task</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=dependencies">Dependencies</a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    last_result = st.session_state.get("operator_last_result")
    if isinstance(last_result, dict):
        _show_command_result(str(last_result.get("label") or "Operator action"), last_result)

    show_final_approval_quick_gate(conn)

    if completion_summary:
        st.caption("Completion preview from current AUTORUN mode:")
        _show_work_summary_metrics(completion_summary)
    if autonomy_summary:
        st.caption("Autonomous worker preview from current AUTORUN mode:")
        _show_work_summary_metrics(autonomy_summary)

    st.markdown(
        """
        <div class="operator-workbench">
          <div class="operator-workbench-title">WORKBENCH.DAT - CURRENT ROUTE</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    workbench_tabs = st.tabs(["Current Task", "Top Dependencies", "Blocked Reasons"])
    with workbench_tabs[0]:
        show_current_ai_task_card(conn)
    with workbench_tabs[1]:
        _show_compact_dependency_workbench(dependencies)
    with workbench_tabs[2]:
        show_autorun_blocked_reasons(conn)

    if st.session_state.get("operator_show_review_task"):
        show_current_ai_task_card(conn)
        show_ready_to_accept_packets(conn)
    if st.session_state.get("operator_show_dependencies"):
        show_global_input_dependency_map(dependencies)


def show_final_approval_quick_gate(conn: sqlite3.Connection) -> None:
    items = build_final_approval_queue(rows_for_final_approval(conn, limit=1000))
    bulk_safe_items = [
        item for item in items if item.safe_to_mark_submitted and item.final_action_type == "final_submit"
    ]
    safe_count = len(bulk_safe_items)
    owner_only_count = len(items) - safe_count
    st.markdown(
        """
        <div class="operator-workbench approval-gate">
          <div class="operator-workbench-title">APPROVAL GATE.EXE - READY OWNER DECISIONS</div>
          <div class="operator-console-note">
            AI prepares everything it can. The owner approval buttons stay available whenever a final submit, login,
            legal, tax, identity, purchase, wallet, or sensitive claim gate appears.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    gate_cols = st.columns(4)
    gate_cols[0].metric("Approval Items", len(items))
    gate_cols[1].metric("Bulk-Safe Submit", safe_count)
    gate_cols[2].metric("Owner-Only Gates", owner_only_count)
    gate_cols[3].metric("Mode", str(load_autorun_control().get("execution_mode") or "Dry Run"))

    if not items:
        st.info("No final approval packets are waiting right now. AI can keep scanning, prepping, and routing safe work.")
        return

    _show_bulk_approval_console(conn, items, bulk_safe_items)

    rows = []
    for item in items[:12]:
        rows.append(
            {
                "id": item.claim_queue_id,
                "title": item.opportunity_title,
                "value": round(item.expected_gain_value, 2),
                "risk": item.risk_level,
                "final_action": item.final_action_type,
                "safe_submit": item.safe_to_mark_submitted,
                "why": item.why_approval_required,
            }
        )
    show_dataframe(pd.DataFrame(rows))

    st.markdown('<div class="approval-stack">', unsafe_allow_html=True)
    for item in items[:5]:
        st.markdown(_approval_card_html(item), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.caption(
        "Approve moves safe final-submit packets into Submitted/processing through the existing queue. "
        "Payment, purchase, legal, tax, identity, wallet signing, and login actions stay owner-executed."
    )


def _show_bulk_approval_console(conn: sqlite3.Connection, items: list[object], bulk_safe_items: list[object]) -> None:
    st.markdown("**Bulk Owner Approval Console**")
    st.caption(
        "This is the mass-approval table. Select all low-risk owner approvals to advance every safe prepared item; "
        "sensitive gates are still shown here, but bulk approve skips them and leaves them for item-by-item decisions."
    )
    visible_items = items[:80]
    preset_cols = st.columns([1.2, 1.6, 1, 2.4])
    select_all_visible = preset_cols[0].checkbox("Select all visible decisions", key="bulk_approval_select_all_visible")
    select_all_safe = preset_cols[1].checkbox("Select all low-risk owner approvals", key="bulk_approval_select_all_safe")
    if preset_cols[2].button("Clear Selection", use_container_width=True):
        st.session_state["bulk_approval_select_all_visible"] = False
        st.session_state["bulk_approval_select_all_safe"] = False
        st.rerun()
    preset_cols[3].caption(
        "Low-risk means prepared final-submit packets with no detected payment, purchase, login, legal, tax, identity, or wallet-signing gate."
    )
    editable_rows = []
    for item in visible_items:
        bulk_safe = bool(
            getattr(item, "safe_to_mark_submitted", False)
            and str(getattr(item, "final_action_type", "")) == "final_submit"
        )
        editable_rows.append(
            {
                "select": bool(select_all_visible or (select_all_safe and bulk_safe)),
                "id": int(getattr(item, "claim_queue_id", 0) or 0),
                "title": str(getattr(item, "opportunity_title", "Untitled")),
                "value": round(float(getattr(item, "expected_gain_value", 0.0) or 0.0), 2),
                "gate": str(getattr(item, "final_action_type", "")),
                "risk": str(getattr(item, "risk_level", "")),
                "bulk_safe": bulk_safe,
                "owner_decision_group": "LOW-RISK BULK" if bulk_safe else "OWNER-ONLY / REVIEW",
                "why": str(getattr(item, "why_approval_required", "")),
            }
        )
    if not editable_rows:
        return
    edited = st.data_editor(
        pd.DataFrame(editable_rows),
        width="stretch",
        hide_index=True,
        disabled=["id", "title", "value", "gate", "risk", "bulk_safe", "owner_decision_group", "why"],
        column_config={
            "select": st.column_config.CheckboxColumn("Select", help="Pick rows for a bulk owner action."),
            "bulk_safe": st.column_config.CheckboxColumn("Bulk Safe"),
        },
        key=f"bulk_final_approval_editor_{int(select_all_visible)}_{int(select_all_safe)}",
    )
    selected_ids = _selected_bulk_approval_ids(edited)
    item_by_id = {int(getattr(item, "claim_queue_id", 0) or 0): item for item in items}

    cols = st.columns([1.3, 1, 1, 1.5, 1.4])
    if cols[0].button("Approve Selected Low-Risk", use_container_width=True, disabled=not selected_ids):
        result = _apply_bulk_final_approval(
            conn,
            [item_by_id[item_id] for item_id in selected_ids if item_id in item_by_id],
            "Approve Final Step",
            only_bulk_safe=True,
        )
        st.session_state["operator_last_result"] = result
        st.session_state["operator_active_view"] = "execution"
        st.session_state["operator_active_sort"] = "updated"
        st.rerun()
    if cols[1].button("Later Selected", use_container_width=True, disabled=not selected_ids):
        result = _apply_bulk_final_approval(
            conn,
            [item_by_id[item_id] for item_id in selected_ids if item_id in item_by_id],
            "Later",
            only_bulk_safe=False,
        )
        st.session_state["operator_last_result"] = result
        st.session_state["operator_active_view"] = "approvals"
        st.session_state["operator_active_sort"] = "updated"
        st.rerun()
    if cols[2].button("More Info Selected", use_container_width=True, disabled=not selected_ids):
        result = _apply_bulk_final_approval(
            conn,
            [item_by_id[item_id] for item_id in selected_ids if item_id in item_by_id],
            "Needs More Info",
            only_bulk_safe=False,
        )
        st.session_state["operator_last_result"] = result
        st.session_state["operator_active_view"] = "approvals"
        st.session_state["operator_active_sort"] = "updated"
        st.rerun()
    if cols[3].button("Approve All Low-Risk Owner Approvals", use_container_width=True, disabled=not bulk_safe_items):
        result = _apply_bulk_final_approval(
            conn,
            bulk_safe_items,
            "Approve Final Step",
            only_bulk_safe=True,
        )
        st.session_state["operator_last_result"] = result
        st.session_state["operator_active_view"] = "execution"
        st.session_state["operator_active_sort"] = "updated"
        st.rerun()
    confirm_reject = cols[4].checkbox("Enable Reject Selected", key="bulk_approval_enable_reject")
    if cols[4].button("Reject Selected", use_container_width=True, disabled=not selected_ids or not confirm_reject):
        result = _apply_bulk_final_approval(
            conn,
            [item_by_id[item_id] for item_id in selected_ids if item_id in item_by_id],
            "Reject",
            only_bulk_safe=False,
        )
        st.session_state["operator_last_result"] = result
        st.session_state["operator_active_view"] = "history"
        st.session_state["operator_active_sort"] = "updated"
        st.rerun()


def _selected_bulk_approval_ids(edited: object) -> list[int]:
    if not isinstance(edited, pd.DataFrame) or "select" not in edited.columns:
        return []
    selected = edited[edited["select"].fillna(False)]
    ids: list[int] = []
    for value in selected.get("id", []):
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def _apply_bulk_final_approval(
    conn: sqlite3.Connection,
    selected_items: list[object],
    action: str,
    *,
    only_bulk_safe: bool,
) -> dict[str, object]:
    applied = 0
    skipped = 0
    lines: list[str] = []
    for item in selected_items:
        claim_id = int(getattr(item, "claim_queue_id", 0) or 0)
        action_type = str(getattr(item, "final_action_type", "") or "")
        bulk_safe = bool(getattr(item, "safe_to_mark_submitted", False) and action_type == "final_submit")
        title = str(getattr(item, "opportunity_title", "Untitled"))
        if only_bulk_safe and not bulk_safe:
            skipped += 1
            lines.append(f"SKIP #{claim_id}: {title} requires item-by-item owner approval ({action_type}).")
            continue
        note = apply_final_approval_action(conn, claim_id, action_type, action)
        applied += 1
        lines.append(f"{action} #{claim_id}: {title} -> {note}")
    if not lines:
        lines.append("No selected items were eligible for this bulk action.")
    lines.append("")
    lines.append(f"Applied: {applied}")
    lines.append(f"Skipped: {skipped}")
    if only_bulk_safe:
        lines.append("Bulk approve only applies to low-risk final_submit packets. Sensitive gates remain blocked.")
    return {
        "label": f"Bulk {action}",
        "returncode": 0 if applied or skipped else 1,
        "output": "\n".join(lines),
    }


def _approval_card_html(item: object) -> str:
    title = html.escape(str(getattr(item, "opportunity_title", "Untitled")))
    action_type = html.escape(str(getattr(item, "final_action_type", "final_submit")))
    risk = html.escape(str(getattr(item, "risk_level", "unknown")))
    why = html.escape(str(getattr(item, "why_approval_required", "")))
    claim_id = int(getattr(item, "claim_queue_id", 0) or 0)
    value = float(getattr(item, "expected_gain_value", 0.0) or 0.0)
    return f"""
      <div class="approval-card">
        <div class="approval-card-main">
          <div class="approval-card-title">#{claim_id} {title}</div>
          <div class="approval-card-meta">value ${value:,.2f} | risk {risk} | gate {action_type}</div>
          <div class="approval-card-why">{why}</div>
        </div>
        <div class="approval-card-actions">
          <a class="retro-tool retro-action-link" target="_self" href="/?view=approvals&sort=value#active-operator-table">Review Packet</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?approval_action=approve&claim_id={claim_id}&final_action_type={action_type}">Approve</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?approval_action=later&claim_id={claim_id}&final_action_type={action_type}">Later</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?approval_action=more_info&claim_id={claim_id}&final_action_type={action_type}">More Info</a>
          <a class="retro-tool retro-action-link" target="_self" href="/?approval_action=reject&claim_id={claim_id}&final_action_type={action_type}">Reject</a>
        </div>
      </div>
    """


def _show_command_result(label: str, result: dict[str, object]) -> None:
    if result.get("returncode") == 0:
        st.success(f"{label} completed.")
    else:
        st.warning(f"{label} completed with warnings/errors.")
    output = str(result.get("output") or "").strip()
    if output:
        st.code(output[-6000:], language="text")


def _show_compact_dependency_workbench(dependencies: list[object]) -> None:
    if not dependencies:
        st.write("No repeated missing inputs are blocking the current queue.")
        return
    rows = []
    for dependency in dependencies[:8]:
        rows.append(
            {
                "input": dependency.display_name,
                "unlocks": dependency.number_unblocked,
                "unlock_score": round(float(dependency.unlock_score), 2),
                "target": dependency.target_section,
                "next action": dependency.prompt,
                "blocked examples": ", ".join(dependency.blocks[:3]),
            }
        )
    show_dataframe(pd.DataFrame(rows))
    st.caption("These are computed from the current queue dependency graph, not hand-entered estimates.")


ROUTE_VIEWS = {
    "opportunities": "Opportunities",
    "claim_queue": "Claim Queue",
    "fastest": "Fastest Gains",
    "sources": "Sources",
    "approvals": "Approvals",
    "execution": "Execution",
    "ready": "Ready To Accept",
    "blocked": "Blocked / Needs Input",
    "history": "History",
}

ROUTE_SORTS = {
    "id": "cq.id",
    "status": "cq.status",
    "readiness": "cq.input_status",
    "value": "cq.expected_value_usd",
    "fastest": "cq.fastest_gain_score",
    "probability": "cq.probability_score_1_to_10",
    "title": "o.title",
    "domain": "o.root_domain",
    "updated": "cq.updated_at",
}


def show_routed_operator_table(conn: sqlite3.Connection) -> None:
    view = _active_operator_view()
    sort_key = _active_operator_sort()

    st.markdown(
        f"""
        <div id="active-operator-table" class="operator-workbench">
          <div class="operator-workbench-title">ACTIVE TABLE - {html.escape(ROUTE_VIEWS[view]).upper()}</div>
          <div class="operator-routebar">
            <a class="retro-tool retro-action-link" target="_self" href="/?view=opportunities&sort=value#active-operator-table">Back To Main</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?view=opportunities#active-operator-table">Opportunities</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?view=claim_queue#active-operator-table">Claim Queue</a>
            <a class="retro-tool retro-action-link fastest-gains-link" target="_self" href="/?view=fastest&sort=fastest#active-operator-table">FASTEST GAINS</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?view=sources#active-operator-table">Sources</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?view=approvals&sort=value#active-operator-table">Approvals</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?view=execution&sort=updated#active-operator-table">Execution</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?view=ready&sort=value#active-operator-table">Ready</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?view=blocked&sort=readiness#active-operator-table">Blocked</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?view=history&sort=updated#active-operator-table">History</a>
            <a class="retro-tool retro-action-link easy-link" target="_self" href="/?page=easy">EASY</a>
            <a class="retro-tool retro-action-link ai-labor-link" target="_self" href="/?page=ai_labor">AI LABOR</a>
            <a class="retro-tool retro-action-link treasury-link" target="_self" href="/?page=treasury">TREASURY</a>
            <a class="retro-tool retro-action-link chaos-link" target="_self" href="/?page=chaos">CHAOS</a>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    focus_message = st.session_state.get("operator_focus_message")
    if focus_message:
        st.info(str(focus_message))
    if view == "approvals":
        st.caption(
            "Approval route is live: select a row to open the prepared packet, Vault/autofill preview, "
            "official link, and Approve / Later / More Info / Reject controls."
        )
        _show_approval_fast_path_bar(conn)
    elif view == "fastest":
        _show_fastest_gains_intro(conn)
    sort_cols = st.columns([1, 1, 4])
    selected_view = sort_cols[0].selectbox(
        "View",
        options=list(ROUTE_VIEWS.keys()),
        index=list(ROUTE_VIEWS.keys()).index(view),
        format_func=lambda key: ROUTE_VIEWS[key],
        key=f"operator_route_view_select_{view}_{sort_key}",
    )
    selected_sort = sort_cols[1].selectbox(
        "Sort",
        options=list(ROUTE_SORTS.keys()),
        index=list(ROUTE_SORTS.keys()).index(sort_key),
        format_func=lambda key: key.title(),
        key=f"operator_route_sort_select_{view}_{sort_key}",
    )
    if selected_view != view or selected_sort != sort_key:
        st.session_state["operator_active_view"] = selected_view
        st.session_state["operator_active_sort"] = selected_sort
        st.session_state["operator_focus_message"] = f"Showing {ROUTE_VIEWS[selected_view]} sorted by {selected_sort.title()}."
        try:
            st.query_params["view"] = selected_view
            st.query_params["sort"] = selected_sort
        except Exception:  # noqa: BLE001
            pass
        st.rerun()
    sort_cols[2].markdown(_sort_links(view), unsafe_allow_html=True)

    df = _operator_view_dataframe(conn, view, sort_key)
    if df.empty:
        st.write("No rows for this view yet.")
        return
    _show_selectable_operator_table(conn, df, view, sort_key)


def _fastest_gain_rows(conn: sqlite3.Connection, limit: int = 120) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            cq.execution_status,
            cq.input_status AS readiness,
            o.title,
            o.root_domain,
            cq.expected_value_usd,
            cq.probability_score_1_to_10,
            cq.fastest_gain_score,
            cq.time_to_gain_days,
            cq.estimated_completion_percent,
            cq.next_action,
            cq.human_input_needed,
            cq.official_link
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
          AND COALESCE(cq.fastest_gain_score, 0) > 0
        ORDER BY
            COALESCE(cq.fastest_gain_score, 0) DESC,
            COALESCE(cq.time_to_gain_days, 9999) ASC,
            COALESCE(cq.probability_score_1_to_10, 0) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _show_fastest_gains_intro(conn: sqlite3.Connection) -> None:
    rows = _fastest_gain_rows(conn)
    ready_now = sum(1 for row in rows if str(row.get("readiness") or "") == "ready_for_ai_work")
    final_approval = sum(1 for row in rows if str(row.get("readiness") or "") == "final_approval_required")
    needs_input = sum(
        1
        for row in rows
        if str(row.get("readiness") or "") in {"missing_shipping", "missing_payout", "needs_connect", "blocked"}
    )
    st.markdown(
        """
        <div class="operator-workbench fastest-gains-panel">
          <div class="operator-workbench-title fastest-gains-title">FASTEST GAINS</div>
          <div class="operator-console-note">
            Streamlined path: pick the simplest/quickest gains, approve the safe ones in bulk, and route anything
            needing shipping, payout, login, or final owner review into the Vault / Approval Queue.
          </div>
          <div class="operator-routebar">
            <a class="retro-tool retro-action-link fastest-gains-link" target="_self" href="/?operator_action=fastest_triage_all">
              APPROVE POSSIBLE + ROUTE REST
            </a>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    cols[0].metric("Quick Picks", len(rows))
    cols[1].metric("Ready For AI", ready_now)
    cols[2].metric("Final Approval", final_approval)
    cols[3].metric("Needs Input/Connect", needs_input)
    st.caption(
        "Select rows below. Bulk approval only runs AI-safe items; sensitive/legal/tax/identity/payment/login gates stay item-by-item."
    )
    st.caption(
        "This is the approve-all-style workflow: safe/prep work continues; sensitive or incomplete items are routed instead of silently skipped."
    )
    _show_recent_fastest_result_notice()


def _show_recent_fastest_result_notice() -> None:
    last_action = str(st.session_state.get("operator_last_action") or "")
    last_result = st.session_state.get("operator_last_result")
    if not last_action.startswith("operator_bulk_") or not isinstance(last_result, dict):
        return
    output = str(last_result.get("output") or "")
    applied = _extract_result_count(output, "Applied")
    skipped = _extract_result_count(output, "Skipped")
    routed = _extract_result_count(output, "Routed")
    if applied > 0 or routed > 0:
        st.success(f"Last bulk action completed: {applied} applied, {routed} routed, {skipped} skipped.")
    else:
        st.warning(
            f"Last bulk action ran, but applied 0 items and skipped {skipped}. "
            "Those selected rows need item-by-item owner approval or more direct safe-prep eligibility."
        )
    with st.expander("Last bulk action details", expanded=False):
        st.code(output[-5000:] or "No details recorded.", language="text")


def _extract_result_count(output: str, label: str) -> int:
    pattern = rf"(?m)^{re.escape(label)}:\s*(\d+)"
    match = re.search(pattern, output)
    return int(match.group(1)) if match else 0


def _show_selectable_operator_table(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    view: str,
    sort_key: str,
) -> None:
    select_key = f"operator_select_all_visible_{view}_{sort_key}"
    control_cols = st.columns([1.2, 1.1, 3.7])
    select_all_visible = control_cols[0].checkbox("Select all rows in this table", key=select_key)
    if control_cols[1].button("Clear selection", key=f"operator_clear_selection_{view}_{sort_key}", use_container_width=True):
        st.session_state[select_key] = False
        st.rerun()
    control_cols[2].caption(
        "The left checkbox column is for bulk workflow actions. Column-name sort links above still control table grouping/sorting."
    )

    editable = df.copy()
    if "select" in editable.columns:
        editable = editable.drop(columns=["select"])
    editable.insert(0, "select", bool(select_all_visible))
    edited = st.data_editor(
        editable,
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        disabled=[column for column in editable.columns if column != "select"],
        column_config={
            "select": st.column_config.CheckboxColumn("Select", help="Pick rows for bulk owner actions."),
        },
        key=f"operator_select_editor_{view}_{sort_key}_{int(select_all_visible)}",
    )
    selected_ids = _selected_bulk_approval_ids(edited)
    if selected_ids:
        _show_operator_selected_bulk_actions(conn, selected_ids, view)
    if len(selected_ids) == 1 and view != "sources":
        selected = df[df["id"].astype(str) == str(selected_ids[0])]
        if not selected.empty:
            _show_selected_operator_row(conn, selected.iloc[0].to_dict())
    elif len(selected_ids) == 1 and view == "sources":
        st.markdown("**Selected Source**")
        selected = df[df["id"].astype(str) == str(selected_ids[0])]
        if not selected.empty:
            show_dataframe(selected)


def _show_operator_selected_bulk_actions(conn: sqlite3.Connection, selected_ids: list[int], view: str) -> None:
    st.markdown("**Selected Bulk Workflow**")
    cols = st.columns([1, 1.4, 1.2, 1, 1, 1.2])
    cols[0].metric("Selected", len(selected_ids))
    if view == "sources":
        cols[1].caption("Source bulk actions stay in source controls for now.")
        return

    if cols[1].button("Approve Safe / Prep", key=f"operator_bulk_approve_{view}", use_container_width=True):
        result = _apply_operator_selected_action(conn, selected_ids, "approve_safe_or_prep")
        st.session_state["operator_last_result"] = result
        st.session_state["operator_last_action"] = "operator_bulk_approve_safe_or_prep"
        st.session_state["operator_focus_message"] = "Selected rows were processed through the safe approval/prep path."
        st.rerun()
    if cols[2].button("Approve Possible + Route Rest", key=f"operator_bulk_triage_{view}", use_container_width=True):
        result = _apply_operator_selected_action(conn, selected_ids, "approve_possible_route_rest")
        st.session_state["operator_last_result"] = result
        st.session_state["operator_last_action"] = "operator_bulk_approve_possible_route_rest"
        st.session_state["operator_focus_message"] = "Selected rows were triaged: safe work advanced and blocked work routed."
        st.rerun()
    if cols[3].button("Later Selected", key=f"operator_bulk_later_{view}", use_container_width=True):
        result = _apply_operator_selected_action(conn, selected_ids, "later")
        st.session_state["operator_last_result"] = result
        st.session_state["operator_last_action"] = "operator_bulk_later"
        st.session_state["operator_focus_message"] = "Selected rows moved to Later where allowed."
        st.rerun()
    if cols[4].button("More Info", key=f"operator_bulk_more_info_{view}", use_container_width=True):
        result = _apply_operator_selected_action(conn, selected_ids, "more_info")
        st.session_state["operator_last_result"] = result
        st.session_state["operator_last_action"] = "operator_bulk_more_info"
        st.session_state["operator_focus_message"] = "Selected rows were routed for more info / owner review."
        st.rerun()
    confirm_reject = cols[5].checkbox("Enable reject", key=f"operator_bulk_reject_confirm_{view}")
    if cols[5].button("Reject Selected", key=f"operator_bulk_reject_{view}", use_container_width=True, disabled=not confirm_reject):
        result = _apply_operator_selected_action(conn, selected_ids, "reject")
        st.session_state["operator_last_result"] = result
        st.session_state["operator_last_action"] = "operator_bulk_reject"
        st.session_state["operator_focus_message"] = "Selected rows were rejected where allowed."
        st.rerun()


def _apply_operator_selected_action(
    conn: sqlite3.Connection,
    selected_ids: list[int],
    action: str,
) -> dict[str, object]:
    lines: list[str] = []
    applied = 0
    routed = 0
    skipped = 0
    for claim_id in selected_ids:
        detail = load_claim_detail(conn, int(claim_id))
        if not detail:
            skipped += 1
            lines.append(f"SKIP #{claim_id}: row not found.")
            continue
        detail_dict = dict(detail)
        title = str(detail_dict.get("title") or "Untitled")
        if _previous_browser_execution_submitted(detail_dict):
            skipped += 1
            lines.append(f"SKIP #{claim_id}: {title} already has a recorded external browser submit.")
            continue
        action_type = final_action_type(detail_dict)
        item = build_final_approval_queue([detail_dict])[0] if action_type else None
        if action == "approve_safe_or_prep":
            if item:
                bulk_safe = bool(item.safe_to_mark_submitted and item.final_action_type == "final_submit")
                if not bulk_safe:
                    skipped += 1
                    lines.append(f"SKIP #{claim_id}: {title} needs item-by-item final approval ({item.final_action_type}).")
                    continue
                note = apply_final_approval_action(conn, claim_id, item.final_action_type, "Approve Final Step")
                lines.append(f"APPROVE SAFE #{claim_id}: {title} -> {note}")
            else:
                apply_claim_status(conn, claim_id, "Approved")
                lines.append(f"APPROVE PREP #{claim_id}: {title} -> AI work/prep continued.")
            applied += 1
        elif action == "approve_possible_route_rest":
            if item:
                bulk_safe = bool(item.safe_to_mark_submitted and item.final_action_type == "final_submit")
                if bulk_safe:
                    note = apply_final_approval_action(conn, claim_id, item.final_action_type, "Approve Final Step")
                    applied += 1
                    lines.append(f"APPROVE SAFE #{claim_id}: {title} -> {note}")
                else:
                    note = _route_owner_gated_item(conn, claim_id, item.final_action_type, item.why_approval_required)
                    routed += 1
                    lines.append(f"ROUTE #{claim_id}: {title} -> {note}")
            elif _has_missing_or_connect_blocker(detail_dict):
                note = _route_missing_or_connect_item(conn, claim_id, detail_dict)
                routed += 1
                lines.append(f"ROUTE #{claim_id}: {title} -> {note}")
            else:
                apply_claim_status(conn, claim_id, "Approved")
                applied += 1
                lines.append(f"APPROVE PREP #{claim_id}: {title} -> AI work/prep continued.")
        elif action == "later":
            if item:
                note = apply_final_approval_action(conn, claim_id, item.final_action_type, "Later")
            else:
                apply_claim_status(conn, claim_id, "Later")
                note = "Moved to Later."
            applied += 1
            lines.append(f"LATER #{claim_id}: {title} -> {note}")
        elif action == "more_info":
            if item:
                note = apply_final_approval_action(conn, claim_id, item.final_action_type, "Needs More Info")
            else:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    """
                    UPDATE claim_queue
                    SET execution_status='Paused Awaiting Input',
                        human_input_needed='Owner requested more information before approval.',
                        next_action='AI should gather more information and rebuild the approval packet.',
                        updated_at=?
                    WHERE id=?
                    """,
                    (now, claim_id),
                )
                conn.commit()
                note = "Paused for more information."
            applied += 1
            lines.append(f"MORE INFO #{claim_id}: {title} -> {note}")
        elif action == "reject":
            if item:
                note = apply_final_approval_action(conn, claim_id, item.final_action_type, "Reject")
            else:
                apply_claim_status(conn, claim_id, "Rejected")
                note = "Rejected."
            applied += 1
            lines.append(f"REJECT #{claim_id}: {title} -> {note}")
    if not lines:
        lines.append("No selected rows were eligible for this action.")
    lines.append("")
    lines.append(f"Applied: {applied}")
    lines.append(f"Routed: {routed}")
    lines.append(f"Skipped: {skipped}")
    lines.append("Approve Possible + Route Rest advances safe work and routes owner-only gates without bypassing approval.")
    return {"label": f"Selected {action}", "returncode": 0, "output": "\n".join(lines)}


def _has_missing_or_connect_blocker(detail: dict[str, object]) -> bool:
    text = " ".join(
        str(detail.get(key) or "")
        for key in ["input_status", "missing_inputs", "human_input_needed", "owner_input_required", "next_action"]
    ).lower()
    return any(term in text for term in ["missing", "needs_connect", "connect", "shipping", "payout", "login"])


def _route_owner_gated_item(
    conn: sqlite3.Connection,
    claim_queue_id: int,
    final_action: str,
    why: str,
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    reason = str(why or final_action or "final owner approval required")
    conn.execute(
        """
        UPDATE claim_queue
        SET status='Ready to Accept',
            execution_status='Ready To Accept',
            input_status='final_approval_required',
            human_input_needed=?,
            next_action=?,
            updated_at=?
        WHERE id=?
        """,
        (
            f"Owner final approval required: {final_action}.",
            f"Review approval packet: {reason}",
            now,
            claim_queue_id,
        ),
    )
    conn.commit()
    SQLiteStore(DB_PATH).normalize_required_inputs()
    return f"routed to Final Approval Queue ({final_action})."


def _route_missing_or_connect_item(
    conn: sqlite3.Connection,
    claim_queue_id: int,
    detail: dict[str, object],
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    input_status = str(detail.get("input_status") or "")
    missing = str(detail.get("missing_inputs") or detail.get("human_input_needed") or detail.get("owner_input_required") or "")
    if "connect" in input_status or "login" in missing.lower() or "connect" in missing.lower():
        status = "Connect Needed"
        execution_status = "Paused Awaiting Input"
        human = missing or "Owner account connection/login approval is required."
        next_action = "Open Vault / connectors, approve the account connection, then resume AI prep."
    else:
        status = str(detail.get("status") or "Needs Approval")
        execution_status = "Paused Awaiting Input"
        human = missing or "Reusable owner input is required."
        next_action = "Resolve missing input in the Vault, then resume AI prep."
    conn.execute(
        """
        UPDATE claim_queue
        SET status=?,
            execution_status=?,
            human_input_needed=?,
            next_action=?,
            updated_at=?
        WHERE id=?
        """,
        (status, execution_status, human, next_action, now, claim_queue_id),
    )
    conn.commit()
    SQLiteStore(DB_PATH).normalize_required_inputs()
    return next_action


def _show_approval_fast_path_bar(conn: sqlite3.Connection) -> None:
    items = build_final_approval_queue(rows_for_final_approval(conn, limit=1000))
    bulk_safe_items = [
        item for item in items if item.safe_to_mark_submitted and item.final_action_type == "final_submit"
    ]
    owner_only_count = len(items) - len(bulk_safe_items)
    st.markdown(
        """
        <div class="operator-workbench approval-gate">
          <div class="operator-workbench-title">FAST PATH - ACCEPT SAFE READY ITEMS</div>
          <div class="operator-console-note">
            This approves only low-risk final-submit packets and moves them to Submitted/processing.
            Login, wallet, payment, purchase, legal, tax, and identity gates stay owner-only.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cols = st.columns([1, 1, 1.2, 1.4])
    cols[0].metric("Safe To Accept", len(bulk_safe_items))
    cols[1].metric("Owner-Only Gates", owner_only_count)
    cols[2].link_button(
        "Review Packets",
        "/?view=approvals&sort=value#active-operator-table",
        use_container_width=True,
    )
    if bulk_safe_items:
        cols[3].markdown(
            '<a class="retro-tool retro-action-link" target="_self" '
            'href="/?operator_action=fast_path_accept_all_safe">ACCEPT ALL LOW-RISK</a>',
            unsafe_allow_html=True,
        )
    else:
        cols[3].button("ACCEPT ALL LOW-RISK", use_container_width=True, disabled=True)


def _active_operator_view() -> str:
    query_view = _query_param("view", "")
    if query_view in ROUTE_VIEWS:
        st.session_state["operator_active_view"] = query_view
        st.session_state["operator_focus_message"] = f"Showing {ROUTE_VIEWS[query_view]}."
    view = str(st.session_state.get("operator_active_view") or "opportunities")
    return view if view in ROUTE_VIEWS else "opportunities"


def _active_operator_sort() -> str:
    query_sort = _query_param("sort", "")
    if query_sort in ROUTE_SORTS:
        st.session_state["operator_active_sort"] = query_sort
    sort_key = str(st.session_state.get("operator_active_sort") or "value")
    return sort_key if sort_key in ROUTE_SORTS else "value"


def _operator_view_dataframe(conn: sqlite3.Connection, view: str, sort_key: str) -> pd.DataFrame:
    order_col = ROUTE_SORTS.get(sort_key, "expected_value_usd")
    direction = "ASC" if sort_key in {"id", "title", "domain", "status", "readiness"} else "DESC"
    where = "cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')"
    if view == "approvals":
        where += " AND (cq.status IN ('Needs Approval', 'Connect Needed', 'Ready to Accept') OR cq.execution_status='Ready To Accept' OR cq.input_status='final_approval_required')"
    elif view == "execution":
        where += " AND (cq.execution_status IN ('Execution Queue', 'AI Working', 'Processing') OR cq.status IN ('Submitted', 'Processing'))"
    elif view == "fastest":
        where += """
            AND COALESCE(cq.fastest_gain_score, 0) > 0
            AND (
                cq.input_status IN ('ready_for_ai_work', 'final_approval_required', 'missing_shipping', 'missing_payout', 'needs_connect')
                OR cq.execution_status IN ('Ready To Accept', 'Execution Queue', 'AI Working', 'Processing')
                OR cq.status IN ('Needs Approval', 'Approved', 'Ready to Accept', 'Submitted')
            )
        """
    elif view == "ready":
        where += " AND (cq.execution_status='Ready To Accept' OR cq.status='Ready to Accept')"
    elif view == "blocked":
        where += " AND (cq.input_status IN ('missing_shipping', 'missing_payout', 'needs_connect', 'blocked') OR cq.execution_status='Paused Awaiting Input')"
    elif view == "history":
        where = "cq.status IN ('Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid', 'Submitted')"
    if view == "sources":
        return pd.read_sql_query(
            f"""
            SELECT
                id, status, title, url, domain, root_domain,
                source_score_1_to_10, expected_gain_potential_1_to_10,
                risk_level, login_required, payment_required, updated_at
            FROM source_candidates
            ORDER BY updated_at DESC
            LIMIT 300
            """,
            conn,
        )
    return pd.read_sql_query(
        f"""
        SELECT
            cq.id,
            cq.status,
            cq.execution_status,
            cq.input_status AS readiness,
            o.title,
            o.root_domain,
            cq.expected_value_usd,
            cq.probability_score_1_to_10,
            cq.fastest_gain_score,
            cq.time_to_gain_days,
            cq.estimated_completion_percent,
            cq.destination_type,
            cq.asset_type,
            CASE
                WHEN cq.status='Connect Needed' OR cq.input_status='needs_connect'
                    THEN 'Select row -> connector / login approval'
                WHEN cq.execution_status='Ready To Accept' OR cq.status='Ready to Accept'
                    THEN 'Select row -> final packet approval'
                WHEN cq.input_status='final_approval_required'
                    THEN 'Select row -> owner final decision'
                WHEN cq.execution_status IN ('Execution Queue', 'AI Working', 'Processing')
                    THEN 'Select row -> work / tracking details'
                ELSE 'Select row -> inspect next action'
            END AS action,
            cq.next_action,
            cq.human_input_needed,
            cq.official_link,
            cq.updated_at
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE {where}
        ORDER BY {order_col} {direction}, cq.fastest_gain_score DESC
        LIMIT 300
        """,
        conn,
    )


def _show_selected_operator_row(conn: sqlite3.Connection, selected: dict[str, object]) -> None:
    row_id = selected.get("id")
    st.markdown("**Selected Row**")
    cols = st.columns([1, 2, 2, 2])
    cols[0].metric("ID", row_id)
    cols[1].write(f"Status: {selected.get('status', '')}")
    cols[2].write(f"Readiness: {selected.get('readiness', selected.get('input_status', ''))}")
    if selected.get("official_link"):
        cols[3].link_button("Open Official Link", str(selected["official_link"]), use_container_width=True)
    if row_id and "readiness" in selected:
        detail = load_claim_detail(conn, int(row_id))
        if detail:
            _show_selected_row_approval_controls(dict(detail))
            with st.expander("Prepared Packet / Autofill Preview", expanded=True):
                show_vault_data_preview(dict(detail))
                show_final_approval_packet(dict(detail))


def _show_selected_row_approval_controls(detail: dict[str, object]) -> None:
    action_type = final_action_type(detail)
    if not action_type:
        st.caption("Selected item has no final approval gate detected yet. AI can continue prep or dependency resolution.")
        return
    items = build_final_approval_queue([detail])
    if not items:
        return
    st.markdown("**Selected Item Owner Decision**")
    st.markdown(_approval_card_html(items[0]), unsafe_allow_html=True)


def _sort_links(view: str) -> str:
    links = [
        f'<a class="retro-tool retro-action-link" target="_self" href="/?view={view}&sort={key}#active-operator-table">{label}</a>'
        for key, label in [
            ("id", "ID"),
            ("status", "Status"),
            ("readiness", "Readiness"),
            ("fastest", "Fastest"),
            ("value", "Value"),
            ("probability", "Probability"),
            ("title", "Title"),
            ("domain", "Domain"),
            ("updated", "Updated"),
        ]
    ]
    return '<div class="operator-routebar">' + "".join(links) + "</div>"


def _query_param(name: str, default: str = "") -> str:
    try:
        return str(st.query_params.get(name) or default)
    except Exception:  # noqa: BLE001
        return default


def _project_python_executable() -> str:
    venv_python = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _run_broad_fetch_scan() -> dict[str, object]:
    command = [
        _project_python_executable(),
        str(ROOT_DIR / "src" / "main.py"),
        "--fetch-only",
        "--limit",
        "400",
        "--max-candidates-per-source",
        "20",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"returncode": 1, "output": f"Broad fetch scan failed: {exc}"}
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    return {"returncode": completed.returncode, "output": output}


def _run_autonomy_boost() -> dict[str, object]:
    fetch_result = _run_broad_fetch_scan()
    output_parts = [str(fetch_result.get("output") or "")]
    if fetch_result["returncode"] != 0:
        return {"returncode": fetch_result["returncode"], "output": "\n".join(output_parts)}
    try:
        with connect() as conn:
            summary = run_autonomous_queue_pass(
                conn,
                ROOT_DIR,
                {"enabled": True, "mode": "Open-To-Everything", "execution_mode": "Live Assist"},
            )
            conn.commit()
        output_parts.append("Live Assist local prep summary:")
        output_parts.append(json.dumps(summary.to_dict(), ensure_ascii=True, indent=2))
        return {"returncode": 0, "output": "\n".join(output_parts)}
    except Exception as exc:  # noqa: BLE001
        output_parts.append(f"Live Assist local prep failed: {exc}")
        return {"returncode": 1, "output": "\n".join(output_parts)}


def _run_magic_money_scout() -> dict[str, object]:
    try:
        store = SQLiteStore(DB_PATH)
        store.init_db()
        summary = run_magic_money_scout(store, promote_to_queue=True)
        store.refresh_exploration_queue()
        store.normalize_required_inputs()
        with connect() as scout_conn:
            completion = run_completion_engine_pass(
                scout_conn,
                load_effective_user_context(),
                mode="Live Assist",
                commit=True,
            )
            autonomy = run_autonomous_queue_pass(
                scout_conn,
                ROOT_DIR,
                {"enabled": True, "mode": "Open-To-Everything", "execution_mode": "Live Assist"},
            )
            scout_conn.commit()
        return {
            "returncode": 0,
            "output": json.dumps(
                {
                    "magic_money_scout": summary.to_dict(),
                    "completion_engine": completion.to_dict(),
                    "autonomous_worker": autonomy.to_dict(),
                    "external_submission": "not_performed",
                    "safety": "No buys, sells, payments, legal/tax/identity actions, wallet signing, or final external submits were performed.",
                },
                ensure_ascii=True,
                indent=2,
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"returncode": 1, "output": f"MAGIC FAIRYTALE MONIES scout failed: {exc}"}


def _run_autonomy_pump() -> dict[str, object]:
    try:
        summary = run_autonomy_pump(
            root_dir=ROOT_DIR,
            database_path=DB_PATH,
            control={"enabled": True, "mode": "Open-To-Everything", "execution_mode": "Live Assist"},
            inspect_limit=16,
        )
        return {
            "returncode": 0,
            "output": json.dumps(
                {
                    "autonomy_pump": summary.to_dict(),
                    "external_submission": "not_performed",
                    "safety": "Safe local prep, queue updates, and official-form inspection only.",
                },
                ensure_ascii=True,
                indent=2,
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"returncode": 1, "output": f"Autonomy pump failed: {exc}"}


def _run_safe_automation_cycle() -> dict[str, object]:
    output_parts: list[str] = []
    fetch_result = _run_broad_fetch_scan()
    output_parts.append(str(fetch_result.get("output") or ""))
    if fetch_result.get("returncode") != 0:
        return {"returncode": fetch_result.get("returncode", 1), "output": "\n".join(output_parts)}

    try:
        store = SQLiteStore(DB_PATH)
        store.init_db()
        store.normalize_required_inputs()
        store.normalize_execution_state()
        with connect() as cycle_conn:
            completion = run_completion_engine_pass(
                cycle_conn,
                load_effective_user_context(),
                mode="Live Assist",
                commit=True,
            )
            autonomy = run_autonomous_queue_pass(
                cycle_conn,
                ROOT_DIR,
                {"enabled": True, "mode": "Open-To-Everything", "execution_mode": "Live Assist"},
            )
            cycle_conn.commit()
        output_parts.append("Completion Engine summary:")
        output_parts.append(json.dumps(completion.to_dict(), ensure_ascii=True, indent=2))
        output_parts.append("Autonomous Worker summary:")
        output_parts.append(json.dumps(autonomy.to_dict(), ensure_ascii=True, indent=2))
        output_parts.append("No external forms were submitted. Final approval gates remain active.")
        return {"returncode": 0, "output": "\n".join(output_parts)}
    except Exception as exc:  # noqa: BLE001
        output_parts.append(f"Safe automation cycle failed: {exc}")
        return {"returncode": 1, "output": "\n".join(output_parts)}


def _run_safe_browser_execution_batch(
    conn: sqlite3.Connection,
    limit: int = 12,
    execution_mode_override: str | None = None,
    context_override: dict[str, object] | None = None,
    batch_deadline_seconds: int = 0,
) -> dict[str, object]:
    control = load_autorun_control()
    execution_mode = str(execution_mode_override or control.get("execution_mode") or "Dry Run")
    if execution_mode != "Live Submit With Final Approval":
        return {
            "returncode": 0,
            "output": json.dumps(
                {
                    "mode": execution_mode,
                    "submitted_external": 0,
                    "blocked": 0,
                    "skipped": "Execution mode is not Live Submit With Final Approval.",
                    "safety": "No external forms were submitted.",
                },
                ensure_ascii=True,
                indent=2,
            ),
        }

    context = context_override or load_effective_user_context()
    consent_store = SubmissionConsentStore.for_root(ROOT_DIR)
    consent_payload = consent_store.load()
    consent_ids = [
        int(claim_id)
        for claim_id, consent in (consent_payload.get("items") or {}).items()
        if isinstance(consent, dict) and consent.get("allowed") and str(claim_id).isdigit()
    ]
    seen_ids: set[int] = set()
    rows: list[dict[str, object]] = []
    scan_limit = max(limit * 80, 1000)
    source_rows = rows_for_browser_execution(conn, limit=scan_limit) + rows_for_browser_execution_candidates(conn, limit=scan_limit)
    if consent_ids:
        placeholders = ",".join("?" for _ in consent_ids)
        source_rows.extend(
            [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT cq.*, o.title, o.url
                    FROM claim_queue cq
                    JOIN opportunities o ON o.id = cq.opportunity_id
                    WHERE cq.id IN ({placeholders})
                    """,
                    consent_ids,
                ).fetchall()
            ]
        )
    source_rows = sorted(source_rows, key=_instant_gain_priority)
    skipped_not_direct = 0
    for row in source_rows:
        row_id = int(row["id"])
        if row_id in seen_ids:
            continue
        if not _looks_low_risk_live_candidate(dict(row)):
            continue
        if not _is_claimable_live_submit_target(dict(row)):
            skipped_not_direct += 1
            continue
        if _previous_browser_execution_submitted(dict(row)):
            continue
        if _previous_browser_execution_blocked(dict(row)):
            continue
        seen_ids.add(row_id)
        rows.append(row)
    attempted = 0
    submitted = 0
    blocked = 0
    skipped_no_consent = 0
    deadline_enabled = batch_deadline_seconds > 0
    stopped_for_timebox = False
    started_at = time.monotonic()
    details: list[dict[str, object]] = []

    for row in rows:
        if deadline_enabled and time.monotonic() - started_at >= batch_deadline_seconds:
            stopped_for_timebox = True
            break
        claim_queue_id = int(row["id"])
        consent = consent_store.consent_for(claim_queue_id)
        if not consent.get("allowed"):
            skipped_no_consent += 1
            continue
        plan = build_browser_execution_plan(dict(row), context, execution_mode)
        connector_profile = profile_for_url(ROOT_DIR, str(row.get("official_link") or row.get("url") or ""))
        result = execute_safe_official_form(
            plan,
            context,
            consent,
            submit_external=True,
            timeout_seconds=90,
            browser_profile_dir=connector_profile,
        )
        attempted += 1
        submitted += 1 if result.submitted else 0
        blocked += 0 if result.submitted else 1
        _apply_browser_execution_result(conn, claim_queue_id, result)
        record_browser_execution_run(ROOT_DIR, plan, result.status, result.note)
        details.append(
            {
                "claim_queue_id": claim_queue_id,
                "title": row.get("title"),
                "status": result.status,
                "submitted": result.submitted,
                "note": result.note,
                "next_action": result.next_action,
                "stop_flags": result.stop_flags,
                "missing_fields": result.missing_fields,
                "connector_profile": str(connector_profile) if connector_profile else "",
            }
        )
        if attempted >= limit:
            break

    return {
        "returncode": 0,
        "output": json.dumps(
            {
                "mode": execution_mode,
                "eligible_processing_rows": len(rows),
                "attempted": attempted,
                "submitted_external": submitted,
                "blocked_or_paused": blocked,
                "skipped_no_consent": skipped_no_consent,
                "skipped_not_direct_claim_path": skipped_not_direct,
                "timebox_seconds": batch_deadline_seconds if deadline_enabled else "disabled",
                "stopped_for_timebox": stopped_for_timebox,
                "details": details,
                "strategy": "Direct official claim/signup/sample/reward paths first; discovery/article pages stay queued for extraction, not fake progress.",
                "safety": "Executed only consented low-risk browser forms; sensitive gates remain blocked.",
            },
            ensure_ascii=True,
            indent=2,
        ),
    }


def _previous_browser_execution_blocked(row: dict[str, object]) -> bool:
    browser_payload = _browser_execution_payload(row)
    if not browser_payload:
        return False
    status = str(browser_payload.get("status") or "")
    retryable = {
        "blocked_network_error",
        "blocked_browser_execution_error",
        "blocked_no_mapped_fields",
        "blocked_required_unmapped",
        "blocked_no_form",
    }
    return status.startswith("blocked_") and status not in retryable


def _previous_browser_execution_submitted(row: dict[str, object]) -> bool:
    browser_payload = _browser_execution_payload(row)
    if not browser_payload:
        return False
    return str(browser_payload.get("status") or "") in {"submitted_external", "submitted_external_browser"}


def _browser_execution_payload(row: dict[str, object]) -> dict[str, object]:
    try:
        payload = json.loads(str(row.get("action_engine_json") or "{}"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    browser_payload = payload.get("browser_execution")
    if not isinstance(browser_payload, dict):
        return {}
    return browser_payload


def _is_claimable_live_submit_target(row: dict[str, object]) -> bool:
    """Keep real browser submit attempts focused on pages that look like an actual asset action."""
    primary_blob = _primary_signal_blob(row)
    blob = _row_blob(row)
    url = str(row.get("official_link") or row.get("url") or "").lower()
    target_blob = f"{primary_blob} {url}"
    if str(row.get("input_status") or "") != "ready_for_ai_work":
        return False
    if str(row.get("sensitive_inputs") or "").strip():
        return False
    if _has_any(primary_blob, SENSITIVE_APPROVAL_TERMS):
        return False
    if _has_any(primary_blob, SLOW_OR_PAPER_TERMS) or _has_any(primary_blob, CREDIT_ONLY_TERMS):
        return False
    if _has_any(target_blob, DISCOVERY_ONLY_LIVE_SUBMIT_TERMS):
        return False
    if _has_any(url, LIVE_SUBMIT_TRUSTED_GAIN_URL_TERMS):
        return True
    if _has_any(target_blob, LIVE_SUBMIT_DIRECT_ACTION_TERMS):
        return True
    return _has_any(blob, LIVE_SUBMIT_DIRECT_ACTION_TERMS) and not _has_any(target_blob, NOISE_OR_INFO_TERMS)


def _looks_low_risk_live_candidate(row: dict[str, object]) -> bool:
    blob = " ".join(
        str(row.get(key) or "")
        for key in [
            "title",
            "gain_type",
            "asset_type",
            "source_name",
            "claim_instructions",
            "what_this_gain_is",
            "why_it_may_produce_real_asset_value",
            "next_action",
        ]
    ).lower()
    blocked_terms = [
        "settlement",
        "class action",
        "lawsuit",
        "legal",
        "unclaimed",
        "data breach",
        "tax",
        "ssn",
        "social security",
        "identity",
        "kyc",
        "credit card",
        "purchase",
        "refund policy",
        "reimbursement",
    ]
    if any(term in blob for term in blocked_terms):
        return False
    low_risk_terms = [
        "sample",
        "freebie",
        "product test",
        "product testing",
        "tester",
        "survey",
        "paid study",
        "research",
        "user testing",
        "usability",
        "beta",
        "reward",
        "gift card",
        "cash rewards",
    ]
    return any(term in blob for term in low_risk_terms)


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return 0


def require_owner_access() -> bool:
    configured_account_lookup = user_lookup(configured_users())
    if configured_account_lookup:
        if st.session_state.get("owner_access_granted") and st.session_state.get("owner_access_user"):
            _show_access_identity()
            return True

        st.markdown("## quantumgains access")
        st.caption("Private hosted access. This does not store plaintext passwords or bypass platform logins.")
        username = st.text_input("Username", key="quantumgains_access_username")
        password = st.text_input("Password", type="password", key="quantumgains_access_password")
        if st.button("Sign in", use_container_width=True):
            user = configured_account_lookup.get(str(username or "").strip().lower())
            if user and verify_password(str(password or ""), user.password_hash):
                st.session_state["owner_access_granted"] = True
                st.session_state["owner_access_user"] = user.username
                st.session_state["owner_access_role"] = user.role
                st.rerun()
            else:
                st.error("Access denied.")
        st.stop()
        return False

    expected_pin = _configured_access_pin()
    expected_pin_hash = _configured_access_pin_hash()
    if not expected_pin and not expected_pin_hash:
        return True
    if st.session_state.get("owner_access_granted"):
        _show_access_identity()
        return True

    st.markdown("## quantumgains owner access")
    st.caption("Owner-only gate for hosted deployments. This does not store passwords or bypass platform logins.")
    entered = st.text_input("Access PIN", type="password", key="quantumgains_access_pin_input")
    if st.button("Unlock", use_container_width=True):
        if _pin_matches(str(entered or ""), expected_pin, expected_pin_hash):
            st.session_state["owner_access_granted"] = True
            st.session_state["owner_access_user"] = "owner"
            st.session_state["owner_access_role"] = "owner"
            st.rerun()
        else:
            st.error("Access denied.")
    st.stop()
    return False


def _configured_access_pin() -> str:
    for key in ACCESS_PIN_ENV_KEYS:
        value = os.getenv(key)
        if value:
            return str(value)
    try:
        value = st.secrets.get("QUANTUMGAINS_ACCESS_PIN", "")
    except Exception:  # noqa: BLE001
        value = ""
    return str(value or "")


def _configured_access_pin_hash() -> str:
    for key in ACCESS_PIN_HASH_ENV_KEYS:
        value = os.getenv(key)
        if value:
            return str(value)
    try:
        value = st.secrets.get("QUANTUMGAINS_ACCESS_PIN_HASH", "")
    except Exception:  # noqa: BLE001
        value = ""
    return str(value or "")


def _pin_matches(entered: str, expected_pin: str, expected_pin_hash: str) -> bool:
    if expected_pin_hash and verify_password(entered, expected_pin_hash):
        return True
    if expected_pin:
        return hmac.compare_digest(entered, expected_pin)
    return False


def _show_access_identity() -> None:
    user = str(st.session_state.get("owner_access_user") or "owner")
    role = str(st.session_state.get("owner_access_role") or "owner")
    with st.sidebar:
        st.caption(f"Signed in: {user} ({role})")
        if st.button("Sign out", key="quantumgains_sign_out"):
            for key in [
                "owner_access_granted",
                "owner_access_user",
                "owner_access_role",
                "quantumgains_access_password",
                "quantumgains_access_pin_input",
            ]:
                st.session_state.pop(key, None)
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="quantumgains", layout="wide")
    inject_retro_command_os_style()
    require_owner_access()
    process_dream_action()
    if _is_chaos_route():
        show_chaos_mode_route()
        return
    if _is_connectors_route():
        show_live_connectors_route()
        return
    if _is_treasury_route():
        show_entity_treasury_route()
        return
    if _is_ai_labor_route():
        show_ai_labor_engine_route()
        return
    if _is_easy_route():
        show_easy_asset_acquisition_route()
        return
    if _is_vault_route():
        show_standalone_vault_route()
        return

    if not DB_PATH.exists():
        st.title("quantumgains")
        st.caption("Self-Expanding Acquisition Engine")
        st.info(f"No database found at {DB_PATH}. Run `python src/main.py` first.")
        return

    store = SQLiteStore(DB_PATH)
    store.init_db()
    store.normalize_required_inputs()
    store.normalize_execution_state()

    with connect() as conn:
        process_approval_action(conn)
        process_operator_action(conn)
        autorun_control = load_autorun_control()
        autonomy_summary = run_autonomous_queue_pass(conn, ROOT_DIR, autorun_control)
        completion_summary = run_completion_engine_pass(
            conn,
            load_effective_user_context(),
            mode=str(autorun_control.get("execution_mode") or "Dry Run"),
            commit=bool(autorun_control.get("enabled"))
            and str(autorun_control.get("execution_mode") or "Dry Run") != "Dry Run",
        )
        conn.commit()
        route_view = _query_param("view", "")
        session_view = str(st.session_state.get("operator_active_view") or "")
        routed_view_requested = (
            route_view in ROUTE_VIEWS
            or (session_view in ROUTE_VIEWS and session_view != "opportunities")
        )
        if routed_view_requested:
            show_routed_operator_table(conn)
            show_top_dashboard_metrics(conn)
            show_operator_command_center(conn, autonomy_summary, completion_summary)
        else:
            show_top_dashboard_metrics(conn)
            show_operator_command_center(conn, autonomy_summary, completion_summary)
            show_routed_operator_table(conn)

        claim_status_control(conn)
        source_status_control(conn)

        st.markdown('<div id="gain-opportunities"></div>', unsafe_allow_html=True)
        st.markdown("**Gain Opportunities**")
        show_opportunities(conn)

        show_autorun_status_strip(conn)
        show_autonomous_work_summary(autonomy_summary)
        show_broad_gain_sweep_control(conn)
        show_completion_engine_control(conn, completion_summary)
        show_retro_adapter_contract()
        show_magic_fairytale_monies(conn)
        show_make_dreams_reality()

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
                "Browser Execution",
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
            show_ready_to_accept_packets(conn)

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
            show_browser_execution_queue(conn)

        with tabs[27]:
            show_user_context(conn)

        with tabs[28]:
            show_input_statuses(conn, ["missing_shipping", "missing_payout", "needs_connect", "blocked"], limit=200)

        with tabs[29]:
            show_input_statuses(conn, ["ready_for_ai_work"], limit=200)

        with tabs[30]:
            show_input_statuses(conn, ["final_approval_required"], limit=200)

        show_owner_setup_progress_panel(conn, include_status=False)
        show_top_level_user_action_center(conn)

        if st.session_state.get("show_vault") or st.session_state.get("user_profile_vault_open"):
            show_user_profile_autofill_vault(conn)
        show_global_page_links("dashboard")


def show_magic_fairytale_monies(conn: sqlite3.Connection) -> None:
    lane_rows = magic_money_lane_rows()
    lane_count = len(lane_rows)
    queued_magic = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE o.source_type='autonomous_gain_lane'
           OR o.tags LIKE '%magic-fairytale-monies%'
           OR o.source_name='MAGIC FAIRYTALE MONIES!'
        """
    ).fetchone()["n"]
    ready_magic = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE (o.source_type='autonomous_gain_lane'
           OR o.tags LIKE '%magic-fairytale-monies%'
           OR o.source_name='MAGIC FAIRYTALE MONIES!')
          AND cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
        """
    ).fetchone()["n"]
    high_risk_watch = sum(1 for row in lane_rows if row["risk"] == "high")

    st.markdown(
        f"""
        <div id="magic-fairytale-monies" class="operator-workbench magic-money-workbench">
          <div class="operator-workbench-title">MAGIC FAIRYTALE MONIES!</div>
          <div class="operator-console-note">
            Broad lawful gain lanes: refunds, settlements, samples, paid research, developer credits, crypto rewards,
            airdrop/quest watch, bounties, and high-risk watch/simulation only. AI scouts and preps; owner approval gates stay hard.
          </div>
          <div class="magic-money-grid">
            <div class="retro-card"><div class="retro-card-label">LANES</div><div class="retro-card-value">{lane_count}</div><div class="retro-card-sub">autonomy channels</div></div>
            <div class="retro-card"><div class="retro-card-label">QUEUED</div><div class="retro-card-value">{int(queued_magic)}</div><div class="retro-card-sub">existing pipeline rows</div></div>
            <div class="retro-card"><div class="retro-card-label">ACTIVE</div><div class="retro-card-value">{int(ready_magic)}</div><div class="retro-card-sub">not terminal</div></div>
            <div class="retro-card"><div class="retro-card-label">WATCH ONLY</div><div class="retro-card-value">{high_risk_watch}</div><div class="retro-card-sub">no auto trading</div></div>
          </div>
          <div class="retro-toolbar" style="margin:8px 0 0 0;">
            <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=magic_money_scout">Run Magic Scout</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=autonomy_pump">Autonomy Pump</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=safe_auto_cycle">Safe Auto Cycle</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?view=ready&sort=value">Ready Accepts</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?view=approvals&sort=value#active-operator-table">Approval Gates</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?page=vault">Vault Unlocks</a>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    lanes_df = pd.DataFrame(lane_rows)
    show_dataframe(lanes_df)
    st.caption(
        "This catalog seeds the existing source discovery, claim queue, dependency, autofill, approval, and tracking flow. "
        "High-risk crypto lanes are research/simulation only; wallet signing, purchases, swaps, and trading remain final-approval/manual gates."
    )


def show_make_dreams_reality() -> None:
    assets = _load_dream_assets()
    st.markdown(
        """
        <div id="dreams-reality" class="operator-workbench dreams-workbench">
          <div class="operator-workbench-title">MAKE YOUR DREAMS A REALITY</div>
          <div class="dreams-note">
            Drop domains, NFTs, coins, stocks, listings, products, handles, repos, or weird little value fragments here.
            DREAM! turns them into a utility / saleability / value watch list for future AI work.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    raw_assets = st.text_area(
        "Digital assets",
        placeholder="quantumbusinessstrategies.com\nMy NFT collection URL\nSOL coin ticker or wallet-public asset note\neBay listing URL\nGitHub repo / app / product link",
        height=120,
        label_visibility="collapsed",
        key="dream_asset_input",
    )
    submitted = st.button("DREAM!", use_container_width=True, key="dream_asset_submit")
    if submitted:
        new_assets = [_assess_dream_asset(line) for line in _split_dream_inputs(raw_assets)]
        existing_keys = {asset["key"] for asset in assets}
        added = 0
        for asset in new_assets:
            if asset["key"] in existing_keys:
                continue
            assets.append(asset)
            existing_keys.add(asset["key"])
            added += 1
        _save_dream_assets(assets)
        st.session_state["dream_last_result"] = f"DREAM! added {added} asset{'s' if added != 1 else ''} to the reality list."
        st.success(st.session_state["dream_last_result"])
    if st.session_state.get("dream_last_result"):
        st.success(str(st.session_state["dream_last_result"]))

    encoded_preview = quote(str(raw_assets or ""), safe="")
    st.markdown(
        f"""
        <div class="dreams-fallback">
          <span>Button stubborn? use the hard-link path:</span>
          <a class="retro-tool retro-action-link" target="_self" href="/?dream_asset={encoded_preview}">DREAM LINK</a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if assets:
        st.markdown('<div class="dreams-table-wrap">', unsafe_allow_html=True)
        show_dataframe(
            pd.DataFrame(
                [
                    {
                        "asset": asset["asset"],
                        "type": asset["asset_type"],
                        "utility %": asset["utility_percent"],
                        "saleability %": asset["saleability_percent"],
                        "value": asset["estimated_value_label"],
                        "next AI move": asset["next_ai_move"],
                    }
                    for asset in assets
                ]
            )
        )
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("No dream assets linked yet. Add one asset per line and press DREAM!.")

    cols = st.columns([1, 1, 2])
    if cols[0].button("Clear Dreams", use_container_width=True):
        _save_dream_assets([])
        st.rerun()
    cols[1].markdown(
        '<a class="quantify-button" target="_blank" href="https://quantumbusinessstrategies.com">Quantify?</a>',
        unsafe_allow_html=True,
    )
    cols[2].caption("Heuristic estimates only. AI can later scout buyers, utility paths, listings, holders, comps, and monetization routes.")


def _load_dream_assets() -> list[dict[str, object]]:
    if not DREAM_ASSETS_PATH.exists():
        return []
    try:
        data = json.loads(DREAM_ASSETS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [dict(item) for item in data if isinstance(item, dict)]


def _save_dream_assets(assets: list[dict[str, object]]) -> None:
    DREAM_ASSETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DREAM_ASSETS_PATH.write_text(json.dumps(assets, ensure_ascii=True, indent=2), encoding="utf-8")


def _split_dream_inputs(raw_assets: str) -> list[str]:
    parts: list[str] = []
    for line in str(raw_assets or "").replace(",", "\n").splitlines():
        cleaned = " ".join(line.split())
        if cleaned:
            parts.append(cleaned)
    return parts


def _assess_dream_asset(asset: str) -> dict[str, object]:
    lowered = asset.lower()
    asset_type = _dream_asset_type(lowered)
    utility, saleability, value, move = _dream_scores(asset_type, lowered)
    return {
        "key": hashlib.sha256(asset.strip().lower().encode("utf-8")).hexdigest(),
        "asset": asset,
        "asset_type": asset_type,
        "utility_percent": utility,
        "saleability_percent": saleability,
        "estimated_value_label": value,
        "next_ai_move": move,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _dream_asset_type(lowered: str) -> str:
    if lowered.startswith("http") and any(term in lowered for term in ["domain", "porkbun", "godaddy", "namecheap"]):
        return "domain"
    if "." in lowered and " " not in lowered and "/" not in lowered.replace("https://", "").replace("http://", ""):
        return "domain"
    if any(term in lowered for term in ["opensea", "magiceden", "nft", "collection"]):
        return "nft"
    if any(term in lowered for term in ["coin", "token", "crypto", "sol", "eth", "btc", "wallet"]):
        return "crypto"
    if any(term in lowered for term in ["stock", "nasdaq", "nyse", "ticker", "$"]):
        return "stock"
    if any(term in lowered for term in ["ebay", "etsy", "amazon", "listing", "marketplace"]):
        return "listing"
    if any(term in lowered for term in ["github", "repo", "app", "saas", "product"]):
        return "digital_product"
    return "asset"


def _dream_scores(asset_type: str, lowered: str) -> tuple[int, int, str, str]:
    profiles = {
        "domain": (72, 58, "$50-$5,000+", "Check domain comps, landing page use, outbound buyers, and SEO/business fit."),
        "nft": (38, 42, "floor-dependent", "Check collection liquidity, holder demand, royalties, and safe listing options."),
        "crypto": (44, 65, "market-dependent", "Watch liquidity, volatility, unlocks, staking/airdrop utility, and risk flags."),
        "stock": (48, 78, "market quote", "Pull current quote, thesis, dividend/options utility, and exit/liquidity paths."),
        "listing": (62, 70, "listing comps", "Compare sold comps, improve title/photos/price, and route to marketplace action."),
        "digital_product": (78, 55, "$100-$25,000+", "Map users, monetization, landing page, distribution, and buyer/acquirer paths."),
        "asset": (50, 45, "needs comps", "Classify asset, find comps, and generate utility/sale path."),
    }
    utility, saleability, value, move = profiles.get(asset_type, profiles["asset"])
    if "quantum" in lowered or "business" in lowered:
        utility = min(95, utility + 8)
    if lowered.startswith("http"):
        saleability = min(95, saleability + 5)
    return utility, saleability, value, move


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inject_retro_command_os_style() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap');
        .stApp {
            background: #008080;
            color: #111;
            font-family: "VT323", "Courier New", monospace;
            image-rendering: pixelated;
        }
        [data-testid="stAppViewContainer"] > .main {
            background: #008080;
        }
        [data-testid="stHeader"] {
            background: transparent;
        }
        .block-container {
            max-width: 1280px;
            background: #c0c0c0;
            border: 1px solid #222;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: .65rem .75rem 2rem;
        }
        h1 {
            color: #111;
            letter-spacing: 0;
        }
        div[data-testid="stMetric"],
        div[data-testid="stExpander"],
        div[data-testid="stDataFrame"],
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: #e8e8e8;
            border: 1px solid #777;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
        }
        button[kind="secondary"],
        button[kind="primary"],
        .stButton > button,
        .stDownloadButton > button,
        a[data-testid="stLinkButton"] {
            background: #c0c0c0 !important;
            color: #111 !important;
            border: 1px solid #777 !important;
            border-radius: 0 !important;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555 !important;
            font-family: "VT323", "Courier New", monospace !important;
            font-size: 18px !important;
            font-weight: 700 !important;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 2px;
            background: #c0c0c0;
            border: 1px solid #777;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 2px;
        }
        .stTabs [data-baseweb="tab"] {
            background: #c0c0c0;
            border: 1px solid #777;
            border-radius: 0;
            min-height: 34px;
            font-family: "VT323", "Courier New", monospace !important;
            font-size: 20px;
            font-weight: 700;
        }
        .stTabs [aria-selected="true"] {
            background: #000080 !important;
            color: white !important;
        }
        input, textarea, select {
            border-radius: 0 !important;
            font-family: "VT323", "Courier New", monospace !important;
            font-size: 18px !important;
        }
        .retro-titlebar {
            background: #000080;
            color: white;
            padding: 5px 8px;
            font-size: 17px;
            font-weight: 700;
            border: 1px solid #222;
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .retro-menu {
            display: flex;
            gap: 18px;
            flex-wrap: wrap;
            background: #c0c0c0;
            border: 1px solid #777;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 4px 8px;
            font-size: 18px;
            margin-bottom: 8px;
        }
        .retro-menu a,
        .retro-menu a:visited {
            color: #111;
            text-decoration: none;
            padding: 1px 4px;
        }
        .retro-menu a:hover {
            background: #000080;
            color: #fff;
        }
        .retro-status {
            background: #000;
            color: #00ff66;
            border: 1px solid #777;
            padding: 8px;
            font-size: 17px;
            margin: 8px 0;
            box-shadow: inset 1px 1px 0 #555, inset -1px -1px 0 #111;
        }
        .retro-shell {
            border: 1px solid #222;
            background: #c0c0c0;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 0;
            margin: 0 0 10px 0;
        }
        .retro-toolbar {
            display: flex;
            gap: 6px;
            align-items: center;
            flex-wrap: wrap;
            border-top: 1px solid #777;
            border-bottom: 1px solid #777;
            padding: 8px;
            background: #c0c0c0;
        }
        .retro-tool {
            border: 1px solid #777;
            background: #c0c0c0;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 5px 10px;
            font-size: 18px;
            font-weight: 700;
            white-space: nowrap;
        }
        .retro-tool.active {
            background: #000080;
            color: #fff;
        }
        .fastest-gains-link,
        .fastest-gains-link:visited {
            color: #b00000 !important;
            font-weight: 900 !important;
            text-shadow: 1px 1px 0 #fff;
        }
        .fastest-gains-link:hover {
            background: #b00000 !important;
            color: #fff !important;
            text-shadow: none;
        }
        .easy-link,
        .easy-link:visited {
            color: #ff0000 !important;
            font-weight: 1000 !important;
            letter-spacing: .06em;
            text-shadow: 1px 1px 0 #fff, 0 0 7px rgba(255,0,0,.65);
            border-color: #7a0000 !important;
        }
        .easy-link:hover {
            background: #ff0000 !important;
            color: #fff !important;
            text-shadow: 1px 1px 0 #111;
        }
        .ai-labor-link,
        .ai-labor-link:visited {
            color: #0044ff !important;
            font-weight: 1000 !important;
            letter-spacing: .04em;
            text-shadow: 1px 1px 0 #fff, 0 0 7px rgba(0,70,255,.55);
            border-color: #001a7a !important;
        }
        .ai-labor-link:hover {
            background: #0044ff !important;
            color: #fff !important;
            text-shadow: 1px 1px 0 #111;
        }
        .treasury-link,
        .treasury-link:visited {
            color: #006b2a !important;
            font-weight: 1000 !important;
            letter-spacing: .04em;
            text-shadow: 1px 1px 0 #fff, 0 0 7px rgba(0,140,60,.55);
            border-color: #005a00 !important;
        }
        .treasury-link:hover {
            background: #007a2f !important;
            color: #fff !important;
            text-shadow: 1px 1px 0 #111;
        }
        .chaos-link,
        .chaos-link:visited {
            color: #b000ff !important;
            font-weight: 1000 !important;
            letter-spacing: .06em;
            text-shadow: 1px 1px 0 #fff, 0 0 7px rgba(176,0,255,.6);
            border-color: #4b006d !important;
        }
        .chaos-link:hover {
            background: #4b006d !important;
            color: #fff !important;
            text-shadow: 1px 1px 0 #111;
        }
        .retro-action-link,
        .retro-action-link:visited {
            display: inline-block;
            color: #111;
            text-decoration: none;
            cursor: pointer;
        }
        .retro-tool.retro-action-link:hover,
        .retro-nav-item.retro-action-link:hover,
        .retro-mini-panel.retro-action-link:hover {
            background: #000080;
            color: #fff;
        }
        .retro-main-grid {
            display: grid;
            grid-template-columns: 250px minmax(0, 1fr);
            gap: 12px;
            padding: 12px;
        }
        .retro-panel {
            border: 1px solid #777;
            background: #efefef;
            box-shadow: 2px 2px 0 #777, inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 12px;
        }
        .retro-panel-title {
            font-weight: 700;
            letter-spacing: 2px;
            font-size: 18px;
            margin-bottom: 8px;
            text-transform: uppercase;
        }
        .retro-nav-item {
            padding: 7px 9px;
            font-size: 20px;
            margin: 6px 0;
            border: 1px solid #777;
            background: #d8d8d8;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            font-weight: 700;
        }
        .retro-nav-item.active {
            background: #000080;
            color: #fff;
            font-weight: 700;
            box-shadow: inset -1px -1px 0 #fff, inset 1px 1px 0 #000;
        }
        .retro-action-drawer {
            margin-top: 8px;
            border: 1px solid #777;
            background: #d0d0d0;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
        }
        .retro-action-drawer summary {
            cursor: pointer;
            list-style: none;
            background: #c0c0c0;
            border-bottom: 1px solid #777;
            padding: 6px 8px;
            font-size: 18px;
            font-weight: 800;
            letter-spacing: 1px;
            text-transform: uppercase;
        }
        .retro-action-drawer summary::-webkit-details-marker {
            display: none;
        }
        .retro-action-drawer summary::before {
            content: "+ ";
            color: #000080;
            font-weight: 900;
        }
        .retro-action-drawer[open] summary::before {
            content: "- ";
        }
        .retro-drawer-body {
            padding: 7px;
            display: grid;
            gap: 5px;
            background:
                linear-gradient(90deg, rgba(0,0,0,.04) 1px, transparent 1px),
                linear-gradient(rgba(0,0,0,.04) 1px, transparent 1px),
                #e6e6e6;
            background-size: 10px 10px;
        }
        .retro-drawer-link {
            display: block;
            border: 1px solid #777;
            background: #efefef;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #777;
            padding: 5px 7px;
            font-size: 17px;
            font-weight: 700;
            color: #111;
            text-decoration: none;
        }
        .retro-drawer-link:hover {
            background: #000080;
            color: #fff;
        }
        .retro-drawer-note {
            font-size: 15px;
            color: #44506a;
            line-height: 1.05;
        }
        .retro-content-header {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: flex-start;
            margin-bottom: 14px;
        }
        .retro-workspace {
            border: 1px solid #777;
            background: #f7f7f7;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 16px;
            min-height: 650px;
        }
        .retro-command-title {
            font-size: 52px;
            line-height: 1;
            font-weight: 800;
            letter-spacing: 0;
            margin: 0;
        }
        .retro-subtitle {
            color: #35445a;
            font-size: 20px;
            letter-spacing: .04em;
            margin-top: 6px;
        }
        .retro-radio {
            color: #4d5970;
            font-size: 18px;
            font-style: italic;
            margin-top: 8px;
        }
        .retro-metrics {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 8px;
            margin-bottom: 12px;
        }
        .retro-card {
            border: 1px solid #777;
            background: #e8e8e8;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 10px;
            min-height: 72px;
        }
        .retro-card-label {
            font-size: 17px;
            color: #35445a;
            text-transform: uppercase;
            letter-spacing: .06em;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .retro-card-value {
            font-size: 34px;
            font-weight: 800;
            line-height: 1.1;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .retro-card-sub {
            font-size: 16px;
            color: #536079;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .retro-autorun {
            display: grid;
            grid-template-columns: 130px 1fr;
            gap: 12px;
            align-items: center;
            border: 1px solid #777;
            background: #efefef;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 10px;
            margin-bottom: 12px;
            font-size: 18px;
        }
        .retro-autorun-line {
            display: flex;
            gap: 0;
            flex-wrap: wrap;
            font-size: 18px;
            align-items: stretch;
        }
        .retro-autorun-cell {
            min-width: 86px;
            border: 1px solid #999;
            background: #f7f7f7;
            padding: 4px 7px;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #aaa;
            text-align: center;
            line-height: 1.1;
        }
        .retro-two-col {
            display: grid;
            grid-template-columns: 1.15fr 1fr;
            gap: 12px;
        }
        .retro-task-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 10px;
            align-items: start;
        }
        .retro-phase {
            display: inline-block;
            font-size: 38px;
            text-align: left;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            border: 1px inset #999;
            background: #fff;
            padding: 2px 10px;
            margin-top: 3px;
            max-width: 100%;
        }
        .retro-blocker-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 52px 70px;
            gap: 8px;
            border-bottom: 1px solid #c8c8c8;
            padding: 8px 0;
            align-items: center;
            color: #111;
            text-decoration: none;
        }
        .retro-blocker-row.retro-action-link:hover {
            background: #000080;
            color: #fff;
        }
        .retro-table-shell {
            border: 1px solid #777;
            background: #efefef;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            margin-top: 12px;
            min-height: 260px;
        }
        .retro-tabs {
            display: flex;
            gap: 2px;
            align-items: stretch;
            border-bottom: 1px solid #777;
            background: #c0c0c0;
            overflow: hidden;
        }
        .retro-tab {
            padding: 9px 14px;
            border-right: 1px solid #777;
            background: #c0c0c0;
            font-size: 20px;
            font-weight: 700;
            white-space: nowrap;
        }
        .retro-tab.active {
            background: #fff;
        }
        .retro-filter {
            margin-left: auto;
            background: #fff;
            border-left: 1px solid #777;
            padding: 9px 14px;
            color: #7b7b7b;
            font-size: 20px;
            font-weight: 700;
            min-width: 170px;
        }
        .retro-data-wrap {
            max-height: 190px;
            overflow: auto;
            background: #fff;
        }
        .retro-data-table {
            border-collapse: collapse;
            width: 100%;
            table-layout: fixed;
            font-size: 19px;
            font-family: "VT323", "Courier New", monospace;
        }
        .retro-data-table th,
        .retro-data-table td {
            border: 1px solid #c8c8c8;
            padding: 8px 9px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            text-align: left;
        }
        .retro-data-table th {
            background: #dcdcdc;
            color: #22304f;
            text-transform: uppercase;
            font-size: 16px;
            letter-spacing: .06em;
        }
        .retro-scrollbar {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 4px 8px;
            background: #c0c0c0;
            border-top: 1px solid #777;
        }
        .retro-scroll-track {
            height: 12px;
            flex: 1;
            background: #8f8f8f;
            border: 1px solid #777;
            box-shadow: inset 1px 1px 0 #555, inset -1px -1px 0 #ddd;
        }
        .retro-scroll-thumb {
            height: 100%;
            width: 44%;
            background: #d8d8d8;
            border-right: 1px solid #555;
        }
        .retro-small {
            font-size: 17px;
            color: #536079;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .retro-utility-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
            margin-top: 12px;
        }
        .retro-mini-panel {
            border: 1px solid #777;
            background: #e8e8e8;
            box-shadow: 2px 2px 0 #888, inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 10px;
            min-height: 88px;
            font-size: 18px;
        }
        .retro-mini-panel b {
            display: block;
            letter-spacing: 2px;
            margin-bottom: 6px;
        }
        .retro-canvas {
            min-height: 170px;
            background:
                linear-gradient(90deg, rgba(0,0,0,.045) 1px, transparent 1px),
                linear-gradient(rgba(0,0,0,.045) 1px, transparent 1px),
                #f8f8f8;
            background-size: 12px 12px;
            border: 1px inset #999;
            box-shadow: inset 2px 2px 0 #aaa, inset -2px -2px 0 #fff;
            padding: 10px;
            font-size: 19px;
            line-height: 1.25;
        }
        .retro-input-area {
            min-height: 135px;
            background: #fff;
            border: 2px inset #9a9a9a;
            padding: 10px;
            font-size: 18px;
            line-height: 1.15;
            box-shadow: inset 2px 2px 0 #777;
        }
        .retro-section-head {
            background: #000080;
            color: #fff;
            padding: 5px 8px;
            font-weight: 700;
            font-size: 17px;
            margin: -12px -12px 10px -12px;
        }
        .operator-console {
            border: 1px solid #222;
            background: #c0c0c0;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 10px;
            margin: 10px 0 12px 0;
        }
        .operator-console-title {
            background: #000080;
            color: #fff;
            padding: 5px 8px;
            font-size: 20px;
            font-weight: 700;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }
        .operator-console-note {
            background: #000;
            color: #00ff66;
            border: 1px solid #777;
            padding: 7px 9px;
            font-size: 18px;
            margin-top: 8px;
        }
        .operator-workbench {
            border: 1px solid #222;
            background: #d8d8d8;
            box-shadow: 2px 2px 0 #777, inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 10px;
            margin: 10px 0 12px 0;
        }
        .operator-workbench-title {
            background: #000080;
            color: #fff;
            padding: 5px 8px;
            font-weight: 700;
            font-size: 20px;
            margin-bottom: 8px;
        }
        .operator-routebar {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin: 8px 0;
        }
        .approval-gate {
            background:
                linear-gradient(90deg, rgba(255,255,255,.35) 0 1px, transparent 1px),
                #d8d8d8;
            background-size: 10px 10px;
        }
        .fastest-gains-panel {
            background:
                linear-gradient(90deg, rgba(255,255,255,.38) 0 1px, transparent 1px),
                linear-gradient(rgba(0,0,0,.04) 0 1px, transparent 1px),
                #efefef;
            background-size: 10px 10px;
        }
        .fastest-gains-title {
            background: #b00000;
            color: #fff;
        }
        .easy-title-shell {
            border: 2px solid #7a0000;
            background:
                linear-gradient(90deg, rgba(255,255,255,.35) 0 1px, transparent 1px),
                linear-gradient(rgba(0,0,0,.06) 0 1px, transparent 1px),
                #d8d8d8;
            background-size: 10px 10px;
            box-shadow: 3px 3px 0 #777, inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 14px;
            margin: 0 0 12px 0;
        }
        .easy-title {
            color: #e00000;
            font-size: 42px;
            font-weight: 1000;
            line-height: 1;
            letter-spacing: .04em;
            text-align: center;
            text-shadow:
                1px 1px 0 #fff,
                0 0 7px rgba(255,0,0,.8),
                0 0 14px rgba(255,0,0,.45);
        }
        .easy-subtitle,
        .easy-note {
            color: #1b2840;
            font-size: 18px;
            font-weight: 700;
            margin-top: 8px;
            text-align: center;
        }
        .easy-note {
            border: 1px solid #777;
            background: #efefef;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 8px;
            text-align: left;
            margin: 8px 0;
        }
        .easy-ready-panel {
            border: 2px solid #005a00;
            background:
                linear-gradient(90deg, rgba(255,255,255,.35) 0 1px, transparent 1px),
                #d8d8d8;
            background-size: 10px 10px;
            box-shadow: 3px 3px 0 #777, inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 12px;
            margin: 14px 0 8px 0;
        }
        .easy-ready-title {
            color: #005a00;
            font-size: 32px;
            font-weight: 1000;
            text-align: center;
            text-shadow: 1px 1px 0 #fff, 0 0 8px rgba(0,255,60,.55);
        }
        .ai-labor-title-shell {
            border-color: #001a7a;
        }
        .ai-labor-title-shell .easy-title,
        .ai-labor-panel .easy-ready-title {
            color: #0044ff;
            text-shadow: 1px 1px 0 #fff, 0 0 8px rgba(0,70,255,.65);
        }
        .ai-labor-panel {
            border-color: #001a7a;
        }
        .treasury-title-shell {
            border-color: #005a00;
        }
        .treasury-title-shell .easy-title,
        .treasury-panel .easy-ready-title {
            color: #007a2f;
            text-shadow: 1px 1px 0 #fff, 0 0 8px rgba(0,180,80,.65);
        }
        .treasury-panel {
            border-color: #005a00;
        }
        .chaos-title-shell {
            border-color: #4b006d;
            background:
                linear-gradient(90deg, rgba(255,255,255,.35) 0 1px, transparent 1px),
                linear-gradient(rgba(0,0,0,.12) 0 1px, transparent 1px),
                #d0c0d8;
            background-size: 10px 10px;
        }
        .chaos-title-shell .easy-title {
            color: #b000ff;
            text-shadow: 1px 1px 0 #fff, 0 0 9px rgba(176,0,255,.75);
        }
        .chaos-panel {
            border: 2px solid #4b006d;
            background: #e8d8ef;
            box-shadow: 3px 3px 0 #777, inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 12px;
            margin: 10px 0;
        }
        .chaos-warning {
            color: #7a0000;
            font-size: 28px;
            font-weight: 1000;
            text-align: center;
            text-shadow: 1px 1px 0 #fff;
        }
        .global-page-links {
            margin-top: 18px;
            border: 1px solid #777;
            background: #c0c0c0;
            box-shadow: 3px 3px 0 #777, inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 8px;
        }
        .approval-stack {
            display: grid;
            gap: 8px;
            margin: 8px 0 10px 0;
        }
        .approval-card {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(520px, auto);
            gap: 10px;
            align-items: center;
            border: 1px solid #777;
            background: #efefef;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 9px;
        }
        .approval-card-title {
            font-size: 22px;
            font-weight: 800;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .approval-card-meta,
        .approval-card-why {
            font-size: 17px;
            color: #35445a;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .approval-card-actions {
            display: flex;
            gap: 4px;
            flex-wrap: wrap;
            justify-content: flex-end;
            max-width: 560px;
        }
        .approval-card-actions .retro-tool {
            padding: 4px 8px;
            font-size: 17px;
        }
        details[data-testid="stExpander"] summary,
        div[data-testid="stExpander"] summary {
            font-family: "VT323", "Courier New", monospace !important;
            font-size: 22px !important;
            font-weight: 700 !important;
            background: #c0c0c0 !important;
            border: 1px solid #777 !important;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555 !important;
        }
        @media (max-width: 1000px) {
            .retro-main-grid,
            .retro-two-col {
                grid-template-columns: 1fr;
            }
            .retro-metrics {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .retro-command-title {
                font-size: 28px;
            }
            .retro-utility-grid {
                grid-template-columns: 1fr;
            }
            .approval-card {
                grid-template-columns: 1fr;
            }
            .approval-card-actions {
                justify-content: flex-start;
            }
        }
        .magic-money-workbench {
            background:
                linear-gradient(90deg, rgba(0,0,128,.08) 0 1px, transparent 1px),
                linear-gradient(rgba(0,0,128,.08) 0 1px, transparent 1px),
                #d8d8d8;
            background-size: 12px 12px;
        }
        .magic-money-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 8px;
            margin-top: 8px;
        }
        .dreams-workbench {
            background:
                repeating-linear-gradient(45deg, rgba(0,0,0,.04) 0 4px, transparent 4px 8px),
                #d0d0d0;
        }
        .dreams-note {
            background: #f7f7f7;
            border: 2px inset #999;
            padding: 8px 10px;
            font-size: 18px;
            color: #24324d;
        }
        .dreams-table-wrap {
            border: 1px solid #777;
            background: #efefef;
            box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #555;
            padding: 8px;
            margin-top: 8px;
        }
        .dreams-fallback {
            display: flex;
            align-items: center;
            gap: 8px;
            margin: 6px 0 10px 0;
            font-size: 16px;
            color: #35445a;
        }
        .quantify-button,
        .quantify-button:visited {
            display: block;
            text-align: center;
            background: #1b1b1b;
            color: #7cff00;
            border: 1px solid #4a4a4a;
            box-shadow: inset 1px 1px 0 #555, inset -1px -1px 0 #000;
            padding: 7px 10px;
            text-decoration: none;
            font-size: 20px;
            font-weight: 800;
            filter: grayscale(.25);
        }
        .quantify-button:hover {
            background: #000;
            color: #ff4dff;
        }
        @media (max-width: 1000px) {
            .magic-money-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
    context = load_effective_user_context()
    completeness = compute_completeness(context)
    rows = rows_for_action_center(conn)
    dependencies = global_input_dependency_map(rows)
    metrics = load_metrics(conn)
    potential_unlocks = len({title for dependency in dependencies for title in dependency.blocks})
    control = load_autorun_control()
    status = autorun_status_summary(conn)
    task = current_ai_task(conn)
    blockers = autorun_blocked_reasons(conn)
    autonomy = _current_autonomy_percent(rows, completeness)
    value_surface = _queue_value_surface(conn)
    received_paid = metrics["received_log"]

    metric_cards = [
        ("Autonomy", f"{autonomy:.1f}%", "safe work coverage"),
        ("Context", f"{completeness.automation_readiness_score:.1f}%", "vault completeness"),
        ("Unlocks", str(potential_unlocks), "ready routes"),
        ("Received", str(received_paid), "paid / assets"),
        ("Value Surface", f"${value_surface:,.0f}", "discovered map"),
    ]
    metric_html = "".join(
        f'<div class="retro-card"><div class="retro-card-label">{_h(label)}</div>'
        f'<div class="retro-card-value">{_h(value)}</div>'
        f'<div class="retro-card-sub">{_h(sub)}</div></div>'
        for label, value, sub in metric_cards
    )
    blocker_html = "".join(_retro_blocker_html(blocker) for blocker in blockers[:3])
    if not blocker_html:
        blocker_html = '<div class="retro-small">No current blockers detected.</div>'

    task_title = _h(_short_text(task.get("title") if task else "No active AI task", 46))
    task_source = _h(str(task.get("source_domain") if task else "local"))
    task_missing = _h(str(task.get("missing_input") if task else "None detected"))
    task_confidence = _h(str(task.get("confidence_level") if task else "n/a"))
    task_phase = _h(str(task.get("phase") if task else "idle").title())
    task_next = _h(_short_text(task.get("next_required_action") if task else "Waiting for queue work.", 95))
    table_preview = _retro_table_preview_html(conn)
    strategy = _h(str(control.get("mode") or "Balanced"))
    execution = _h(str(control.get("execution_mode") or "Dry Run").replace("Live Assist", "Live Assist").replace("Live Submit With Final Approval", "Final OK"))
    autorun_state = "ON" if control.get("enabled") else "OFF"

    shell_html = f"""
        <div class="retro-shell">
          <div class="retro-titlebar">
            <span>quantumgains v0.9 - Self-Expanding Acquisition Engine</span>
            <span>□ ×</span>
          </div>
          <div class="retro-menu">
            <a target="_self" href="/">File</a>
            <a target="_self" href="/?operator_action=autonomy_boost">Entity</a>
            <a target="_self" href="/?view=claim_queue&sort=readiness#active-operator-table">Queue</a>
            <a target="_self" href="/?page=vault">Vault</a>
            <a target="_self" href="/?view=sources&sort=updated#active-operator-table">Sources</a>
            <a target="_self" href="#operator-console">Operator</a>
            <a target="_self" href="/?operator_action=autonomy_pump">Automation</a>
            <a target="_self" href="/?view=opportunities&sort=value#active-operator-table">View</a>
            <a target="_self" href="#command-os-adapter-contract">Help</a>
          </div>
          <div class="retro-toolbar">
            <a class="retro-tool retro-action-link active" target="_self" href="/">📂 Mission</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=safe_auto_cycle">💰 Value</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=dependencies">🔗 Connectors</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=completion_sync">📋 Queue</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=review_task#operator-console">🤖 AI Task</a>
            <a class="retro-tool retro-action-link easy-link" target="_self" href="/?page=easy">EASY</a>
            <a class="retro-tool retro-action-link ai-labor-link" target="_self" href="/?page=ai_labor">AI LABOR</a>
            <a class="retro-tool retro-action-link treasury-link" target="_self" href="/?page=treasury">TREASURY</a>
            <a class="retro-tool retro-action-link chaos-link" target="_self" href="/?page=chaos">CHAOS</a>
            <a class="retro-tool retro-action-link fastest-gains-link" target="_self" href="/?view=fastest&sort=fastest#active-operator-table">FASTEST GAINS</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=autonomy_pump">PUMP</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?operator_action=magic_money_scout">MAGIC $</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?page=vault">🔐 Vault</a>
            <a class="retro-tool retro-action-link" target="_self" href="/?page=vault">⚙ Settings</a>
            <span class="retro-small">♪ lofi-acquire.mid // scan -> prep -> approve -> deliver</span>
          </div>
          <div class="retro-main-grid">
            <div>
              <div class="retro-panel">
                <div class="retro-panel-title">ENTITY EXPLORER.EXE</div>
                <div class="retro-small"><i>route // queue // acquire</i></div>
                <a class="retro-nav-item retro-action-link active" target="_self" href="/">▸ Mission</a>
                <a class="retro-nav-item retro-action-link" target="_self" href="/?view=opportunities&sort=value#active-operator-table">▸ Opportunities</a>
                <a class="retro-nav-item retro-action-link" target="_self" href="/?view=claim_queue&sort=readiness#active-operator-table">▸ Claim Queue</a>
                <a class="retro-nav-item retro-action-link easy-link" target="_self" href="/?page=easy">EASY</a>
                <a class="retro-nav-item retro-action-link ai-labor-link" target="_self" href="/?page=ai_labor">AI LABOR</a>
                <a class="retro-nav-item retro-action-link treasury-link" target="_self" href="/?page=treasury">TREASURY</a>
                <a class="retro-nav-item retro-action-link chaos-link" target="_self" href="/?page=chaos">CHAOS MODE</a>
                <a class="retro-nav-item retro-action-link fastest-gains-link" target="_self" href="/?view=fastest&sort=fastest#active-operator-table">▸ FASTEST GAINS</a>
                <a class="retro-nav-item retro-action-link" target="_self" href="/?view=approvals&sort=value#active-operator-table">▸ Approvals</a>
                <a class="retro-nav-item retro-action-link" target="_self" href="/?view=execution&sort=updated#active-operator-table">▸ Execution</a>
                <a class="retro-nav-item retro-action-link" target="_self" href="/?view=sources&sort=updated#active-operator-table">▸ Sources</a>
                <a class="retro-nav-item retro-action-link" target="_self" href="/?view=blocked&sort=readiness#active-operator-table">▸ Blockers</a>
                <a class="retro-nav-item retro-action-link" target="_self" href="#magic-fairytale-monies">▸ Magic Money</a>
                <a class="retro-nav-item retro-action-link" target="_self" href="/?page=vault">▸ Vault</a>
                <a class="retro-nav-item retro-action-link" target="_self" href="#operator-console">▸ Operator</a>
                <details class="retro-action-drawer" open>
                  <summary>Run Work</summary>
                  <div class="retro-drawer-body">
                    <a class="retro-drawer-link" target="_self" href="/?operator_action=discovery">Fetch Scan</a>
                    <a class="retro-drawer-link" target="_self" href="/?operator_action=autonomy_pump">Autonomy Pump</a>
                    <a class="retro-drawer-link" target="_self" href="/?operator_action=live_assist_prep">Live Assist Prep</a>
                    <a class="retro-drawer-link" target="_self" href="/?operator_action=browser_execute_safe_batch">Safe Browser Execute</a>
                    <a class="retro-drawer-link" target="_self" href="/?operator_action=safe_auto_cycle">Safe Auto Cycle</a>
                    <div class="retro-drawer-note">Runs local discovery/prep passes. No external final submit.</div>
                  </div>
                </details>
                <details class="retro-action-drawer">
                  <summary>Queues</summary>
                  <div class="retro-drawer-body">
                    <a class="retro-drawer-link" target="_self" href="/?view=ready&sort=value#active-operator-table">Ready Accepts</a>
                    <a class="retro-drawer-link fastest-gains-link" target="_self" href="/?view=fastest&sort=fastest#active-operator-table">FASTEST GAINS</a>
                    <a class="retro-drawer-link" target="_self" href="/?view=approvals&sort=value#active-operator-table">Approval Gates</a>
                    <a class="retro-drawer-link" target="_self" href="/?view=blocked&sort=readiness#active-operator-table">Blocked Inputs</a>
                    <a class="retro-drawer-link" target="_self" href="/?view=execution&sort=updated#active-operator-table">AI Working</a>
                    <div class="retro-drawer-note">Routes to selectable tables with real queue actions.</div>
                  </div>
                </details>
                <details class="retro-action-drawer">
                  <summary>Vault / Inputs</summary>
                  <div class="retro-drawer-body">
                    <a class="retro-drawer-link" target="_self" href="/?page=vault">Open Vault</a>
                    <a class="retro-drawer-link" target="_self" href="/?operator_action=dependencies">Dependency Map</a>
                    <a class="retro-drawer-link" target="_self" href="/?view=blocked&sort=readiness#active-operator-table">Resolve Blockers</a>
                    <div class="retro-drawer-note">Reusable context feeds Required Inputs and autofill plans.</div>
                  </div>
                </details>
                <details class="retro-action-drawer">
                  <summary>Gain Scout</summary>
                  <div class="retro-drawer-body">
                    <a class="retro-drawer-link" target="_self" href="/?operator_action=magic_money_scout">Magic Scout</a>
                    <a class="retro-drawer-link" target="_self" href="/?operator_action=autonomy_boost">Autonomy Boost</a>
                    <a class="retro-drawer-link" target="_self" href="#dreams-reality">Dream Asset List</a>
                    <div class="retro-drawer-note">Adds lawful gain lanes into the existing source/queue flow.</div>
                  </div>
                </details>
              </div>
              <div class="retro-panel" style="margin-top:12px;">
                  <div class="retro-section-head">PIPELINE.CANVAS</div>
                  <div class="retro-canvas">
                    <div>01 AI finds</div><div>02 AI preps</div><div>03 User approves</div><div>04 AI finalizes</div><div>05 Asset delivered</div>
                  </div>
              </div>
              <div class="retro-panel" style="margin-top:12px;">
                <div class="retro-section-head">ADAPTERS.TXT</div>
                <div class="retro-input-area">
                  <div>&gt; openOfficialPath()</div><div>&gt; buildAutofillPlan()</div><div>&gt; applyQueueAction()</div><div>&gt; markReceivedPaid()</div>
                </div>
              </div>
            </div>
            <div>
              <div class="retro-workspace">
              <div class="retro-content-header">
                <div>
                  <div class="retro-command-title">quantumgains</div>
                  <div class="retro-subtitle">SELF-EXPANDING ACQUISITION ENGINE</div>
                  <div class="retro-radio">[radio] dialup dreams.wav - approved assets only</div>
                </div>
                <div style="text-align:right;">
                  <a class="retro-tool retro-action-link" target="_self" href="/?page=vault">🔐 User Vault</a>
                  <div style="margin-top:8px;">AUTORUN: <b>{autorun_state}</b></div>
                </div>
              </div>
              <div class="retro-metrics">{metric_html}</div>
              <div class="retro-autorun">
                <div><b>AUTORUN</b></div>
                <div>
                  <div class="retro-autorun-line">
                    <span class="retro-autorun-cell">Strategy:<br><b>{strategy}</b></span>
                    <span class="retro-autorun-cell">Mode:<br><b>{execution}</b></span>
                    <span class="retro-autorun-cell">Scan<br><b>{status["ai_currently_scanning"]}</b></span>
                    <span class="retro-autorun-cell">Prep<br><b>{status["ai_preparing"]}</b></span>
                    <span class="retro-autorun-cell">Exec<br><b>{status["ai_executing"]}</b></span>
                    <span class="retro-autorun-cell">OK<br><b>{status["waiting_approval"]}</b></span>
                    <span class="retro-autorun-cell">Paid<br><b>{status["received_paid"]}</b></span>
                  </div>
                  <div class="retro-small" style="margin-top:8px;">{_h(_autorun_execution_mode_text(str(control.get("execution_mode") or "Dry Run")))}</div>
                </div>
              </div>
              <div class="retro-two-col">
                <div class="retro-panel">
                  <div class="retro-panel-title">▾ AI TASK.EXE</div>
                  <div class="retro-task-grid">
                    <div>
                      <b>{task_title}</b>
                      <div class="retro-small">Source: {task_source} · Missing: {task_missing} · Confidence: {task_confidence}</div>
                      <div class="retro-small">Next: {task_next}</div>
                    </div>
                    <div>
                      <div class="retro-small" style="text-align:left;">PHASE</div>
                      <div class="retro-phase">{task_phase}</div>
                    </div>
                  </div>
                </div>
                <div class="retro-panel">
                  <div class="retro-panel-title">▾ BLOCKERS</div>
                  {blocker_html}
                </div>
              </div>
              <div class="retro-utility-grid">
                <a class="retro-mini-panel retro-action-link" target="_self" href="/?operator_action=live_assist_prep"><b>UTILITY PORTS</b><div>Official link opener</div><div>Safe autofill planner</div><div>Final approval packet</div></a>
                <a class="retro-mini-panel retro-action-link" target="_self" href="/?page=vault"><b>CONNECTORS</b><div>Google / GitHub / PayPal</div><div>Manual login approvals</div><div>Status-driven autofill</div></a>
                <a class="retro-mini-panel retro-action-link" target="_self" href="/?operator_action=completion_sync"><b>DELIVERY</b><div>Received/Paid tracking</div><div>Destination routing</div><div>Asset receipt log</div></a>
              </div>
              {table_preview}
              </div>
            </div>
          </div>
        </div>
        """
    shell_html = (
        shell_html.replace("\u00e2\u2013\u00a1 \u00c3\u2014", "[] X")
        .replace("\u00f0\u0178\u201c\u201a Mission", "[F1] Mission")
        .replace("\u00f0\u0178\u2019\u00b0 Value", "[$] Value")
        .replace("\u00f0\u0178\u201d\u2014 Connectors", "[LINK] Connectors")
        .replace("\u00f0\u0178\u201c\u2039 Queue", "[Q] Queue")
        .replace("\u00f0\u0178\u00a4\u2013 AI Task", "[AI] Task")
        .replace("\u00f0\u0178\u201d\u0090 Vault", "[LOCK] Vault")
        .replace("\u00f0\u0178\u201d\u0090 User Vault", "[LOCK] User Vault")
        .replace("\u00e2\u0161\u2122 Settings", "[GEAR] Settings")
        .replace("\u00e2\u2122\u00aa ", "")
        .replace("\u00e2\u2013\u00b8", "&gt;")
        .replace("\u00e2\u2013\u00be", "v")
        .replace("\u00c2\u00b7", "//")
        .replace("no-op", "no-op")
        .replace("ðŸ“‚ Mission", "[F1] Mission")
        .replace("ðŸ’° Value", "[$] Value")
        .replace("ðŸ”— Connectors", "[LINK] Connectors")
        .replace("ðŸ“‹ Queue", "[Q] Queue")
        .replace("ðŸ¤– AI Task", "[AI] Task")
        .replace("ðŸ” Vault", "[LOCK] Vault")
        .replace("ðŸ” User Vault", "[LOCK] User Vault")
        .replace("âš™ Settings", "[GEAR] Settings")
        .replace("â™ª ", "")
        .replace("â–¸", "&gt;")
        .replace("â–¾", "v")
        .replace("Â·", "//")
    )
    st.markdown(
        shell_html,
        unsafe_allow_html=True,
    )


def dashboard_rules() -> dict[str, object]:
    try:
        return load_yaml_file(RULES_PATH)
    except FileNotFoundError:
        return {}


def _queue_value_surface(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(COALESCE(expected_value_usd, 0)), 0) AS value_surface
        FROM claim_queue
        WHERE status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later')
        """
    ).fetchone()
    return _safe_float(row["value_surface"] if row else 0)


def _retro_blocker_html(blocker: dict[str, object]) -> str:
    raw_reason = str(blocker.get("reason") or "Blocked")
    reason = _h(raw_reason.upper())
    required = _h(_short_text(blocker.get("required_action") or "Owner action required.", 42))
    opportunities = int(blocker.get("opportunities") or 0)
    autonomy = float(blocker.get("autonomy_delta") or 0.0)
    href = _h(_blocked_reason_href(raw_reason))
    return (
        f'<a class="retro-blocker-row retro-action-link" target="_self" href="{href}"><div><b>!! {reason}</b>'
        f'<div class="retro-small">{required}</div></div>'
        f'<div class="retro-card-value" style="font-size:24px;">{opportunities}</div>'
        f'<div><b>+{autonomy:.0f}%</b></div></a>'
    )


def _blocked_reason_href(reason: str) -> str:
    routes = {
        "Final Approval Required": "/?view=approvals&sort=value#active-operator-table",
        "Site Login Needed": "/?page=vault",
        "Missing Email": "/?page=vault",
        "Missing Shipping": "/?page=vault",
        "Payment Routing Missing": "/?page=vault",
        "Human Verification": "/?view=approvals&sort=value#active-operator-table",
        "External Wait": "/?view=execution&sort=updated#active-operator-table",
        "Legal Restriction": "/?view=approvals&sort=value#active-operator-table",
    }
    return routes.get(reason, "/?view=blocked&sort=readiness#active-operator-table")


def _retro_table_preview_html(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            cq.execution_status,
            cq.input_status,
            cq.required_user_action,
            cq.next_action,
            cq.expected_value_usd,
            o.title,
            o.root_domain,
            o.source_name
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
        ORDER BY
            CASE
                WHEN cq.execution_status = 'Ready To Accept' THEN 0
                WHEN cq.input_status = 'ready_for_ai_work' THEN 1
                WHEN cq.execution_status = 'AI Working' THEN 2
                ELSE 3
            END,
            COALESCE(cq.fastest_gain_score, 0) DESC,
            cq.updated_at DESC
        LIMIT 8
        """
    ).fetchall()
    body = ""
    for row in rows:
        item = dict(row)
        readiness = _retro_readiness_label(item)
        status = str(item.get("execution_status") or item.get("status") or "")
        need = _retro_need_label(item)
        next_action = _short_text(item.get("next_action") or item.get("required_user_action") or "Prepare", 34)
        title = _short_text(item.get("title") or "Untitled", 46)
        domain = _short_text(item.get("root_domain") or item.get("source_name") or "local", 24)
        body += (
            "<tr>"
            f"<td>{int(item.get('id') or 0)}</td>"
            f"<td>{_h(status)}</td>"
            f"<td>{_h(title)}</td>"
            f"<td>{_h(domain)}</td>"
            f"<td>{_h(need)}</td>"
            f"<td>{_h(next_action)}</td>"
            f"<td>{_h(readiness)}</td>"
            "</tr>"
        )
    if not body:
        body = '<tr><td colspan="7">No active queue rows yet.</td></tr>'
    return (
        '<div class="retro-table-shell">'
        '<div class="retro-tabs">'
        '<a class="retro-tab retro-action-link active" target="_self" href="/?view=opportunities">Opportunities</a>'
        '<a class="retro-tab retro-action-link" target="_self" href="/?view=claim_queue">Claim Queue</a>'
        '<a class="retro-tab retro-action-link" target="_self" href="/?view=sources">Sources</a>'
        '<a class="retro-tab retro-action-link" target="_self" href="/?view=approvals&sort=value#active-operator-table">Approvals</a>'
        '<a class="retro-tab retro-action-link" target="_self" href="/?view=execution">Execution</a>'
        '<a class="retro-tab retro-action-link" target="_self" href="/?view=history">History</a>'
        '<a class="retro-tab retro-action-link easy-link" target="_self" href="/?page=easy">EASY</a>'
        '<div class="retro-filter">filter table...</div>'
        '</div>'
        '<div class="retro-data-wrap">'
        '<table class="retro-data-table">'
        '<thead><tr>'
        '<th style="width:48px;"><a target="_self" href="/?view=opportunities&sort=id">ID</a></th>'
        '<th style="width:112px;"><a target="_self" href="/?view=opportunities&sort=status">Status</a></th>'
        '<th><a target="_self" href="/?view=opportunities&sort=title">Title</a></th>'
        '<th style="width:130px;"><a target="_self" href="/?view=opportunities&sort=domain">Domain</a></th>'
        '<th style="width:110px;">Need</th>'
        '<th style="width:150px;"><a target="_self" href="/?view=opportunities&sort=updated">Next</a></th>'
        '<th style="width:110px;"><a target="_self" href="/?view=opportunities&sort=readiness">Autofill</a></th>'
        '</tr></thead>'
        f"<tbody>{body}</tbody>"
        "</table>"
        "</div>"
        '<div class="retro-scrollbar"><span>&lt;</span><div class="retro-scroll-track"><div class="retro-scroll-thumb"></div></div><span>&gt;</span></div>'
        "</div>"
    )


def _retro_readiness_label(item: dict[str, object]) -> str:
    execution = str(item.get("execution_status") or "")
    input_status = str(item.get("input_status") or "")
    if execution == "Ready To Accept":
        return "READY"
    if input_status == "ready_for_ai_work":
        return "READY"
    if input_status == "needs_connect":
        return "NEEDS LOGIN"
    if input_status.startswith("missing"):
        return "PARTIAL"
    if input_status == "final_approval_required":
        return "BLOCKED"
    return "PARTIAL"


def _retro_need_label(item: dict[str, object]) -> str:
    input_status = str(item.get("input_status") or "")
    action = str(item.get("required_user_action") or "")
    if input_status == "needs_connect":
        return "login"
    if "shipping" in input_status or action == "provide_shipping":
        return "shipping"
    if "payout" in input_status or action == "provide_payout":
        return "payout"
    if input_status == "ready_for_ai_work":
        return "none"
    if input_status == "final_approval_required":
        return "approval"
    return action or "approval"


def _h(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _short_text(value: object, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


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


def show_autonomous_work_summary(summary: object) -> None:
    data = summary.to_dict() if hasattr(summary, "to_dict") else {}
    if not data or not int(data.get("scanned", 0) or 0):
        return
    with st.expander("Autonomous Work Pass", expanded=False):
        _show_work_summary_metrics(summary)


def _show_work_summary_metrics(summary: object) -> None:
    data = summary.to_dict() if hasattr(summary, "to_dict") else {}
    if not data or not int(data.get("scanned", 0) or 0):
        return
    cols = st.columns(6)
    cols[0].metric("Scanned", data.get("scanned", 0))
    cols[1].metric("Safe Packets", data.get("safe_packets_prepared", 0))
    cols[2].metric("Advanced", data.get("approved_items_advanced", data.get("ai_work_advanced", 0)))
    cols[3].metric("Final Approval Ready", data.get("final_approval_ready", data.get("ready_for_approval", 0)))
    cols[4].metric("Live Submit Staged", data.get("live_submit_staged", 0))
    cols[5].metric("Needs Connect", data.get("blocked_connector", data.get("blocked_connectors", 0)))
    missing_count = data.get("blocked_missing_input", data.get("blocked_missing_fields", 0))
    if missing_count:
        st.caption(f"Missing-input blockers held: {missing_count}")
    if data.get("blocked_sensitive"):
        st.caption(f"Sensitive/manual blockers held: {data['blocked_sensitive']}")
    if data.get("input_synced") is not None:
        st.caption(
            "Synced: "
            f"inputs={data.get('input_synced', 0)}, "
            f"destinations={data.get('destination_synced', 0)}, "
            f"dependencies={data.get('dependency_synced', 0)}."
        )
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
            cols = st.columns([2, 3.2, 1.2, 1.3, 1.5, 1.4])
            cols[0].markdown(f"**{blocker['reason']}**")
            cols[1].write(f"Required action: {blocker['required_action']}")
            cols[2].metric("Unlocks", int(blocker["opportunities"]))
            cols[3].metric("Autonomy", f"+{float(blocker['autonomy_delta']):.1f}%")
            cols[4].write(f"Confidence: {blocker['confidence_level']}")
            cols[5].link_button(
                "Open Action",
                _blocked_reason_href(str(blocker.get("reason") or "")),
                use_container_width=True,
            )
            affected = blocker.get("affected_opportunities") or []
            if affected:
                st.caption("Affected opportunities: " + "; ".join(str(item) for item in affected[:6]))
            st.caption(f"Source of calculation: {blocker.get('source_of_calculation', 'Dependency graph from current queue rows')}")


def autorun_blocked_reasons(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = rows_for_action_center(conn)
    context = load_effective_user_context()
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
            WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
              AND (
                   cq.input_status = 'ready_for_ai_work'
                OR cq.execution_status IN ('Execution Queue', 'Ready To Accept')
              )
            """,
        ),
        "ai_executing": _count_sql(
            conn,
            """
            SELECT COUNT(*) FROM claim_queue cq
            WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
              AND cq.execution_status = 'AI Working'
            """,
        ),
        "waiting_approval": _count_sql(
            conn,
            """
            SELECT COUNT(*) FROM claim_queue cq
            WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid', 'Submitted', 'Processing')
              AND (
                   cq.input_status = 'final_approval_required'
                OR cq.status IN ('Needs Approval', 'Connect Needed')
              )
            """,
        ),
        "paused": _count_sql(
            conn,
            """
            SELECT COUNT(*) FROM claim_queue cq
            WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid', 'Submitted', 'Processing')
              AND (
                   cq.execution_status = 'Paused Awaiting Input'
                OR cq.input_status IN ('missing_shipping', 'missing_payout', 'needs_connect', 'blocked')
              )
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
            WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid', 'Submitted', 'Processing')
              AND (
                   cq.input_status = 'final_approval_required'
                OR {sensitive_clause}
              )
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
    context = load_effective_user_context()
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


def show_user_profile_autofill_vault(conn: sqlite3.Connection, standalone: bool = True) -> None:
    context = USER_CONTEXT_STORE.load()
    completeness = compute_completeness(context)
    dependencies = global_input_dependency_map(rows_for_action_center(conn))

    with st.container():
        title_cols = st.columns([4, 1])
        title_cols[0].markdown("**User Context / Autofill Profile**")
        if standalone and title_cols[1].button("Close Vault", use_container_width=True):
            st.session_state["show_vault"] = False
            st.session_state["user_profile_vault_open"] = False
            st.rerun()
        elif not standalone:
            with title_cols[1]:
                _dashboard_escape_button("Dashboard")

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
                st.info(
                    "Credential Sign-In, External Connectors, and Submit Consent now live in their own Vault page tabs "
                    "so those controls function outside this safe profile form."
                )
                st.link_button("Open Vault Sign-In / Connectors", "/?page=vault", use_container_width=True)

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
    context = load_effective_user_context()
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
        if st.button("Create encrypted credential vault", key="credential_vault_create_button"):
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
        if st.button("Unlock credential vault", key="credential_vault_unlock_button"):
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
    if cols[0].button("Save encrypted credential", key="credential_vault_save_button"):
        try:
            vault.save_record(key, label=label, username=username, password=password, login_url=login_url, notes=notes)
            st.success("Credential encrypted and saved.")
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))
    delete_options = [""] + [record.key for record in records]
    delete_key = cols[1].selectbox("Delete credential", options=delete_options, key="credential_delete_key")
    if cols[1].button("Delete selected credential", key="credential_vault_delete_button"):
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
            cols[1].caption(f"Provider URL: {provider.owner_link_url}")
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
    if st.button("Save external authorizations", key="external_authorizations_save_button"):
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

    st.markdown("**Live Connector Login Sessions**")
    st.caption(
        "Open a real Chrome/Edge profile for a provider, sign in once, then the entity can reuse that local session for "
        "approved Live Assist navigation. No test-browser fallback is used for connector login, and no plaintext "
        "passwords are stored."
    )
    session_rows = live_connector_rows(ROOT_DIR)
    show_dataframe(pd.DataFrame([
        {
            "provider": row["label"],
            "category": row["category"],
            "profile exists": row["profile_exists"],
            "state": row.get("state", ""),
            "last url": row.get("last_url", ""),
            "note": row.get("note", ""),
        }
        for row in session_rows
    ]))
    launch_options = {provider.key: f"{provider.label} - {provider.category}" for provider in LIVE_CONNECTOR_PROVIDERS}
    launch_key = st.selectbox(
        "Connector to log into",
        options=list(launch_options.keys()),
        format_func=lambda key: launch_options[key],
        key="live_connector_launch_key",
    )
    launch_provider = next(provider for provider in LIVE_CONNECTOR_PROVIDERS if provider.key == launch_key)
    launch_cols = st.columns([1.4, 1, 2])
    launch_cols[0].caption(f"Provider URL: {launch_provider.login_url}")
    if launch_cols[1].button("Launch Real Chrome Login", key="launch_live_connector_session", use_container_width=True):
        proc = _start_live_connector_session(launch_key)
        st.success(f"Real browser connector login launched for {launch_provider.label} as PID {proc.pid}.")
        st.rerun()
    launch_cols[2].caption(
        "After login succeeds in real Chrome/Edge, return here and mark the provider Authorized above. Close the browser window when finished."
    )


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
    context = load_effective_user_context()
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
    context = load_effective_user_context()
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
    context = load_effective_user_context()
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
        show_final_approval_packet(dict(details))
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


def show_final_approval_packet(claim: dict[str, object]) -> None:
    packet = build_final_approval_packet(claim, load_effective_user_context())
    st.markdown("**Final Approval Packet**")
    top_cols = st.columns(3)
    top_cols[0].write(f"Source URL: {packet.source_url or 'Not specified'}")
    top_cols[1].write(f"Destination: {packet.destination}")
    top_cols[2].write(f"Action: {packet.final_action_type.replace('_', ' ').title()}")

    st.markdown("**Exact Fields AI Prepared**")
    if packet.exact_fields_ai_prepared:
        show_dataframe(pd.DataFrame(
            [
                {
                    "field": field,
                    "preview": packet.prepared_value_preview.get(field, "available"),
                }
                for field in packet.exact_fields_ai_prepared
            ]
        ))
    else:
        st.write("No safe autofill fields prepared for this item.")

    st.markdown("**What Will Be Submitted**")
    st.write(packet.what_will_be_submitted)

    verify_cols = st.columns(2)
    with verify_cols[0]:
        st.markdown("**What User Must Verify**")
        for item in packet.what_user_must_verify:
            st.write(f"- {item}")
    with verify_cols[1]:
        st.markdown("**Risk / Safety Flags**")
        for flag in packet.risk_safety_flags:
            st.write(f"- {flag}")


def show_ready_to_accept_packets(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT cq.*, o.title, o.url
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status = 'Ready to Accept'
           OR cq.execution_status = 'Ready To Accept'
        ORDER BY cq.fastest_gain_score DESC, cq.updated_at DESC
        LIMIT 100
        """
    ).fetchall()
    if not rows:
        return
    st.markdown("**Ready To Accept - Final Approval Packets**")
    show_vault_instant_accept_lane([dict(row) for row in rows])
    labels = {
        int(row["id"]): f"{row['id']} - {row['title'][:100]}"
        for row in rows
    }
    selected_id = st.selectbox(
        "Ready item packet",
        options=list(labels.keys()),
        format_func=lambda item_id: labels[item_id],
        key="ready_to_accept_packet_select",
    )
    selected = next(row for row in rows if int(row["id"]) == int(selected_id))
    show_final_approval_packet(dict(selected))
    packet_action = st.selectbox(
        "Packet action",
        ["Approve Final Step", "Reject", "Later"],
        key="ready_to_accept_packet_action",
    )
    cols = st.columns([1, 3])
    if cols[0].button("Apply packet action", key="ready_to_accept_packet_apply"):
        action_type = "final_submit"
        note = apply_final_approval_action(conn, int(selected_id), action_type, packet_action)
        st.success(note)
        st.rerun()
    cols[1].caption("Dry Run / Live Assist only. This does not submit externally.")


def show_vault_instant_accept_lane(rows: list[dict[str, object]]) -> None:
    candidates = [row for row in rows if _is_vault_instant_accept_candidate(row)]
    if not candidates:
        st.caption("No low-risk Vault Instant Accept packets are ready yet. Add reusable Vault info to unlock this lane.")
        return

    st.markdown("**Vault Instant Accept Lane**")
    st.caption(
        "One-click owner approval for low-risk prepared packets. This only updates the local queue to Submitted/processing; "
        "payment, legal, tax, identity, login, purchase, and wallet-signing items are excluded."
    )
    preview_rows = []
    for row in candidates[:8]:
        packet = build_final_approval_packet(row, load_effective_user_context())
        preview_rows.append(
            {
                "id": row.get("id"),
                "opportunity": row.get("title"),
                "value": row.get("expected_value_usd"),
                "prepared fields": ", ".join(packet.exact_fields_ai_prepared) or "official path / packet",
                "next": row.get("next_action") or packet.what_will_be_submitted,
            }
        )
    show_dataframe(pd.DataFrame(preview_rows))
    st.markdown('<div class="approval-stack">', unsafe_allow_html=True)
    for row in candidates[:5]:
        claim_id = int(row.get("id") or 0)
        title = html.escape(_short_text(row.get("title") or "Untitled", 80))
        value = _safe_float(row.get("expected_value_usd"))
        st.markdown(
            f"""
            <div class="approval-card">
              <div class="approval-card-main">
                <div class="approval-card-title">#{claim_id} {title}</div>
                <div class="approval-card-meta">vault-ready | low-risk final submit packet | value ${value:,.2f}</div>
                <div class="approval-card-why">Reusable Vault/context data can support this packet. Owner approval is still explicit.</div>
              </div>
              <div class="approval-card-actions">
                <a class="retro-tool retro-action-link" target="_self" href="/?view=approvals&sort=value#active-operator-table">Review</a>
                <a class="retro-tool retro-action-link" target="_self" href="/?approval_action=approve&claim_id={claim_id}&final_action_type=final_submit">Instant Accept</a>
                <a class="retro-tool retro-action-link" target="_self" href="/?approval_action=later&claim_id={claim_id}&final_action_type=final_submit">Later</a>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _is_vault_instant_accept_candidate(row: dict[str, object]) -> bool:
    if str(row.get("input_status") or "") != "ready_for_ai_work":
        return False
    if str(row.get("execution_status") or "") != "Ready To Accept" and str(row.get("status") or "") != "Ready to Accept":
        return False
    sensitive = set(_csv_values(row.get("sensitive_inputs")))
    blocked_sensitive = {
        "identity_sensitive",
        "student_verification",
        "business_info_sensitive",
        "tax_info",
        "purchase_required",
        "legal_attestation",
        "payment_authorization",
        "wallet_signing",
        "platform_login",
    }
    if sensitive & blocked_sensitive:
        return False
    text = " ".join(str(row.get(key) or "") for key in ["title", "next_action", "claim_instructions", "safety_notes"]).lower()
    blocked_terms = ["identity", "kyc", "tax", "w-9", "1099", "purchase", "payment authorization", "wallet signing", "legal agreement", "login", "sign in"]
    return not any(term in text for term in blocked_terms)


def _csv_values(value: object) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def show_browser_execution_queue(conn: sqlite3.Connection) -> None:
    rows = rows_for_browser_execution(conn)
    candidate_rows = rows_for_browser_execution_candidates(conn)
    st.markdown("**Browser Execution Queue**")
    st.caption(
        "Live-test structure for staged claims. Dry Run inspects mapping only; Live Assist may fill safe fields; "
        "Live Submit requires explicit consent and still stops on sensitive screens."
    )
    if rows:
        selectable_rows = rows
        st.caption("Showing submitted/processing rows staged for browser execution.")
    else:
        selectable_rows = candidate_rows
        st.info("No submitted or processing rows are staged yet. Showing Ready To Accept / AI-prepared candidates for live inspection.")
    if not selectable_rows:
        st.write("No browser execution candidates are available yet.")
        _show_browser_execution_history()
        return

    control = load_autorun_control()
    execution_mode = str(control.get("execution_mode") or "Dry Run")
    context = load_effective_user_context()
    labels = {int(row["id"]): f"{row['id']} - {row['title'][:100]}" for row in selectable_rows}
    selected_id = st.selectbox(
        "Browser execution item",
        options=list(labels.keys()),
        format_func=lambda item_id: labels[item_id],
        key="browser_execution_item_select",
    )
    selected = next(row for row in selectable_rows if int(row["id"]) == int(selected_id))
    plan = build_browser_execution_plan(dict(selected), context, execution_mode)
    live_session = build_live_assist_session(dict(selected), context, execution_mode=execution_mode)
    inspection_key = f"browser_form_inspection_{plan.claim_queue_id}"
    cols = st.columns(5)
    cols[0].metric("Mode", execution_mode)
    cols[1].metric("Prepared Fields", len(plan.prepared_fields))
    cols[2].metric("Stop Conditions", len(plan.stop_conditions))
    cols[3].metric("Claim", plan.claim_queue_id)
    cols[4].metric("Queue Stage", str(selected.get("execution_status") or selected.get("status") or "Candidate"))

    driver = browser_driver_status()
    driver_key = f"browser_driver_probe_{plan.claim_queue_id}"
    driver_cols = st.columns([1, 1, 3])
    driver_cols[0].metric("JS Browser", "Ready" if driver.available else "Offline")
    driver_cols[1].metric("Driver", driver.driver.replace(" Chromium", ""))
    driver_cols[2].caption(
        f"{driver.note} Rendered probes are inspection-only: no login bypass, no captcha bypass, no external submit."
    )
    if driver_cols[0].button("JS Probe", key=f"browser_driver_probe_button_{plan.claim_queue_id}", disabled=not driver.available):
        st.session_state[driver_key] = inspect_with_playwright(plan.official_link).to_dict()
        record_browser_execution_run(ROOT_DIR, plan, "js_browser_probe", st.session_state[driver_key].get("note", "JS browser probe recorded."))
        st.rerun()
    if st.session_state.get(driver_key):
        probe = st.session_state[driver_key]
        st.caption(str(probe.get("note") or "JS browser probe complete."))
        show_dataframe(pd.DataFrame([{
            "reachable": probe.get("reachable"),
            "final_url": probe.get("final_url") or probe.get("url"),
            "title": probe.get("title"),
            "forms_found": probe.get("forms_found"),
            "buttons_found": probe.get("buttons_found"),
            "blocked_reason": probe.get("blocked_reason"),
        }]))
        cta_candidates = probe.get("cta_candidates") or []
        if cta_candidates:
            show_dataframe(pd.DataFrame(cta_candidates))

    st.markdown("**Execution Plan**")
    show_dataframe(pd.DataFrame([{
        "opportunity": plan.opportunity_title,
        "official_link": plan.official_link,
        "next_step": plan.next_step,
        "allowed_actions": ", ".join(plan.allowed_actions),
        "blocked_actions": ", ".join(plan.blocked_actions),
    }]))

    st.markdown("**Prepared Field Map**")
    if plan.prepared_fields:
        show_dataframe(pd.DataFrame([
            {"field": field, "preview": plan.field_preview.get(field, "available")}
            for field in plan.prepared_fields
        ]))
    else:
        st.write("No prepared fields available.")

    st.markdown("**Live Assist Session Packet**")
    show_dataframe(pd.DataFrame([{
        "readiness": live_session.readiness,
        "selected_path": live_session.selected_path,
        "safe_fields": ", ".join(live_session.safe_fields_to_prefill),
        "missing_fields": ", ".join(live_session.missing_fields),
        "connector_needed": live_session.connector_needed,
        "next_action": live_session.next_action,
    }]))
    assist_cols = st.columns(2)
    with assist_cols[0]:
        st.markdown("**AI Can Do Now**")
        for item in live_session.ai_can_do_now:
            st.write(f"- {item}")
    with assist_cols[1]:
        st.markdown("**Owner Must Do / Approve**")
        for item in live_session.owner_must_do:
            st.write(f"- {item}")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Dry Run Checklist**")
        for item in plan.dry_run_checklist:
            st.write(f"- {item}")
    with col_b:
        st.markdown("**Stop Conditions**")
        if plan.stop_conditions:
            for item in plan.stop_conditions:
                st.write(f"- {item}")
        else:
            st.write("No stop terms detected in stored plan text.")

    st.markdown("**Live Form Inspector**")
    inspect_cols = st.columns([1, 1, 2])
    if inspect_cols[0].button("Inspect Official Form Now", key="browser_live_inspect"):
        inspection = inspect_official_form(plan, context)
        st.session_state[inspection_key] = inspection.to_dict()
        status = "live_form_inspected" if inspection.can_live_assist else "blocked_or_manual_inspection"
        record_browser_execution_run(ROOT_DIR, plan, status, inspection.note)
        st.rerun()
    if inspect_cols[1].button("Clear Inspection", key="browser_clear_live_inspect"):
        st.session_state.pop(inspection_key, None)
        st.rerun()
    inspect_cols[2].caption("This fetches and parses the official page, maps safe Vault fields, and never submits externally.")
    inspection_payload = st.session_state.get(inspection_key)
    if inspection_payload:
        _show_form_inspection_result(inspection_payload)

    action_cols = st.columns([1, 1, 1, 2])
    if action_cols[0].button("Record Dry Run Inspect", key="browser_record_dry_run"):
        record_browser_execution_run(ROOT_DIR, plan, "dry_run_inspected", "Dry Run inspection recorded. No external submit.")
        st.success("Dry Run inspection recorded.")
        st.rerun()
    if action_cols[1].button("Pause Need User", key="browser_pause_need_user"):
        _update_browser_execution_status(conn, plan.claim_queue_id, "Needs Approval", "Paused Awaiting Input", "Paused for owner review from browser execution queue.")
        record_browser_execution_run(ROOT_DIR, plan, "paused_need_user", "Paused for owner review.")
        st.success("Paused for owner review.")
        st.rerun()
    if action_cols[2].button("Mark Processing", key="browser_mark_processing"):
        _update_browser_execution_status(conn, plan.claim_queue_id, "Processing", "Processing", "Browser execution remains staged for live test.")
        record_browser_execution_run(ROOT_DIR, plan, "processing", "Browser execution staged.")
        st.success("Marked processing.")
        st.rerun()
    if plan.official_link:
        action_cols[3].link_button("Open Official Link", plan.official_link, use_container_width=True)

    st.markdown("**Consent-Gated Real Browser Execution**")
    consent = SubmissionConsentStore.for_root(ROOT_DIR).consent_for(plan.claim_queue_id)
    execute_cols = st.columns([1.2, 1.2, 2.6])
    consent_label = "Recorded" if consent.get("allowed") else "Missing"
    execute_cols[0].metric("Final Submit Consent", consent_label)
    execute_cols[1].metric("External Submit", "Armed" if execution_mode == "Live Submit With Final Approval" else "Dry/Assist")
    execute_cols[2].caption(
        "Attempts only simple, low-risk, already-approved HTML forms. It hard-stops on login, captcha, payment, "
        "purchase, legal/tax/identity, wallet signing, password, file upload, or unmapped required fields."
    )
    result_key = f"browser_execution_result_{plan.claim_queue_id}"
    if st.button("Execute Consented Safe Form", key="browser_execute_safe_form", use_container_width=True):
        connector_profile = profile_for_url(ROOT_DIR, plan.official_link)
        result = execute_safe_official_form(
            plan,
            context,
            consent,
            submit_external=True,
            browser_profile_dir=connector_profile,
        )
        st.session_state[result_key] = result.to_dict()
        _apply_browser_execution_result(conn, plan.claim_queue_id, result)
        record_browser_execution_run(ROOT_DIR, plan, result.status, result.note)
        st.rerun()
    if st.session_state.get(result_key):
        _show_browser_execution_result(st.session_state[result_key])

    _show_browser_execution_history()


def _show_form_inspection_result(result: dict[str, object]) -> None:
    metric_cols = st.columns(6)
    metric_cols[0].metric("Reachable", "Yes" if result.get("reachable") else "No")
    metric_cols[1].metric("HTTP", str(result.get("status_code") or "n/a"))
    metric_cols[2].metric("Forms", int(result.get("forms_found") or 0))
    metric_cols[3].metric("Mapped", len(result.get("mapped_fields") or []))
    metric_cols[4].metric("Missing", len(result.get("missing_fields") or []))
    metric_cols[5].metric("Live Assist", "Ready" if result.get("can_live_assist") else "Blocked")
    st.caption(str(result.get("note") or ""))
    st.write(f"Inspected URL: {result.get('url') or 'Not available'}")

    stop_flags = result.get("stop_flags") or []
    if stop_flags:
        st.warning("Stop flags detected: " + ", ".join(str(flag) for flag in stop_flags))
    missing_fields = result.get("missing_fields") or []
    if missing_fields:
        st.info("Missing Vault fields: " + ", ".join(str(field) for field in missing_fields))
    cta_links = result.get("cta_links") or []
    if cta_links:
        st.markdown("**Detected Claim / Apply Links**")
        show_dataframe(pd.DataFrame(cta_links))

    fields = result.get("fields") or []
    if fields:
        st.markdown("**Detected Field Map**")
        show_dataframe(pd.DataFrame(fields))
    else:
        st.write("No visible form fields were detected on this page.")


def _show_browser_execution_result(result: dict[str, object]) -> None:
    metric_cols = st.columns(6)
    metric_cols[0].metric("Attempted", "Yes" if result.get("attempted") else "No")
    metric_cols[1].metric("Submitted", "Yes" if result.get("submitted") else "No")
    metric_cols[2].metric("Status", str(result.get("status") or "n/a"))
    metric_cols[3].metric("HTTP", str(result.get("response_status_code") or "n/a"))
    metric_cols[4].metric("Mapped", len(result.get("mapped_fields") or []))
    metric_cols[5].metric("Stops", len(result.get("stop_flags") or []))
    note = str(result.get("note") or "")
    if result.get("submitted"):
        st.success(note)
    elif result.get("stop_flags") or result.get("missing_fields"):
        st.warning(note)
    else:
        st.info(note)
    st.caption(str(result.get("next_action") or ""))
    if result.get("proof_or_reference_note"):
        st.write(f"Proof/reference: {result.get('proof_or_reference_note')}")
    if result.get("stop_flags"):
        st.write("Stop flags: " + ", ".join(str(item) for item in result.get("stop_flags") or []))
    if result.get("missing_fields"):
        st.write("Missing fields: " + ", ".join(str(item) for item in result.get("missing_fields") or []))
    payload_preview = result.get("payload_preview") or {}
    if payload_preview:
        st.markdown("**Redacted Submit Payload Preview**")
        show_dataframe(pd.DataFrame([{"field": key, "preview": value} for key, value in dict(payload_preview).items()]))


def _show_browser_execution_history() -> None:
    history = BrowserExecutionStore.for_root(ROOT_DIR).recent()
    st.markdown("**Browser Execution Run History**")
    if not history:
        st.write("No browser execution runs recorded yet.")
        return
    show_dataframe(pd.DataFrame(history))


def _apply_browser_execution_result(
    conn: sqlite3.Connection,
    claim_queue_id: int,
    result: object,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    submitted = bool(getattr(result, "submitted", False))
    existing = conn.execute(
        "SELECT status, execution_status, action_engine_json FROM claim_queue WHERE id=?",
        (claim_queue_id,),
    ).fetchone()
    if submitted:
        status = "Submitted"
        execution_status = "Processing"
    else:
        current_status = str(existing["status"] or "") if existing else ""
        status = current_status if current_status in {"Submitted", "Processing", "Ready to Accept"} else "Needs Approval"
        execution_status = "Paused Awaiting Input"
    merged_payload = _merge_action_engine_payload(
        existing["action_engine_json"] if existing else "",
        "browser_execution",
        result.to_dict() if hasattr(result, "to_dict") else dict(result),
    )
    conn.execute(
        """
        UPDATE claim_queue
        SET
            status=?,
            execution_status=?,
            next_action=?,
            human_input_needed=?,
            ai_work_completed=COALESCE(NULLIF(?, ''), ai_work_completed),
            action_engine_json=?,
            last_execution_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            status,
            execution_status,
            getattr(result, "next_action", ""),
            "" if submitted else getattr(result, "next_action", ""),
            getattr(result, "note", ""),
            merged_payload,
            now,
            now,
            claim_queue_id,
        ),
    )
    conn.commit()


def _merge_action_engine_payload(existing_json: object, key: str, payload: dict[str, object]) -> str:
    try:
        existing = json.loads(str(existing_json or "{}"))
    except json.JSONDecodeError:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    nested_payload = payload.get(key) if isinstance(payload.get(key), dict) else payload
    existing[key] = nested_payload
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    return json.dumps(existing, ensure_ascii=True, sort_keys=True)


def _update_browser_execution_status(
    conn: sqlite3.Connection,
    claim_queue_id: int,
    status: str,
    execution_status: str,
    note: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE claim_queue
        SET status=?, execution_status=?, next_action=?, updated_at=?
        WHERE id=?
        """,
        (status, execution_status, note, now, claim_queue_id),
    )
    conn.commit()


def show_global_input_dependency_map(dependencies: list[object]) -> None:
    st.markdown("**Global Input Dependency Map**")
    if not dependencies:
        st.write("No repeated missing inputs are blocking the current queue.")
        return
    render_count = int(st.session_state.get("_global_dependency_map_render_count", 0)) + 1
    st.session_state["_global_dependency_map_render_count"] = render_count
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
    for index, dependency in enumerate(dependencies[:10]):
        cols = st.columns([3, 2, 2])
        cols[0].write(f"{dependency.display_name}: {dependency.prompt}")
        cols[1].write(f"Unlock score {dependency.unlock_score:.2f}")
        cols[2].button(
            f"Resolve {dependency.display_name}",
            key=f"resolve_dependency_{render_count}_{index}_{dependency.input_key}",
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
    execution_status = _execution_status_after_final_action(status, action)
    now = datetime.now(timezone.utc).isoformat()
    opportunity = conn.execute(
        "SELECT opportunity_id FROM claim_queue WHERE id=?",
        (claim_queue_id,),
    ).fetchone()
    conn.execute(
        """
        UPDATE claim_queue
        SET status=?, execution_status=?, next_action=?, updated_at=?
        WHERE id=?
        """,
        (status, execution_status, note, now, claim_queue_id),
    )
    if opportunity:
        conn.execute(
            "UPDATE opportunities SET status=?, updated_at=? WHERE id=?",
            (status, now, opportunity["opportunity_id"]),
        )
    live_note = _stage_live_submit_after_safe_approval(conn, claim_queue_id, final_action_type, action)
    if live_note:
        note = f"{note} {live_note}"
    conn.commit()
    SQLiteStore(DB_PATH).normalize_required_inputs()
    return note


def _stage_live_submit_after_safe_approval(
    conn: sqlite3.Connection,
    claim_queue_id: int,
    final_action_type: str,
    action: str,
) -> str:
    control = load_autorun_control()
    execution_mode = str(control.get("execution_mode") or "Dry Run")
    if action != "Approve Final Step" or final_action_type != "final_submit":
        return ""
    if execution_mode != "Live Submit With Final Approval":
        return ""

    details = load_claim_detail(conn, claim_queue_id)
    if not details:
        return "Live-submit staging skipped: claim detail could not be loaded."

    detail_dict = dict(details)
    allowed, reason = can_live_submit(
        final_action_type,
        str(detail_dict.get("risk_level") or ""),
        explicit_terms_checked=True,
    )
    if not allowed:
        return f"Live-submit staging skipped: {reason}"

    consent_store = SubmissionConsentStore.for_root(ROOT_DIR)
    existing_consent = consent_store.consent_for(claim_queue_id)
    if not existing_consent.get("allowed"):
        consent_store.save_consent(
            new_consent(
                claim_queue_id,
                execution_mode,
                "Owner approved this low-risk final-submit packet from the dashboard fast lane.",
            )
        )
    live_result = evaluate_live_submit(detail_dict, consent_store.consent_for(claim_queue_id))
    if not live_result.allowed:
        return f"Live-submit staging skipped: {live_result.note}"

    _apply_live_submit_result(conn, claim_queue_id, live_result)
    try:
        plan = browser_execution.build_browser_execution_plan(
            detail_dict,
            load_effective_user_context(),
            execution_mode,
        )
        browser_execution.record_browser_execution_run(
            ROOT_DIR,
            plan,
            "live_submit_staged",
            live_result.note,
        )
    except Exception as exc:  # noqa: BLE001
        return f"Live-submit staged; browser packet logging skipped: {exc}"
    return "Live-submit staged for browser execution."


def _execution_status_after_final_action(status: str, action: str) -> str:
    if action == "Reject":
        return "Rejected"
    if action in {"Later", "Needs More Info"}:
        return "Paused Awaiting Input"
    if status == "Submitted":
        return "Processing"
    if status == "Connect Needed":
        return "Paused Awaiting Input"
    if status == "Approved":
        return "Owner Action Required"
    return status or "Execution Queue"


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
