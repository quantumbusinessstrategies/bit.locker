from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from user_context.required_inputs import input_status_badge


ACTION_BUCKETS = [
    "Needs Connect",
    "Needs Shipping",
    "Needs Payment",
    "Missing Email",
    "Missing Phone",
    "Missing Wallet",
    "Final Approval Required",
    "Needs Login",
    "Missing Tax Information",
    "Missing Identity",
    "Other Required Inputs",
]

FRICTION_BY_STATUS = {
    "ready_for_ai_work": 1.0,
    "missing_shipping": 2.0,
    "missing_payout": 2.5,
    "needs_connect": 3.0,
    "final_approval_required": 5.0,
    "blocked": 4.0,
}


@dataclass(frozen=True)
class UserActionItem:
    claim_queue_id: int
    opportunity: str
    estimated_gain: float
    missing_requirement: str
    action_bucket: str
    time_required: str
    completion_percent: float
    ai_readiness: str
    readiness_badge: str
    action_priority_score: float
    action_button_label: str
    action_behavior: str
    required_input_count: int
    friction_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GlobalInputDependency:
    input_key: str
    display_name: str
    blocks: list[str]
    number_unblocked: int
    value_score: float
    probability_score: float
    unlock_score: float
    prompt: str
    target_section: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_user_action_items(rows: list[dict[str, Any]], user_context: dict[str, Any]) -> list[UserActionItem]:
    items = [build_user_action_item(row, user_context) for row in rows]
    actionable = [item for item in items if item.action_bucket in ACTION_BUCKETS]
    return sorted(actionable, key=lambda item: item.action_priority_score, reverse=True)


def global_input_dependency_map(rows: list[dict[str, Any]]) -> list[GlobalInputDependency]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for input_key in _dependency_keys(row):
            grouped.setdefault(input_key, []).append(row)

    dependencies = []
    for input_key, blocked_rows in grouped.items():
        number_unblocked = len(blocked_rows)
        value_score = _average(_score_value(row, "highest_value_score") for row in blocked_rows)
        probability_score = _average(
            _score_value(row, "probability_score_1_to_10", fallback_key="probability_score")
            for row in blocked_rows
        )
        unlock_score = round(number_unblocked * value_score * probability_score, 2)
        display_name = _input_display_name(input_key)
        dependencies.append(
            GlobalInputDependency(
                input_key=input_key,
                display_name=display_name,
                blocks=[str(row.get("title") or "Untitled opportunity") for row in blocked_rows],
                number_unblocked=number_unblocked,
                value_score=round(value_score, 2),
                probability_score=round(probability_score, 2),
                unlock_score=unlock_score,
                prompt=f"Completing this unlocks {number_unblocked} opportunities.",
                target_section=_target_section(input_key),
            )
        )
    return sorted(dependencies, key=lambda item: item.unlock_score, reverse=True)


def build_user_action_item(row: dict[str, Any], user_context: dict[str, Any]) -> UserActionItem:
    input_status = str(row.get("input_status") or "blocked")
    required_inputs = _csv(row.get("required_inputs"))
    missing_inputs = _csv(row.get("missing_inputs"))
    sensitive_inputs = _csv(row.get("sensitive_inputs"))
    required_count = max(1, len(required_inputs) + len(missing_inputs) + len(sensitive_inputs))
    friction = _friction_score(input_status, missing_inputs, sensitive_inputs)
    priority = _priority_score(row, required_count, friction)
    bucket = _action_bucket(input_status, missing_inputs, sensitive_inputs, row)
    has_context = bool(_csv(row.get("available_inputs"))) and input_status == "ready_for_ai_work"
    button_label = "AI Autofill From Context" if has_context else "Resolve Missing Inputs"
    behavior = (
        "AI can stage safe reusable fields from User Context; final approval is still required before submission."
        if has_context
        else "Open the Profile Completion Center for the missing reusable input or final approval blocker."
    )
    return UserActionItem(
        claim_queue_id=int(row.get("id") or row.get("claim_queue_id") or 0),
        opportunity=str(row.get("title") or row.get("opportunity") or "Untitled opportunity"),
        estimated_gain=_number(row.get("expected_value_usd")),
        missing_requirement=_missing_requirement(missing_inputs, sensitive_inputs, row),
        action_bucket=bucket,
        time_required=_time_required(row, friction),
        completion_percent=_number(row.get("estimated_completion_percent")),
        ai_readiness=_ai_readiness(row, input_status),
        readiness_badge=input_status_badge(input_status),
        action_priority_score=priority,
        action_button_label=button_label,
        action_behavior=behavior,
        required_input_count=required_count,
        friction_score=friction,
    )


def rows_for_action_center(conn: Any, limit: int = 500) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            o.title,
            o.url,
            cq.expected_value_usd,
            cq.probability_score,
            cq.probability_score_1_to_10,
            cq.time_to_gain,
            cq.time_to_gain_days,
            cq.fastest_gain_score,
            cq.highest_value_score,
            cq.input_status,
            cq.required_inputs,
            cq.available_inputs,
            cq.missing_inputs,
            cq.sensitive_inputs,
            cq.acceptance_status,
            cq.destination_type,
            cq.asset_type,
            cq.estimated_completion_percent,
            cq.ai_work_completed,
            cq.ai_work_possible_now,
            cq.owner_input_required,
            cq.next_action,
            cq.exact_next_step,
            cq.official_link,
            cq.updated_at
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
        ORDER BY cq.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def _priority_score(row: dict[str, Any], required_count: int, friction: float) -> float:
    probability = _number(row.get("probability_score_1_to_10", row.get("probability_score")))
    speed = _number(row.get("fastest_gain_score"))
    value = _number(row.get("highest_value_score"))
    if speed <= 0:
        speed = _speed_from_days(_number(row.get("time_to_gain_days")))
    if value <= 0:
        value = _value_from_dollars(_number(row.get("expected_value_usd")))
    denominator = max(1.0, required_count + friction)
    return round((probability * speed * value) / denominator, 2)


def _action_bucket(
    input_status: str,
    missing_inputs: list[str],
    sensitive_inputs: list[str],
    row: dict[str, Any],
) -> str:
    text = " ".join([input_status, " ".join(missing_inputs), " ".join(sensitive_inputs), _blob(row)])
    if "tax_info" in text or "tax" in text or "w-9" in text or "1099" in text:
        return "Missing Tax Information"
    if "identity_sensitive" in text or "identity" in text or "kyc" in text:
        return "Missing Identity"
    if "wallet_signing" in text or "wallet signature" in text or "sign transaction" in text:
        return "Final Approval Required"
    if "legal_attestation" in text or "legal agreement" in text or "attest" in text:
        return "Final Approval Required"
    if input_status == "final_approval_required":
        return "Final Approval Required"
    if input_status == "needs_connect":
        return "Needs Connect"
    if "platform_login" in text or "login" in text or "sign in" in text:
        return "Needs Login"
    if input_status == "missing_shipping" or "shipping." in text:
        return "Needs Shipping"
    if input_status == "missing_payout" or "payouts." in text:
        return "Needs Payment"
    if "profile.email" in text:
        return "Missing Email"
    if "profile.phone" in text:
        return "Missing Phone"
    if "crypto_wallets." in text or "crypto_wallet" in text:
        return "Missing Wallet"
    return "Other Required Inputs"


def _missing_requirement(missing_inputs: list[str], sensitive_inputs: list[str], row: dict[str, Any]) -> str:
    if sensitive_inputs:
        return ", ".join(sensitive_inputs)
    if missing_inputs:
        return ", ".join(missing_inputs)
    return str(row.get("owner_input_required") or row.get("next_action") or "No missing reusable input detected.")


def _dependency_keys(row: dict[str, Any]) -> list[str]:
    input_status = str(row.get("input_status") or "")
    missing_inputs = _csv(row.get("missing_inputs"))
    sensitive_inputs = _csv(row.get("sensitive_inputs"))
    keys: list[str] = []
    if input_status == "missing_shipping" or any(field.startswith("shipping.") for field in missing_inputs):
        keys.append("shipping_address")
    if input_status == "missing_payout" or any(field.startswith("payouts.") for field in missing_inputs):
        keys.append(_payout_dependency_key(row, missing_inputs))
    if (
        input_status == "needs_connect"
        or "platform_login" in missing_inputs
        or str(row.get("status") or "") == "Connect Needed"
    ):
        keys.append(_login_dependency_key(row))
    if "profile.email" in missing_inputs:
        keys.append("email")
    if "profile.phone" in missing_inputs:
        keys.append("phone")
    if any(field.startswith("crypto_wallets.") for field in missing_inputs):
        keys.append(_wallet_dependency_key(row, missing_inputs))
    if "tax_info" in sensitive_inputs:
        keys.append("tax_info")
    if "identity_sensitive" in sensitive_inputs:
        keys.append("identity_sensitive")
    if "legal_attestation" in sensitive_inputs:
        keys.append("legal_attestation")
    if "wallet_signing" in sensitive_inputs:
        keys.append("wallet_signing")
    if "purchase_required" in sensitive_inputs:
        keys.append("purchase_required")
    return _dedupe(keys)


def _payout_dependency_key(row: dict[str, Any], missing_inputs: list[str]) -> str:
    text = _blob(row)
    if "paypal" in text or "payouts.paypal_email" in missing_inputs:
        return "paypal_email"
    if "venmo" in text:
        return "venmo"
    if "cashapp" in text or "cash app" in text:
        return "cashapp"
    if "stripe" in text:
        return "stripe_email"
    return "payout_account"


def _login_dependency_key(row: dict[str, Any]) -> str:
    text = _blob(row)
    if "github" in text or "student pack" in text or "developer" in text:
        return "github_login"
    if "google" in text:
        return "google_login"
    if "microsoft" in text or "azure" in text:
        return "microsoft_login"
    if "tiktok" in text:
        return "tiktok_login"
    if "amazon" in text:
        return "amazon_login"
    if "paypal" in text:
        return "paypal_login"
    return "platform_login"


def _wallet_dependency_key(row: dict[str, Any], missing_inputs: list[str]) -> str:
    text = _blob(row)
    if "btc" in text or "bitcoin" in text or "crypto_wallets.btc_address" in missing_inputs:
        return "btc_address"
    if "eth" in text or "ethereum" in text or "crypto_wallets.eth_address" in missing_inputs:
        return "eth_address"
    if "sol" in text or "solana" in text or "crypto_wallets.sol_address" in missing_inputs:
        return "sol_address"
    if "usdc" in text or "crypto_wallets.usdc_address" in missing_inputs:
        return "usdc_address"
    return "crypto_wallet"


def _input_display_name(input_key: str) -> str:
    return {
        "shipping_address": "Shipping address",
        "paypal_email": "PayPal email",
        "venmo": "Venmo",
        "cashapp": "Cash App",
        "stripe_email": "Stripe email",
        "payout_account": "Payout account",
        "github_login": "GitHub login",
        "google_login": "Google login",
        "microsoft_login": "Microsoft login",
        "tiktok_login": "TikTok login",
        "amazon_login": "Amazon login",
        "paypal_login": "PayPal login",
        "platform_login": "Platform login",
        "email": "Email",
        "phone": "Phone",
        "btc_address": "BTC address",
        "eth_address": "ETH address",
        "sol_address": "SOL address",
        "usdc_address": "USDC address",
        "crypto_wallet": "Crypto wallet",
        "tax_info": "Tax information",
        "identity_sensitive": "Identity verification",
        "legal_attestation": "Legal attestation",
        "wallet_signing": "Wallet signing approval",
        "purchase_required": "Purchase/payment approval",
    }.get(input_key, input_key.replace("_", " ").title())


def _target_section(input_key: str) -> str:
    if input_key == "shipping_address":
        return "Shipping"
    if input_key in {"paypal_email", "venmo", "cashapp", "stripe_email", "payout_account"}:
        return "Payments"
    if input_key.endswith("_login") or input_key == "platform_login":
        return "Email Accounts"
    if input_key in {"email"}:
        return "Email Accounts"
    if input_key == "phone":
        return "Phone"
    if input_key in {"btc_address", "eth_address", "sol_address", "usdc_address", "crypto_wallet"}:
        return "Crypto"
    if input_key in {"tax_info", "identity_sensitive", "legal_attestation", "wallet_signing", "purchase_required"}:
        return "Final Approval"
    return "Profile"


def _time_required(row: dict[str, Any], friction: float) -> str:
    if row.get("time_to_gain"):
        return str(row["time_to_gain"])
    if friction <= 1:
        return "Under 5 minutes"
    if friction <= 3:
        return "5-10 minutes"
    return "Owner review required"


def _ai_readiness(row: dict[str, Any], input_status: str) -> str:
    if input_status == "ready_for_ai_work":
        return "Ready for AI-safe continuation"
    if input_status == "final_approval_required":
        return "AI can prepare only; final approval required"
    if row.get("ai_work_possible_now"):
        return str(row["ai_work_possible_now"])
    return "Waiting on owner-required input"


def _friction_score(input_status: str, missing_inputs: list[str], sensitive_inputs: list[str]) -> float:
    base = FRICTION_BY_STATUS.get(input_status, 4.0)
    return base + (len(missing_inputs) * 0.5) + (len(sensitive_inputs) * 1.5)


def _score_value(row: dict[str, Any], key: str, fallback_key: str | None = None) -> float:
    value = _number(row.get(key))
    if value <= 0 and fallback_key:
        value = _number(row.get(fallback_key))
    return value


def _average(values: Any) -> float:
    numbers = [float(value) for value in values if float(value) > 0]
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def _speed_from_days(days: float) -> float:
    if days <= 0:
        return 60.0
    if days <= 1:
        return 95.0
    if days <= 3:
        return 85.0
    if days <= 7:
        return 70.0
    if days <= 30:
        return 30.0
    return 10.0


def _value_from_dollars(value: float) -> float:
    if value <= 0:
        return 10.0
    if value >= 1000:
        return 100.0
    if value >= 100:
        return 70.0
    return max(20.0, min(60.0, value))


def _csv(value: Any) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return 0.0


def _blob(row: dict[str, Any]) -> str:
    keys = [
        "acceptance_status",
        "destination_type",
        "asset_type",
        "owner_input_required",
        "next_action",
        "exact_next_step",
        "title",
    ]
    return " ".join(str(row.get(key) or "") for key in keys).lower()
