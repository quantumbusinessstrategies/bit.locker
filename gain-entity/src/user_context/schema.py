from __future__ import annotations

from copy import deepcopy
from typing import Any


PROFILE_FIELDS = ["name", "email", "phone", "date_of_birth"]
SHIPPING_FIELDS = [
    "full_name",
    "address_line_1",
    "address_line_2",
    "city",
    "state",
    "zip",
    "country",
]
PAYOUT_FIELDS = ["paypal_email", "cashapp", "venmo", "stripe_email", "bank_label", "other_payout_note"]
CRYPTO_WALLET_FIELDS = ["btc_address", "eth_address", "sol_address", "usdc_address", "wallet_notes"]
ACCOUNT_FIELDS = [
    "github_username",
    "google_email",
    "microsoft_email",
    "tiktok_username",
    "amazon_email",
    "apple_email",
    "paypal_email",
    "paypal_connected",
    "gmail_connected",
    "github_connected",
    "microsoft_connected",
    "amazon_connected",
    "apple_connected",
    "connection_status",
    "future_connector_notes",
]
BUSINESS_FIELDS = [
    "business_name",
    "website_domain",
    "founder_name",
    "company_description",
    "startup_stage",
    "industry",
    "ein_tax_placeholder",
]
PREFERENCE_FIELDS = [
    "physical_goods",
    "cash_rewards",
    "crypto",
    "gift_cards",
    "cloud_ai_credits",
    "developer_credits",
    "creator_programs",
    "affiliate_referral",
    "startup_credits",
    "class_actions",
    "surveys",
    "beta_tests",
    "local_pickup",
    "travel_events",
    "requires_purchase",
]
AUTOMATION_LIMIT_FIELDS = [
    "allow_autofill",
    "allow_open_links",
    "allow_prepare_forms",
    "allow_connector_suggestions",
    "queue_low_risk_tasks_automatically",
    "allow_submit_without_final_approval",
    "max_out_of_pocket_spend",
    "require_final_approval_for_sensitive",
    "require_final_approval_for_submit",
    "require_final_approval_for_purchases",
    "require_final_approval_for_legal_tax_identity_wallet_payment",
]
PREFERENCE_PROFILE_MODES = [
    "Minimal Input",
    "Balanced",
    "Open To Everything",
    "Aggressive Growth",
    "Privacy Focused",
    "Custom",
]

REQUIRED_INPUTS = [
    "shipping_address",
    "email",
    "phone",
    "payout_account",
    "crypto_wallet",
    "platform_login",
    "student_verification",
    "business_info",
    "tax_info",
    "identity_sensitive",
    "legal_attestation",
    "wallet_signing",
    "purchase_required",
]

INPUT_STATUSES = [
    "ready_for_ai_work",
    "missing_shipping",
    "missing_payout",
    "needs_connect",
    "final_approval_required",
    "blocked",
]

DEFAULT_CONTEXT: dict[str, Any] = {
    "profile": {
        "name": "",
        "email": "",
        "phone": "",
        "date_of_birth": "",
    },
    "shipping": {
        "full_name": "",
        "address_line_1": "",
        "address_line_2": "",
        "city": "",
        "state": "",
        "zip": "",
        "country": "",
    },
    "payouts": {
        "paypal_email": "",
        "cashapp": "",
        "venmo": "",
        "stripe_email": "",
        "bank_label": "",
        "other_payout_note": "",
    },
    "crypto_wallets": {
        "btc_address": "",
        "eth_address": "",
        "sol_address": "",
        "usdc_address": "",
        "wallet_notes": "",
    },
    "accounts": {
        "github_username": "",
        "google_email": "",
        "microsoft_email": "",
        "tiktok_username": "",
        "amazon_email": "",
        "apple_email": "",
        "paypal_email": "",
        "paypal_connected": False,
        "gmail_connected": False,
        "github_connected": False,
        "microsoft_connected": False,
        "amazon_connected": False,
        "apple_connected": False,
        "connection_status": "",
        "future_connector_notes": "",
    },
    "business": {
        "business_name": "",
        "website_domain": "",
        "founder_name": "",
        "company_description": "",
        "startup_stage": "",
        "industry": "",
        "ein_tax_placeholder": "",
    },
    "preferences": {
        "preference_profile": "Balanced",
        "open_to_everything": False,
        "physical_goods": False,
        "cash_rewards": False,
        "crypto": False,
        "gift_cards": False,
        "cloud_ai_credits": False,
        "developer_credits": False,
        "creator_programs": False,
        "affiliate_referral": False,
        "startup_credits": False,
        "class_actions": False,
        "surveys": False,
        "beta_tests": False,
        "local_pickup": False,
        "travel_events": False,
        "requires_purchase": False,
    },
    "automation_limits": {
        "allow_autofill": False,
        "allow_open_links": False,
        "allow_prepare_forms": True,
        "allow_connector_suggestions": False,
        "queue_low_risk_tasks_automatically": False,
        "allow_submit_without_final_approval": False,
        "max_out_of_pocket_spend": 0,
        "require_final_approval_for_sensitive": True,
        "require_final_approval_for_submit": True,
        "require_final_approval_for_purchases": True,
        "require_final_approval_for_legal_tax_identity_wallet_payment": True,
    },
}


def default_user_context() -> dict[str, Any]:
    return deepcopy(DEFAULT_CONTEXT)


def merge_user_context(payload: dict[str, Any] | None) -> dict[str, Any]:
    merged = default_user_context()
    if not isinstance(payload, dict):
        return merged
    for section, defaults in DEFAULT_CONTEXT.items():
        incoming = payload.get(section)
        if isinstance(incoming, dict):
            for key in defaults:
                if key in incoming:
                    merged[section][key] = incoming[key]
    return apply_preference_profile(merged)


def apply_open_to_everything_mode(context: dict[str, Any]) -> dict[str, Any]:
    return apply_preference_profile(context)


def apply_preference_profile(context: dict[str, Any]) -> dict[str, Any]:
    preferences = context.setdefault("preferences", {})
    automation = context.setdefault("automation_limits", {})
    profile = str(preferences.get("preference_profile") or "Balanced")
    if profile == "Custom":
        _enforce_safety_gates(automation)
        return context
    if profile == "Minimal Input":
        preferences["open_to_everything"] = False
        automation["allow_autofill"] = True
        automation["allow_open_links"] = True
        automation["allow_prepare_forms"] = True
        automation["allow_connector_suggestions"] = False
        automation["queue_low_risk_tasks_automatically"] = True
    elif profile == "Aggressive Growth":
        preferences["open_to_everything"] = True
        _enable_all_categories(preferences)
        preferences["requires_purchase"] = False
        automation["allow_autofill"] = True
        automation["allow_open_links"] = True
        automation["allow_prepare_forms"] = True
        automation["allow_connector_suggestions"] = True
        automation["queue_low_risk_tasks_automatically"] = True
    elif profile == "Open To Everything" or truthy(preferences.get("open_to_everything")):
        preferences["open_to_everything"] = True
        _enable_all_categories(preferences)
        preferences["requires_purchase"] = False
        automation["allow_autofill"] = True
        automation["allow_open_links"] = True
        automation["allow_prepare_forms"] = True
        automation["allow_connector_suggestions"] = True
        automation["queue_low_risk_tasks_automatically"] = False
    elif profile == "Privacy Focused":
        preferences["open_to_everything"] = False
        automation["allow_autofill"] = False
        automation["allow_open_links"] = False
        automation["allow_prepare_forms"] = True
        automation["allow_connector_suggestions"] = False
        automation["queue_low_risk_tasks_automatically"] = False
    else:
        preferences["open_to_everything"] = False
        automation["allow_autofill"] = False
        automation["allow_open_links"] = False
        automation["allow_prepare_forms"] = True
        automation["allow_connector_suggestions"] = False
        automation["queue_low_risk_tasks_automatically"] = False
    _enforce_safety_gates(automation)
    return context


def _enable_all_categories(preferences: dict[str, Any]) -> None:
    for field in PREFERENCE_FIELDS:
        if field == "requires_purchase":
            continue
        preferences[field] = True


def _enforce_safety_gates(automation: dict[str, Any]) -> None:
    automation["allow_submit_without_final_approval"] = False
    automation["require_final_approval_for_sensitive"] = True
    automation["require_final_approval_for_submit"] = True
    automation["require_final_approval_for_purchases"] = True
    automation["require_final_approval_for_legal_tax_identity_wallet_payment"] = True


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "connected",
        "connected externally",
        "available for autofill",
        "enabled",
        "on",
    }
