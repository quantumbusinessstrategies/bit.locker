from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from security.access_control import hash_password  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a hashed QuantumGains web access user.")
    parser.add_argument("username", help="Login username to create.")
    parser.add_argument("--role", default="user", help="Optional role label. Default: user.")
    parser.add_argument("--password", default="", help="Password. If omitted, prompts without echo.")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    confirm = args.password or getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        return 2

    payload = {
        args.username: {
            "password_hash": hash_password(password),
            "role": args.role,
        }
    }
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
