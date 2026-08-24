# CURRENT STATE

Generated after unpacking and inspecting `gain-entity.zip` on 2026-05-19.

## Summary

This is an existing Python/SQLite/Streamlit Gain Acquisition Entity, not a blank scaffold. The architecture already follows the intended loop:

```text
Discover -> Score/Rank -> Queue -> Owner approval -> AI-safe continuation -> Route/track -> Export/dashboard
```

The strongest current theme is "approval-first autonomous prep." The entity can discover sources, fetch opportunities, score and filter them with OpenAI, prepare owner-facing execution packets, queue approvals, route expected assets, and continue limited AI-safe work after approval. It does not yet perform true browser execution, form submission, account connection, payout/shipping entry, external monitoring, or provider-backed web search.

The project already contains a populated runtime state:

- `data/gain_entity.sqlite3`
- CSV exports in `data/exports/`
- `data/autonomy_status.json`
- `data/manual_search_queries.csv`

Current database snapshot:

- `sources`: 47
- `opportunities`: 305
- `source_candidates`: 39
- `approved_sources`: 25
- `rejected_sources`: 4
- `claim_queue`: 50
- `reject_log`: 284
- `dead_end_log`: 0
- `received_log`: 0
- `exploration_queue`: 11
- `source_discovery_log`: 9

Claim queue status:

- `Needs Approval`: 46
- `Rejected`: 4

Execution status:

- `Execution Queue`: 50

Acceptance status:

- `Needs Approval`: 31
- `Needs Shipping`: 14
- `Needs Connect`: 4
- `Not Ready`: 1

## Project Structure

```text
gain-entity/
  app/
    dashboard.py
  config/
    rules.yaml
    sources.yaml
  data/
    gain_entity.sqlite3
    autonomy_status.json
    manual_search_queries.csv
    exports/
  prompts/
    source_scorer.txt
    gain_scorer.txt
    execution_prep.txt
    execution_continuation.txt
  src/
    main.py
    config.py
    ai/
    autonomy/
    discovery/
    execution/
    intelligence/
    queue/
    routing/
    search/
    sources/
    storage/
  README.md
  requirements.txt
```

There is also an unpacked `.venv/` and generated `__pycache__/` folders in the archive. No test suite was found.

## Existing Systems

### Source Discovery

Files:

- `src/sources/source_discovery.py`
- `src/sources/search_queries.py`
- `src/search/providers/`
- `config/sources.yaml`

What exists:

- Broad query catalog for lawful gain sources.
- Source discovery engine with known-URL dedupe.
- Manual query generation to `data/manual_search_queries.csv` when no provider is available.
- DuckDuckGo HTML scraping fallback.
- Provider interface for `ManualQueryMode`, `Brave`, `Tavily`, `SerpAPI`, and `Apify`.
- Source candidates are stored with fingerprints, graph metadata, discovery method, query, and raw payload.

Current limitation:

- Real provider classes are shells. They report available when API keys exist, but their `search()` methods currently return no results.
- Manual query mode is the default and intentionally does not search through an API.
- DuckDuckGo HTML scraping is brittle and may be blocked or unstable.

### Source Swarm / Candidate Fetching

Files:

- `src/sources/rss_sources.py`
- `config/sources.yaml`

What exists:

- RSS feed fetching through `feedparser`.
- Configured URL fetching through `requests` and BeautifulSoup.
- Link extraction from configured pages using gain-related keywords.
- Manual seed link preservation even when automatic fetch fails.
- Per-source candidate limits and dedupe.

Current limitation:

- Fetching is mostly static HTTP/HTML. It does not handle dynamic pages, authenticated pages, pagination, JavaScript-rendered listings, or anti-bot flows.
- Manual seed pages can become generic "opportunities" and depend heavily on the AI scorer to reject broad pages.

### Source Scoring and Source Queue

Files:

- `src/ai/source_scorer.py`
- `prompts/source_scorer.txt`
- `src/queue/source_queue.py`
- `src/storage/sqlite_store.py`

What exists:

- OpenAI-backed source due-diligence scoring.
- Normalization for source score, gain potential, freshness, searchability, risk, login/payment requirements, source type, tags, and real asset path signal.
- Source queue decision logic.
- Auto-approval for sufficiently scored safe no-login/no-payment sources.
- Dashboard status controls for approving, rejecting, or deferring source candidates.

Current limitation:

- Source approval is conservative but not deeply verified. It relies on AI interpretation of title/snippet/page content.
- Auto-approved sources can add more configured URLs, but source fetch behavior remains shallow.

### Opportunity Scoring / Claim Filtering

Files:

- `src/ai/scorer.py`
- `prompts/gain_scorer.txt`
- `src/queue/claim_queue.py`
- `src/storage/sqlite_store.py`

What exists:

- OpenAI-backed opportunity due diligence.
- Strong normalization of probability, value, risk, timing, effort, AI-completion percentage, payment/loss flags, real asset path, destination, and ranking scores.
- Wide-net and strict qualification modes.
- Hard rejection/defer rules for high risk, upfront payment, loss paths, illegal/terms-violating/scammy items, task-grind drift, weak real asset paths, low probability, high effort, low AI-doable work, and unsupported owner actions.
- Paid but otherwise non-scammy items go to `Paid Mode Later`.
- Rejection logging is persisted.

Current limitation:

- The scorer only sees fetched source text, so poor extraction or generic pages can produce weak scoring inputs.
- Ranking score quality depends on model output and normalization, not on independent verification.

### Opportunity Intelligence

Files:

- `src/intelligence/opportunity_ranker.py`
- `src/discovery/diversity_guard.py`
- `app/dashboard.py`

What exists:

- Ranking by value, speed, success probability, owner effort, AI-completion percentage, and risk.
- Time-window filtering for Today, 3 Days, 7 Days, and 30 Days.
- Top fastest, highest probability, highest value, AI-completable, and immediate-action views.
- Diversity-adjusted priority scoring.

Current limitation:

- Ranking is local and queue-based. It does not yet learn from outcomes, actual conversion, delivery, rejection rates, or user preferences beyond configured rules.

### Diversity Guard

Files:

- `src/discovery/diversity_guard.py`
- `src/discovery/source_graph.py`

What exists:

- Source family, category family, root domain, domain, depth, and lineage metadata.
- Dominance detection by source family and root domain.
- Underrepresented category detection.
- Exploration queue generation.
- Diversity adjustments to rankings.

Current limitation:

- Classification is rule/keyword based. It is useful but likely to drift as new source types appear.
- The guard adjusts ranking and exploration suggestions, but it does not hard-block fetch volume by family/domain during source selection beyond the simple selected-source cap.

### Source Graph

Files:

- `src/discovery/source_graph.py`
- `src/storage/sqlite_store.py`

What exists:

- Lightweight graph metadata enrichment for opportunities and source candidates.
- Recursive query generation from approved sources and underrepresented categories.
- Stored lineage in JSON.
- Exploration queue refreshed from active claim queue data.

Current limitation:

- This is a metadata graph, not a traversable graph database.
- Recursion is query-generation only. It does not crawl deeper source-to-source relationships directly.

### Approval Queue

Files:

- `src/queue/approval_router.py`
- `src/queue/claim_queue.py`
- `app/dashboard.py`
- `src/storage/sqlite_store.py`

What exists:

- Claim queue with owner-facing statuses.
- Dashboard actions: approve, reject, later, connect needed, submitted, ready to accept, accepted, received/paid, dead end.
- Approval screen shows exact next step, copy/paste text, official link, AI/system next work, and final accept/receive step.
- Approving an item triggers action-engine evaluation and execution-state fields.

Current limitation:

- Approval is only local dashboard state. There is no notification, inbox, mobile push, or single-click approval outside Streamlit.
- Status changes do not yet trigger a separate durable worker process; the next autonomous continuation occurs when the main run/scheduler processes approved items.

### Execution Workers

Files:

- `src/execution/action_engine.py`
- `src/execution/account_worker.py`
- `src/execution/browser_worker.py`
- `src/execution/form_worker.py`
- `src/execution/routing_worker.py`
- `src/execution/submission_worker.py`
- `src/ai/execution_continuation.py`

What exists:

- Action engine gates AI work after approval.
- Account/routing blockers pause work when credentials, login, terms, identity, shipping, payout, bank, PayPal, Stripe, or wallet input is required.
- Form worker identifies existing prepared form/instruction packets.
- Browser worker prepares an official-link review action.
- Submission worker moves approved/prepared items toward `AI Working`, `Ready To Accept`, or paused states.
- OpenAI continuation can refine instructions and set recommended next status after owner approval.

Current limitation:

- Workers are decision/prep workers, not actual browser/form automation workers.
- `BrowserWorker` does not open pages or inspect DOMs.
- `FormWorker` does not parse forms.
- `SubmissionWorker` does not submit anything.
- This is appropriate for current safety boundaries, but it is not yet autonomous execution in the stronger sense.

### Routing and Destination Routing

Files:

- `src/routing/destination_router.py`
- `src/queue/acceptance_queue.py`
- `src/storage/sqlite_store.py`
- `app/dashboard.py`

What exists:

- Destination type inference: PayPal, Stripe, bank, crypto wallet, gift card, shipping address, email, platform account, marketplace account, cloud/API credit account, local pickup, claim portal, unknown.
- Asset type inference: cash, crypto, gift card, rebate, reward points, physical good, software license, cloud/AI/developer credit, affiliate commission, creator payout, grant, ticket, membership, unclaimed property, other.
- Acceptance status inference: not ready, needs approval, needs connect, needs shipping, needs payout, needs identity verification, ready to accept, accepted, received/paid, dead end.
- Routing fields are normalized into `claim_queue` and shown in dashboard.

Current limitation:

- Routing is heuristic text matching. It will drift on new wording and ambiguous destinations.
- No external destination validation exists.

### Dashboard

File:

- `app/dashboard.py`

What exists:

- Streamlit dashboard with metrics and tabs for opportunities, claim queue, sources, discovery graph, approvals, execution states, routing, received/paid, dead ends, opportunity intelligence, and autonomy status.
- Claim and source status controls.
- Received/Paid action logs received records.
- Approving a claim runs the action engine immediately.

Current limitation:

- Dashboard is data-table heavy and operational, not a guided workflow UI.
- It does not currently provide batch approval, filtering by "fastest/highest probability/minimal effort" in the status-control selector, or an approval inbox optimized for rapid user decisions.
- It assumes local access to the SQLite database.

### Autonomy Logic

Files:

- `src/main.py`
- `src/autonomy/scheduler.py`
- `data/autonomy_status.json`
- `config/rules.yaml`

What exists:

- Main run performs discovery, source approval/scoring, source merge, opportunity fetch, score/filter/prep, approved-item continuation, graph refresh, CSV export, and autonomy status update.
- Scheduler can run once or loop every `1h`, `3h`, `6h`, `12h`, or daily.
- Cost guard limits OpenAI calls, candidates per run, and sources per run.
- Autonomy status records last run, next run, sources searched, new candidates, opportunities found, AI work completed, approvals needed, ready-to-accept, received/paid, and cost guard usage.

Current limitation:

- Scheduler is a local foreground loop, not a service, daemon, cron, or cloud worker.
- No locking prevents overlapping runs.
- No retry/backoff strategy beyond catching per-source/per-item errors.
- No external alerts when approval is required or a gain is ready to accept.

## Completed Features

- Project has a coherent existing architecture and preserved pipeline.
- Runtime settings, YAML config, prompt files, and environment loading exist.
- SQLite schema covers sources, opportunities, source candidates, approved/rejected sources, claim queue, rejection log, dead-end log, received log, discovery log, and exploration queue.
- Schema migration helpers exist for newer columns.
- Source discovery, source scoring, source queueing, source approval, and approved-source merge exist.
- RSS/configured/manual source swarm exists.
- Opportunity scorer, strict/wide-net filter, execution prep, and queue persistence exist.
- Ranking and opportunity intelligence exist.
- Diversity guard and source graph metadata exist.
- Destination routing and acceptance normalization exist.
- Execution state engine and safety blockers exist.
- Local scheduler and autonomy status exist.
- CSV export exists.
- Streamlit dashboard exists and can mutate local statuses.
- Existing data shows the system has run multiple times and populated queues.

## Incomplete Features

- Provider-backed search is not implemented for Brave, Tavily, SerpAPI, or Apify.
- Browser execution is not implemented; browser worker only prepares a public-link review action.
- Form parsing/filling is not implemented; form worker only uses existing prepared copy/instructions.
- Actual autonomous submission is not implemented and remains intentionally blocked by safety boundaries.
- No notification channel for approvals or ready-to-accept items.
- No durable job queue or background worker beyond the local scheduler loop.
- No tests were found.
- No outcome learning from received/paid, dead ends, approvals, or rejections.
- No robust source health scoring beyond stored source metadata and last fetched timestamp.
- No deduplicated "approval inbox" optimized around user priorities.
- No external account connectors, inbox import, or authenticated source ingestion.

## Weaknesses

- The default source discovery mode depends on manual queries and DuckDuckGo HTML scraping, so discovery quality and reliability are limited.
- The current system has 46 items needing approval and 0 received/paid, suggesting the bottleneck is owner approval and execution follow-through.
- All 50 claim queue items are still in `Execution Queue`; none have progressed to `AI Working`, `Ready To Accept`, or `Completed` in the current DB snapshot.
- Routing and graph classification are heuristic and keyword-driven.
- Opportunity quality is highly dependent on AI scorer outputs from shallow source text.
- The dashboard exposes many tables but does not yet minimize user effort for the fastest/highest-probability approval path.
- There is no first-class "fastest gains approval lane" even though fastest gains are a top priority.
- Cost guard protects AI calls but not HTTP fetch volume, page quality, or low-yield source churn.
- The local `.env`, SQLite database, exports, `.venv`, and generated caches are included in the archive. That is convenient for handoff but risky for repeatable project hygiene.

## Likely Drift Points

- Search provider shells may look available when keys are set but still return no results.
- Source scoring can approve sources that are safe but low-yield if the prompt overestimates asset paths.
- Generic directory/homepage pages can re-enter the pipeline unless the scorer/filter remains strict about specific claimable opportunities.
- New destination language may bypass the destination router's keyword checks.
- Source family/category classification will drift as the system discovers new categories outside the current keyword map.
- The dashboard action list and `config/rules.yaml` statuses can diverge from action-engine statuses such as `AI Working`, `Execution Queue`, and `Paused Awaiting Input`.
- Approval state and execution state can become confusing because claim `status`, `acceptance_status`, and `execution_status` are related but separate.
- Scheduler and manual dashboard updates can overlap if used at the same time.
- Existing exports may be mistaken for source of truth, but SQLite is the real source of truth.
- Manual seed links and configured URLs can create broad candidates that look like opportunities but are only discovery pages.

## Recommended Next Steps

1. Build a "Fastest Gains Approval Lane" inside the existing dashboard.
   - Use the existing claim queue, ranker, destination router, and action fields.
   - Sort by fastest gain score, probability, low effort, AI-can-do percentage, and low risk.
   - Show only the exact owner decision needed: approve, reject, later, connect, provide shipping/payout, or accept.

2. Implement a provider-backed search path without changing architecture.
   - Fill in one existing provider shell first, preferably Brave or Tavily.
   - Preserve the `SearchProviderResult` interface.
   - Keep ManualQueryMode as fallback.

3. Add lightweight tests around the highest-risk logic.
   - `StrictFilter`
   - `DestinationRouter`
   - `DiversityGuard`
   - `SourceGraph`
   - `ActionEngine`
   - scoring/prep normalization functions

4. Add an approval/ready notification layer.
   - Keep it local and approval-first.
   - Notify when high-priority items enter `Needs Approval`, `Connect Needed`, or `Ready to Accept`.

5. Tighten the execution-state loop.
   - After dashboard approval, ensure approved items are re-evaluated and moved to `AI Working`, `Paused Awaiting Input`, or `Ready To Accept` consistently.
   - Consider a small local worker command that only processes approved items.

6. Improve source quality controls.
   - Track per-source yield: fetched, queued, rejected, approved, received/paid.
   - Prefer high-yield sources during `select_sources_for_run`.
   - Penalize sources that repeatedly produce generic pages or rejected opportunities.

7. Add outcome feedback.
   - Use `Received/Paid`, `Dead End`, `Rejected`, and `Later` history to adjust ranking and exploration.
   - Keep this as a scoring/ranking layer, not an architectural rewrite.

8. Clean project hygiene later.
   - Decide whether `.venv`, runtime DB, exports, and caches should remain archived.
   - Preserve current state before cleanup because the DB contains useful operational history.

## Architecture Preservation Notes

The next work should extend the existing modules instead of replacing them:

- Put search integrations in `src/search/providers/`.
- Keep source discovery in `src/sources/source_discovery.py`.
- Keep queue qualification in `src/queue/claim_queue.py` and `src/queue/source_queue.py`.
- Keep prioritization in `src/intelligence/opportunity_ranker.py`.
- Keep diversity/source graph logic in `src/discovery/`.
- Keep destination normalization in `src/routing/destination_router.py`.
- Keep autonomous continuation inside `src/execution/` plus `src/ai/execution_continuation.py`.
- Keep dashboard workflow changes in `app/dashboard.py`.

The most valuable immediate improvement is not a redesign. It is turning the current 46 approval-needed items into a low-effort, high-confidence approval workflow that prioritizes fastest gains and then lets the existing continuation/routing machinery advance them.

## Architectural Laws

1. Never bypass final approval for sensitive actions.
2. Extend architecture; do not replace.
3. Queue/database state is source of truth.
4. User Context feeds Required Inputs.
5. Required Inputs feeds Continuation Engine.
6. Dashboard visualizes state; it should not become the core logic.
7. Credentials are never stored in plaintext.
8. Do not store passwords or full bank numbers.
9. Human remains final authority for payment, legal, identity, tax, login, purchase, and submission actions.
10. Open to Everything means discover broadly, but execute only through safety gates.
11. Sensitive blockers remain final-approval-required.
12. Missing reusable inputs should become specific buckets, not vague pauses.
13. Any new module must preserve existing discovery, queue, routing, ranking, and dashboard flow.

## Current System Direction

```text
Discovery
-> Ranking
-> Approval
-> Required Inputs Detector
-> User Context Lookup
-> AI Continuation
-> Final Approval
-> Asset/Gain Routing
-> Received/Paid tracking
```

## Owner Interaction Principle

Purpose: minimize repeated owner interruptions.

- If missing data already exists in User Context, AI should silently continue through the safe continuation path.
- If missing data exists in a connected account, AI should retrieve or reference it through the approved connector path and continue, without storing credentials.
- If multiple opportunities require the same reusable input, request it once and propagate it globally through User Context.
- Missing inputs should be grouped by global dependency, not presented as repeated per-claim interruptions.
- Completion prompts should explain leverage, for example: "Completing this unlocks 14 opportunities."
- Once a reusable input is added, all blocked claims depending on that input should become eligible for required-input refresh and continuation.

Examples:

```text
shipping_address
blocks:
- Free Samples
- Carhartt
- Merchology

paypal_email
blocks:
- Honey Rewards
- Cashback sites

github_login
blocks:
- GitHub Student Pack
- Developer offers
```

Missing inputs are sorted by unlock leverage:

```text
unlock_score = number_unblocked * value_score * probability_score
```
