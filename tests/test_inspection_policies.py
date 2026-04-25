from __future__ import annotations

import unittest

from crew_agent.core.models import ExecutionPlan, Host
from crew_agent.handlers.deterministic import build_builtin_plan
from crew_agent.policy.gates import approval_reasons_for_plan, guard_command
from crew_agent.policy.validation import validate_step_stdout


class InspectionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = Host(name="local-win", platform="windows", transport="local", enabled=True)

    def test_shutdown_reason_request_uses_deterministic_json_plan(self) -> None:
        plan = build_builtin_plan(
            "check what was the reason to show down the pc last time",
            [self.host],
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.operation_class, "inspect")
        self.assertFalse(plan.requires_confirmation)
        self.assertEqual(plan.steps[0].validation_type, "event_log_json")
        self.assertIn("ConvertTo-Json", plan.steps[0].command)

    def test_shutdown_reason_request_accepts_shout_down_typo(self) -> None:
        plan = build_builtin_plan(
            "what was the reason of the last shout down",
            [self.host],
        )
        self.assertIsNotNone(plan)

    def test_low_risk_inspect_plan_does_not_require_approval(self) -> None:
        plan = ExecutionPlan(
            summary="Inspect something harmless",
            risk="low",
            domain="infra",
            operation_class="inspect",
            requires_confirmation=True,
            requires_unsafe=False,
        )
        reasons = approval_reasons_for_plan(plan, permission_mode="safe", approval_policy="risky")
        self.assertEqual(reasons, [])

    def test_unknown_validation_type_does_not_fail_plain_text(self) -> None:
        plan = build_builtin_plan(
            "check what was the reason to show down the pc last time",
            [self.host],
        )
        assert plan is not None
        step = plan.steps[0]
        error = validate_step_stdout(
            step,
            '[{\"TimeCreated\":\"2026-04-24T23:58:28\",\"ProviderName\":\"User32\",\"Id\":1074,\"Message\":\"test\"}]',
        )
        self.assertIsNone(error)

    def test_guard_does_not_block_shutdowntype_field_name(self) -> None:
        command = (
            "Get-WinEvent -FilterHashtable @{LogName='System'; ID=1074} | "
            "Select-Object @{Name='ShutdownType';Expression={$_.Properties[3].Value}} | "
            "ConvertTo-Json -Compress"
        )
        guard_command(self.host, command, permission_mode="safe")

    def test_github_cli_presence_request_uses_deterministic_plan(self) -> None:
        plan = build_builtin_plan(
            "is github cli installed in my windows system",
            [self.host],
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.operation_class, "inspect")
        self.assertEqual(plan.steps[0].validation_type, "tool_presence_json")
        self.assertIn("Get-Command gh", plan.steps[0].command)

    def test_tool_presence_validation_accepts_installed_false_json(self) -> None:
        plan = build_builtin_plan(
            "is github cli installed in my windows system",
            [self.host],
        )
        assert plan is not None
        step = plan.steps[0]
        error = validate_step_stdout(
            step,
            '{"Installed":false,"Name":"GitHub CLI","Command":"gh","Source":"","Version":"","Hint":"Not found."}',
        )
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
