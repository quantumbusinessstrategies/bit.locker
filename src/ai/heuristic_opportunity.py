from __future__ import annotations

from typing import Any

from ai.execution_prep import normalize_prep
from ai.scorer import normalize_score


CATEGORY_RULES = [
    ("settlement", "cash", 35, 7, 3, 75, "claim"),
    ("refund", "cash", 25, 7, 3, 75, "claim"),
    ("rebate", "cash", 20, 7, 3, 70, "claim"),
    ("unclaimed", "cash", 0, 6, 5, 65, "claim"),
    ("product testing", "physical_goods", 20, 6, 4, 75, "provide_shipping"),
    ("free sample", "physical_goods", 10, 7, 3, 80, "provide_shipping"),
    ("sample", "physical_goods", 10, 6, 4, 75, "provide_shipping"),
    ("survey", "cash_rewards", 5, 6, 5, 70, "claim"),
    ("research study", "cash_rewards", 40, 6, 5, 65, "claim"),
    ("focus group", "cash_rewards", 50, 6, 5, 65, "claim"),
    ("user testing", "cash_rewards", 10, 6, 5, 70, "claim"),
    ("beta", "gift_cards", 10, 6, 4, 75, "claim"),
    ("gift card", "gift_cards", 10, 6, 4, 75, "claim"),
    ("startup", "developer_credits", 1000, 6, 5, 70, "apply"),
    ("cloud credit", "developer_credits", 1000, 6, 5, 70, "apply"),
    ("developer", "developer_credits", 100, 6, 4, 75, "apply"),
    ("ai credit", "developer_credits", 100, 6, 4, 75, "apply"),
    ("creator", "cash_rewards", 0, 5, 5, 65, "connect"),
    ("affiliate", "cash_rewards", 0, 5, 5, 65, "connect"),
    ("referral", "cash_rewards", 0, 5, 4, 70, "connect"),
    ("crypto learn", "crypto", 5, 5, 5, 65, "claim"),
    ("learning rewards", "crypto", 5, 5, 5, 65, "claim"),
    ("airdrop", "crypto", 5, 4, 6, 55, "approve"),
    ("free token", "crypto", 5, 4, 6, 55, "approve"),
    ("free tokens", "crypto", 5, 4, 6, 55, "approve"),
    ("free nft", "crypto", 5, 4, 6, 55, "approve"),
    ("quest", "crypto", 5, 4, 6, 55, "approve"),
    ("bounty", "cash_rewards", 50, 5, 6, 65, "apply"),
    ("ticket", "tickets", 25, 5, 4, 70, "claim"),
    ("membership", "memberships", 20, 5, 4, 70, "claim"),
    ("grant", "grant", 0, 5, 6, 60, "apply"),
    ("challenge", "prize", 0, 5, 6, 60, "apply"),
]

BLOCK_TERMS = [
    "purchase required",
    "deposit required",
    "credit card required",
    "buy now",
    "casino",
    "gambling",
    "loan",
    "forex",
    "margin",
    "investment required",
    "adult",
    "resale",
    "arbitrage",
]

SENSITIVE_TERMS = ["tax", "ssn", "identity verification", "kyc", "wallet signing", "legal agreement"]


def heuristic_opportunity_score(candidate: Any) -> dict[str, Any]:
    payload = _payload(candidate)
    blob = _blob(payload)
    rule = _best_rule(blob)
    blocked = [term for term in BLOCK_TERMS if term in blob]
    sensitive = [term for term in SENSITIVE_TERMS if term in blob]
    if rule:
        gain_type, expected_value, probability, effort, ai_percent, action = rule[1:]
    else:
        gain_type, expected_value, probability, effort, ai_percent, action = ("other", 0, 4, 7, 45, "approve")

    should_add = bool(rule and not blocked)
    if sensitive:
        action = "approve"
        ai_percent = min(ai_percent, 60)
    return normalize_score(
        {
            "gain_type": gain_type,
            "expected_value_usd": expected_value,
            "expected_value_rationale": "Deterministic estimate from opportunity type; owner-specific value may vary.",
            "probability_score_1_to_10": probability,
            "risk_level": "medium" if sensitive or action == "connect" else "low",
            "risk_rationale": "Heuristic triage; final safety gates still apply.",
            "time_to_gain": _time_to_gain(gain_type),
            "time_to_gain_days": _time_to_gain_days(gain_type),
            "owner_effort_required": "Approve, connect, or provide reusable context if needed.",
            "owner_effort_minutes": 5 if effort <= 4 else 15,
            "effort_score_1_to_10": effort,
            "ai_can_do_percent": ai_percent,
            "upfront_payment_required": bool(blocked),
            "net_loss_possible": bool(blocked),
            "illegal": False,
            "terms_violating": False,
            "scammy_or_terms_violating": bool(blocked),
            "job_task_grind": False,
            "official_platform_action_required": True,
            "required_user_action": action,
            "real_asset_path": _real_asset_path(payload, gain_type),
            "destination": _destination(gain_type),
            "expected_delivery_method": _destination(gain_type),
            "should_add_to_claim_queue": should_add,
            "summary": "Heuristic wide-net claim candidate.",
            "disqualification_reasons": blocked,
        },
        payload,
    )


def heuristic_execution_prep(candidate: Any, score: dict[str, Any]) -> dict[str, str]:
    payload = _payload(candidate)
    title = str(payload.get("title") or "Untitled opportunity")
    url = str(payload.get("url") or "")
    action = str(score.get("required_user_action") or "approve")
    return normalize_prep(
        {
            "what_this_gain_is": f"{title} appears to be a claim/apply/redeem opportunity for {score.get('gain_type', 'value')}.",
            "why_it_may_produce_real_asset_value": str(score.get("real_asset_path") or "Official page appears to expose a gain path."),
            "exact_next_step": _next_step(action),
            "ai_work_possible_now": "AI can inspect the official page, map required inputs, prepare safe fields, and stage a final approval packet.",
            "ai_work_completed": "Queued by deterministic wide-net triage; ready for Required Inputs and Autofill checks.",
            "user_approval_needed": "Owner must approve final submit, account connection, terms screens, or any manual-only blocker.",
            "copy_paste_form_answers": "",
            "claim_instructions": f"Use the official page only: {url}",
            "official_link": url,
            "final_acceptance_step": "Owner reviews prepared packet and approves, rejects, or marks later.",
            "asset_landing": str(score.get("destination") or ""),
            "expected_delivery_method": str(score.get("expected_delivery_method") or ""),
            "follow_up_tracking_step": "Track submitted/processing/received/paid status after owner approval or reliable confirmation.",
            "recommended_status": "Needs Approval",
            "safety_notes": "No payment, purchase, legal/tax/identity, wallet signing, or external submit without explicit final approval.",
        }
    )


def _payload(candidate: Any) -> dict[str, Any]:
    if hasattr(candidate, "to_dict"):
        return candidate.to_dict()
    return dict(candidate)


def _blob(payload: dict[str, Any]) -> str:
    tags = payload.get("tags")
    if isinstance(tags, list):
        tags_text = " ".join(str(tag) for tag in tags)
    else:
        tags_text = str(tags or "")
    return " ".join(
        str(payload.get(key) or "")
        for key in ["source_name", "source_type", "title", "url", "summary", "content_text"]
    ).lower() + " " + tags_text.lower()


def _best_rule(blob: str) -> tuple[str, str, int, int, int, int, str] | None:
    for rule in CATEGORY_RULES:
        if rule[0] in blob:
            return rule
    return None


def _real_asset_path(payload: dict[str, Any], gain_type: str) -> str:
    url = str(payload.get("url") or "")
    return f"Official page exposes a {gain_type} claim/apply/redeem path: {url}"


def _destination(gain_type: str) -> str:
    if gain_type in {"physical_goods", "tickets", "memberships"}:
        return "Owner account, email, or shipping destination"
    if gain_type in {"developer_credits", "grant", "prize"}:
        return "Platform account or program dashboard"
    if gain_type == "crypto":
        return "Owner-approved public wallet or platform account"
    return "Owner payout account, email, gift card, or claim portal"


def _time_to_gain(gain_type: str) -> str:
    if gain_type in {"physical_goods", "grant", "prize"}:
        return "days to weeks"
    return "same day to several days"


def _time_to_gain_days(gain_type: str) -> int:
    if gain_type == "physical_goods":
        return 14
    if gain_type in {"grant", "prize"}:
        return 30
    return 3


def _next_step(action: str) -> str:
    if action == "provide_shipping":
        return "Confirm shipping context, then let AI prepare safe form fields for final approval."
    if action == "connect":
        return "Connect or approve the required platform account, then AI can continue preparation."
    if action == "apply":
        return "Approve AI preparation of the application packet before any final submit."
    return "Approve AI preparation and inspect the official page before final submit."
