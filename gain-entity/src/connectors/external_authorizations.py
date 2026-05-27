from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExternalAuthorizationProvider:
    key: str
    label: str
    category: str
    owner_link_url: str
    ai_can_use_for: list[str]
    blocked_actions: list[str]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExternalAuthorizationRecord:
    provider_key: str
    authorized: bool
    authorization_note: str
    authorized_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


EXTERNAL_AUTHORIZATION_PROVIDERS = [
    ExternalAuthorizationProvider(
        key="paypal",
        label="PayPal",
        category="Payout / payment account",
        owner_link_url="https://www.paypal.com/",
        ai_can_use_for=["payout email routing", "claim payout destination prep", "owner-approved payout handoff"],
        blocked_actions=["payment authorization", "purchase", "bank changes", "legal/tax submission"],
        note="Useful for receiving payouts. AI may not authorize payments or change financial settings.",
    ),
    ExternalAuthorizationProvider(
        key="stripe",
        label="Stripe",
        category="Payout / business account",
        owner_link_url="https://dashboard.stripe.com/",
        ai_can_use_for=["stripe email routing", "startup/business payout prep", "owner-approved payout handoff"],
        blocked_actions=["payment authorization", "bank account changes", "tax form submission"],
        note="Useful for payout/account routing. Tax and banking actions stay owner-controlled.",
    ),
    ExternalAuthorizationProvider(
        key="github",
        label="GitHub",
        category="Developer / startup credits",
        owner_link_url="https://github.com/login",
        ai_can_use_for=["developer offer prep", "GitHub username autofill", "owner-approved program navigation"],
        blocked_actions=["credential changes", "terms acceptance without approval", "paid plan purchase"],
        note="Useful for developer/student/startup offers after owner-authorized login.",
    ),
    ExternalAuthorizationProvider(
        key="google",
        label="Google",
        category="Email / cloud / startup credits",
        owner_link_url="https://accounts.google.com/",
        ai_can_use_for=["email-based prep", "Google startup/cloud offer prep", "owner-approved navigation"],
        blocked_actions=["identity verification", "payment authorization", "legal/tax submission"],
        note="Useful for Gmail/Google Cloud flows. Sensitive account prompts remain owner-controlled.",
    ),
    ExternalAuthorizationProvider(
        key="microsoft",
        label="Microsoft",
        category="Email / cloud / startup credits",
        owner_link_url="https://login.microsoftonline.com/",
        ai_can_use_for=["Microsoft startup/cloud offer prep", "email-based prep", "owner-approved navigation"],
        blocked_actions=["identity verification", "payment authorization", "legal/tax submission"],
        note="Useful for Microsoft startup/cloud offers after owner-authorized login.",
    ),
    ExternalAuthorizationProvider(
        key="amazon",
        label="Amazon / AWS",
        category="Shopping / cloud credits",
        owner_link_url="https://signin.aws.amazon.com/",
        ai_can_use_for=["AWS startup credit prep", "owner-approved application navigation"],
        blocked_actions=["purchase", "payment authorization", "terms acceptance without approval"],
        note="Useful for AWS Activate and startup credits. Purchases stay blocked.",
    ),
    ExternalAuthorizationProvider(
        key="apple",
        label="Apple",
        category="Account / settlement / digital assets",
        owner_link_url="https://appleid.apple.com/",
        ai_can_use_for=["Apple email/account routing", "settlement prep", "owner-approved navigation"],
        blocked_actions=["payment authorization", "identity verification", "account security changes"],
        note="Useful for Apple-related claims that require an account or contact email.",
    ),
    ExternalAuthorizationProvider(
        key="moonpay",
        label="MoonPay",
        category="Crypto on/off-ramp",
        owner_link_url="https://www.moonpay.com/",
        ai_can_use_for=["public wallet destination prep", "owner-approved crypto payout routing notes"],
        blocked_actions=["purchase", "sale", "payment authorization", "identity verification", "wallet signing"],
        note="AI may prepare public wallet routing only. Transactions, KYC, and signing stay owner-controlled.",
    ),
    ExternalAuthorizationProvider(
        key="recaptcha",
        label="reCAPTCHA / human verification",
        category="Human verification",
        owner_link_url="",
        ai_can_use_for=["detect human-verification blockers", "pause and ask owner at the exact step"],
        blocked_actions=["captcha solving bypass", "anti-bot circumvention"],
        note="AI must not bypass human verification. It can pause cleanly and resume after owner completion.",
    ),
]


class ExternalAuthorizationStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_root(cls, root_dir: Path) -> "ExternalAuthorizationStore":
        return cls(root_dir / "data" / "external_authorizations.json")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"providers": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"providers": {}}
        return payload if isinstance(payload, dict) else {"providers": {}}

    def records(self) -> dict[str, ExternalAuthorizationRecord]:
        providers = self.load().get("providers", {})
        output = {}
        if not isinstance(providers, dict):
            return output
        for key, payload in providers.items():
            if isinstance(payload, dict):
                output[key] = ExternalAuthorizationRecord(
                    provider_key=key,
                    authorized=bool(payload.get("authorized")),
                    authorization_note=str(payload.get("authorization_note") or ""),
                    authorized_at=str(payload.get("authorized_at") or ""),
                )
        return output

    def save_records(self, records: list[ExternalAuthorizationRecord]) -> None:
        payload = self.load()
        providers = payload.setdefault("providers", {})
        for record in records:
            providers[record.provider_key] = record.to_dict()
        payload["updated_at"] = _utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def external_authorization_rows(root_dir: Path) -> list[dict[str, Any]]:
    store = ExternalAuthorizationStore.for_root(root_dir)
    records = store.records()
    rows = []
    for provider in EXTERNAL_AUTHORIZATION_PROVIDERS:
        record = records.get(provider.key)
        row = provider.to_dict()
        row["authorized"] = bool(record.authorized) if record else False
        row["authorization_note"] = record.authorization_note if record else ""
        row["authorized_at"] = record.authorized_at if record else ""
        rows.append(row)
    return rows


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
