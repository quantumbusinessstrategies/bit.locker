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

SUBMIT_SAFE_ACTIONS = {"final_submit"}

LOW_RISK_BULK_APPROVAL_TERMS = [
    "free sample",
    "sample request",
    "request sample",
    "sample box",
    "product testing",
    "product tester",
    "tester application",
    "keep products",
    "free product",
    "paid research",
    "paid study",
    "user testing",
    "website testing",
    "usability test",
    "app beta",
    "beta test",
    "gift card rewards",
    "reward signup",
    "cashback rewards",
    "signup bonus",
    "no purchase",
    "no-purchase",
]

OWNER_ONLY_CLAIM_TERMS = [
    "settlement",
    "class action",
    "data breach",
    "unclaimed property",
    "claim administrator",
    "legal claim",
    "court approved",
    "harmed consumer",
    "ftc refund",
    "cfpb",
    "sec distribution",
    "reimbursement claim",
]

SENSITIVE_INPUTS = {
    "wallet_signing",
    "identity_sensitive",
    "tax_info",
    "legal_attestation",
    "purchase_required",
    "payment_authorization",
}

POLICY_NOISE_PHRASES = [
    "owner approves final submit, account connection, terms, identity, tax, wallet signing, purchases, or manual-only steps",
    "owner approves final submit, account connection, terms, identity, tax, wallet signing, purchases, or manual-only steps.",
    "no payment, purchase, legal/tax/identity, wallet signing, or external submit without explicit final approval",
    "no payment, purchase, legal/tax/identity, wallet signing, or external submit without explicit final approval.",
    "payment, purchase, legal, tax, identity, wallet signing",
    "owner final approval required: legal_agreement",
    "review approval packet: legal terms, certification, or attestation requires explicit owner approval",
]


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


def rows_for_final_approval(conn: Any, limit: int = 1000) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            cq.id,
            cq.status,
            cq.execution_status,
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
            cq.human_input_needed,
            cq.next_action,
            cq.action_engine_json,
            cq.safety_notes,
            cq.updated_at
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status NOT IN (
            'Reject',
            'Rejected',
            'Dead End',
            'Paid Mode Later',
            'Received/Paid',
            'Submitted',
            'Processing'
        )
          AND COALESCE(cq.execution_status, '') NOT IN ('Processing', 'Completed')
        ORDER BY
            CASE
                WHEN (cq.status='Ready to Accept' OR cq.execution_status='Ready To Accept')
                 AND COALESCE(cq.sensitive_inputs, '')=''
                 AND COALESCE(cq.risk_level, 'unknown') IN ('', 'low', 'unknown')
                 AND (
                    lower(o.title) LIKE '%free sample%'
                    OR lower(o.title) LIKE '%sample request%'
                    OR lower(o.title) LIKE '%product test%'
                    OR lower(o.title) LIKE '%product tester%'
                    OR lower(o.title) LIKE '%user testing%'
                    OR lower(o.title) LIKE '%website testing%'
                    OR lower(o.title) LIKE '%paid research%'
                    OR lower(o.title) LIKE '%paid study%'
                    OR lower(o.title) LIKE '%gift card rewards%'
                    OR lower(o.title) LIKE '%beta tester%'
                 )
                THEN 0
                ELSE 1
            END ASC,
            cq.fastest_gain_score DESC,
            cq.expected_value_usd DESC,
            cq.updated_at DESC
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
    if "tax_info" in sensitive_inputs or any(term in text for term in ["tax", "w-9", "w9", "1099", "ein"]):
        return "tax_action"
    if "legal_attestation" in sensitive_inputs or any(
        term in text
        for term in ["legal agreement", "accept terms", "agree to terms", "terms and conditions", "attest", "certify"]
    ):
        return "legal_agreement"
    if "purchase_required" in sensitive_inputs or any(
        _has_unnegated_blocker(text, term)
        for term in ["purchase", "buy ", "payment required", "out of pocket"]
    ):
        return "purchase"
    if any(term in text for term in ["payment authorization", "authorize payment", "card authorization"]):
        return "payment_authorization"
    if str(row.get("input_status") or "") == "needs_connect" or any(term in text for term in ["connect account", "login", "sign in", "oauth"]):
        return "account_connection"
    if _looks_like_safe_ready_submit(row):
        return "final_submit"
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


def _looks_like_safe_ready_submit(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "")
    execution_status = str(row.get("execution_status") or "")
    input_status = str(row.get("input_status") or "")
    if status != "Ready to Accept" and execution_status != "Ready To Accept":
        return False
    if input_status not in {"", "ready_for_ai_work", "submitted_processing", "final_approval_required"}:
        return False
    sensitive_inputs = set(_csv(row.get("sensitive_inputs")))
    if sensitive_inputs & SENSITIVE_INPUTS:
        return False
    text = _blob(row)
    blocked_terms = [
        "wallet signing",
        "sign transaction",
        "identity verification",
        "verify identity",
        "kyc",
        "government id",
        "tax",
        "w-9",
        "w9",
        "1099",
        "legal agreement",
        "accept terms",
        "agree to terms",
        "terms and conditions",
        "attest",
        "certify",
        "purchase",
        "buy ",
        "payment required",
        "out of pocket",
        "payment authorization",
        "authorize payment",
        "connect account",
        "login",
        "sign in",
        "oauth",
    ]
    if any(_has_unnegated_blocker(text, term) for term in blocked_terms):
        return False
    if input_status == "final_approval_required" and not _is_low_risk_bulk_approval(row):
        return False
    return True


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
        safe_to_mark_submitted=_is_bulk_safe_submit(row, action_type),
    )


def _is_bulk_safe_submit(row: dict[str, Any], action_type: str) -> bool:
    risk = str(row.get("risk_level") or "unknown").lower()
    return (
        action_type == "final_submit"
        and risk in {"", "low", "unknown"}
        and _looks_like_safe_ready_submit(row)
        and _is_low_risk_bulk_approval(row)
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
    keys = [
        "status",
        "execution_status",
        "input_status",
        "required_inputs",
        "sensitive_inputs",
        "acceptance_status",
        "destination_type",
        "asset_type",
        "required_user_action",
        "owner_input_required",
        "human_input_needed",
        "what_user_must_approve",
        "ai_work_possible_now",
        "what_ai_already_prepared",
        "exact_next_step",
        "next_action",
        "claim_instructions",
        "official_link",
        "final_acceptance_step",
        "title",
        "url",
    ]
    text = " ".join(str(row.get(key) or "") for key in keys).lower()
    return _scrub_policy_noise(text)


def _is_low_risk_bulk_approval(row: dict[str, Any]) -> bool:
    text = _blob(row)
    if not any(term in text for term in LOW_RISK_BULK_APPROVAL_TERMS):
        return False
    return not any(term in text for term in OWNER_ONLY_CLAIM_TERMS)


def _has_unnegated_blocker(text: str, term: str) -> bool:
    if term not in text:
        return False
    if term.strip() in {"purchase", "payment required", "out of pocket"}:
        negations = [
            "no purchase",
            "no-purchase",
            "without purchase",
            "purchase not required",
            "purchase required: false",
            "no payment required",
            "without payment",
            "no out of pocket",
            "no out-of-pocket",
        ]
        if any(phrase in text for phrase in negations):
            return False
    return True


def _scrub_policy_noise(text: str) -> str:
    cleaned = text
    for phrase in POLICY_NOISE_PHRASES:
        cleaned = cleaned.replace(phrase, " ")
    return " ".join(cleaned.split())
