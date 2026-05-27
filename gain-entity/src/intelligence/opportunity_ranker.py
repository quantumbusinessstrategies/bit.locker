from __future__ import annotations

from math import log10
from typing import Any, Iterable

from discovery.diversity_guard import DiversityGuard


TIME_WINDOWS = {
    "Today": 1.0,
    "3 Days": 3.0,
    "7 Days": 7.0,
    "30 Days": 30.0,
}

ACTIONABLE_STATUSES = {
    "Needs Approval",
    "Connect Needed",
    "Approved",
    "AI Work Started",
    "AI Work Complete",
    "Submitted",
    "Ready to Accept",
}


def rank_opportunities(
    rows: Iterable[Any],
    time_window: str = "30 Days",
    diversity_rules: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    max_days = TIME_WINDOWS.get(time_window, TIME_WINDOWS["30 Days"])
    ranked = [rank_opportunity(row) for row in rows]
    filtered = [
        item
        for item in ranked
        if item["time_to_gain_days"] is None or item["time_to_gain_days"] <= max_days
    ]
    return DiversityGuard(diversity_rules).adjust_rankings(filtered)


def rank_opportunity(row: Any) -> dict[str, Any]:
    expected_value = _number(_get(row, "expected_value_usd"))
    time_to_gain_days = _optional_number(_get(row, "time_to_gain_days"))
    probability = _number(_get(row, "probability_score_1_to_10", _get(row, "probability_score")))
    effort = _number(_get(row, "effort_score_1_to_10"))
    ai_percent = _number(_get(row, "ai_can_do_percent", _get(row, "ai_can_do_percentage")))
    risk_level = str(_get(row, "risk_level", "unknown") or "unknown").lower()

    value_score = _value_score(expected_value, _number(_get(row, "highest_value_score")))
    speed_score = _speed_score(time_to_gain_days, _number(_get(row, "fastest_gain_score")))
    success_probability = _clamp(probability * 10)
    effort_required = _effort_score(effort, _optional_number(_get(row, "owner_effort_minutes")))
    ai_completion_percent = _clamp(ai_percent)
    risk_score = _risk_score(risk_level)
    priority_score = round(
        (value_score + speed_score + success_probability + ai_completion_percent)
        - (risk_score + effort_required),
        2,
    )

    ranked = _to_dict(row)
    ranked.update(
        {
            "value_score": value_score,
            "speed_score": speed_score,
            "success_probability": success_probability,
            "effort_required": effort_required,
            "ai_completion_percent": ai_completion_percent,
            "risk_score": risk_score,
            "priority_score": priority_score,
            "ranking_reason": _ranking_reason(
                value_score=value_score,
                speed_score=speed_score,
                success_probability=success_probability,
                ai_completion_percent=ai_completion_percent,
                risk_score=risk_score,
                effort_required=effort_required,
                time_to_gain_days=time_to_gain_days,
                risk_level=risk_level,
            ),
        }
    )
    return ranked


def top_fastest(rows: Iterable[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (item["speed_score"], item["priority_score"]), reverse=True)[:limit]


def top_probability(rows: Iterable[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (item["success_probability"], item["priority_score"]), reverse=True)[:limit]


def top_value(rows: Iterable[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (item["value_score"], item["priority_score"]), reverse=True)[:limit]


def top_ai_completable(rows: Iterable[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (item["ai_completion_percent"], item["priority_score"]), reverse=True)[:limit]


def top_immediate_actions(rows: Iterable[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    actionable = [
        item
        for item in rows
        if str(item.get("status", "")) in ACTIONABLE_STATUSES
        and (item.get("exact_next_step") or item.get("final_acceptance_step") or item.get("official_link"))
    ]
    return sorted(
        actionable,
        key=lambda item: (item["speed_score"], item["priority_score"], item["success_probability"]),
        reverse=True,
    )[:limit]


def _value_score(expected_value: float, existing_score: float) -> float:
    if expected_value > 0:
        dollar_score = min(100.0, log10(expected_value + 1) * 20.0)
        return round(max(dollar_score, existing_score), 2)
    return round(_clamp(existing_score), 2)


def _speed_score(days: float | None, existing_score: float) -> float:
    if days is None:
        return round(_clamp(existing_score), 2)
    if days <= 0:
        return 100.0
    if days <= 1:
        return 95.0
    if days <= 3:
        return 85.0
    if days <= 7:
        return 70.0
    if days <= 14:
        return 50.0
    if days <= 30:
        return 30.0
    return 10.0


def _effort_score(effort_score: float, owner_effort_minutes: float | None) -> float:
    if effort_score > 0:
        return round(_clamp(effort_score * 10), 2)
    if owner_effort_minutes is None:
        return 50.0
    if owner_effort_minutes <= 5:
        return 10.0
    if owner_effort_minutes <= 15:
        return 25.0
    if owner_effort_minutes <= 30:
        return 40.0
    if owner_effort_minutes <= 60:
        return 60.0
    return 85.0


def _risk_score(risk_level: str) -> float:
    return {
        "low": 10.0,
        "medium": 45.0,
        "high": 90.0,
    }.get(risk_level, 70.0)


def _ranking_reason(
    *,
    value_score: float,
    speed_score: float,
    success_probability: float,
    ai_completion_percent: float,
    risk_score: float,
    effort_required: float,
    time_to_gain_days: float | None,
    risk_level: str,
) -> str:
    time_text = "unknown timing" if time_to_gain_days is None else f"{time_to_gain_days:g} day window"
    return (
        f"value {value_score:.1f}, speed {speed_score:.1f} ({time_text}), "
        f"success {success_probability:.1f}, AI {ai_completion_percent:.1f}; "
        f"penalties risk {risk_score:.1f} ({risk_level}) and effort {effort_required:.1f}"
    )


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return getattr(row, key, default)


def _to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except TypeError:
        return {
            key: getattr(row, key)
            for key in dir(row)
            if not key.startswith("_") and not callable(getattr(row, key))
        }


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, value)), 2)
