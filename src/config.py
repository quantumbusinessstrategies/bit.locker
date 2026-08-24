from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    root_dir: Path
    data_dir: Path
    exports_dir: Path
    database_path: Path
    sources_path: Path
    rules_path: Path
    prompts_dir: Path
    openai_api_key: str | None
    openai_model: str
    max_candidates_per_source: int
    request_timeout_seconds: int
    user_agent: str


def load_settings(root_dir: Path | None = None) -> Settings:
    root = root_dir or Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")

    data_dir = root / "data"
    exports_dir = data_dir / "exports"
    database_path = _resolve_path(
        root,
        os.getenv("DATABASE_PATH", "data/gain_entity.sqlite3"),
    )

    return Settings(
        root_dir=root,
        data_dir=data_dir,
        exports_dir=exports_dir,
        database_path=database_path,
        sources_path=root / "config" / "sources.yaml",
        rules_path=root / "config" / "rules.yaml",
        prompts_dir=root / "prompts",
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        max_candidates_per_source=_env_int("MAX_CANDIDATES_PER_SOURCE", 15),
        request_timeout_seconds=_env_int("REQUEST_TIMEOUT_SECONDS", 20),
        user_agent=os.getenv(
            "USER_AGENT",
            "gain-entity-source-swarm/0.1 (+local MVP)",
        ),
    )


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return loaded


def read_prompt(settings: Settings, filename: str) -> str:
    path = settings.prompts_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing prompt file: {path}")
    return path.read_text(encoding="utf-8")


def ensure_runtime_dirs(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.exports_dir.mkdir(parents=True, exist_ok=True)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _resolve_path(root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return root / path
