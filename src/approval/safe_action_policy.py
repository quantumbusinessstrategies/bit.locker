from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SafeActionDecision:
    action_class: str
    submit_allowed: bool
    confidence: str
    direct_gain_signals: list[str]
    stop_flags: list[str]
    reasons: list[str]
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


GENERIC_CAPTURE_TERMS = [
    "list-manage.com",
    "mailchimp",
    "mc-embedded-subscribe",
    "constantcontact",
    "klaviyo",
    "newsletter",
    "subscribe/post",
    "email signup",
    "mailing list",
]

DIRECT_GAIN_TERMS = [
    "claim",
    "file claim",
    "submit claim",
    "request sample",
    "free sample",
    "sample request",
    "product test",
    "product testing",
    "tester application",
    "rebate",
    "refund",
    "settlement",
    "compensation",
    "payout",
    "reward",
    "gift card",
    "redeem",
    "unclaimed property",
    "paid study",
    "research study",
    "user testing",
    "usability test",
    "beta test",
    "apply for rewards",
]

STRONG_DIRECT_GAIN_TERMS = [
    "file claim",
    "submit claim",
    "request sample",
    "free sample",
    "sample request",
    "rebate",
    "refund",
    "settlement",
    "unclaimed property",
    "paid study",
    "user testing",
    "product testing",
    "redeem",
]

MANUAL_STOP_TERMS = [
    "password",
    "captcha",
    "recaptcha",
    "hcaptcha",
    "human verification",
    "payment authorization",
    "payment method",
    "purchase required",
    "buy now",
    "credit card",
    "billing",
    "legal agreement",
    "tax",
    "w-9",
    "w9",
    "1099",
    "ssn",
    "identity verification",
    "driver license",
    "passport",
    "kyc",
    "wallet signing",
    "sign transaction",
    "seed phrase",
    "private key",
]

OWNER_FINAL_APPROVAL_CLAIM_TERMS = [
    "settlement",
    "class action",
    "claim administrator",
    "unclaimed property",
    "refund",
    "reimbursement",
    "rebate",
]

LOW_RISK_AUTOSUBMIT_TERMS = [
    "request sample",
    "free sample",
    "sample request",
    "product test",
    "product testing",
    "tester application",
    "paid study",
    "research study",
    "user testing",
    "usability test",
    "beta test",
    "gift card",
    "reward",
    "redeem",
]

LOGIN_TERMS = [
    "login",
    "log in",
    "sign in",
    "oauth",
    "connect account",
]


def classify_safe_external_submit(
    *,
    opportunity_title: str,
    official_link: str,
    form_action_url: str,
    page_url: str,
    payload_preview: dict[str, str],
    page_text: str = "",
    form_text: str = "",
    mapped_fields: list[str] | None = None,
    required_unmapped_fields: list[str] | None = None,
    stop_flags: list[str] | None = None,
) -> SafeActionDecision:
    """Decide whether a consented browser submit is a real low-risk gain action."""

    mapped_fields = mapped_fields or []
    required_unmapped_fields = required_unmapped_fields or []
    inherited_stop_flags = stop_flags or []
    payload_keys = " ".join(str(key) for key in payload_preview.keys())
    blob = _normalize(
        " ".join(
            [
                opportunity_title,
                official_link,
                form_action_url,
                page_url,
                payload_keys,
                page_text[:6000],
                form_text[:2000],
            ]
        )
    )
    action_blob = _normalize(f"{form_action_url} {payload_keys} {form_text[:2000]}")
    direct_signals = _matches(blob, DIRECT_GAIN_TERMS)
    strong_direct_signals = _matches(blob, STRONG_DIRECT_GAIN_TERMS)
    manual_flags = _matches(blob, MANUAL_STOP_TERMS)
    generic_flags = _matches(action_blob, GENERIC_CAPTURE_TERMS)
    login_flags = _matches(action_blob, LOGIN_TERMS)

    if inherited_stop_flags or manual_flags:
        flags = _dedupe(inherited_stop_flags + manual_flags)
        return SafeActionDecision(
            action_class="sensitive_or_manual",
            submit_allowed=False,
            confidence="High",
            direct_gain_signals=direct_signals,
            stop_flags=flags,
            reasons=["Sensitive/manual-only terms were detected before submit."],
            next_action="Pause and route to owner final approval or manual completion.",
        )

    if generic_flags:
        return SafeActionDecision(
            action_class="generic_capture",
            submit_allowed=False,
            confidence="High",
            direct_gain_signals=direct_signals,
            stop_flags=generic_flags,
            reasons=["The matched form is a mailing-list/newsletter capture, not a direct acquisition action."],
            next_action="Keep this as a discovery source or inspect manually; do not submit as a gain claim.",
        )

    if login_flags:
        return SafeActionDecision(
            action_class="site_login_needed",
            submit_allowed=False,
            confidence="Medium",
            direct_gain_signals=direct_signals,
            stop_flags=login_flags,
            reasons=["The form/action appears to require account login or connection."],
            next_action="Route to Needs Connect or owner login approval, then resume safe prep.",
        )

    if required_unmapped_fields:
        return SafeActionDecision(
            action_class="missing_required_mapping",
            submit_allowed=False,
            confidence="High",
            direct_gain_signals=direct_signals,
            stop_flags=[],
            reasons=["Required form fields are not mapped to safe Vault data."],
            next_action="Ask once for reusable fields or route to manual review if the field is not reusable.",
        )

    if not direct_signals:
        return SafeActionDecision(
            action_class="no_direct_gain_intent",
            submit_allowed=False,
            confidence="Medium",
            direct_gain_signals=[],
            stop_flags=[],
            reasons=["The page/form does not show a clear claim, sample, reward, rebate, study, or payout intent."],
            next_action="Inspect for a more direct official claim/apply/redeem path before submitting.",
        )

    owner_claim_flags = _matches(blob, OWNER_FINAL_APPROVAL_CLAIM_TERMS)
    low_risk_autosubmit_signals = _matches(blob, LOW_RISK_AUTOSUBMIT_TERMS)
    if owner_claim_flags and not low_risk_autosubmit_signals:
        return SafeActionDecision(
            action_class="final_approval_claim",
            submit_allowed=False,
            confidence="High",
            direct_gain_signals=direct_signals,
            stop_flags=owner_claim_flags,
            reasons=["This looks like a legal/refund/rebate/unclaimed-property claim that needs owner verification."],
            next_action="Prepare the packet, show exact fields and official link, then wait for explicit owner final approval.",
        )

    if _only_email(mapped_fields) and not strong_direct_signals:
        return SafeActionDecision(
            action_class="thin_email_capture",
            submit_allowed=False,
            confidence="Medium",
            direct_gain_signals=direct_signals,
            stop_flags=[],
            reasons=["Only an email field is mapped and no strong direct gain action was detected."],
            next_action="Open in Live Assist and verify this is a real acquisition path before submit.",
        )

    return SafeActionDecision(
        action_class=_action_class(direct_signals),
        submit_allowed=True,
        confidence="High" if strong_direct_signals else "Medium",
        direct_gain_signals=direct_signals,
        stop_flags=[],
        reasons=["Direct gain intent detected and no sensitive/manual-only blockers found."],
        next_action="Proceed only under Live Submit With Final Approval and recorded owner consent.",
    )


def _action_class(signals: list[str]) -> str:
    signal_blob = " ".join(signals)
    if any(term in signal_blob for term in ["claim", "settlement", "unclaimed"]):
        return "direct_claim"
    if any(term in signal_blob for term in ["sample", "product test", "product testing"]):
        return "sample_or_product_test"
    if any(term in signal_blob for term in ["rebate", "refund"]):
        return "rebate_or_refund"
    if any(term in signal_blob for term in ["paid study", "research study", "user testing", "usability test"]):
        return "paid_research_or_testing"
    if any(term in signal_blob for term in ["reward", "gift card", "redeem", "payout"]):
        return "reward_or_payout"
    return "direct_gain_action"


def _only_email(mapped_fields: list[str]) -> bool:
    normalized = {str(field).lower() for field in mapped_fields}
    return bool(normalized) and normalized <= {"email", "profile.email"}


def _matches(text: str, terms: list[str]) -> list[str]:
    normalized = _normalize(text)
    return _dedupe([term for term in terms if _term_present(normalized, term)])


def _term_present(normalized_text: str, term: str) -> bool:
    if term == "purchase required" and "no purchase required" in normalized_text:
        return False
    if term == "credit card" and "no credit card" in normalized_text:
        return False
    if term in {"payment method", "payment authorization"} and "no payment" in normalized_text:
        return False
    return term in normalized_text


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output
