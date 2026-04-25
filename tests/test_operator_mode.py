from __future__ import annotations

import unittest

from crew_agent.core.models import ExecutionPlan, StepExecutionResult
from crew_agent.core.operator_mode import (
    should_show_step_command,
    should_show_step_evidence,
    should_use_compact_view,
)


class OperatorModeTests(unittest.TestCase):
    def test_builtin_low_risk_plan_uses_compact_view(self) -> None:
        plan = ExecutionPlan(
            summary="Inspect disk space",
            risk="low",
            domain="infra",
            operation_class="inspect",
            raw={"builtin": True},
        )
        self.assertTrue(should_use_compact_view(plan, operator_mode=True))

    def test_high_risk_plan_does_not_use_compact_view(self) -> None:
        plan = ExecutionPlan(
            summary="Restart service",
            risk="high",
            domain="infra",
            operation_class="change",
            raw={"builtin": True},
        )
        self.assertFalse(should_use_compact_view(plan, operator_mode=True))

    def test_compact_view_hides_builtin_command_and_success_evidence(self) -> None:
        plan = ExecutionPlan(
            summary="Inspect shutdown",
            risk="low",
            domain="infra",
            operation_class="inspect",
            raw={"builtin": True},
        )
        result = StepExecutionResult(
            step_id="1",
            host="local-win",
            title="Inspect",
            command="cmd",
            success=True,
            returncode=0,
            stdout="{}",
            stderr="",
            verify=None,
            duration_seconds=0.2,
        )
        self.assertFalse(should_show_step_command(plan, compact_view=True))
        self.assertFalse(should_show_step_evidence(plan, result, compact_view=True))

    def test_compact_view_keeps_failure_evidence(self) -> None:
        plan = ExecutionPlan(
            summary="Inspect shutdown",
            risk="low",
            domain="infra",
            operation_class="inspect",
            raw={"builtin": True},
        )
        result = StepExecutionResult(
            step_id="1",
            host="local-win",
            title="Inspect",
            command="cmd",
            success=False,
            returncode=1,
            stdout="failure",
            stderr="boom",
            verify=None,
            duration_seconds=0.2,
        )
        self.assertTrue(should_show_step_evidence(plan, result, compact_view=True))


if __name__ == "__main__":
    unittest.main()
