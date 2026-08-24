from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DISALLOWED_LIVE_SUBMIT_ACTIONS = {
    "payment_authorization",
    "purchase",
    "legal_agreement",
    "tax_action",
    "identity_verification",
    "wallet_signing",
    "account_connection",
}


@dataclass(frozen=True)
class SubmissionConsent:
    claim_queue_id: int
    allowed: bool
    mode: str
    consent_text: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SubmissionConsentStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_root(cls, root_dir: Path) -> "SubmissionConsentStore":
        return cls(root_dir / "data" / "submission_consent.json")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"items": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"items": {}}
        return payload if isinstance(payload, dict) else {"items": {}}

    def save_consent(self, consent: SubmissionConsent) -> None:
        payload = self.load()
        payload.setdefault("items", {})[str(consent.claim_queue_id)] = consent.to_dict()
        payload["updated_at"] = _utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def consent_for(self, claim_queue_id: int) -> dict[str, Any]:
        return dict(self.load().get("items", {}).get(str(claim_queue_id), {}))


def can_live_submit(action_type: str, risk_level: str, explicit_terms_checked: bool) -> tuple[bool, str]:
    if action_type in DISALLOWED_LIVE_SUBMIT_ACTIONS:
        return False, f"{action_type.replace('_', ' ')} remains owner-executed."
    if str(risk_level or "").lower() not in {"", "low", "unknown"}:
        return False, "Only low-risk prepared submissions can enter AI live-submit."
    if not explicit_terms_checked:
        return False, "Explicit live-submit consent checkbox is required."
    return True, "Eligible for consent-gated low-risk AI live-submit."


def new_consent(claim_queue_id: int, mode: str, consent_text: str) -> SubmissionConsent:
    return SubmissionConsent(
        claim_queue_id=claim_queue_id,
        allowed=True,
        mode=mode,
        consent_text=consent_text,
        created_at=_utc_now(),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
