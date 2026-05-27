from __future__ import annotations

import ast
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


EVM_CHAINS = {
    "eth",
    "ethereum",
    "evm",
    "base",
    "polygon",
    "matic",
    "bnb",
    "bsc",
    "arbitrum",
    "optimism",
}
CHAIN_ALIASES = {
    "bitcoin": "btc",
    "btc": "btc",
    "ethereum": "eth",
    "eth": "eth",
    "evm": "eth",
    "solana": "sol",
    "sol": "sol",
    "usd coin": "usdc",
    "usdc": "usdc",
    "matic": "polygon",
    "binance": "bnb",
    "bsc": "bnb",
}
CONTEXT_FIELD_BY_CHAIN = {
    "btc": "btc_address",
    "eth": "eth_address",
    "sol": "sol_address",
    "usdc": "usdc_address",
}
SECRET_KEY_HINTS = (
    "private",
    "seed",
    "mnemonic",
    "phrase",
    "password",
    "passwd",
    "secret",
    "keystore",
    "recovery",
    "ssn",
    "bank",
)
ADDRESS_KEYS = {
    "btc_address": "btc",
    "bitcoin_address": "btc",
    "eth_address": "eth",
    "ethereum_address": "eth",
    "evm_address": "eth",
    "sol_address": "sol",
    "solana_address": "sol",
    "usdc_address": "usdc",
    "base_address": "base",
    "polygon_address": "polygon",
    "matic_address": "polygon",
    "bnb_address": "bnb",
    "bsc_address": "bnb",
    "sui_address": "sui",
}


@dataclass
class ExternalWalletRoutes:
    wallets_by_chain: dict[str, str] = field(default_factory=dict)
    labels_by_chain: dict[str, str] = field(default_factory=dict)
    source_files: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def found_count(self) -> int:
        return len(self.wallets_by_chain)

    def redacted_rows(self) -> list[dict[str, str]]:
        return [
            {
                "chain": chain,
                "label": self.labels_by_chain.get(chain, ""),
                "address": redact_address(address),
            }
            for chain, address in sorted(self.wallets_by_chain.items())
        ]

    def context_patch(self) -> dict[str, str]:
        patch = {"btc_address": "", "eth_address": "", "sol_address": "", "usdc_address": "", "wallet_notes": ""}
        for chain, address in self.wallets_by_chain.items():
            canonical = _canonical_chain(chain)
            field_name = CONTEXT_FIELD_BY_CHAIN.get(canonical)
            if field_name and not patch[field_name]:
                patch[field_name] = address
            elif canonical in EVM_CHAINS and not patch["eth_address"]:
                patch["eth_address"] = address
        if self.wallets_by_chain:
            lines = [
                f"{chain}: {address}"
                for chain, address in sorted(self.wallets_by_chain.items())
                if address not in {patch["btc_address"], patch["eth_address"], patch["sol_address"], patch["usdc_address"]}
            ]
            if lines:
                patch["wallet_notes"] = "External public wallet routes: " + "; ".join(lines)
        return patch

    def route_for_text(self, text: str) -> str:
        lowered = text.lower()
        chain_order = [
            ("btc", ("btc", "bitcoin")),
            ("sol", ("sol", "solana")),
            ("usdc", ("usdc", "stablecoin", "usd coin")),
            ("base", ("base",)),
            ("polygon", ("polygon", "matic")),
            ("bnb", ("bnb", "bsc", "binance")),
            ("sui", ("sui",)),
            ("eth", ("eth", "ethereum", "evm", "wallet", "token", "airdrop", "crypto")),
        ]
        for chain, terms in chain_order:
            if any(term in lowered for term in terms):
                direct = self.wallets_by_chain.get(chain)
                if direct:
                    return direct
                if chain in EVM_CHAINS:
                    fallback = _first_wallet(self.wallets_by_chain, ["eth", "base", "polygon", "bnb", "arbitrum", "optimism"])
                    if fallback:
                        return fallback
        return _first_wallet(self.wallets_by_chain, ["usdc", "eth", "sol", "btc", "base", "polygon", "bnb", "sui"])


def load_external_wallet_routes(root_dir: Path | None = None) -> ExternalWalletRoutes:
    result = ExternalWalletRoutes()
    for path in _candidate_paths(root_dir):
        if not path.exists():
            continue
        result.source_files.append(str(path))
        try:
            if path.suffix.lower() == ".db":
                _load_sqlite_wallets(path, result)
            elif path.suffix.lower() == ".json":
                _load_json_wallets(path, result)
            elif path.suffix.lower() in {".env", ".txt", ".ini"}:
                _load_key_value_wallets(path, result)
            elif path.suffix.lower() == ".py":
                _load_python_wallets(path, result)
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"{path.name}: {type(exc).__name__}: {exc}")
    return result


def apply_external_wallet_routes(context: dict[str, Any], root_dir: Path | None = None, *, overwrite: bool = True) -> dict[str, Any]:
    routes = load_external_wallet_routes(root_dir)
    if not routes.wallets_by_chain:
        return context
    merged = dict(context)
    wallets = dict(merged.get("crypto_wallets") or {})
    patch = routes.context_patch()
    for field_name, value in patch.items():
        if field_name == "wallet_notes":
            if value and value not in str(wallets.get("wallet_notes") or ""):
                existing = str(wallets.get("wallet_notes") or "").strip()
                wallets["wallet_notes"] = f"{existing}\n{value}".strip() if existing else value
            continue
        if value and (overwrite or not str(wallets.get(field_name) or "").strip()):
            wallets[field_name] = value
    merged["crypto_wallets"] = wallets
    merged["_external_wallet_routes"] = {
        "found_count": routes.found_count,
        "source_files": routes.source_files,
        "wallets": routes.redacted_rows(),
        "warnings": routes.warnings,
    }
    return merged


def wallet_route_for_text(root_dir: Path | None, text: str) -> str:
    return load_external_wallet_routes(root_dir).route_for_text(text)


def redact_address(address: str) -> str:
    cleaned = str(address or "").strip()
    if len(cleaned) <= 14:
        return cleaned
    return f"{cleaned[:6]}...{cleaned[-6:]}"


def _candidate_paths(root_dir: Path | None) -> list[Path]:
    paths: list[Path] = []
    for env_key in ("QUANTUMGAINS_WALLET_ROUTES_PATH", "GAIN_ENTITY_WALLET_ROUTES_PATH"):
        raw = os.getenv(env_key)
        if raw:
            paths.append(Path(raw).expanduser())
    if root_dir:
        paths.append(root_dir / "data" / "external_wallet_routes.json")
    desktop_tool = Path.home() / "Desktop" / "free_crypto_acquirer_pure"
    paths.extend(
        [
            desktop_tool / "wallet_routes.json",
            desktop_tool / "wallets.json",
            desktop_tool / "crypto_tool.db",
            desktop_tool / "free_crypto_acquirer_pure.py",
        ]
    )
    return list(dict.fromkeys(paths))


def _load_sqlite_wallets(path: Path, result: ExternalWalletRoutes) -> None:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT label, chain, address FROM wallets WHERE COALESCE(active, 1)=1 ORDER BY id"
        ).fetchall()
    for label, chain, address in rows:
        _add_wallet(result, str(chain or ""), str(address or ""), str(label or path.name), path.name)


def _load_json_wallets(path: Path, result: ExternalWalletRoutes) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    for chain, address, label in _walk_json_wallets(payload):
        _add_wallet(result, chain, address, label or path.name, path.name)


def _load_key_value_wallets(path: Path, result: ExternalWalletRoutes) -> None:
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lower()
        value = value.strip().strip("\"'")
        chain = ADDRESS_KEYS.get(key)
        if chain:
            _add_wallet(result, chain, value, key, path.name)


def _load_python_wallets(path: Path, result: ExternalWalletRoutes) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    key = target.id.lower()
                    chain = ADDRESS_KEYS.get(key)
                    if chain and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        _add_wallet(result, chain, node.value.value, key, path.name)
                    elif "wallet" in key:
                        _load_literal_wallet_container(node.value, result, path.name)


def _load_literal_wallet_container(node: ast.AST, result: ExternalWalletRoutes, source: str) -> None:
    try:
        payload = ast.literal_eval(node)
    except Exception:  # noqa: BLE001
        return
    for chain, address, label in _walk_json_wallets(payload):
        _add_wallet(result, chain, address, label or source, source)


def _walk_json_wallets(payload: Any) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered == "crypto_wallets" and isinstance(value, dict):
                found.extend(_walk_json_wallets(value))
            elif lowered in {"wallets", "wallet_routes", "routes"} and isinstance(value, list):
                found.extend(_walk_json_wallets(value))
            elif lowered in ADDRESS_KEYS and isinstance(value, str):
                found.append((ADDRESS_KEYS[lowered], value, lowered))
            elif {"chain", "address"} <= set(str(k).lower() for k in payload.keys()):
                found.append((str(payload.get("chain") or ""), str(payload.get("address") or ""), str(payload.get("label") or "")))
                break
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_walk_json_wallets(item))
    return found


def _add_wallet(result: ExternalWalletRoutes, chain: str, address: str, label: str, source: str) -> None:
    key_text = f"{chain} {label}".lower()
    if any(hint in key_text for hint in SECRET_KEY_HINTS):
        result.ignored.append(f"{source}: ignored secret-like wallet field {label or chain}")
        return
    canonical = _canonical_chain(chain)
    cleaned = str(address or "").strip()
    if not canonical or not cleaned:
        return
    if not _looks_like_public_address(canonical, cleaned):
        result.warnings.append(f"{source}: ignored invalid {chain} address {redact_address(cleaned)}")
        return
    if canonical not in result.wallets_by_chain:
        result.wallets_by_chain[canonical] = cleaned
        result.labels_by_chain[canonical] = label


def _canonical_chain(chain: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(chain or "").lower()).strip()
    return CHAIN_ALIASES.get(normalized, normalized)


def _looks_like_public_address(chain: str, address: str) -> bool:
    if any(hint in address.lower() for hint in SECRET_KEY_HINTS):
        return False
    if re.search(r"\s", address):
        return False
    if chain == "btc":
        return bool(re.fullmatch(r"(bc1|[13])[A-HJ-NP-Za-km-z0-9]{25,90}", address))
    if chain == "sol":
        return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", address))
    if chain == "sui":
        return bool(re.fullmatch(r"0x[a-fA-F0-9]{64}", address))
    if chain in EVM_CHAINS or chain == "usdc":
        return bool(re.fullmatch(r"0x[a-fA-F0-9]{40}", address))
    return 20 <= len(address) <= 120


def _first_wallet(wallets_by_chain: dict[str, str], chain_order: list[str]) -> str:
    for chain in chain_order:
        value = wallets_by_chain.get(chain)
        if value:
            return value
    return ""
