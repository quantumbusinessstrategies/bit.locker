from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
import copy

from connectors.connector_registry import ConnectorDefinition, connector_definitions
from user_context.schema import truthy


@dataclass(frozen=True)
class ConnectorStatus:
    key: str
    label: str
    connected: bool
    connection_state: str
    context_field: str
    value_present: bool
    status_note: str
    supported_fields: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def connector_statuses(user_context: dict[str, Any]) -> list[ConnectorStatus]:
    return [_status_for_connector(connector, user_context) for connector in connector_definitions()]


def connected_accounts(user_context: dict[str, Any]) -> list[ConnectorStatus]:
    return [status for status in connector_statuses(user_context) if status.connected]


def missing_connectors(user_context: dict[str, Any]) -> list[ConnectorStatus]:
    return [status for status in connector_statuses(user_context) if not status.connected]


def connector_status_map(user_context: dict[str, Any]) -> dict[str, ConnectorStatus]:
    return {status.key: status for status in connector_statuses(user_context)}


def apply_external_authorizations(
    user_context: dict[str, Any],
    authorization_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    enriched = copy.deepcopy(user_context)
    accounts = enriched.setdefault("accounts", {})
    if not isinstance(accounts, dict):
        accounts = {}
        enriched["accounts"] = accounts
    for row in authorization_rows:
        if not row.get("authorized"):
            continue
        key = str(row.get("key") or row.get("provider_key") or "").strip().lower()
        if not key:
            continue
        accounts[f"{key}_connected"] = True
        if key == "google":
            accounts["gmail_connected"] = True
        if key == "paypal" and not accounts.get("paypal_email"):
            accounts["paypal_email"] = _note_email(row.get("authorization_note"))
        accounts["connection_status"] = "connected externally"
    return enriched


def _status_for_connector(connector: ConnectorDefinition, user_context: dict[str, Any]) -> ConnectorStatus:
    section = user_context.get(connector.context_section, {})
    value = section.get(connector.context_field) if isinstance(section, dict) else ""
    explicit_connected = section.get(f"{connector.key}_connected") if isinstance(section, dict) else False
    if connector.key == "google" and isinstance(section, dict):
        explicit_connected = section.get("gmail_connected", explicit_connected)
    generic_status = str(user_context.get("accounts", {}).get("connection_status") or "").strip()
    value_present = bool(str(value or "").strip())
    connected = value_present or truthy(explicit_connected) or truthy(generic_status)
    state = _connection_state(value_present, explicit_connected, generic_status, connector)
    note = state if state != "Available for autofill" else "Reusable context present"
    return ConnectorStatus(
        key=connector.key,
        label=connector.label,
        connected=connected,
        connection_state=state,
        context_field=f"{connector.context_section}.{connector.context_field}",
        value_present=value_present,
        status_note=note,
        supported_fields=connector.supported_fields,
    )


def _connection_state(
    value_present: bool,
    explicit_connected: Any,
    generic_status: str,
    connector: ConnectorDefinition,
) -> str:
    generic = str(generic_status or "").strip().lower()
    if "final approval" in generic or "approval" in generic:
        return "Requires final approval"
    if truthy(explicit_connected):
        return "Connected externally" if not value_present else "Available for autofill"
    if value_present:
        return "Manual login needed" if "login" in connector.sensitive_actions_blocked else "Available for autofill"
    if truthy(generic_status):
        return "Connected externally"
    return "Not connected"


def _note_email(value: Any) -> str:
    text = str(value or "").strip()
    for token in text.replace(",", " ").split():
        if "@" in token and "." in token:
            return token.strip(" ;")
    return ""
