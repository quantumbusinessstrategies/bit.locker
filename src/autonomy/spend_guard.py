from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_live_autorun_control(root_dir: Path) -> dict[str, Any]:
    path = root_dir / "data" / "autorun_control.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def apply_paid_mode_to_rules(rules: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    """Overlay the live owner-controlled Free/Paid toggle onto the static rules.

    paid_mode_enabled defaults to off, so when it is missing or false the
    pipeline stays free-only regardless of what config/rules.yaml says.
    """
    merged = dict(rules)
    paid_mode_enabled = bool(control.get("paid_mode_enabled"))
    merged["free_mode_only"] = not paid_mode_enabled
    merged["require_no_upfront_payment"] = not paid_mode_enabled
    return merged


def spend_cap_check(store: Any, control: dict[str, Any], cost_usd: float) -> tuple[bool, str]:
    """Owner-set hard spend cap. Never lets committed paid spend exceed max_spend_usd."""
    if cost_usd <= 0:
        return True, ""
    if not bool(control.get("paid_mode_enabled")):
        return False, "paid mode is off - free-only"
    cap = float(control.get("max_spend_usd") or 0)
    if cap <= 0:
        return False, "no spending cap set - paid items blocked until an owner sets max_spend_usd"
    committed = float(store.committed_paid_spend_usd())
    if committed + cost_usd > cap:
        return False, (
            f"would exceed spend cap (${committed:,.2f} committed + "
            f"${cost_usd:,.2f} > ${cap:,.2f} cap)"
        )
    return True, ""
