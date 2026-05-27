from __future__ import annotations

from typing import Any


DESTINATION_TYPES = [
    "PayPal",
    "Stripe",
    "Bank",
    "Crypto Wallet",
    "Gift Card",
    "Shipping Address",
    "Email Account",
    "Platform Account",
    "Marketplace Account",
    "Cloud/API Credit Account",
    "Local Pickup",
    "Claim Portal",
    "Unknown",
]

ASSET_TYPES = [
    "cash",
    "crypto",
    "gift_card",
    "rebate",
    "reward_points",
    "physical_good",
    "software_license",
    "cloud_credit",
    "ai_credit",
    "developer_credit",
    "affiliate_commission",
    "creator_payout",
    "grant",
    "ticket",
    "membership",
    "unclaimed_property",
    "other_asset",
]

ACCEPTANCE_STATUSES = [
    "Not Ready",
    "Needs Approval",
    "Needs Connect",
    "Needs Shipping",
    "Needs Payout",
    "Needs Identity Verification",
    "Ready to Accept",
    "Accepted",
    "Received/Paid",
    "Dead End",
]


class DestinationRouter:
    def route(self, item: dict[str, Any]) -> dict[str, str]:
        destination_type = self.destination_type(item)
        asset_type = self.asset_type(item)
        acceptance_status = self.acceptance_status(item, destination_type)
        asset_destination = self.asset_destination(item, destination_type)
        final_acceptance_step = self.final_acceptance_step(item, acceptance_status, destination_type)
        owner_input_required = self.owner_input_required(item, acceptance_status, destination_type)
        ai_next_action = self.ai_next_action(item, acceptance_status)
        post_approval_action = self.post_approval_action(item, acceptance_status, destination_type)
        received_tracking_note = self.received_tracking_note(item, asset_type, asset_destination)
        return {
            "destination_type": destination_type,
            "asset_type": asset_type,
            "acceptance_status": acceptance_status,
            "asset_destination": asset_destination,
            "final_acceptance_step": final_acceptance_step,
            "owner_input_required": owner_input_required,
            "ai_next_action": ai_next_action,
            "post_approval_action": post_approval_action,
            "received_tracking_note": received_tracking_note,
        }

    def destination_type(self, item: dict[str, Any]) -> str:
        text = _blob(item)
        destination = str(item.get("destination") or item.get("asset_landing") or "").strip()
        if "paypal" in text:
            return "PayPal"
        if "stripe" in text:
            return "Stripe"
        if any(
            term in text
            for term in [
                "cloud credit",
                "api credit",
                "ai credit",
                "developer credit",
                "startup credit",
                "cloud services",
                "openai",
                "aws",
                "azure",
                "google cloud",
                "vultr",
            ]
        ):
            return "Cloud/API Credit Account"
        if any(term in text for term in ["bank", "ach", "direct deposit", "checking account", "wire transfer"]):
            return "Bank"
        if any(term in text for term in ["crypto", "wallet", "token", "stablecoin", "usdc", "ethereum", "bitcoin"]):
            return "Crypto Wallet"
        if any(term in text for term in ["gift card", "egift", "e-gift"]):
            return "Gift Card"
        if any(term in text for term in ["shipping", "ship", "mailing address", "mailed", "delivered", "sample"]):
            return "Shipping Address"
        if any(term in text for term in ["email", "inbox", "license key", "download link"]):
            return "Email Account"
        if any(term in text for term in ["marketplace", "seller account", "amazon", "etsy", "ebay"]):
            return "Marketplace Account"
        if any(term in text for term in ["local pickup", "pickup", "pick up"]):
            return "Local Pickup"
        if any(term in text for term in ["claim portal", "claim form", "settlement", "unclaimed", "refund", "benefit finder"]):
            return "Claim Portal"
        if any(term in text for term in ["platform account", "dashboard", "member account", "developer account"]):
            return "Platform Account"
        if destination:
            return "Platform Account"
        return "Unknown"

    def asset_type(self, item: dict[str, Any]) -> str:
        text = _blob(item)
        if any(term in text for term in ["cash", "paypal", "bank deposit", "direct deposit", "refund check", "payout"]):
            return "cash"
        if any(term in text for term in ["crypto", "token", "stablecoin", "usdc", "bitcoin", "ethereum"]):
            return "crypto"
        if "gift card" in text:
            return "gift_card"
        if any(term in text for term in ["rebate", "refund", "coupon"]):
            return "rebate"
        if any(term in text for term in ["reward points", "points", "miles"]):
            return "reward_points"
        if any(term in text for term in ["physical", "sample", "shipped", "shipping", "product testing", "electronics", "clothing", "food"]):
            return "physical_good"
        if any(term in text for term in ["software license", "license key", "saas", "subscription"]):
            return "software_license"
        if any(term in text for term in ["ai credit", "openai credit", "anthropic credit"]):
            return "ai_credit"
        if any(term in text for term in ["developer credit", "github", "developer pack"]):
            return "developer_credit"
        if any(term in text for term in ["cloud credit", "aws", "azure", "google cloud", "vultr"]):
            return "cloud_credit"
        if "affiliate" in text:
            return "affiliate_commission"
        if any(term in text for term in ["creator payout", "creator fund", "royalty"]):
            return "creator_payout"
        if any(term in text for term in ["grant", "funding award"]):
            return "grant"
        if "ticket" in text:
            return "ticket"
        if "membership" in text:
            return "membership"
        if any(term in text for term in ["unclaimed property", "unclaimed money", "treasury hunt"]):
            return "unclaimed_property"
        return "other_asset"

    def acceptance_status(self, item: dict[str, Any], destination_type: str) -> str:
        status = str(item.get("status") or "").strip()
        text = _blob(item)
        if status == "Dead End":
            return "Dead End"
        if status == "Received/Paid":
            return "Received/Paid"
        if status == "Accepted":
            return "Accepted"
        if status == "Ready to Accept":
            return "Ready to Accept"
        if "identity verification" in text or "verify identity" in text or "kyc" in text:
            return "Needs Identity Verification"
        if status == "Connect Needed" or any(term in text for term in ["connect account", "login", "sign in", "oauth"]):
            return "Needs Connect"
        if destination_type == "Shipping Address" or "provide shipping" in text or "shipping address" in text:
            return "Needs Shipping"
        if destination_type in {"PayPal", "Stripe", "Bank", "Crypto Wallet"} and any(
            term in text for term in ["provide payout", "payout details", "payment method", "wallet address"]
        ):
            return "Needs Payout"
        if status in {"Needs Approval", "Qualified", "AI Work Complete"}:
            return "Needs Approval"
        if status in {"Approved", "AI Work Started", "Submitted"}:
            return "Not Ready"
        return "Not Ready"

    def asset_destination(self, item: dict[str, Any], destination_type: str) -> str:
        explicit = _first_text(
            item.get("asset_destination"),
            item.get("destination"),
            item.get("asset_landing"),
            item.get("expected_delivery_method"),
        )
        if explicit:
            return explicit
        return {
            "PayPal": "Owner PayPal account inside the official claim or payout platform.",
            "Stripe": "Owner Stripe account or connected payout account.",
            "Bank": "Owner bank account entered only inside the official platform.",
            "Crypto Wallet": "Owner crypto wallet address entered only inside the official platform.",
            "Gift Card": "Gift card code delivered to email or platform account.",
            "Shipping Address": "Owner shipping address entered only inside the official platform.",
            "Email Account": "Owner email account.",
            "Platform Account": "Owner account on the official platform.",
            "Marketplace Account": "Owner marketplace account.",
            "Cloud/API Credit Account": "Owner cloud, API, developer, or startup account.",
            "Local Pickup": "Local pickup location designated by the official source.",
            "Claim Portal": "Official claim portal or benefits/refund portal.",
        }.get(destination_type, "Unknown destination until official instructions are reviewed.")

    def final_acceptance_step(self, item: dict[str, Any], acceptance_status: str, destination_type: str) -> str:
        existing = _first_text(item.get("final_acceptance_step"))
        if existing:
            return existing
        if acceptance_status == "Ready to Accept":
            return "Owner opens the official link and accepts or confirms receipt inside the official platform."
        if acceptance_status == "Needs Connect":
            return "Owner connects or signs in to the official platform, then returns the item for AI continuation."
        if acceptance_status == "Needs Shipping":
            return "Owner enters shipping information inside the official platform and confirms the request."
        if acceptance_status == "Needs Payout":
            return "Owner enters payout destination inside the official platform and confirms the request."
        if acceptance_status == "Needs Identity Verification":
            return "Owner completes identity verification only inside the official platform."
        if destination_type == "Unknown":
            return "Confirm the official destination and acceptance method before proceeding."
        return "Owner approves the prepared path, then completes the final official accept/claim/submit step."

    def owner_input_required(self, item: dict[str, Any], acceptance_status: str, destination_type: str) -> str:
        existing = _first_text(item.get("owner_input_required"), item.get("user_approval_needed"), item.get("what_user_must_approve"))
        if existing:
            return existing
        return {
            "Needs Approval": "Approve or reject the prepared claim path.",
            "Needs Connect": "Connect or sign in to the official account.",
            "Needs Shipping": "Provide shipping address inside the official platform.",
            "Needs Payout": "Provide payout details inside the official platform.",
            "Needs Identity Verification": "Complete identity verification inside the official platform.",
            "Ready to Accept": "Accept or confirm the final asset inside the official platform.",
            "Accepted": "No new input required unless delivery fails.",
            "Received/Paid": "Confirm tracking details are accurate.",
            "Dead End": "No input required.",
        }.get(acceptance_status, f"Review the official {destination_type} path and approve the next step.")

    def ai_next_action(self, item: dict[str, Any], acceptance_status: str) -> str:
        existing = _first_text(item.get("ai_next_action"), item.get("ai_work_possible_now"), item.get("what_ai_can_do"))
        if existing:
            return existing
        if acceptance_status in {"Needs Approval", "Needs Connect", "Needs Shipping", "Needs Payout", "Needs Identity Verification"}:
            return "Wait for owner input, then continue safe preparation and tracking."
        if acceptance_status == "Ready to Accept":
            return "Prepare final acceptance checklist and monitor follow-up tracking."
        return "Monitor status and update tracking after owner action."

    def post_approval_action(self, item: dict[str, Any], acceptance_status: str, destination_type: str) -> str:
        existing = _first_text(item.get("post_approval_action"))
        if existing:
            return existing
        if acceptance_status == "Needs Approval":
            return "After approval, continue AI-safe prep and move to connect, submit, or ready-to-accept as appropriate."
        if acceptance_status == "Needs Connect":
            return "After connection, continue official-form prep without handling credentials."
        if acceptance_status in {"Needs Shipping", "Needs Payout", "Needs Identity Verification"}:
            return "After owner provides required official-platform input, track submission and delivery."
        if destination_type == "Claim Portal":
            return "Track the claim portal for confirmation, payout, delivery, or rejection."
        return "Track delivery/crediting and update Received/Paid or Dead End."

    def received_tracking_note(self, item: dict[str, Any], asset_type: str, asset_destination: str) -> str:
        existing = _first_text(item.get("received_tracking_note"), item.get("follow_up_tracking_step"))
        if existing:
            return existing
        return f"When received, mark Received/Paid with asset_type={asset_type} and destination={asset_destination}."


def _blob(item: dict[str, Any]) -> str:
    keys = [
        "title",
        "gain_type",
        "what_this_gain_is",
        "why_real_asset_value",
        "real_asset_path",
        "destination",
        "asset_landing",
        "expected_delivery_method",
        "required_user_action",
        "exact_next_step",
        "claim_instructions",
        "final_acceptance_step",
        "user_approval_needed",
        "owner_input_required",
        "ai_work_possible_now",
        "official_link",
    ]
    return " ".join(str(item.get(key) or "") for key in keys).lower()


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
