from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrictFilterResult:
    qualified: bool
    status: str
    reasons: list[str]


class StrictFilter:
    def __init__(self, rules: dict[str, Any]) -> None:
        self.rules = rules
        self.allowed_user_actions = set(rules.get("allowed_user_actions", []))
        mode = str(rules.get("qualification_mode", "wide_net")).strip().lower()
        self.thresholds = rules.get("strict" if mode == "strict" else "wide_net", {})

    def evaluate(self, score: dict[str, Any]) -> StrictFilterResult:
        reasons: list[str] = []

        if not _bool(score.get("should_add_to_claim_queue")):
            reasons.append("scorer did not recommend claim queue")

        if _risk_rank(score.get("risk_level")) > _risk_rank(self.rules.get("max_risk", "medium")):
            reasons.append("risk is high")

        if self.rules.get("require_no_upfront_payment", True) and _bool(
            score.get("upfront_payment_required", score.get("upfront_money_required"))
        ):
            reasons.append("upfront money required")

        if self.rules.get("disallow_loss_paths", True) and _bool(
            score.get("net_loss_possible", score.get("could_produce_loss"))
        ):
            reasons.append("could produce loss")

        if self.rules.get("disallow_illegal", True) and _bool(score.get("illegal")):
            reasons.append("illegal or not lawful")

        if self.rules.get("disallow_terms_violating", True) and _bool(score.get("terms_violating")):
            reasons.append("terms-violating")

        if self.rules.get("disallow_scammy", True) and _bool(score.get("scammy_or_terms_violating")):
            reasons.append("scammy or terms-violating")

        if self.rules.get("disallow_job_task_grind", True) and _bool(score.get("job_task_grind")):
            reasons.append("job/task-grind drift")

        effort = _number(score.get("effort_score_1_to_10"))

        probability = _number(score.get("probability_score_1_to_10", score.get("probability_score")))
        minimum_probability = _number(
            self.thresholds.get(
                "minimum_probability_score_1_to_10",
                self.rules.get("minimum_probability_score", 5),
            )
        )
        # A true long-shot (e.g. a legit sweepstakes/prize drawing) can fairly score low
        # probability while still being worth entering, because entry itself costs nothing.
        # Only bypass the probability floor when effort is trivial AND every other safety
        # gate above (risk, upfront payment, loss, illegal, terms, scammy) already passed.
        long_shot_bypass_enabled = self.rules.get("long_shot_free_entry_bypass_enabled", True)
        long_shot_max_effort = _number(self.rules.get("long_shot_free_entry_max_effort", 2))
        is_long_shot_free_entry = (
            long_shot_bypass_enabled
            and not reasons
            and effort <= long_shot_max_effort
        )
        if probability < minimum_probability and not is_long_shot_free_entry:
            reasons.append(f"probability below {minimum_probability:g}")

        maximum_effort = _number(self.thresholds.get("maximum_effort_score_1_to_10", 6))
        if effort > maximum_effort:
            reasons.append(f"effort above {maximum_effort:g}")

        ai_percent = _number(score.get("ai_can_do_percent", score.get("ai_can_do_percentage")))
        minimum_ai_percent = _number(
            self.thresholds.get(
                "minimum_ai_can_do_percent",
                self.rules.get("minimum_ai_can_do_percentage", 60),
            )
        )
        if ai_percent < minimum_ai_percent:
            reasons.append(f"AI prep/work below {minimum_ai_percent:g}%")

        minimum_expected_value = _number(self.rules.get("minimum_expected_value_usd", 0))
        if _number(score.get("expected_value_usd")) < minimum_expected_value:
            reasons.append(f"expected value below ${minimum_expected_value:g}")

        if self.rules.get("require_specific_claimable_opportunity", True):
            disqualification_reasons = [
                str(reason).lower()
                for reason in score.get("disqualification_reasons", [])
                if reason is not None
            ]
            if any("not a specific claimable opportunity" in reason for reason in disqualification_reasons):
                reasons.append("not a specific claimable opportunity")

        if self.rules.get("require_strong_real_asset_path", True):
            real_asset_path = str(score.get("real_asset_path", "")).strip()
            if _weak_real_asset_path(real_asset_path):
                reasons.append("real_asset_path is weak, vague, or nonexistent")

        action = str(score.get("required_user_action", "")).strip().lower()
        if action not in self.allowed_user_actions:
            reasons.append(f"user action {action or 'unknown'} is outside allowed actions")

        if reasons:
            return StrictFilterResult(
                qualified=False,
                status=self._rejection_status(score),
                reasons=reasons,
            )

        return StrictFilterResult(
            qualified=True,
            status=self._initial_queue_status(action),
            reasons=[],
        )

    @staticmethod
    def _initial_queue_status(action: str) -> str:
        if action == "connect":
            return "Connect Needed"
        return "Needs Approval"

    @staticmethod
    def _rejection_status(score: dict[str, Any]) -> str:
        if _bool(score.get("upfront_payment_required", score.get("upfront_money_required"))) and not _bool(
            score.get("scammy_or_terms_violating")
        ):
            return "Paid Mode Later"
        return "Rejected"


def _risk_rank(value: Any) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(str(value or "high").strip().lower(), 3)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "required"}


def _number(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return 0.0


def _weak_real_asset_path(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return True
    weak_exact = {
        "unknown",
        "n/a",
        "na",
        "none",
        "not specified",
        "unspecified",
        "website",
        "official website",
        "homepage",
        "home page",
        "varies",
    }
    if text in weak_exact:
        return True
    weak_phrases = [
        "check the page",
        "visit the website",
        "search online",
        "not provided",
        "no direct",
        "no specific",
        "unclear",
        "to be determined",
    ]
    return any(phrase in text for phrase in weak_phrases)
