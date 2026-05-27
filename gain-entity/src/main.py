from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ai.execution_continuation import ExecutionContinuationGenerator
from ai.execution_prep import ExecutionPrepGenerator
from ai.heuristic_source_scorer import heuristic_source_score
from ai.heuristic_opportunity import heuristic_execution_prep, heuristic_opportunity_score
from ai.scorer import AIScorer
from ai.source_scorer import SourceScorer
from config import ensure_runtime_dirs, load_settings, load_yaml_file, read_prompt
from discovery.source_graph import SourceGraph
from execution.action_engine import ActionEngine
from sources.rss_sources import SourceCandidate, SourceSwarm
from sources.source_discovery import SourceDiscoveryEngine
from storage.sqlite_store import SQLiteStore


def _configure_console_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def main() -> int:
    _configure_console_output()
    settings = load_settings()
    args = parse_args(settings)
    ensure_runtime_dirs(settings)

    source_config = load_yaml_file(settings.sources_path)
    rules = load_yaml_file(settings.rules_path)
    if args.qualification_mode:
        rules["qualification_mode"] = args.qualification_mode
    cost_guard = build_cost_guard(rules)

    store = SQLiteStore(args.database_path)
    store.init_db()

    source_stats = {
        "new_source_candidates_discovered": 0,
        "source_candidates_saved": 0,
        "sources_auto_approved": 0,
        "sources_needing_approval": 0,
        "sources_rejected": 0,
        "source_errors": [],
    }

    if rules.get("source_discovery_enabled", True) and not args.skip_source_discovery:
        source_stats = run_source_discovery(
            settings=settings,
            args=args,
            rules=rules,
            store=store,
            cost_guard=cost_guard,
        )

    approved_fetch_limit = int(cost_guard.get("max_sources_per_run", 0) or 0)
    source_config = merge_approved_sources(source_config, store.approved_source_records()[:approved_fetch_limit])
    source_config = select_sources_for_run(source_config, approved_fetch_limit)

    swarm = SourceSwarm(
        source_config,
        max_candidates_per_source=args.max_candidates_per_source,
        request_timeout_seconds=settings.request_timeout_seconds,
        user_agent=settings.user_agent,
    )
    source_records = swarm.source_records()
    store.upsert_sources(source_records)

    fetch_result = swarm.fetch_all()
    store.mark_sources_fetched(source_records)

    opportunity_cap = args.limit or int(rules.get("max_candidates_per_run", rules.get("max_opportunities_per_run", 50)) or 0)
    fetched_candidates = fetch_result.candidates
    if opportunity_cap and len(fetched_candidates) > opportunity_cap:
        cost_guard["candidate_cap_applied"] = True
        fetched_candidates = fetched_candidates[:opportunity_cap]

    stored_candidates: list[tuple[int, SourceCandidate, bool]] = []
    for candidate in fetched_candidates:
        opportunity_id, is_new = store.save_candidate(candidate)
        stored_candidates.append((opportunity_id, candidate, is_new))

    process_candidates: list[tuple[int, Any, bool]] = []
    for opportunity_id, candidate, is_new in stored_candidates:
        should_process = is_new or args.rescore_existing or store.opportunity_needs_score(opportunity_id)
        if not should_process:
            continue
        process_candidates.append((opportunity_id, candidate, is_new))
        if opportunity_cap and len(process_candidates) >= opportunity_cap:
            break
    if not args.rescore_existing and (not opportunity_cap or len(process_candidates) < opportunity_cap):
        remaining = 0 if not opportunity_cap else opportunity_cap - len(process_candidates)
        exclude_ids = {opportunity_id for opportunity_id, _, _ in process_candidates}
        process_candidates.extend(
            store.pending_opportunities(limit=remaining or 50, exclude_ids=exclude_ids)
        )

    added_to_queue = 0
    rejected = 0
    scored = 0
    continuations = 0

    if rules.get("heuristic_opportunity_triage_enabled", True):
        strict_filter_cls = load_class(Path(__file__).parent / "queue" / "claim_queue.py", "StrictFilter")
        strict_filter = strict_filter_cls(rules)
        heuristic_limit = int(rules.get("heuristic_opportunity_triage_limit", opportunity_cap or 80) or 0)
        heuristic_count = 0
        for opportunity_id, candidate, is_new in process_candidates:
            if heuristic_limit and heuristic_count >= heuristic_limit:
                break
            if not (is_new or args.rescore_existing or store.opportunity_needs_score(opportunity_id)):
                continue
            score = heuristic_opportunity_score(candidate)
            filter_result = strict_filter.evaluate(score)
            store.update_opportunity_score(opportunity_id, score, filter_result.status)
            heuristic_count += 1
            if filter_result.qualified:
                prep = heuristic_execution_prep(candidate, score)
                queue_status = _recommended_status(prep, filter_result.status)
                _, created = store.save_queue_item(
                    opportunity_id=opportunity_id,
                    score=score,
                    prep=prep,
                    status=queue_status,
                )
                store.update_opportunity_prep(opportunity_id, prep)
                if created:
                    added_to_queue += 1
            else:
                store.log_rejection(
                    opportunity_id=opportunity_id,
                    status=filter_result.status,
                    reasons=filter_result.reasons,
                    score=score,
                )
                rejected += 1

    if args.fetch_only:
        store.refresh_exploration_queue()
        store.normalize_required_inputs()
        store.export_csvs(settings.exports_dir)
        write_autonomy_status(
            settings=settings,
            rules=rules,
            store=store,
            source_stats=source_stats,
            sources_searched=len(source_records),
            opportunities_found=len(fetched_candidates),
            ai_work_completed=continuations,
            cost_guard=cost_guard,
        )
        print_run_summary(
            store=store,
            candidates_fetched=len(fetched_candidates),
            candidates_considered=len(fetched_candidates),
            added_to_queue=added_to_queue,
            rejected=rejected,
            source_errors=fetch_result.errors,
            fetch_only=True,
            source_stats=source_stats,
            cost_guard=cost_guard,
            sources_searched=len(source_records),
        )
        return 0

    if not settings.openai_api_key:
        store.refresh_exploration_queue()
        store.normalize_required_inputs()
        store.export_csvs(settings.exports_dir)
        write_autonomy_status(
            settings=settings,
            rules=rules,
            store=store,
            source_stats=source_stats,
            sources_searched=len(source_records),
            opportunities_found=len(fetched_candidates),
            ai_work_completed=continuations,
            cost_guard=cost_guard,
        )
        print_run_summary(
            store=store,
            candidates_fetched=len(fetched_candidates),
            candidates_considered=len(process_candidates),
            added_to_queue=added_to_queue,
            rejected=rejected,
            source_errors=fetch_result.errors,
            fetch_only=False,
            source_stats=source_stats,
            cost_guard=cost_guard,
            sources_searched=len(source_records),
        )
        print("\nOpenAI scoring was not run because OPENAI_API_KEY is missing in .env.")
        return 2

    strict_filter_cls = load_class(Path(__file__).parent / "queue" / "claim_queue.py", "StrictFilter")
    strict_filter = strict_filter_cls(rules)
    scorer = AIScorer(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        prompt=read_prompt(settings, "gain_scorer.txt"),
    )
    prep_generator = ExecutionPrepGenerator(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        prompt=read_prompt(settings, "execution_prep.txt"),
    )
    continuation_generator = ExecutionContinuationGenerator(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        prompt=read_prompt(settings, "execution_continuation.txt"),
    )
    action_engine = ActionEngine()

    for opportunity_id, candidate, is_new in process_candidates:
        if not can_use_openai(cost_guard, 1):
            cost_guard["stopped_by_cost_guard"] = True
            break
        try:
            store.update_opportunity_status(opportunity_id, "AI Work Started")
            score = scorer.score(candidate)
            record_openai_call(cost_guard, "opportunity_score")
            scored += 1
            filter_result = strict_filter.evaluate(score)

            if filter_result.qualified:
                if not can_use_openai(cost_guard, 1):
                    cost_guard["stopped_by_cost_guard"] = True
                    break
                store.update_opportunity_score(opportunity_id, score, "AI Work Complete")
                prep = prep_generator.prepare(candidate, score)
                record_openai_call(cost_guard, "execution_prep")
                queue_status = _recommended_status(prep, filter_result.status)
                _, created = store.save_queue_item(
                    opportunity_id=opportunity_id,
                    score=score,
                    prep=prep,
                    status=queue_status,
                )
                store.update_opportunity_prep(opportunity_id, prep)
                if created:
                    added_to_queue += 1
            else:
                store.update_opportunity_score(opportunity_id, score, filter_result.status)
                store.log_rejection(
                    opportunity_id=opportunity_id,
                    status=filter_result.status,
                    reasons=filter_result.reasons,
                    score=score,
                )
                rejected += 1
        except Exception as exc:  # noqa: BLE001 - keep the run moving and track the failed item
            store.log_dead_end(opportunity_id, f"AI processing failed: {exc}")

    for item in store.claim_items_by_status(["Approved"], limit=args.continue_approved_limit):
        action_result = action_engine.evaluate(item)
        store.update_claim_execution(item["id"], action_result)
        if not action_result.can_continue_alone or action_result.execution_status == "Paused Awaiting Input":
            continue
        if not can_use_openai(cost_guard, 1):
            cost_guard["stopped_by_cost_guard"] = True
            break
        try:
            continuation = continuation_generator.continue_work(item)
            record_openai_call(cost_guard, "execution_continuation")
            store.update_claim_continuation(item["id"], continuation)
            continuations += 1
        except Exception as exc:  # noqa: BLE001
            store.log_dead_end(item.get("opportunity_id"), f"AI continuation failed: {exc}")

    store.refresh_exploration_queue()
    store.normalize_required_inputs()
    store.export_csvs(settings.exports_dir)
    write_autonomy_status(
        settings=settings,
        rules=rules,
        store=store,
        source_stats=source_stats,
        sources_searched=len(source_records),
        opportunities_found=len(fetched_candidates),
        ai_work_completed=continuations + added_to_queue,
        cost_guard=cost_guard,
    )
    print_run_summary(
        store=store,
        candidates_fetched=len(fetched_candidates),
        candidates_considered=len(process_candidates),
        added_to_queue=added_to_queue,
        rejected=rejected,
        source_errors=fetch_result.errors,
        fetch_only=False,
        scored=scored,
        source_stats=source_stats,
        continuations=continuations,
        cost_guard=cost_guard,
        sources_searched=len(source_records),
    )
    return 0


def parse_args(settings: Any) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Gain Acquisition Entity source and claim pipeline.")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum total opportunities to consider this run. 0 uses config max_opportunities_per_run.",
    )
    parser.add_argument(
        "--max-candidates-per-source",
        type=int,
        default=settings.max_candidates_per_source,
        help="Maximum items fetched from each source.",
    )
    parser.add_argument(
        "--database-path",
        type=Path,
        default=settings.database_path,
        help="SQLite database path.",
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Fetch and store candidates without calling OpenAI.",
    )
    parser.add_argument(
        "--rescore-existing",
        action="store_true",
        help="Rescore existing opportunities in this run.",
    )
    parser.add_argument(
        "--qualification-mode",
        choices=["wide_net", "strict"],
        default=None,
        help="Override config/rules.yaml qualification_mode for this run.",
    )
    parser.add_argument(
        "--skip-source-discovery",
        action="store_true",
        help="Skip self-expanding source discovery for this run.",
    )
    parser.add_argument(
        "--rescore-sources",
        action="store_true",
        help="Rescore existing source candidates in this run.",
    )
    parser.add_argument(
        "--continue-approved-limit",
        type=int,
        default=10,
        help="Maximum Approved claim queue items to continue with AI after scoring.",
    )
    return parser.parse_args()


def load_class(path: Path, class_name: str) -> Any:
    spec = importlib.util.spec_from_file_location("gain_entity_claim_queue", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {class_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def run_source_discovery(
    settings: Any,
    args: Any,
    rules: dict[str, Any],
    store: SQLiteStore,
    cost_guard: dict[str, Any],
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "new_source_candidates_discovered": 0,
        "source_candidates_saved": 0,
        "sources_auto_approved": 0,
        "sources_needing_approval": 0,
        "sources_rejected": 0,
        "source_errors": [],
    }
    started_at = _utc_now()
    discovery = SourceDiscoveryEngine(
        rules=rules,
        request_timeout_seconds=settings.request_timeout_seconds,
        user_agent=settings.user_agent,
    )
    extra_queries = []
    if rules.get("discovery_graph_enabled", True):
        graph = SourceGraph(rules)
        extra_queries = graph.recursive_queries(
            approved_sources=store.approved_source_records(),
            exploration_items=store.exploration_queue_records(limit=6),
            limit=8,
        )
    result = discovery.discover(store.known_source_urls(), extra_queries=extra_queries)
    stats["new_source_candidates_discovered"] = len(result.candidates)
    stats["source_errors"] = result.errors

    saved: list[tuple[int, Any, bool]] = []
    for candidate in result.candidates:
        candidate_id, is_new = store.save_source_candidate(candidate)
        if is_new:
            stats["source_candidates_saved"] += 1
        saved.append((candidate_id, candidate, is_new))

    seen_candidate_ids = {candidate_id for candidate_id, _, _ in saved}
    for candidate_id, payload in store.pending_source_candidates(limit=50):
        if candidate_id in seen_candidate_ids:
            continue
        saved.append((candidate_id, payload, False))
        seen_candidate_ids.add(candidate_id)

    if rules.get("heuristic_source_auto_approval_enabled", True):
        source_queue_cls = load_class(Path(__file__).parent / "queue" / "source_queue.py", "SourceQueue")
        source_queue = source_queue_cls(rules)
        heuristic_limit = int(rules.get("heuristic_source_approval_limit", 120) or 0)
        heuristics_scored = 0
        for candidate_id, candidate, is_new in saved:
            if heuristic_limit and heuristics_scored >= heuristic_limit:
                break
            if not (is_new or args.rescore_sources or store.source_candidate_needs_score(candidate_id)):
                continue
            try:
                score = heuristic_source_score(candidate)
                decision = source_queue.evaluate(score)
                reason = "heuristic: " + "; ".join(decision.reasons)
                store.update_source_candidate_score(candidate_id, score, decision.status, reason)
                heuristics_scored += 1
                if decision.status == "Approved":
                    if store.approve_source_candidate(candidate_id, score):
                        stats["sources_auto_approved"] += 1
                elif decision.status == "Rejected":
                    store.reject_source_candidate(candidate_id, reason, score)
                    stats["sources_rejected"] += 1
                else:
                    stats["sources_needing_approval"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["source_errors"].append(f"heuristic source candidate {candidate_id}: {exc}")

    if settings.openai_api_key and not args.fetch_only:
        source_scorer = SourceScorer(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            prompt=read_prompt(settings, "source_scorer.txt"),
        )
        source_queue_cls = load_class(Path(__file__).parent / "queue" / "source_queue.py", "SourceQueue")
        source_queue = source_queue_cls(rules)
        sources_scored = 0
        max_sources = int(rules.get("max_sources_per_run", 8) or 0)
        for candidate_id, candidate, is_new in saved:
            if not (is_new or args.rescore_sources or store.source_candidate_needs_score(candidate_id)):
                continue
            if max_sources and sources_scored >= max_sources:
                break
            if not can_use_openai(cost_guard, 1):
                cost_guard["stopped_by_cost_guard"] = True
                break
            try:
                score = source_scorer.score(candidate)
                record_openai_call(cost_guard, "source_score")
                sources_scored += 1
                decision = source_queue.evaluate(score)
                reason = "; ".join(decision.reasons)
                store.update_source_candidate_score(candidate_id, score, decision.status, reason)
                if decision.status == "Approved":
                    if store.approve_source_candidate(candidate_id, score):
                        stats["sources_auto_approved"] += 1
                elif decision.status == "Rejected":
                    store.reject_source_candidate(candidate_id, reason, score)
                    stats["sources_rejected"] += 1
                else:
                    stats["sources_needing_approval"] += 1
            except Exception as exc:  # noqa: BLE001
                stats["source_errors"].append(f"source candidate {candidate_id}: {exc}")

    store.log_source_discovery(
        run_started_at=started_at,
        run_finished_at=_utc_now(),
        queries_run=result.queries_run,
        candidates_discovered=len(result.candidates),
        candidates_saved=stats["source_candidates_saved"],
        sources_auto_approved=stats["sources_auto_approved"],
        sources_needing_approval=stats["sources_needing_approval"],
        sources_rejected=stats["sources_rejected"],
        errors=stats["source_errors"],
    )
    return stats


def merge_approved_sources(source_config: dict[str, Any], approved_records: list[dict[str, Any]]) -> dict[str, Any]:
    merged = {
        key: [dict(item) for item in source_config.get(key, [])]
        for key in ["rss_feeds", "configured_urls", "manual_seed_links"]
    }
    for key, value in source_config.items():
        if key not in merged:
            merged[key] = value

    known = {
        str(item.get("url", "")).strip().lower()
        for key in ["rss_feeds", "configured_urls", "manual_seed_links"]
        for item in merged.get(key, [])
    }
    for record in approved_records:
        url = str(record.get("url", "")).strip()
        if not url or url.lower() in known:
            continue
        known.add(url.lower())
        metadata = record.get("metadata", {}) or {}
        score = metadata.get("score", {}) if isinstance(metadata, dict) else {}
        tags = score.get("tags", []) if isinstance(score, dict) else []
        source_type = record.get("source_type", "configured_url")
        if source_type == "rss":
            merged.setdefault("rss_feeds", []).append(
                {"name": record["name"], "enabled": True, "url": url, "tags": tags, "source_origin": "approved_source"}
            )
        else:
            merged.setdefault("configured_urls", []).append(
                {
                    "name": record["name"],
                    "enabled": True,
                    "url": url,
                    "extract_links": True,
                    "only_same_domain": True,
                    "tags": tags,
                    "source_origin": "approved_source",
                }
            )
    return merged


def select_sources_for_run(source_config: dict[str, Any], max_sources: int) -> dict[str, Any]:
    if max_sources <= 0:
        return source_config

    source_keys = ["rss_feeds", "configured_urls", "manual_seed_links"]
    seed_entries: list[tuple[str, dict[str, Any]]] = []
    approved_entries: list[tuple[str, dict[str, Any]]] = []
    for key in source_keys:
        for source in source_config.get(key, []):
            if not source.get("enabled", True):
                continue
            entry = (key, dict(source))
            if source.get("source_origin") == "approved_source":
                approved_entries.append(entry)
            else:
                seed_entries.append(entry)

    approved_target = 0
    if approved_entries and max_sources >= 4:
        approved_target = min(len(approved_entries), max(1, max_sources // 2))
    seed_target = max_sources - approved_target
    selected = seed_entries[:seed_target] + approved_entries[:approved_target]

    if len(selected) < max_sources:
        used = {(key, item.get("url", "")) for key, item in selected}
        for entry in seed_entries[seed_target:] + approved_entries[approved_target:]:
            marker = (entry[0], entry[1].get("url", ""))
            if marker in used:
                continue
            selected.append(entry)
            used.add(marker)
            if len(selected) >= max_sources:
                break

    limited = {
        key: value
        for key, value in source_config.items()
        if key not in source_keys
    }
    for key in source_keys:
        limited[key] = []
    for key, source in selected:
        limited.setdefault(key, []).append(source)
    return limited


def print_run_summary(
    store: SQLiteStore,
    candidates_fetched: int,
    candidates_considered: int,
    added_to_queue: int,
    rejected: int,
    source_errors: list[str],
    fetch_only: bool,
    scored: int = 0,
    source_stats: dict[str, Any] | None = None,
    continuations: int = 0,
    cost_guard: dict[str, Any] | None = None,
    sources_searched: int = 0,
) -> None:
    counts = store.counts()
    source_stats = source_stats or {}
    cost_guard = cost_guard or {}
    print("\nGain Entity Operator Summary")
    print("============================")
    print(f"New source candidates discovered: {source_stats.get('new_source_candidates_discovered', 0)}")
    print(f"Sources auto-approved: {source_stats.get('sources_auto_approved', 0)}")
    print(f"Sources needing approval: {source_stats.get('sources_needing_approval', 0)}")
    print(f"Sources rejected: {source_stats.get('sources_rejected', 0)}")
    print(f"Sources searched: {sources_searched}")
    print(f"Opportunities fetched: {candidates_fetched}")
    print(f"Opportunities considered: {candidates_considered}")
    print(f"AI scored: {scored}")
    print(f"Opportunities queued: {added_to_queue}")
    print(f"Rejected/deferred opportunities this run: {rejected}")
    print(f"Approved items continued by AI: {continuations}")
    print(f"Stored opportunities: {counts['opportunities']}")
    print(f"Claim queue items: {counts['claim_queue']}")
    print(f"Source candidates stored: {counts.get('source_candidates', 0)}")
    print(f"Approved sources stored: {counts.get('approved_sources', 0)}")
    print(f"Rejected sources stored: {counts.get('rejected_sources', 0)}")
    print(f"Rejected/deferred total: {counts['reject_log']}")
    print(f"Dead ends total: {counts['dead_end_log']}")
    print(f"Received/paid total: {counts['received_log']}")
    print(
        "Usage: "
        f"OpenAI calls {cost_guard.get('openai_calls_used', 0)}/{cost_guard.get('max_openai_calls_per_run', 'unlimited')}, "
        f"candidates {candidates_considered}/{cost_guard.get('max_candidates_per_run', 'unlimited')}, "
        f"sources {sources_searched}/{cost_guard.get('max_sources_per_run', 'unlimited')}"
    )
    if cost_guard.get("stopped_by_cost_guard"):
        print("Cost guard stopped additional AI work this run.")
    if cost_guard.get("candidate_cap_applied"):
        print("Candidate cap limited stored/scored opportunities this run.")

    if fetch_only:
        print("\nFetch-only mode: OpenAI scoring and execution prep were skipped.")

    all_source_errors = list(source_errors) + list(source_stats.get("source_errors", []))
    if all_source_errors:
        print("\nSource warnings")
        for error in all_source_errors[:10]:
            print(f"- {error}")
        if len(all_source_errors) > 10:
            print(f"- ...and {len(all_source_errors) - 10} more")

    _print_rows("Top 5 Fastest Gains", store.top_fastest(5))
    _print_rows("Top 5 Highest-Value Gains", store.top_highest_value(5))
    _print_rows("Needs Approval", store.by_statuses(["Needs Approval"], 10))
    _print_rows("Approved / AI Work Continuing", store.by_statuses(["Approved"], 10))
    _print_rows("Connect Needed", store.by_statuses(["Connect Needed"], 10))
    _print_rows("Ready to Accept", store.by_statuses(["Ready to Accept"], 10))
    _print_rows("Received/Paid Items", store.by_statuses(["Received/Paid"], 10))
    _print_rows("Dead Ends", store.by_statuses(["Dead End"], 10))


def _print_rows(title: str, rows: list[Any]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    if not rows:
        print("None yet.")
        return
    for row in rows:
        value = row["expected_value_usd"] if row["expected_value_usd"] is not None else 0
        probability = row["probability_score_1_to_10"] or row["probability_score"] or 0
        days = row["time_to_gain_days"] if row["time_to_gain_days"] is not None else "?"
        fastest = row["fastest_gain_score"] if row["fastest_gain_score"] is not None else 0
        value_score = row["highest_value_score"] if row["highest_value_score"] is not None else 0
        print(
            f"[{row['id']}] {row['title']} | ${value:,.2f} | p={probability}/10 | "
            f"{days} days | fast={fastest:.1f} | value={value_score:.1f} | {row['status']} | {row['url']}"
        )


def _recommended_status(prep: dict[str, str], fallback: str) -> str:
    allowed = {"Needs Approval", "Connect Needed"}
    status = str(prep.get("recommended_status") or "").strip()
    return status if status in allowed else fallback


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_cost_guard(rules: dict[str, Any]) -> dict[str, Any]:
    return {
        "max_openai_calls_per_run": int(rules.get("max_openai_calls_per_run", 120) or 0),
        "max_candidates_per_run": int(rules.get("max_candidates_per_run", rules.get("max_opportunities_per_run", 50)) or 0),
        "max_sources_per_run": int(rules.get("max_sources_per_run", rules.get("approved_source_fetch_limit", 8)) or 0),
        "openai_calls_used": 0,
        "openai_call_breakdown": {},
        "stopped_by_cost_guard": False,
        "candidate_cap_applied": False,
    }


def can_use_openai(cost_guard: dict[str, Any], calls: int = 1) -> bool:
    limit = int(cost_guard.get("max_openai_calls_per_run", 0) or 0)
    if limit <= 0:
        return True
    return int(cost_guard.get("openai_calls_used", 0)) + calls <= limit


def record_openai_call(cost_guard: dict[str, Any], category: str) -> None:
    cost_guard["openai_calls_used"] = int(cost_guard.get("openai_calls_used", 0)) + 1
    breakdown = cost_guard.setdefault("openai_call_breakdown", {})
    breakdown[category] = int(breakdown.get(category, 0)) + 1


def write_autonomy_status(
    settings: Any,
    rules: dict[str, Any],
    store: SQLiteStore,
    source_stats: dict[str, Any],
    sources_searched: int,
    opportunities_found: int,
    ai_work_completed: int,
    cost_guard: dict[str, Any],
) -> None:
    last_run = datetime.now(timezone.utc)
    frequency = str(rules.get("schedule_frequency", "6h"))
    status = {
        "last_run": last_run.isoformat(),
        "next_run": (last_run + schedule_delta(frequency)).isoformat(),
        "schedule_frequency": frequency,
        "autonomy_enabled": bool(rules.get("autonomy_enabled", True)),
        "sources_searched": sources_searched,
        "new_candidates": int(source_stats.get("new_source_candidates_discovered", 0) or 0),
        "opportunities_found": opportunities_found,
        "ai_work_completed": ai_work_completed,
        "approvals_needed": store.claim_status_count(["Needs Approval", "Connect Needed"]),
        "ready_to_accept": store.claim_status_count(["Ready to Accept"]),
        "received_paid": store.claim_status_count(["Received/Paid"]),
        "cost_guard": cost_guard,
    }
    output_path = settings.data_dir / "autonomy_status.json"
    output_path.write_text(json.dumps(status, ensure_ascii=True, indent=2), encoding="utf-8")


def schedule_delta(frequency: str) -> timedelta:
    if frequency == "daily":
        return timedelta(days=1)
    if frequency.endswith("h"):
        try:
            return timedelta(hours=int(frequency[:-1]))
        except ValueError:
            return timedelta(hours=6)
    return timedelta(hours=6)


if __name__ == "__main__":
    raise SystemExit(main())
