from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


FINAL_ACTION_TYPES = [
    "final_submit",
    "payment_authorization",
    "purchase",
    "legal_agreement",
    "tax_action",
    "identity_verification",
    "wallet_signing",
    "sensitive_claim",
    "account_connection",
]

SUBMIT_SAFE_ACTIONS = {"final_submit", "sensitive_claim"}


@dataclass(frozen=True)
class FinalApprovalItem:
    claim_queue_id: int
    opportunity_title: str
    expected_gain_value: float
    risk_level: str
    why_approval_required: str
    what_ai_already_prepared: str
    what_happens_if_approved: str
    what_happens_if_rejected: str
    official_link: str
    final_action_type: str
    safe_to_mark_submitted: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def rows_for_final_approval(conn: Any, limit: int = 500) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            o.title,
            o.url,
            cq.expected_value_usd,
            cq.risk_level,
            cq.input_status,
            cq.required_inputs,
            cq.sensitive_inputs,
            cq.acceptance_status,
            cq.destination_type,
            cq.asset_type,
            cq.required_user_action,
            cq.ai_work_completed,
            cq.ai_work_possible_now,
            cq.what_ai_already_prepared,
            cq.exact_next_step,
            cq.claim_instructions,
            cq.official_link,
            cq.final_acceptance_step,
            cq.owner_input_required,
            cq.safety_notes,
            cq.updated_at
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later', 'Received/Paid')
        ORDER BY cq.fastest_gain_score DESC, cq.expected_value_usd DESC, cq.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def build_final_approval_queue(rows: list[dict[str, Any]]) -> list[FinalApprovalItem]:
    items = []
    for row in rows:
        action_type = final_action_type(row)
        if not action_type:
            continue
        items.append(_item_from_row(row, action_type))
    return items


def final_action_type(row: dict[str, Any]) -> str:
    text = _blob(row)
    sensitive_inputs = set(_csv(row.get("sensitive_inputs")))
    if "wallet_signing" in sensitive_inputs or any(term in text for term in ["wallet signing", "sign transaction", "wallet signature"]):
        return "wallet_signing"
    if "identity_sensitive" in sensitive_inputs or any(term in text for term in ["identity verification", "verify identity", "kyc", "government id"]):
        return "identity_verification"
    if "tax_info" in sensitive_inputs or any(term in text for term in ["tax", "w-9", "w9", "1099"]):
        return "tax_action"
    if "legal_attestation" in sensitive_inputs or any(term in text for term in ["legal agreement", "accept terms", "attest", "certify"]):
        return "legal_agreement"
    if "purchase_required" in sensitive_inputs or any(term in text for term in ["purchase", "buy ", "payment required", "out of pocket"]):
        return "purchase"
    if any(term in text for term in ["payment authorization", "authorize payment", "card authorization"]):
        return "payment_authorization"
    if str(row.get("input_status") or "") == "needs_connect" or any(term in text for term in ["connect account", "login", "sign in", "oauth"]):
        return "account_connection"
    if str(row.get("input_status") or "") == "final_approval_required":
        return "sensitive_claim"
    if any(
        term in text
        for term in [
            "final submit",
            "submit application",
            "submit the application",
            "application form",
            "submit claim",
            "submit the claim",
            "claim form",
            "submit the form",
            "claim submitted",
        ]
    ):
        return "final_submit"
    return ""


def approval_result_status(action_type: str, action: str) -> str:
    if action == "Reject":
        return "Rejected"
    if action == "Later":
        return "Later"
    if action == "Needs More Info":
        return "Needs Approval"
    if action != "Approve Final Step":
        return "Needs Approval"
    if action_type == "account_connection":
        return "Connect Needed"
    if action_type in SUBMIT_SAFE_ACTIONS:
        return "Submitted"
    return "Approved"


def approval_result_note(action_type: str, action: str) -> str:
    if action != "Approve Final Step":
        return f"Final approval action marked: {action}."
    if action_type in SUBMIT_SAFE_ACTIONS:
        return "Owner approved final step; item can move to Submitted/processing for safe continuation."
    return (
        "Owner approved review path, but this action remains owner-executed. "
        "Do not auto-submit payment, purchase, legal, tax, identity, wallet-signing, or login actions."
    )


def _item_from_row(row: dict[str, Any], action_type: str) -> FinalApprovalItem:
    return FinalApprovalItem(
        claim_queue_id=int(row.get("id") or 0),
        opportunity_title=str(row.get("title") or "Untitled opportunity"),
        expected_gain_value=_number(row.get("expected_value_usd")),
        risk_level=str(row.get("risk_level") or "unknown"),
        why_approval_required=_why_required(row, action_type),
        what_ai_already_prepared=_prepared_text(row),
        what_happens_if_approved=_approved_text(action_type),
        what_happens_if_rejected="The item remains stopped and can be rejected, deferred, or reviewed later.",
        official_link=str(row.get("official_link") or row.get("url") or ""),
        final_action_type=action_type,
        safe_to_mark_submitted=action_type in SUBMIT_SAFE_ACTIONS,
    )


def _why_required(row: dict[str, Any], action_type: str) -> str:
    labels = {
        "final_submit": "The prepared work needs explicit owner consent before final submission.",
        "payment_authorization": "Payment authorization requires explicit owner approval.",
        "purchase": "Purchase or out-of-pocket action requires explicit owner approval.",
        "legal_agreement": "Legal terms, certification, or attestation requires explicit owner approval.",
        "tax_action": "Tax-related information or form action requires explicit owner approval.",
        "identity_verification": "Identity verification requires owner action inside the official platform.",
        "wallet_signing": "Wallet signing requires explicit owner action and cannot be automated.",
        "sensitive_claim": "Sensitive claim action is gated behind final approval.",
        "account_connection": "Account connection or login requires owner action.",
    }
    return labels.get(action_type, str(row.get("owner_input_required") or "Final approval is required."))


def _prepared_text(row: dict[str, Any]) -> str:
    return str(
        row.get("ai_work_completed")
        or row.get("what_ai_already_prepared")
        or row.get("claim_instructions")
        or row.get("exact_next_step")
        or "AI has prepared available instructions and context for owner review."
    )


def _approved_text(action_type: str) -> str:
    if action_type in SUBMIT_SAFE_ACTIONS:
        return "The item moves to Submitted/processing for safe continuation and tracking."
    if action_type == "account_connection":
        return "The item moves to Connect Needed so the owner can connect inside the official platform."
    return "The owner performs the sensitive final action manually inside the official platform; AI continues tracking/prep only."


def _csv(value: Any) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in str(value).split(",") if part.strip()]


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
    return " ".join(str(value or "") for value in row.values()).lower()
