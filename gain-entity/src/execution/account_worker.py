from __future__ import annotations

from typing import Any

from execution.autofill_execution import safe_context_covers_owner_blocker


class AccountWorker:
    BLOCKING_TERMS = [
        "credential",
        "password",
        "sign in",
        "login",
        "log in",
        "connect account",
        "oauth",
        "accept terms",
        "terms",
        "identity verification",
        "verify identity",
        "kyc",
        "shipping address",
        "payout",
        "bank account",
        "paypal",
        "stripe",
        "wallet address",
    ]

    def __init__(self, user_context: dict[str, Any] | None = None) -> None:
        self.user_context = user_context or {}

    def inspect(self, item: dict[str, Any]) -> dict[str, Any]:
        text = _blob(item)
        matched = [term for term in self.BLOCKING_TERMS if term in text]
        status = str(item.get("status") or "")
        if status == "Connect Needed" or matched:
            if status != "Connect Needed" and safe_context_covers_owner_blocker(item, self.user_context):
                return {
                    "blocked": False,
                    "reason": "Safe reusable context covers this owner-input blocker.",
                    "completion": 72,
                    "matched_terms": matched,
                }
            reason = "Owner-only account, terms, payout, shipping, or identity input is required."
            return {
                "blocked": True,
                "reason": reason,
                "human_input_needed": item.get("owner_input_required") or item.get("user_approval_needed") or reason,
                "next_action": item.get("final_acceptance_step") or item.get("exact_next_step") or reason,
                "completion": 40,
                "matched_terms": matched,
            }
        return {
            "blocked": False,
            "reason": "No credential/connect blocker detected.",
            "completion": 60,
        }


def _blob(item: dict[str, Any]) -> str:
    keys = [
        "status",
        "acceptance_status",
        "required_user_action",
        "owner_input_required",
        "user_approval_needed",
        "what_user_must_approve",
        "exact_next_step",
        "claim_instructions",
        "final_acceptance_step",
        "destination",
        "asset_destination",
    ]
    return " ".join(str(item.get(key) or "") for key in keys).lower()
