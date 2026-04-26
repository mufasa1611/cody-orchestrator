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
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import WordCompleter

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


def ensure_truthful_model(ui: TerminalUI, config: AppConfig) -> AppConfig:
    """The 'Global Truth' anchor: ensures the config matches the real GPU state."""
    ui.phase("thinking", "Scanning GPU for active models...")
    client = OllamaClient(model=config.model, base_url=config.base_url)
    real_model = client.get_running_model()
    
    if real_model:
        if real_model != config.model:
            config.model = real_model
            save_config(config)
            ui.phase("done", f"Detected active model: {real_model}")
    else:
        # Nothing is loaded; FORCE SELECTION
        ui.phase("warn", "No model is currently loaded in your GPU.")
        # Trigger selection menu
        choice = _handle_model_selection(ui, config)
        if choice:
            config.model = choice
            save_config(config)
            # PRO LOGIC: Blocking Wait for Load
            ui.phase("thinking", f"Loading {choice} onto GPU (this can take a moment for large models)...")
            client = OllamaClient(model=choice, base_url=config.base_url)
            client.warm_up()
            
            # POLL for reality
            max_attempts = 30
            for attempt in range(max_attempts):
                real_check = client.get_running_model()
                if real_check and choice in real_check:
                    ui.phase("done", f"Model {choice} is now fully resident in GPU.")
                    break
                time.sleep(2)
            else:
                ui.phase("warn", f"Model {choice} is taking a long time to load. It will be ready shortly.")
            
    return config

def _handle_model_selection(ui: TerminalUI, config: AppConfig) -> str | None:
    client = OllamaClient(model=config.model, base_url=config.base_url)
    try:
        names = client.list_model_names()
        if not names:
            return None
        return ui.select_option("Select AI Model to Load", names, current=config.model)
    except:
        return None

def _interactive_shell(ui: TerminalUI) -> int:
    bootstrap_local_files()
    paths = ensure_app_dirs()
    config = load_config()
    
    # 1. TRUTH FIRST
    config = ensure_truthful_model(ui, config)
    inventory = load_inventory()
    
    ui.banner(f"interactive shell ready\nmodel={config.model} enabled_hosts={len([h for h in inventory if h.enabled])}")

    # Initialize persistent conversation thread with DB history
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
        ui.phase("warn", f"Command {cmd} is not yet implemented in this view.")

def _handle_model_cmd(ui: TerminalUI) -> None:
    config = load_config()
    choice = _handle_model_selection(ui, config)
    if choice and choice != config.model:
        client = OllamaClient(model=config.model, base_url=config.base_url)
        ui.phase("thinking", f"Unloading {config.model} from VRAM...")
        client.unload_model()
        config.model = choice
        save_config(config)
        ui.phase("thinking", f"Loading {choice} onto GPU...")
        new_client = OllamaClient(model=choice, base_url=config.base_url)
        new_client.warm_up()
        ui.phase("done", f"Model switched to: {choice}")

def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    bootstrap_local_files()
    ui = TerminalUI()
    
    argv = list(sys.argv[1:] if argv is None else argv)
    
    # Check for update but don't hang
    # (Optional: call _check_for_updates)

    if not argv or (len(argv) == 1 and argv[0] == "shell"):
        return _interactive_shell(ui)
    
    if "--version" in argv:
        from crew_agent import __version__
        print(f"Codin v{__version__}")
        return 0

    # PRO TRUTH-RUN: Also verify model for one-shot runs
    config = load_config()
    config = ensure_truthful_model(ui, config)

    request_text = " ".join(argv)
    if argv[0] == "run": request_text = " ".join(argv[1:])

    return orchestrator_run_request(request=request_text, ui=ui, is_interactive=True)

if __name__ == "__main__":
    sys.exit(main())
