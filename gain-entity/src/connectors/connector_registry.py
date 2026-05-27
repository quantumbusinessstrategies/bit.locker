from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ConnectorDefinition:
    key: str
    label: str
    context_section: str
    context_field: str
    supported_fields: list[str]
    sensitive_actions_blocked: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CONNECTORS = {
    "github": ConnectorDefinition(
        key="github",
        label="GitHub",
        context_section="accounts",
        context_field="github_username",
        supported_fields=["github_username", "basic_profile_fields"],
        sensitive_actions_blocked=["login", "accept_terms", "submit"],
    ),
    "google": ConnectorDefinition(
        key="google",
        label="Google",
        context_section="accounts",
        context_field="google_email",
        supported_fields=["google_email", "email", "basic_profile_fields"],
        sensitive_actions_blocked=["login", "identity_verification", "submit"],
    ),
    "microsoft": ConnectorDefinition(
        key="microsoft",
        label="Microsoft",
        context_section="accounts",
        context_field="microsoft_email",
        supported_fields=["microsoft_email", "email", "basic_profile_fields"],
        sensitive_actions_blocked=["login", "identity_verification", "submit"],
    ),
    "paypal": ConnectorDefinition(
        key="paypal",
        label="PayPal",
        context_section="accounts",
        context_field="paypal_email",
        supported_fields=["paypal_email", "payout_email"],
        sensitive_actions_blocked=["payment_authorization", "submit"],
    ),
    "amazon": ConnectorDefinition(
        key="amazon",
        label="Amazon",
        context_section="accounts",
        context_field="amazon_email",
        supported_fields=["email", "basic_profile_fields"],
        sensitive_actions_blocked=["purchase", "login", "submit"],
    ),
    "apple": ConnectorDefinition(
        key="apple",
        label="Apple",
        context_section="accounts",
        context_field="apple_email",
        supported_fields=["email", "basic_profile_fields"],
        sensitive_actions_blocked=["login", "payment_authorization", "submit"],
    ),
    "tiktok": ConnectorDefinition(
        key="tiktok",
        label="TikTok",
        context_section="accounts",
        context_field="tiktok_username",
        supported_fields=["basic_profile_fields"],
        sensitive_actions_blocked=["login", "submit"],
    ),
}


def connector_definitions() -> list[ConnectorDefinition]:
    return list(CONNECTORS.values())


def connector_for_requirement(requirement: str) -> ConnectorDefinition | None:
    lowered = str(requirement or "").lower()
    for connector in CONNECTORS.values():
        if connector.key in lowered or connector.label.lower() in lowered:
            return connector
    if "platform_login" in lowered or "connect" in lowered or "login" in lowered:
        return None
    return None
