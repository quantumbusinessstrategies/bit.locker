from __future__ import annotations

import json
import re
from typing import Any


class AIScorer:
    def __init__(self, api_key: str, model: str, prompt: str) -> None:
        self.client = _openai_client(api_key)
        self.model = model
        self.prompt = prompt

    def score(self, candidate: Any) -> dict[str, Any]:
        candidate_payload = _candidate_payload(candidate)
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self.prompt},
                {
                    "role": "user",
                    "content": json.dumps(candidate_payload, ensure_ascii=True, indent=2),
                },
            ],
        )
        content = response.choices[0].message.content or "{}"
        return normalize_score(_parse_json_object(content), candidate_payload)


def normalize_score(score: dict[str, Any], candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = dict(score)
    normalized["gain_type"] = str(normalized.get("gain_type") or "other").strip() or "other"
    normalized["expected_value_usd"] = _number(normalized.get("expected_value_usd"))
    if _looks_like_total_pool_value(normalized["expected_value_usd"], candidate or {}):
        normalized["expected_value_usd"] = 0.0
        rationale = str(normalized.get("expected_value_rationale") or "").strip()
        normalized["expected_value_rationale"] = (
            f"{rationale} Per-owner value is unknown; ignored apparent total pool/program value.".strip()
        )
    probability = _clamp(
        _number(normalized.get("probability_score_1_to_10", normalized.get("probability_score"))),
        0,
        10,
    )
    normalized["probability_score_1_to_10"] = probability
    normalized["probability_score"] = probability
    normalized["risk_level"] = _risk(normalized.get("risk_level"))
    normalized["time_to_gain"] = str(normalized.get("time_to_gain") or "unknown")
    normalized["time_to_gain_days"] = max(0, _number(normalized.get("time_to_gain_days")))
    normalized["owner_effort_required"] = str(normalized.get("owner_effort_required") or "unknown")
    normalized["owner_effort_minutes"] = max(0, _number(normalized.get("owner_effort_minutes")))
    effort_score = _clamp(
        _number(normalized.get("effort_score_1_to_10", _effort_from_minutes(normalized["owner_effort_minutes"]))),
        1,
        10,
    )
    normalized["effort_score_1_to_10"] = effort_score
    ai_percent = _clamp(
        _number(normalized.get("ai_can_do_percent", normalized.get("ai_can_do_percentage"))),
        0,
        100,
    )
    normalized["ai_can_do_percent"] = ai_percent
    normalized["ai_can_do_percentage"] = ai_percent

    upfront_payment_required = _bool(
        normalized.get("upfront_payment_required", normalized.get("upfront_money_required"))
    )
    net_loss_possible = _bool(normalized.get("net_loss_possible", normalized.get("could_produce_loss")))
    normalized["upfront_payment_required"] = upfront_payment_required
    normalized["upfront_money_required"] = upfront_payment_required
    normalized["net_loss_possible"] = net_loss_possible
    normalized["could_produce_loss"] = net_loss_possible

    for field in ["illegal", "terms_violating", "scammy_or_terms_violating", "job_task_grind", "official_platform_action_required"]:
        normalized[field] = _bool(normalized.get(field))

    normalized["required_user_action"] = _normalize_action(normalized.get("required_user_action"))
    normalized.setdefault("expected_value_rationale", "")
    normalized.setdefault("risk_rationale", "")
    normalized["real_asset_path"] = _text(normalized.get("real_asset_path"), "unknown")
    normalized["destination"] = _text(normalized.get("destination"), "unknown")
    normalized["expected_delivery_method"] = _text(
        normalized.get("expected_delivery_method", normalized.get("destination")),
        "unknown",
    )
    normalized["should_add_to_claim_queue"] = _bool(normalized.get("should_add_to_claim_queue"))
    normalized["fastest_gain_score"] = _ranking_score(
        normalized.get("fastest_gain_score", _fastest_gain_score(normalized))
    )
    normalized["highest_value_score"] = _ranking_score(
        normalized.get("highest_value_score", _highest_value_score(normalized))
    )
    normalized.setdefault("summary", "")
    if not isinstance(normalized.get("disqualification_reasons"), list):
        normalized["disqualification_reasons"] = []
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


def _openai_client(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ModuleNotFoundError as exc:
        raise RuntimeError("OpenAI package is required for AI scoring. Use fetch-only/heuristic mode or install openai.") from exc
    return OpenAI(api_key=api_key)


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("OpenAI scorer returned JSON, but not an object")
    return parsed


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
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
    if risk not in {"low", "medium", "high"}:
        return "high"
    return risk


def _normalize_action(value: Any) -> str:
    action = str(value or "approve").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "connect_account": "connect",
        "sign_accept_terms": "sign",
        "accept_terms": "sign",
        "provide_shipping_address": "provide_shipping",
        "provide_payout_details": "provide_payout",
        "provide_payout_account": "provide_payout",
        "accept_asset": "accept",
        "owner_claim": "claim",
    }
    return aliases.get(action, action)


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _effort_from_minutes(minutes: float) -> float:
    if minutes <= 5:
        return 1
    if minutes <= 15:
        return 3
    if minutes <= 30:
        return 5
    if minutes <= 60:
        return 7
    return 9


def _fastest_gain_score(score: dict[str, Any]) -> float:
    probability = _number(score.get("probability_score_1_to_10", score.get("probability_score")))
    effort = _number(score.get("effort_score_1_to_10"))
    days = max(0, _number(score.get("time_to_gain_days")))
    speed_component = max(0, 100 - min(days, 100))
    probability_component = probability * 10
    effort_component = max(0, 100 - (effort * 10))
    return (speed_component * 0.45) + (probability_component * 0.35) + (effort_component * 0.20)


def _highest_value_score(score: dict[str, Any]) -> float:
    value = max(0, _number(score.get("expected_value_usd")))
    probability = _number(score.get("probability_score_1_to_10", score.get("probability_score")))
    risk_penalty = {"low": 1.0, "medium": 0.75, "high": 0.2}.get(str(score.get("risk_level")).lower(), 0.2)
    value_component = min(100, value / 10) if value else 0
    if value >= 1000:
        value_component = 100
    elif value >= 100:
        value_component = 60 + min(40, (value - 100) / 22.5)
    return ((value_component * 0.65) + (probability * 10 * 0.35)) * risk_penalty


def _ranking_score(value: Any) -> float:
    score = _number(value)
    if 0 < score <= 10:
        score *= 10
    return _clamp(score, 0, 100)


def _looks_like_total_pool_value(value: float, candidate: dict[str, Any]) -> bool:
    if value < 10000:
        return False
    blob = " ".join(
        str(candidate.get(field, ""))
        for field in ["title", "summary", "content_text", "url"]
    ).lower()
    pool_terms = ["settlement", "class action", "lawsuit", "agreed to a $", "fund", "pool"]
    per_owner_terms = ["per person", "per claimant", "individual payout", "up to $", "credit up to"]
    return any(term in blob for term in pool_terms) and not any(term in blob for term in per_owner_terms)
