from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from user_context.schema import default_user_context, merge_user_context


class UserContextStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_root(cls, root_dir: Path) -> "UserContextStore":
        return cls(root_dir / "data" / "user_context.json")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return default_user_context()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default_user_context()
        return merge_user_context(payload)

    def save(self, context: dict[str, Any]) -> dict[str, Any]:
        merged = merge_user_context(context)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(merged, ensure_ascii=True, indent=2), encoding="utf-8")
        return merged

