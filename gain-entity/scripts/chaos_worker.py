from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    os.chdir(root)
    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from app import dashboard

    log_path = args.log.resolve()
    status_path = root / "data" / "chaos_worker_status.json"
    end_at = time.time() + args.duration_seconds if args.duration_seconds > 0 else None

    control = dashboard._load_chaos_control()
    if args.enable:
        control.update(
            {
                "enabled": True,
                "use_vault": args.use_vault,
                "low_risk_live_submit": args.low_risk_live_submit,
                "risk_on": args.risk_on,
                "deep_scan": args.deep_scan,
                "interval_seconds": args.interval_seconds,
                "worker_started_at": utc_now(),
                "worker_pid": os.getpid(),
            }
        )
        dashboard._save_chaos_control(control)

    write_status(
        status_path,
        {
            "state": "running",
            "pid": os.getpid(),
            "started_at": utc_now(),
            "last_message": "CHAOS worker started.",
        },
    )
    log(log_path, "CHAOS WORKER START")
    log(log_path, "Controls are read from data/chaos_mode.json. Disable CHAOS MODE to stop gracefully.")
    cycles = 0
    exit_reason = "duration elapsed"
    try:
        while True:
            if end_at is not None and time.time() >= end_at:
                exit_reason = "duration elapsed"
                break

            control = dashboard._load_chaos_control()
            if not control.get("enabled") and not args.run_once:
                exit_reason = "CHAOS MODE disabled"
                break

            force_run = bool(args.run_once and cycles == 0)
            should_run, reason = dashboard._chaos_should_run(control, force_run=force_run)
            write_status(
                status_path,
                {
                    "state": "waiting" if not should_run else "running_cycle",
                    "pid": os.getpid(),
                    "updated_at": utc_now(),
                    "last_message": reason,
                    "cycles": cycles,
                },
            )
            if should_run:
                log(log_path, f"CYCLE {cycles + 1} START {json.dumps(worker_flags(control, args), sort_keys=True)}")
                with dashboard.connect() as conn:
                    result = dashboard._run_chaos_cycle(conn, **worker_flags(control, args))
                    dashboard._record_chaos_result(control, result)
                cycles += 1
                log(log_path, f"CYCLE {cycles} END submitted_external={int(result.get('submitted_external') or 0)}")
                write_status(
                    status_path,
                    {
                        "state": "cycle_complete",
                        "pid": os.getpid(),
                        "updated_at": utc_now(),
                        "cycles": cycles,
                        "submitted_external": int(result.get("submitted_external") or 0),
                        "last_result": safe_result_summary(result),
                    },
                )
                if args.run_once:
                    exit_reason = "one cycle complete"
                    break

            sleep_for = max(5, min(int(control.get("interval_seconds") or args.interval_seconds), 60))
            if end_at is not None:
                sleep_for = min(sleep_for, max(0, int(end_at - time.time())))
            if sleep_for <= 0:
                continue
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        exit_reason = "keyboard interrupt"
    except Exception as exc:  # pragma: no cover - status/log path for operator recovery.
        exit_reason = f"error: {type(exc).__name__}: {exc}"
        log(log_path, "ERROR " + exit_reason)
        write_status(
            status_path,
            {
                "state": "error",
                "pid": os.getpid(),
                "updated_at": utc_now(),
                "last_message": exit_reason,
                "cycles": cycles,
            },
        )
        raise
    finally:
        if args.run_once:
            try:
                control = dashboard._load_chaos_control()
                control.update({"enabled": False, "worker_run_once_completed_at": utc_now()})
                dashboard._save_chaos_control(control)
            except Exception:
                pass
        log(log_path, f"CHAOS WORKER END reason={exit_reason} cycles={cycles}")
        write_status(
            status_path,
            {
                "state": "stopped",
                "pid": os.getpid(),
                "updated_at": utc_now(),
                "last_message": exit_reason,
                "cycles": cycles,
            },
        )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the QuantumGains CHAOS automation worker outside Streamlit.")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--log", type=Path, default=Path("data/chaos_worker.log"))
    parser.add_argument("--duration-seconds", type=int, default=3600, help="0 means run until disabled.")
    parser.add_argument("--interval-seconds", type=int, default=120)
    parser.add_argument("--enable", action="store_true", help="Turn CHAOS MODE on before starting the loop.")
    parser.add_argument("--run-once", action="store_true", help="Run one cycle immediately, then exit.")
    parser.add_argument("--use-vault", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--low-risk-live-submit", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--risk-on", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--deep-scan", action=argparse.BooleanOptionalAction, default=False)
    return parser.parse_args()


def worker_flags(control: dict[str, Any], args: argparse.Namespace) -> dict[str, bool]:
    return {
        "use_vault": bool(control.get("use_vault", args.use_vault)),
        "low_risk_live_submit": bool(control.get("low_risk_live_submit", args.low_risk_live_submit)),
        "risk_on": bool(control.get("risk_on", args.risk_on)),
        "deep_scan": bool(control.get("deep_scan", args.deep_scan)),
    }


def safe_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    after = result.get("snapshot_after") if isinstance(result.get("snapshot_after"), dict) else {}
    return {
        "submitted_external": int(result.get("submitted_external") or 0),
        "withdrawable_value": float(after.get("withdrawable_value") or 0),
        "submitted_value": float(after.get("submitted_value") or 0),
        "ready_value": float(after.get("ready_value") or 0),
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{utc_now()}] {message}\n")


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except json.JSONDecodeError:
            existing = {}
    existing.update(payload)
    path.write_text(json.dumps(existing, ensure_ascii=True, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
