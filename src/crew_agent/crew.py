from __future__ import annotations

import os
from pathlib import Path

from crewai import Agent, Crew, Task
from crewai.memory.storage.kickoff_task_outputs_storage import (
    KickoffTaskOutputsSQLiteStorage,
)
from crewai.utilities.task_output_storage_handler import TaskOutputStorageHandler
from pydantic import PrivateAttr

from crew_agent.llm import build_llm
from crew_agent.tools import DiscoveryTool, FileEditorTool, WebSearchTool, WindowsCommandTool


def configure_local_storage() -> Path:
    storage_root = Path(
        os.getenv("CREW_AGENT_STORAGE_ROOT", Path.cwd() / ".crewai")
    ).resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("LOCALAPPDATA", str(storage_root))
    os.environ.setdefault("APPDATA", str(storage_root))
    os.environ.setdefault("CREWAI_STORAGE_DIR", "crew-agent")
    os.environ.setdefault("CREWAI_TESTING", "true")
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    _disable_crewai_first_run_tracing()
    return storage_root


def _disable_crewai_first_run_tracing() -> None:
    try:
        from crewai.events.listeners.tracing.first_time_trace_handler import (
            FirstTimeTraceHandler,
        )
    except Exception:
        return

    def _never_initialize(self: FirstTimeTraceHandler) -> bool:
        self.is_first_time = False
        return False

    def _do_nothing(self: FirstTimeTraceHandler) -> None:
        return None

    FirstTimeTraceHandler.initialize_for_first_time_user = _never_initialize
    FirstTimeTraceHandler.handle_execution_completion = _do_nothing


class LocalTaskOutputStorageHandler(TaskOutputStorageHandler):
    def __init__(self) -> None:
        storage_root = configure_local_storage() / "CrewAI" / "crew-agent"
        storage_root.mkdir(parents=True, exist_ok=True)
        db_path = storage_root / "latest_kickoff_task_outputs.db"
        self.storage = KickoffTaskOutputsSQLiteStorage(str(db_path))


class LocalCrew(Crew):
    _task_output_handler: LocalTaskOutputStorageHandler = PrivateAttr(
        default_factory=LocalTaskOutputStorageHandler
    )


def build_windows_agent(
    model: str | None = None,
    temperature: float | None = None,
    base_url: str | None = None,
    allow_unsafe: bool = False,
    verbose: bool = False,
) -> Agent:
    cmd_tool = WindowsCommandTool(allow_unsafe=allow_unsafe)
    edit_tool = FileEditorTool()
    web_tool = WebSearchTool()
    discovery_tool = DiscoveryTool()
    llm = build_llm(
        model=model,
        temperature=temperature,
        base_url=base_url,
    )

    return Agent(
        role="Windows automation operator",
        goal=(
            "Translate user requests into safe PowerShell commands, surgical file edits, "
            "web research steps, or network discovery, execute them when necessary, and explain the result clearly."
        ),
        backstory=(
            "You are a senior Windows administrator operating through a CLI. "
            "Use the windows_command tool for system tasks, file_editor for "
            "precise code modifications, web_search to find documentation, and "
            "discover_hosts to map the local network. Summarize what happened concisely."
        ),
        llm=llm,
        tools=[cmd_tool, edit_tool, web_tool, discovery_tool],
        allow_delegation=False,
        verbose=verbose,
    )


def run_request(
    request: str,
    model: str | None = None,
    temperature: float | None = None,
    base_url: str | None = None,
    allow_unsafe: bool = False,
    verbose: bool = False,
):
    configure_local_storage()
    agent = build_windows_agent(
        model=model,
        temperature=temperature,
        base_url=base_url,
        allow_unsafe=allow_unsafe,
        verbose=verbose,
    )

    task = Task(
        description=(
            "Handle this Windows CLI request:\n"
            f"{request}\n\n"
            "Use the windows_command tool if a PowerShell command is required. "
            "Return a concise summary of what you executed and the result."
        ),
        expected_output=(
            "A short answer describing the command used, important command output, "
            "and the final result."
        ),
        agent=agent,
    )

    crew = LocalCrew(
        agents=[agent],
        tasks=[task],
        verbose=verbose,
    )
    return crew.kickoff()
