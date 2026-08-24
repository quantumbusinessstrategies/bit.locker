from __future__ import annotations

import json
import re
from typing import Any


class SourceScorer:
    def __init__(self, api_key: str, model: str, prompt: str) -> None:
        self.client = _openai_client(api_key)
        self.model = model
        self.prompt = prompt

    def score(self, source_candidate: Any) -> dict[str, Any]:
        payload = source_candidate.to_dict() if hasattr(source_candidate, "to_dict") else dict(source_candidate)
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=True, indent=2)},
            ],
        )
        content = response.choices[0].message.content or "{}"
        return normalize_source_score(_parse_json_object(content))


def normalize_source_score(score: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(score)
    normalized["source_score_1_to_10"] = _clamp(_number(normalized.get("source_score_1_to_10")), 0, 10)
    normalized["expected_gain_potential_1_to_10"] = _clamp(
        _number(normalized.get("expected_gain_potential_1_to_10")),
        0,
        10,
    )
    normalized["freshness_score_1_to_10"] = _clamp(_number(normalized.get("freshness_score_1_to_10")), 0, 10)
    normalized["searchability_score_1_to_10"] = _clamp(
        _number(normalized.get("searchability_score_1_to_10")),
        0,
        10,
    )
    normalized["real_asset_path_strength_1_to_10"] = _clamp(
        _number(normalized.get("real_asset_path_strength_1_to_10")),
        0,
        10,
    )
    normalized["risk_level"] = _risk(normalized.get("risk_level"))
    normalized["login_required"] = _bool(normalized.get("login_required"))
    normalized["payment_required"] = _bool(normalized.get("payment_required"))
    normalized["auto_approve_recommended"] = _bool(normalized.get("auto_approve_recommended"))
    normalized["likely_source_type"] = _source_type(normalized.get("likely_source_type"))
    normalized.setdefault("real_asset_path_signal", "")
    normalized.setdefault("reason", "")
    normalized.setdefault("tags", [])
    if not isinstance(normalized.get("rejection_reasons"), list):
        normalized["rejection_reasons"] = []
    return normalized


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("OpenAI source scorer returned JSON, but not an object")
    return parsed


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else 0.0


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "required"}


def _risk(value: Any) -> str:
    risk = str(value or "high").strip().lower()
    return risk if risk in {"low", "medium", "high"} else "high"


def _source_type(value: Any) -> str:
    source_type = str(value or "configured_url").strip().lower()
    return source_type if source_type in {"configured_url", "rss", "manual_seed"} else "configured_url"


def _openai_client(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("OpenAI package is required for AI source scoring. Use fetch-only/heuristic mode or install openai.") from exc
    return OpenAI(api_key=api_key)
