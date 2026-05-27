from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

@dataclass(frozen=True)
class MagicMoneyLane:
    name: str
    category: str
    url: str
    summary: str
    tags: list[str]
    autonomy_path: str
    ai_can_do: list[str]
    stops_on: list[str]
    direct_queue: bool = True
    risk_level: str = "low"

    @property
    def fingerprint(self) -> str:
        basis = json.dumps({"name": self.name, "url": self.url, "category": self.category}, sort_keys=True)
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def to_source_candidate(self) -> dict[str, Any]:
        parsed = urlparse(self.url)
        return {
            "title": self.name,
            "url": self.url,
            "snippet": self.summary,
            "discovery_method": "magic_fairytale_money_lane",
            "query": self.category,
            "domain": parsed.netloc,
            "fingerprint": self.fingerprint,
            "raw": self.to_dict(),
        }

    def to_opportunity_candidate(self) -> "MagicOpportunityCandidate":
        now = _utc_now()
        content = (
            f"{self.summary}\n"
            f"Autonomy path: {self.autonomy_path}\n"
            f"AI can do: {', '.join(self.ai_can_do)}\n"
            f"Stops on: {', '.join(self.stops_on)}"
        )
        return MagicOpportunityCandidate(
            source_name="MAGIC FAIRYTALE MONIES!",
            source_type="autonomous_gain_lane",
            title=self.name,
            url=self.url,
            summary=self.summary,
            content_text=content,
            published_at=None,
            fetched_at=now,
            tags=self.tags + [self.category, "magic-fairytale-monies"],
            raw=self.to_dict(),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MagicOpportunityCandidate:
    source_name: str
    source_type: str
    title: str
    url: str
    summary: str
    content_text: str
    published_at: str | None
    fetched_at: str
    tags: list[str]
    raw: dict[str, Any]

    @property
    def fingerprint(self) -> str:
        basis = json.dumps(
            {
                "source_name": self.source_name,
                "source_type": self.source_type,
                "title": self.title,
                "url": self.url,
            },
            sort_keys=True,
        )
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True)
class MagicMoneyScoutSummary:
    lanes_scanned: int
    source_candidates_saved: int
    opportunities_saved: int
    queue_items_created: int
    queue_items_updated: int
    approval_gated_lanes: int
    high_risk_watch_lanes: int
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


MAGIC_MONEY_LANES: list[MagicMoneyLane] = [
    MagicMoneyLane(
        name="Simple Free Sample Request Lane",
        category="physical_goods",
        url="https://www.sampler.io/",
        summary="Low-friction free sample programs where AI can prepare reusable profile/shipping fields and queue owner accept.",
        tags=["free sample", "sample request", "physical goods", "shipping", "low friction"],
        autonomy_path="Scout free sample paths -> map safe profile/shipping fields -> queue bulk-safe owner approval -> track shipment.",
        ai_can_do=["find official sample paths", "prepare profile fields", "prepare shipping fields", "track shipment"],
        stops_on=[],
    ),
    MagicMoneyLane(
        name="Keep-It Product Tester Lane",
        category="physical_goods",
        url="https://www.hometesterclub.com/",
        summary="Product tester programs where users may receive and keep goods after simple feedback requirements.",
        tags=["product testing", "product tester", "keep products", "free product", "shipping"],
        autonomy_path="Scout product tester campaigns -> prepare reusable fields -> queue low-risk owner approval -> track delivery.",
        ai_can_do=["find tester campaigns", "prepare profile fields", "prepare shipping fields", "track delivery/follow-up"],
        stops_on=[],
    ),
    MagicMoneyLane(
        name="Paid User Testing Signup Lane",
        category="paid_research",
        url="https://www.usertesting.com/tester",
        summary="Paid website/app testing signup path; AI can prepare profile/payout fields and route tests needing human action.",
        tags=["paid user testing", "website testing", "paid study", "paypal", "low friction"],
        autonomy_path="Scout paid testing panels -> prepare profile/payout fields -> queue owner accept -> route human tests separately.",
        ai_can_do=["prepare signup fields", "route payout destination", "summarize tests", "track payout"],
        stops_on=[],
    ),
    MagicMoneyLane(
        name="Paid Research Participant Signup Lane",
        category="paid_research",
        url="https://www.userinterviews.com/participants",
        summary="Paid research participant signup and study matching path; AI can prep reusable profile details and payout routing.",
        tags=["paid research", "paid study", "gift card", "paypal", "low friction"],
        autonomy_path="Scout research panels -> prepare profile/payout fields -> queue owner accept -> route interviews/screeners.",
        ai_can_do=["prepare signup fields", "rank paid studies", "route payout destination", "track payout"],
        stops_on=[],
    ),
    MagicMoneyLane(
        name="Gift Card Rewards Signup Lane",
        category="paid_research",
        url="https://www.swagbucks.com/",
        summary="Reward and gift-card signup paths with low upfront friction; AI can prep signup data and payout preference.",
        tags=["gift card rewards", "reward signup", "cashback rewards", "signup bonus"],
        autonomy_path="Scout reward paths -> prepare safe signup/payout preference -> queue owner accept -> track rewards.",
        ai_can_do=["prepare signup fields", "route payout preference", "track reward balance", "surface cash-out steps"],
        stops_on=[],
    ),
    MagicMoneyLane(
        name="Beta Tester Rewards Signup Lane",
        category="paid_research",
        url="https://www.centercode.com/tester-network",
        summary="Beta tester network signup path for reward, gift-card, and product-test opportunities.",
        tags=["beta test", "app beta", "product tester", "gift card rewards"],
        autonomy_path="Scout beta tester networks -> prepare profile fields -> queue owner accept -> track invitations/rewards.",
        ai_can_do=["prepare profile fields", "rank beta invites", "track reward paths", "route follow-ups"],
        stops_on=[],
    ),
    MagicMoneyLane(
        name="FTC Refund Programs",
        category="cash_refunds",
        url="https://www.ftc.gov/enforcement/refunds",
        summary="Official refund programs for eligible consumers; AI can watch, summarize, and prepare claim packets.",
        tags=["official", "refund", "cash", "claim"],
        autonomy_path="Scout official refund list -> map eligibility -> prep claim packet -> owner final approval.",
        ai_can_do=["monitor official page", "extract deadlines", "prepare claim packet", "track status"],
        stops_on=["legal attestation", "identity verification", "final submit"],
    ),
    MagicMoneyLane(
        name="CFPB Harmed Consumer Payments",
        category="cash_refunds",
        url="https://www.consumerfinance.gov/enforcement/payments-harmed-consumers/payments-by-case/",
        summary="Official CFPB case directory for payments to harmed consumers; AI can watch cases and prepare recovery packets.",
        tags=["official", "refund", "cash", "harmed consumers"],
        autonomy_path="Monitor CFPB cases -> identify eligibility paths -> prepare owner packet -> owner final approval.",
        ai_can_do=["monitor official cases", "extract administrator/contact path", "prepare claim checklist", "track status"],
        stops_on=["legal attestation", "identity verification", "final submit"],
    ),
    MagicMoneyLane(
        name="SEC Harmed Investor Distributions",
        category="investor_recovery",
        url="https://www.sec.gov/enforcement-litigation/distributions-harmed-investors",
        summary="Official SEC harmed-investor distribution directory; AI can identify claim administrators and recovery paths.",
        tags=["official", "investor recovery", "cash", "claim"],
        autonomy_path="Scan SEC distributions -> match owner/domain assets if applicable -> prepare packet -> owner final approval.",
        ai_can_do=["monitor official distributions", "extract fund administrator details", "prepare eligibility checklist", "track status"],
        stops_on=["identity verification", "tax action", "legal attestation", "final submit"],
    ),
    MagicMoneyLane(
        name="Open Class Action Settlements",
        category="settlements",
        url="https://www.classaction.org/settlements",
        summary="Open settlement directory; AI can identify no/low-proof claims and prepare final approval packets.",
        tags=["settlement", "cash", "claim", "legal"],
        autonomy_path="Scan settlement rows -> rank low effort/high probability -> prepare packet -> owner final approval.",
        ai_can_do=["extract claim deadline", "map required fields", "prepare answers from vault", "route to approval"],
        stops_on=["legal attestation", "identity verification", "final submit"],
    ),
    MagicMoneyLane(
        name="No-Proof Settlement Sweep",
        category="settlements",
        url="https://www.openclassactions.com/",
        summary="Settlement directory with no-proof and low-friction claim paths; AI can rank easiest eligible packets first.",
        tags=["settlement", "cash", "claim", "no proof"],
        autonomy_path="Scan no-proof settlements -> rank fit/value/deadline -> prepare claim packet -> owner final approval.",
        ai_can_do=["extract deadlines", "detect proof requirements", "prepare safe fields", "queue approval packets"],
        stops_on=["legal attestation", "identity verification", "final submit"],
    ),
    MagicMoneyLane(
        name="USA.gov Unclaimed Money",
        category="unclaimed_money",
        url="https://www.usa.gov/unclaimed-money",
        summary="Official unclaimed money path; AI can route searches and prepare follow-up checklists.",
        tags=["official", "unclaimed", "cash", "claim"],
        autonomy_path="Open official state paths -> prepare search inputs -> owner approves identity-sensitive steps.",
        ai_can_do=["find correct state portal", "prepare reusable profile fields", "track claim status"],
        stops_on=["identity verification", "legal attestation", "final submit"],
    ),
    MagicMoneyLane(
        name="Product Testing / Free Samples Swarm",
        category="physical_goods",
        url="https://www.hometesterclub.com/",
        summary="Product testing and sample programs; AI can prepare profile/shipping fields and queue simple accepts.",
        tags=["product testing", "free sample", "physical goods", "shipping"],
        autonomy_path="Scout sample panels -> use vault shipping/profile -> owner accepts -> track shipment.",
        ai_can_do=["prepare profile", "autofill safe fields", "track shipment/follow-up"],
        stops_on=["purchase", "payment authorization", "final submit"],
    ),
    MagicMoneyLane(
        name="Full-Size Product Tester Sweep",
        category="physical_goods",
        url="https://www.tryable.com/",
        summary="Product testing lane for free goods in exchange for feedback; AI can prep safe profile/shipping information.",
        tags=["product testing", "free samples", "physical goods", "shipping"],
        autonomy_path="Scout tester campaigns -> map shipping/profile fields -> owner final approval -> track delivery/review due.",
        ai_can_do=["prepare profile", "autofill shipping", "queue accepts", "track delivery and review follow-up"],
        stops_on=["purchase", "payment authorization", "final submit"],
    ),
    MagicMoneyLane(
        name="Paid Research / User Testing",
        category="paid_research",
        url="https://www.respondent.io/respondents",
        summary="Paid research and testing panels; AI can find fits, prep profile, and route payout requirements.",
        tags=["paid research", "user testing", "cash rewards", "paypal"],
        autonomy_path="Scan paid studies -> match profile -> prep application -> owner approves/does human test.",
        ai_can_do=["rank studies", "prepare application fields", "route payout destination", "track payout"],
        stops_on=["human interview", "identity verification", "tax action", "final submit"],
    ),
    MagicMoneyLane(
        name="Paid Study Multi-Panel Sweep",
        category="paid_research",
        url="https://www.prolific.com/participants",
        summary="Paid online study lane; AI can prepare profiles, spot higher-probability studies, and route payout tracking.",
        tags=["paid research", "cash", "surveys", "paypal"],
        autonomy_path="Monitor paid panels -> match reusable context -> prep application/screener packet -> owner approves.",
        ai_can_do=["rank studies", "prepare profile fields", "summarize screener questions", "track submitted/paid status"],
        stops_on=["identity verification", "tax action", "human interview", "final submit"],
    ),
    MagicMoneyLane(
        name="Website/App Test Cash Lane",
        category="paid_research",
        url="https://trymata.com/",
        summary="Paid user-testing lane; AI can find tests, prepare test-readiness packets, and route payout requirements.",
        tags=["user testing", "cash", "paypal", "website testing"],
        autonomy_path="Scout user tests -> prep device/profile/payout fields -> owner does human test if required -> track payout.",
        ai_can_do=["prepare applications", "summarize test requirements", "route payout fields", "track payout"],
        stops_on=["human test", "screen recording consent", "identity verification", "tax action", "final submit"],
    ),
    MagicMoneyLane(
        name="Developer / Startup Credits",
        category="developer_credits",
        url="https://education.github.com/pack",
        summary="Developer, student, startup, cloud, and AI credit paths; AI can prep eligibility packets and connector needs.",
        tags=["developer", "startup", "cloud credit", "ai credit", "github"],
        autonomy_path="Scout credit portals -> map connector/login -> prep application -> owner approval.",
        ai_can_do=["prepare business fields", "suggest connectors", "draft applications", "track credit delivery"],
        stops_on=["login", "identity verification", "legal agreement", "final submit"],
    ),
    MagicMoneyLane(
        name="Startup Credit Marketplace Sweep",
        category="developer_credits",
        url="https://www.f6s.com/deals",
        summary="Startup deal and credit directories; AI can match business context to credits and prepare applications.",
        tags=["startup", "software credits", "cloud credits", "ai credits"],
        autonomy_path="Scan startup deal directories -> match Vault business profile -> prep applications -> owner final approval.",
        ai_can_do=["match eligibility", "prepare business profile", "draft applications", "track credit delivery"],
        stops_on=["login", "legal agreement", "identity verification", "tax action", "final submit"],
    ),
    MagicMoneyLane(
        name="AI / Cloud Credit Stack",
        category="developer_credits",
        url="https://www.mongodb.com/startups",
        summary="Founder/dev credit stack for cloud, database, AI, support, analytics, and startup tooling.",
        tags=["startup", "developer credits", "cloud credits", "ai credits"],
        autonomy_path="Map credit stack -> reuse business context -> prepare applications -> owner approves account/terms.",
        ai_can_do=["prepare application drafts", "reuse business fields", "rank highest-value credits", "track approvals"],
        stops_on=["login", "legal agreement", "identity verification", "final submit"],
    ),
    MagicMoneyLane(
        name="Crypto Learn-and-Earn Rewards",
        category="crypto_rewards",
        url="https://www.coinbase.com/learning-rewards",
        summary="Free crypto education/reward paths; AI can monitor, prepare profile/wallet fields, and stop at account gates.",
        tags=["crypto learn", "learning rewards", "free tokens", "wallet"],
        autonomy_path="Monitor learn-and-earn portals -> prep profile -> owner approves account/wallet steps.",
        ai_can_do=["find official reward path", "prepare public wallet/profile fields", "track reward status"],
        stops_on=["wallet signing", "kyc", "tax action", "account connection", "final submit"],
    ),
    MagicMoneyLane(
        name="Airdrop / Quest Watcher",
        category="crypto_airdrops",
        url="https://galxe.com/",
        summary="Web3 quests and airdrops; AI can watch, score legitimacy, prep task lists, and stop at signing/purchases.",
        tags=["airdrop", "quest", "free nft", "free tokens", "wallet signing"],
        autonomy_path="Scout quest portals -> score risk -> prepare task checklist -> owner controls wallet/signing.",
        ai_can_do=["monitor opportunities", "dedupe campaigns", "prepare non-signing tasks", "build risk packet"],
        stops_on=["wallet signing", "purchase", "swap", "bridge", "token approval", "kyc"],
        risk_level="medium",
    ),
    MagicMoneyLane(
        name="Public Wallet Quest Router",
        category="crypto_airdrops",
        url="https://layer3.xyz/",
        summary="Quest and campaign route that only prepares public-wallet and non-signing steps until owner approval.",
        tags=["crypto rewards", "quest", "airdrop", "public wallet"],
        autonomy_path="Scan quest portals -> remove purchase/signing tasks -> prep safe steps -> owner controls wallet actions.",
        ai_can_do=["dedupe campaigns", "score legitimacy", "prepare non-signing checklist", "track reward status"],
        stops_on=["wallet signing", "purchase", "swap", "bridge", "token approval", "kyc"],
        risk_level="medium",
    ),
    MagicMoneyLane(
        name="Open Source Bounties / Grants",
        category="bounties",
        url="https://github.com/sponsors",
        summary="Open source funding, bounties, and maintainer perks; AI can find matching work and prepare submissions.",
        tags=["bounty", "grant", "developer", "payout"],
        autonomy_path="Scout bounties -> match skills/repos -> prepare proposal/work packet -> owner approves.",
        ai_can_do=["rank tasks", "draft proposals", "prepare repo/context", "track payout"],
        stops_on=["tax action", "legal agreement", "final submit"],
    ),
    MagicMoneyLane(
        name="Developer Bounty Board Sweep",
        category="bounties",
        url="https://app.onlydust.com/",
        summary="Open-source bounty and reward boards; AI can shortlist feasible work and prepare contribution packets.",
        tags=["bounty", "developer", "open source", "payout"],
        autonomy_path="Scan bounty boards -> rank fit/time/value -> prepare task packet -> owner approves work/submit.",
        ai_can_do=["rank bounties", "draft issue approach", "prepare repo notes", "track payout"],
        stops_on=["tax action", "legal agreement", "final submit"],
    ),
    MagicMoneyLane(
        name="Prize Hackathon Sweep",
        category="prize_competitions",
        url="https://devpost.com/hackathons",
        summary="Prize competition and hackathon lane; AI can find deadlines, prepare ideas, and package submissions.",
        tags=["prize", "hackathon", "developer", "awards"],
        autonomy_path="Scan prize competitions -> rank AI-buildable entries -> prepare project packet -> owner final approval.",
        ai_can_do=["extract deadlines", "rank feasibility", "draft submission copy", "prepare project checklist"],
        stops_on=["legal agreement", "team eligibility", "final submit"],
    ),
    MagicMoneyLane(
        name="No-Purchase Sweepstakes / Giveaways",
        category="giveaways",
        url="https://www.sweepstakesadvantage.com/",
        summary="No-purchase giveaway discovery lane; AI can inspect rules and queue only low-risk official entries.",
        tags=["no purchase necessary", "giveaway", "prize", "ticket"],
        autonomy_path="Scout giveaways -> filter official/no-purchase -> prep entry -> owner final approval.",
        ai_can_do=["inspect rules", "filter purchase-required entries", "prepare safe fields", "track winners"],
        stops_on=["purchase", "legal attestation", "identity verification", "final submit"],
        risk_level="medium",
    ),
    MagicMoneyLane(
        name="Pump.fun / Meme Coin Simulator",
        category="high_risk_crypto_watch",
        url="https://pump.fun/",
        summary="Watch/simulation lane only. AI can research and simulate; no autonomous buys, sells, wallet signing, or trading.",
        tags=["crypto", "meme coin", "watcher", "simulation", "wallet signing", "purchase"],
        autonomy_path="Watch/simulate only -> surface risk packet -> owner makes any financial decision manually.",
        ai_can_do=["watch public data", "simulate outcomes", "flag scams/risks", "prepare research packet"],
        stops_on=["wallet signing", "purchase", "swap", "sell", "token approval", "payment authorization"],
        direct_queue=False,
        risk_level="high",
    ),
]


def run_magic_money_scout(store: Any, *, promote_to_queue: bool = True, limit: int = 200) -> MagicMoneyScoutSummary:
    """Seed broad gain lanes into the existing source, opportunity, and claim queue pipeline."""

    lanes = MAGIC_MONEY_LANES[:limit]
    source_saved = 0
    opportunities_saved = 0
    queue_created = 0
    queue_updated = 0
    approval_gated = 0
    high_risk = 0
    notes: list[str] = []

    for lane in lanes:
        _, source_is_new = store.save_source_candidate(lane.to_source_candidate())
        source_saved += int(source_is_new)
        approval_gated += int(bool(lane.stops_on))
        high_risk += int(lane.risk_level == "high")
        if not promote_to_queue or not lane.direct_queue:
            continue

        candidate = lane.to_opportunity_candidate()
        opportunity_id, opportunity_is_new = store.save_candidate(candidate)
        opportunities_saved += int(opportunity_is_new)
        score = _score_for_lane(lane)
        prep = _prep_for_lane(lane, score)
        if lane.stops_on:
            prep["safety_notes"] = (
                "MAGIC FAIRYTALE MONIES lane. AI may scout, prepare, autofill safe reusable fields, and track. "
                "Stop on: " + ", ".join(lane.stops_on) + "."
            )
        else:
            prep["safety_notes"] = (
                "MAGIC FAIRYTALE MONIES low-friction lane. AI may scout, prepare, autofill safe reusable fields, "
                "and track. If the official page introduces a hard blocker, route to owner review."
            )
        prep["ai_work_completed"] = "Seeded by autonomous gain lane scout; ready for dependency/autofill/final approval checks."
        status = "Ready to Accept" if not lane.stops_on and lane.risk_level == "low" else "Needs Approval"
        store.update_opportunity_score(opportunity_id, score, status)
        queue_id, created = store.save_queue_item(opportunity_id, score, prep, status)
        if created:
            queue_created += 1
        else:
            queue_updated += 1
        notes.append(f"Queued lane #{queue_id}: {lane.name}")

    notes.append("High-risk crypto/trading lanes are watch/simulation only; no autonomous buys, sells, or wallet signing.")
    notes.append("All lanes preserve final approval gates and the existing queue as source of truth.")
    return MagicMoneyScoutSummary(
        lanes_scanned=len(lanes),
        source_candidates_saved=source_saved,
        opportunities_saved=opportunities_saved,
        queue_items_created=queue_created,
        queue_items_updated=queue_updated,
        approval_gated_lanes=approval_gated,
        high_risk_watch_lanes=high_risk,
        notes=notes[-12:],
    )


def magic_money_lane_rows() -> list[dict[str, Any]]:
    return [
        {
            "lane": lane.name,
            "category": lane.category,
            "risk": lane.risk_level,
            "queue": "yes" if lane.direct_queue else "watch only",
            "ai_can_do": ", ".join(lane.ai_can_do),
            "stops_on": ", ".join(lane.stops_on),
            "url": lane.url,
        }
        for lane in MAGIC_MONEY_LANES
    ]


def _score_for_lane(lane: MagicMoneyLane) -> dict[str, Any]:
    category_defaults = {
        "cash_refunds": ("cash", 25, 7, 3, 80, "claim"),
        "investor_recovery": ("cash", 50, 5, 5, 68, "claim"),
        "settlements": ("cash", 35, 7, 3, 75, "claim"),
        "unclaimed_money": ("cash", 0, 6, 5, 65, "claim"),
        "physical_goods": ("physical_goods", 15, 6, 4, 78, "provide_shipping"),
        "paid_research": ("cash_rewards", 35, 6, 5, 70, "claim"),
        "developer_credits": ("developer_credits", 500, 6, 5, 72, "apply"),
        "crypto_rewards": ("crypto", 5, 5, 5, 62, "claim"),
        "crypto_airdrops": ("crypto", 5, 4, 6, 55, "approve"),
        "bounties": ("cash_rewards", 50, 5, 6, 65, "apply"),
        "prize_competitions": ("cash_rewards", 250, 3, 8, 58, "apply"),
        "giveaways": ("prize", 25, 4, 5, 60, "claim"),
        "high_risk_crypto_watch": ("crypto_watch", 0, 2, 9, 35, "manual_review"),
    }
    gain_type, value, probability, effort, ai_percent, action = category_defaults.get(
        lane.category,
        ("other", 0, 4, 7, 45, "approve"),
    )
    blocked = lane.risk_level == "high"
    return {
        "gain_type": gain_type,
        "expected_value_usd": value,
        "expected_value_rationale": "Deterministic estimate from autonomous gain lane type; actual owner value may vary.",
        "probability_score_1_to_10": probability,
        "risk_level": lane.risk_level,
        "risk_rationale": "Autonomous lane triage; final approval and sensitive action gates remain active.",
        "time_to_gain": "same day to several days" if value <= 50 else "days to weeks",
        "time_to_gain_days": 3 if value <= 50 else 14,
        "owner_effort_required": "Minimal: approve, connect, or provide reusable context when required.",
        "owner_effort_minutes": 5 if effort <= 5 else 15,
        "effort_score_1_to_10": effort,
        "ai_can_do_percent": ai_percent,
        "upfront_payment_required": blocked,
        "net_loss_possible": blocked,
        "illegal": False,
        "terms_violating": False,
        "scammy_or_terms_violating": blocked,
        "job_task_grind": False,
        "official_platform_action_required": True,
        "required_user_action": action,
        "real_asset_path": f"Autonomous lane points to an official/public gain path: {lane.url}",
        "destination": _destination_for_gain(gain_type),
        "expected_delivery_method": _destination_for_gain(gain_type),
        "should_add_to_claim_queue": not blocked,
        "fastest_gain_score": _score_speed(value, probability, effort),
        "highest_value_score": float(value) * max(1.0, float(probability)),
        "summary": lane.summary,
        "disqualification_reasons": ["watch/simulation only"] if blocked else [],
    }


def _prep_for_lane(lane: MagicMoneyLane, score: dict[str, Any]) -> dict[str, str]:
    if lane.stops_on:
        approval_needed = "Owner approval required for: " + ", ".join(lane.stops_on) + "."
        final_step = "Owner reviews prepared packet and chooses Approve, Reject, Later, or Needs More Info."
        recommended_status = "Needs Approval"
        safety_notes = "Hard-stop lane: route listed blockers to owner approval before any external submit."
    else:
        approval_needed = "Owner can bulk-approve this low-risk prepared submit after reviewing the fields."
        final_step = "Bulk-safe owner approval may move this prepared item to Submitted/processing for tracking."
        recommended_status = "Ready to Accept"
        safety_notes = "Low-friction lane: keep it to safe reusable fields and route unexpected blockers to owner review."
    return {
        "what_this_gain_is": f"{lane.name} is a {score.get('gain_type')} gain/acquisition lane.",
        "why_it_may_produce_real_asset_value": lane.summary,
        "exact_next_step": lane.autonomy_path,
        "ai_work_possible_now": "AI can scout, inspect official pages, map dependencies, prepare safe fields, and build approval packets.",
        "ai_work_completed": "Seeded by autonomous gain lane scout; ready for dependency/autofill/final approval checks.",
        "user_approval_needed": approval_needed,
        "copy_paste_form_answers": "",
        "claim_instructions": f"Use official/public path only: {lane.url}",
        "official_link": lane.url,
        "final_acceptance_step": final_step,
        "asset_landing": str(score.get("destination") or ""),
        "expected_delivery_method": str(score.get("expected_delivery_method") or ""),
        "follow_up_tracking_step": "Track submitted/processing/received/paid status after owner approval or reliable confirmation.",
        "recommended_status": recommended_status,
        "safety_notes": safety_notes,
    }


def _destination_for_gain(gain_type: str) -> str:
    if gain_type == "physical_goods":
        return "Owner shipping destination"
    if gain_type in {"developer_credits", "crypto_watch"}:
        return "Platform account or owner-approved dashboard"
    if gain_type == "crypto":
        return "Owner-approved public wallet or platform account"
    if gain_type == "prize":
        return "Owner email, account, shipping, or prize claim portal"
    return "Owner payout account, email, gift card, or claim portal"


def _score_speed(value: float, probability: float, effort: float) -> float:
    return round((float(probability) * max(1.0, float(value) + 10.0)) / max(1.0, float(effort)), 2)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
