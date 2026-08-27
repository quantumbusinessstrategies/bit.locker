from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _reminders_path(root_dir: Path, username: str = "owner") -> Path:
    suffix = "" if username == "owner" else f"_{username}"
    return root_dir / "data" / f"cancel_reminders{suffix}.json"


def maybe_create_trial_cancel_reminder(
    root_dir: Path,
    claim_queue_id: int,
    title: str,
    converts_to_paid_trial: bool,
    trial_days_before_charge: int,
    link: str = "",
    username: str = "owner",
) -> bool:
    """Auto-create a cancel-by reminder the moment a free-trial item is submitted/received.

    Safety net for "free trial that converts to a paid charge unless cancelled" - fires
    regardless of whether a human approved it or the background loop auto-submitted it,
    so nobody has to remember to set this manually. Idempotent: never overwrites an
    existing reminder already logged for this claim.
    """
    if not converts_to_paid_trial or trial_days_before_charge <= 0:
        return False
    path = _reminders_path(root_dir, username)
    reminders: dict[str, dict[str, Any]] = {}
    if path.exists():
        try:
            reminders = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            reminders = {}
    key = str(claim_queue_id)
    if key in reminders:
        return False
    safety_margin_days = max(0, trial_days_before_charge - 1)
    cancel_by = (datetime.now(timezone.utc) + timedelta(days=safety_margin_days)).date().isoformat()
    reminders[key] = {
        "title": title,
        "cancel_by": cancel_by,
        "link": link,
        "note": "Auto-created: converts to a paid subscription/charge if not cancelled by this date.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reminders, indent=2), encoding="utf-8")
    return True
