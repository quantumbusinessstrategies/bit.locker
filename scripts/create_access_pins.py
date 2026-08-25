from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from security.access_control import hash_password  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the QUANTUMGAINS_ACCESS_PINS_JSON value for a set of teammates, each with "
            "their own short personal code (e.g. 3846) and their own isolated vault/settings. "
            "Pass repeated --person 'username:code:role' triples. Role defaults to 'member'; "
            "exactly one person should usually be role 'owner' (controls spend caps)."
        )
    )
    parser.add_argument(
        "--person",
        action="append",
        required=True,
        metavar="username:code[:role]",
        help="e.g. --person owner:3846:owner --person tester1:0420",
    )
    args = parser.parse_args()

    entries = []
    for raw in args.person:
        parts = raw.split(":")
        if len(parts) < 2:
            print(f"Skipping malformed --person value: {raw!r}", file=sys.stderr)
            continue
        username = parts[0].strip().lower()
        code = parts[1].strip()
        role = parts[2].strip() if len(parts) > 2 and parts[2].strip() else "member"
        if not username or not code:
            print(f"Skipping malformed --person value: {raw!r}", file=sys.stderr)
            continue
        entries.append({"pin_hash": hash_password(code), "username": username, "role": role})

    print("Set this as QUANTUMGAINS_ACCESS_PINS_JSON (in .env locally, and as a Fly secret to deploy):")
    print(json.dumps(entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
