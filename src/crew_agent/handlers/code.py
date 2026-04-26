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

    # PRO BLOCK: If this is an infra task (count, maintenance, etc), skip code specialist entirely
    if any(t in lowered for t in ("how many", "count", "total", "folder in", "maintenance", "cleanup")):
        return None

    read_plan = _build_file_read_plan(request, lowered, local_hosts)
    if read_plan is not None: return read_plan

    search_plan = _build_text_search_plan(request, lowered, local_hosts)
    if search_plan is not None: return search_plan

    file_search_plan = _build_file_search_plan(request, lowered, local_hosts)
    if file_search_plan is not None: return file_search_plan

    list_plan = _build_file_list_plan(lowered, local_hosts)
    if list_plan is not None: return list_plan

    git_plan = _build_git_status_plan(lowered, local_hosts)
    if git_plan is not None: return git_plan

    test_plan = _build_test_plan(request, lowered, local_hosts)
    if test_plan is not None: return test_plan

    return None

def _build_file_read_plan(request: str, lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not any(term in lowered for term in ("read ", "show ", "open ", "display ", "print ")):
        return None
    targets = _extract_file_targets(request, lowered)
    if not targets: return None
    return _build_file_read_inspect_plan(hosts, targets)

def _build_text_search_plan(request: str, lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    # Must be specific to code searching
    if not any(term in lowered for term in ("search repo", "search codebase", "grep codebase")):
        return None
    pattern = _extract_search_pattern(request)
    if not pattern: return None
    command = _powershell_search_text_command(pattern, max_results=_agent_int_policy("repo-searcher", "max_results", 100))
    return _single_code_inspect_plan(hosts, f"Search the repository for '{pattern}'.", f"Search for {pattern}", command, "JSON", "repo_search_text", "repo_text_search", "repo-searcher")

def _build_file_search_plan(request: str, lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    # Must be specific to repo file finding
    if not any(term in lowered for term in ("find repo file", "search repo files")):
        return None
    name = _extract_file_search_name(request)
    if not name: return None
    command = _powershell_search_file_command(name, max_results=_agent_int_policy("repo-searcher", "max_results", 100))
    return _single_code_inspect_plan(hosts, f"Find repository files matching {name}.", f"Find file {name}", command, "JSON", "repo_file_list_text", "repo_file_search", "repo-searcher")

def _build_file_list_plan(lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    # Block generic "list files" which belongs in deterministic
    if not any(phrase in lowered for phrase in ("repo files", "repository files", "codebase files", "project files")):
        return None
    command = _powershell_list_files_command(max_results=_agent_int_policy("repo-searcher", "max_results", 200))
    return _single_code_inspect_plan(hosts, "List repository files.", "List repository files", command, "A file list", "repo_file_list_text", "repo_file_list", "repo-searcher")

def _build_git_status_plan(lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not any(phrase in lowered for phrase in ("git status", "changed files", "what changed", "show diff status")):
        return None
    command = _powershell_git_status_command()
    return _single_code_inspect_plan(hosts, "Inspect the local git working tree status.", "Show git status", command, "Git status", "git_status_text", "git_status", "repo-inspector")

def _build_test_plan(request: str, lowered: str, hosts: list[Host]) -> ExecutionPlan | None:
    if not _looks_like_test_request(lowered):
        return None
    target = _extract_test_target(request)
    command = _powershell_test_command(target)
    target_suffix = f" for {target}" if target else ""
    return _single_code_inspect_plan(hosts, f"Run repository tests{target_suffix}.", f"Run tests{target_suffix}", command, "Test summary", "test_run_text", "test_run", "test-runner", accept_nonzero_returncode=_agent_bool_policy("test-runner", "accept_nonzero_returncode", True))

def _single_code_inspect_plan(hosts: list[Host], summary: str, title: str, command: str, expected_signal: str, validation_type: str, handler: str, specialist: str, accept_nonzero_returncode: bool = False) -> ExecutionPlan:
    steps = [PlanStep(id=f"code-{handler}-{i}", title=title, host=host.name, kind="inspect", rationale="Coding assistant handler.", command=command, expected_signal=expected_signal, validation_type=validation_type, accept_nonzero_returncode=accept_nonzero_returncode) for i, host in enumerate(hosts, start=1)]
    return ExecutionPlan(summary=summary, planner_notes=["matched built-in coding handler"], risk="low", domain="code", operation_class="inspect", requires_confirmation=False, requires_unsafe=False, missing_information=[], target_hosts=[host.name for host in hosts], steps=steps, raw={"builtin": True, "handler": handler, "specialist": specialist})

def _build_file_read_inspect_plan(hosts: list[Host], targets: list[FileTarget]) -> ExecutionPlan:
    path = targets[0].path
    summary = f"Read file {path}."
    steps = []
    counter = 1
    for host in hosts:
        for target in targets:
            steps.append(PlanStep(id=f"code-repo_file_read-{counter}", title=f"Read {target.path}", host=host.name, kind="inspect", rationale="Coding assistant handler.", command=target.read_command, expected_signal=f"File contents for {target.path}", validation_type="repo_file_text", continue_on_failure=target.continue_on_failure))
            counter += 1
    return ExecutionPlan(summary=summary, planner_notes=["matched built-in coding handler"], risk="low", domain="code", operation_class="inspect", requires_confirmation=False, requires_unsafe=False, missing_information=[], target_hosts=[host.name for host in hosts], steps=steps, raw={"builtin": True, "handler": "repo_file_read", "specialist": "file-reader", "stop_after_first_success": True})

def _extract_file_targets(request: str, lowered: str) -> list[FileTarget]:
    path = _extract_repo_path(request)
    if not path: return []
    if Path(path).parent != Path("."):
        return [FileTarget(path=path, location_label="workspace", read_command=_powershell_read_file_command(path, preview_lines=250))]
    named_location = _extract_named_location(lowered)
    if named_location:
        expr, label = named_location
        return [FileTarget(path=path, location_label=label, read_command=_powershell_read_file_command(path, directory_expr=expr, preview_lines=250))]
    return [FileTarget(path=path, location_label="workspace", read_command=_powershell_read_file_command(path, preview_lines=250))]

def _extract_repo_path(request: str) -> str | None:
    patterns = (r"(?:(?:read|show|open|display|print)\s+)([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)", r"([A-Za-z0-9_./\\-]+\.[A-Za-z0-9_]+)")
    for p in patterns:
        m = re.search(p, request, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip().strip("'\"")
            if candidate and ".." not in candidate: return candidate.replace("/", "\\")
    return None

def _extract_search_pattern(request: str) -> str | None:
    quoted = re.search(r"['\"]([^'\"]{2,200})['\"]", request)
    if quoted: return quoted.group(1).strip()
    return None

def _extract_file_search_name(request: str) -> str | None:
    match = re.search(r"(?:find|search)\s+(?:for\s+)?(?:file|files)\s+(?:named\s+)?([A-Za-z0-9._/-]+)", request, re.IGNORECASE)
    if match: return match.group(1).strip().strip("'\"")
    return None

def _extract_test_target(request: str) -> str | None:
    match = re.search(r"(tests?[\\/][A-Za-z0-9_./\\-]+\.py)", request, re.IGNORECASE)
    if match: return match.group(1).strip().strip("'\"")
    return None

def _looks_like_test_request(l: str) -> bool:
    return any(p in l for p in ("run tests", "pytest", "unittest"))

def _extract_named_location(l: str) -> tuple[str, str] | None:
    if "documents" in l: return "[Environment]::GetFolderPath('MyDocuments')", "Documents"
    if "desktop" in l: return "[Environment]::GetFolderPath('Desktop')", "Desktop"
    if "downloads" in l: return "Join-Path $env:USERPROFILE 'Downloads'", "Downloads"
    return None

def _powershell_read_file_command(path: str, directory_expr: str | None = None, preview_lines: int = 250) -> str:
    path_expr = f"Join-Path ({directory_expr}) '{path}'" if directory_expr else f"'{path}'"
    return f"$p = {path_expr}; if (-not (Test-Path $p)) {{ exit 1 }}; Get-Content $p -TotalCount {preview_lines}"

def _powershell_search_text_command(pattern: str, max_results: int) -> str:
    return f"Get-ChildItem -Recurse -File | Select-String -Pattern '{pattern}' | Select-Object -First {max_results}"

def _powershell_search_file_command(name: str, max_results: int) -> str:
    return f"Get-ChildItem -Recurse -Filter '*{name}*' | Select-Object -First {max_results}"

def _powershell_list_files_command(max_results: int) -> str:
    return f"Get-ChildItem -Recurse -File | Select-Object FullName -First {max_results}"

def _powershell_git_status_command() -> str:
    return "git status --short"

def _powershell_test_command(target: str | None) -> str:
    return "pytest -q" if target is None else f"pytest {target}"

def _agent_int_policy(n: str, k: str, d: int) -> int: return d
def _agent_bool_policy(n: str, k: str, d: bool) -> bool: return d
