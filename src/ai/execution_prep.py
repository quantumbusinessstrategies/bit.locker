from __future__ import annotations

import json
import re
from typing import Any


class ExecutionPrepGenerator:
    def __init__(self, api_key: str, model: str, prompt: str) -> None:
        self.client = _openai_client(api_key)
        self.model = model
        self.prompt = prompt

    def prepare(self, candidate: Any, score: dict[str, Any]) -> dict[str, str]:
        payload = {
            "candidate": _candidate_payload(candidate),
            "score": score,
        }
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
        parsed = _parse_json_object(content)
        return normalize_prep(parsed)


def normalize_prep(prep: dict[str, Any]) -> dict[str, str]:
    normalized = {
        "what_this_gain_is": _as_text(prep.get("what_this_gain_is", "")),
        "why_it_may_produce_real_asset_value": _as_text(
            prep.get("why_it_may_produce_real_asset_value", prep.get("why_real_asset_value", ""))
        ),
        "exact_next_step": _as_text(prep.get("exact_next_step", "")),
        "ai_work_possible_now": _as_text(
            prep.get("ai_work_possible_now", prep.get("what_ai_can_do", ""))
        ),
        "ai_work_completed": _as_text(
            prep.get("ai_work_completed", prep.get("what_ai_already_prepared", ""))
        ),
        "user_approval_needed": _as_text(
            prep.get("user_approval_needed", prep.get("what_user_must_approve", ""))
        ),
        "copy_paste_form_answers": _as_text(prep.get("copy_paste_form_answers", "")),
        "claim_instructions": _as_text(prep.get("claim_instructions", "")),
        "official_link": _as_text(prep.get("official_link", "")),
        "final_acceptance_step": _as_text(prep.get("final_acceptance_step", "")),
        "asset_landing": _as_text(prep.get("asset_landing", "")),
        "expected_delivery_method": _as_text(prep.get("expected_delivery_method", "")),
        "follow_up_tracking_step": _as_text(prep.get("follow_up_tracking_step", "")),
        "recommended_status": _as_text(prep.get("recommended_status", "Needs Approval")),
        "safety_notes": _as_text(prep.get("safety_notes", "")),
    }
    normalized["why_real_asset_value"] = normalized["why_it_may_produce_real_asset_value"]
    normalized["what_ai_can_do"] = normalized["ai_work_possible_now"]
    normalized["what_ai_already_prepared"] = normalized["ai_work_completed"]
    normalized["what_user_must_approve"] = normalized["user_approval_needed"]
    return normalized


def _candidate_payload(candidate: Any) -> dict[str, Any]:
    if hasattr(candidate, "to_dict"):
        payload = candidate.to_dict()
    elif isinstance(candidate, dict):
        payload = dict(candidate)
    else:
        payload = dict(candidate.__dict__)
    payload.pop("raw", None)
    return payload


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("OpenAI execution prep returned JSON, but not an object")
    return parsed


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=True, indent=2)


def _openai_client(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("OpenAI package is required for AI execution prep. Use fetch-only/heuristic mode or install openai.") from exc
    return OpenAI(api_key=api_key)
