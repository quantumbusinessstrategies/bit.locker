from __future__ import annotations

import re
from typing import Any


SAFE_AUTOFILL_FIELDS = {
    "email",
    "phone",
    "shipping.full_name",
    "shipping.address_line_1",
    "shipping.address_line_2",
    "shipping.city",
    "shipping.state",
    "shipping.zip",
    "shipping.country",
    "payouts.paypal_email",
    "payouts.stripe_email",
    "crypto_wallets.btc_address",
    "crypto_wallets.eth_address",
    "crypto_wallets.sol_address",
    "crypto_wallets.usdc_address",
    "accounts.github_username",
    "accounts.google_email",
    "accounts.microsoft_email",
    "accounts.apple_email",
    "accounts.amazon_email",
    "accounts.paypal_email",
    "business.business_name",
    "business.website_domain",
    "business.founder_name",
    "business.company_description",
    "business.startup_stage",
    "business.industry",
    "profile.name",
    "profile.email",
    "profile.phone",
}

SENSITIVE_BLOCKERS = {
    "identity_sensitive",
    "tax_info",
    "payment_authorization",
    "purchase_required",
    "legal_attestation",
    "wallet_signing",
}


def is_safe_autofill_field(field_name: str) -> bool:
    return field_name in SAFE_AUTOFILL_FIELDS


def final_approval_required_for(item: dict[str, Any]) -> bool:
    text = _blob(item)
    if any(blocker in text for blocker in SENSITIVE_BLOCKERS):
        return True
    sensitive_phrases = [
        "identity verification",
        "verify identity",
        "purchase",
        "payment authorization",
        "legal agreement",
        "accept terms",
        "wallet signing",
        "sign transaction",
    ]
    return any(phrase in text for phrase in sensitive_phrases) or bool(re.search(r"\b(tax|w-?9|1099)\b", text))


def safe_next_action(can_autofill: bool, final_approval_required: bool, connector_needed: str) -> str:
    if final_approval_required:
        return "Prepare safe draft fields only; wait for explicit final approval before sensitive action."
    if connector_needed:
        return f"Ask owner to connect or confirm {connector_needed}, then continue safe preparation."
    if can_autofill:
        return "Stage safe autofill values from User Context; do not submit without final approval."
    return "Collect missing reusable User Context before continuing."


def _blob(item: dict[str, Any]) -> str:
    keys = [
        "status",
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
        "official_link",
        "final_acceptance_step",
        "required_inputs",
        "missing_inputs",
        "sensitive_inputs",
    ]
    return " ".join(str(item.get(key) or "") for key in keys).lower()
