from __future__ import annotations

import json
import re
from typing import Any


class ExecutionContinuationGenerator:
    def __init__(self, api_key: str, model: str, prompt: str) -> None:
        self.client = _openai_client(api_key)
        self.model = model
        self.prompt = prompt

    def continue_work(self, queue_item: dict[str, Any]) -> dict[str, str]:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": json.dumps(queue_item, ensure_ascii=True, indent=2)},
            ],
        )
        content = response.choices[0].message.content or "{}"
        return normalize_continuation(_parse_json_object(content))


def normalize_continuation(payload: dict[str, Any]) -> dict[str, str]:
    recommended = str(payload.get("recommended_status") or "Ready to Accept").strip()
    if recommended not in {"Connect Needed", "Submitted", "Ready to Accept", "Needs Approval", "Dead End"}:
        recommended = "Ready to Accept"
    return {
        "ai_work_completed": _text(payload.get("ai_work_completed")),
        "ai_work_possible_now": _text(payload.get("ai_work_possible_now")),
        "exact_next_step": _text(payload.get("exact_next_step")),
        "final_acceptance_step": _text(payload.get("final_acceptance_step")),
        "follow_up_tracking_step": _text(payload.get("follow_up_tracking_step")),
        "recommended_status": recommended,
        "safety_notes": _text(payload.get("safety_notes")),
    }


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("OpenAI execution continuation returned JSON, but not an object")
    return parsed


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=True, indent=2)


def _openai_client(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("OpenAI package is required for AI execution continuation. Use fetch-only/heuristic mode or install openai.") from exc
    return OpenAI(api_key=api_key)
