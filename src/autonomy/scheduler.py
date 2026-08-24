from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml


FREQUENCIES = {
    "1h": timedelta(hours=1),
    "3h": timedelta(hours=3),
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "daily": timedelta(days=1),
}


def main() -> int:
    args = parse_args()
    root_dir = Path(__file__).resolve().parents[2]
    rules = load_rules(root_dir)
    if not bool(rules.get("autonomy_enabled", True)) and not args.once:
        print("Autonomy scheduler is disabled in config/rules.yaml.")
        return 0

    frequency = args.frequency or str(rules.get("schedule_frequency", "6h"))
    interval = parse_frequency(frequency)

    if args.once:
        return run_entity_once(root_dir)

    print(f"Gain Entity scheduler started. Frequency: {frequency}.")
    while True:
        started = datetime.now(timezone.utc)
        code = run_entity_once(root_dir)
        finished = datetime.now(timezone.utc)
        next_run = finished + interval
        print(
            f"Run finished with code {code} at {finished.isoformat()}. "
            f"Next run: {next_run.isoformat()}."
        )
        sleep_seconds = max(0, (next_run - datetime.now(timezone.utc)).total_seconds())
        time.sleep(sleep_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Gain Entity automatically on a schedule.")
    parser.add_argument("--once", action="store_true", help="Run the entity once through the scheduler wrapper.")
    parser.add_argument(
        "--frequency",
        choices=sorted(FREQUENCIES.keys()),
        default=None,
        help="Override config/rules.yaml schedule_frequency.",
    )
    return parser.parse_args()


def run_entity_once(root_dir: Path) -> int:
    command = [sys.executable, str(root_dir / "src" / "main.py")]
    completed = subprocess.run(command, cwd=root_dir, check=False)
    return int(completed.returncode)


def load_rules(root_dir: Path) -> dict[str, Any]:
    path = root_dir / "config" / "rules.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def parse_frequency(value: str) -> timedelta:
    try:
        return FREQUENCIES[value]
    except KeyError as exc:
        allowed = ", ".join(FREQUENCIES)
        raise ValueError(f"Unsupported schedule_frequency {value!r}. Use one of: {allowed}") from exc


def next_run_after(last_run: datetime, frequency: str) -> datetime:
    return last_run + parse_frequency(frequency)


if __name__ == "__main__":
    raise SystemExit(main())
