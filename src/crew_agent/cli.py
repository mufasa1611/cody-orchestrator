from __future__ import annotations

import argparse
import json
import shlex
import sys

from dotenv import load_dotenv

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
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cody",
        description="Autonomous Infrastructure Orchestrator shell.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Check local prerequisites and configuration.")

    inventory = subparsers.add_parser("inventory", help="Inspect or initialize inventory.")
    inventory_sub = inventory.add_subparsers(dest="inventory_command", required=True)
    inventory_sub.add_parser("init", help="Create default config and inventory files.")
    inventory_sub.add_parser("show", help="Show the current inventory.")

    model = subparsers.add_parser("model", help="Show, list, or set the planner model.")
    model_sub = model.add_subparsers(dest="model_command", required=False)
    model_sub.add_parser("show", help="Show the configured model.")
    model_sub.add_parser("list", help="List models from Ollama.")
    model_set = model_sub.add_parser("set", help="Set the configured model.")
    model_set.add_argument("model_name", help="Model name from Ollama, e.g. gemma4:latest")

    permissions = subparsers.add_parser(
        "permissions",
        help="Show or set the permission mode.",
    )
    permissions_sub = permissions.add_subparsers(dest="permissions_command", required=False)
    permissions_sub.add_parser("show", help="Show current permission mode.")
    permissions_set = permissions_sub.add_parser("set", help="Set permission mode.")
    permissions_set.add_argument(
        "mode",
        choices=["safe", "elevated", "full"],
        help="Permission mode",
    )

    approvals = subparsers.add_parser(
        "approvals",
        help="Show or set the approval policy.",
    )
    approvals_sub = approvals.add_subparsers(dest="approvals_command", required=True)
    approvals_sub.add_parser("show", help="Show current approval policy.")
    approvals_set = approvals_sub.add_parser("set", help="Set approval policy.")
    approvals_set.add_argument(
        "mode",
        choices=["risky", "always", "never"],
        help="Approval policy",
    )

    agents = subparsers.add_parser("agents", help="Inspect local Cody specialist agents.")
    agents_sub = agents.add_subparsers(dest="agents_command", required=True)
    agents_sub.add_parser("list", help="List local specialist agents.")

    backup = subparsers.add_parser(
        "backup",
        help="Show or set the backup policy for full-permission runs.",
    )
    backup_sub = backup.add_subparsers(dest="backup_command", required=True)
    backup_sub.add_parser("show", help="Show whether backups run before full execution.")
    backup_set = backup_sub.add_parser("set", help="Enable or disable backup snapshots.")
    backup_set.add_argument("mode", choices=["on", "off"], help="Backup policy")

    runs = subparsers.add_parser("runs", help="Inspect recent orchestrator runs.")
    runs_sub = runs.add_subparsers(dest="runs_command", required=True)
    runs_list = runs_sub.add_parser("list", help="List recent runs.")
    runs_list.add_argument("--limit", type=int, default=5, help="Maximum runs to show.")
    runs_sub.add_parser("latest", help="Show the newest run summary.")

    subparsers.add_parser("status", help="Show the current model and permission mode.")

    plan = subparsers.add_parser("plan", help="Plan a request without executing it.")
    plan.add_argument("request", help="Natural-language infrastructure request.")
    plan.add_argument("--host", action="append", default=[], help="Restrict planning to one host. Repeatable.")
    plan.add_argument("--tag", action="append", default=[], help="Restrict planning to hosts that have this tag. Repeatable.")

    run = subparsers.add_parser("run", help="Plan and execute a request.")
    run.add_argument("request", help="Natural-language infrastructure request.")
    run.add_argument("--host", action="append", default=[], help="Restrict execution to one host. Repeatable.")
    run.add_argument("--tag", action="append", default=[], help="Restrict execution to hosts that have this tag. Repeatable.")
    run.add_argument(
        "--permissions",
        choices=["safe", "elevated", "full"],
        help="Override the configured permission mode for this run.",
    )
    run.add_argument(
        "--approve",
        action="store_true",
        help="Bypass approval prompts for this run.",
    )
    run.add_argument("--dry-run", action="store_true", help="Show the plan but do not execute it.")

    subparsers.add_parser("shell", help="Launch the interactive Cody shell.")
    return parser


def _doctor(ui: TerminalUI) -> int:
    bootstrap_local_files()
    paths = ensure_app_dirs()
    config = load_config()
    inventory = load_inventory()
    ui.banner(f"model={config.model} inventory={len([h for h in inventory if h.enabled])} enabled host(s)")

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ui.phase("thinking", f"python {python_version}")
    ui.phase("thinking", f"cody home: {paths.root}")
    ui.phase("thinking", f"inventory file: {paths.inventory_file}")
    ui.phase("thinking", f"run logs: {paths.runs_dir}")
    ui.phase(
        "thinking",
        f"permissions={config.permission_mode} backup_on_full={config.backup_on_full}",
    )
    ui.phase("thinking", f"approval_policy={config.approval_policy}")
    ui.phase("thinking", f"operator_mode={config.operator_mode}")

    client = OllamaClient(model=config.model, base_url=config.base_url, timeout=30)
    try:
        tags = client.tags()
        model_names = [item.get("name", "") for item in tags.get("models", [])]
        model_ok = config.model in model_names
        ui.phase("done", f"ollama url: {normalize_base_url(config.base_url)}")
        ui.phase(
            "done" if model_ok else "warn",
            f"planner model {'found' if model_ok else 'not found'}: {config.model}",
        )
    except Exception as exc:
        ui.phase("warn", f"ollama check failed: {exc}")
        return 1

    ui.show_inventory(inventory)
    return 0


def _status(ui: TerminalUI) -> int:
    config = load_config()
    inventory = load_inventory()
    paths = ensure_app_dirs()
    enabled_hosts = len([host for host in inventory if host.enabled])
    ui.banner(
        (
            f"model={config.model}\n"
            f"permissions={config.permission_mode}\n"
            f"backup_on_full={config.backup_on_full}\n"
            f"approval_policy={config.approval_policy}\n"
            f"operator_mode={config.operator_mode}\n"
            f"ollama_url={normalize_base_url(config.base_url)}\n"
            f"enabled_hosts={enabled_hosts}\n"
            f"runs_dir={paths.runs_dir}"
        )
    )
    return 0


def _inventory(ui: TerminalUI, command: str) -> int:
    if command == "init":
        bootstrap_local_files()
        paths = ensure_app_dirs()
        ui.phase("done", f"initialized inventory at {paths.inventory_file}")
        return 0
    if command == "show":
        inventory = load_inventory()
        ui.show_inventory(inventory)
        return 0
    return 2


def _model(ui: TerminalUI, command: str, model_name: str | None = None) -> int:
    config = load_config()
    client = OllamaClient(model=config.model, base_url=config.base_url, timeout=30)

    if command == "show":
        ui.phase("done", f"current model: {config.model}")
        return 0
    if command == "list":
        names = client.list_model_names()
        for name in names:
            marker = "*" if name == config.model else " "
            ui.phase("thinking", f"{marker} {name}")
        return 0
    if command == "set" and model_name:
        names = client.list_model_names()
        if model_name not in names:
            ui.phase("warn", f"model not found in Ollama: {model_name}")
            return 2
        config.model = model_name
        save_config(config)
        ui.phase("done", f"model set to {model_name}")
        return 0
    return 2


def _model_selector(ui: TerminalUI) -> int:
    config = load_config()
    client = OllamaClient(model=config.model, base_url=config.base_url, timeout=30)
    names = client.list_model_names()
    if not names:
        ui.phase("warn", "no Ollama models found")
        return 1
    selected = ui.select_option(
        title="Model Selector",
        options=names,
        current=config.model,
        help_text="Choose the planner model.",
    )
    if selected is None:
        ui.phase("thinking", "model selection cancelled")
        return 0
    if selected == config.model:
        ui.phase("done", f"model unchanged: {selected}")
        return 0
    config.model = selected
    save_config(config)
    ui.phase("done", f"model set to {selected}")
    return 0


def _permissions(ui: TerminalUI, command: str, mode: str | None = None) -> int:
    config = load_config()
    if command == "show":
        ui.phase("done", f"current permissions: {config.permission_mode}")
        ui.phase("thinking", f"backup_on_full: {config.backup_on_full}")
        ui.phase(
            "thinking",
            "safe blocks elevated and destructive commands; elevated allows service-level changes; full allows destructive commands and may create a backup snapshot for risky infrastructure runs",
        )
        return 0
    if command == "set" and mode:
        config.permission_mode = mode
        save_config(config)
        ui.phase("done", f"permissions set to {mode}")
        if mode == "full":
            if config.backup_on_full:
                ui.phase(
                    "thinking",
                    "full mode may create a backup snapshot under .cody/backups for risky infrastructure runs",
                )
            else:
                ui.phase(
                    "warn",
                    "full mode is active but backup_on_full is disabled",
                )
        return 0
    return 2


def _permissions_selector(ui: TerminalUI) -> int:
    config = load_config()
    options = ["safe", "elevated", "full"]
    selected = ui.select_option(
        title="Permission Selector",
        options=options,
        current=config.permission_mode,
        help_text="Choose the execution permission mode.",
    )
    if selected is None:
        ui.phase("thinking", "permission selection cancelled")
        return 0
    if selected == config.permission_mode:
        ui.phase("done", f"permissions unchanged: {selected}")
        return 0
    return _permissions(ui, "set", selected)


def _approvals(ui: TerminalUI, command: str, mode: str | None = None) -> int:
    config = load_config()
    if command == "show":
        ui.phase("done", f"current approval policy: {config.approval_policy}")
        ui.phase(
            "thinking",
            "risky requires approval for high-risk, unsafe, confirmation-marked, or full-permission runs",
        )
        ui.phase("thinking", "always requires approval for every execution")
        ui.phase("thinking", "never skips approval gates entirely")
        return 0
    if command == "set" and mode:
        config.approval_policy = mode
        save_config(config)
        ui.phase("done", f"approval policy set to {mode}")
        if mode == "never":
            ui.phase("warn", "approval gates are disabled")
        return 0
    return 2


def _backup(ui: TerminalUI, command: str, mode: str | None = None) -> int:
    config = load_config()
    if command == "show":
        ui.phase(
            "done",
            f"backup snapshot before full execution: {'on' if config.backup_on_full else 'off'}",
        )
        return 0
    if command == "set" and mode:
        config.backup_on_full = mode == "on"
        save_config(config)
        ui.phase("done", f"backup_on_full set to {config.backup_on_full}")
        if not config.backup_on_full and config.permission_mode == "full":
            ui.phase("warn", "full permissions are active without automatic backups")
        return 0
    return 2


def _agents(ui: TerminalUI, command: str) -> int:
    if command != "list":
        return 2
    catalog = get_agent_catalog()
    if not catalog.definitions:
        ui.phase("warn", f"no local agent definitions found in {catalog.directory}")
        return 1
    ui.phase("done", f"local agent definitions: {catalog.directory}")
    for definition in catalog.definitions.values():
        ui.phase(
            "thinking",
            f"{definition.name} [{definition.kind}] - {definition.description}",
        )
    return 0


def _runs(ui: TerminalUI, command: str, limit: int = 5) -> int:
    paths = ensure_app_dirs()
    run_files = sorted(
        paths.runs_dir.glob("*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not run_files:
        ui.phase("warn", "no run logs found")
        return 1

    if command == "list":
        for path in run_files[: max(1, limit)]:
            payload = json.loads(path.read_text(encoding="utf-8"))
            results = payload.get("results", [])
            succeeded = sum(1 for result in results if result.get("success"))
            ui.phase(
                "thinking",
                (
                    f"{path.name} perm={payload.get('permission_mode', '-')} "
                    f"approval={'yes' if payload.get('approval_required') else 'no'} "
                    f"steps={succeeded}/{len(results)} "
                    f"backup={'yes' if payload.get('backup_path') else 'no'}"
                ),
            )
            ui.console.print(f"  request: {payload.get('request', '')[:140]}")
        return 0

    if command == "latest":
        payload = json.loads(run_files[0].read_text(encoding="utf-8"))
        results = payload.get("results", [])
        succeeded = sum(1 for result in results if result.get("success"))
        ui.phase("done", f"latest run: {run_files[0]}")
        ui.phase("thinking", f"request: {payload.get('request', '')}")
        ui.phase("thinking", f"summary: {payload.get('summary', '')}")
        ui.phase(
            "thinking",
            (
                f"risk={payload.get('risk', '-')} "
                f"permissions={payload.get('permission_mode', '-')} "
                f"approval_policy={payload.get('approval_policy', '-')} "
                f"approval_granted={payload.get('approval_granted', False)} "
                f"steps={succeeded}/{len(results)}"
            ),
        )
        reasons = payload.get("approval_reasons") or []
        for reason in reasons:
            ui.phase("thinking", f"approval reason: {reason}")
        if payload.get("backup_path"):
            ui.phase("thinking", f"backup: {payload['backup_path']}")
        return 0

    return 2


def _prompt_for_approval(ui: TerminalUI, reasons: list[str]) -> bool:
    ui.phase("warn", "approval required before execution")
    for reason in reasons:
        ui.phase("thinking", f"approval reason: {reason}")
    ui.console.print("  type approve to continue: ", end="")
    try:
        response = input().strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return response.casefold() == "approve"


def _handle_request_intent(ui: TerminalUI, request: str) -> tuple[str | None, int | None]:
    path_reply = _handle_workspace_follow_up(ui, request)
    if path_reply is not None:
        ui.phase("done", path_reply)
        return None, 0

    memory_reply = _handle_conversation_memory(ui, request)
    if memory_reply is not None:
        ui.phase("done", memory_reply)
        return None, 0

    config = load_config()
    decision = route_request(request, config)
    ui.phase(
        "thinking",
        f"router={decision.kind} confidence={decision.confidence} reason={decision.reason or '-'}",
    )
    if decision.kind == "task":
        normalized_request = decision.normalized_request or request
        if normalized_request != request:
            ui.phase("thinking", f"normalized request: {normalized_request}")
        return normalized_request, None
    if decision.kind == "help":
        ui.phase("done", decision.message or "Ask for help with a concrete Cody feature.")
        _show_shell_help(ui)
        return None, 0
    if decision.kind == "chat":
        ui.phase("done", decision.message or "Give me a concrete infrastructure task to run.")
        return None, 0
    ui.phase(
        "warn",
        decision.message
        or "That request is not specific enough to execute safely.",
    )
    return None, 2


def _handle_conversation_memory(ui: TerminalUI, request: str) -> str | None:
    assigned_name = extract_assistant_name_assignment(request)
    if assigned_name:
        path = save_workspace_memory(request)
        ui.phase("thinking", f"saved workspace memory to {path}")
        return f"Understood. My name in this workspace is now {assigned_name}."

    user_name = extract_user_name_assignment(request)
    if user_name:
        path = save_workspace_memory(request)
        ui.phase("thinking", f"saved workspace memory to {path}")
        return f"Understood. Your name in this workspace is now {user_name}."

    if should_save_workspace_memory(request):
        path = save_workspace_memory(request)
        ui.phase("thinking", f"saved workspace memory to {path}")
        return "Understood. I saved that in the workspace memo."

    if is_user_identity_question(request):
        memory = load_workspace_memory()
        if memory.user_name:
            return f"Your name here is {memory.user_name}."
        return "I do not know your name yet."

    if is_identity_question(request):
        memory = load_workspace_memory()
        name = memory.assistant_name or DEFAULT_ASSISTANT_NAME
        return f"My name here is {name}."

    if is_memory_recall_question(request):
        memory = load_workspace_memory()
        return summarize_workspace_memory(memory)

    return None


def _handle_workspace_follow_up(ui: TerminalUI, request: str) -> str | None:
    if not ui.last_workspace_artifact_path:
        return None
    lowered = " ".join(request.casefold().split())
    if any(
        phrase in lowered
        for phrase in (
            "path of that text file",
            "path of that file",
            "path of the file",
            "where is that file",
            "where is the file",
            "what is the path",
            "give me the path",
        )
    ):
        return ui.last_workspace_artifact_path
    return None


def _plan(ui: TerminalUI, request: str, hosts: list[str], tags: list[str]) -> int:
    routed_request, handled = _handle_request_intent(ui, request)
    if handled is not None:
        return handled
    plan, selected_hosts = orchestrator_plan_request(
        request=routed_request or request,
        ui=ui,
        host_names=hosts,
        tags=tags,
    )
    ui.show_plan(plan, selected_hosts)
    return 0 if plan.steps else 2


def _run(
    ui: TerminalUI,
    request: str,
    hosts: list[str],
    tags: list[str],
    permission_mode: str | None,
    approved: bool,
    allow_prompt: bool,
    dry_run: bool,
) -> int:
    routed_request, handled = _handle_request_intent(ui, request)
    if handled is not None:
        return handled
    approval_callback = None
    if allow_prompt and not approved:
        approval_callback = lambda reasons: _prompt_for_approval(ui, reasons)
    return orchestrator_run_request(
        request=routed_request or request,
        ui=ui,
        host_names=hosts,
        tags=tags,
        permission_mode=permission_mode,
        approved=approved,
        approval_callback=approval_callback,
        dry_run=dry_run,
    )


def _show_shell_help(ui: TerminalUI) -> None:
    ui.phase("thinking", "plain text runs a request immediately")
    ui.phase("thinking", "/plan <request> previews a plan")
    ui.phase("thinking", "/doctor checks config, inventory, and ollama")
    ui.phase("thinking", "/hosts shows the current inventory")
    ui.phase("thinking", "/status shows the current model and permissions")
    ui.phase("thinking", "/model opens the model selector")
    ui.phase("thinking", "/permissions opens the permission selector")
    ui.phase("thinking", "/approvals risky|always|never changes approval gates")
    ui.phase("thinking", "/agents lists local specialist agent files")
    ui.phase("thinking", "/backup on|off controls backup snapshots before full runs")
    ui.phase("thinking", "/runs lists recent executions")
    ui.phase("thinking", "/runs latest shows the newest run summary")
    ui.phase("thinking", "/exit quits")


def _interactive_shell(ui: TerminalUI) -> int:
    bootstrap_local_files()
    config = load_config()
    inventory = load_inventory()
    ui.banner(
        f"interactive shell ready\nmodel={config.model} enabled_hosts={len([h for h in inventory if h.enabled])}"
    )
    _show_shell_help(ui)

    while True:
        try:
            request = input("cody> ").strip().lstrip("\ufeff")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not request:
            continue
        lowered = request.casefold()
        if lowered in {"exit", "quit", "/exit", "/quit"}:
            return 0
        if lowered.startswith("/"):
            parts = shlex.split(request)
            command = parts[0].casefold()
            if command == "/help":
                _show_shell_help(ui)
                continue
            if command == "/doctor":
                _doctor(ui)
                continue
            if command == "/hosts":
                ui.show_inventory(load_inventory())
                continue
            if command == "/status":
                _status(ui)
                continue
            if command == "/model":
                if len(parts) == 1:
                    _model_selector(ui)
                    continue
                if len(parts) == 2 and parts[1].casefold() == "list":
                    _model(ui, "list")
                    continue
                if len(parts) >= 3 and parts[1].casefold() == "set":
                    _model(ui, "set", " ".join(parts[2:]))
                    continue
            if command == "/permissions":
                if len(parts) == 1:
                    _permissions_selector(ui)
                    continue
                if len(parts) == 2 and parts[1].casefold() in {"safe", "elevated", "full"}:
                    _permissions(ui, "set", parts[1].casefold())
                    continue
                if len(parts) == 2 and parts[1].casefold() == "show":
                    _permissions(ui, "show")
                    continue
            if command == "/approvals":
                if len(parts) == 1:
                    _approvals(ui, "show")
                    continue
                if len(parts) == 2 and parts[1].casefold() in {"risky", "always", "never"}:
                    _approvals(ui, "set", parts[1].casefold())
                    continue
                if len(parts) == 2 and parts[1].casefold() == "show":
                    _approvals(ui, "show")
                    continue
            if command == "/agents":
                _agents(ui, "list")
                continue
            if command == "/backup":
                if len(parts) == 1:
                    _backup(ui, "show")
                    continue
                if len(parts) == 2 and parts[1].casefold() in {"on", "off"}:
                    _backup(ui, "set", parts[1].casefold())
                    continue
                if len(parts) == 2 and parts[1].casefold() == "show":
                    _backup(ui, "show")
                    continue
            if command == "/runs":
                if len(parts) == 1:
                    _runs(ui, "list")
                    continue
                if len(parts) == 2 and parts[1].casefold() == "latest":
                    _runs(ui, "latest")
                    continue
            if command == "/plan" and len(parts) >= 2:
                _plan(ui, request[len(parts[0]):].strip(), hosts=[], tags=[])
                continue
            if command == "/run" and len(parts) >= 2:
                _run(
                    ui,
                    request[len(parts[0]):].strip(),
                    hosts=[],
                    tags=[],
                    permission_mode=None,
                    approved=False,
                    allow_prompt=True,
                    dry_run=False,
                )
                continue

        _run(
            ui,
            request,
            hosts=[],
            tags=[],
            permission_mode=None,
            approved=False,
            allow_prompt=True,
            dry_run=False,
        )


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    bootstrap_local_files()
    ui = TerminalUI()

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return _interactive_shell(ui)

    first = argv[0]
    if first not in KNOWN_COMMANDS and not first.startswith("-"):
        argv = ["run", *argv]

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        return _doctor(ui)
    if args.command == "inventory":
        return _inventory(ui, args.inventory_command)
    if args.command == "model":
        if getattr(args, "model_command", None) is None:
            return _model_selector(ui)
        return _model(ui, args.model_command, getattr(args, "model_name", None))
    if args.command == "permissions":
        if getattr(args, "permissions_command", None) is None:
            return _permissions_selector(ui)
        return _permissions(ui, args.permissions_command, getattr(args, "mode", None))
    if args.command == "approvals":
        return _approvals(ui, args.approvals_command, getattr(args, "mode", None))
    if args.command == "agents":
        return _agents(ui, args.agents_command)
    if args.command == "backup":
        return _backup(ui, args.backup_command, getattr(args, "mode", None))
    if args.command == "runs":
        return _runs(ui, args.runs_command, getattr(args, "limit", 5))
    if args.command == "status":
        return _status(ui)
    if args.command == "plan":
        return _plan(ui, args.request, args.host, args.tag)
    if args.command == "run":
        return _run(
            ui,
            args.request,
            args.host,
            args.tag,
            args.permissions,
            args.approve,
            sys.stdin.isatty(),
            args.dry_run,
        )
    if args.command == "shell":
        return _interactive_shell(ui)

    parser.print_help()
    return 2
