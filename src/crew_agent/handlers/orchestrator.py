from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from crew_agent.core.answering import build_answer_summaries
from crew_agent.core.models import ExecutionPlan, Host, StepExecutionResult
from crew_agent.core.operator_mode import (
    should_show_step_command,
    should_show_step_evidence,
    should_use_compact_view,
)
from crew_agent.core.paths import ensure_app_dirs
from crew_agent.core.ui import TerminalUI
from crew_agent.executors.runtime import execute_plan_step
from crew_agent.handlers.backup import create_backup_snapshot
from crew_agent.handlers.planner import create_execution_plan
from crew_agent.handlers.task_router import resolve_execution_plan
from crew_agent.policy.config import load_config
from crew_agent.policy.gates import approval_reasons_for_plan
from crew_agent.providers.inventory import filter_hosts, host_map, load_inventory


def save_run_log(
    request: str,
    plan: ExecutionPlan,
    results: list[StepExecutionResult],
    permission_mode: str,
    approval_policy: str,
    approval_required: bool,
    approval_granted: bool,
    approval_reasons: list[str],
    backup_path: str | None = None,
) -> Path:
    paths = ensure_app_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = paths.runs_dir / f"{stamp}-{uuid4().hex[:8]}.json"
    payload = {
        "request": request,
        "summary": plan.summary,
        "risk": plan.risk,
        "domain": plan.domain,
        "operation_class": plan.operation_class,
        "permission_mode": permission_mode,
        "approval_policy": approval_policy,
        "approval_required": approval_required,
        "approval_granted": approval_granted,
        "approval_reasons": approval_reasons,
        "backup_path": backup_path,
        "requires_unsafe": plan.requires_unsafe,
        "target_hosts": plan.target_hosts,
        "steps": [
            {
                "id": step.id,
                "title": step.title,
                "host": step.host,
                "kind": step.kind,
                "command": step.command,
                "verify_command": step.verify_command,
                "expected_signal": step.expected_signal,
                "validation_type": step.validation_type,
                "accept_nonzero_returncode": step.accept_nonzero_returncode,
                "continue_on_failure": step.continue_on_failure,
                "rationale": step.rationale,
            }
            for step in plan.steps
        ],
        "results": [
            {
                "step_id": result.step_id,
                "host": result.host,
                "title": result.title,
                "command": result.command,
                "success": result.success,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration_seconds": result.duration_seconds,
                "validation_error": result.validation_error,
                "verify": (
                    {
                        "returncode": result.verify.returncode,
                        "stdout": result.verify.stdout,
                        "stderr": result.verify.stderr,
                    }
                    if result.verify is not None
                    else None
                ),
            }
            for result in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def plan_request(
    request: str,
    ui: TerminalUI,
    host_names: list[str] | None = None,
    tags: list[str] | None = None,
) -> tuple[ExecutionPlan, list[Host]]:
    config = load_config()
    inventory = load_inventory()
    selected_hosts = filter_hosts(inventory, host_names=host_names, tags=tags)
    if not selected_hosts:
        raise ValueError("No matching enabled hosts were found in the inventory.")

    ui.phase("thinking", f"loaded {len(inventory)} hosts from inventory")
    ui.phase("thinking", f"selected {len(selected_hosts)} host(s) for planning")
    plan, source = resolve_execution_plan(request=request, hosts=selected_hosts, config=config)
    specialist = str(plan.raw.get("specialist") or "").strip()
    if specialist:
        ui.phase("thinking", f"selected specialist agent: {specialist}")
    if source == "workspace":
        ui.phase("thinking", "matched built-in workspace handler")
    elif source == "code":
        ui.phase("thinking", "matched built-in coding handler")
    elif source == "deterministic":
        ui.phase("thinking", "matched built-in deterministic handler")
    else:
        ui.phase("thinking", f"asking model {config.model} for an execution plan")
    return plan, selected_hosts


def run_request(
    request: str,
    ui: TerminalUI,
    host_names: list[str] | None = None,
    tags: list[str] | None = None,
    permission_mode: str | None = None,
    approval_policy: str | None = None,
    approved: bool = False,
    approval_callback: Callable[[list[str]], bool] | None = None,
    dry_run: bool = False,
) -> int:
    config = load_config()
    plan, selected_hosts = plan_request(
        request=request,
        ui=ui,
        host_names=host_names,
        tags=tags,
    )
    compact_view = should_use_compact_view(plan, config.operator_mode)
    ui.show_plan(plan, selected_hosts, compact=compact_view)
    effective_permission = permission_mode or config.permission_mode
    effective_approval_policy = approval_policy or config.approval_policy
    approval_reasons = approval_reasons_for_plan(
        plan=plan,
        permission_mode=effective_permission,
        approval_policy=effective_approval_policy,
    )
    approval_required = bool(approval_reasons)
    approval_granted = approved

    if plan.missing_information and not plan.steps:
        return 2
    if not plan.steps:
        ui.phase("warn", "planner returned no executable steps")
        return 2
    if plan.requires_unsafe and effective_permission != "full":
        ui.phase(
            "warn",
            "planner marked this request as unsafe. Switch permissions to full to execute it.",
        )
        return 3
    if dry_run:
        ui.phase("done", "dry-run only; no commands executed")
        return 0
    if approval_required and not approval_granted:
        if approval_callback is not None:
            approval_granted = approval_callback(approval_reasons)
        if not approval_granted:
            ui.phase(
                "warn",
                "execution blocked by approval gate. Re-run with --approve or approve interactively.",
            )
            return 5

    selected_map = host_map(selected_hosts)
    results: list[StepExecutionResult] = []
    backup_dir: Path | None = None
    should_backup = (
        effective_permission == "full"
        and config.backup_on_full
        and plan.domain == "infra"
        and (plan.requires_unsafe or plan.risk == "high")
    )
    if should_backup:
        ui.phase("thinking", "full permission enabled; creating pre-execution backup snapshot")
        try:
            backup_dir = create_backup_snapshot(
                request=request,
                plan=plan,
                hosts=selected_hosts,
                config=config,
            )
            ui.phase("done", f"backup snapshot saved to {backup_dir}")
        except Exception as exc:
            ui.phase("warn", f"backup snapshot failed: {exc}")
            return 4
    elif effective_permission == "full" and plan.domain == "infra" and (plan.requires_unsafe or plan.risk == "high"):
        ui.phase("warn", "full permission enabled without automatic backups")

    i = 0
    replan_count = 0
    while i < len(plan.steps):
        step = plan.steps[i]
        host = selected_map[step.host]
        ui.show_step_start(
            i + 1,
            len(plan.steps),
            step.host,
            step.title,
            step.command,
            show_command=should_show_step_command(plan, compact_view),
        )
        result = execute_plan_step(
            step,
            host,
            config=config,
            permission_mode=effective_permission,
        )
        ui.show_step_result(
            result,
            show_evidence=should_show_step_evidence(plan, result, compact_view),
        )
        results.append(result)
        
        if result.success:
            if plan.raw.get("stop_after_first_success"):
                ui.phase("thinking", f"{step.title} succeeded; stopping the specialist workflow")
                break
            i += 1
            continue
        
        # Step failed
        if step.continue_on_failure:
            ui.phase("thinking", f"{step.title} failed; continuing agent workflow to the next fallback step")
            i += 1
            continue
            
        if replan_count < 1:  # Allow 1 replan attempt
            ui.phase("thinking", f"step '{step.title}' failed. Attempting to re-plan with error context...")
            error_context = result.stderr or result.validation_error or "Unknown error"
            refined_request = (
                f"The previous plan failed at step '{step.title}' with error: {error_context}. "
                f"The original request was: {request}. Please provide a corrected plan."
            )
            try:
                new_plan = create_execution_plan(refined_request, selected_hosts, config)
                if new_plan.steps:
                    ui.phase("thinking", "received a new execution plan. Continuing with updated steps.")
                    plan.steps = plan.steps[:i] + new_plan.steps
                    replan_count += 1
                    # Don't increment i, the loop will pick up new_plan.steps[0] at the current i
                    continue
            except Exception as e:
                ui.phase("warn", f"re-planning failed: {e}")

        ui.phase("warn", f"stopping after failed step on {result.host}")
        break

    log_path = save_run_log(
        request=request,
        plan=plan,
        results=results,
        permission_mode=effective_permission,
        approval_policy=effective_approval_policy,
        approval_required=approval_required,
        approval_granted=approval_granted,
        approval_reasons=approval_reasons,
        backup_path=str(backup_dir) if backup_dir is not None else None,
    )
    ui.show_answer_summaries(build_answer_summaries(plan, results))
    ui.show_run_summary(results, str(log_path))
    blocking_failures = [
        (step, result)
        for step, result in zip(plan.steps[: len(results)], results)
        if not result.success and not step.continue_on_failure
    ]
    return 0 if results and not blocking_failures and any(result.success for result in results) else 1
