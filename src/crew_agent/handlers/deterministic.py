from __future__ import annotations

import re

from crew_agent.core.models import ExecutionPlan, Host, PlanStep


def build_builtin_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    """
    Entry point for fast, non-LLM automation.
    Priority: Specific Maintenance -> Scoped Counting -> Grep -> Find
    """
    lowered = " ".join(request.casefold().split())
    windows_hosts = [host for host in hosts if host.platform == "windows" and host.enabled]
    if not windows_hosts:
        return None

    # 1. Identity & System (Instant)
    if _looks_like_github_cli_presence_request(lowered):
        return _windows_github_cli_presence_plan(windows_hosts)
    if ("powershell" in lowered or "pwsh" in lowered) and "version" in lowered:
        return _windows_powershell_version_plan(windows_hosts)
    if _looks_like_os_version_request(lowered):
        return _windows_os_version_plan(windows_hosts)

    # 2. Infrastructure Operations
    if _looks_like_discovery_request(lowered):
        return _windows_discovery_plan(windows_hosts)
    if _looks_like_cleanup_request(lowered):
        return _windows_cleanup_plan(windows_hosts)
    if _looks_like_shutdown_reason_request(lowered):
        return _windows_shutdown_reason_plan(windows_hosts)

    # 3. Scoped Counting (High Precision)
    if _looks_like_file_count_request(lowered):
        return _windows_file_count_plan(request, windows_hosts)

    # 4. Content Search (Grep) - Must have explicit "content" or "inside"
    if _looks_like_content_search_request(lowered):
        return _windows_content_search_plan(request, windows_hosts)

    # 5. Filename Search (Find) - General fallback
    if _looks_like_search_request(lowered):
        return _windows_search_plan(request, windows_hosts)

    # 6. Service Status
    service_name = _extract_service_name(request)
    if service_name and any(keyword in lowered for keyword in ("service", "status", "running")):
        return _windows_service_status_plan(windows_hosts, service_name)

    return None


# --- DETECTION LOGIC (STRICT) ---

def _looks_like_file_count_request(lowered: str) -> bool:
    # Simpler, broader matching
    has_count = any(t in lowered for t in ("how many", "count", "total", "sum", "number of"))
    has_resource = any(t in lowered for t in ("file", "folder", "directory", "dir", "document", "video", "music", "picture", "desktop", "download"))
    return has_count and has_resource


def _looks_like_content_search_request(lowered: str) -> bool:
    # Requires explicit "content", "inside", "contains", or "grep" to avoid stealing from file search
    grep_terms = ("content", "inside", "contains", "grep", "text inside", "lines with")
    return any(term in lowered for term in grep_terms)


def _looks_like_search_request(lowered: str) -> bool:
    search_terms = ("search", "find", "look for", "locate", "where is")
    # Only if it didn't match the count or grep logic
    return any(term in lowered for term in search_terms)


def _looks_like_cleanup_request(lowered: str) -> bool:
    return any(t in lowered for t in ("cleanup", "clean up", "wipe")) and \
           any(t in lowered for t in ("temp", "tmp", "cache", "junk"))


def _looks_like_discovery_request(lowered: str) -> bool:
    return any(t in lowered for t in ("discover", "scan", "who is on")) and \
           any(t in lowered for t in ("network", "hosts", "devices", "neighbors"))


# --- PLAN GENERATORS (NO HARDCODING) ---

def _windows_file_count_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    lowered = request.lower()
    
    # Identify mode
    is_folder_query = any(term in lowered for term in ("folder", "directory", "dir"))
    mode_flag = "-Directory" if is_folder_query else "-File"
    resource_type = "folders" if is_folder_query else "files"

    # Resolve Target Folder
    target_path = None
    display_name = "Target"
    
    if "document" in lowered or "docunment" in lowered:
        target_path = "$([Environment]::GetFolderPath('MyDocuments'))"
        display_name = "Documents"
    elif "desktop" in lowered:
        target_path = "$([Environment]::GetFolderPath('Desktop'))"
        display_name = "Desktop"
    elif "downloads" in lowered:
        target_path = "$env:USERPROFILE\\Downloads"
        display_name = "Downloads"
    elif "video" in lowered:
        target_path = "$([Environment]::GetFolderPath('MyVideos'))"
        display_name = "Videos"
    elif "music" in lowered:
        target_path = "$([Environment]::GetFolderPath('MyMusic'))"
        display_name = "Music"
    elif "picture" in lowered:
        target_path = "$([Environment]::GetFolderPath('MyPictures'))"
        display_name = "Pictures"
    else:
        # Generic "in [name]" extraction
        path_match = re.search(r"in (?:the )?([A-Za-z0-9._-]+)", lowered)
        if path_match:
            folder_name = path_match.group(1)
            # PRO FIX: Search User Profile first (Fast), then fallback to C:\ (Slow)
            target_path = (
                f"$p = Get-ChildItem -Path $env:USERPROFILE -Filter '{folder_name}' -Recurse -Directory -ErrorAction SilentlyContinue | Select-Object -First 1; "
                f"if (-not $p) {{ $p = Get-ChildItem -Path C:\\ -Filter '{folder_name}' -Recurse -Directory -MaxDepth 2 -ErrorAction SilentlyContinue | Select-Object -First 1 }}; "
                "$p.FullName"
            )
            display_name = folder_name

    if not target_path:
        return None # Let the LLM handle complex/vague paths

    ext_filter = "*"
    ext_match = re.search(r"\.([a-z0-9]+)", lowered)
    if not is_folder_query and ext_match:
        ext_filter = f"*.{ext_match.group(1)}"

    command = (
        f"$target = {target_path}; "
        "if (-not $target) { Write-Error 'Target folder not found.'; exit 1 }; "
        f"$count = (Get-ChildItem -Path $target -Filter '{ext_filter}' -Recurse {mode_flag} -ErrorAction SilentlyContinue | Measure-Object).Count; "
        f"[pscustomobject]@{{Folder=$target; Type='{resource_type}'; Filter='{ext_filter}'; Count=$count}} | ConvertTo-Json -Compress"
    )
    
    return _single_inspect_plan(
        hosts,
        summary=f"Count {resource_type} in {display_name}.",
        title=f"Count {resource_type} in {display_name}",
        command=command,
        expected_signal="JSON count object",
        validation_type="file_count_json"
    )


def _windows_content_search_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    # Extract the pattern strictly after "for", "contains", or "with"
    match = re.search(r"(?:for|contains|with) ['\"]?([^'\"]+)['\"]?", request, re.IGNORECASE)
    if not match:
        return None # Yield to planner if we can't find a clear pattern

    pattern = match.group(1)
    command = (
        f"$pattern = '{pattern}'; "
        "Get-ChildItem -Path C:\\ -Include *.txt,*.log,*.md,*.json,*.py,*.env,*.yaml,*.yml -Recurse -ErrorAction SilentlyContinue | "
        "Where-Object { $_.FullName -notmatch '\\\\.(cody|git|gemini|venv)' } | "
        "Select-String -Pattern $pattern | "
        "Select-Object @{Name='File';Expression={$_.Path}}, LineNumber, @{Name='Content';Expression={$_.Line.Trim()}} | "
        "ConvertTo-Json"
    )
    return _single_inspect_plan(
        hosts,
        summary=f"Search file content for '{pattern}'.",
        title=f"Grep for '{pattern}'",
        command=command,
        expected_signal="JSON match array",
        validation_type="grep_json"
    )


def _windows_search_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    # Extract filename strictly
    match = re.search(r"(?:for|locate|find) ([A-Za-z0-9._-]+)", request, re.IGNORECASE)
    if not match:
        return None # Yield to planner

    filename = match.group(1)
    command = (
        f"$file = '{filename}'; "
        "$results = Get-ChildItem -Path C:\\ -Filter $file -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName; "
        "if ($results) { $results; exit 0 } else { exit 1 }"
    )
    return _single_inspect_plan(
        hosts,
        summary=f"Search for file '{filename}'.",
        title=f"Find file '{filename}'",
        command=command,
        expected_signal="File paths",
        validation_type="text"
    )


# --- UTILITIES ---

def _single_inspect_plan(
    hosts: list[Host],
    summary: str,
    title: str,
    command: str,
    expected_signal: str,
    validation_type: str,
) -> ExecutionPlan:
    steps = [
        PlanStep(
            id=f"builtin-{i}",
            title=title,
            host=host.name,
            kind="inspect",
            rationale="Handled by Codex's high-precision deterministic engine.",
            command=command,
            expected_signal=expected_signal,
            validation_type=validation_type,
            accept_nonzero_returncode=True
        )
        for i, host in enumerate(hosts, start=1)
    ]
    return ExecutionPlan(
        summary=summary,
        planner_notes=["matched precision deterministic handler"],
        risk="low",
        domain="infra",
        operation_class="inspect",
        requires_confirmation=False,
        requires_unsafe=False,
        missing_information=[],
        target_hosts=[host.name for host in hosts],
        steps=steps,
        raw={"builtin": True, "handler": validation_type, "specialist": "infra-inspector"},
    )

def _extract_service_name(request: str) -> str | None:
    patterns = (r"service\s+([A-Za-z0-9._-]+)", r"status of\s+([A-Za-z0-9._-]+)")
    for p in patterns:
        m = re.search(p, request, re.IGNORECASE)
        if m: return m.group(1)
    return None

def _looks_like_github_cli_presence_request(l: str) -> bool:
    return "github cli" in l and any(t in l for t in ("install", "available", "present", "exist"))

def _looks_like_os_version_request(l: str) -> bool:
    return "os version" in l or "windows version" in l

def _looks_like_shutdown_reason_request(l: str) -> bool:
    return any(t in l for t in ("shutdown", "reboot", "restart")) and any(t in l for t in ("why", "reason", "last"))

def _windows_powershell_version_plan(hosts: list[Host]) -> ExecutionPlan:
    return _single_inspect_plan(hosts, "Inspect PowerShell version.", "Get PS Version", "$PSVersionTable.PSVersion | ConvertTo-Json -Compress", "JSON", "powershell_version_json")

def _windows_os_version_plan(hosts: list[Host]) -> ExecutionPlan:
    return _single_inspect_plan(hosts, "Inspect OS version.", "Get OS Version", "Get-CimInstance Win32_OperatingSystem | ConvertTo-Json -Compress", "JSON", "os_version_json")

def _windows_github_cli_presence_plan(hosts: list[Host]) -> ExecutionPlan:
    cmd = "$c = Get-Command gh -ErrorAction SilentlyContinue; if($c){[pscustomobject]@{Installed=$true;Source=$c.Source}|ConvertTo-Json}else{[pscustomobject]@{Installed=$false}|ConvertTo-Json}"
    return _single_inspect_plan(hosts, "Check GitHub CLI.", "Check GH CLI", cmd, "JSON", "tool_presence_json")

def _windows_discovery_plan(hosts: list[Host]) -> ExecutionPlan:
    return _single_inspect_plan(hosts, "Discover neighbors.", "Network Scan", "arp -a", "Text", "text")

def _windows_service_status_plan(hosts: list[Host], name: str) -> ExecutionPlan:
    return _single_inspect_plan(hosts, f"Status of {name}.", f"Service: {name}", f"Get-Service -Name '{name}' | ConvertTo-Json -Compress", "JSON", "service_status_json")

def _windows_shutdown_reason_plan(hosts: list[Host]) -> ExecutionPlan:
    cmd = "Get-WinEvent -FilterHashtable @{LogName='System'; ID=1074} -MaxEvents 1 | ConvertTo-Json -Compress"
    return _single_inspect_plan(hosts, "Last shutdown reason.", "Shutdown Reason", cmd, "JSON", "event_log_json")

def _windows_cleanup_plan(hosts: list[Host]) -> ExecutionPlan:
    cmd = "$f=Get-ChildItem $env:TEMP -Recurse -ErrorAction SilentlyContinue; $c=($f|Measure).Count; $f|Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; [pscustomobject]@{Count=$c}|ConvertTo-Json"
    return _single_inspect_plan(hosts, "Clean temp files.", "Cleanup Temp", cmd, "JSON", "text")
