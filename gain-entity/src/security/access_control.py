from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any


HASH_PREFIX = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 390_000


@dataclass(frozen=True)
class AccessUser:
    username: str
    password_hash: str
    role: str = "user"


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    if not password:
        raise ValueError("Password is required.")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        [
            HASH_PREFIX,
            str(iterations),
            _b64(salt),
            _b64(digest),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        prefix, iterations_raw, salt_raw, expected_raw = password_hash.split("$", 3)
        if prefix != HASH_PREFIX:
            return False
        iterations = int(iterations_raw)
        salt = _unb64(salt_raw)
        expected = _unb64(expected_raw)
    except Exception:  # noqa: BLE001
        return False
    actual = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def configured_users() -> list[AccessUser]:
    users = _users_from_json_env(os.getenv("QUANTUMGAINS_USERS_JSON", ""))
    if users:
        return users
    users = _users_from_compact_env(os.getenv("QUANTUMGAINS_USERS", ""))
    if users:
        return users
    return []


def user_lookup(users: list[AccessUser]) -> dict[str, AccessUser]:
    return {user.username.lower(): user for user in users if user.username}


def _users_from_json_env(raw: str) -> list[AccessUser]:
    raw = raw.strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        return [_user_from_payload(username, record) for username, record in payload.items() if username]
    if isinstance(payload, list):
        users = []
        for record in payload:
            if isinstance(record, dict):
                username = str(record.get("username") or "").strip()
                if username:
                    users.append(_user_from_payload(username, record))
        return [user for user in users if user.password_hash]
    return []


def _users_from_compact_env(raw: str) -> list[AccessUser]:
    users = []
    for item in raw.split(";"):
        item = item.strip()
        if not item or ":" not in item:
            continue
        username, password_hash = item.split(":", 1)
        username = username.strip()
        password_hash = password_hash.strip()
        if username and password_hash:
            users.append(AccessUser(username=username, password_hash=password_hash))
    return users


def _user_from_payload(username: str, record: Any) -> AccessUser:
    if isinstance(record, str):
        return AccessUser(username=username.strip(), password_hash=record.strip())
    if isinstance(record, dict):
        return AccessUser(
            username=username.strip(),
            password_hash=str(record.get("password_hash") or record.get("hash") or "").strip(),
            role=str(record.get("role") or "user").strip() or "user",
        )
    return AccessUser(username=username.strip(), password_hash="")


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))
