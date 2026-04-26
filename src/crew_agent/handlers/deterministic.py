from __future__ import annotations

import re

from crew_agent.core.models import ExecutionPlan, Host, PlanStep


def build_builtin_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    """
    Entry point for fast, non-LLM automation.
    Priority: Specific Maintenance -> Scoped Counting -> Grep -> Find
    """
    raw_input = request.lower()
    lowered = " ".join(request.casefold().split())
    windows_hosts = [host for host in hosts if host.platform == "windows" and host.enabled]
    if not windows_hosts:
        return None

    # 1. Identity & System
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

    # 3. Scoped Counting (Check ORIGINAL input for "how many")
    if any(t in raw_input for t in ("how many", "count", "total", "number of", "sum")):
        return _windows_file_count_plan(request, windows_hosts, do_count=True)
    
    # 4. Scoped Listing
    if any(t in raw_input for t in ("list", "show", "contents", "what is in")):
        return _windows_file_count_plan(request, windows_hosts, do_count=False)

    # 5. Content Search (Grep)
    if _looks_like_content_search_request(lowered):
        return _windows_content_search_plan(request, windows_hosts)

    # 6. Filename Search (Find)
    if _looks_like_search_request(lowered):
        return _windows_search_plan(request, windows_hosts)

    return None


# --- DETECTION LOGIC (STRICT) ---

def _looks_like_content_search_request(lowered: str) -> bool:
    grep_terms = ("content", "inside", "contains", "grep", "text inside", "lines with")
    return any(term in lowered for term in grep_terms)

def _looks_like_search_request(lowered: str) -> bool:
    search_terms = ("search", "find", "look for", "locate", "where is")
    return any(term in lowered for term in search_terms)

def _looks_like_cleanup_request(lowered: str) -> bool:
    return any(t in lowered for t in ("cleanup", "clean up", "wipe")) and any(t in lowered for t in ("temp", "tmp", "cache", "junk"))

def _looks_like_discovery_request(lowered: str) -> bool:
    return any(t in lowered for t in ("discover", "scan", "who is on")) and any(t in lowered for t in ("network", "hosts", "devices", "neighbors"))


# --- PLAN GENERATORS (THE "PRO" WAY) ---

def _windows_file_count_plan(request: str, hosts: list[Host], do_count: bool) -> ExecutionPlan | None:
    lowered = request.lower()
    
    # Identify type
    is_folder_query = any(term in lowered for term in ("folder", "directory", "dir"))
    mode_filter = "Where-Object { $_.PSIsContainer }" if is_folder_query else "Where-Object { -not $_.PSIsContainer }"
    resource_type = "folders" if is_folder_query else "files"

    # Resolve Target Folder
    target_path_expr = None
    display_name = "Target"
    
    if "document" in lowered or "docunment" in lowered:
        target_path_expr = "$([Environment]::GetFolderPath('MyDocuments'))"
        display_name = "Documents"
    elif "desktop" in lowered:
        target_path_expr = "$([Environment]::GetFolderPath('Desktop'))"
        display_name = "Desktop"
    elif "downloads" in lowered:
        target_path_expr = "$env:USERPROFILE\\Downloads"
        display_name = "Downloads"
    elif "video" in lowered:
        target_path_expr = "$([Environment]::GetFolderPath('MyVideos'))"
        display_name = "Videos"
    elif "music" in lowered:
        target_path_expr = "$([Environment]::GetFolderPath('MyMusic'))"
        display_name = "Music"
    elif "picture" in lowered:
        target_path_expr = "$([Environment]::GetFolderPath('MyPictures'))"
        display_name = "Pictures"
    else:
        # Resolve by name across all drives
        path_match = re.search(r"(?:in|of) (?:the )?([A-Za-z0-9._-]+)", lowered)
        if path_match:
            folder_name = path_match.group(1)
            target_path_expr = (
                f"& {{ $fn='{folder_name}'; $f=Get-ChildItem -Path $env:USERPROFILE -Filter $fn -ErrorAction SilentlyContinue | Where-Object {{ $_.PSIsContainer }} | Select-Object -First 1; "
                "if(-not $f){ $drives=Get-PSDrive -PSProvider FileSystem; foreach($d in $drives){ "
                "$f=Get-ChildItem -Path $d.Root -Filter $fn -ErrorAction SilentlyContinue | Where-Object { $_.PSIsContainer } | Select-Object -First 1; "
                "if($f){break}}}; if($f){$f.FullName}else{$null} }}"
            )
            display_name = folder_name

    if not target_path_expr:
        return None

    if do_count:
        command = (
            f"$base = ({target_path_expr}); "
            "if (-not $base) { Write-Error 'Folder not found.'; exit 1 }; "
            f"$count = (Get-ChildItem -Path $base -ErrorAction SilentlyContinue | {mode_filter} | Measure-Object).Count; "
            f"[pscustomobject]@{{Folder=$base; Type='{resource_type}'; Count=$count}} | ConvertTo-Json -Compress"
        )
        val_type = "file_count_json"
        expected = "JSON count object"
        title = f"Count {resource_type} in {display_name}"
    else:
        command = (
            f"$base = ({target_path_expr}); "
            "if (-not $base) { Write-Error 'Folder not found.'; exit 1 }; "
            f"Get-ChildItem -Path $base -ErrorAction SilentlyContinue | {mode_filter} | Select-Object -ExpandProperty Name"
        )
        val_type = "text"
        expected = "List of names"
        title = f"List {resource_type} in {display_name}"

    return _single_inspect_plan(hosts, f"Process {resource_type} in {display_name}.", title, command, expected, val_type)


def _windows_content_search_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    match = re.search(r"(?:for|contains|with) ['\"]?([^'\"]+)['\"]?", request, re.IGNORECASE)
    if not match: return None
    pattern = match.group(1)
    command = (
        f"$pattern = '{pattern}'; "
        "Get-ChildItem -Path C:\\,D:\\,X:\\ -Include *.txt,*.log,*.md,*.json,*.py,*.env,*.yaml,*.yml -Recurse -ErrorAction SilentlyContinue | "
        "Where-Object { $_.FullName -notmatch '\\\\.(cody|git|gemini|venv)' } | "
        "Select-String -Pattern $pattern | "
        "Select-Object @{Name='File';Expression={$_.Path}}, LineNumber, @{Name='Content';Expression={$_.Line.Trim()}} | "
        "ConvertTo-Json"
    )
    return _single_inspect_plan(hosts, f"Search file content for '{pattern}'.", f"Grep for '{pattern}'", command, "JSON", "grep_json")


def _windows_search_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    match = re.search(r"(?:for|locate|find) ([A-Za-z0-9._-]+)", request, re.IGNORECASE)
    if not match: return None
    filename = match.group(1)
    command = (
        f"$file = '{filename}'; "
        "$results = Get-ChildItem -Path C:\\,D:\\,X:\\ -Filter $file -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName; "
        "if ($results) { $results; exit 0 } else { exit 1 }"
    )
    return _single_inspect_plan(hosts, f"Find file '{filename}'.", f"Find file '{filename}'", command, "Paths", "text")


# --- UTILITIES ---

def _single_inspect_plan(hosts, summary, title, command, expected_signal, validation_type, specialist="infra-inspector"):
    steps = [PlanStep(id=f"builtin-{i}", title=title, host=host.name, kind="inspect", command=command, expected_signal=expected_signal, validation_type=validation_type, accept_nonzero_returncode=True) for i, host in enumerate(hosts, start=1)]
    return ExecutionPlan(summary=summary, risk="low", domain="infra", operation_class="inspect", target_hosts=[host.name for host in hosts], steps=steps, raw={"builtin": True, "handler": validation_type, "specialist": specialist})

def _extract_service_name(request: str) -> str | None:
    patterns = (r"service\s+([A-Za-z0-9._-]+)", r"status of\s+([A-Za-z0-9._-]+)")
    for p in patterns:
        m = re.search(p, request, re.IGNORECASE)
        if m: return m.group(1)
    return None

def _looks_like_github_cli_presence_request(l: str) -> bool: return "github cli" in l and "installed" in l
def _looks_like_os_version_request(l: str) -> bool: return "os version" in l
def _looks_like_shutdown_reason_request(l: str) -> bool: return "shutdown" in l and "reason" in l

def _windows_powershell_version_plan(hosts): return _single_inspect_plan(hosts, "PS Version", "Get PS Version", "$PSVersionTable.PSVersion | ConvertTo-Json", "JSON", "powershell_version_json")
def _windows_os_version_plan(hosts): return _single_inspect_plan(hosts, "OS Version", "Get OS Version", "Get-CimInstance Win32_OperatingSystem | ConvertTo-Json", "JSON", "os_version_json")
def _windows_github_cli_presence_plan(hosts): return _single_inspect_plan(hosts, "GH CLI", "Check GH CLI", "Get-Command gh -ErrorAction SilentlyContinue", "JSON", "tool_presence_json")
def _windows_discovery_plan(hosts): return _single_inspect_plan(hosts, "Discovery", "Network Scan", "arp -a", "Text", "text")
def _windows_service_status_plan(hosts, name): return _single_inspect_plan(hosts, f"Status: {name}", f"Service: {name}", f"Get-Service '{name}' | ConvertTo-Json", "JSON", "service_status_json")
def _windows_shutdown_reason_plan(hosts): return _single_inspect_plan(hosts, "Shutdown Reason", "Shutdown Reason", "Get-WinEvent -FilterHashtable @{LogName='System'; ID=1074} -MaxEvents 1 | ConvertTo-Json", "JSON", "event_log_json")
def _windows_cleanup_plan(hosts): return _single_inspect_plan(hosts, "Cleanup", "Cleanup Temp", "$f=Get-ChildItem $env:TEMP -Recurse; $f|Remove-Item -Force; 'Done'", "Text", "text")
