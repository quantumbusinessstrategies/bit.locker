from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execution.account_worker import AccountWorker
from execution.autofill_execution import build_autofill_execution_packet
from execution.browser_worker import BrowserWorker
from execution.form_worker import FormWorker
from execution.routing_worker import RoutingWorker
from execution.submission_worker import SubmissionWorker
from user_context.user_context_store import UserContextStore


EXECUTION_STATUSES = {
    "Execution Queue",
    "AI Working",
    "Paused Awaiting Input",
    "Ready To Accept",
    "Completed",
}


@dataclass(frozen=True)
class ActionEngineResult:
    can_continue_alone: bool
    execution_status: str
    claim_status: str
    estimated_completion_percent: float
    estimated_time: str
    human_input_needed: str
    next_action: str
    ai_work_completed: str
    action_engine_json: str


class ActionEngine:
    def __init__(self, user_context: dict[str, Any] | None = None) -> None:
        self.user_context = user_context if user_context is not None else _load_user_context()
        self.routing_worker = RoutingWorker(self.user_context)
        self.account_worker = AccountWorker(self.user_context)
        self.form_worker = FormWorker()
        self.browser_worker = BrowserWorker()
        self.submission_worker = SubmissionWorker()

    def evaluate(self, item: dict[str, Any]) -> ActionEngineResult:
        status = str(item.get("status") or "")
        current_execution = str(item.get("execution_status") or "")
        if status in {"Received/Paid", "Accepted"}:
            return self._completed(item, "Asset has already been accepted or received.")
        if status in {"Reject", "Rejected"}:
            return self._result(
                item=item,
                can_continue=False,
                execution_status="Rejected",
                claim_status="Rejected",
                completion=float(item.get("estimated_completion_percent") or 0),
                estimated_time="Rejected",
                human_input_needed="",
                next_action="No further AI work; item was rejected.",
                completed="Owner rejected this item.",
                details={"rejected": True},
            )
        if status == "Dead End":
            return self._paused(item, "Dead end; no further execution is available.", claim_status="Dead End")
        if status == "Connect Needed":
            return self._paused(
                item,
                "Connect or approve login for the required platform.",
                claim_status="Connect Needed",
            )
        if status == "Submitted":
            return self._result(
                item=item,
                can_continue=True,
                execution_status="Processing",
                claim_status="Submitted",
                completion=max(float(item.get("estimated_completion_percent") or 0), 92.0),
                estimated_time=str(item.get("estimated_time") or "Processing / follow-up pending"),
                human_input_needed="",
                next_action=str(item.get("next_action") or "Track submitted item until received, paid, rejected, or follow-up is due."),
                completed=str(item.get("ai_work_completed") or "Owner approved safe final step; item is now in submitted/processing tracking."),
                details={"submitted_tracking": True},
            )
        if current_execution == "Ready To Accept":
            return self._result(
                item=item,
                can_continue=True,
                execution_status="Ready To Accept",
                claim_status=status or "Needs Approval",
                completion=float(item.get("estimated_completion_percent") or 88),
                estimated_time=str(item.get("estimated_time") or "Ready now"),
                human_input_needed=str(item.get("human_input_needed") or ""),
                next_action=str(item.get("next_action") or "Review final approval packet."),
                completed=str(item.get("ai_work_completed") or "Final approval packet is prepared."),
                details={"prepared_packet": True},
            )
        if status not in {"Approved", "AI Working", "Submitted", "Ready to Accept"}:
            return self._queued(item, "Waiting for owner approval before autonomous execution.")

        routing = self.routing_worker.inspect(item)
        account = self.account_worker.inspect(item)
        blocked = bool(routing.get("blocked") or account.get("blocked"))
        autofill = build_autofill_execution_packet(item, self.user_context)
        form = self.form_worker.prepare(item)
        browser = self.browser_worker.prepare(item)
        prepared = bool(form.get("worked") or browser.get("worked") or autofill.can_prepare)
        submission = self.submission_worker.decide(item, blocked=blocked, prepared=prepared)

        if blocked:
            human_input = str(
                account.get("human_input_needed")
                or routing.get("human_input_needed")
                or item.get("owner_input_required")
                or "Owner input required inside the official platform."
            )
            return self._result(
                item=item,
                can_continue=False,
                execution_status="Paused Awaiting Input",
                claim_status=self._pause_claim_status(item, human_input),
                completion=max(float(routing.get("completion", 0)), float(account.get("completion", 0))),
                estimated_time="Paused until owner input is provided",
                human_input_needed=human_input,
                next_action=str(account.get("next_action") or routing.get("next_action") or human_input),
                completed=self._completed_text(routing, account, form, browser, {"summary": autofill.prepared_summary}),
                details={
                    "routing": routing,
                    "account": account,
                    "autofill": autofill.to_dict(),
                    "form": form,
                    "browser": browser,
                    "submission": submission,
                },
            )

        execution_status = str(submission.get("execution_status") or "AI Working")
        claim_status = str(submission.get("claim_status") or item.get("status") or "Approved")
        if autofill.can_prepare and autofill.final_approval_required:
            execution_status = "Ready To Accept"
            claim_status = "Ready to Accept"
            submission["next_action"] = autofill.next_safe_action
            submission["completion"] = max(float(submission.get("completion", 0)), 88.0)
        if execution_status not in EXECUTION_STATUSES:
            execution_status = "AI Working"
        completion = max(
            float(submission.get("completion", 0)),
            float(form.get("completion", 0)),
            float(browser.get("completion", 0)),
            float(routing.get("completion", 0)),
            88.0 if autofill.can_prepare else 0.0,
        )
        can_continue = execution_status in {"AI Working", "Ready To Accept"}
        return self._result(
            item=item,
            can_continue=can_continue,
            execution_status=execution_status,
            claim_status=claim_status,
            completion=completion,
            estimated_time=self._estimated_time(execution_status, completion),
            human_input_needed="",
            next_action=str(submission.get("next_action") or autofill.next_safe_action or form.get("next_action") or browser.get("next_action") or ""),
            completed=self._completed_text(routing, account, {"summary": autofill.prepared_summary}, form, browser),
            details={
                "routing": routing,
                "account": account,
                "autofill": autofill.to_dict(),
                "form": form,
                "browser": browser,
                "submission": submission,
            },
        )

    def _completed(self, item: dict[str, Any], message: str) -> ActionEngineResult:
        return self._result(
            item=item,
            can_continue=False,
            execution_status="Completed",
            claim_status=str(item.get("status") or "Received/Paid"),
            completion=100,
            estimated_time="Complete",
            human_input_needed="",
            next_action="No further action required.",
            completed=message,
            details={"completed": message},
        )

    def _paused(self, item: dict[str, Any], message: str, claim_status: str | None = None) -> ActionEngineResult:
        return self._result(
            item=item,
            can_continue=False,
            execution_status="Paused Awaiting Input",
            claim_status=claim_status or str(item.get("status") or "Approved"),
            completion=35,
            estimated_time="Paused until owner input is provided",
            human_input_needed=message,
            next_action=message,
            completed=message,
            details={"paused": message},
        )

    def _queued(self, item: dict[str, Any], message: str) -> ActionEngineResult:
        return self._result(
            item=item,
            can_continue=False,
            execution_status="Execution Queue",
            claim_status=str(item.get("status") or "Needs Approval"),
            completion=float(item.get("estimated_completion_percent") or 25),
            estimated_time=str(item.get("estimated_time") or "Waiting for approval"),
            human_input_needed=str(item.get("user_approval_needed") or item.get("owner_input_required") or "Owner approval required."),
            next_action=str(item.get("exact_next_step") or message),
            completed=message,
            details={"queued": message},
        )

    def _result(
        self,
        *,
        item: dict[str, Any],
        can_continue: bool,
        execution_status: str,
        claim_status: str,
        completion: float,
        estimated_time: str,
        human_input_needed: str,
        next_action: str,
        completed: str,
        details: dict[str, Any],
    ) -> ActionEngineResult:
        payload = {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "can_continue_alone": can_continue,
            "execution_status": execution_status,
            "claim_status": claim_status,
            "details": details,
        }
        return ActionEngineResult(
            can_continue_alone=can_continue,
            execution_status=execution_status,
            claim_status=claim_status,
            estimated_completion_percent=round(max(0.0, min(100.0, completion)), 1),
            estimated_time=estimated_time,
            human_input_needed=human_input_needed,
            next_action=next_action,
            ai_work_completed=completed,
            action_engine_json=json.dumps(payload, ensure_ascii=True, sort_keys=True),
        )

    @staticmethod
    def _pause_claim_status(item: dict[str, Any], human_input: str) -> str:
        text = human_input.lower()
        if any(term in text for term in ["connect", "sign in", "login", "account", "credential"]):
            return "Connect Needed"
        return str(item.get("status") or "Approved")

    @staticmethod
    def _estimated_time(execution_status: str, completion: float) -> str:
        if execution_status == "Processing":
            return "Processing / follow-up pending"
        if execution_status == "Ready To Accept":
            return "Ready now"
        if completion >= 80:
            return "Under 5 minutes of AI-safe work remaining"
        if completion >= 60:
            return "5-15 minutes of AI-safe work remaining"
        return "15-30 minutes of AI-safe preparation remaining"

    @staticmethod
    def _completed_text(*worker_results: dict[str, Any]) -> str:
        summaries = [str(result.get("summary") or result.get("reason") or "").strip() for result in worker_results]
        return " ".join(summary for summary in summaries if summary)


def result_to_dict(result: ActionEngineResult) -> dict[str, Any]:
    return asdict(result)


def _load_user_context() -> dict[str, Any]:
    try:
        return UserContextStore.for_root(Path(__file__).resolve().parents[2]).load()
    except Exception:  # noqa: BLE001 - execution should still work without optional vault context
        return {}
