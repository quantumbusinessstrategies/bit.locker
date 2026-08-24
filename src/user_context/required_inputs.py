from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from user_context.completeness import compute_completeness
from user_context.schema import truthy


FINAL_APPROVAL_INPUTS = {"tax_info", "identity_sensitive", "legal_attestation", "purchase_required", "wallet_signing"}


@dataclass(frozen=True)
class RequiredInputResult:
    required_inputs: list[str]
    available_inputs: list[str]
    missing_fields: list[str]
    sensitive_inputs: list[str]
    input_status: str
    what_ai_already_has: str
    what_user_must_provide: str
    what_ai_can_do_next: str
    final_approval_needed: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True)


def detect_required_inputs(item: dict[str, Any], user_context: dict[str, Any]) -> RequiredInputResult:
    required = _detect_required_inputs(item)
    available, missing = _compare_with_context(required, user_context)
    sensitive = sorted(required & FINAL_APPROVAL_INPUTS)
    status = _input_status(required, available, missing, sensitive, user_context)

    return RequiredInputResult(
        required_inputs=sorted(required),
        available_inputs=sorted(available),
        missing_fields=missing,
        sensitive_inputs=sensitive,
        input_status=status,
        what_ai_already_has=_ai_has_text(available),
        what_user_must_provide=_user_must_provide_text(missing, sensitive),
        what_ai_can_do_next=_ai_next_text(status, item, user_context),
        final_approval_needed=_final_approval_text(sensitive, item, user_context),
    )


def result_payload(result: RequiredInputResult) -> dict[str, Any]:
    badge = input_status_badge(result.input_status)
    return {
        "input_status": result.input_status,
        "required_inputs": ", ".join(result.required_inputs),
        "available_inputs": ", ".join(result.available_inputs),
        "missing_inputs": ", ".join(result.missing_fields),
        "sensitive_inputs": ", ".join(result.sensitive_inputs),
        "input_summary": json.dumps({**result.to_dict(), "readiness_badge": badge}, ensure_ascii=True, sort_keys=True),
    }


def input_status_badge(input_status: str) -> str:
    return {
        "ready_for_ai_work": "Ready",
        "missing_shipping": "Missing Shipping",
        "missing_payout": "Missing Payout",
        "needs_connect": "Needs Connect",
        "final_approval_required": "Final Approval Required",
        "blocked": "Blocked",
    }.get(input_status, "Blocked")


def readiness_badge_for_item(item: dict[str, Any]) -> str:
    return input_status_badge(str(item.get("input_status") or "blocked"))


def _detect_required_inputs(item: dict[str, Any]) -> set[str]:
    text = _blob(item)
    required: set[str] = set()

    if any(term in text for term in ["shipping", "mailing address", "ship ", "shipped", "delivered", "physical good", "sample"]):
        required.add("shipping_address")
    if any(term in text for term in ["email", "inbox", "e-mail", "license key", "download link"]):
        required.add("email")
    if "phone" in text or "sms" in text or "text message" in text:
        required.add("phone")
    if any(term in text for term in ["paypal", "venmo", "cashapp", "cash app", "stripe", "bank", "ach", "direct deposit", "payout"]):
        required.add("payout_account")
    if any(term in text for term in ["crypto", "wallet", "btc", "bitcoin", "eth", "ethereum", "solana", "sol ", "usdc"]):
        required.add("crypto_wallet")
    if any(term in text for term in ["connect account", "login", "log in", "sign in", "oauth", "platform account"]):
        required.add("platform_login")
    if any(term in text for term in ["student", "education", "school email", ".edu", "student verification"]):
        required.add("student_verification")
    if any(term in text for term in ["business", "startup", "company", "ein", "founder", "incorporated"]):
        required.add("business_info")
    if _has_tax_signal(text):
        required.add("tax_info")
    if any(term in text for term in ["identity verification", "verify identity", "kyc", "driver", "passport", "government id"]):
        required.add("identity_sensitive")
    if any(term in text for term in ["legal attestation", "certify", "accept terms", "legal agreement", "terms agreement"]):
        required.add("legal_attestation")
    if any(term in text for term in ["wallet signing", "sign wallet", "wallet signature", "sign transaction"]):
        required.add("wallet_signing")
    if any(term in text for term in ["purchase required", "requires purchase", "buy ", "spend ", "out of pocket", "payment required"]):
        required.add("purchase_required")

    destination_type = str(item.get("destination_type") or "").lower()
    acceptance_status = str(item.get("acceptance_status") or "").lower()
    required_action = str(item.get("required_user_action") or "").lower()
    if destination_type == "shipping address" or "shipping" in acceptance_status or required_action == "provide_shipping":
        required.add("shipping_address")
    if destination_type in {"paypal", "stripe", "bank"} or "payout" in acceptance_status or required_action == "provide_payout":
        required.add("payout_account")
    if destination_type == "crypto wallet":
        required.add("crypto_wallet")
    if "connect" in acceptance_status or required_action == "connect":
        required.add("platform_login")
    if item.get("upfront_payment_required") or item.get("upfront_money_required"):
        required.add("purchase_required")

    return required


def _compare_with_context(required: set[str], context: dict[str, Any]) -> tuple[set[str], list[str]]:
    available: set[str] = set()
    missing: list[str] = []
    for input_name in sorted(required):
        fields = _required_context_fields(input_name, context)
        present = [field for field, value in fields.items() if _has_value(value)]
        if _input_is_available(input_name, fields, present, context):
            available.add(input_name)
        else:
            missing.extend(field for field in fields if field not in present)
    return available, _dedupe(missing)


def _input_status(
    required: set[str],
    available: set[str],
    missing: list[str],
    sensitive: list[str],
    context: dict[str, Any],
) -> str:
    completeness = compute_completeness(context)
    if sensitive:
        return "final_approval_required"
    if "shipping_address" in required and not completeness.sections["shipping"].usable_for_ai_work:
        return "missing_shipping"
    if "payout_account" in required and not completeness.sections["payouts"].usable_for_ai_work:
        return "missing_payout"
    if "platform_login" in required and "platform_login" not in available:
        return "needs_connect"
    if missing:
        return "blocked"
    return "ready_for_ai_work"


def _required_context_fields(input_name: str, context: dict[str, Any]) -> dict[str, Any]:
    profile = context.get("profile", {})
    shipping = context.get("shipping", {})
    payouts = context.get("payouts", {})
    wallets = context.get("crypto_wallets", {})
    accounts = context.get("accounts", {})
    preferences = context.get("preferences", {})
    automation = context.get("automation_limits", {})
    if input_name == "shipping_address":
        return {
            "shipping.full_name": shipping.get("full_name"),
            "shipping.address_line_1": shipping.get("address_line_1"),
            "shipping.city": shipping.get("city"),
            "shipping.state": shipping.get("state"),
            "shipping.zip": shipping.get("zip"),
            "shipping.country": shipping.get("country"),
        }
    if input_name == "email":
        return {"profile.email": profile.get("email")}
    if input_name == "phone":
        return {"profile.phone": profile.get("phone")}
    if input_name == "payout_account":
        return {
            "payouts.paypal_email": payouts.get("paypal_email"),
            "payouts.cashapp": payouts.get("cashapp"),
            "payouts.venmo": payouts.get("venmo"),
            "payouts.stripe_email": payouts.get("stripe_email"),
            "payouts.bank_label": payouts.get("bank_label"),
        }
    if input_name == "crypto_wallet":
        return {
            "crypto_wallets.btc_address": wallets.get("btc_address"),
            "crypto_wallets.eth_address": wallets.get("eth_address"),
            "crypto_wallets.sol_address": wallets.get("sol_address"),
            "crypto_wallets.usdc_address": wallets.get("usdc_address"),
        }
    if input_name == "platform_login":
        return {"accounts.connection_status": accounts.get("connection_status")}
    if input_name == "student_verification":
        return {
            "accounts.github_username": accounts.get("github_username"),
            "accounts.google_email": accounts.get("google_email"),
            "accounts.microsoft_email": accounts.get("microsoft_email"),
        }
    if input_name == "business_info":
        return {"accounts.connection_status": accounts.get("connection_status")}
    if input_name == "tax_info":
        return {"final_approval.tax_info": ""}
    if input_name == "identity_sensitive":
        return {"final_approval.identity_sensitive": ""}
    if input_name == "legal_attestation":
        return {"final_approval.legal_attestation": ""}
    if input_name == "wallet_signing":
        return {"final_approval.wallet_signing": ""}
    if input_name == "purchase_required":
        return {
            "preferences.requires_purchase": preferences.get("requires_purchase"),
            "automation_limits.max_out_of_pocket_spend": automation.get("max_out_of_pocket_spend"),
        }
    return {}


def _input_is_available(input_name: str, fields: dict[str, Any], present: list[str], context: dict[str, Any]) -> bool:
    if input_name == "payout_account":
        return bool(present)
    if input_name == "crypto_wallet":
        return bool(present)
    if input_name == "platform_login":
        return bool(present) and truthy(fields.get("accounts.connection_status"))
    if input_name == "student_verification":
        return bool(present)
    if input_name == "business_info":
        return bool(present)
    if input_name == "purchase_required":
        automation = context.get("automation_limits", {})
        preferences = context.get("preferences", {})
        return truthy(preferences.get("requires_purchase")) and _number(automation.get("max_out_of_pocket_spend")) > 0
    if input_name in {"tax_info", "identity_sensitive", "legal_attestation", "wallet_signing"}:
        return False
    return bool(fields) and len(present) == len(fields)


def _ai_has_text(available: set[str]) -> str:
    if not available:
        return "No reusable required inputs are available from User Context yet."
    return "User Context has: " + ", ".join(sorted(available)) + "."


def _user_must_provide_text(missing: list[str], sensitive: list[str]) -> str:
    parts = []
    if missing:
        parts.append("Missing: " + ", ".join(missing) + ".")
    if sensitive:
        parts.append("Final approval required for: " + ", ".join(sensitive) + ".")
    return " ".join(parts) if parts else "No additional reusable inputs appear to be missing."


def _ai_next_text(status: str, item: dict[str, Any], context: dict[str, Any]) -> str:
    automation = context.get("automation_limits", {})
    if status in {"missing_shipping", "missing_payout", "needs_connect", "blocked"}:
        return "Wait for the owner to add missing context, then prepare the safe next step."
    if status == "final_approval_required":
        return "Prepare instructions and safe draft fields only; wait for explicit final approval before sensitive action."
    allowed = []
    if truthy(automation.get("allow_open_links")):
        allowed.append("open official links")
    if truthy(automation.get("allow_prepare_forms")):
        allowed.append("prepare forms")
    if truthy(automation.get("allow_autofill")):
        allowed.append("autofill safe fields")
    if not allowed:
        return str(item.get("ai_next_action") or item.get("ai_work_possible_now") or "Prepare instructions for owner approval.")
    return "AI may " + ", ".join(allowed) + " within approval-first limits."


def _final_approval_text(sensitive: list[str], item: dict[str, Any], context: dict[str, Any]) -> str:
    automation = context.get("automation_limits", {})
    if sensitive or truthy(automation.get("require_final_approval_for_sensitive")):
        return (
            "Explicit final approval is required before login/connect, payment, legal attestation, "
            "tax, identity, purchase, payout, or submission-sensitive steps."
        )
    return str(item.get("final_acceptance_step") or "Final owner approval remains required before accepting or submitting.")


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
        "final_acceptance_step",
    ]
    return " ".join(str(item.get(key) or "") for key in keys).lower()


def _has_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value > 0
    return bool(str(value).strip())


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return 0.0


def _has_tax_signal(text: str) -> bool:
    return bool(re.search(r"\b(tax|w-?9|1099|ssn|tin)\b", text))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
