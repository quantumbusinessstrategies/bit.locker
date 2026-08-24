from __future__ import annotations

from typing import Any

from execution.autofill_execution import safe_context_covers_owner_blocker


class RoutingWorker:
    BLOCKING_ACCEPTANCE = {
        "Needs Connect": "Owner must connect or sign in to the official platform.",
        "Needs Shipping": "Owner must provide shipping details inside the official platform.",
        "Needs Payout": "Owner must provide payout details inside the official platform.",
        "Needs Identity Verification": "Owner must complete identity verification inside the official platform.",
    }

    def __init__(self, user_context: dict[str, Any] | None = None) -> None:
        self.user_context = user_context or {}

    def inspect(self, item: dict[str, Any]) -> dict[str, Any]:
        acceptance_status = str(item.get("acceptance_status") or "").strip()
        if acceptance_status in self.BLOCKING_ACCEPTANCE:
            if acceptance_status in {"Needs Shipping", "Needs Payout"} and safe_context_covers_owner_blocker(item, self.user_context):
                return {
                    "blocked": False,
                    "safe_autofill_available": True,
                    "reason": f"{acceptance_status} is covered by safe User Context fields.",
                    "next_action": "Use vault-backed autofill packet in live assist, then request final approval before submission.",
                    "completion": 72,
                }
            return {
                "blocked": True,
                "reason": self.BLOCKING_ACCEPTANCE[acceptance_status],
                "human_input_needed": self.BLOCKING_ACCEPTANCE[acceptance_status],
                "next_action": item.get("owner_input_required") or self.BLOCKING_ACCEPTANCE[acceptance_status],
                "completion": 35,
            }
        if acceptance_status == "Ready to Accept":
            return {
                "blocked": False,
                "ready_to_accept": True,
                "next_action": item.get("final_acceptance_step") or "Owner accepts the final gain in the official platform.",
                "completion": 90,
            }
        return {
            "blocked": False,
            "ready_to_accept": False,
            "next_action": item.get("ai_next_action") or item.get("exact_next_step") or "Continue safe execution prep.",
            "completion": 45,
        }
