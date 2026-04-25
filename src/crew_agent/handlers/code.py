from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from crew_agent.agents import get_agent_definition
from crew_agent.core.models import ExecutionPlan, Host, PlanStep


class FileTarget(NamedTuple):
    path: str
    location_label: str
    read_command: str
    continue_on_failure: bool = False


def build_code_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    lowered = " ".join(request.casefold().split())
    local_hosts = [host for host in hosts if host.transport == "local"]
    if not local_hosts:
        return None

    read_plan = _build_file_read_plan(request, lowered, local_hosts)
    if read_plan is not None:
        return read_plan

    search_plan = _build_text_search_plan(request, lowered, local_hosts)
    if search_plan is not None:
        return search_plan

    file_search_plan = _build_file_search_plan(request, lowered, local_hosts)
    if file_search_plan is not None:
        return file_search_plan

    list_plan = _build_file_list_plan(lowered, local_hosts)
    if list_plan is not None:
        return list_plan

    git_plan = _build_git_status_plan(lowered, local_hosts)
    if git_plan is not None:
        return git_plan

    test_plan = _build_test_plan(request, lowered, local_hosts)
    if test_plan is not None:
        return test_plan

    return None


def _build_file_read_plan(request: str, lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not any(term in lowered for term in ("read ", "show ", "open ", "display ", "print ")):
        return None

    targets = _extract_file_targets(request, lowered)
    if not targets:
        return None

    return _build_file_read_inspect_plan(hosts, targets)


def _build_text_search_plan(request: str, lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not any(term in lowered for term in ("search for", "find ", "grep ", "look for", "where is", "search codebase", "search repo")):
        return None

    if any(term in lowered for term in ("file named", "filename", "file name", "files named")):
        return None

    pattern = _extract_search_pattern(request)
    if not pattern:
        return None

    command = _powershell_search_text_command(pattern, max_results=_agent_int_policy("repo-searcher", "max_results", 100))
    return _single_code_inspect_plan(
        hosts,
        summary=f"Search the repository for '{pattern}'.",
        title=f"Search for {pattern}",
        command=command,
        expected_signal="Search hits or an explicit no-match message",
        validation_type="repo_search_text",
        handler="repo_text_search",
        specialist="repo-searcher",
    )


def _build_file_search_plan(request: str, lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not any(term in lowered for term in ("find file", "search file", "file named", "filename", "file name", "files named")):
        return None

    name = _extract_file_search_name(request)
    if not name:
        return None

    command = _powershell_search_file_command(name)
    command = _powershell_search_file_command(name, max_results=_agent_int_policy("repo-searcher", "max_results", 100))
    return _single_code_inspect_plan(
        hosts,
        summary=f"Find repository files matching {name}.",
        title=f"Find file {name}",
        command=command,
        expected_signal="Matching file paths or an explicit no-match message",
        validation_type="repo_file_list_text",
        handler="repo_file_search",
        specialist="repo-searcher",
    )


def _build_file_list_plan(lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not any(
        phrase in lowered
        for phrase in (
            "list files",
            "show files",
            "repo files",
            "repository files",
            "codebase files",
            "project files",
            "tree of files",
        )
    ):
        return None

    command = _powershell_list_files_command(max_results=_agent_int_policy("repo-searcher", "max_results", 200))
    return _single_code_inspect_plan(
        hosts,
        summary="List repository files.",
        title="List repository files",
        command=command,
        expected_signal="A file list for the current repository",
        validation_type="repo_file_list_text",
        handler="repo_file_list",
        specialist="repo-searcher",
    )


def _build_git_status_plan(lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not any(phrase in lowered for phrase in ("git status", "changed files", "what changed", "show diff status")):
        return None

    command = _powershell_git_status_command()
    return _single_code_inspect_plan(
        hosts,
        summary="Inspect the local git working tree status.",
        title="Show git status",
        command=command,
        expected_signal="Git status output or a clear not-a-repo message",
        validation_type="git_status_text",
        handler="git_status",
        specialist="repo-inspector",
    )


def _build_test_plan(request: str, lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not _looks_like_test_request(lowered):
        return None

    target = _extract_test_target(request)
    command = _powershell_test_command(target)
    target_suffix = f" for {target}" if target else ""
    return _single_code_inspect_plan(
        hosts,
        summary=f"Run repository tests{target_suffix}.",
        title=f"Run tests{target_suffix}",
        command=command,
        expected_signal="A test summary showing passed or failed counts",
        validation_type="test_run_text",
        handler="test_run",
        specialist="test-runner",
        accept_nonzero_returncode=_agent_bool_policy("test-runner", "accept_nonzero_returncode", True),
    )


def _single_code_inspect_plan(
    hosts: list[Host],
    summary: str,
    title: str,
    command: str,
    expected_signal: str,
    validation_type: str,
    handler: str,
    specialist: str,
    accept_nonzero_returncode: bool = False,
) -> ExecutionPlan:
    steps = [
        PlanStep(
            id=f"code-{handler}-{index}",
            title=title,
            host=host.name,
            kind="inspect",
            rationale="Handled by Cody's built-in coding assistant handler.",
            command=command,
            expected_signal=expected_signal,
            validation_type=validation_type,
            accept_nonzero_returncode=accept_nonzero_returncode,
        )
        for index, host in enumerate(hosts, start=1)
    ]
    return ExecutionPlan(
        summary=summary,
        planner_notes=["matched built-in coding handler"],
        risk="low",
        domain="code",
        operation_class="inspect",
        requires_confirmation=False,
        requires_unsafe=False,
        missing_information=[],
        target_hosts=[host.name for host in hosts],
        steps=steps,
        raw={"builtin": True, "handler": handler, "specialist": specialist},
    )


def _build_file_read_inspect_plan(hosts: list[Host], targets: list[FileTarget]) -> ExecutionPlan:
    path = targets[0].path
    summary = (
        f"Read file {path} from {targets[0].location_label}."
        if len(targets) == 1
        else f"Read file {path} by checking {', '.join(target.location_label for target in targets)}."
    )
    steps: list[PlanStep] = []
    counter = 1
    for host in hosts:
        for target in targets:
            steps.append(
                PlanStep(
                    id=f"code-repo_file_read-{counter}",
                    title=f"Read {target.path} from {target.location_label}",
                    host=host.name,
                    kind="inspect",
                    rationale="Handled by Cody's built-in coding assistant handler.",
                    command=target.read_command,
                    expected_signal=f"File contents for {target.path}",
                    validation_type="repo_file_text",
                    continue_on_failure=target.continue_on_failure,
                )
            )
            counter += 1
    return ExecutionPlan(
        summary=summary,
        planner_notes=["matched built-in coding handler", f"workflow={_agent_workflow_strategy('file-reader', 'single_step_read')}"],
        risk="low",
        domain="code",
        operation_class="inspect",
        requires_confirmation=False,
        requires_unsafe=False,
        missing_information=[],
        target_hosts=[host.name for host in hosts],
        steps=steps,
        raw={
            "builtin": True,
            "handler": "repo_file_read",
            "specialist": "file-reader",
            "stop_after_first_success": True,
        },
    )


def _extract_file_targets(request: str, lowered: str) -> list[FileTarget]:
    path = _extract_repo_path(request)
    if not path:
        return []

    if Path(path).parent != Path("."):
        return [
            FileTarget(
                path=path,
                location_label="the current workspace",
                read_command=_powershell_read_file_command(path, preview_lines=_agent_int_policy("file-reader", "preview_lines", 250)),
            )
        ]

    named_location = _extract_named_location(lowered)
    if named_location is not None:
        directory_expr, location_label = named_location
        return [
            FileTarget(
                path=path,
                location_label=location_label,
                read_command=_powershell_read_file_command(
                    path,
                    directory_expr=directory_expr,
                    preview_lines=_agent_int_policy("file-reader", "preview_lines", 250),
                ),
            )
        ]

    workflow_strategy = _agent_workflow_strategy("file-reader", "single_step_read")
    if workflow_strategy != "sequential_fallback_read":
        return [
            FileTarget(
                path=path,
                location_label="the current workspace",
                read_command=_powershell_read_file_command(path, preview_lines=_agent_int_policy("file-reader", "preview_lines", 250)),
            )
        ]

    targets: list[FileTarget] = []
    continue_on_failure = _agent_workflow_bool("file-reader", "continue_on_failure", True)
    for location_name in _agent_list_policy(
        "file-reader",
        "fallback_locations",
        ("workspace", "documents", "desktop", "downloads"),
    ):
        location = _resolve_location_name(location_name)
        if location is None:
            continue
        directory_expr, location_label = location
        targets.append(
            FileTarget(
                path=path,
                location_label=location_label,
                read_command=_powershell_read_file_command(
                    path,
                    directory_expr=directory_expr,
                    preview_lines=_agent_int_policy("file-reader", "preview_lines", 250),
                ),
                continue_on_failure=continue_on_failure,
            )
        )
    if targets:
        targets[-1] = FileTarget(
            path=targets[-1].path,
            location_label=targets[-1].location_label,
            read_command=targets[-1].read_command,
            continue_on_failure=False,
        )
    return targets


def _extract_repo_path(request: str) -> str | None:
    patterns = (
        r"(?:(?:read|show|open|display|print)\s+)([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)",
        r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, request, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip().strip("'\"")
        safe = _sanitize_repo_relative_path(candidate)
        if safe:
            return safe
    return None


def _extract_search_pattern(request: str) -> str | None:
    quoted = re.search(r"['\"]([^'\"]{2,200})['\"]", request)
    if quoted:
        return quoted.group(1).strip()

    patterns = (
        r"(?:search for|look for|grep for|find)\s+(.+?)(?:\s+in\s+(?:the\s+)?(?:repo|repository|code|codebase)|\s*$)",
        r"(?:where is)\s+(.+?)(?:\s+used|\s+defined|\s+declared|\s*$)",
    )
    for pattern in patterns:
        match = re.search(pattern, request, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip().strip("'\"")
        if candidate and len(candidate) <= 200 and "/" not in candidate and "\\" not in candidate:
            return candidate
    return None


def _extract_file_search_name(request: str) -> str | None:
    match = re.search(
        r"(?:find|search)\s+(?:for\s+)?(?:file|files)\s+(?:named\s+)?([A-Za-z0-9._/-]+)",
        request,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip().strip("'\"")
    return None


def _extract_test_target(request: str) -> str | None:
    patterns = (
        r"(tests?[\\/][A-Za-z0-9_./\\-]+\.py)",
        r"\b([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, request, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).strip().strip("'\"")
        if candidate:
            return candidate
    return None


def _looks_like_test_request(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "run tests",
            "run the tests",
            "run unit tests",
            "run test suite",
            "execute tests",
            "pytest",
            "unittest",
            "test file",
            "test module",
            "failing tests",
        )
    )


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


def _resolve_location_name(name: str) -> tuple[str | None, str] | None:
    lowered = name.casefold()
    if lowered == "workspace":
        return None, "the current workspace"
    if lowered == "documents":
        return "[Environment]::GetFolderPath('MyDocuments')", "Documents"
    if lowered == "desktop":
        return "[Environment]::GetFolderPath('Desktop')", "Desktop"
    if lowered == "downloads":
        return "Join-Path $env:USERPROFILE 'Downloads'", "Downloads"
    return None


def _sanitize_repo_relative_path(path: str) -> str | None:
    candidate = path.strip().replace("/", "\\")
    if not candidate or Path(candidate).is_absolute():
        return None
    normalized_parts = Path(candidate).parts
    if any(part == ".." for part in normalized_parts):
        return None
    return str(Path(*normalized_parts))


def _powershell_read_file_command(path: str, directory_expr: str | None = None, preview_lines: int = 250) -> str:
    escaped_path = _ps_quote(path)
    if directory_expr is not None:
        path_expr = f"Join-Path ({directory_expr}) '{escaped_path}'"
    else:
        path_expr = f"'{escaped_path}'"
    return (
        f"$path = {path_expr}; "
        "if (-not (Test-Path -LiteralPath $path)) { Write-Error \"File not found: $path\"; exit 1 }; "
        "Write-Output (\"FILE: \" + (Resolve-Path -LiteralPath $path)); "
        f"Get-Content -LiteralPath $path -TotalCount {max(1, preview_lines)}"
    )


def _powershell_search_text_command(pattern: str, max_results: int) -> str:
    escaped_pattern = _ps_quote(pattern)
    return (
        f"$pattern = '{escaped_pattern}'; "
        "$rg = Get-Command rg -ErrorAction SilentlyContinue; "
        "if ($rg) { "
        "  $hits = @(rg --line-number --no-heading --color never --fixed-strings --smart-case --context 2 --max-columns 500 --glob !.git/** --glob !venv/** --glob !.venv/** --glob !__pycache__/** -- $pattern .); "
        "} else { "
        "  $hits = @(Get-ChildItem -Recurse -File | "
        "    Where-Object { $_.FullName -notmatch '\\\\(\\.git|venv|\\.venv|__pycache__)\\\\' } | "
        "    Select-String -SimpleMatch -Pattern $pattern | "
        "    ForEach-Object { \"{0}:{1}:{2}\" -f $_.Path, $_.LineNumber, $_.Line.Trim() }); "
        "} "
        "if (-not $hits -or $hits.Count -eq 0) { Write-Output 'No matches found.'; exit 0 }; "
        f"$hits | Select-Object -First {max(1, max_results)}"
    )


def _powershell_search_file_command(name: str, max_results: int) -> str:
    escaped_name = _ps_quote(name)
    return (
        f"$name = '{escaped_name}'; "
        "$rg = Get-Command rg -ErrorAction SilentlyContinue; "
        "if ($rg) { "
        "  $hits = @(rg --files --glob !.git/** --glob !venv/** --glob !.venv/** --glob !__pycache__/** | "
        "    Select-String -SimpleMatch -Pattern $name | ForEach-Object { $_.Line }); "
        "} else { "
        "  $hits = @(Get-ChildItem -Recurse -File | "
        "    Where-Object { $_.FullName -notmatch '\\\\(\\.git|venv|\\.venv|__pycache__)\\\\' -and $_.Name -like ('*' + $name + '*') } | "
        "    ForEach-Object { $_.FullName }); "
        "} "
        "if (-not $hits -or $hits.Count -eq 0) { Write-Output 'No matching files found.'; exit 0 }; "
        f"$hits | Select-Object -First {max(1, max_results)}"
    )


def _powershell_list_files_command(max_results: int) -> str:
    return (
        "$rg = Get-Command rg -ErrorAction SilentlyContinue; "
        "if ($rg) { "
        "  $files = @(rg --files --glob !.git/** --glob !venv/** --glob !.venv/** --glob !__pycache__/**); "
        "} else { "
        "  $files = @(Get-ChildItem -Recurse -File | "
        "    Where-Object { $_.FullName -notmatch '\\\\(\\.git|venv|\\.venv|__pycache__)\\\\' } | "
        "    ForEach-Object { $_.FullName }); "
        "} "
        "if (-not $files -or $files.Count -eq 0) { Write-Output 'No files found.'; exit 0 }; "
        f"$files | Select-Object -First {max(1, max_results)}"
    )


def _powershell_git_status_command() -> str:
    return (
        "if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Output 'git is not available.'; exit 0 }; "
        "if (-not (Test-Path -LiteralPath '.git')) { Write-Output 'Not a git repository.'; exit 0 }; "
        "$status = @(git status --short); "
        "if (-not $status -or $status.Count -eq 0) { Write-Output 'Working tree clean.'; exit 0 }; "
        "$status"
    )


def _powershell_test_command(target: str | None) -> str:
    escaped_target = _ps_quote(target) if target else ""
    target_block = (
        (
            f"$target = '{escaped_target}'; "
            "if ($target -like '*.py' -and (Test-Path -LiteralPath $target)) { "
            "  $candidate = ($target -replace '/', '\\'); "
            "  & $python -m unittest $candidate 2>&1; "
            "  exit $LASTEXITCODE; "
            "} "
            "if ($target) { "
            "  & $python -m unittest $target 2>&1; "
            "  exit $LASTEXITCODE; "
            "} "
        )
        if target
        else ""
    )
    return (
        "$python = $null; "
        "if (Test-Path -LiteralPath 'venv\\Scripts\\python.exe') { $python = 'venv\\Scripts\\python.exe' } "
        "elseif (Test-Path -LiteralPath '.venv\\Scripts\\python.exe') { $python = '.venv\\Scripts\\python.exe' } "
        "elseif (Get-Command python -ErrorAction SilentlyContinue) { $python = 'python' } "
        "elseif (Get-Command py -ErrorAction SilentlyContinue) { $python = 'py' } "
        "else { Write-Error 'No Python interpreter found.'; exit 1 }; "
        "$pytestAvailable = $false; "
        "& $python -c \"import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('pytest') else 1)\"; "
        "if ($LASTEXITCODE -eq 0) { $pytestAvailable = $true }; "
        + target_block
        + "if ($pytestAvailable) { "
        "  & $python -m pytest -q 2>&1; "
        "  exit $LASTEXITCODE; "
        "} "
        "if (Test-Path -LiteralPath 'tests') { "
        "  & $python -m unittest discover -s tests -p 'test*.py' 2>&1; "
        "  exit $LASTEXITCODE; "
        "} "
        "& $python -m unittest discover 2>&1; "
        "exit $LASTEXITCODE"
    )


def _ps_quote(text: str) -> str:
    return text.replace("'", "''")


def _agent_definition(name: str):
    return get_agent_definition(name)


def _agent_int_policy(name: str, key: str, default: int) -> int:
    definition = _agent_definition(name)
    value = (definition.policy or {}).get(key) if definition is not None else None
    return int(value) if isinstance(value, int) else default


def _agent_bool_policy(name: str, key: str, default: bool) -> bool:
    definition = _agent_definition(name)
    value = (definition.policy or {}).get(key) if definition is not None else None
    return bool(value) if isinstance(value, bool) else default


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
