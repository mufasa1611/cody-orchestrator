from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from crew_agent.agents import get_agent_definition
from crew_agent.core.memory import build_memo_content, load_workspace_memory
from crew_agent.core.models import ExecutionPlan, Host, PlanStep


class WorkspaceTarget(NamedTuple):
    directory_expr: str
    location_label: str
    continue_on_failure: bool = False


def build_workspace_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    lowered = " ".join(request.casefold().split())
    windows_hosts = [host for host in hosts if host.platform == "windows" and host.transport == "local"]
    if not windows_hosts:
        return None

    memo_plan = _build_memo_plan(request, lowered, windows_hosts)
    if memo_plan is not None:
        return memo_plan

    file_edit_plan = _build_local_file_insert_plan(request, lowered, windows_hosts)
    if file_edit_plan is not None:
        return file_edit_plan

    file_plan = _build_local_file_create_plan(request, lowered, windows_hosts)
    if file_plan is not None:
        return file_plan

    return None


def _build_memo_plan(request: str, lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not _looks_like_memo_write(lowered):
        return None

    filename = _extract_filename(request) or "memo.md"
    if filename.casefold() != "memo.md" or not _is_safe_workspace_filename(filename):
        return None

    content = build_memo_content(request=request, existing=load_workspace_memory())
    command = _powershell_write_file_command(filename, content)
    verify_command = (
        f"if (Test-Path -LiteralPath '{_ps_quote(filename)}') {{ "
        f"Get-Content -LiteralPath '{_ps_quote(filename)}' -Raw "
        f"}} else {{ exit 1 }}"
    )
    return ExecutionPlan(
        summary=f"Create or update workspace file {filename}.",
        planner_notes=["matched built-in workspace memo handler"],
        risk="low",
        domain="workspace",
        operation_class="write_text",
        requires_confirmation=False,
        requires_unsafe=False,
        missing_information=[],
        target_hosts=[host.name for host in hosts],
        steps=[
            PlanStep(
                id="workspace-memo-1",
                title=f"Write {filename}",
                host=hosts[0].name,
                kind="change",
                rationale="Handled by Cody's built-in workspace memo writer.",
                command=command,
                verify_command=verify_command,
                expected_signal=f"{filename} exists and contains the expected text",
                validation_type="workspace_text_file",
            )
        ],
        raw={
            "builtin": True,
            "handler": "workspace_memo_write",
            "filename": filename,
            "specialist": "memory-keeper",
        },
    )


def _build_local_file_create_plan(request: str, lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not _looks_like_local_file_create(lowered):
        return None

    target_dir_expr, target_dir_label = _extract_target_directory(lowered)
    filename = _extract_target_filename(request, lowered)
    if not filename:
        return None

    command = _powershell_create_file_command(filename, target_dir_expr)
    verify_command = _powershell_file_info_command(filename, target_dir_expr)
    return ExecutionPlan(
        summary=f"Create file {filename} in {target_dir_label}.",
        planner_notes=["matched built-in local file creation handler"],
        risk="low",
        domain="workspace",
        operation_class="write_text",
        requires_confirmation=False,
        requires_unsafe=False,
        missing_information=[],
        target_hosts=[host.name for host in hosts],
        steps=[
            PlanStep(
                id="workspace-file-1",
                title=f"Create {filename}",
                host=hosts[0].name,
                kind="change",
                rationale="Handled by Cody's built-in local file creation handler.",
                command=command,
                verify_command=verify_command,
                expected_signal=f"{filename} exists in {target_dir_label}",
                validation_type="workspace_file_info_json",
            )
        ],
        raw={
            "builtin": True,
            "handler": "workspace_file_create",
            "filename": filename,
            "target_dir": target_dir_label,
            "specialist": "workspace-operator",
        },
    )


def _build_local_file_insert_plan(request: str, lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not _looks_like_local_file_edit(lowered):
        return None

    filename = _extract_target_filename(request, lowered)
    inserted_text = _extract_inserted_text(request)
    if not filename or not inserted_text:
        return None

    targets = _extract_insert_targets(lowered)
    if not targets:
        return None

    steps: list[PlanStep] = []
    for index, target in enumerate(targets, start=1):
        steps.append(
            PlanStep(
                id=f"workspace-file-insert-{index}",
                title=f"Insert text into {filename} in {target.location_label}",
                host=hosts[0].name,
                kind="change",
                rationale="Handled by Cody's built-in workspace file edit handler.",
                command=_powershell_insert_text_command(filename, target.directory_expr, inserted_text),
                expected_signal=f"{filename} contains the inserted text",
                validation_type="workspace_file_contains_json",
                continue_on_failure=target.continue_on_failure,
            )
        )

    summary = (
        f"Insert text into {filename} in {targets[0].location_label}."
        if len(targets) == 1
        else f"Insert text into {filename} by checking {', '.join(target.location_label for target in targets)}."
    )
    return ExecutionPlan(
        summary=summary,
        planner_notes=[
            "matched built-in workspace edit handler",
            f"workflow={_agent_workflow_strategy('workspace-operator', 'verified_workspace_change')}",
        ],
        risk="low",
        domain="workspace",
        operation_class="write_text",
        requires_confirmation=False,
        requires_unsafe=False,
        missing_information=[],
        target_hosts=[host.name for host in hosts],
        steps=steps,
        raw={
            "builtin": True,
            "handler": "workspace_file_insert",
            "filename": filename,
            "target_dir": targets[0].location_label if len(targets) == 1 else "fallback search",
            "inserted_text": inserted_text,
            "specialist": "workspace-operator",
            "stop_after_first_success": True,
        },
    )


def _looks_like_memo_write(lowered: str) -> bool:
    write_terms = ("create", "write", "save", "make", "remember", "note down", "keep")
    memo_terms = ("memo", "memory", "memo.md")
    return any(term in lowered for term in write_terms) and any(term in lowered for term in memo_terms)


def _looks_like_local_file_create(lowered: str) -> bool:
    create_terms = ("create", "make", "write", "save")
    file_terms = ("file", "text file", "txt file", "document")
    return any(term in lowered for term in create_terms) and any(term in lowered for term in file_terms)


def _looks_like_local_file_edit(lowered: str) -> bool:
    edit_terms = ("insert", "append", "add", "write", "put", "edit", "modify", "replace")
    file_terms = ("file", "text file", "txt file", "document", ".txt", ".md")
    return any(term in lowered for term in edit_terms) and any(term in lowered for term in file_terms)


def _extract_filename(request: str) -> str | None:
    match = re.search(r"([A-Za-z0-9._-]+\.(?:md|txt))", request, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    return None


def _extract_target_filename(request: str, lowered: str) -> str | None:
    explicit = _extract_filename(request)
    if explicit:
        return explicit

    quoted_match = re.search(
        r"(?:name(?:\s+it)?|call(?:\s+it)?|named)\s+['\"]?([A-Za-z0-9._ -]+?)['\"]?(?:\s+in|\s+under|\s*$)",
        request,
        flags=re.IGNORECASE,
    )
    if quoted_match:
        base = _sanitize_filename(quoted_match.group(1))
        if base:
            return _apply_default_extension(base, lowered)

    bare_match = re.search(r"\bname\s+it\s+([A-Za-z0-9._-]+)\b", lowered, flags=re.IGNORECASE)
    if bare_match:
        base = _sanitize_filename(bare_match.group(1))
        if base:
            return _apply_default_extension(base, lowered)

    named_match = re.search(r"\bnamed\s+([A-Za-z0-9._-]+)\b", lowered, flags=re.IGNORECASE)
    if named_match:
        base = _sanitize_filename(named_match.group(1))
        if base:
            return _apply_default_extension(base, lowered)

    direct_match = re.search(
        r"\b(?:text\s+file|txt\s+file|file)\s+([A-Za-z0-9._-]+)(?:\s+in|\s+under|\s*$)",
        lowered,
        flags=re.IGNORECASE,
    )
    if direct_match:
        base = _sanitize_filename(direct_match.group(1))
        if base:
            return _apply_default_extension(base, lowered)

    return None


def _extract_inserted_text(request: str) -> str | None:
    patterns = (
        r"\b(?:insert|append|add|write|put)\s+['\"]?(.+?)['\"]?\s+(?:in|into)\s+(?:the\s+)?(?:text\s+)?file\b",
        r"\b(?:insert|append|add|write|put)\s+['\"]?(.+?)['\"]?\s+(?:to)\s+(?:the\s+)?(?:text\s+)?file\b",
        r"\bedit\b.*?\b(?:and|to)\s+insert\s*\(?\s*['\"]?(.+?)['\"]?\s*\)?\s*$",
        r"\b(?:insert|append|add|write|put)\s*\(?\s*['\"]?(.+?)['\"]?\s*\)?\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, request, flags=re.IGNORECASE)
        if match:
            text = match.group(1).strip().strip("'\"").strip()
            text = text.strip("()[]{}").strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                return text
    return None


def _extract_target_directory(lowered: str) -> tuple[str, str]:
    if any(
        phrase in lowered
        for phrase in (
            "documents folder",
            "document folder",
            "documents",
            "docuiments folder",
            "docuiments",
            "documints",
        )
    ):
        return "[Environment]::GetFolderPath('MyDocuments')", "Documents"
    if "desktop" in lowered:
        return "[Environment]::GetFolderPath('Desktop')", "Desktop"
    if "downloads" in lowered:
        return "Join-Path $env:USERPROFILE 'Downloads'", "Downloads"
    return "(Get-Location).Path", "current folder"


def _extract_insert_targets(lowered: str) -> list[WorkspaceTarget]:
    named_location = _extract_named_location(lowered)
    if named_location is not None:
        directory_expr, location_label = named_location
        return [WorkspaceTarget(directory_expr=directory_expr, location_label=location_label)]

    if _agent_workflow_strategy("workspace-operator", "verified_workspace_change") != "sequential_fallback_edit":
        return [WorkspaceTarget(directory_expr="(Get-Location).Path", location_label="current folder")]

    targets: list[WorkspaceTarget] = []
    continue_on_failure = _agent_workflow_bool("workspace-operator", "continue_on_failure", True)
    for location_name in _agent_list_policy(
        "workspace-operator",
        "fallback_locations",
        ("workspace", "documents", "desktop", "downloads"),
    ):
        location = _resolve_location_name(location_name)
        if location is None:
            continue
        directory_expr, location_label = location
        targets.append(
            WorkspaceTarget(
                directory_expr=directory_expr,
                location_label=location_label,
                continue_on_failure=continue_on_failure,
            )
        )
    if targets:
        targets[-1] = WorkspaceTarget(
            directory_expr=targets[-1].directory_expr,
            location_label=targets[-1].location_label,
            continue_on_failure=False,
        )
    return targets


def _extract_named_location(lowered: str) -> tuple[str, str] | None:
    if any(
        phrase in lowered
        for phrase in (
            "documents folder",
            "document folder",
            "documents",
            "docuiments folder",
            "docuiments",
            "documints",
        )
    ):
        return "[Environment]::GetFolderPath('MyDocuments')", "Documents"
    if "desktop folder" in lowered or "desktop" in lowered:
        return "[Environment]::GetFolderPath('Desktop')", "Desktop"
    if "downloads folder" in lowered or "downloads" in lowered:
        return "Join-Path $env:USERPROFILE 'Downloads'", "Downloads"
    return None


def _resolve_location_name(name: str) -> tuple[str, str] | None:
    lowered = name.casefold()
    if lowered == "workspace":
        return "(Get-Location).Path", "current folder"
    if lowered == "documents":
        return "[Environment]::GetFolderPath('MyDocuments')", "Documents"
    if lowered == "desktop":
        return "[Environment]::GetFolderPath('Desktop')", "Desktop"
    if lowered == "downloads":
        return "Join-Path $env:USERPROFILE 'Downloads'", "Downloads"
    return None


def _sanitize_filename(value: str) -> str:
    cleaned = value.strip().strip("'\"").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.rstrip(".")
    cleaned = cleaned.replace("/", "-").replace("\\", "-").replace(":", "-")
    return cleaned


def _apply_default_extension(base: str, lowered: str) -> str:
    if "." in Path(base).name:
        return base
    if "markdown" in lowered or "md file" in lowered:
        return f"{base}.md"
    return f"{base}.txt"


def _is_safe_workspace_filename(filename: str) -> bool:
    path = Path(filename)
    return not path.is_absolute() and path.parent == Path(".")


def _powershell_write_file_command(filename: str, content: str) -> str:
    escaped_content = _ps_here_string(content)
    escaped_filename = _ps_quote(filename)
    return (
        f"$content = {escaped_content}; "
        f"Set-Content -LiteralPath '{escaped_filename}' -Value $content -Encoding utf8"
    )


def _powershell_create_file_command(filename: str, directory_expr: str) -> str:
    escaped_filename = _ps_quote(filename)
    return (
        f"$dir = {directory_expr}; "
        f"$path = Join-Path $dir '{escaped_filename}'; "
        "if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }; "
        "if (-not (Test-Path -LiteralPath $path)) { New-Item -ItemType File -Path $path -Force | Out-Null }; "
        "@{"
        "Path = $path; "
        "Name = [System.IO.Path]::GetFileName($path); "
        "Parent = [System.IO.Path]::GetDirectoryName($path); "
        "Exists = (Test-Path -LiteralPath $path)"
        "} | ConvertTo-Json -Compress"
    )


def _powershell_file_info_command(filename: str, directory_expr: str) -> str:
    escaped_filename = _ps_quote(filename)
    return (
        f"$dir = {directory_expr}; "
        f"$path = Join-Path $dir '{escaped_filename}'; "
        "@{"
        "Path = $path; "
        "Name = [System.IO.Path]::GetFileName($path); "
        "Parent = [System.IO.Path]::GetDirectoryName($path); "
        "Exists = (Test-Path -LiteralPath $path)"
        "} | ConvertTo-Json -Compress"
    )


def _powershell_insert_text_command(filename: str, directory_expr: str, inserted_text: str) -> str:
    escaped_filename = _ps_quote(filename)
    escaped_inserted_text = _ps_quote(inserted_text)
    return (
        f"$dir = {directory_expr}; "
        f"$path = Join-Path $dir '{escaped_filename}'; "
        f"$insert = '{escaped_inserted_text}'; "
        "if (-not (Test-Path -LiteralPath $path)) { Write-Error \"File not found: $path\"; exit 1 }; "
        "$existing = Get-Content -LiteralPath $path -Raw; "
        "if ([string]::IsNullOrWhiteSpace($existing)) { "
        "  Set-Content -LiteralPath $path -Value $insert -Encoding utf8 "
        "} else { "
        "  Add-Content -LiteralPath $path -Value $insert -Encoding utf8 "
        "}; "
        "$updated = Get-Content -LiteralPath $path -Raw; "
        "@{"
        "Path = $path; "
        "Name = [System.IO.Path]::GetFileName($path); "
        "Parent = [System.IO.Path]::GetDirectoryName($path); "
        "Exists = (Test-Path -LiteralPath $path); "
        "InsertedText = $insert; "
        "ContainsExpected = $updated -like ('*' + $insert + '*')"
        "} | ConvertTo-Json -Compress"
    )


def _ps_here_string(content: str) -> str:
    sanitized = content.replace("@'", "@ ''")
    return "@'\n" + sanitized + "\n'@"


def _ps_quote(text: str) -> str:
    return text.replace("'", "''")


def _agent_definition(name: str):
    return get_agent_definition(name)


def _agent_list_policy(name: str, key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    definition = _agent_definition(name)
    value = (definition.policy or {}).get(key) if definition is not None else None
    if isinstance(value, list):
        items = tuple(str(item).strip() for item in value if str(item).strip())
        if items:
            return items
    return default


def _agent_workflow_strategy(name: str, default: str) -> str:
    definition = _agent_definition(name)
    value = (definition.workflow or {}).get("strategy") if definition is not None else None
    return str(value).strip() if value else default


def _agent_workflow_bool(name: str, key: str, default: bool) -> bool:
    definition = _agent_definition(name)
    value = (definition.workflow or {}).get(key) if definition is not None else None
    return bool(value) if isinstance(value, bool) else default
