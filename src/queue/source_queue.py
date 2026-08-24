from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceQueueDecision:
    status: str
    reasons: list[str]
    auto_approved: bool = False


class SourceQueue:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules
        self.min_score = float(rules.get("source_candidate_min_score", 6))
        self.auto_approve_safe = bool(rules.get("auto_approve_safe_sources", True))
        self.free_mode_only = bool(rules.get("free_mode_only", True))

    def evaluate(self, score: dict[str, Any]) -> SourceQueueDecision:
        reasons: list[str] = []
        source_score = _number(score.get("source_score_1_to_10"))
        if source_score < self.min_score:
            reasons.append(f"source score below {self.min_score:g}")
        if str(score.get("risk_level", "high")).lower() == "high":
            reasons.append("source risk is high")
        if self.free_mode_only and _bool(score.get("payment_required")):
            reasons.append("source appears to require payment")
        if _number(score.get("real_asset_path_strength_1_to_10")) < 5:
            reasons.append("weak real asset path signal")

        if reasons:
            return SourceQueueDecision(status="Rejected", reasons=reasons)

        if self.auto_approve_safe and not _bool(score.get("login_required")) and not _bool(score.get("payment_required")):
            return SourceQueueDecision(status="Approved", reasons=["safe no-login/no-payment source"], auto_approved=True)

        return SourceQueueDecision(status="Needs Approval", reasons=["source needs owner approval before use"])


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return 0.0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "required"}
