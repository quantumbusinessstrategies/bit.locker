from __future__ import annotations

from typing import Any


class SubmissionWorker:
    def decide(self, item: dict[str, Any], blocked: bool, prepared: bool) -> dict[str, Any]:
        if blocked:
            return {
                "execution_status": "Paused Awaiting Input",
                "claim_status": item.get("status") or "Approved",
                "next_action": item.get("owner_input_required") or item.get("final_acceptance_step") or "Wait for owner input.",
                "completion": 45,
            }
        if str(item.get("acceptance_status") or "") == "Ready to Accept":
            return {
                "execution_status": "Ready To Accept",
                "claim_status": "Ready to Accept",
                "next_action": item.get("final_acceptance_step") or "Owner accepts the prepared gain.",
                "completion": 92,
            }
        if prepared:
            return {
                "execution_status": "AI Working",
                "claim_status": "Approved",
                "next_action": item.get("ai_next_action") or item.get("exact_next_step") or "Continue safe execution prep.",
                "completion": 72,
            }
        return {
            "execution_status": "Execution Queue",
            "claim_status": item.get("status") or "Approved",
            "next_action": item.get("exact_next_step") or "Prepare the next execution step.",
            "completion": 50,
        }

