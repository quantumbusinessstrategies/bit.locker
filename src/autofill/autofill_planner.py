from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from autofill.autofill_safety import final_approval_required_for, is_safe_autofill_field, safe_next_action
from connectors.connector_status import connector_status_map


@dataclass(frozen=True)
class AutofillPlan:
    claim_queue_id: int
    opportunity: str
    fields_ai_can_autofill: list[str]
    fields_missing: list[str]
    connector_needed: str
    next_safe_ai_action: str
    final_approval_required: bool
    readiness: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_autofill_for_opportunity(row: dict[str, Any], user_context: dict[str, Any]) -> AutofillPlan:
    required_fields = _required_autofill_fields(row)
    available = _available_context_fields(user_context)
    can_autofill = sorted(field for field in required_fields if field in available and is_safe_autofill_field(field))
    missing = sorted(field for field in required_fields if field not in can_autofill)
    connector_needed = _connector_needed(row, user_context)
    final_required = final_approval_required_for(row)
    readiness = _readiness(can_autofill, missing, connector_needed, final_required)
    return AutofillPlan(
        claim_queue_id=int(row.get("id") or 0),
        opportunity=str(row.get("title") or "Untitled opportunity"),
        fields_ai_can_autofill=can_autofill,
        fields_missing=missing,
        connector_needed=connector_needed,
        next_safe_ai_action=safe_next_action(bool(can_autofill), final_required, connector_needed),
        final_approval_required=final_required,
        readiness=readiness,
    )


def plan_autofill_for_opportunities(rows: list[dict[str, Any]], user_context: dict[str, Any]) -> list[AutofillPlan]:
    return [plan_autofill_for_opportunity(row, user_context) for row in rows]


def rows_for_autofill(conn: Any, limit: int = 500) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            o.title,
            o.url,
            cq.input_status,
            cq.required_inputs,
            cq.available_inputs,
            cq.missing_inputs,
            cq.sensitive_inputs,
            cq.destination_type,
            cq.asset_type,
            cq.acceptance_status,
            cq.required_user_action,
            cq.owner_input_required,
            cq.ai_work_possible_now,
            cq.exact_next_step,
            cq.claim_instructions,
            cq.official_link,
            cq.expected_value_usd,
            cq.probability_score_1_to_10,
            cq.fastest_gain_score
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
        ORDER BY cq.fastest_gain_score DESC, cq.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def summarize_autofill(plans: list[AutofillPlan], user_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "autofill_ready": sum(1 for plan in plans if plan.readiness == "autofill_ready"),
        "blocked_by_login": sum(1 for plan in plans if plan.readiness == "blocked_by_login"),
        "blocked_by_missing_context": sum(1 for plan in plans if plan.readiness == "blocked_by_missing_context"),
        "final_approval_required": sum(1 for plan in plans if plan.final_approval_required),
        "connected_accounts": sum(1 for status in connector_status_map(user_context).values() if status.connected),
        "missing_connectors": sum(1 for status in connector_status_map(user_context).values() if not status.connected),
    }


def _required_autofill_fields(row: dict[str, Any]) -> set[str]:
    text = _blob(row)
    required = set()
    required_inputs = set(_csv(row.get("required_inputs")))
    missing_inputs = set(_csv(row.get("missing_inputs")))
    if "email" in required_inputs or "profile.email" in missing_inputs or "email" in text:
        required.add("profile.email")
    if "phone" in required_inputs or "profile.phone" in missing_inputs or "phone" in text:
        required.add("profile.phone")
    if "shipping_address" in required_inputs or any(item.startswith("shipping.") for item in missing_inputs):
        required.update(
            {
                "shipping.full_name",
                "shipping.address_line_1",
                "shipping.city",
                "shipping.state",
                "shipping.zip",
                "shipping.country",
            }
        )
    if "payout_account" in required_inputs or any(item.startswith("payouts.") for item in missing_inputs):
        if "stripe" in text:
            required.add("payouts.stripe_email")
        else:
            required.add("payouts.paypal_email")
    if "crypto_wallet" in required_inputs or any(item.startswith("crypto_wallets.") for item in missing_inputs):
        if "btc" in text or "bitcoin" in text:
            required.add("crypto_wallets.btc_address")
        elif "sol" in text or "solana" in text:
            required.add("crypto_wallets.sol_address")
        elif "usdc" in text:
            required.add("crypto_wallets.usdc_address")
        else:
            required.add("crypto_wallets.eth_address")
    if "github" in text:
        required.add("accounts.github_username")
    if "google" in text:
        required.add("accounts.google_email")
    if "microsoft" in text or "azure" in text:
        required.add("accounts.microsoft_email")
    if "apple" in text or "icloud" in text:
        required.add("accounts.apple_email")
    if "paypal" in text:
        required.add("accounts.paypal_email")
    if "business" in text or "company" in text or "startup" in text:
        required.add("business.business_name")
    if not required:
        required.update({"profile.name", "profile.email"})
    return required


def _available_context_fields(user_context: dict[str, Any]) -> set[str]:
    available = set()
    profile = user_context.get("profile", {})
    shipping = user_context.get("shipping", {})
    payouts = user_context.get("payouts", {})
    wallets = user_context.get("crypto_wallets", {})
    accounts = user_context.get("accounts", {})
    business = user_context.get("business", {})
    for field in ["name", "email", "phone"]:
        if _has_value(profile.get(field)):
            available.add(f"profile.{field}")
    for field in ["full_name", "address_line_1", "address_line_2", "city", "state", "zip", "country"]:
        if _has_value(shipping.get(field)):
            available.add(f"shipping.{field}")
    for field in ["paypal_email", "stripe_email"]:
        if _has_value(payouts.get(field)):
            available.add(f"payouts.{field}")
    for field in ["btc_address", "eth_address", "sol_address", "usdc_address"]:
        if _has_value(wallets.get(field)):
            available.add(f"crypto_wallets.{field}")
    for field in ["github_username", "google_email", "microsoft_email", "apple_email", "amazon_email", "paypal_email"]:
        if _has_value(accounts.get(field)):
            available.add(f"accounts.{field}")
    for status in connector_status_map(user_context).values():
        if status.connected:
            available.add(status.context_field)
    for field in ["business_name", "website_domain", "founder_name", "company_description", "startup_stage", "industry"]:
        if _has_value(business.get(field)):
            available.add(f"business.{field}")
    return available


def _connector_needed(row: dict[str, Any], user_context: dict[str, Any]) -> str:
    text = _blob(row)
    statuses = connector_status_map(user_context)
    for key in ["github", "google", "microsoft", "apple", "paypal", "amazon", "tiktok"]:
        status = statuses.get(key)
        if key in text and (status is None or not status.connected):
            return status.label if status else key.title()
    if str(row.get("input_status") or "") == "needs_connect" and not _generic_platform_access_available(user_context):
        return "Platform account"
    return ""


def _generic_platform_access_available(user_context: dict[str, Any]) -> bool:
    accounts = user_context.get("accounts", {})
    if not isinstance(accounts, dict):
        return False
    if str(accounts.get("connection_status") or "").strip():
        return True
    return any(
        bool(accounts.get(key))
        for key in [
            "paypal_connected",
            "gmail_connected",
            "github_connected",
            "microsoft_connected",
            "amazon_connected",
            "apple_connected",
        ]
    )


def _readiness(can_autofill: list[str], missing: list[str], connector_needed: str, final_required: bool) -> str:
    if final_required:
        return "final_approval_required"
    if connector_needed:
        return "blocked_by_login"
    if missing:
        return "blocked_by_missing_context"
    if can_autofill:
        return "autofill_ready"
    return "blocked_by_missing_context"


def _has_value(value: Any) -> bool:
    return bool(str(value or "").strip())


def _csv(value: Any) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _blob(row: dict[str, Any]) -> str:
    return " ".join(str(value or "") for value in row.values()).lower()
