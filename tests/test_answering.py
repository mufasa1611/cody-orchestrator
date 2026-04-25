from __future__ import annotations

import unittest

from crew_agent.core.answering import build_answer_summaries
from crew_agent.core.models import ExecutionPlan, StepExecutionResult


class AnsweringTests(unittest.TestCase):
    def test_shutdown_answer_summary_is_direct(self) -> None:
        plan = ExecutionPlan(summary="Inspect shutdown reasons", operation_class="inspect")
        result = StepExecutionResult(
            step_id="1",
            host="local-win",
            title="Get recent shutdown reasons",
            command="cmd",
            success=True,
            returncode=0,
            stdout='[{"TimeCreated":"\\/Date(1777067908985)\\/","ProviderName":"User32","Id":1074,"User":"DESKTOP-GEKVHOM\\\\Mufasa","Reason":"power off","ShutdownType":"0x0","Message":"The process C:\\\\WINDOWS\\\\SystemApps\\\\Microsoft.Windows.StartMenuExperienceHost_cw5n1h2txyewy\\\\StartMenuExperienceHost.exe (DESKTOP-GEKVHOM) has initiated the power off of computer DESKTOP-GEKVHOM on behalf of user DESKTOP-GEKVHOM\\\\Mufasa."}]',
            stderr="",
            verify=None,
            duration_seconds=0.4,
            validation_type="event_log_json",
        )
        summaries = build_answer_summaries(plan, [result])
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].title, "Answer")
        self.assertTrue(any("Latest event:" in line for line in summaries[0].lines))
        self.assertTrue(any("Initiated by:" in line for line in summaries[0].lines))

    def test_workspace_file_answer_summary_contains_path(self) -> None:
        plan = ExecutionPlan(summary="Create file", operation_class="write_text")
        result = StepExecutionResult(
            step_id="1",
            host="local-win",
            title="Create test.txt",
            command="cmd",
            success=True,
            returncode=0,
            stdout='{"Path":"C:\\\\Users\\\\Mufasa\\\\Documents\\\\test.txt","Name":"test.txt","Parent":"C:\\\\Users\\\\Mufasa\\\\Documents","Exists":true}',
            stderr="",
            verify=None,
            duration_seconds=0.2,
            validation_type="workspace_file_info_json",
            artifact_path=r"C:\Users\Mufasa\Documents\test.txt",
        )
        summaries = build_answer_summaries(plan, [result])
        self.assertEqual(len(summaries), 1)
        self.assertTrue(any("Path:" in line for line in summaries[0].lines))

    def test_workspace_file_insert_summary_contains_inserted_text(self) -> None:
        plan = ExecutionPlan(summary="Insert text", operation_class="write_text")
        result = StepExecutionResult(
            step_id="1",
            host="local-win",
            title="Insert text into test-brother.txt",
            command="cmd",
            success=True,
            returncode=0,
            stdout='{"Path":"C:\\\\Users\\\\Mufasa\\\\Documents\\\\test-brother.txt","Name":"test-brother.txt","Parent":"C:\\\\Users\\\\Mufasa\\\\Documents","Exists":true,"InsertedText":"welcome my brother","ContainsExpected":true}',
            stderr="",
            verify=None,
            duration_seconds=0.2,
            validation_type="workspace_file_contains_json",
            artifact_path=r"C:\Users\Mufasa\Documents\test-brother.txt",
        )
        summaries = build_answer_summaries(plan, [result])
        self.assertEqual(len(summaries), 1)
        self.assertTrue(any("Inserted text:" in line for line in summaries[0].lines))

    def test_tool_presence_summary_reports_installed_status(self) -> None:
        plan = ExecutionPlan(summary="Check tool", operation_class="inspect")
        result = StepExecutionResult(
            step_id="1",
            host="local-win",
            title="Check GitHub CLI installation",
            command="cmd",
            success=True,
            returncode=0,
            stdout='{"Installed":true,"Name":"GitHub CLI","Command":"gh","Source":"C:\\\\Program Files\\\\GitHub CLI\\\\gh.exe","Version":"gh version 2.91.0"}',
            stderr="",
            verify=None,
            duration_seconds=0.2,
            validation_type="tool_presence_json",
        )
        summaries = build_answer_summaries(plan, [result])
        self.assertEqual(len(summaries), 1)
        self.assertTrue(any("Installed: yes" in line for line in summaries[0].lines))
        self.assertTrue(any("Source:" in line for line in summaries[0].lines))


if __name__ == "__main__":
    unittest.main()
