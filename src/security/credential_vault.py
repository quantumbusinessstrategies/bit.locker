from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - surfaced in dashboard if dependency is missing
    Fernet = None  # type: ignore[assignment]
    InvalidToken = Exception  # type: ignore[assignment]


PBKDF2_ITERATIONS = 390_000
VAULT_VERSION = 1


@dataclass(frozen=True)
class CredentialRecord:
    key: str
    label: str
    username: str
    login_url: str
    notes: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CredentialVaultUnavailable(RuntimeError):
    pass


class CredentialVault:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_root(cls, root_dir: Path) -> "CredentialVault":
        return cls(root_dir / "data" / "credential_vault.json")

    def exists(self) -> bool:
        return self.path.exists()

    def setup(self, master_password: str) -> None:
        _require_crypto()
        if not master_password:
            raise ValueError("Master password is required.")
        salt = os.urandom(16)
        payload = {
            "version": VAULT_VERSION,
            "kdf": "pbkdf2_sha256",
            "iterations": PBKDF2_ITERATIONS,
            "salt": _b64(salt),
            "verifier": _verifier(master_password, salt),
            "credentials": {},
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
        }
        self._write(payload)

    def unlock(self, master_password: str) -> bytes:
        payload = self._read()
        salt = base64.urlsafe_b64decode(payload["salt"])
        if payload.get("verifier") != _verifier(master_password, salt):
            raise ValueError("Credential vault unlock failed.")
        return _derive_key(master_password, salt)

    def list_records(self, key: bytes) -> list[CredentialRecord]:
        payload = self._read()
        records = []
        for item_key, encrypted in payload.get("credentials", {}).items():
            record = self._decrypt_record(key, encrypted)
            records.append(CredentialRecord(key=item_key, **_public_record(record)))
        return sorted(records, key=lambda item: item.label.lower())

    def save_record(
        self,
        key: bytes,
        *,
        label: str,
        username: str,
        password: str,
        login_url: str = "",
        notes: str = "",
    ) -> CredentialRecord:
        if not label.strip():
            raise ValueError("Credential label is required.")
        if not username.strip():
            raise ValueError("Username is required.")
        if not password:
            raise ValueError("Password is required.")
        payload = self._read()
        record_key = _record_key(label)
        now = _utc_now()
        record = {
            "label": label.strip(),
            "username": username.strip(),
            "password": password,
            "login_url": login_url.strip(),
            "notes": notes.strip(),
            "updated_at": now,
        }
        payload.setdefault("credentials", {})[record_key] = self._encrypt_record(key, record)
        payload["updated_at"] = now
        self._write(payload)
        return CredentialRecord(key=record_key, **_public_record(record))

    def delete_record(self, key: bytes, record_key: str) -> bool:
        payload = self._read()
        credentials = payload.get("credentials", {})
        if record_key not in credentials:
            return False
        # Decrypt once to prove the provided session key can read the vault.
        self._decrypt_record(key, credentials[record_key])
        del credentials[record_key]
        payload["updated_at"] = _utc_now()
        self._write(payload)
        return True

    def _encrypt_record(self, key: bytes, record: dict[str, Any]) -> str:
        _require_crypto()
        token = Fernet(key).encrypt(json.dumps(record, ensure_ascii=True, sort_keys=True).encode("utf-8"))
        return token.decode("ascii")

    def _decrypt_record(self, key: bytes, token: str) -> dict[str, Any]:
        _require_crypto()
        try:
            data = Fernet(key).decrypt(token.encode("ascii"))
        except InvalidToken as exc:
            raise ValueError("Credential vault key cannot decrypt this record.") from exc
        payload = json.loads(data.decode("utf-8"))
        return payload if isinstance(payload, dict) else {}

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            raise FileNotFoundError("Credential vault is not set up yet.")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Credential vault file is invalid.")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def credential_vault_available() -> bool:
    return Fernet is not None


def _derive_key(master_password: str, salt: bytes) -> bytes:
    raw = hashlib.pbkdf2_hmac("sha256", master_password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=32)
    return base64.urlsafe_b64encode(raw)


def _verifier(master_password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", master_password.encode("utf-8"), salt + b":verifier", PBKDF2_ITERATIONS).hex()


def _public_record(record: dict[str, Any]) -> dict[str, str]:
    return {
        "label": str(record.get("label") or ""),
        "username": str(record.get("username") or ""),
        "login_url": str(record.get("login_url") or ""),
        "notes": str(record.get("notes") or ""),
        "updated_at": str(record.get("updated_at") or ""),
    }


def _record_key(label: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in label.strip())
    return "_".join(part for part in slug.split("_") if part) or "credential"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_crypto() -> None:
    if Fernet is None:
        raise CredentialVaultUnavailable("Install cryptography to use the encrypted credential vault.")
