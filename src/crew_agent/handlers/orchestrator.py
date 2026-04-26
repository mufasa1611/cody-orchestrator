from __future__ import annotations

import concurrent.futures
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from crew_agent.core.answering import build_answer_summaries
from crew_agent.core.db import save_run_to_db
from crew_agent.core.memory import load_workspace_memory, save_step_to_history
from crew_agent.core.models import ExecutionPlan, Host, StepExecutionResult
from crew_agent.core.paths import ensure_app_dirs
from crew_agent.core.ui import TerminalUI
from crew_agent.executors.runtime import execute_plan_step
from crew_agent.handlers.backup import create_backup_snapshot
from crew_agent.handlers.planner import create_execution_plan
from crew_agent.handlers.task_router import resolve_execution_plan
from crew_agent.policy.config import load_config
from crew_agent.providers.inventory import filter_hosts, host_map, load_inventory


def plan_request(
    request: str,
    hosts: list[Host],
    config: AppConfig,
) -> tuple[ExecutionPlan, list[Host]]:
    plan, source = resolve_execution_plan(request, hosts, config)
    selected_hosts = [h for h in hosts if h.name in plan.target_hosts]
    return plan, selected_hosts


def save_run_log(
    request: str,
    plan: ExecutionPlan,
    results: list[StepExecutionResult],
    permission_mode: str,
    backup_path: str | None = None,
) -> Path:
    paths = ensure_app_dirs()
    log_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
    log_path = paths.runs_dir / f"{log_id}.json"
    
    data = {
        "request": request,
        "summary": plan.summary,
        "risk": plan.risk,
        "permission_mode": permission_mode,
        "backup_path": backup_path,
        "results": [
            {
                "step_id": r.step_id,
                "host": r.host,
                "title": r.title,
                "command": r.command,
                "success": r.success,
                "returncode": r.returncode,
                "stdout": r.stdout,
                "stderr": r.stderr,
                "duration_seconds": r.duration_seconds,
            }
            for r in results
        ]
    }
    log_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return log_path


def run_request(
    request: str,
    ui: TerminalUI,
    config: AppConfig | None = None,
    inventory: list[Host] | None = None,
    permissions: str | None = None,
    approve_all: bool = False,
    is_interactive: bool = True,
    dry_run: bool = False,
    host_names: list[str] | None = None,
    tags: list[str] | None = None,
    permission_mode: str | None = None,
    approved: bool = False,
    approval_callback: Any | None = None,
    thread: ConversationThread | None = None,
) -> int:
    if config is None:
        config = load_config()
    if inventory is None:
        inventory = load_inventory()
    
    # 0. Track conversation
    if thread:
        thread.add_message("user", request)

    # Final decisive approval check
    actual_approve_all = approve_all or approved

    # Filter inventory
    if host_names:
        inventory = [h for h in inventory if h.name in host_names]
    if tags:
        inventory = [h for h in inventory if all(t in h.tags for t in tags)]

    actual_permission_mode = permission_mode or permissions or config.permission_mode
    
    # 1. Plan
    plan, source = resolve_execution_plan(request=request, hosts=filter_hosts(inventory), config=config, thread=thread)
    selected_hosts = [h for h in inventory if h.name in plan.target_hosts]
    selected_map = host_map(selected_hosts)
    
    if plan.missing_information:
        for msg in plan.missing_information:
            ui.phase("warn", f"missing information: {msg}")
        return 2

    # 2. UI Display
    ui.show_plan(plan, selected_hosts)
    
    if dry_run:
        ui.phase("done", "dry run complete; skipping execution")
        return 0

    # 3. Approvals
    if not actual_approve_all and plan.requires_confirmation:
        if not is_interactive:
            ui.phase("warn", "approval required but shell is non-interactive; aborting")
            return 3
        if not ui.ask_approval("approval required before execution"):
            return 0

    # 4. Backups
    backup_dir: Path | None = None
    if actual_permission_mode == "full" and config.backup_on_full and plan.domain == "infra" and plan.risk == "high":
        ui.phase("thinking", "creating pre-execution backup snapshot")
        try:
            backup_dir = create_backup_snapshot(request, plan, selected_hosts, config)
        except Exception as exc:
            ui.phase("warn", f"backup snapshot failed: {exc}")

    # 5. Execute
    results: list[StepExecutionResult] = []
    replan_count = 0
    i = 0
    
    # PRO ORCHESTRATION: Handle conditional termination
    stop_on_success = plan.raw.get("stop_after_first_success", False)

    while i < len(plan.steps):
        step = plan.steps[i]
        host = selected_map[step.host]
        ui.show_step_start(i + 1, len(plan.steps), step.host, step.title, step.command)
        
        result = execute_plan_step(step, host, config, actual_permission_mode)
        ui.show_step_result(result)
        results.append(result)
        
        if result.success:
            save_step_to_history(request, f"Step '{step.title}' succeeded.")
            if stop_on_success:
                ui.phase("done", "Task achieved on first successful step; terminating early.")
                break
            i += 1
        else:
            # If step allowed failure, just move on
            if step.continue_on_failure:
                ui.phase("thinking", "Step failed but marked as optional; continuing...")
                i += 1
                continue
                
            if replan_count < 3:
                ui.phase("thinking", f"step failed; re-planning (attempt {replan_count+1}/3)")
                replan_count += 1
                try:
                    new_plan = create_execution_plan(f"The step '{step.title}' failed with error: {result.stderr}. Fix it.", selected_hosts, config)
                    if new_plan.steps:
                        plan.steps = plan.steps[:i] + new_plan.steps
                        continue
                except:
                    pass
            break

    # 6. Finalize
    exit_code = 0 if (results and results[-1].success) else 1
    
    # PRO MEMORY: Record the final success in the thread
    if exit_code == 0 and thread:
        thread.add_message("assistant", f"I successfully completed the request: {plan.summary}")

    log_path = save_run_log(request, plan, results, actual_permission_mode, str(backup_dir) if backup_dir else None)
    
    ui.show_answer_summaries(build_answer_summaries(plan, results, ui))
    ui.show_run_summary(results, str(log_path))
    
    try:
        save_run_to_db(log_path.stem, request, plan.summary, plan.domain, plan.risk, exit_code, results)
    except:
        pass

    return exit_code
