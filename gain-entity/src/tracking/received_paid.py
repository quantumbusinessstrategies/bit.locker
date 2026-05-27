from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def received_paid_rows(conn: Any, limit: int = 500) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            rl.id,
            rl.claim_queue_id,
            o.title,
            o.url,
            rl.received_type,
            rl.estimated_value_usd,
            rl.destination,
            rl.notes,
            rl.received_at,
            cq.asset_type,
            cq.destination_type,
            cq.expected_delivery_method,
            cq.status
        FROM received_log rl
        LEFT JOIN claim_queue cq ON cq.id = rl.claim_queue_id
        LEFT JOIN opportunities o ON o.id = cq.opportunity_id
        ORDER BY rl.received_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def mark_received_paid(
    conn: Any,
    claim_queue_id: int,
    received_type: str,
    estimated_value_usd: float,
    destination: str,
    notes: str,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT id FROM received_log WHERE claim_queue_id=?",
        (claim_queue_id,),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE received_log
            SET received_type=?, estimated_value_usd=?, destination=?, notes=?, received_at=?
            WHERE claim_queue_id=?
            """,
            (received_type, estimated_value_usd, destination, notes, now, claim_queue_id),
        )
    else:
        conn.execute(
            """
            INSERT INTO received_log (
                claim_queue_id, received_type, estimated_value_usd,
                destination, notes, received_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (claim_queue_id, received_type, estimated_value_usd, destination, notes, now),
        )
    row = conn.execute("SELECT opportunity_id FROM claim_queue WHERE id=?", (claim_queue_id,)).fetchone()
    conn.execute("UPDATE claim_queue SET status='Received/Paid', updated_at=? WHERE id=?", (now, claim_queue_id))
    if row:
        conn.execute("UPDATE opportunities SET status='Received/Paid', updated_at=? WHERE id=?", (now, row["opportunity_id"]))
    conn.commit()
