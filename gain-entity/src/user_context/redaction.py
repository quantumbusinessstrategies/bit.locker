from __future__ import annotations

from typing import Any


SENSITIVE_FIELD_NAMES = {
    "date_of_birth",
    "phone",
    "address_line_1",
    "address_line_2",
    "zip",
    "btc_address",
    "eth_address",
    "sol_address",
    "usdc_address",
}


def redact_user_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        section: {
            key: redact_value(key, value)
            for key, value in values.items()
        }
        for section, values in context.items()
        if isinstance(values, dict)
    }


def redact_value(field_name: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if field_name not in SENSITIVE_FIELD_NAMES:
        return text
    if "@" in text:
        local, _, domain = text.partition("@")
        return f"{_prefix(local)}@{domain}"
    if len(text) <= 4:
        return "****"
    return f"{_prefix(text)}...{text[-4:]}"


def _prefix(value: str) -> str:
    return value[:2] + "***" if len(value) > 2 else "***"

