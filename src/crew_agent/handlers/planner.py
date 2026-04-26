from __future__ import annotations

import json
from typing import Any

from crew_agent.agents import get_agent_definition
from crew_agent.conversation.ollama import OllamaClient
from crew_agent.core.memory import load_workspace_memory
from crew_agent.core.models import AppConfig, ExecutionPlan, Host, PlanStep


DEFAULT_PLANNER_SYSTEM_PROMPT = """
You are Cody, an infrastructure orchestration planner.

Your job is to convert a natural-language infrastructure request into a SAFE structured execution plan.

Rules:
- Return valid JSON only.
- Use only the hosts provided in INVENTORY.
- Never invent hosts.
- Prefer inspection commands first when the user asks to "check", "show", "list", "status", or "version".
- For Windows hosts, produce PowerShell command text only. Do not wrap it in "powershell -Command".
- IMPORTANT: Never use CMD.exe style flags (e.g., dir /s, del /f, copy /y). Use native PowerShell cmdlets (e.g., Get-ChildItem -Recurse, Remove-Item -Force, Copy-Item).
- Never recursively scan the root of C: or D: drives for file contents or patterns unless explicitly told to "scan the whole disk". Focus on the User Profile ($env:USERPROFILE) or specific named folders.
- For all file modifications (replacing text, inserting lines, or updating content), you MUST use the "edit" kind.
- NEVER use PowerShell redirection (e.g., Set-Content, Add-Content, -replace) to modify source code.
- IMPORTANT: The command for an "edit" step MUST be a valid JSON object using DOUBLE QUOTES (").
- Example edit command: {"file_path": "C:\\full\\path\\to\\file.txt", "old_string": "old text", "new_string": "new text"}
- Always provide the FULL ABSOLUTE PATH for the file_path in an edit command.
- Use the kind "web_search" and the search query as the command when you need to research documentation or error solutions. Assign these steps to the 'local-win' host or the first available host in the inventory.
- Use the kind "discovery" when the user wants to scan the network or find other devices. Assign these steps to a local host.
- Even if a request is purely research-based, you MUST provide at least one executable step.
- For change and edit steps, you MUST provide a verify_command to confirm the success of the action. Don't claim success unless verified.
- Avoid placeholder or weak commands that return nothing.
- If the user request is a casual greeting (e.g., 'hi', 'hello') or a conversational question that does not require executing commands, return an empty `steps` array and put your friendly response in the `summary` field. You do not need to provide steps for simple chat.
- Example Windows inspection command for PowerShell version:
  `$PSVersionTable.PSVersion | Select-Object Major,Minor,Build,Revision | ConvertTo-Json -Compress`
- Example Windows inspection command for service status:
  `Get-Service -Name Audiosrv | Select-Object Name,Status,StartType | ConvertTo-Json -Compress`
- Example Linux inspection command for nginx status:
  `systemctl status nginx --no-pager --full`
- If the request is ambiguous, return missing_information.
- Mark requires_unsafe=true for clearly destructive operations like delete, wipe, format, reboot, shutdown, firewall flush, package removal, or service stop on production-sounding requests.
- Keep commands single-step and operationally realistic.
- Provide a short planning summary and short planner_notes, not hidden chain-of-thought.

Output schema:
{
  "summary": "short summary",
  "planner_notes": ["short note", "short note"],
  "risk": "low|medium|high",
  "requires_confirmation": true,
  "requires_unsafe": false,
  "missing_information": ["question or gap"],
  "target_hosts": ["host-1"],
  "steps": [
    {
      "id": "step-1",
      "title": "human title",
      "host": "host-1",
      "kind": "inspect|change|edit|web_search|discovery|verify",
      "rationale": "why this step exists",
      "command": "actual command",
      "verify_command": "optional validation command",
      "expected_signal": "what success should look like",
      "validation_type": "optional validation type"
    }
  ]
}
""".strip()


def _planner_system_prompt() -> str:
    definition = get_agent_definition("infra-planner")
    if definition is None or not definition.prompt:
        return DEFAULT_PLANNER_SYSTEM_PROMPT
    return f"{definition.prompt}\n\n{DEFAULT_PLANNER_SYSTEM_PROMPT}".strip()


def _inventory_payload(hosts: list[Host]) -> list[dict[str, Any]]:
    return [
        {
            "name": host.name,
            "platform": host.platform,
            "transport": host.transport,
            "address": host.address,
            "user": host.user,
            "port": host.port,
            "tags": host.tags,
        }
        for host in hosts
    ]


def _normalize_plan(data: dict[str, Any], hosts: list[Host]) -> ExecutionPlan:
    host_lookup = {host.name: host for host in hosts}
    default_host_name = _default_host_name(hosts)
    target_hosts = [
        name for name in data.get("target_hosts", []) if isinstance(name, str) and name in host_lookup
    ]

    raw_steps = data.get("steps", [])
    steps: list[PlanStep] = []
    if isinstance(raw_steps, list):
        for index, item in enumerate(raw_steps, start=1):
            if not isinstance(item, dict):
                continue
            host_name = str(item.get("host", "")).strip()
            if host_name not in host_lookup:
                host_name = default_host_name
            if host_name not in host_lookup:
                continue
            command = str(item.get("command", "")).strip()
            if not command:
                continue
            steps.append(
                PlanStep(
                    id=str(item.get("id") or f"step-{index}"),
                    title=str(item.get("title") or f"Step {index}"),
                    host=host_name,
                    command=command,
                    rationale=str(item.get("rationale", "")).strip(),
                    kind=str(item.get("kind") or "change"),
                    verify_command=(
                        str(item.get("verify_command")).strip()
                        if item.get("verify_command")
                        else None
                    ),
                    expected_signal=(
                        str(item.get("expected_signal")).strip()
                        if item.get("expected_signal")
                        else None
                    ),
                    validation_type=(
                        str(item.get("validation_type")).strip()
                        if item.get("validation_type")
                        else None
                    ),
                )
            )

    planner_notes = data.get("planner_notes", [])
    missing_information = data.get("missing_information", [])
    if not isinstance(planner_notes, list):
        planner_notes = []
    if not isinstance(missing_information, list):
        missing_information = []

    if not target_hosts:
        target_hosts = sorted({step.host for step in steps})

    return ExecutionPlan(
        summary=str(data.get("summary") or "No summary returned."),
        planner_notes=[str(item) for item in planner_notes if str(item).strip()],
        risk=str(data.get("risk") or "medium").lower(),
        domain=str(data.get("domain") or "infra").lower(),
        operation_class=str(data.get("operation_class") or _infer_operation_class(steps)).lower(),
        requires_confirmation=bool(data.get("requires_confirmation", False)),
        requires_unsafe=bool(data.get("requires_unsafe", False)),
        missing_information=[str(item) for item in missing_information if str(item).strip()],
        target_hosts=target_hosts,
        steps=steps,
        raw=data,
    )


def _repair_plan(plan: ExecutionPlan, request: str, hosts: list[Host]) -> ExecutionPlan:
    host_lookup = {host.name: host for host in hosts}
    lower_request = request.casefold()

    for step in plan.steps:
        host = host_lookup[step.host]
        if (
            host.platform == "windows"
            and "powershell" in lower_request
            and "version" in lower_request
            and step.kind == "inspect"
        ):
            step.title = "Get PowerShell version"
            step.command = (
                "$PSVersionTable.PSVersion | "
                "Select-Object Major,Minor,Build,Revision | ConvertTo-Json -Compress"
            )
            step.expected_signal = "JSON object with PowerShell version fields"
            step.validation_type = "powershell_version_json"
            continue

        weak_windows_commands = {"$psversion", "$psversiontable"}
        if host.platform == "windows" and step.command.casefold() in weak_windows_commands:
            step.command = "$PSVersionTable.PSVersion | Format-List *"
            step.expected_signal = step.expected_signal or "Visible PowerShell version output"

    return plan


def _default_host_name(hosts: list[Host]) -> str:
    for host in hosts:
        if host.name == "local-win":
            return host.name
    return hosts[0].name if hosts else ""


def _infer_operation_class(steps: list[PlanStep]) -> str:
    if steps and all(step.kind == "inspect" for step in steps):
        return "inspect"
    return "change"


def create_execution_plan(
    request: str,
    hosts: list[Host],
    config: AppConfig,
    thread: ConversationThread | None = None,
) -> ExecutionPlan:
    if not hosts:
        raise ValueError("No enabled hosts are available for planning.")

    memory = load_workspace_memory()
    history_context = ""
    if memory.history_summaries:
        history_context = "### RECENT HISTORY (FOR CONTEXT):\n" + "\n".join(memory.history_summaries) + "\n\n"

    conversation_context = ""
    if thread and thread.messages:
        conversation_context = "### RECENT CONVERSATION:\n" + thread.format_for_llm() + "\n\n"

    client = OllamaClient(
        model=config.model,
        base_url=config.base_url,
        timeout=config.planner_timeout_seconds,
    )
    user_prompt = json.dumps(
        {
            "request": request,
            "inventory": _inventory_payload(hosts),
        },
        indent=2,
    )
    planner_prompt = history_context + conversation_context + _planner_system_prompt() + "\n\nIMPORTANT: Return ONLY the JSON object. Do not include any conversational filler."
    data = client.generate_json(planner_prompt, user_prompt)
    plan = _normalize_plan(data, hosts)
    plan = _repair_plan(plan, request, hosts)
    plan.raw.setdefault("specialist", "infra-planner")
    definition = get_agent_definition("infra-planner")
    if definition is not None:
        plan.raw.setdefault("agent_title", definition.title)
        plan.raw.setdefault(
            "agent_definition_path",
            str(definition.source_path) if definition.source_path is not None else "",
        )
    if not plan.steps and not plan.missing_information:
        plan.missing_information.append(
            "Planner returned no executable steps. Rephrase the request more concretely."
        )
    return plan
  return plan
