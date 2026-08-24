from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from approval.final_approval_queue import final_action_type
from approval.submission_consent import DISALLOWED_LIVE_SUBMIT_ACTIONS


@dataclass(frozen=True)
class LiveSubmitResult:
    attempted: bool
    allowed: bool
    status: str
    execution_status: str
    note: str
    proof_or_reference_note: str
    next_action: str
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_live_submit(item: dict[str, Any], consent: dict[str, Any], credential_unlocked: bool = False) -> LiveSubmitResult:
    action_type = final_action_type(item)
    official_link = str(item.get("official_link") or item.get("url") or "").strip()
    if not consent.get("allowed"):
        return _result(False, False, "Submitted", "Processing", "No live-submit consent is recorded.", "", "Wait for explicit live-submit consent.", {})
    if action_type in DISALLOWED_LIVE_SUBMIT_ACTIONS:
        return _result(
            False,
            False,
            str(item.get("status") or "Submitted"),
            "Paused Awaiting Input",
            f"{action_type.replace('_', ' ').title()} is blocked from AI live-submit.",
            "",
            "Owner must complete this step directly on the official platform.",
            {"action_type": action_type},
        )
    if not official_link:
        return _result(
            False,
            False,
            "Submitted",
            "Paused Awaiting Input",
            "No official link is available for live-submit.",
            "",
            "Find or confirm the official claim URL.",
            {"action_type": action_type},
        )

    payload = {
        "action_type": action_type or "final_submit",
        "official_link": official_link,
        "credential_unlocked": credential_unlocked,
        "consent_created_at": consent.get("created_at"),
        "prepared_at": _utc_now(),
        "blocked_actions": sorted(DISALLOWED_LIVE_SUBMIT_ACTIONS),
        "safety_note": "Browser execution may fill low-risk prepared fields only; no payment, legal, tax, identity, wallet signing, or account-connection submit.",
    }
    return _result(
        True,
        True,
        "Processing",
        "Processing",
        "Low-risk live-submit is consented and staged for browser execution.",
        f"Official link staged: {official_link}",
        "Run browser execution for this prepared claim; verify result before marking received/paid.",
        payload,
    )


def _result(
    attempted: bool,
    allowed: bool,
    status: str,
    execution_status: str,
    note: str,
    proof_or_reference_note: str,
    next_action: str,
    payload: dict[str, Any],
) -> LiveSubmitResult:
    return LiveSubmitResult(
        attempted=attempted,
        allowed=allowed,
        status=status,
        execution_status=execution_status,
        note=note,
        proof_or_reference_note=proof_or_reference_note,
        next_action=next_action,
        payload_json=json.dumps(payload, ensure_ascii=True, sort_keys=True),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
