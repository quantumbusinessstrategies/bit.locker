from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from approval.final_approval_packet import build_final_approval_packet
from approval.safe_action_policy import classify_safe_external_submit
from user_context.redaction import redact_value


STOP_TERMS = [
    "password",
    "captcha",
    "recaptcha",
    "human verification",
    "payment authorization",
    "payment method",
    "purchase required",
    "buy now",
    "credit card",
    "legal agreement",
    "accept terms",
    "tax",
    "w-9",
    "1099",
    "ssn",
    "identity",
    "kyc",
    "wallet signing",
    "sign transaction",
]

FIELD_ALIASES = {
    "profile.first_name": ["first name", "firstname", "given name"],
    "profile.last_name": ["last name", "lastname", "surname", "family name"],
    "name": ["name", "full name", "fullname", "contact name", "your name"],
    "email": ["email", "e-mail", "email address"],
    "phone": ["phone", "mobile", "mobile phone", "cell", "cell phone", "tel", "telephone"],
    "shipping.full_name": ["ship name", "ship-to name", "recipient", "delivery name"],
    "shipping.address_line_1": [
        "address",
        "address1",
        "address 1",
        "address line 1",
        "street",
        "street address",
        "mailing address",
    ],
    "shipping.address_line_2": ["address2", "address 2", "address line 2", "apt", "apartment", "suite", "unit"],
    "shipping.city": ["city", "town"],
    "shipping.state": ["state", "province", "region"],
    "shipping.zip": ["zip", "zip code", "postal", "postal code", "postcode"],
    "shipping.country": ["country"],
    "payouts.paypal_email": ["paypal", "paypal email", "paypal account"],
    "payouts.cashapp": ["cashapp", "cash app"],
    "payouts.venmo": ["venmo"],
    "payouts.stripe_email": ["stripe"],
    "crypto_wallets.btc_address": ["btc", "bitcoin"],
    "crypto_wallets.eth_address": ["eth", "ethereum"],
    "crypto_wallets.sol_address": ["sol", "solana"],
    "crypto_wallets.usdc_address": ["usdc"],
    "accounts.github_username": ["github"],
    "accounts.google_email": ["google email", "gmail"],
    "accounts.microsoft_email": ["microsoft", "outlook"],
    "business.business_name": ["company", "company name", "business", "organization", "startup"],
    "business.website_domain": ["website", "company website", "domain", "url"],
}

SENSITIVE_FORM_TERMS = [
    "password",
    "passcode",
    "credit card",
    "card number",
    "cvv",
    "cvc",
    "billing",
    "purchase required",
    "buy now",
    "payment authorization",
    "payment method",
    "ssn",
    "social security",
    "tax id",
    "ein",
    "w-9",
    "w9",
    "1099",
    "identity",
    "driver license",
    "passport",
    "kyc",
    "captcha",
    "recaptcha",
    "hcaptcha",
    "legal",
    "signature",
    "sign transaction",
    "wallet connect",
    "seed phrase",
    "private key",
]

PAGE_STOP_TERMS = [
    "password",
    "captcha",
    "recaptcha",
    "human verification",
    "credit card",
    "card number",
    "cvv",
    "cvc",
    "billing information",
    "payment authorization",
    "purchase required",
    "legal agreement",
    "accept terms",
    "agree to terms",
    "tax",
    "w-9",
    "w9",
    "1099",
    "ssn",
    "social security",
    "tax id",
    "ein",
    "identity verification",
    "driver license",
    "passport",
    "kyc",
    "wallet signing",
    "sign transaction",
    "wallet connect",
    "seed phrase",
    "private key",
]

US_STATE_ABBREVIATIONS = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}

UNSAFE_INPUT_TYPES = {"password", "file"}
IGNORED_INPUT_TYPES = {"submit", "button", "image", "reset"}


@dataclass(frozen=True)
class BrowserExecutionPlan:
    claim_queue_id: int
    opportunity_title: str
    official_link: str
    execution_mode: str
    prepared_fields: list[str]
    field_preview: dict[str, str]
    stop_conditions: list[str]
    allowed_actions: list[str]
    blocked_actions: list[str]
    next_step: str
    dry_run_checklist: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FormFieldInspection:
    form_index: int
    field_name: str
    field_type: str
    label: str
    mapped_context_field: str
    redacted_value_preview: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FormInspectionResult:
    url: str
    reachable: bool
    status_code: int | None
    forms_found: int
    fields: list[FormFieldInspection]
    mapped_fields: list[str]
    missing_fields: list[str]
    cta_links: list[dict[str, str]]
    stop_flags: list[str]
    can_live_assist: bool
    final_approval_required: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fields"] = [field.to_dict() for field in self.fields]
        return payload


@dataclass(frozen=True)
class BrowserExecutionResult:
    attempted: bool
    submitted: bool
    status: str
    note: str
    next_action: str
    proof_or_reference_note: str
    mapped_fields: list[str]
    missing_fields: list[str]
    stop_flags: list[str]
    response_status_code: int | None
    response_url: str
    payload_preview: dict[str, str]
    payload_json: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SafeFormPayload:
    form_index: int
    method: str
    action_url: str
    form_text: str
    payload: dict[str, str]
    payload_preview: dict[str, str]
    mapped_fields: list[str]
    missing_fields: list[str]
    stop_flags: list[str]
    required_unmapped_fields: list[str]
    requires_browser_submit: bool = False


@dataclass(frozen=True)
class BrowserExecutionRun:
    claim_queue_id: int
    status: str
    note: str
    created_at: str
    plan: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BrowserExecutionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_root(cls, root_dir: Path) -> "BrowserExecutionStore":
        return cls(root_dir / "data" / "browser_execution_runs.json")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"runs": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"runs": []}
        return payload if isinstance(payload, dict) else {"runs": []}

    def append(self, run: BrowserExecutionRun) -> None:
        payload = self.load()
        payload.setdefault("runs", []).append(run.to_dict())
        payload["updated_at"] = _utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        runs = self.load().get("runs", [])
        if not isinstance(runs, list):
            return []
        return list(reversed(runs[-limit:]))


def rows_for_browser_execution(conn: Any, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT cq.*, o.title, o.url
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status IN ('Processing', 'Submitted')
           OR cq.execution_status IN ('Processing')
        ORDER BY cq.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def rows_for_browser_execution_candidates(conn: Any, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT cq.*, o.title, o.url
        FROM claim_queue cq
        JOIN opportunities o ON o.id = cq.opportunity_id
        WHERE cq.status = 'Ready to Accept'
           OR cq.execution_status = 'Ready To Accept'
           OR cq.execution_status = 'AI Working'
           OR cq.status = 'Approved'
        ORDER BY cq.fastest_gain_score DESC, cq.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def build_browser_execution_plan(row: dict[str, Any], user_context: dict[str, Any], execution_mode: str) -> BrowserExecutionPlan:
    packet = build_final_approval_packet(row, user_context)
    stop_conditions = _stop_conditions(row)
    return BrowserExecutionPlan(
        claim_queue_id=packet.claim_queue_id,
        opportunity_title=packet.opportunity_title,
        official_link=packet.source_url,
        execution_mode=execution_mode,
        prepared_fields=packet.exact_fields_ai_prepared,
        field_preview=packet.prepared_value_preview,
        stop_conditions=stop_conditions,
        allowed_actions=[
            "open official link",
            "inspect visible form",
            "map visible fields to prepared vault fields",
            "fill safe prepared fields in Live Assist",
            "record proof/reference note",
        ],
        blocked_actions=[
            "submit without explicit consent",
            "payment or purchase",
            "legal/tax/identity attestation",
            "wallet signing",
            "captcha or human-verification bypass",
            "credential changes or account-security changes",
        ],
        next_step=_next_step(packet.source_url, stop_conditions, execution_mode),
        dry_run_checklist=[
            "Verify official URL is reachable.",
            "Verify form fields match the prepared packet.",
            "Verify no blocked/sensitive step appears.",
            "If blocked, pause and route to owner.",
            "If clean and consented, proceed only in Live Submit With Final Approval.",
        ],
    )


def record_browser_execution_run(
    root_dir: Path,
    plan: BrowserExecutionPlan,
    status: str,
    note: str,
) -> BrowserExecutionRun:
    run = BrowserExecutionRun(
        claim_queue_id=plan.claim_queue_id,
        status=status,
        note=note,
        created_at=_utc_now(),
        plan=plan.to_dict(),
    )
    BrowserExecutionStore.for_root(root_dir).append(run)
    return run


def inspect_official_form(
    plan: BrowserExecutionPlan,
    user_context: dict[str, Any],
    timeout_seconds: int = 12,
) -> FormInspectionResult:
    if not _safe_http_url(plan.official_link):
        return FormInspectionResult(
            url=plan.official_link,
            reachable=False,
            status_code=None,
            forms_found=0,
            fields=[],
            mapped_fields=[],
            missing_fields=[],
            cta_links=[],
            stop_flags=["missing_or_invalid_url"],
            can_live_assist=False,
            final_approval_required=True,
            note="Official URL is missing or is not an HTTP/HTTPS URL.",
        )

    session = requests.Session()
    session.headers.update({"User-Agent": "GainEntityBrowserExecutor/0.1 (+consent-gated-safe-submit)"})
    try:
        response = session.get(plan.official_link, timeout=timeout_seconds, allow_redirects=True)
    except requests.RequestException as exc:
        return FormInspectionResult(
            url=plan.official_link,
            reachable=False,
            status_code=None,
            forms_found=0,
            fields=[],
            mapped_fields=[],
            missing_fields=[],
            cta_links=[],
            stop_flags=["network_error"],
            can_live_assist=False,
            final_approval_required=True,
            note=f"Could not reach official URL: {exc.__class__.__name__}.",
        )

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        return FormInspectionResult(
            url=response.url,
            reachable=response.ok,
            status_code=response.status_code,
            forms_found=0,
            fields=[],
            mapped_fields=[],
            missing_fields=[],
            cta_links=[],
            stop_flags=[] if response.ok else ["unreachable_status"],
            can_live_assist=False,
            final_approval_required=True,
            note=f"URL returned non-HTML content type: {content_type or 'unknown'}.",
        )

    soup = BeautifulSoup(response.text, "html.parser")
    page_text = soup.get_text(" ", strip=True).lower()
    stop_flags = _matched_stop_terms(page_text, PAGE_STOP_TERMS)
    forms = soup.find_all("form")
    cta_links = _cta_links(soup, response.url)
    inspected_fields: list[FormFieldInspection] = []
    missing_fields: list[str] = []
    mapped_fields: list[str] = []

    for form_index, form in enumerate(forms, start=1):
        controls = form.find_all(["input", "select", "textarea"])
        for control in controls:
            field_type = str(control.get("type") or control.name or "text").lower()
            if field_type in {"hidden", "submit", "button", "image", "reset"}:
                continue
            identity = _field_identity(control, soup)
            mapped_context_field = _map_field_identity(identity)
            value = _context_value(user_context, mapped_context_field)
            status = "mapped_available" if value else "missing"
            preview = redact_value(mapped_context_field.rsplit(".", 1)[-1], value) if value else ""
            control_stop_flags = _control_stop_flags(control, identity)
            if mapped_context_field:
                mapped_fields.append(mapped_context_field)
                if not value:
                    missing_fields.append(mapped_context_field)
            elif control_stop_flags:
                status = "sensitive_stop"
                stop_flags.extend(control_stop_flags)
            else:
                status = "unmapped"
            inspected_fields.append(
                FormFieldInspection(
                    form_index=form_index,
                    field_name=str(control.get("name") or control.get("id") or control.get("autocomplete") or ""),
                    field_type=field_type,
                    label=identity[:140],
                    mapped_context_field=mapped_context_field,
                    redacted_value_preview=preview,
                    status=status,
                )
            )

    if not forms and cta_links:
        note = "Official page is reachable. No simple HTML forms were detected, but claim/apply/redeem links were found."
    elif not forms:
        note = "Official page is reachable, but no HTML forms were detected."
    elif stop_flags:
        note = "Form inspection found sensitive stop terms. Live Assist should pause for owner review."
    else:
        note = "Form inspection completed. Safe mapped fields can be prepared in Live Assist."
    can_live_assist = response.ok and bool(inspected_fields) and not stop_flags
    return FormInspectionResult(
        url=response.url,
        reachable=response.ok,
        status_code=response.status_code,
        forms_found=len(forms),
        fields=inspected_fields,
        mapped_fields=_dedupe(mapped_fields),
        missing_fields=_dedupe(missing_fields),
        cta_links=cta_links,
        stop_flags=stop_flags,
        can_live_assist=can_live_assist,
        final_approval_required=True,
        note=note,
    )


def execute_safe_official_form(
    plan: BrowserExecutionPlan,
    user_context: dict[str, Any],
    consent: dict[str, Any],
    submit_external: bool = False,
    timeout_seconds: int = 12,
    browser_profile_dir: Path | None = None,
) -> BrowserExecutionResult:
    """Submit only consented, low-risk, simple HTML forms with safe mapped fields."""
    active_plan = replace(plan, official_link=_personalized_official_link(plan.official_link, user_context))
    if plan.execution_mode != "Live Submit With Final Approval":
        return _execution_result(
            attempted=False,
            submitted=False,
            status="blocked_wrong_mode",
            note="Browser execution is not in Live Submit With Final Approval mode.",
            next_action="Switch execution mode only when the owner wants real low-risk form submit attempts.",
        )
    if not consent.get("allowed"):
        return _execution_result(
            attempted=False,
            submitted=False,
            status="blocked_no_consent",
            note="No explicit live-submit consent is recorded for this claim.",
            next_action="Approve this final-submit packet before real browser execution.",
        )
    if not submit_external:
        return _execution_result(
            attempted=False,
            submitted=False,
            status="ready_for_safe_external_submit",
            note="Safe browser execution is gated and ready, but external submit was not requested.",
            next_action="Press Execute Consented Safe Form to attempt the real low-risk submit.",
        )
    if not _safe_http_url(active_plan.official_link):
        return _execution_result(
            attempted=False,
            submitted=False,
            status="blocked_invalid_url",
            note="Official URL is missing or is not an HTTP/HTTPS URL.",
            next_action="Confirm the official claim URL before execution.",
            stop_flags=["missing_or_invalid_url"],
        )

    session = requests.Session()
    session.headers.update({"User-Agent": "GainEntityBrowserExecutor/0.1 (+consent-gated-safe-submit)"})
    try:
        response = session.get(active_plan.official_link, timeout=timeout_seconds, allow_redirects=True)
    except requests.RequestException as exc:
        return _execution_result(
            attempted=True,
            submitted=False,
            status="blocked_network_error",
            note=f"Could not reach official URL: {exc.__class__.__name__}.",
            next_action="Open the official link manually or retry later.",
            stop_flags=["network_error"],
        )

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        return _execution_result(
            attempted=True,
            submitted=False,
            status="blocked_non_html",
            note=f"Official URL returned non-HTML content type: {content_type or 'unknown'}.",
            next_action="Open the official link manually; automated form submission cannot continue.",
            response_status_code=response.status_code,
            response_url=response.url,
        )

    soup = BeautifulSoup(response.text, "html.parser")
    page_stop_flags = _matched_stop_terms(soup.get_text(" ", strip=True).lower(), PAGE_STOP_TERMS)
    if page_stop_flags:
        return _execution_result(
            attempted=True,
            submitted=False,
            status="blocked_sensitive_page",
            note="Sensitive page-level stop terms were detected before submit.",
            next_action="Owner must review the official page and approve or complete the blocked step manually.",
            stop_flags=page_stop_flags,
            response_status_code=response.status_code,
            response_url=response.url,
        )

    payloads = _safe_payloads_from_soup(soup, response.url, user_context)
    cta_source_url = ""
    if not payloads:
        cta_result = _payloads_from_first_safe_cta(session, soup, response.url, user_context, timeout_seconds)
        if cta_result:
            response, soup, payloads, cta_source_url = cta_result
        else:
            browser_result = _execute_safe_form_with_playwright(
                active_plan,
                user_context,
                submit_external=submit_external,
                timeout_ms=timeout_seconds * 1000,
                browser_profile_dir=browser_profile_dir,
            )
            if browser_result:
                return browser_result
            return _execution_result(
                attempted=True,
                submitted=False,
                status="blocked_no_form",
                note="No simple HTML form was detected on the official page or its first safe claim/apply links.",
                next_action="Use Live Assist or manual browser navigation for this item.",
                response_status_code=response.status_code,
                response_url=response.url,
            )

    payloads = sorted(payloads, key=lambda payload: len(payload.mapped_fields), reverse=True)
    best = payloads[0]
    if not best.mapped_fields and not cta_source_url:
        cta_result = _payloads_from_first_safe_cta(session, soup, response.url, user_context, timeout_seconds)
        if cta_result:
            response, soup, payloads, cta_source_url = cta_result
            payloads = sorted(payloads, key=lambda payload: len(payload.mapped_fields), reverse=True)
            best = payloads[0]
        elif browser_profile_dir:
            browser_result = _execute_safe_form_with_playwright(
                active_plan,
                user_context,
                submit_external=submit_external,
                timeout_ms=timeout_seconds * 1000,
                browser_profile_dir=browser_profile_dir,
            )
            if browser_result:
                return browser_result
    if best.stop_flags:
        return _execution_result(
            attempted=True,
            submitted=False,
            status="blocked_sensitive_form",
            note="The best matching form contains sensitive or manual-only controls.",
            next_action="Owner must review or complete this form manually.",
            mapped_fields=best.mapped_fields,
            missing_fields=best.missing_fields,
            stop_flags=best.stop_flags,
            response_status_code=response.status_code,
            response_url=response.url,
            payload_preview=best.payload_preview,
        )
    if best.missing_fields:
        return _execution_result(
            attempted=True,
            submitted=False,
            status="blocked_missing_fields",
            note="The form matches safe Vault fields, but required reusable data is missing.",
            next_action="Add the missing Vault fields, then rerun browser execution.",
            mapped_fields=best.mapped_fields,
            missing_fields=best.missing_fields,
            response_status_code=response.status_code,
            response_url=response.url,
            payload_preview=best.payload_preview,
        )
    if best.required_unmapped_fields:
        return _execution_result(
            attempted=True,
            submitted=False,
            status="blocked_required_unmapped",
            note="The form has required fields that cannot be safely mapped from the Vault.",
            next_action="Owner must review the required fields or add reusable mappings.",
            mapped_fields=best.mapped_fields,
            missing_fields=best.required_unmapped_fields,
            response_status_code=response.status_code,
            response_url=response.url,
            payload_preview=best.payload_preview,
        )
    if not best.mapped_fields:
        return _execution_result(
            attempted=True,
            submitted=False,
            status="blocked_no_mapped_fields",
            note="A form exists, but no safe Vault fields matched it.",
            next_action="Use Live Assist or update field mappings before external submit.",
            response_status_code=response.status_code,
            response_url=response.url,
            payload_preview=best.payload_preview,
        )
    safety_decision = classify_safe_external_submit(
        opportunity_title=plan.opportunity_title,
        official_link=active_plan.official_link,
        form_action_url=best.action_url,
        page_url=response.url,
        payload_preview=best.payload_preview,
        page_text=soup.get_text(" ", strip=True),
        form_text=best.form_text,
        mapped_fields=best.mapped_fields,
        required_unmapped_fields=best.required_unmapped_fields,
        stop_flags=best.stop_flags,
    )
    if not safety_decision.submit_allowed:
        return _execution_result(
            attempted=True,
            submitted=False,
            status=f"blocked_{safety_decision.action_class}",
            note=" ".join(safety_decision.reasons),
            next_action=safety_decision.next_action,
            mapped_fields=best.mapped_fields,
            stop_flags=safety_decision.stop_flags,
            response_status_code=response.status_code,
            response_url=response.url,
            payload_preview=best.payload_preview,
        )

    if best.requires_browser_submit:
        browser_result = _execute_safe_form_with_playwright(
            active_plan,
            user_context,
            submit_external=submit_external,
            timeout_ms=timeout_seconds * 1000,
            browser_profile_dir=browser_profile_dir,
        )
        if browser_result:
            return browser_result
        return _execution_result(
            attempted=True,
            submitted=False,
            status="blocked_browser_submit_required",
            note="The safe form uses browser-side submission and could not be submitted through static HTTP.",
            next_action="Use Live Assist or retry with browser execution enabled.",
            mapped_fields=best.mapped_fields,
            response_status_code=response.status_code,
            response_url=response.url,
            payload_preview=best.payload_preview,
        )

    try:
        if best.method == "get":
            submit_response = session.get(best.action_url, params=best.payload, timeout=timeout_seconds, allow_redirects=True)
        elif best.method == "post":
            submit_response = session.post(best.action_url, data=best.payload, timeout=timeout_seconds, allow_redirects=True)
        else:
            return _execution_result(
                attempted=True,
                submitted=False,
                status="blocked_method",
                note=f"Unsupported form method: {best.method}.",
                next_action="Owner must complete this form manually.",
                mapped_fields=best.mapped_fields,
                response_status_code=response.status_code,
                response_url=response.url,
                payload_preview=best.payload_preview,
            )
    except requests.RequestException as exc:
        return _execution_result(
            attempted=True,
            submitted=False,
            status="submit_failed",
            note=f"Safe form submit attempt failed: {exc.__class__.__name__}.",
            next_action="Retry later or open the official link manually.",
            mapped_fields=best.mapped_fields,
            response_status_code=response.status_code,
            response_url=response.url,
            payload_preview=best.payload_preview,
        )

    ok = submit_response.status_code < 400
    return _execution_result(
        attempted=True,
        submitted=ok,
        status="submitted_external" if ok else "submit_http_error",
        note=(
            "External low-risk form submit completed."
            if ok
            else f"External submit returned HTTP {submit_response.status_code}."
        ),
        next_action="Monitor confirmation, email, account, shipment, or payout status." if ok else "Open the official link manually and verify the submission result.",
        proof_or_reference_note=(
            f"Submitted to {best.action_url}; HTTP {submit_response.status_code}; final URL {submit_response.url}"
            + (f"; reached via CTA {cta_source_url}" if cta_source_url else "")
        ),
        mapped_fields=best.mapped_fields,
        response_status_code=submit_response.status_code,
        response_url=submit_response.url,
        payload_preview=best.payload_preview,
    )


def _stop_conditions(row: dict[str, Any]) -> list[str]:
    text = " ".join(str(row.get(key) or "") for key in [
        "title",
        "owner_input_required",
        "claim_instructions",
        "final_acceptance_step",
        "safety_notes",
        "human_input_needed",
        "next_action",
    ]).lower()
    return _matched_stop_terms(text, STOP_TERMS)


def _fetch_official_page(url: str, timeout_seconds: int) -> requests.Response:
    return requests.get(
        url,
        timeout=timeout_seconds,
        headers={"User-Agent": "GainEntityLiveAssist/0.1 (+form-inspection)"},
        allow_redirects=True,
    )


def _personalized_official_link(official_link: str, user_context: dict[str, Any]) -> str:
    """Route known directory pages to the owner-specific application page when safe fields exist."""
    parsed = urlparse(str(official_link or ""))
    if parsed.netloc.lower().endswith("jobs.focusgrouppanel.com") and parsed.path.rstrip("/") == "/jobs":
        shipping = user_context.get("shipping", {})
        if isinstance(shipping, dict):
            city_slug = _slugify(str(shipping.get("city") or ""))
            state_abbr = _state_abbreviation(str(shipping.get("state") or "")).lower()
            title_slug = _slugify(parse_qs(parsed.query).get("title", [""])[0])
            if city_slug and state_abbr and title_slug:
                return f"https://jobs.focusgrouppanel.com/jobs/{title_slug}-in-{city_slug}-{state_abbr}"
    return str(official_link or "")


def _safe_http_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _state_abbreviation(value: str) -> str:
    clean = str(value or "").strip()
    if len(clean) == 2:
        return clean.upper()
    return US_STATE_ABBREVIATIONS.get(clean.lower(), "")


def _field_identity(control: Any, soup: BeautifulSoup) -> str:
    tokens = [
        str(control.get("name") or ""),
        str(control.get("id") or ""),
        str(control.get("placeholder") or ""),
        str(control.get("aria-label") or ""),
        str(control.get("autocomplete") or ""),
        str(control.get("type") or ""),
    ]
    control_id = control.get("id")
    if control_id:
        label = soup.find("label", attrs={"for": control_id})
        if label:
            tokens.append(label.get_text(" ", strip=True))
    parent_label = control.find_parent("label")
    if parent_label:
        tokens.append(parent_label.get_text(" ", strip=True))
    return " ".join(token for token in tokens if token).strip().lower()


def _map_field_identity(identity: str) -> str:
    for field, aliases in FIELD_ALIASES.items():
        if any(_contains_term(identity, alias) for alias in aliases):
            return field
    return ""


def _build_safe_form_payload(
    form: Any,
    soup: BeautifulSoup,
    base_url: str,
    user_context: dict[str, Any],
    form_index: int,
) -> SafeFormPayload:
    method = str(form.get("method") or "get").strip().lower()
    action_url = urljoin(base_url, str(form.get("action") or base_url))
    form_text = " ".join(form.get_text(" ", strip=True).split())[:2000]
    payload: dict[str, str] = {}
    payload_preview: dict[str, str] = {}
    mapped_fields: list[str] = []
    missing_fields: list[str] = []
    stop_flags: list[str] = []
    required_unmapped_fields: list[str] = []

    if method not in {"get", "post"}:
        stop_flags.append(f"unsupported_method:{method or 'unknown'}")
    if not _safe_http_url(action_url):
        stop_flags.append("unsafe_form_action")

    for control in form.find_all(["input", "select", "textarea"]):
        tag_name = str(control.name or "").lower()
        field_type = str(control.get("type") or tag_name or "text").lower()
        field_name = str(control.get("name") or "").strip()
        identity = _field_identity(control, soup)
        required = control.has_attr("required") or str(control.get("aria-required") or "").lower() == "true"

        if field_type in IGNORED_INPUT_TYPES:
            continue
        if field_type in UNSAFE_INPUT_TYPES:
            stop_flags.append(field_type)
            continue

        control_flags = _control_stop_flags(control, identity)
        if control_flags:
            stop_flags.extend(control_flags)
            continue

        if field_type == "hidden":
            if field_name:
                payload[field_name] = str(control.get("value") or "")
                payload_preview[field_name] = "[hidden]"
            continue

        if not field_name:
            if required:
                required_unmapped_fields.append(identity[:80] or "unnamed_required_field")
            continue

        mapped_context_field = _map_field_identity(identity)
        value = _context_value(user_context, mapped_context_field)
        if mapped_context_field:
            mapped_fields.append(mapped_context_field)
            if value:
                if tag_name == "select":
                    value = _select_value_for_context(control, value)
                payload[field_name] = value
                payload_preview[field_name] = redact_value(mapped_context_field.rsplit(".", 1)[-1], value)
            else:
                missing_fields.append(mapped_context_field)
            continue

        if field_type in {"checkbox", "radio"}:
            if control.has_attr("checked"):
                payload[field_name] = str(control.get("value") or "on")
                payload_preview[field_name] = "[checked]"
            elif required:
                required_unmapped_fields.append(identity[:80] or field_name)
            continue

        if tag_name == "select":
            selected = control.find("option", selected=True)
            option_value = str(selected.get("value") if selected else "").strip() if selected else ""
            if option_value and not required:
                payload[field_name] = option_value
                payload_preview[field_name] = "[default option]"
            elif required:
                required_unmapped_fields.append(identity[:80] or field_name)
            continue

        if required:
            required_unmapped_fields.append(identity[:80] or field_name)

    return SafeFormPayload(
        form_index=form_index,
        method=method,
        action_url=action_url,
        form_text=form_text,
        payload=payload,
        payload_preview=payload_preview,
        mapped_fields=_dedupe(mapped_fields),
        missing_fields=_dedupe(missing_fields),
        stop_flags=_dedupe(stop_flags),
        required_unmapped_fields=_dedupe(required_unmapped_fields),
        requires_browser_submit=not form.has_attr("action") and not form.has_attr("method"),
    )


def _safe_payloads_from_soup(soup: BeautifulSoup, base_url: str, user_context: dict[str, Any]) -> list[SafeFormPayload]:
    return [
        _build_safe_form_payload(form, soup, base_url, user_context, form_index)
        for form_index, form in enumerate(soup.find_all("form"), start=1)
    ]


def _payloads_from_first_safe_cta(
    session: requests.Session,
    soup: BeautifulSoup,
    base_url: str,
    user_context: dict[str, Any],
    timeout_seconds: int,
) -> tuple[requests.Response, BeautifulSoup, list[SafeFormPayload], str] | None:
    for cta in _cta_links(soup, base_url)[:4]:
        cta_url = str(cta.get("url") or "").strip()
        if not _safe_http_url(cta_url):
            continue
        try:
            response = session.get(cta_url, timeout=timeout_seconds, allow_redirects=True)
        except requests.RequestException:
            continue
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            continue
        cta_soup = BeautifulSoup(response.text, "html.parser")
        stop_flags = _matched_stop_terms(cta_soup.get_text(" ", strip=True).lower(), PAGE_STOP_TERMS)
        if stop_flags:
            continue
        payloads = _safe_payloads_from_soup(cta_soup, response.url, user_context)
        if payloads:
            return response, cta_soup, payloads, cta_url
    return None


def _execute_safe_form_with_playwright(
    plan: BrowserExecutionPlan,
    user_context: dict[str, Any],
    *,
    submit_external: bool,
    timeout_ms: int,
    browser_profile_dir: Path | None = None,
) -> BrowserExecutionResult | None:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None

    browser = None
    context = None
    try:
        system_browser = _system_browser_executable()
        if system_browser is None:
            return None
        with sync_playwright() as p:
            if browser_profile_dir:
                browser_profile_dir.mkdir(parents=True, exist_ok=True)
                launch_kwargs: dict[str, Any] = {"headless": True, "executable_path": str(system_browser)}
                context = p.chromium.launch_persistent_context(str(browser_profile_dir), **launch_kwargs)
                page = context.pages[0] if context.pages else context.new_page()
            else:
                browser = p.chromium.launch(headless=True, executable_path=str(system_browser))
                page = browser.new_page()
            page.goto(plan.official_link, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(750)
            page_text = str(page.locator("body").inner_text(timeout=1500) or "")
            page_flags = _matched_stop_terms(page_text.lower(), PAGE_STOP_TERMS)
            if page_flags:
                return _execution_result(
                    attempted=True,
                    submitted=False,
                    status="blocked_sensitive_page",
                    note="Rendered browser page contains sensitive/manual-only stop terms.",
                    next_action="Owner must review or complete this page manually.",
                    stop_flags=page_flags,
                    response_url=page.url,
                )

            controls = page.locator("input, textarea, select")
            control_count = min(controls.count(), 100)
            mapped_fields: list[str] = []
            missing_fields: list[str] = []
            stop_flags: list[str] = []
            payload_preview: dict[str, str] = {}
            filled = 0
            for index in range(control_count):
                control = controls.nth(index)
                try:
                    identity = str(control.evaluate(_PLAYWRIGHT_FIELD_IDENTITY_JS) or "").lower()
                    field_type = str(control.evaluate("(el) => String(el.type || el.tagName || 'text').toLowerCase()") or "text").lower()
                    field_name = str(control.evaluate("(el) => String(el.name || el.id || el.getAttribute('aria-label') || '')") or f"field_{index}")
                    disabled = bool(control.evaluate("(el) => Boolean(el.disabled || el.readOnly)"))
                except Exception:
                    continue
                if disabled or field_type in IGNORED_INPUT_TYPES or field_type == "hidden":
                    continue
                if field_type in UNSAFE_INPUT_TYPES:
                    stop_flags.append(field_type)
                    continue
                control_flags = _matched_stop_terms(identity, SENSITIVE_FORM_TERMS)
                if control_flags:
                    stop_flags.extend(control_flags)
                    continue
                mapped_context_field = _map_field_identity(identity)
                if not mapped_context_field:
                    continue
                value = _context_value(user_context, mapped_context_field)
                mapped_fields.append(mapped_context_field)
                if not value:
                    missing_fields.append(mapped_context_field)
                    continue
                try:
                    if field_type in {"checkbox", "radio"}:
                        continue
                    if field_type == "select-one":
                        if _playwright_select_context_value(control, value):
                            payload_preview[field_name] = redact_value(mapped_context_field.rsplit(".", 1)[-1], value)
                            filled += 1
                        continue
                    control.fill(value, timeout=1200)
                    payload_preview[field_name] = redact_value(mapped_context_field.rsplit(".", 1)[-1], value)
                    filled += 1
                except Exception:
                    continue

            mapped_fields = _dedupe(mapped_fields)
            missing_fields = _dedupe(missing_fields)
            stop_flags = _dedupe(stop_flags)
            if stop_flags:
                return _execution_result(
                    attempted=True,
                    submitted=False,
                    status="blocked_sensitive_form",
                    note="Rendered form contains sensitive or manual-only controls.",
                    next_action="Owner must review or complete this page manually.",
                    mapped_fields=mapped_fields,
                    missing_fields=missing_fields,
                    stop_flags=stop_flags,
                    response_url=page.url,
                    payload_preview=payload_preview,
                )
            if missing_fields:
                return _execution_result(
                    attempted=True,
                    submitted=False,
                    status="blocked_missing_fields",
                    note="Rendered form matched safe fields, but reusable Vault data is missing.",
                    next_action="Add missing Vault fields, then rerun live browser execution.",
                    mapped_fields=mapped_fields,
                    missing_fields=missing_fields,
                    response_url=page.url,
                    payload_preview=payload_preview,
                )
            if not filled:
                return _execution_result(
                    attempted=True,
                    submitted=False,
                    status="blocked_no_mapped_fields",
                    note="Rendered browser form exists, but no safe Vault fields could be filled.",
                    next_action="Use Live Assist or add field mappings before submit.",
                    mapped_fields=mapped_fields,
                    response_url=page.url,
                    payload_preview=payload_preview,
                )

            safety_decision = classify_safe_external_submit(
                opportunity_title=plan.opportunity_title,
                official_link=plan.official_link,
                form_action_url=page.url,
                page_url=page.url,
                payload_preview=payload_preview,
                page_text=page_text,
                form_text=page_text[:2000],
                mapped_fields=mapped_fields,
                required_unmapped_fields=[],
                stop_flags=[],
            )
            if not safety_decision.submit_allowed:
                return _execution_result(
                    attempted=True,
                    submitted=False,
                    status=f"blocked_{safety_decision.action_class}",
                    note=" ".join(safety_decision.reasons),
                    next_action=safety_decision.next_action,
                    mapped_fields=mapped_fields,
                    stop_flags=safety_decision.stop_flags,
                    response_url=page.url,
                    payload_preview=payload_preview,
                )
            if not submit_external:
                return _execution_result(
                    attempted=True,
                    submitted=False,
                    status="live_assist_filled_safe_fields",
                    note="Rendered browser filled safe fields but did not submit.",
                    next_action="Owner can review the browser-filled form or enable consented live submit.",
                    mapped_fields=mapped_fields,
                    response_url=page.url,
                    payload_preview=payload_preview,
                )

            submit_locator = _playwright_submit_locator(page)
            if submit_locator is None:
                return _execution_result(
                    attempted=True,
                    submitted=False,
                    status="blocked_no_safe_submit_button",
                    note="Safe fields were filled, but no direct safe submit/request/apply button was detected.",
                    next_action="Owner should review and click the final button manually.",
                    mapped_fields=mapped_fields,
                    response_url=page.url,
                    payload_preview=payload_preview,
                )
            before_url = page.url
            try:
                submit_locator.click(timeout=2500)
                page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
            final_url = page.url
            return _execution_result(
                attempted=True,
                submitted=True,
                status="submitted_external_browser",
                note="Rendered browser low-risk form submit was attempted after safe field fill.",
                next_action="Monitor confirmation, email, account, shipment, or payout status.",
                proof_or_reference_note=f"Rendered browser clicked safe submit on {before_url}; final URL {final_url}",
                mapped_fields=mapped_fields,
                response_url=final_url,
                payload_preview=payload_preview,
            )
    except Exception as exc:
        return _execution_result(
            attempted=True,
            submitted=False,
            status="blocked_browser_execution_error",
            note=f"Rendered browser execution failed: {exc.__class__.__name__}.",
            next_action="Retry later or use Live Assist/manual browser navigation.",
        )
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass


def _system_browser_executable() -> Path | None:
    for executable in ("chrome.exe", "chrome", "msedge.exe", "msedge"):
        found = shutil.which(executable)
        if found:
            return Path(found)

    candidate_strings = [
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for candidate in candidate_strings:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def _playwright_submit_locator(page: Any) -> Any | None:
    terms = [
        "request sample",
        "free sample",
        "submit claim",
        "file claim",
        "apply",
        "redeem",
        "submit",
        "send",
        "join",
        "register",
        "get started",
    ]
    blocked = ["payment", "purchase", "buy", "checkout", "agree", "terms", "sign in", "login"]
    locators = page.locator("button, input[type=submit], input[type=button]")
    count = min(locators.count(), 80)
    for index in range(count):
        locator = locators.nth(index)
        try:
            text = str(locator.evaluate("(el) => String(el.innerText || el.value || el.getAttribute('aria-label') || '')") or "")
            lowered = text.lower()
            if any(term in lowered for term in blocked):
                continue
            if any(term in lowered for term in terms):
                return locator
        except Exception:
            continue
    return None


_PLAYWRIGHT_FIELD_IDENTITY_JS = """
(el) => {
  const labels = el.labels ? Array.from(el.labels).map((label) => label.innerText || '').join(' ') : '';
  return [
    el.name || '',
    el.id || '',
    el.placeholder || '',
    el.getAttribute('aria-label') || '',
    el.getAttribute('autocomplete') || '',
    el.type || '',
    labels,
    el.closest('label') ? el.closest('label').innerText || '' : ''
  ].join(' ');
}
"""


def _control_stop_flags(control: Any, identity: str) -> list[str]:
    field_type = str(control.get("type") or control.name or "text").lower()
    flags: list[str] = []
    if field_type in UNSAFE_INPUT_TYPES:
        flags.append(field_type)
    flags.extend(_matched_stop_terms(identity, SENSITIVE_FORM_TERMS))
    if field_type in {"checkbox", "radio"} and any(term in identity for term in ["agree", "terms", "legal", "consent", "signature"]):
        flags.append("manual_attestation")
    return _dedupe(flags)


def _looks_like_generic_subscription(action_url: str, page_url: str, payload_preview: dict[str, str]) -> bool:
    blob = f"{action_url} {page_url} {' '.join(payload_preview.keys())}".lower()
    generic_terms = [
        "list-manage.com",
        "mailchimp",
        "subscribe/post",
        "newsletter",
        "mc-embedded-subscribe",
        "constantcontact",
        "klaviyo",
    ]
    direct_gain_terms = [
        "claim",
        "sample",
        "rebate",
        "refund",
        "settlement",
        "apply",
        "redeem",
        "reward",
        "payout",
        "product-test",
    ]
    return any(term in blob for term in generic_terms) and not any(term in blob for term in direct_gain_terms)


def _cta_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    cta_terms = [
        "claim",
        "file claim",
        "submit claim",
        "apply",
        "sign up",
        "join",
        "register",
        "redeem",
        "get started",
        "start",
        "apply now",
        "join now",
        "become a tester",
        "product testing",
        "tester",
        "get paid",
        "learn rewards",
        "participate",
        "enter",
        "request sample",
        "free sample",
    ]
    blocked_terms = ["login", "sign in", "privacy", "terms", "contact", "cookie", "facebook", "twitter", "linkedin"]
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        text = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(base_url, str(anchor.get("href") or ""))
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        blob = f"{text} {href}".lower()
        if not any(term in blob for term in cta_terms):
            continue
        if any(term in blob for term in blocked_terms) and not any(term in blob for term in ["claim", "apply", "redeem"]):
            continue
        if href in seen:
            continue
        seen.add(href)
        output.append({"label": text[:140] or parsed.netloc, "url": href})
        if len(output) >= 8:
            break
    return output


def _context_value(user_context: dict[str, Any], mapped_context_field: str) -> str:
    if not mapped_context_field:
        return ""
    if mapped_context_field in {"profile.first_name", "profile.last_name"}:
        profile = user_context.get("profile", {})
        shipping = user_context.get("shipping", {})
        name = ""
        if isinstance(profile, dict):
            name = str(profile.get("name") or "")
        if not name and isinstance(shipping, dict):
            name = str(shipping.get("full_name") or "")
        parts = [part for part in name.strip().split() if part]
        if not parts:
            return ""
        return parts[0] if mapped_context_field.endswith("first_name") else parts[-1]
    if "." not in mapped_context_field:
        profile = user_context.get("profile", {})
        if isinstance(profile, dict):
            return str(profile.get(mapped_context_field) or "")
        return ""
    section, field = mapped_context_field.split(".", 1)
    values = user_context.get(section, {})
    if isinstance(values, dict):
        return str(values.get(field) or "")
    return ""


def _select_value_for_context(control: Any, context_value: str) -> str:
    clean_value = str(context_value or "").strip()
    if not clean_value:
        return ""
    lowered = clean_value.lower()
    for option in control.find_all("option"):
        option_value = str(option.get("value") or "").strip()
        option_text = option.get_text(" ", strip=True)
        if lowered in {option_value.lower(), option_text.lower()}:
            return option_value or option_text or clean_value
    for option in control.find_all("option"):
        option_value = str(option.get("value") or "").strip()
        option_text = option.get_text(" ", strip=True)
        blob = f"{option_value} {option_text}".lower()
        if lowered and lowered in blob:
            return option_value or option_text or clean_value
    return clean_value


def _playwright_select_context_value(control: Any, context_value: str) -> bool:
    clean_value = str(context_value or "").strip()
    if not clean_value:
        return False
    attempts = [
        {"label": clean_value},
        {"value": clean_value},
    ]
    for attempt in attempts:
        try:
            control.select_option(**attempt, timeout=1200)
            return True
        except Exception:
            pass
    try:
        options = control.locator("option")
        count = min(options.count(), 200)
        lowered = clean_value.lower()
        for index in range(count):
            option = options.nth(index)
            text = str(option.inner_text(timeout=500) or "").strip()
            value = str(option.get_attribute("value") or "").strip()
            if lowered and lowered in f"{text} {value}".lower():
                control.select_option(value=value or text, timeout=1200)
                return True
    except Exception:
        return False
    return False


def _next_step(official_link: str, stop_conditions: list[str], execution_mode: str) -> str:
    if not official_link:
        return "Pause: official link is missing."
    if stop_conditions:
        return "Open only for inspection; pause if any listed stop condition appears."
    if execution_mode == "Dry Run":
        return "Dry Run: inspect and verify field mapping only."
    if execution_mode == "Live Assist":
        return "Live Assist: open official link and fill safe fields only; do not submit."
    return "Live Submit With Final Approval: submit only if explicit consent exists and no stop condition appears."


def _execution_result(
    attempted: bool,
    submitted: bool,
    status: str,
    note: str,
    next_action: str,
    proof_or_reference_note: str = "",
    mapped_fields: list[str] | None = None,
    missing_fields: list[str] | None = None,
    stop_flags: list[str] | None = None,
    response_status_code: int | None = None,
    response_url: str = "",
    payload_preview: dict[str, str] | None = None,
) -> BrowserExecutionResult:
    payload = {
        "browser_execution": {
            "attempted": attempted,
            "submitted": submitted,
            "status": status,
            "note": note,
            "next_action": next_action,
            "proof_or_reference_note": proof_or_reference_note,
            "mapped_fields": mapped_fields or [],
            "missing_fields": missing_fields or [],
            "stop_flags": stop_flags or [],
            "response_status_code": response_status_code,
            "response_url": response_url,
            "payload_preview": payload_preview or {},
            "created_at": _utc_now(),
        }
    }
    return BrowserExecutionResult(
        attempted=attempted,
        submitted=submitted,
        status=status,
        note=note,
        next_action=next_action,
        proof_or_reference_note=proof_or_reference_note,
        mapped_fields=mapped_fields or [],
        missing_fields=missing_fields or [],
        stop_flags=stop_flags or [],
        response_status_code=response_status_code,
        response_url=response_url,
        payload_preview=payload_preview or {},
        payload_json=json.dumps(payload, ensure_ascii=True, sort_keys=True),
    )


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _matched_stop_terms(text: str, terms: list[str]) -> list[str]:
    normalized = " ".join(str(text or "").lower().split())
    return _dedupe([term for term in terms if _contains_term(normalized, term)])


def _contains_term(text: str, term: str) -> bool:
    text = " ".join(str(text or "").lower().split())
    normalized_term = " ".join(str(term or "").lower().split())
    if not normalized_term:
        return False
    if normalized_term == "w9":
        return bool(re.search(r"\bw[-\s]?9\b", text))
    if normalized_term == "w-9":
        return bool(re.search(r"\bw[-\s]?9\b", text))
    if normalized_term == "purchase required" and re.search(r"\bno\s+purchase\s+required\b", text):
        return False
    if normalized_term == "credit card" and re.search(r"\bno\s+credit\s+card(?:\s+required)?\b", text):
        return False
    if normalized_term in {"payment method", "payment authorization"} and re.search(r"\bno\s+payment", text):
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(normalized_term).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
    return bool(re.search(pattern, text))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
