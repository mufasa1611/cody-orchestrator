from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from rich.panel import Panel
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory

from crew_agent.conversation.ollama import OllamaClient, normalize_base_url
from crew_agent.conversation.router import route_request
from crew_agent.agents import get_agent_catalog
from crew_agent.core.memory import (
    DEFAULT_ASSISTANT_NAME,
    extract_assistant_name_assignment,
    extract_user_name_assignment,
    is_identity_question,
    is_memory_recall_question,
    is_user_identity_question,
    load_workspace_memory,
    save_workspace_memory,
    should_save_workspace_memory,
    summarize_workspace_memory,
)
from crew_agent.core.paths import ensure_app_dirs
from crew_agent.core.ui import TerminalUI
from crew_agent.core.models import ConversationThread
from crew_agent.handlers.orchestrator import plan_request as orchestrator_plan_request
from crew_agent.handlers.orchestrator import run_request as orchestrator_run_request
from crew_agent.policy.config import (
    bootstrap_local_files,
    load_config,
    save_config,
)
from crew_agent.providers.inventory import load_inventory


KNOWN_COMMANDS = {
    "approvals",
    "agents",
    "backup",
    "doctor",
    "inventory",
    "model",
    "permissions",
    "runs",
    "status",
    "plan",
    "run",
    "shell",
    "help",
    "update",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codin",
        description="Autonomous Infrastructure Orchestrator shell.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor")
    subparsers.add_parser("inventory")
    subparsers.add_parser("model")
    subparsers.add_parser("permissions")
    subparsers.add_parser("approvals")
    subparsers.add_parser("agents")
    subparsers.add_parser("backup")
    subparsers.add_parser("runs")
    subparsers.add_parser("status")
    subparsers.add_parser("shell")
    run = subparsers.add_parser("run")
    run.add_argument("request")
    run.add_argument("--host", action="append", default=[])
    run.add_argument("--tag", action="append", default=[])
    run.add_argument("--permissions")
    run.add_argument("--approve", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    plan = subparsers.add_parser("plan")
    plan.add_argument("request")
    plan.add_argument("--host", action="append", default=[])
    plan.add_argument("--tag", action="append", default=[])
    return parser


def _plan(ui: TerminalUI, request: str, hosts: list[str], tags: list[str], thread: ConversationThread | None = None) -> int:
    plan, selected_hosts = orchestrator_plan_request(request=request, hosts=load_inventory(), config=load_config())
    ui.show_plan(plan, selected_hosts)
    return 0

def _run(ui: TerminalUI, request: str, hosts: list[str], tags: list[str], permissions: str | None, approved: bool, allow_prompt: bool, dry_run: bool, thread: ConversationThread | None = None) -> int:
    return orchestrator_run_request(request=request, ui=ui, permissions=permissions, approve_all=approved, is_interactive=allow_prompt, dry_run=dry_run, host_names=hosts, tags=tags, thread=thread)

def _show_shell_help(ui: TerminalUI) -> None:
    ui.phase("thinking", "Enter any natural language task or a /command.")

def _interactive_shell(ui: TerminalUI) -> int:
    bootstrap_local_files()
    paths = ensure_app_dirs()
    ui.banner("interactive shell ready")
    _show_shell_help(ui)

    thread = ConversationThread()
    slash_commands = [
        "/help", "/doctor", "/inventory", "/status", "/model", "/permissions", 
        "/approvals", "/agents", "/backup", "/runs", "/update", "/exit", "/quit"
    ]
    completer = WordCompleter(slash_commands, ignore_case=True)
    history_file = paths.root / "history.txt"
    session = PromptSession(history=FileHistory(str(history_file)), completer=completer, complete_while_typing=True)

    while True:
        try:
            request = session.prompt("codin> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0

        if not request: continue
        if request.casefold() in {"exit", "quit", "/exit", "/quit"}: return 0
        
        _run(ui, request, [], [], None, False, True, False, thread=thread)


def _check_for_updates(ui: TerminalUI) -> None:
    try:
        if not os.path.exists(".git"): return
        paths = ensure_app_dirs()
        sentinel = paths.root / ".last_update_check"
        if sentinel.exists() and (time.time() - sentinel.stat().st_mtime) < 86400: return
        subprocess.run(["git", "fetch"], capture_output=True, timeout=5)
        res = subprocess.run(["git", "rev-list", "HEAD..origin/main", "--count"], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            count = int(res.stdout.strip() or "0")
            if count > 0:
                ui.console.print(Panel(f"Update Available! Codex is {count} commits behind. Run 'git pull'.", border_style="yellow"))
        sentinel.touch()
    except: pass

def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    bootstrap_local_files()
    ui = TerminalUI()
    _check_for_updates(ui)
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv: return _interactive_shell(ui)
    
    # Simple argument parsing for this test
    if argv[0] == "run":
        return _run(ui, " ".join(argv[1:]), [], [], None, False, True, False)
    return _interactive_shell(ui)

if __name__ == "__main__":
    sys.exit(main())
