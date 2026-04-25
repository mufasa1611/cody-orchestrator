from __future__ import annotations

import unittest

from crew_agent.agents import get_agent_catalog, get_agent_definition
from crew_agent.core.models import AppConfig, Host
from crew_agent.handlers.task_router import resolve_execution_plan


class AgentCatalogTests(unittest.TestCase):
    def test_local_agent_definitions_are_loaded(self) -> None:
        catalog = get_agent_catalog()
        self.assertIn("file-reader", catalog.definitions)
        self.assertIn("infra-planner", catalog.definitions)

    def test_agent_definition_has_source_path(self) -> None:
        definition = get_agent_definition("file-reader")
        self.assertIsNotNone(definition)
        assert definition is not None
        self.assertTrue(str(definition.source_path).endswith("file-reader.yaml"))

    def test_task_router_attaches_agent_definition_metadata(self) -> None:
        host = Host(name="local-win", platform="windows", transport="local", enabled=True)
        plan, source = resolve_execution_plan(
            "read file imp-info.txt in documents folder and show me the server info in the file",
            [host],
            AppConfig(),
        )
        self.assertEqual(source, "code")
        self.assertEqual(plan.raw.get("specialist"), "file-reader")
        self.assertEqual(plan.raw.get("agent_title"), "File Reader")
        self.assertTrue(str(plan.raw.get("agent_definition_path", "")).endswith("file-reader.yaml"))


if __name__ == "__main__":
    unittest.main()
