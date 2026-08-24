# gain-entity

Self-expanding AI-assisted Gain Acquisition Entity for finding legitimate no-upfront-cost gains, scoring sources and opportunities, preparing execution steps, and keeping the owner in a small approval loop.

This project is intentionally separate from any existing user projects. It does not connect to outside accounts, submit claims, accept terms, provide payout details, or share credentials. The owner handles official-platform actions such as approve, connect, sign/accept terms, provide shipping or payout, claim, and accept asset.

## What It Does

- Fetches candidates from real RSS feeds, configurable URLs, and manual seed links.
- Discovers new source candidates through broad search queries and scores them before use.
- Auto-approves safe no-login/no-payment sources when allowed by `config/rules.yaml`; sends others to the Source Queue.
- Uses the OpenAI API with `gpt-4o-mini` by default to score due diligence fields.
- Applies Wide Free Net filtering by default, with strict mode available in `config/rules.yaml` or `--qualification-mode strict`.
- Rejects weak or vague `real_asset_path` values before anything reaches the owner.
- Generates execution prep before adding any candidate to the claim queue.
- Continues AI-safe work after the owner marks an item Approved.
- Can run on a local autonomy schedule through `src/autonomy/scheduler.py`.
- Generates manual search queries when no search provider key is configured.
- Ranks queued opportunities by value, speed, success probability, owner effort, AI completion potential, and risk.
- Applies source-family and root-domain diversity controls so Opportunity Intelligence does not tunnel into one source family.
- Advances approved items through a local autonomous execution layer when no owner-only input is required.
- Stores all data in SQLite and exports CSVs after each run.
- Provides a local Streamlit dashboard for queues, approvals, accepted items, rejections, and dead ends.

V2.5 queue records include `real_asset_path`, `destination`, `final_acceptance_step`, `ai_work_possible_now`, `ai_work_completed`, `user_approval_needed`, `expected_delivery_method`, `fastest_gain_score`, and `highest_value_score`.

## Install

```powershell
cd C:\Users\Thadmin Jarvis\Desktop\Gain-Entity\gain-entity
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a local `.env` file from `.env.example` and set `OPENAI_API_KEY`.

```powershell
Copy-Item .env.example .env
notepad .env
```

## Run

```powershell
python src/main.py
```

Each run prints an operator summary:

- new source candidates discovered,
- sources auto-approved,
- sources needing approval,
- opportunities fetched and queued,
- top fastest and highest-value gains,
- approvals needed,
- ready-to-accept items,
- received/paid and dead ends.

Strict mode:

```powershell
python src/main.py --qualification-mode strict
```

Refresh existing stored opportunities with new scoring/prep fields:

```powershell
python src/main.py --rescore-existing
```

The run will:

- fetch source candidates,
- store new opportunities,
- call OpenAI for due diligence scoring,
- add only qualified items to the claim queue,
- generate approval prep,
- export CSVs to `data/exports`,
- print a run summary with fastest gains, highest-value gains, approval-needed items, and ready-to-accept items.

For a source-only smoke check that does not call OpenAI:

```powershell
python src/main.py --fetch-only --limit 10
```

## Autonomy Scheduler

Autonomy Layer Phase 1 keeps the current architecture intact and adds a local scheduler wrapper around the normal entity run.

Enable or disable it in `config/rules.yaml`:

```yaml
autonomy_enabled: true
schedule_frequency: 6h
```

Supported frequencies are `1h`, `3h`, `6h`, `12h`, and `daily`.

Run once through the scheduler:

```powershell
python src/autonomy/scheduler.py --once
```

Run continuously:

```powershell
python src/autonomy/scheduler.py
```

The scheduled loop runs:

```text
discover -> score -> queue -> continue work -> prepare approvals -> update dashboard
```

## Dashboard

```powershell
streamlit run app/dashboard.py
```

The dashboard reads `data/gain_entity.sqlite3` by default. It shows:

- Gain Opportunities,
- Claim Queue,
- Source Candidates,
- Discovery Graph,
- Approved Sources,
- Rejected Sources,
- Needs Approval,
- Approved / AI Work Continuing,
- Execution Queue,
- AI Working,
- Paused Awaiting Input,
- Ready To Accept,
- Completed,
- Destination Routing,
- Ready to Accept,
- Needs Connect,
- Needs Shipping/Payout,
- Received/Paid,
- Dead Ends,
- Opportunity Intelligence,
- Autonomy Status.

It also includes claim status controls for Approve, Reject, Later, Connect Needed, Claim Submitted, Ready to Accept, Accepted, Received/Paid, and Dead End. Selecting Approve displays the exact next action, copy/paste text, official link, what the AI/system can do next, and the final accept/receive step. Source status controls let the owner approve, reject, or defer newly discovered sources.

The Opportunity Intelligence tab reads the claim queue through `src/intelligence/opportunity_ranker.py`. It shows Top Fastest Gains, Top Highest Probability, Top Highest Value, Top AI-Completable, and Top Immediate Actions, with Today, 3 Days, 7 Days, and 30 Days filters plus ranking reasons.

The Destination Routing tab reads normalized routing fields from the claim queue through `src/routing/destination_router.py` and `src/queue/acceptance_queue.py`. It shows expected asset, destination type, asset destination, owner input required, AI next action, post-approval action, final acceptance step, and received tracking note for high-priority items. Focused tabs also show Needs Connect and Needs Shipping/Payout.

The Discovery Graph tab reads `src/discovery/source_graph.py` and `src/discovery/diversity_guard.py` metadata. It shows source family distribution, category family distribution, dominant sources, underrepresented categories, exploration queue, source lineage, top new source candidates, and diversity warnings.

The execution tabs read `src/execution/action_engine.py` and its workers. After an item is approved, the engine decides whether AI can continue alone, moves safe work into AI Working, pauses on credentials/connect/signing/shipping/payout/identity needs, and moves completed prep toward Ready To Accept.

The Autonomy Status tab reads `data/autonomy_status.json` and shows last run, next run, sources searched, new candidates, opportunities found, AI work completed, approvals needed, ready-to-accept, received/paid, and cost guard usage.

## Configuration

Edit sources in:

```text
config/sources.yaml
```

Default source types:

- `rss_feeds`: live RSS feeds such as Grants.gov and NIH funding opportunity feeds.
- `configured_urls`: pages the source swarm fetches and optionally scans for relevant links.
- `manual_seed_links`: specific official pages to track as candidate asset paths.
- `future_web_search` and `future_inbox_import`: disabled extension points for later API/inbox connectors.

Edit safety/filter rules in:

```text
config/rules.yaml
```

Current mode is free/no-upfront-cost/no-loss/low-input. Paid acquisition paths are rejected into `Paid Mode Later` and are not placed in the active claim queue.

Source discovery defaults:

- `source_discovery_enabled: true`
- `auto_approve_safe_sources: true`
- `free_mode_only: true`
- `paid_mode_enabled: false`
- `source_candidate_min_score: 6`
- `discovery_graph_enabled: true`
- `max_discovery_depth: 3`
- `max_same_source_family_percent: 20`
- `max_same_domain_percent: 15`
- `exploration_weight: 0.35`
- `exploitation_weight: 0.65`
- `boost_underrepresented_categories: true`
- `max_openai_calls_per_run: 120`
- `max_candidates_per_run: 50`
- `max_sources_per_run: 8`
- `max_opportunities_per_run: 50`
- `approved_source_fetch_limit: 8`
- `search_provider: ManualQueryMode`

Wide-net mode defaults:

- `should_add_to_claim_queue` must be true,
- `risk_level` must not be high,
- `probability_score_1_to_10 >= 5`,
- `effort_score_1_to_10 <= 6`,
- `ai_can_do_percent >= 60`,
- `upfront_payment_required` must be false,
- `net_loss_possible` must be false,
- `real_asset_path` must be specific and official enough to act on.

Strict mode raises the threshold to probability 7+, effort 5 or lower, and AI-can-do 75%+.

## Search Providers

The search provider interface lives in `src/search/providers/`. Phase 1 includes provider shells for:

- `ManualQueryMode`
- `Brave`
- `Tavily`
- `SerpAPI`
- `Apify`

No provider API key is required. With the default `ManualQueryMode`, the system creates `data/manual_search_queries.csv` containing generated search queries. You can run those manually, paste promising URLs into `config/sources.yaml`, or later wire one of the provider classes to its official API.

To switch providers later, set `search_provider` and `source_discovery.provider` in `config/rules.yaml`, then add the provider's official API key to `.env`.

## Data

SQLite database:

```text
data/gain_entity.sqlite3
```

CSV exports:

```text
data/exports/opportunities.csv
data/exports/claim_queue.csv
data/exports/reject_log.csv
data/exports/dead_end_log.csv
data/exports/received_log.csv
data/exports/sources.csv
data/exports/source_candidates.csv
data/exports/approved_sources.csv
data/exports/rejected_sources.csv
data/exports/source_discovery_log.csv
data/exports/exploration_queue.csv
```

Autonomy and manual-search outputs:

```text
data/autonomy_status.json
data/manual_search_queries.csv
```

## Safety Boundaries

The system is designed to reject or defer opportunities that involve scams, deception, illegal activity, fake identities, credential sharing, terms violations, job/task-grind drift, upfront payments, net-loss paths, hidden fees, gray-market credit resale, or high risk.

The AI prepares and tracks. The owner approves and performs official-platform actions.
