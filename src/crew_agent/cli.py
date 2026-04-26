from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from rich.panel import Panel
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory

from crew_agent.conversation.ollama import OllamaClient, normalize_base_url
from crew_agent.core.paths import ensure_app_dirs
from crew_agent.core.ui import TerminalUI
from crew_agent.core.models import ConversationThread, AppConfig
from crew_agent.handlers.orchestrator import plan_request as orchestrator_plan_request
from crew_agent.handlers.orchestrator import run_request as orchestrator_run_request
from crew_agent.policy.config import (
    bootstrap_local_files,
    load_config,
    save_config,
)
from crew_agent.providers.inventory import load_inventory


def _interactive_shell(ui: TerminalUI) -> int:
    bootstrap_local_files()
    paths = ensure_app_dirs()
    config = load_config()
    inventory = load_inventory()
    
    ui.banner(f"interactive shell ready\nmodel={config.model} enabled_hosts={len([h for h in inventory if h.enabled])}")
    ui.phase("thinking", "Enter any natural language task or a /command.")

    # NEW: Initialize persistent conversation thread with DB history
    from crew_agent.core.db import get_last_messages_from_db
    from crew_agent.core.models import ConversationThread, ConversationMessage
    
    db_messages = get_last_messages_from_db(limit=10)
    msg_objects = [ConversationMessage(role=m['role'], content=m['content']) for m in db_messages]
    thread = ConversationThread(messages=msg_objects)
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
        
        if request.startswith("/"):
            _handle_slash_command(request, ui, thread)
        else:
            orchestrator_run_request(request=request, ui=ui, is_interactive=True, thread=thread)

def _handle_slash_command(request: str, ui: TerminalUI, thread: ConversationThread) -> None:
    parts = shlex.split(request)
    cmd = parts[0].casefold()
    
    if cmd == "/status":
        from crew_agent.cli import _status
        _status(ui)
    elif cmd == "/model":
        _handle_model_cmd(ui)
    elif cmd == "/help":
        ui.phase("thinking", "Available commands: " + ", ".join(["/status", "/model", "/doctor", "/inventory", "/exit"]))
    else:
        ui.phase("warn", f"Command {cmd} is not yet implemented in this view, but I'm working on it!")

def _handle_model_cmd(ui: TerminalUI) -> None:
    config = load_config()
    client = OllamaClient(model=config.model, base_url=config.base_url)
    try:
        names = client.list_model_names()
        if not names:
            ui.phase("warn", "No models found in Ollama.")
            return
        
        choice = ui.select_option("Select AI Model", names, current=config.model)
        if choice:
            config.model = choice
            save_config(config)
            ui.phase("done", f"Model updated to: {choice}")
    except Exception as e:
        ui.phase("warn", f"Could not list models: {e}")

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
                ui.console.print(Panel(f"Update Available! Codin is {count} commits behind. Run '/update apply'.", border_style="yellow"))
        sentinel.touch()
    except: pass

def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    bootstrap_local_files()
    ui = TerminalUI()
    _check_for_updates(ui)
    
    argv = list(sys.argv[1:] if argv is None else argv)
    
    # 1. Handle no-args or explicit 'shell' command
    if not argv or (len(argv) == 1 and argv[0] == "shell"):
        return _interactive_shell(ui)
    
    # 2. Handle built-in flags
    if "--version" in argv:
        from crew_agent import __version__
        print(f"Codin v{__version__}")
        return 0

    # 3. Handle 'run' command (stripping the 'run' prefix if present)
    request_text = " ".join(argv)
    if argv[0] == "run":
        request_text = " ".join(argv[1:])

    # 4. Execute orchestration
    return orchestrator_run_request(request=request_text, ui=ui, is_interactive=False)

if __name__ == "__main__":
    sys.exit(main())
