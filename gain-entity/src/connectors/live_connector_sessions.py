from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class LiveConnectorProvider:
    key: str
    label: str
    category: str
    login_url: str
    domains: list[str]
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


LIVE_CONNECTOR_PROVIDERS = [
    LiveConnectorProvider("github", "GitHub", "developer / credits", "https://github.com/login", ["github.com", "education.github.com"], "Developer credits, bounties, and repo work."),
    LiveConnectorProvider("google", "Google", "email / cloud", "https://accounts.google.com/", ["accounts.google.com", "google.com", "cloud.google.com"], "Google account, cloud/startup credits, email-adjacent flows."),
    LiveConnectorProvider("microsoft", "Microsoft", "email / cloud", "https://login.microsoftonline.com/", ["login.microsoftonline.com", "microsoft.com", "azure.microsoft.com"], "Microsoft startup/cloud offers."),
    LiveConnectorProvider("amazon", "Amazon / AWS", "shopping / cloud", "https://signin.aws.amazon.com/", ["amazon.com", "aws.amazon.com", "signin.aws.amazon.com"], "AWS credits and Amazon account gated freebie routes."),
    LiveConnectorProvider("paypal", "PayPal", "payout", "https://www.paypal.com/signin", ["paypal.com"], "Receiving/payout handoff only; no payment authorization."),
    LiveConnectorProvider("stripe", "Stripe", "payout / business", "https://dashboard.stripe.com/login", ["stripe.com", "dashboard.stripe.com"], "Business/payout handoff only; no bank/tax changes."),
    LiveConnectorProvider("hometesterclub", "Home Tester Club", "product testing", "https://www.hometesterclub.com/login", ["hometesterclub.com"], "Product testing and sample campaigns."),
    LiveConnectorProvider("bzzagent", "BzzAgent", "product testing", "https://www.bzzagent.com/login", ["bzzagent.com"], "Sample campaigns and product testing."),
    LiveConnectorProvider("influenster", "Influenster", "product testing", "https://www.influenster.com/login", ["influenster.com"], "Product review campaigns."),
    LiveConnectorProvider("sampler", "Sampler", "product samples", "https://www.sampler.io/", ["sampler.io"], "Brand sample offers."),
    LiveConnectorProvider("merchology", "Merchology", "free samples", "https://www.merchology.com/account/login", ["merchology.com"], "Free sample/product request flows that may involve cart-style navigation."),
    LiveConnectorProvider("pinchme", "PINCHme", "free samples", "https://www.pinchme.com/login", ["pinchme.com"], "Free sample boxes and product campaigns."),
    LiveConnectorProvider("socialnature", "Social Nature", "product samples", "https://www.socialnature.com/login", ["socialnature.com"], "Natural-product trials and sample/rebate offers."),
    LiveConnectorProvider("samplesource", "SampleSource", "free samples", "https://www.samplesource.com/", ["samplesource.com"], "Seasonal sample boxes and freebie campaigns."),
    LiveConnectorProvider("pgeveryday", "P&G Everyday", "rewards / samples", "https://www.pgeveryday.com/login", ["pgeveryday.com"], "Rewards, coupons, and sample-related routes."),
    LiveConnectorProvider("usertesting", "UserTesting", "paid testing", "https://www.usertesting.com/login", ["usertesting.com"], "Paid user testing work."),
    LiveConnectorProvider("userinterviews", "User Interviews", "paid research", "https://www.userinterviews.com/sign_in", ["userinterviews.com"], "Paid research applications."),
    LiveConnectorProvider("respondent", "Respondent", "paid research", "https://app.respondent.io/login", ["respondent.io"], "Paid research applications."),
    LiveConnectorProvider("prolific", "Prolific", "paid studies", "https://app.prolific.com/login", ["prolific.com"], "Paid study work."),
    LiveConnectorProvider("f6s", "F6S", "startup credits", "https://www.f6s.com/login", ["f6s.com"], "Startup deals and credit applications."),
    LiveConnectorProvider("devpost", "Devpost", "prizes / hackathons", "https://devpost.com/login", ["devpost.com"], "Hackathon and prize submissions."),
    LiveConnectorProvider("onlydust", "OnlyDust", "developer bounties", "https://app.onlydust.com/", ["onlydust.com", "app.onlydust.com"], "Open-source reward work."),
    LiveConnectorProvider("superteam", "Superteam Earn", "crypto / bounties", "https://earn.superteam.fun/", ["earn.superteam.fun"], "Bounties and crypto reward tasks."),
]


def live_connector_root(root_dir: Path) -> Path:
    return root_dir / "data" / "live_connector_profiles"


def live_connector_profile_dir(root_dir: Path, provider_key: str) -> Path:
    return live_connector_root(root_dir) / safe_provider_key(provider_key)


def live_connector_status_path(root_dir: Path) -> Path:
    return root_dir / "data" / "live_connector_sessions.json"


def provider_by_key(provider_key: str) -> LiveConnectorProvider | None:
    normalized = safe_provider_key(provider_key)
    for provider in LIVE_CONNECTOR_PROVIDERS:
        if provider.key == normalized:
            return provider
    return None


def provider_for_url(url: str) -> LiveConnectorProvider | None:
    hostname = urlparse(str(url or "")).netloc.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    for provider in LIVE_CONNECTOR_PROVIDERS:
        for domain in provider.domains:
            normalized = domain.lower()
            if normalized.startswith("www."):
                normalized = normalized[4:]
            if hostname == normalized or hostname.endswith("." + normalized):
                return provider
    return None


def profile_for_url(root_dir: Path, url: str) -> Path | None:
    provider = provider_for_url(url)
    if not provider:
        return None
    path = live_connector_profile_dir(root_dir, provider.key)
    return path if path.exists() else None


def load_live_connector_status(root_dir: Path) -> dict[str, Any]:
    path = live_connector_status_path(root_dir)
    if not path.exists():
        return {"providers": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"providers": {}}
    return payload if isinstance(payload, dict) else {"providers": {}}


def save_live_connector_status(root_dir: Path, provider_key: str, payload: dict[str, Any]) -> None:
    status = load_live_connector_status(root_dir)
    providers = status.setdefault("providers", {})
    providers[safe_provider_key(provider_key)] = {
        **providers.get(safe_provider_key(provider_key), {}),
        **payload,
        "updated_at": utc_now(),
    }
    path = live_connector_status_path(root_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, ensure_ascii=True, indent=2), encoding="utf-8")


def live_connector_rows(root_dir: Path) -> list[dict[str, Any]]:
    status = load_live_connector_status(root_dir).get("providers", {})
    if not isinstance(status, dict):
        status = {}
    rows = []
    for provider in LIVE_CONNECTOR_PROVIDERS:
        profile_dir = live_connector_profile_dir(root_dir, provider.key)
        row = provider.to_dict()
        provider_status = status.get(provider.key, {}) if isinstance(status.get(provider.key), dict) else {}
        row.update(provider_status)
        row["profile_exists"] = profile_dir.exists()
        row["profile_dir"] = str(profile_dir)
        rows.append(row)
    return rows


def safe_provider_key(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value or "")).strip("_")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
