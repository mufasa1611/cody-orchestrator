from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from crew_agent.core.answering import build_answer_summaries
from crew_agent.core.models import (
    AppConfig,
    CommandResult,
    ExecutionPlan,
    Host,
    PlanStep,
    StepExecutionResult,
)
from crew_agent.executors.runtime import execute_plan_step
from crew_agent.handlers.orchestrator import run_request
from crew_agent.handlers.code import build_code_plan
from crew_agent.handlers.planner import create_execution_plan
from crew_agent.handlers.task_router import resolve_execution_plan
from crew_agent.policy.gates import approval_reasons_for_plan
from crew_agent.policy.validation import validate_step_stdout
from crew_agent.core.ui import TerminalUI


class CodePlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = Host(name="local-win", platform="windows", transport="local", enabled=True)
        self.config = AppConfig()

    def test_read_file_request_uses_code_handler(self) -> None:
        plan = build_code_plan("read src/crew_agent/cli.py", [self.host])
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.domain, "code")
        self.assertEqual(plan.raw.get("handler"), "repo_file_read")
        self.assertEqual(plan.raw.get("specialist"), "file-reader")
        self.assertEqual(plan.steps[0].validation_type, "repo_file_text")

    def test_read_file_request_in_documents_folder_resolves_known_location(self) -> None:
        plan = build_code_plan(
            "read file imp-info.txt in documents folder and show me the server info in the file",
            [self.host],
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("Documents", plan.summary)
        self.assertIn("GetFolderPath('MyDocuments')", plan.steps[0].command)
        self.assertIn("Join-Path", plan.steps[0].command)

    def test_read_file_request_without_location_uses_fallback_workflow(self) -> None:
        plan = build_code_plan("read file imp-info.txt", [self.host])
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertGreaterEqual(len(plan.steps), 4)
        self.assertTrue(plan.steps[0].continue_on_failure)
        self.assertFalse(plan.steps[-1].continue_on_failure)
        self.assertIn("checking", plan.summary)

    def test_search_request_uses_code_handler(self) -> None:
        plan = build_code_plan('search for "approval_policy" in the repo', [self.host])
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.raw.get("handler"), "repo_text_search")
        self.assertEqual(plan.raw.get("specialist"), "repo-searcher")
        self.assertEqual(plan.steps[0].validation_type, "repo_search_text")

    def test_task_router_chooses_code_specialist(self) -> None:
        plan, source = resolve_execution_plan(
            "read file imp-info.txt in documents folder and show me the server info in the file",
            [self.host],
            self.config,
        )
        self.assertEqual(source, "code")
        self.assertEqual(plan.raw.get("specialist"), "file-reader")

    def test_run_tests_request_allows_nonzero_returncode(self) -> None:
        plan = build_code_plan("run unit tests", [self.host])
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.raw.get("handler"), "test_run")
        self.assertTrue(plan.steps[0].accept_nonzero_returncode)

    def test_low_risk_code_inspection_does_not_require_approval(self) -> None:
        plan = build_code_plan("show git status", [self.host])
        assert plan is not None
        reasons = approval_reasons_for_plan(plan, permission_mode="safe", approval_policy="risky")
        self.assertEqual(reasons, [])

    def test_planner_assigns_default_host_when_model_omits_it(self) -> None:
        with patch("crew_agent.handlers.planner.OllamaClient.generate_json") as generate_json_mock:
            generate_json_mock.return_value = {
                "summary": "Inspect PowerShell version",
                "risk": "low",
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Get version",
                        "kind": "inspect",
                        "command": "$PSVersionTable.PSVersion | ConvertTo-Json -Compress",
                    }
                ],
            }
            plan = create_execution_plan("show powershell version", [self.host], self.config)
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].host, "local-win")
        self.assertEqual(plan.target_hosts, ["local-win"])


class CodeExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = Host(name="local-win", platform="windows", transport="local", enabled=True)
        self.config = AppConfig()

    def test_test_execution_can_succeed_with_failing_tests(self) -> None:
        step = PlanStep(
            id="test-1",
            title="Run tests",
            host=self.host.name,
            kind="inspect",
            command="python -m unittest",
            validation_type="test_run_text",
            accept_nonzero_returncode=True,
        )
        with patch(
            "crew_agent.executors.runtime._execute_windows_local",
            return_value=CommandResult(
                returncode=1,
                stdout="Ran 2 tests in 0.010s\nFAILED (failures=1)",
                stderr="",
            ),
        ):
            result = execute_plan_step(step, self.host, self.config, permission_mode="safe")
        self.assertTrue(result.success)
        self.assertEqual(result.returncode, 1)

    def test_new_text_validation_types_accept_plain_output(self) -> None:
        step = PlanStep(
            id="search-1",
            title="Search",
            host=self.host.name,
            kind="inspect",
            command="rg approval_policy .",
            validation_type="repo_search_text",
        )
        self.assertIsNone(validate_step_stdout(step, "No matches found."))

    def test_orchestrator_continues_file_reader_fallback_steps(self) -> None:
        ui = TerminalUI()
        with patch(
            "crew_agent.handlers.orchestrator.plan_request"
        ) as plan_request_mock, patch(
            "crew_agent.handlers.orchestrator.execute_plan_step"
        ) as execute_step_mock, patch(
            "crew_agent.handlers.orchestrator.save_run_log",
            return_value=Path(".cody/runs/fake.json"),
        ):
            plan = build_code_plan("read file imp-info.txt", [self.host])
            assert plan is not None
            selected_hosts = [self.host]
            plan_request_mock.return_value = (plan, selected_hosts)
            execute_step_mock.side_effect = [
                StepExecutionResult(
                    step_id=plan.steps[0].id,
                    host=self.host.name,
                    title=plan.steps[0].title,
                    command=plan.steps[0].command,
                    success=False,
                    returncode=1,
                    stdout="",
                    stderr="not found",
                    verify=None,
                    duration_seconds=0.1,
                    validation_type=plan.steps[0].validation_type,
                ),
                StepExecutionResult(
                    step_id=plan.steps[1].id,
                    host=self.host.name,
                    title=plan.steps[1].title,
                    command=plan.steps[1].command,
                    success=True,
                    returncode=0,
                    stdout="FILE: C:\\Users\\Mufasa\\Documents\\imp-info.txt\nserver=alpha",
                    stderr="",
                    verify=None,
                    duration_seconds=0.1,
                    validation_type=plan.steps[1].validation_type,
                ),
            ]
            exit_code = run_request("read file imp-info.txt", ui)
            self.assertEqual(exit_code, 0)
            self.assertEqual(execute_step_mock.call_count, 2)


class CodeAnsweringTests(unittest.TestCase):
    def test_test_summary_reports_failures(self) -> None:
        plan = ExecutionPlan(summary="Run tests", domain="code", operation_class="inspect")
        summaries = build_answer_summaries(
            plan,
            [
                StepExecutionResult(
                    step_id="1",
                    host="local-win",
                    title="Run tests",
                    command="python -m unittest",
                    success=True,
                    returncode=1,
                    stdout="Ran 2 tests in 0.010s\nFAILED (failures=1)",
                    stderr="",
                    verify=None,
                    duration_seconds=0.2,
                    validation_type="test_run_text",
                )
            ],
        )
        self.assertEqual(summaries[0].title, "Test Results")
        self.assertTrue(any("FAILED" in line for line in summaries[0].lines))


if __name__ == "__main__":
    unittest.main()
