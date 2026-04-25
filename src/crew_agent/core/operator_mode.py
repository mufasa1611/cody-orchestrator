from __future__ import annotations

from crew_agent.core.models import ExecutionPlan, StepExecutionResult


def should_use_compact_view(plan: ExecutionPlan, operator_mode: bool) -> bool:
    if not operator_mode:
        return False
    if plan.risk != "low" or plan.requires_unsafe or plan.requires_confirmation:
        return False
    if plan.raw.get("builtin"):
        return True
    if plan.domain == "workspace" and plan.operation_class == "write_text":
        return True
    if plan.domain == "code" and plan.operation_class == "inspect":
        return True
    if plan.operation_class == "inspect" and len(plan.steps) <= 2:
        return True
    return False


def should_show_step_command(plan: ExecutionPlan, compact_view: bool) -> bool:
    if not compact_view:
        return True
    return not bool(plan.raw.get("builtin"))


def should_show_step_evidence(
    plan: ExecutionPlan,
    result: StepExecutionResult,
    compact_view: bool,
) -> bool:
    if not compact_view:
        return True
    if not result.success:
        return True
    return False
