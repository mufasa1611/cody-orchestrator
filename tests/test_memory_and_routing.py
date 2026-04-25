from __future__ import annotations

import os
import unittest
from uuid import uuid4
import shutil
from pathlib import Path
from unittest.mock import patch

from crew_agent.cli import _handle_workspace_follow_up
from crew_agent.conversation.router import RouteDecision, validate_route_decision
from crew_agent.core.memory import (
    build_memo_content,
    extract_assistant_name_assignment,
    extract_user_name_assignment,
    is_memory_recall_question,
    is_user_identity_question,
    load_workspace_memory,
    save_workspace_memory,
    should_save_workspace_memory,
    summarize_workspace_memory,
)
from crew_agent.core.models import Host, StepExecutionResult
from crew_agent.core.ui import TerminalUI
from crew_agent.handlers.workspace import build_workspace_plan
from crew_agent.cli import _handle_conversation_memory


class MemoryTests(unittest.TestCase):
    def _make_temp_dir(self) -> Path:
        path = Path(".cody") / "test-tmp" / uuid4().hex
        path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(path, ignore_errors=True))
        return path

    def test_extract_assistant_name_assignment(self) -> None:
        self.assertEqual(
            extract_assistant_name_assignment("your name from now on is Cody ok"),
            "Cody",
        )

    def test_save_workspace_memory_persists_name(self) -> None:
        temp_path = self._make_temp_dir()
        path = save_workspace_memory(
            "your name from now on is Cody",
            cwd=temp_path,
        )
        self.assertTrue(path.exists())
        memory = load_workspace_memory(temp_path)
        self.assertEqual(memory.assistant_name, "Cody")

    def test_save_workspace_memory_persists_user_name(self) -> None:
        temp_path = self._make_temp_dir()
        save_workspace_memory("my name is Mohamed can you save that in your memo file", cwd=temp_path)
        memory = load_workspace_memory(temp_path)
        self.assertEqual(memory.user_name, "Mohamed")

    def test_build_memo_content_keeps_existing_notes(self) -> None:
        temp_path = self._make_temp_dir()
        save_workspace_memory("your name from now on is Cody", cwd=temp_path)
        content = build_memo_content(
            request="remember this is the local workspace memo",
            existing=load_workspace_memory(temp_path),
        )
        self.assertIn("- Assistant name: Cody", content)
        self.assertIn("Remembered: this is the local workspace memo", content)
        self.assertEqual(content.count("- Purpose: Store important local notes for this workspace."), 1)

    def test_extract_user_name_assignment(self) -> None:
        self.assertEqual(
            extract_user_name_assignment("my name is mohamed can you save that in your memo file"),
            "Mohamed",
        )

    def test_should_save_workspace_memory_for_explicit_note(self) -> None:
        self.assertTrue(should_save_workspace_memory("remember that the server ip is 10.0.0.5"))

    def test_user_identity_question_detection(self) -> None:
        self.assertTrue(is_user_identity_question("so what is my name"))

    def test_memory_recall_question_detection(self) -> None:
        self.assertTrue(is_memory_recall_question("what do you know about me"))

    def test_summarize_workspace_memory_includes_user_name_and_notes(self) -> None:
        temp_path = self._make_temp_dir()
        save_workspace_memory("my name is Mohamed", cwd=temp_path)
        save_workspace_memory("remember that the server ip is 10.0.0.5", cwd=temp_path)
        summary = summarize_workspace_memory(load_workspace_memory(temp_path))
        self.assertIn("Your name here is Mohamed.", summary)
        self.assertIn("Remembered:", summary)

    def test_workspace_artifact_path_persists_across_ui_instances(self) -> None:
        temp_path = self._make_temp_dir()
        artifact_path = r"C:\Users\Mufasa\Documents\test.txt"
        with patch.dict(os.environ, {"CODY_HOME": str(temp_path / ".cody-home")}):
            ui = TerminalUI()
            ui.show_step_result(
                StepExecutionResult(
                    step_id="1",
                    host="local-win",
                    title="Create test.txt",
                    command="cmd",
                    success=True,
                    returncode=0,
                    stdout="",
                    stderr="",
                    verify=None,
                    duration_seconds=0.1,
                    validation_type="workspace_file_info_json",
                    artifact_path=artifact_path,
                ),
                show_evidence=False,
            )
            fresh_ui = TerminalUI()
            self.assertEqual(fresh_ui.last_workspace_artifact_path, artifact_path)
            reply = _handle_workspace_follow_up(
                fresh_ui,
                "give me the path of that text file you have create it",
            )
            self.assertEqual(reply, artifact_path)

    def test_cli_memory_handler_answers_user_name(self) -> None:
        temp_path = self._make_temp_dir()
        with patch("crew_agent.cli.save_workspace_memory") as save_mock, patch(
            "crew_agent.cli.load_workspace_memory",
            return_value=load_workspace_memory(temp_path),
        ):
            save_mock.side_effect = lambda request: save_workspace_memory(request, cwd=temp_path)
            ui = TerminalUI()
            saved = _handle_conversation_memory(ui, "my name is mohamed can you save that in your memo file")
            self.assertEqual(saved, "Understood. Your name in this workspace is now Mohamed.")

        with patch(
            "crew_agent.cli.load_workspace_memory",
            return_value=load_workspace_memory(temp_path),
        ):
            ui = TerminalUI()
            reply = _handle_conversation_memory(ui, "what is my name")
            self.assertEqual(reply, "Your name here is Mohamed.")


class RoutingTests(unittest.TestCase):
    def test_reject_route_falls_back_for_workspace_write(self) -> None:
        decision = RouteDecision(
            kind="reject",
            message="I need a concrete infrastructure task.",
            confidence="medium",
        )
        validated = validate_route_decision(
            decision,
            "create memo.md file and save your name Cody in it",
        )
        self.assertIsNone(validated)

    def test_chat_route_falls_back_for_workspace_write(self) -> None:
        decision = RouteDecision(
            kind="chat",
            message="Hello",
            confidence="medium",
        )
        validated = validate_route_decision(
            decision,
            "create memo.md file and save important info",
        )
        self.assertIsNone(validated)

    def test_workspace_plan_matches_memo_write(self) -> None:
        host = Host(name="local-win", platform="windows", transport="local", enabled=True)
        plan = build_workspace_plan(
            "create memo.md file and save the info which you will need later like your name Cody",
            [host],
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.domain, "workspace")
        self.assertEqual(plan.operation_class, "write_text")

    def test_workspace_plan_creates_documents_text_file(self) -> None:
        host = Host(name="local-win", platform="windows", transport="local", enabled=True)
        plan = build_workspace_plan(
            "can you create in the documents folder a text file and name it test",
            [host],
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.raw.get("handler"), "workspace_file_create")
        self.assertEqual(plan.raw.get("filename"), "test.txt")
        self.assertIn("MyDocuments", plan.steps[0].command)
        self.assertEqual(plan.steps[0].validation_type, "workspace_file_info_json")

    def test_workspace_plan_accepts_named_variant(self) -> None:
        host = Host(name="local-win", platform="windows", transport="local", enabled=True)
        plan = build_workspace_plan(
            "create text file named test in documents folder",
            [host],
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.raw.get("filename"), "test.txt")

    def test_workspace_plan_accepts_direct_filename_variant(self) -> None:
        host = Host(name="local-win", platform="windows", transport="local", enabled=True)
        plan = build_workspace_plan(
            "create text file twin-brother in documents",
            [host],
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.raw.get("filename"), "twin-brother.txt")

    def test_reject_route_falls_back_for_workspace_insert_request(self) -> None:
        decision = RouteDecision(
            kind="reject",
            message="That request is not specific enough to execute safely.",
            confidence="high",
        )
        validated = validate_route_decision(
            decision,
            "insert welcome my brother in the text file you have creat it in docuiments folder name test-brother.txt",
        )
        self.assertIsNone(validated)

    def test_workspace_plan_inserts_text_into_existing_documents_file(self) -> None:
        host = Host(name="local-win", platform="windows", transport="local", enabled=True)
        plan = build_workspace_plan(
            "insert welcome my brother in the text file you have creat it in documents folder name test-brother.txt",
            [host],
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.raw.get("handler"), "workspace_file_insert")
        self.assertEqual(plan.raw.get("filename"), "test-brother.txt")
        self.assertEqual(plan.raw.get("inserted_text"), "welcome my brother")
        self.assertEqual(plan.steps[0].validation_type, "workspace_file_contains_json")
        self.assertIn("MyDocuments", plan.steps[0].command)

    def test_workspace_plan_accepts_documents_typo_for_insert_request(self) -> None:
        host = Host(name="local-win", platform="windows", transport="local", enabled=True)
        plan = build_workspace_plan(
            "insert welcome my brother in the text file you have creat it in docuiments folder name test-brother.txt",
            [host],
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertIn("Documents", plan.summary)
        self.assertIn("MyDocuments", plan.steps[0].command)

    def test_workspace_plan_matches_edit_to_insert_form_without_location(self) -> None:
        host = Host(name="local-win", platform="windows", transport="local", enabled=True)
        plan = build_workspace_plan(
            "edit the text file test-brother.txt and insert ( hi how are you)",
            [host],
        )
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.raw.get("handler"), "workspace_file_insert")
        self.assertEqual(plan.raw.get("filename"), "test-brother.txt")
        self.assertEqual(plan.raw.get("inserted_text"), "hi how are you")
        self.assertEqual(len(plan.steps), 4)
        self.assertTrue(plan.steps[0].continue_on_failure)
        self.assertTrue(plan.steps[1].continue_on_failure)
        self.assertTrue(plan.steps[2].continue_on_failure)
        self.assertFalse(plan.steps[3].continue_on_failure)
        self.assertIn("checking current folder, Documents, Desktop, Downloads", plan.summary)
        self.assertIn("MyDocuments", plan.steps[1].command)

    def test_reject_route_falls_back_for_workspace_edit_request(self) -> None:
        decision = RouteDecision(
            kind="reject",
            message="That request is not specific enough to execute safely.",
            confidence="high",
        )
        validated = validate_route_decision(
            decision,
            "edit the text file test-brother.txt and insert ( hi how are you)",
        )
        self.assertIsNone(validated)


if __name__ == "__main__":
    unittest.main()
