from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discovery.diversity_guard import DiversityGuard
from discovery.source_graph import SourceGraph
from execution.action_engine import ActionEngine
from routing.destination_router import DestinationRouter
from user_context.required_inputs import detect_required_inputs, result_payload
from user_context.user_context_store import UserContextStore


class SQLiteStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    url TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_fetched_at TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_type, url)
                );

                CREATE TABLE IF NOT EXISTS opportunities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    summary TEXT,
                    content_text TEXT,
                    published_at TEXT,
                    fetched_at TEXT NOT NULL,
                    tags TEXT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    raw_json TEXT,
                    scorer_json TEXT,
                    status TEXT NOT NULL DEFAULT 'Found',
                    real_asset_path TEXT,
                    destination TEXT,
                    expected_delivery_method TEXT,
                    final_acceptance_step TEXT,
                    ai_work_possible_now TEXT,
                    ai_work_completed TEXT,
                    user_approval_needed TEXT,
                    upfront_payment_required INTEGER,
                    net_loss_possible INTEGER,
                    fastest_gain_score REAL,
                    highest_value_score REAL,
                    source_family TEXT,
                    category_family TEXT,
                    domain TEXT,
                    root_domain TEXT,
                    discovered_from TEXT,
                    discovery_depth INTEGER,
                    source_lineage TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    snippet TEXT,
                    discovery_method TEXT,
                    query TEXT,
                    domain TEXT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    raw_json TEXT,
                    score_json TEXT,
                    source_score_1_to_10 REAL,
                    expected_gain_potential_1_to_10 REAL,
                    risk_level TEXT,
                    freshness_score_1_to_10 REAL,
                    searchability_score_1_to_10 REAL,
                    login_required INTEGER,
                    payment_required INTEGER,
                    real_asset_path_strength_1_to_10 REAL,
                    real_asset_path_signal TEXT,
                    likely_source_type TEXT,
                    source_family TEXT,
                    category_family TEXT,
                    root_domain TEXT,
                    discovered_from TEXT,
                    discovery_depth INTEGER,
                    source_lineage TEXT,
                    status TEXT NOT NULL DEFAULT 'Found',
                    decision_reason TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approved_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_candidate_id INTEGER,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    source_type TEXT NOT NULL DEFAULT 'configured_url',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    score_json TEXT,
                    metadata TEXT,
                    approved_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(source_candidate_id) REFERENCES source_candidates(id)
                );

                CREATE TABLE IF NOT EXISTS rejected_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_candidate_id INTEGER,
                    title TEXT,
                    url TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    score_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(url, reason),
                    FOREIGN KEY(source_candidate_id) REFERENCES source_candidates(id)
                );

                CREATE TABLE IF NOT EXISTS source_discovery_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_started_at TEXT NOT NULL,
                    run_finished_at TEXT NOT NULL,
                    queries_run INTEGER NOT NULL,
                    candidates_discovered INTEGER NOT NULL,
                    candidates_saved INTEGER NOT NULL,
                    sources_auto_approved INTEGER NOT NULL,
                    sources_needing_approval INTEGER NOT NULL,
                    sources_rejected INTEGER NOT NULL,
                    errors_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS claim_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    opportunity_id INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    should_add_to_claim_queue INTEGER,
                    gain_type TEXT,
                    expected_value_usd REAL,
                    probability_score REAL,
                    probability_score_1_to_10 REAL,
                    risk_level TEXT,
                    time_to_gain TEXT,
                    time_to_gain_days REAL,
                    owner_effort_required TEXT,
                    owner_effort_minutes REAL,
                    effort_score_1_to_10 REAL,
                    ai_can_do_percentage REAL,
                    ai_can_do_percent REAL,
                    upfront_money_required INTEGER,
                    upfront_payment_required INTEGER,
                    could_produce_loss INTEGER,
                    net_loss_possible INTEGER,
                    required_user_action TEXT,
                    real_asset_path TEXT,
                    destination TEXT,
                    expected_delivery_method TEXT,
                    fastest_gain_score REAL,
                    highest_value_score REAL,
                    what_this_gain_is TEXT,
                    why_real_asset_value TEXT,
                    exact_next_step TEXT,
                    what_ai_can_do TEXT,
                    what_ai_already_prepared TEXT,
                    what_user_must_approve TEXT,
                    ai_work_possible_now TEXT,
                    ai_work_completed TEXT,
                    user_approval_needed TEXT,
                    copy_paste_form_answers TEXT,
                    claim_instructions TEXT,
                    official_link TEXT,
                    final_acceptance_step TEXT,
                    asset_landing TEXT,
                    follow_up_tracking_step TEXT,
                    recommended_status TEXT,
                    safety_notes TEXT,
                    destination_type TEXT,
                    asset_type TEXT,
                    acceptance_status TEXT,
                    asset_destination TEXT,
                    owner_input_required TEXT,
                    ai_next_action TEXT,
                    post_approval_action TEXT,
                    received_tracking_note TEXT,
                    execution_status TEXT,
                    estimated_completion_percent REAL,
                    estimated_time TEXT,
                    human_input_needed TEXT,
                    next_action TEXT,
                    action_engine_json TEXT,
                    input_status TEXT,
                    required_inputs TEXT,
                    available_inputs TEXT,
                    missing_inputs TEXT,
                    sensitive_inputs TEXT,
                    input_summary TEXT,
                    last_execution_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
                );

                CREATE TABLE IF NOT EXISTS reject_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    opportunity_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'Reject',
                    reason TEXT NOT NULL,
                    scorer_json TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(opportunity_id, status, reason),
                    FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
                );

                CREATE TABLE IF NOT EXISTS dead_end_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    opportunity_id INTEGER,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(opportunity_id) REFERENCES opportunities(id)
                );

                CREATE TABLE IF NOT EXISTS received_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    claim_queue_id INTEGER,
                    received_type TEXT,
                    estimated_value_usd REAL,
                    destination TEXT,
                    notes TEXT,
                    received_at TEXT NOT NULL,
                    FOREIGN KEY(claim_queue_id) REFERENCES claim_queue(id)
                );

                CREATE TABLE IF NOT EXISTS exploration_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_family TEXT NOT NULL UNIQUE,
                    priority_score REAL,
                    suggested_query TEXT,
                    reason TEXT,
                    status TEXT NOT NULL DEFAULT 'Explore',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_claim_queue_status ON claim_queue(status);
                CREATE INDEX IF NOT EXISTS idx_claim_queue_fastest ON claim_queue(time_to_gain_days);
                CREATE INDEX IF NOT EXISTS idx_claim_queue_value ON claim_queue(expected_value_usd);
                CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(status);
                CREATE INDEX IF NOT EXISTS idx_source_candidates_status ON source_candidates(status);
                CREATE INDEX IF NOT EXISTS idx_source_candidates_score ON source_candidates(source_score_1_to_10);
                """
            )
            self._ensure_opportunity_columns(conn)
            self._ensure_claim_queue_columns(conn)
            self._ensure_source_candidate_columns(conn)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_opportunities_source_family ON opportunities(source_family)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_opportunities_root_domain ON opportunities(root_domain)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_source_candidates_family ON source_candidates(source_family)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claim_queue_fastest_score ON claim_queue(fastest_gain_score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claim_queue_value_score ON claim_queue(highest_value_score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claim_queue_acceptance_status ON claim_queue(acceptance_status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claim_queue_destination_type ON claim_queue(destination_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claim_queue_execution_status ON claim_queue(execution_status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_claim_queue_input_status ON claim_queue(input_status)")
            conn.execute("UPDATE claim_queue SET status='Rejected' WHERE status='Reject'")
            conn.execute("UPDATE opportunities SET status='Rejected' WHERE status='Reject'")
            self.normalize_discovery_graph_metadata(conn=conn)
            self.refresh_exploration_queue(conn=conn)
            self.normalize_acceptance_routes(conn=conn)
            self.normalize_execution_state(conn=conn)
            self.normalize_required_inputs(conn=conn)

    def upsert_sources(self, source_records: list[dict[str, Any]]) -> None:
        now = _utc_now()
        with self._connect() as conn:
            for source in source_records:
                conn.execute(
                    """
                    INSERT INTO sources (
                        name, source_type, url, enabled, metadata, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_type, url)
                    DO UPDATE SET
                        name=excluded.name,
                        enabled=excluded.enabled,
                        metadata=excluded.metadata,
                        updated_at=excluded.updated_at
                    """,
                    (
                        source["name"],
                        source["source_type"],
                        source["url"],
                        1 if source.get("enabled", True) else 0,
                        _json(source.get("metadata", {})),
                        now,
                        now,
                    ),
                )

    def mark_sources_fetched(self, source_records: list[dict[str, Any]]) -> None:
        now = _utc_now()
        with self._connect() as conn:
            for source in source_records:
                conn.execute(
                    """
                    UPDATE sources
                    SET last_fetched_at=?, updated_at=?
                    WHERE source_type=? AND url=?
                    """,
                    (now, now, source["source_type"], source["url"]),
                )

    def save_candidate(self, candidate: Any) -> tuple[int, bool]:
        now = _utc_now()
        payload = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
        graph = SourceGraph().enrich_opportunity_payload(payload)
        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO opportunities (
                        source_name, source_type, title, url, summary, content_text,
                        published_at, fetched_at, tags, fingerprint, raw_json,
                        source_family, category_family, domain, root_domain,
                        discovered_from, discovery_depth, source_lineage,
                        status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Found', ?, ?)
                    """,
                    (
                        payload["source_name"],
                        payload["source_type"],
                        payload["title"],
                        payload["url"],
                        payload.get("summary", ""),
                        payload.get("content_text", ""),
                        payload.get("published_at"),
                        payload["fetched_at"],
                        _json(payload.get("tags", [])),
                        payload["fingerprint"],
                        _json(payload.get("raw", {})),
                        graph["source_family"],
                        graph["category_family"],
                        graph["domain"],
                        graph["root_domain"],
                        graph["discovered_from"],
                        graph["discovery_depth"],
                        graph["source_lineage"],
                        now,
                        now,
                    ),
                )
                return int(cursor.lastrowid), True
            except sqlite3.IntegrityError:
                cursor = conn.execute(
                    """
                    UPDATE opportunities
                    SET
                        fetched_at=?,
                        summary=?,
                        content_text=?,
                        raw_json=?,
                        source_family=?,
                        category_family=?,
                        domain=?,
                        root_domain=?,
                        discovered_from=?,
                        discovery_depth=?,
                        source_lineage=?,
                        updated_at=?
                    WHERE fingerprint=?
                    """,
                    (
                        payload["fetched_at"],
                        payload.get("summary", ""),
                        payload.get("content_text", ""),
                        _json(payload.get("raw", {})),
                        graph["source_family"],
                        graph["category_family"],
                        graph["domain"],
                        graph["root_domain"],
                        graph["discovered_from"],
                        graph["discovery_depth"],
                        graph["source_lineage"],
                        now,
                        payload["fingerprint"],
                    ),
                )
                if cursor.rowcount == 0:
                    raise
                row = conn.execute(
                    "SELECT id FROM opportunities WHERE fingerprint=?",
                    (payload["fingerprint"],),
                ).fetchone()
                return int(row["id"]), False

    def opportunity_needs_score(self, opportunity_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT scorer_json FROM opportunities WHERE id=?",
                (opportunity_id,),
            ).fetchone()
        return bool(row and not row["scorer_json"])

    def pending_opportunities(
        self,
        limit: int = 50,
        exclude_ids: set[int] | None = None,
    ) -> list[tuple[int, dict[str, Any], bool]]:
        exclude_ids = exclude_ids or set()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, source_name, source_type, title, url, summary,
                    content_text, published_at, fetched_at, tags, fingerprint, raw_json
                FROM opportunities
                WHERE scorer_json IS NULL
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (limit + len(exclude_ids),),
            ).fetchall()
        pending: list[tuple[int, dict[str, Any], bool]] = []
        for row in rows:
            opportunity_id = int(row["id"])
            if opportunity_id in exclude_ids:
                continue
            payload = dict(row)
            payload.pop("id", None)
            payload["tags"] = _loads(payload.get("tags")) if isinstance(payload.get("tags"), str) else payload.get("tags")
            payload["raw"] = _loads(payload.pop("raw_json", "{}"))
            pending.append((opportunity_id, payload, False))
            if len(pending) >= limit:
                break
        return pending

    def update_opportunity_score(self, opportunity_id: int, score: dict[str, Any], status: str) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE opportunities
                SET
                    scorer_json=?,
                    status=?,
                    real_asset_path=?,
                    destination=?,
                    expected_delivery_method=?,
                    upfront_payment_required=?,
                    net_loss_possible=?,
                    fastest_gain_score=?,
                    highest_value_score=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    _json(score),
                    status,
                    score.get("real_asset_path"),
                    score.get("destination"),
                    score.get("expected_delivery_method"),
                    _int_bool(score.get("upfront_payment_required", score.get("upfront_money_required"))),
                    _int_bool(score.get("net_loss_possible", score.get("could_produce_loss"))),
                    score.get("fastest_gain_score"),
                    score.get("highest_value_score"),
                    now,
                    opportunity_id,
                ),
            )

    def update_opportunity_prep(self, opportunity_id: int, prep: dict[str, Any]) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE opportunities
                SET
                    final_acceptance_step=?,
                    ai_work_possible_now=?,
                    ai_work_completed=?,
                    user_approval_needed=?,
                    expected_delivery_method=COALESCE(?, expected_delivery_method),
                    updated_at=?
                WHERE id=?
                """,
                (
                    prep.get("final_acceptance_step"),
                    prep.get("ai_work_possible_now", prep.get("what_ai_can_do")),
                    prep.get("ai_work_completed", prep.get("what_ai_already_prepared")),
                    prep.get("user_approval_needed", prep.get("what_user_must_approve")),
                    prep.get("expected_delivery_method"),
                    now,
                    opportunity_id,
                ),
            )

    def update_opportunity_status(self, opportunity_id: int, status: str) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE opportunities SET status=?, updated_at=? WHERE id=?",
                (status, now, opportunity_id),
            )

    def save_queue_item(
        self,
        opportunity_id: int,
        score: dict[str, Any],
        prep: dict[str, Any],
        status: str,
    ) -> tuple[int, bool]:
        now = _utc_now()
        with self._connect() as conn:
            try:
                values = self._queue_values(opportunity_id, status, score, prep, now, now)
                placeholders = ",".join("?" for _ in values)
                cursor = conn.execute(
                    f"""
                    INSERT INTO claim_queue (
                        opportunity_id, status, should_add_to_claim_queue, gain_type,
                        expected_value_usd, probability_score, probability_score_1_to_10,
                        risk_level, time_to_gain, time_to_gain_days, owner_effort_required,
                        owner_effort_minutes, effort_score_1_to_10, ai_can_do_percentage,
                        ai_can_do_percent, upfront_money_required, upfront_payment_required,
                        could_produce_loss, net_loss_possible, required_user_action,
                        real_asset_path, destination, expected_delivery_method,
                        fastest_gain_score, highest_value_score, what_this_gain_is,
                        why_real_asset_value, exact_next_step, what_ai_can_do,
                        what_ai_already_prepared, what_user_must_approve,
                        ai_work_possible_now, ai_work_completed, user_approval_needed,
                        copy_paste_form_answers, claim_instructions, official_link,
                        final_acceptance_step, asset_landing, follow_up_tracking_step,
                        recommended_status, safety_notes, destination_type, asset_type,
                        acceptance_status, asset_destination, owner_input_required,
                        ai_next_action, post_approval_action, received_tracking_note,
                        execution_status, estimated_completion_percent, estimated_time,
                        human_input_needed, next_action, action_engine_json,
                        last_execution_at,
                        created_at, updated_at
                    )
                    VALUES ({placeholders})
                    """,
                    values,
                )
                conn.execute(
                    """
                    UPDATE opportunities
                    SET
                        status=?,
                        final_acceptance_step=?,
                        ai_work_possible_now=?,
                        ai_work_completed=?,
                        user_approval_needed=?,
                        expected_delivery_method=COALESCE(?, expected_delivery_method),
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        status,
                        prep.get("final_acceptance_step"),
                        prep.get("ai_work_possible_now", prep.get("what_ai_can_do")),
                        prep.get("ai_work_completed", prep.get("what_ai_already_prepared")),
                        prep.get("user_approval_needed", prep.get("what_user_must_approve")),
                        prep.get("expected_delivery_method"),
                        now,
                        opportunity_id,
                    ),
                )
                return int(cursor.lastrowid), True
            except sqlite3.IntegrityError:
                values = self._queue_values(opportunity_id, status, score, prep, now, now)
                row = conn.execute(
                    "SELECT id FROM claim_queue WHERE opportunity_id=?",
                    (opportunity_id,),
                ).fetchone()
                conn.execute(
                    """
                    UPDATE claim_queue
                    SET
                        status=?,
                        should_add_to_claim_queue=?,
                        gain_type=?,
                        expected_value_usd=?,
                        probability_score=?,
                        probability_score_1_to_10=?,
                        risk_level=?,
                        time_to_gain=?,
                        time_to_gain_days=?,
                        owner_effort_required=?,
                        owner_effort_minutes=?,
                        effort_score_1_to_10=?,
                        ai_can_do_percentage=?,
                        ai_can_do_percent=?,
                        upfront_money_required=?,
                        upfront_payment_required=?,
                        could_produce_loss=?,
                        net_loss_possible=?,
                        required_user_action=?,
                        real_asset_path=?,
                        destination=?,
                        expected_delivery_method=?,
                        fastest_gain_score=?,
                        highest_value_score=?,
                        what_this_gain_is=?,
                        why_real_asset_value=?,
                        exact_next_step=?,
                        what_ai_can_do=?,
                        what_ai_already_prepared=?,
                        what_user_must_approve=?,
                        ai_work_possible_now=?,
                        ai_work_completed=?,
                        user_approval_needed=?,
                        copy_paste_form_answers=?,
                        claim_instructions=?,
                        official_link=?,
                        final_acceptance_step=?,
                        asset_landing=?,
                        follow_up_tracking_step=?,
                        recommended_status=?,
                        safety_notes=?,
                        destination_type=?,
                        asset_type=?,
                        acceptance_status=?,
                        asset_destination=?,
                        owner_input_required=?,
                        ai_next_action=?,
                        post_approval_action=?,
                        received_tracking_note=?,
                        execution_status=?,
                        estimated_completion_percent=?,
                        estimated_time=?,
                        human_input_needed=?,
                        next_action=?,
                        action_engine_json=?,
                        last_execution_at=?,
                        updated_at=?
                    WHERE opportunity_id=?
                    """,
                    (
                        values[1],
                        *values[2:-2],
                        now,
                        opportunity_id,
                    ),
                )
                conn.execute(
                    """
                    UPDATE opportunities
                    SET
                        status=?,
                        final_acceptance_step=?,
                        ai_work_possible_now=?,
                        ai_work_completed=?,
                        user_approval_needed=?,
                        expected_delivery_method=COALESCE(?, expected_delivery_method),
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        status,
                        prep.get("final_acceptance_step"),
                        prep.get("ai_work_possible_now", prep.get("what_ai_can_do")),
                        prep.get("ai_work_completed", prep.get("what_ai_already_prepared")),
                        prep.get("user_approval_needed", prep.get("what_user_must_approve")),
                        prep.get("expected_delivery_method"),
                        now,
                        opportunity_id,
                    ),
                )
                return int(row["id"]), False

    def log_rejection(
        self,
        opportunity_id: int,
        status: str,
        reasons: list[str],
        score: dict[str, Any],
    ) -> None:
        reason = "; ".join(reasons) or "Rejected by strict filter"
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO reject_log (
                    opportunity_id, status, reason, scorer_json, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (opportunity_id, status, reason, _json(score), now),
            )
            conn.execute(
                "UPDATE opportunities SET status=?, updated_at=? WHERE id=?",
                (status, now, opportunity_id),
            )
            conn.execute(
                "UPDATE claim_queue SET status=?, updated_at=? WHERE opportunity_id=?",
                (status, now, opportunity_id),
            )

    def log_dead_end(self, opportunity_id: int | None, reason: str) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dead_end_log (opportunity_id, reason, created_at)
                VALUES (?, ?, ?)
                """,
                (opportunity_id, reason, now),
            )
            if opportunity_id is not None:
                conn.execute(
                    "UPDATE opportunities SET status='Dead End', updated_at=? WHERE id=?",
                    (now, opportunity_id),
                )

    def update_claim_status(self, claim_queue_id: int, status: str) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE claim_queue SET status=?, updated_at=? WHERE id=?",
                (status, now, claim_queue_id),
            )
            row = conn.execute(
                "SELECT opportunity_id FROM claim_queue WHERE id=?",
                (claim_queue_id,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE opportunities SET status=?, updated_at=? WHERE id=?",
                    (status, now, row["opportunity_id"]),
                )
            if status == "Received/Paid":
                existing = conn.execute(
                    "SELECT id FROM received_log WHERE claim_queue_id=?",
                    (claim_queue_id,),
                ).fetchone()
                if not existing:
                    claim = conn.execute(
                        """
                        SELECT gain_type, expected_value_usd, destination
                        FROM claim_queue
                        WHERE id=?
                        """,
                        (claim_queue_id,),
                    ).fetchone()
                    conn.execute(
                        """
                        INSERT INTO received_log (
                            claim_queue_id, received_type, estimated_value_usd,
                            destination, notes, received_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            claim_queue_id,
                            claim["gain_type"] if claim else None,
                            claim["expected_value_usd"] if claim else None,
                            claim["destination"] if claim else None,
                            "Marked Received/Paid from dashboard or status control.",
                            now,
                        ),
                    )
            self.normalize_acceptance_routes(conn=conn)
            row = self._claim_row(conn, claim_queue_id)
            if row:
                result = ActionEngine().evaluate(dict(row))
                self.update_claim_execution(claim_queue_id, result, conn=conn)

    def export_csvs(self, exports_dir: Path) -> dict[str, Path]:
        exports_dir.mkdir(parents=True, exist_ok=True)
        exported: dict[str, Path] = {}
        for table in [
            "opportunities",
            "claim_queue",
            "reject_log",
            "dead_end_log",
            "received_log",
            "sources",
            "source_candidates",
            "approved_sources",
            "rejected_sources",
            "source_discovery_log",
            "exploration_queue",
        ]:
            output_path = exports_dir / f"{table}.csv"
            with self._connect() as conn, output_path.open("w", encoding="utf-8", newline="") as handle:
                cursor = conn.execute(f"SELECT * FROM {table}")
                writer = csv.writer(handle)
                writer.writerow([description[0] for description in cursor.description])
                writer.writerows(cursor.fetchall())
            exported[table] = output_path
        return exported

    def top_fastest(self, limit: int = 5) -> list[sqlite3.Row]:
        return self._fetch_queue(
            """
            WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later')
            ORDER BY cq.fastest_gain_score DESC, cq.time_to_gain_days ASC, cq.probability_score DESC
            LIMIT ?
            """,
            (limit,),
        )

    def top_highest_value(self, limit: int = 5) -> list[sqlite3.Row]:
        return self._fetch_queue(
            """
            WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later')
            ORDER BY cq.highest_value_score DESC, cq.expected_value_usd DESC, cq.probability_score DESC
            LIMIT ?
            """,
            (limit,),
        )

    def by_statuses(self, statuses: list[str], limit: int = 20) -> list[sqlite3.Row]:
        placeholders = ",".join("?" for _ in statuses)
        return self._fetch_queue(
            f"""
            WHERE cq.status IN ({placeholders})
            ORDER BY cq.expected_value_usd DESC, cq.created_at DESC
            LIMIT ?
            """,
            (*statuses, limit),
        )

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "opportunities": conn.execute("SELECT COUNT(*) AS n FROM opportunities").fetchone()["n"],
                "claim_queue": conn.execute("SELECT COUNT(*) AS n FROM claim_queue").fetchone()["n"],
                "reject_log": conn.execute("SELECT COUNT(*) AS n FROM reject_log").fetchone()["n"],
                "dead_end_log": conn.execute("SELECT COUNT(*) AS n FROM dead_end_log").fetchone()["n"],
                "received_log": conn.execute("SELECT COUNT(*) AS n FROM received_log").fetchone()["n"],
                "source_candidates": conn.execute("SELECT COUNT(*) AS n FROM source_candidates").fetchone()["n"],
                "approved_sources": conn.execute("SELECT COUNT(*) AS n FROM approved_sources").fetchone()["n"],
                "rejected_sources": conn.execute("SELECT COUNT(*) AS n FROM rejected_sources").fetchone()["n"],
            }

    def claim_status_count(self, statuses: list[str]) -> int:
        if not statuses:
            return 0
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            return int(
                conn.execute(
                    f"SELECT COUNT(*) AS n FROM claim_queue WHERE status IN ({placeholders})",
                    tuple(statuses),
                ).fetchone()["n"]
            )

    def known_source_urls(self) -> set[str]:
        urls: set[str] = set()
        with self._connect() as conn:
            for table in ["sources", "approved_sources", "source_candidates", "rejected_sources"]:
                if table in {"sources", "approved_sources"}:
                    rows = conn.execute(f"SELECT url FROM {table}").fetchall()
                else:
                    rows = conn.execute(f"SELECT url FROM {table}").fetchall()
                urls.update(str(row["url"]) for row in rows if row["url"])
        return urls

    def save_source_candidate(self, candidate: Any) -> tuple[int, bool]:
        payload = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
        graph = SourceGraph().enrich_source_candidate_payload(payload)
        now = _utc_now()
        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO source_candidates (
                        title, url, snippet, discovery_method, query, domain,
                        fingerprint, raw_json, source_family, category_family,
                        root_domain, discovered_from, discovery_depth, source_lineage,
                        status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Found', ?, ?)
                    """,
                    (
                        payload["title"],
                        payload["url"],
                        payload.get("snippet", ""),
                        payload.get("discovery_method", ""),
                        payload.get("query", ""),
                        payload.get("domain", ""),
                        payload["fingerprint"],
                        _json(payload.get("raw", {})),
                        graph["source_family"],
                        graph["category_family"],
                        graph["root_domain"],
                        graph["discovered_from"],
                        graph["discovery_depth"],
                        graph["source_lineage"],
                        now,
                        now,
                    ),
                )
                return int(cursor.lastrowid), True
            except sqlite3.IntegrityError:
                conn.execute(
                    """
                    UPDATE source_candidates
                    SET
                        source_family=COALESCE(NULLIF(source_family, ''), ?),
                        category_family=COALESCE(NULLIF(category_family, ''), ?),
                        root_domain=COALESCE(NULLIF(root_domain, ''), ?),
                        discovered_from=COALESCE(NULLIF(discovered_from, ''), ?),
                        discovery_depth=COALESCE(discovery_depth, ?),
                        source_lineage=COALESCE(NULLIF(source_lineage, ''), ?),
                        updated_at=?
                    WHERE fingerprint=?
                    """,
                    (
                        graph["source_family"],
                        graph["category_family"],
                        graph["root_domain"],
                        graph["discovered_from"],
                        graph["discovery_depth"],
                        graph["source_lineage"],
                        now,
                        payload["fingerprint"],
                    ),
                )
                row = conn.execute(
                    "SELECT id FROM source_candidates WHERE fingerprint=?",
                    (payload["fingerprint"],),
                ).fetchone()
                return int(row["id"]), False

    def source_candidate_needs_score(self, candidate_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT score_json FROM source_candidates WHERE id=?",
                (candidate_id,),
            ).fetchone()
        return bool(row and not row["score_json"])

    def pending_source_candidates(self, limit: int = 50) -> list[tuple[int, dict[str, Any]]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id, title, url, snippet, discovery_method, query, domain,
                    fingerprint, raw_json, created_at
                FROM source_candidates
                WHERE score_json IS NULL OR status='Found'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        pending: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            payload = dict(row)
            candidate_id = int(payload.pop("id"))
            payload["raw"] = _loads(payload.pop("raw_json", "{}"))
            payload["fetched_at"] = payload.pop("created_at")
            pending.append((candidate_id, payload))
        return pending

    def update_source_candidate_score(
        self,
        candidate_id: int,
        score: dict[str, Any],
        status: str,
        decision_reason: str,
    ) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE source_candidates
                SET
                    score_json=?,
                    source_score_1_to_10=?,
                    expected_gain_potential_1_to_10=?,
                    risk_level=?,
                    freshness_score_1_to_10=?,
                    searchability_score_1_to_10=?,
                    login_required=?,
                    payment_required=?,
                    real_asset_path_strength_1_to_10=?,
                    real_asset_path_signal=?,
                    likely_source_type=?,
                    status=?,
                    decision_reason=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    _json(score),
                    score.get("source_score_1_to_10"),
                    score.get("expected_gain_potential_1_to_10"),
                    score.get("risk_level"),
                    score.get("freshness_score_1_to_10"),
                    score.get("searchability_score_1_to_10"),
                    _int_bool(score.get("login_required")),
                    _int_bool(score.get("payment_required")),
                    score.get("real_asset_path_strength_1_to_10"),
                    score.get("real_asset_path_signal"),
                    score.get("likely_source_type", "configured_url"),
                    status,
                    decision_reason,
                    now,
                    candidate_id,
                ),
            )

    def approve_source_candidate(self, candidate_id: int, score: dict[str, Any]) -> bool:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    title, url, raw_json, source_family, category_family,
                    root_domain, discovered_from, discovery_depth, source_lineage
                FROM source_candidates
                WHERE id=?
                """,
                (candidate_id,),
            ).fetchone()
            if not row:
                return False
            metadata = {
                "source_candidate_id": candidate_id,
                "score": score,
                "auto_approved": True,
                "source_family": row["source_family"],
                "category_family": row["category_family"],
                "root_domain": row["root_domain"],
                "discovered_from": row["discovered_from"],
                "discovery_depth": row["discovery_depth"],
                "source_lineage": row["source_lineage"],
            }
            try:
                conn.execute(
                    """
                    INSERT INTO approved_sources (
                        source_candidate_id, name, url, source_type, enabled,
                        score_json, metadata, approved_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        row["title"],
                        row["url"],
                        score.get("likely_source_type", "configured_url"),
                        _json(score),
                        _json(metadata),
                        now,
                        now,
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                conn.execute(
                    """
                    UPDATE approved_sources
                    SET
                        name=?,
                        source_type=?,
                        enabled=1,
                        score_json=?,
                        metadata=?,
                        updated_at=?
                    WHERE url=?
                    """,
                    (
                        row["title"],
                        score.get("likely_source_type", "configured_url"),
                        _json(score),
                        _json(metadata),
                        now,
                        row["url"],
                    ),
                )
                return False

    def reject_source_candidate(self, candidate_id: int, reason: str, score: dict[str, Any]) -> None:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT title, url FROM source_candidates WHERE id=?",
                (candidate_id,),
            ).fetchone()
            if not row:
                return
            conn.execute(
                """
                INSERT OR IGNORE INTO rejected_sources (
                    source_candidate_id, title, url, reason, score_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (candidate_id, row["title"], row["url"], reason, _json(score), now),
            )

    def approved_source_records(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT name, url, source_type, enabled, metadata
                FROM approved_sources
                WHERE enabled=1
                ORDER BY updated_at DESC
                """
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            source_type = row["source_type"] or "configured_url"
            metadata = _loads(row["metadata"])
            records.append(
                {
                    "name": row["name"],
                    "source_type": source_type,
                    "url": row["url"],
                    "enabled": bool(row["enabled"]),
                    "metadata": metadata,
                }
            )
        return records

    def log_source_discovery(
        self,
        run_started_at: str,
        run_finished_at: str,
        queries_run: int,
        candidates_discovered: int,
        candidates_saved: int,
        sources_auto_approved: int,
        sources_needing_approval: int,
        sources_rejected: int,
        errors: list[str],
    ) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO source_discovery_log (
                    run_started_at, run_finished_at, queries_run, candidates_discovered,
                    candidates_saved, sources_auto_approved, sources_needing_approval,
                    sources_rejected, errors_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_started_at,
                    run_finished_at,
                    queries_run,
                    candidates_discovered,
                    candidates_saved,
                    sources_auto_approved,
                    sources_needing_approval,
                    sources_rejected,
                    _json(errors),
                    now,
                ),
            )

    def claim_items_by_status(self, statuses: list[str], limit: int = 25) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT cq.*, o.title, o.url
                FROM claim_queue cq
                JOIN opportunities o ON o.id = cq.opportunity_id
                WHERE cq.status IN ({placeholders})
                ORDER BY cq.updated_at ASC
                LIMIT ?
                """,
                (*statuses, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_claim_continuation(self, claim_queue_id: int, continuation: dict[str, Any]) -> None:
        now = _utc_now()
        status = continuation.get("recommended_status") or "Ready to Accept"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE claim_queue
                SET
                    status=?,
                    ai_work_completed=?,
                    ai_work_possible_now=?,
                    exact_next_step=?,
                    final_acceptance_step=?,
                    follow_up_tracking_step=?,
                    safety_notes=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    continuation.get("ai_work_completed"),
                    continuation.get("ai_work_possible_now"),
                    continuation.get("exact_next_step"),
                    continuation.get("final_acceptance_step"),
                    continuation.get("follow_up_tracking_step"),
                    continuation.get("safety_notes"),
                    now,
                    claim_queue_id,
                ),
            )
            row = conn.execute(
                "SELECT opportunity_id FROM claim_queue WHERE id=?",
                (claim_queue_id,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE opportunities
                    SET
                        status=?,
                        ai_work_completed=?,
                        ai_work_possible_now=?,
                        final_acceptance_step=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        status,
                        continuation.get("ai_work_completed"),
                        continuation.get("ai_work_possible_now"),
                        continuation.get("final_acceptance_step"),
                        now,
                        row["opportunity_id"],
                    ),
                )
            self.normalize_acceptance_routes(conn=conn)
            row = self._claim_row(conn, claim_queue_id)
            if row:
                result = ActionEngine().evaluate(dict(row))
                self.update_claim_execution(claim_queue_id, result, conn=conn)

    def normalize_acceptance_routes(self, conn: sqlite3.Connection | None = None) -> int:
        if conn is None:
            with self._connect() as owned_conn:
                return self.normalize_acceptance_routes(conn=owned_conn)

        rows = conn.execute(
            """
            SELECT cq.*, o.title, o.url
            FROM claim_queue cq
            JOIN opportunities o ON o.id = cq.opportunity_id
            """
        ).fetchall()
        router = DestinationRouter()
        updated = 0
        now = _utc_now()
        for row in rows:
            payload = dict(row)
            routing = router.route(payload)
            final_acceptance_step = row["final_acceptance_step"] or routing["final_acceptance_step"]
            current = {
                "destination_type": row["destination_type"],
                "asset_type": row["asset_type"],
                "acceptance_status": row["acceptance_status"],
                "asset_destination": row["asset_destination"],
                "owner_input_required": row["owner_input_required"],
                "ai_next_action": row["ai_next_action"],
                "post_approval_action": row["post_approval_action"],
                "received_tracking_note": row["received_tracking_note"],
                "final_acceptance_step": row["final_acceptance_step"],
            }
            target = {
                "destination_type": routing["destination_type"],
                "asset_type": routing["asset_type"],
                "acceptance_status": routing["acceptance_status"],
                "asset_destination": routing["asset_destination"],
                "owner_input_required": routing["owner_input_required"],
                "ai_next_action": routing["ai_next_action"],
                "post_approval_action": routing["post_approval_action"],
                "received_tracking_note": routing["received_tracking_note"],
                "final_acceptance_step": final_acceptance_step,
            }
            if current == target:
                continue
            conn.execute(
                """
                UPDATE claim_queue
                SET
                    destination_type=?,
                    asset_type=?,
                    acceptance_status=?,
                    asset_destination=?,
                    owner_input_required=?,
                    ai_next_action=?,
                    post_approval_action=?,
                    received_tracking_note=?,
                    final_acceptance_step=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    routing["destination_type"],
                    routing["asset_type"],
                    routing["acceptance_status"],
                    routing["asset_destination"],
                    routing["owner_input_required"],
                    routing["ai_next_action"],
                    routing["post_approval_action"],
                    routing["received_tracking_note"],
                    final_acceptance_step,
                    now,
                    row["id"],
                ),
            )
            updated += 1
        return updated

    def update_claim_execution(
        self,
        claim_queue_id: int,
        action_result: Any,
        conn: sqlite3.Connection | None = None,
        update_claim_status: bool = True,
    ) -> None:
        if conn is None:
            with self._connect() as owned_conn:
                self.update_claim_execution(
                    claim_queue_id,
                    action_result,
                    conn=owned_conn,
                    update_claim_status=update_claim_status,
                )
                return

        now = _utc_now()
        claim_status = getattr(action_result, "claim_status", None)
        if update_claim_status and claim_status:
            current = conn.execute(
                "SELECT status FROM claim_queue WHERE id=?",
                (claim_queue_id,),
            ).fetchone()
            if current and current["status"] != claim_status:
                conn.execute(
                    "UPDATE claim_queue SET status=?, updated_at=? WHERE id=?",
                    (claim_status, now, claim_queue_id),
                )
                opportunity = conn.execute(
                    "SELECT opportunity_id FROM claim_queue WHERE id=?",
                    (claim_queue_id,),
                ).fetchone()
                if opportunity:
                    conn.execute(
                        "UPDATE opportunities SET status=?, updated_at=? WHERE id=?",
                        (claim_status, now, opportunity["opportunity_id"]),
                    )

        conn.execute(
            """
            UPDATE claim_queue
            SET
                execution_status=?,
                estimated_completion_percent=?,
                estimated_time=?,
                human_input_needed=?,
                next_action=?,
                action_engine_json=?,
                ai_work_completed=COALESCE(NULLIF(?, ''), ai_work_completed),
                last_execution_at=?,
                updated_at=?
            WHERE id=?
            """,
            (
                getattr(action_result, "execution_status", "Execution Queue"),
                getattr(action_result, "estimated_completion_percent", 0),
                getattr(action_result, "estimated_time", ""),
                getattr(action_result, "human_input_needed", ""),
                getattr(action_result, "next_action", ""),
                getattr(action_result, "action_engine_json", "{}"),
                getattr(action_result, "ai_work_completed", ""),
                now,
                now,
                claim_queue_id,
            ),
        )

    def normalize_execution_state(self, conn: sqlite3.Connection | None = None) -> int:
        if conn is None:
            with self._connect() as owned_conn:
                return self.normalize_execution_state(conn=owned_conn)

        rows = conn.execute(
            """
            SELECT cq.*, o.title, o.url
            FROM claim_queue cq
            JOIN opportunities o ON o.id = cq.opportunity_id
            """
        ).fetchall()
        engine = ActionEngine()
        updated = 0
        for row in rows:
            if str(row["status"] or "") in {
                "Submitted",
                "Processing",
                "Received/Paid",
                "Reject",
                "Rejected",
                "Dead End",
                "Paid Mode Later",
            }:
                continue
            payload = dict(row)
            result = engine.evaluate(payload)
            current = {
                "execution_status": row["execution_status"],
                "estimated_completion_percent": row["estimated_completion_percent"],
                "estimated_time": row["estimated_time"],
                "human_input_needed": row["human_input_needed"],
                "next_action": row["next_action"],
            }
            target = {
                "execution_status": result.execution_status,
                "estimated_completion_percent": result.estimated_completion_percent,
                "estimated_time": result.estimated_time,
                "human_input_needed": result.human_input_needed,
                "next_action": result.next_action,
            }
            if current == target and row["action_engine_json"]:
                continue
            self.update_claim_execution(
                int(row["id"]),
                result,
                conn=conn,
                update_claim_status=False,
            )
            updated += 1
        return updated

    def normalize_required_inputs(self, conn: sqlite3.Connection | None = None) -> int:
        if conn is None:
            with self._connect() as owned_conn:
                return self.normalize_required_inputs(conn=owned_conn)

        root_dir = self.database_path.parent.parent
        context = UserContextStore.for_root(root_dir).load()
        rows = conn.execute(
            """
            SELECT cq.*, o.title, o.url
            FROM claim_queue cq
            JOIN opportunities o ON o.id = cq.opportunity_id
            """
        ).fetchall()
        updated = 0
        now = _utc_now()
        for row in rows:
            if str(row["status"] or "") in {
                "Submitted",
                "Processing",
                "Received/Paid",
                "Reject",
                "Rejected",
                "Dead End",
                "Paid Mode Later",
            }:
                continue
            payload = dict(row)
            result = result_payload(detect_required_inputs(payload, context))
            current = {
                "input_status": row["input_status"],
                "required_inputs": row["required_inputs"],
                "available_inputs": row["available_inputs"],
                "missing_inputs": row["missing_inputs"],
                "sensitive_inputs": row["sensitive_inputs"],
                "input_summary": row["input_summary"],
            }
            if current == result:
                continue
            conn.execute(
                """
                UPDATE claim_queue
                SET
                    input_status=?,
                    required_inputs=?,
                    available_inputs=?,
                    missing_inputs=?,
                    sensitive_inputs=?,
                    input_summary=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    result["input_status"],
                    result["required_inputs"],
                    result["available_inputs"],
                    result["missing_inputs"],
                    result["sensitive_inputs"],
                    result["input_summary"],
                    now,
                    row["id"],
                ),
            )
            updated += 1
        return updated

    def _claim_row(self, conn: sqlite3.Connection, claim_queue_id: int) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT cq.*, o.title, o.url
            FROM claim_queue cq
            JOIN opportunities o ON o.id = cq.opportunity_id
            WHERE cq.id=?
            """,
            (claim_queue_id,),
        ).fetchone()

    def normalize_discovery_graph_metadata(self, conn: sqlite3.Connection | None = None) -> int:
        if conn is None:
            with self._connect() as owned_conn:
                return self.normalize_discovery_graph_metadata(conn=owned_conn)

        graph = SourceGraph()
        updated = 0
        now = _utc_now()
        opportunity_rows = conn.execute(
            """
            SELECT
                id, source_name, source_type, title, url, summary, content_text,
                raw_json, source_family, category_family, domain, root_domain,
                discovered_from, discovery_depth, source_lineage
            FROM opportunities
            """
        ).fetchall()
        for row in opportunity_rows:
            payload = dict(row)
            payload["raw"] = payload.get("raw_json")
            target = graph.enrich_opportunity_payload(payload)
            current = {key: row[key] for key in target}
            if current == target:
                continue
            conn.execute(
                """
                UPDATE opportunities
                SET
                    source_family=?,
                    category_family=?,
                    domain=?,
                    root_domain=?,
                    discovered_from=?,
                    discovery_depth=?,
                    source_lineage=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    target["source_family"],
                    target["category_family"],
                    target["domain"],
                    target["root_domain"],
                    target["discovered_from"],
                    target["discovery_depth"],
                    target["source_lineage"],
                    now,
                    row["id"],
                ),
            )
            updated += 1

        candidate_rows = conn.execute(
            """
            SELECT
                id, title, url, snippet, discovery_method, query, domain,
                raw_json, source_family, category_family, root_domain,
                discovered_from, discovery_depth, source_lineage
            FROM source_candidates
            """
        ).fetchall()
        for row in candidate_rows:
            payload = dict(row)
            payload["raw"] = payload.get("raw_json")
            target = graph.enrich_source_candidate_payload(payload)
            current = {
                key: row[key]
                for key in [
                    "source_family",
                    "category_family",
                    "root_domain",
                    "discovered_from",
                    "discovery_depth",
                    "source_lineage",
                ]
            }
            compare_target = {key: target[key] for key in current}
            if current == compare_target:
                continue
            conn.execute(
                """
                UPDATE source_candidates
                SET
                    source_family=?,
                    category_family=?,
                    root_domain=?,
                    discovered_from=?,
                    discovery_depth=?,
                    source_lineage=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    target["source_family"],
                    target["category_family"],
                    target["root_domain"],
                    target["discovered_from"],
                    target["discovery_depth"],
                    target["source_lineage"],
                    now,
                    row["id"],
                ),
            )
            updated += 1
        return updated

    def refresh_exploration_queue(self, conn: sqlite3.Connection | None = None) -> int:
        if conn is None:
            with self._connect() as owned_conn:
                return self.refresh_exploration_queue(conn=owned_conn)

        rows = conn.execute(
            """
            SELECT
                cq.id, cq.status, o.title, o.url, cq.gain_type,
                cq.expected_value_usd, cq.probability_score_1_to_10,
                cq.risk_level, cq.time_to_gain_days, cq.effort_score_1_to_10,
                cq.ai_can_do_percent, cq.fastest_gain_score, cq.highest_value_score,
                o.source_family, o.category_family, o.domain, o.root_domain,
                o.discovered_from, o.discovery_depth, o.source_lineage
            FROM claim_queue cq
            JOIN opportunities o ON o.id = cq.opportunity_id
            WHERE cq.status NOT IN ('Reject', 'Rejected', 'Dead End', 'Paid Mode Later')
            """
        ).fetchall()
        queue = DiversityGuard().analyze(list(rows))["exploration_queue"]
        now = _utc_now()
        updated = 0
        for item in queue:
            conn.execute(
                """
                INSERT INTO exploration_queue (
                    category_family, priority_score, suggested_query,
                    reason, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(category_family)
                DO UPDATE SET
                    priority_score=excluded.priority_score,
                    suggested_query=excluded.suggested_query,
                    reason=excluded.reason,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    item["category_family"],
                    item["priority_score"],
                    item["suggested_query"],
                    item["reason"],
                    item["status"],
                    now,
                    now,
                ),
            )
            updated += 1
        return updated

    def exploration_queue_records(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT category_family, priority_score, suggested_query, reason, status
                FROM exploration_queue
                WHERE status='Explore'
                ORDER BY priority_score DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _fetch_queue(self, where_sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        query = f"""
            SELECT
                cq.id,
                cq.status,
                o.title,
                o.url,
                cq.gain_type,
                cq.expected_value_usd,
                cq.probability_score,
                cq.probability_score_1_to_10,
                cq.risk_level,
                cq.time_to_gain,
                cq.time_to_gain_days,
                cq.owner_effort_minutes,
                cq.effort_score_1_to_10,
                cq.ai_can_do_percentage,
                cq.ai_can_do_percent,
                cq.fastest_gain_score,
                cq.highest_value_score,
                cq.required_user_action,
                cq.real_asset_path,
                cq.exact_next_step,
                cq.official_link,
                cq.final_acceptance_step,
                cq.expected_delivery_method,
                cq.destination,
                cq.destination_type,
                cq.asset_type,
                cq.acceptance_status,
                cq.asset_destination,
                cq.owner_input_required,
                cq.ai_next_action,
                cq.post_approval_action,
                cq.received_tracking_note,
                cq.execution_status,
                cq.estimated_completion_percent,
                cq.estimated_time,
                cq.human_input_needed,
                cq.next_action,
                cq.last_execution_at,
                o.source_family,
                o.category_family,
                o.domain,
                o.root_domain,
                o.discovered_from,
                o.discovery_depth,
                o.source_lineage
            FROM claim_queue cq
            JOIN opportunities o ON o.id = cq.opportunity_id
            {where_sql}
        """
        with self._connect() as conn:
            return list(conn.execute(query, params).fetchall())

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_opportunity_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(opportunities)").fetchall()
        }
        columns = {
            "real_asset_path": "TEXT",
            "destination": "TEXT",
            "expected_delivery_method": "TEXT",
            "final_acceptance_step": "TEXT",
            "ai_work_possible_now": "TEXT",
            "ai_work_completed": "TEXT",
            "user_approval_needed": "TEXT",
            "upfront_payment_required": "INTEGER",
            "net_loss_possible": "INTEGER",
            "fastest_gain_score": "REAL",
            "highest_value_score": "REAL",
            "source_family": "TEXT",
            "category_family": "TEXT",
            "domain": "TEXT",
            "root_domain": "TEXT",
            "discovered_from": "TEXT",
            "discovery_depth": "INTEGER",
            "source_lineage": "TEXT",
        }
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE opportunities ADD COLUMN {name} {ddl}")

    def _ensure_source_candidate_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(source_candidates)").fetchall()
        }
        columns = {
            "source_family": "TEXT",
            "category_family": "TEXT",
            "root_domain": "TEXT",
            "discovered_from": "TEXT",
            "discovery_depth": "INTEGER",
            "source_lineage": "TEXT",
        }
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE source_candidates ADD COLUMN {name} {ddl}")

    def _ensure_claim_queue_columns(self, conn: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(claim_queue)").fetchall()
        }
        columns = {
            "should_add_to_claim_queue": "INTEGER",
            "probability_score_1_to_10": "REAL",
            "effort_score_1_to_10": "REAL",
            "ai_can_do_percent": "REAL",
            "upfront_payment_required": "INTEGER",
            "net_loss_possible": "INTEGER",
            "expected_delivery_method": "TEXT",
            "fastest_gain_score": "REAL",
            "highest_value_score": "REAL",
            "what_this_gain_is": "TEXT",
            "why_real_asset_value": "TEXT",
            "ai_work_possible_now": "TEXT",
            "ai_work_completed": "TEXT",
            "user_approval_needed": "TEXT",
            "official_link": "TEXT",
            "recommended_status": "TEXT",
            "destination_type": "TEXT",
            "asset_type": "TEXT",
            "acceptance_status": "TEXT",
            "asset_destination": "TEXT",
            "owner_input_required": "TEXT",
            "ai_next_action": "TEXT",
            "post_approval_action": "TEXT",
            "received_tracking_note": "TEXT",
            "execution_status": "TEXT",
            "estimated_completion_percent": "REAL",
            "estimated_time": "TEXT",
            "human_input_needed": "TEXT",
            "next_action": "TEXT",
            "action_engine_json": "TEXT",
            "input_status": "TEXT",
            "required_inputs": "TEXT",
            "available_inputs": "TEXT",
            "missing_inputs": "TEXT",
            "sensitive_inputs": "TEXT",
            "input_summary": "TEXT",
            "last_execution_at": "TEXT",
        }
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE claim_queue ADD COLUMN {name} {ddl}")

    def _queue_values(
        self,
        opportunity_id: int,
        status: str,
        score: dict[str, Any],
        prep: dict[str, Any],
        created_at: str,
        updated_at: str,
    ) -> tuple[Any, ...]:
        probability = score.get("probability_score_1_to_10", score.get("probability_score"))
        ai_percent = score.get("ai_can_do_percent", score.get("ai_can_do_percentage"))
        upfront = score.get("upfront_payment_required", score.get("upfront_money_required"))
        loss = score.get("net_loss_possible", score.get("could_produce_loss"))
        ai_possible = prep.get("ai_work_possible_now", prep.get("what_ai_can_do"))
        ai_completed = prep.get("ai_work_completed", prep.get("what_ai_already_prepared"))
        approval_needed = prep.get("user_approval_needed", prep.get("what_user_must_approve"))
        routing_payload = {
            **score,
            **prep,
            "status": status,
            "gain_type": score.get("gain_type"),
            "destination": score.get("destination"),
            "asset_landing": prep.get("asset_landing") or score.get("destination"),
            "expected_delivery_method": prep.get("expected_delivery_method") or score.get("expected_delivery_method"),
            "ai_work_possible_now": ai_possible,
            "ai_work_completed": ai_completed,
            "user_approval_needed": approval_needed,
            "official_link": prep.get("official_link") or score.get("real_asset_path"),
        }
        routing = DestinationRouter().route(routing_payload)
        action_result = ActionEngine().evaluate({**routing_payload, **routing})
        return (
            opportunity_id,
            status,
            _int_bool(score.get("should_add_to_claim_queue")),
            score.get("gain_type"),
            score.get("expected_value_usd"),
            probability,
            probability,
            score.get("risk_level"),
            score.get("time_to_gain"),
            score.get("time_to_gain_days"),
            score.get("owner_effort_required"),
            score.get("owner_effort_minutes"),
            score.get("effort_score_1_to_10"),
            ai_percent,
            ai_percent,
            _int_bool(upfront),
            _int_bool(upfront),
            _int_bool(loss),
            _int_bool(loss),
            score.get("required_user_action"),
            score.get("real_asset_path"),
            score.get("destination"),
            prep.get("expected_delivery_method") or score.get("expected_delivery_method"),
            score.get("fastest_gain_score"),
            score.get("highest_value_score"),
            prep.get("what_this_gain_is") or score.get("summary"),
            prep.get("why_real_asset_value") or prep.get("why_it_may_produce_real_asset_value"),
            prep.get("exact_next_step"),
            ai_possible,
            ai_completed,
            approval_needed,
            ai_possible,
            ai_completed,
            approval_needed,
            prep.get("copy_paste_form_answers"),
            prep.get("claim_instructions"),
            prep.get("official_link") or score.get("real_asset_path"),
            prep.get("final_acceptance_step"),
            prep.get("asset_landing") or score.get("destination"),
            prep.get("follow_up_tracking_step"),
            prep.get("recommended_status"),
            prep.get("safety_notes"),
            routing["destination_type"],
            routing["asset_type"],
            routing["acceptance_status"],
            routing["asset_destination"],
            routing["owner_input_required"],
            routing["ai_next_action"],
            routing["post_approval_action"],
            routing["received_tracking_note"],
            action_result.execution_status,
            action_result.estimated_completion_percent,
            action_result.estimated_time,
            action_result.human_input_needed,
            action_result.next_action,
            action_result.action_engine_json,
            updated_at,
            created_at,
            updated_at,
        )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def _loads(value: Any) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}


def _int_bool(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    return 1 if str(value).strip().lower() in {"1", "true", "yes", "y", "required"} else 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
