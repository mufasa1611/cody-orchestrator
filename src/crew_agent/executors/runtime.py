from __future__ import annotations

import json
import shlex
import subprocess
import time

from crew_agent.core.models import AppConfig, CommandResult, Host, PlanStep, StepExecutionResult
from crew_agent.policy.gates import guard_command
from crew_agent.policy.validation import validate_step_stdout
from crew_agent.tools.discovery import DiscoveryTool
from crew_agent.tools.file_editor import FileEditorTool
from crew_agent.tools.web_search import WebSearchTool


def _run_command(command: list[str], timeout: int) -> CommandResult:
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1  # Line buffered
        )
        
        stdout_lines = []
        # Stream stdout line by line
        for line in iter(process.stdout.readline, ""):
            trimmed = line.strip()
            if trimmed:
                # Use a special prefix that the UI can detect or just print it
                # For now, we print it with a 'LIVE' tag
                print(f"    [blue]STREAM:[/blue] {trimmed}")
            stdout_lines.append(line)
        
        # Collect remaining output (stderr)
        _, stderr = process.communicate(timeout=timeout)
        
        return CommandResult(
            returncode=process.returncode,
            stdout="".join(stdout_lines).strip(),
            stderr=stderr.strip(),
        )
    except subprocess.TimeoutExpired:
        process.kill()
        return CommandResult(1, "", "Command timed out")
    except Exception as e:
        return CommandResult(1, "", f"Execution failed: {e}")


def _execute_windows_local(command: str, timeout: int) -> CommandResult:
    return _run_command(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        timeout=timeout,
    )


def _execute_windows_winrm(host: Host, command: str, timeout: int) -> CommandResult:
    target = host.address or host.name
    wrapped = f"Invoke-Command -ComputerName {target} -ScriptBlock {{ {command} }}"
    return _execute_windows_local(wrapped, timeout)


def _execute_linux_ssh(host: Host, command: str, timeout: int, connect_timeout: int) -> CommandResult:
    target = f"{host.user}@{host.address or host.name}" if host.user else (host.address or host.name)
    ssh_command = [
        "ssh",
        "-o",
        f"ConnectTimeout={connect_timeout}",
    ]
    if host.port is not None:
        ssh_command.extend(["-p", str(host.port)])
    ssh_command.extend([target, "bash", "-lc", shlex.quote(command)])
    return _run_command(ssh_command, timeout=timeout)


def _execute_linux_local(host: Host, command: str, timeout: int) -> CommandResult:
    shell = host.shell or "bash"
    if shell.lower() == "wsl":
        return _run_command(["wsl.exe", "-e", "bash", "-lc", command], timeout=timeout)
    return _run_command([shell, "-lc", command], timeout=timeout)


def _execute_edit(command: str) -> CommandResult:
    try:
        data = json.loads(command)
        file_path = data.get("file_path")
        old_string = data.get("old_string")
        new_string = data.get("new_string")
        if not all([file_path, old_string, new_string]):
            return CommandResult(1, "", "Error: 'edit' JSON missing file_path, old_string, or new_string")
        
        tool = FileEditorTool()
        result = tool._run(file_path=file_path, old_string=old_string, new_string=new_string)
        if result.startswith("Successfully"):
            return CommandResult(0, result, "")
        return CommandResult(1, "", result)
    except json.JSONDecodeError:
        return CommandResult(1, "", "Error: 'edit' step command must be a valid JSON object")


def _execute_web_search(query: str) -> CommandResult:
    tool = WebSearchTool()
    result = tool._run(query=query)
    if result.startswith("Error"):
        return CommandResult(1, "", result)
    return CommandResult(0, result, "")


def _execute_discovery(subnet: str | None = None) -> CommandResult:
    tool = DiscoveryTool()
    result = tool._run(subnet=subnet)
    if result.startswith("Error"):
        return CommandResult(1, "", result)
    return CommandResult(0, result, "")


def execute_plan_step(
    step: PlanStep,
    host: Host,
    config: AppConfig,
    permission_mode: str = "safe",
) -> StepExecutionResult:
    started = time.perf_counter()

    if step.kind == "edit":
        primary = _execute_edit(step.command)
    elif step.kind == "web_search":
        primary = _execute_web_search(step.command)
    elif step.kind == "discovery":
        # Note: subnet could be parsed from step.command if we wanted more precision
        primary = _execute_discovery()
    else:
        guard_command(host, step.command, permission_mode=permission_mode)
        if host.platform == "windows" and host.transport == "local":
            primary = _execute_windows_local(step.command, config.command_timeout_seconds)
        elif host.platform == "windows" and host.transport == "winrm":
            primary = _execute_windows_winrm(host, step.command, config.command_timeout_seconds)
        elif host.platform == "linux" and host.transport == "ssh":
            primary = _execute_linux_ssh(
                host,
                step.command,
                config.command_timeout_seconds,
                config.ssh_connect_timeout_seconds,
            )
        elif host.platform == "linux" and host.transport == "local":
            primary = _execute_linux_local(host, step.command, config.command_timeout_seconds)
        else:
            raise ValueError(
                f"Unsupported execution path for host '{host.name}': "
                f"{host.platform}/{host.transport}"
            )

    verify: CommandResult | None = None
    if primary.returncode == 0 and step.verify_command:
        guard_command(host, step.verify_command, permission_mode=permission_mode)
        if host.platform == "windows" and host.transport == "local":
            verify = _execute_windows_local(step.verify_command, config.command_timeout_seconds)
        elif host.platform == "windows" and host.transport == "winrm":
            verify = _execute_windows_winrm(host, step.verify_command, config.command_timeout_seconds)
        elif host.platform == "linux" and host.transport == "ssh":
            verify = _execute_linux_ssh(
                host,
                step.verify_command,
                config.command_timeout_seconds,
                config.ssh_connect_timeout_seconds,
            )
        elif host.platform == "linux" and host.transport == "local":
            verify = _execute_linux_local(host, step.verify_command, config.command_timeout_seconds)

    duration = time.perf_counter() - started
    validation_error = None
    if primary.returncode == 0 or step.accept_nonzero_returncode:
        validation_source = verify.stdout if verify is not None else primary.stdout
        validation_error = validate_step_stdout(step, validation_source)
    success = (
        (primary.returncode == 0 or step.accept_nonzero_returncode)
        and (verify is None or verify.returncode == 0)
        and validation_error is None
    )
    return StepExecutionResult(
        step_id=step.id,
        host=host.name,
        title=step.title,
        command=step.command,
        success=success,
        returncode=primary.returncode,
        stdout=primary.stdout,
        stderr=primary.stderr,
        verify=verify,
        duration_seconds=duration,
        validation_type=step.validation_type,
        artifact_path=_extract_artifact_path(
            verify.stdout if verify is not None else primary.stdout,
            step.validation_type,
        ),
        validation_error=validation_error,
    )


def execute_host_command(
    host: Host,
    command: str,
    config: AppConfig,
    permission_mode: str = "full",
) -> CommandResult:
    guard_command(host, command, permission_mode=permission_mode)
    if host.platform == "windows" and host.transport == "local":
        return _execute_windows_local(command, config.command_timeout_seconds)
    if host.platform == "windows" and host.transport == "winrm":
        return _execute_windows_winrm(host, command, config.command_timeout_seconds)
    if host.platform == "linux" and host.transport == "ssh":
        return _execute_linux_ssh(
            host,
            command,
            config.command_timeout_seconds,
            config.ssh_connect_timeout_seconds,
        )
    if host.platform == "linux" and host.transport == "local":
        return _execute_linux_local(host, command, config.command_timeout_seconds)
    raise ValueError(
        f"Unsupported execution path for host '{host.name}': "
        f"{host.platform}/{host.transport}"
    )


def _extract_artifact_path(stdout: str, validation_type: str | None) -> str | None:
    if validation_type not in {"workspace_file_info_json", "workspace_file_contains_json"} or not stdout:
        return None
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    path = payload.get("Path")
    return str(path).strip() if path else None
