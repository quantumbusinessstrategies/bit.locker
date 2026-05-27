from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


LIFECYCLE_STATES = [
    "discovered",
    "qualified",
    "needs_input",
    "ready_for_ai_work",
    "autofilling",
    "awaiting_final_approval",
    "submitted",
    "processing",
    "ready_to_accept",
    "received",
    "paid",
    "rejected",
    "expired",
    "dead_end",
]

TIME_WINDOWS = {
    "Today": 1,
    "3 Days": 3,
    "7 Days": 7,
    "30 Days": 30,
    "All": 0,
}


@dataclass(frozen=True)
class LifecycleItem:
    claim_queue_id: int | None
    opportunity_id: int
    title: str
    current_status: str
    last_status_update: str
    expected_value_usd: float
    expected_asset: str
    asset_type: str
    destination: str
    payout_method: str
    tracking_note: str
    followup_date: str
    received_date: str
    paid_date: str
    proof_or_reference_note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def rows_for_lifecycle(conn: Any, limit: int = 1000) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            o.id AS opportunity_id,
            o.title,
            o.status AS opportunity_status,
            o.updated_at AS opportunity_updated_at,
            o.real_asset_path,
            o.destination AS opportunity_destination,
            o.expected_delivery_method AS opportunity_delivery,
            cq.id AS claim_queue_id,
            cq.status AS claim_status,
            cq.input_status,
            cq.execution_status,
            cq.acceptance_status,
            cq.expected_value_usd,
            cq.what_this_gain_is,
            cq.gain_type,
            cq.asset_type,
            cq.destination,
            cq.destination_type,
            cq.asset_destination,
            cq.expected_delivery_method,
            cq.follow_up_tracking_step,
            cq.received_tracking_note,
            cq.official_link,
            cq.updated_at AS claim_updated_at,
            rl.received_at,
            rl.received_type,
            rl.destination AS received_destination,
            rl.notes AS received_notes,
            dl.created_at AS dead_end_at,
            dl.reason AS dead_end_reason
        FROM opportunities o
        LEFT JOIN claim_queue cq ON cq.opportunity_id = o.id
        LEFT JOIN received_log rl ON rl.claim_queue_id = cq.id
        LEFT JOIN dead_end_log dl ON dl.opportunity_id = o.id
        ORDER BY COALESCE(cq.updated_at, o.updated_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def build_lifecycle_items(rows: list[dict[str, Any]]) -> list[LifecycleItem]:
    return [_item_from_row(row) for row in rows]


def filter_lifecycle_items(items: list[LifecycleItem], window: str) -> list[LifecycleItem]:
    days = TIME_WINDOWS.get(window, 30)
    if days <= 0:
        return items
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days)
    filtered = []
    for item in items:
        followup = _parse_date(item.followup_date)
        if followup and followup <= cutoff:
            filtered.append(item)
    return filtered


def lifecycle_summary(items: list[LifecycleItem]) -> dict[str, Any]:
    return {
        "total_estimated_pending_value": _sum_value(
            item for item in items if item.current_status not in {"received", "paid", "rejected", "dead_end", "expired"}
        ),
        "submitted_value": _sum_value(item for item in items if item.current_status == "submitted"),
        "processing_value": _sum_value(item for item in items if item.current_status == "processing"),
        "received_value": _sum_value(item for item in items if item.current_status == "received"),
        "paid_value": _sum_value(item for item in items if item.current_status == "paid"),
        "rejected_value": _sum_value(item for item in items if item.current_status == "rejected"),
        "dead_ends": sum(1 for item in items if item.current_status == "dead_end"),
        "next_followups_due": sum(1 for item in items if _is_due(item.followup_date)),
    }


def _item_from_row(row: dict[str, Any]) -> LifecycleItem:
    current_status = _lifecycle_status(row)
    last_update = str(row.get("claim_updated_at") or row.get("opportunity_updated_at") or "")
    received_date = str(row.get("received_at") or "") if current_status in {"received", "paid"} else ""
    paid_date = received_date if current_status == "paid" else ""
    return LifecycleItem(
        claim_queue_id=row.get("claim_queue_id"),
        opportunity_id=int(row.get("opportunity_id") or 0),
        title=str(row.get("title") or "Untitled opportunity"),
        current_status=current_status,
        last_status_update=last_update,
        expected_value_usd=_number(row.get("expected_value_usd")),
        expected_asset=str(row.get("what_this_gain_is") or row.get("gain_type") or row.get("received_type") or ""),
        asset_type=str(row.get("asset_type") or row.get("gain_type") or row.get("received_type") or ""),
        destination=str(
            row.get("asset_destination")
            or row.get("destination")
            or row.get("received_destination")
            or row.get("opportunity_destination")
            or ""
        ),
        payout_method=str(row.get("destination_type") or row.get("expected_delivery_method") or row.get("opportunity_delivery") or ""),
        tracking_note=_tracking_note(row),
        followup_date=_followup_date(row, current_status),
        received_date=received_date,
        paid_date=paid_date,
        proof_or_reference_note=str(row.get("received_notes") or row.get("official_link") or row.get("real_asset_path") or ""),
    )


def _lifecycle_status(row: dict[str, Any]) -> str:
    status = str(row.get("claim_status") or row.get("opportunity_status") or "").strip()
    input_status = str(row.get("input_status") or "")
    execution_status = str(row.get("execution_status") or "")
    acceptance_status = str(row.get("acceptance_status") or "")
    asset_type = str(row.get("asset_type") or row.get("gain_type") or "").lower()
    if row.get("dead_end_at") or status == "Dead End":
        return "dead_end"
    if status == "Rejected":
        return "rejected"
    if status == "Received/Paid":
        return "paid" if _is_cash_like(asset_type) else "received"
    if row.get("received_at"):
        return "paid" if _is_cash_like(asset_type) else "received"
    if status == "Ready to Accept" or acceptance_status == "Ready to Accept":
        return "ready_to_accept"
    if status == "Submitted":
        return "submitted"
    if execution_status == "AI Working":
        return "autofilling"
    if status == "Approved" or execution_status == "Ready To Accept":
        return "processing"
    if input_status == "final_approval_required":
        return "awaiting_final_approval"
    if input_status == "ready_for_ai_work":
        return "ready_for_ai_work"
    if input_status in {"missing_shipping", "missing_payout", "needs_connect", "blocked"} or status in {"Needs Approval", "Connect Needed"}:
        return "needs_input"
    if status in {"Qualified", "AI Work Complete"}:
        return "qualified"
    return "discovered"


def _tracking_note(row: dict[str, Any]) -> str:
    if row.get("dead_end_reason"):
        return str(row["dead_end_reason"])
    return str(
        row.get("received_tracking_note")
        or row.get("follow_up_tracking_step")
        or row.get("received_notes")
        or row.get("official_link")
        or "Track status from the official source or dashboard queue."
    )


def _followup_date(row: dict[str, Any], current_status: str) -> str:
    if current_status in {"received", "paid", "rejected", "dead_end", "expired"}:
        return ""
    basis = _parse_date(str(row.get("claim_updated_at") or row.get("opportunity_updated_at") or ""))
    if not basis:
        basis = datetime.now(timezone.utc)
    days = 1 if current_status in {"submitted", "ready_to_accept", "awaiting_final_approval"} else 3
    return (basis + timedelta(days=days)).date().isoformat()


def _sum_value(items: Any) -> float:
    return round(sum(item.expected_value_usd for item in items), 2)


def _is_due(value: str) -> bool:
    parsed = _parse_date(value)
    if not parsed:
        return False
    return parsed.date() <= datetime.now(timezone.utc).date()


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        try:
            return datetime.fromisoformat(str(value) + "T00:00:00+00:00")
        except ValueError:
            return None


def _is_cash_like(asset_type: str) -> bool:
    return any(term in asset_type for term in ["cash", "payout", "rebate", "refund", "commission", "unclaimed"])


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return 0.0
