from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    log_path = args.log.resolve()
    end_at = time.time() + args.duration_seconds
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    log(log_path, "SAFE AUTONOMY LOOP START")
    log(
        log_path,
        "No external submissions, payments, purchases, legal/tax/identity actions, "
        "wallet signing, or login bypass will be performed.",
    )
    log(log_path, "COUNTS " + json.dumps(counts(root), sort_keys=True))

    cycle = 0
    while time.time() < end_at:
        cycle += 1
        remaining = int(end_at - time.time())
        log(log_path, f"CYCLE {cycle} START remaining_seconds={remaining}")
        run_step(
            log_path,
            root,
            env,
            "fetch_source_discovery",
            [
                sys.executable,
                "src/main.py",
                "--fetch-only",
                "--limit",
                str(args.limit),
                "--max-candidates-per-source",
                str(args.max_candidates_per_source),
            ],
            timeout=720,
        )
        if time.time() >= end_at:
            break
        run_step(
            log_path,
            root,
            env,
            "autonomy_pump_live_assist_safe",
            [sys.executable, "-c", pump_code(args.inspect_limit)],
            timeout=480,
        )
        run_step(
            log_path,
            root,
            env,
            "bulk_accept_local_safe_final_submit_only",
            [sys.executable, "-c", BULK_CODE],
            timeout=180,
        )
        run_step(
            log_path,
            root,
            env,
            "completion_sync",
            [sys.executable, "-c", COMPLETION_CODE],
            timeout=180,
        )
        log(log_path, "COUNTS " + json.dumps(counts(root), sort_keys=True))
        if time.time() < end_at:
            time.sleep(min(args.sleep_seconds, max(0, end_at - time.time())))

    log(log_path, "FINAL_SYNC_START")
    run_step(
        log_path,
        root,
        env,
        "final_completion_sync",
        [sys.executable, "-c", COMPLETION_CODE],
        timeout=180,
    )
    log(log_path, "FINAL_COUNTS " + json.dumps(counts(root), sort_keys=True))
    log(log_path, "SAFE AUTONOMY LOOP END")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run safe local autonomy passes for a bounded duration.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=1800)
    parser.add_argument("--limit", type=int, default=320)
    parser.add_argument("--max-candidates-per-source", type=int, default=12)
    parser.add_argument("--inspect-limit", type=int, default=30)
    parser.add_argument("--sleep-seconds", type=int, default=20)
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{utc_now()}] {message}\n")


def counts(root: Path) -> dict[str, object]:
    conn = sqlite3.connect(database_path(root))
    conn.row_factory = sqlite3.Row
    output: dict[str, object] = {}
    for table in ["opportunities", "claim_queue", "source_candidates", "approved_sources", "rejected_sources"]:
        output[table] = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
    output["claim_status"] = {
        row["status"]: row["c"]
        for row in conn.execute("SELECT status, COUNT(*) c FROM claim_queue GROUP BY status")
    }
    output["execution_status"] = {
        row["s"]: row["c"]
        for row in conn.execute(
            'SELECT COALESCE(execution_status, "") s, COUNT(*) c '
            'FROM claim_queue GROUP BY COALESCE(execution_status, "")'
        )
    }
    conn.close()
    return output


def database_path(root: Path) -> Path:
    configured = os.getenv("DATABASE_PATH")
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else root / path
    return root / "data" / "gain_entity.sqlite3"


def run_step(
    log_path: Path,
    root: Path,
    env: dict[str, str],
    label: str,
    command: list[str],
    *,
    timeout: int,
) -> int:
    log(log_path, f"START {label}")
    try:
        proc = subprocess.run(
            command,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        log(log_path, f"TIMEOUT {label} after {timeout}s")
        if exc.stdout:
            log(log_path, f"{label} STDOUT\n{str(exc.stdout)[-6000:]}")
        if exc.stderr:
            log(log_path, f"{label} STDERR\n{str(exc.stderr)[-3000:]}")
        return 124

    log(log_path, f"END {label} rc={proc.returncode}")
    if proc.stdout:
        log(log_path, f"{label} STDOUT\n{proc.stdout[-6000:]}")
    if proc.stderr:
        log(log_path, f"{label} STDERR\n{proc.stderr[-3000:]}")
    return int(proc.returncode)


def pump_code(inspect_limit: int) -> str:
    return f"""
from pathlib import Path
from autonomy.autonomy_pump import run_autonomy_pump
import os
DB = Path(os.getenv('DATABASE_PATH', 'data/gain_entity.sqlite3'))
summary = run_autonomy_pump(
    root_dir=Path('.').resolve(),
    database_path=DB,
    control={{'enabled': True, 'mode': 'Open-To-Everything', 'execution_mode': 'Live Assist'}},
    inspect_limit={int(inspect_limit)},
)
print(summary.to_dict())
"""


BULK_CODE = r"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from approval.final_approval_queue import build_final_approval_queue, rows_for_final_approval, approval_result_status, approval_result_note
from approval.submission_consent import SubmissionConsentStore, new_consent
from connectors.connector_status import apply_external_authorizations
from connectors.external_authorizations import external_authorization_rows
from execution.browser_execution import build_browser_execution_plan, execute_safe_official_form, record_browser_execution_run
from storage.sqlite_store import SQLiteStore
from user_context.user_context_store import UserContextStore
DB = Path(os.getenv('DATABASE_PATH', 'data/gain_entity.sqlite3'))
ROOT = Path('.').resolve()
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
items = build_final_approval_queue(rows_for_final_approval(conn, limit=1000))
safe_items = [item for item in items if item.safe_to_mark_submitted and item.final_action_type == 'final_submit']
now = datetime.now(timezone.utc).isoformat()
applied = 0
browser_attempted = 0
browser_submitted = 0
browser_blocked = 0
skipped_previous_browser_block = 0
consent_store = SubmissionConsentStore.for_root(ROOT)
context = apply_external_authorizations(UserContextStore.for_root(ROOT).load(), external_authorization_rows(ROOT))
for item in safe_items:
    detail = conn.execute(
        '''
        SELECT cq.*, o.title, o.url
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.id=?
        ''',
        (item.claim_queue_id,),
    ).fetchone()
    if detail:
        try:
            previous_payload = json.loads(str(detail['action_engine_json'] or '{}'))
        except json.JSONDecodeError:
            previous_payload = {}
        previous_browser = previous_payload.get('browser_execution') if isinstance(previous_payload, dict) else {}
        previous_status = str(previous_browser.get('status') or '') if isinstance(previous_browser, dict) else ''
        if previous_status.startswith('blocked') and not previous_browser.get('submitted'):
            skipped_previous_browser_block += 1
            continue
    status = approval_result_status(item.final_action_type, 'Approve Final Step')
    note = approval_result_note(item.final_action_type, 'Approve Final Step')
    execution_status = 'Processing' if status == 'Submitted' else status
    row = conn.execute('SELECT opportunity_id FROM claim_queue WHERE id=?', (item.claim_queue_id,)).fetchone()
    if not consent_store.consent_for(item.claim_queue_id).get('allowed'):
        consent_store.save_consent(new_consent(
            item.claim_queue_id,
            'Live Submit With Final Approval',
            'Owner authorized bounded safe-autonomy loop to live-submit low-risk final-submit packets only.',
        ))
    conn.execute(
        'UPDATE claim_queue SET status=?, execution_status=?, next_action=?, updated_at=? WHERE id=?',
        (status, execution_status, note, now, item.claim_queue_id),
    )
    if row:
        conn.execute('UPDATE opportunities SET status=?, updated_at=? WHERE id=?', (status, now, row['opportunity_id']))
    applied += 1
    if detail:
        detail_dict = dict(detail)
        plan = build_browser_execution_plan(detail_dict, context, 'Live Submit With Final Approval')
        result = execute_safe_official_form(
            plan,
            context,
            consent_store.consent_for(item.claim_queue_id),
            submit_external=True,
        )
        record_browser_execution_run(ROOT, plan, result.status, result.note)
        browser_attempted += 1
        browser_submitted += 1 if result.submitted else 0
        browser_blocked += 0 if result.submitted else 1
        existing = {}
        try:
            existing = json.loads(str(detail_dict.get('action_engine_json') or '{}'))
        except json.JSONDecodeError:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing['browser_execution'] = result.to_dict()
        existing['updated_at'] = datetime.now(timezone.utc).isoformat()
        next_status = 'Submitted' if result.submitted else 'Needs Approval'
        next_execution_status = 'Processing' if result.submitted else 'Paused Awaiting Input'
        conn.execute(
            '''
            UPDATE claim_queue
            SET status=?, execution_status=?, next_action=?, human_input_needed=?,
                ai_work_completed=COALESCE(NULLIF(?, ''), ai_work_completed),
                action_engine_json=?, last_execution_at=?, updated_at=?
            WHERE id=?
            ''',
            (
                next_status,
                next_execution_status,
                result.next_action,
                '' if result.submitted else result.next_action,
                result.note,
                json.dumps(existing, ensure_ascii=True, sort_keys=True),
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                item.claim_queue_id,
            ),
        )
conn.commit()
conn.close()
SQLiteStore(DB).normalize_required_inputs()
print({
    'bulk_safe_final_submit_applied': applied,
    'approval_items_seen': len(items),
    'sensitive_or_owner_only_left': len(items) - len(safe_items),
    'browser_attempted': browser_attempted,
    'browser_submitted': browser_submitted,
    'browser_blocked_or_paused': browser_blocked,
    'skipped_previous_browser_block': skipped_previous_browser_block,
})
"""


COMPLETION_CODE = r"""
import sqlite3
import os
from pathlib import Path
from autonomy.completion_engine import run_completion_engine_pass
from connectors.connector_status import apply_external_authorizations
from connectors.external_authorizations import external_authorization_rows
from user_context.user_context_store import UserContextStore
root = Path('.').resolve()
ctx = apply_external_authorizations(UserContextStore.for_root(root).load(), external_authorization_rows(root))
DB = Path(os.getenv('DATABASE_PATH', 'data/gain_entity.sqlite3'))
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
summary = run_completion_engine_pass(conn, ctx, mode='Live Assist', commit=True)
conn.close()
print(summary.to_dict())
"""


if __name__ == "__main__":
    raise SystemExit(main())
