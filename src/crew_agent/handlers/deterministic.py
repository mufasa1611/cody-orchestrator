from __future__ import annotations

import re
import os
import ctypes
import subprocess
from ctypes import wintypes
from crew_agent.core.models import ExecutionPlan, Host, PlanStep


def build_builtin_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    """
    Entry point for high-precision local automation.
    Priority: Specific Maintenance -> Universal File Counter -> Content Search
    """
    raw_input = request.lower()
    lowered = " ".join(request.casefold().split())
    windows_hosts = [host for host in hosts if host.platform == "windows" and host.enabled]
    if not windows_hosts:
        return None

    # 1. Identity & System (Instant)
    if ("powershell" in lowered or "pwsh" in lowered) and "version" in lowered:
        return _windows_powershell_version_plan(windows_hosts)

    # 2. Universal File/Folder Counter (Pro Two-Step Logic)
    if _looks_like_file_query(raw_input):
        return _windows_universal_file_plan(request, windows_hosts)

    # 3. Content Search (Grep)
    if _looks_like_content_search_request(lowered):
        return _windows_content_search_plan(request, windows_hosts)

    # 4. Cleanup
    if _looks_like_cleanup_request(lowered):
        return _windows_cleanup_plan(windows_hosts)

    return None


# --- PRO PATH RESOLVER (Direct API) ---

def _resolve_folder_path_locally(folder_name: str) -> str | None:
    """Direct Windows API call to resolve special folders instantly."""
    folder_name = folder_name.lower()
    
    CSIDL_PERSONAL = 5    # Documents
    CSIDL_DESKTOP = 0     # Desktop
    CSIDL_MYVIDEO = 14    # Videos
    CSIDL_MYMUSIC = 13    # Music
    CSIDL_MYPICTURES = 39 # Pictures

    def get_win_path(id):
        try:
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, id, None, 0, buf)
            return buf.value
        except:
            return None

    if "document" in folder_name: return get_win_path(CSIDL_PERSONAL)
    if "desktop" in folder_name: return get_win_path(CSIDL_DESKTOP)
    if "video" in folder_name: return get_win_path(CSIDL_MYVIDEO)
    if "music" in folder_name: return get_win_path(CSIDL_MYMUSIC)
    if "picture" in folder_name: return get_win_path(CSIDL_MYPICTURES)
    if "download" in folder_name: return os.path.join(os.getenv('USERPROFILE', ''), 'Downloads')

    # Shallow drive root check
    try:
        for drive in ['C:\\', 'D:\\', 'E:\\', 'X:\\']:
            if os.path.exists(os.path.join(drive, folder_name)):
                return os.path.join(drive, folder_name)
    except:
        pass

    return None


# --- DETECTION LOGIC ---

def _looks_like_file_query(l: str) -> bool:
    count_terms = ("how many", "count", "total", "sum", "number of", "list", "show", "contents")
    resource_terms = ("file", "folder", "directory", "dir", "video", "document", "music", "desktop", "download")
    return any(t in l for t in count_terms) and any(t in l for t in resource_terms)

def _looks_like_content_search_request(l: str) -> bool:
    return any(t in l for t in ("content", "inside", "contains", "grep"))

def _looks_like_cleanup_request(l: str) -> bool:
    return any(t in l for t in ("cleanup", "clean up", "wipe")) and any(t in l for t in ("temp", "tmp", "cache"))


# --- PLAN GENERATORS ---

def _windows_universal_file_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    lowered = request.lower()
    path_match = re.search(r"(?:in|of) (?:the )?([A-Za-z0-9._/\\-]+)", lowered)
    folder_name = path_match.group(1) if path_match else "documents"
    
    # 2. Resolve Path
    resolved_path = None
    # If it looks like an absolute path already, use it!
    if re.match(r"^[a-z]:\\", folder_name, re.IGNORECASE):
        resolved_path = folder_name
    else:
        resolved_path = _resolve_folder_path_locally(folder_name)
    
    if not resolved_path: return None

    is_count = any(t in lowered for t in ("how many", "count", "total"))
    
    # PRO RESOURCE DETECTION
    is_file_query = any(t in lowered for t in ("file", "pdf", "txt", "log", "json"))
    is_folder_query = "folder" in lowered or "directory" in lowered or "dir" in lowered
    
    # If specifically asked for folders, use that, otherwise default to files if 'file' or 'pdf' mentioned
    is_folder_only = is_folder_query and not is_file_query
    
    mode_filter = "Where-Object { $_.PSIsContainer }" if is_folder_only else "Where-Object { -not $_.PSIsContainer }"
    resource_type = "folders" if is_folder_only else "files"

    # PRO EXTENSION RESOLVER: Find any specific extension mentioned (e.g. jpeg, pdf, txt)
    ext_filter = "*"
    # Look for words like 'jpeg', 'pdf', '.txt'
    ext_match = re.search(r"\b([a-z0-9]{2,4})\b files?", lowered)
    if ext_match:
        found_ext = ext_match.group(1)
        if found_ext not in ("how", "many", "file", "folder", "list"):
            ext_filter = f"*.{found_ext}"
    
    # Handle common groups
    if "image" in lowered or "picture" in lowered:
        ext_filter = "*.jpg,*.jpeg,*.png,*.gif,*.bmp"
    elif "pdf" in lowered:
        ext_filter = "*.pdf"
    elif "text" in lowered or "txt" in lowered:
        ext_filter = "*.txt"

    if is_count:
        # PRO UPGRADE: Handle multi-filter strings (for images)
        filter_parts = ext_filter.split(',')
        if len(filter_parts) > 1:
            # Multi-extension search logic
            include_str = "'" + "','".join(filter_parts) + "'"
            cmd = (
                f"$items = @(Get-ChildItem -Path '{resolved_path}' -Include {include_str} -Recurse -ErrorAction SilentlyContinue | {mode_filter}); "
                f"$paths = $items | Select-Object -ExpandProperty FullName; "
                f"[pscustomobject]@{{Folder='{resolved_path}'; Type='{resource_type}'; Filter='{ext_filter}'; Count=$items.Count; Items=$paths}} | ConvertTo-Json -Compress"
            )
        else:
            cmd = (
                f"$items = @(Get-ChildItem -Path '{resolved_path}' -Filter '{ext_filter}' -ErrorAction SilentlyContinue | {mode_filter}); "
                f"$paths = $items | Select-Object -ExpandProperty FullName; "
                f"[pscustomobject]@{{Folder='{resolved_path}'; Type='{resource_type}'; Filter='{ext_filter}'; Count=$items.Count; Items=$paths}} | ConvertTo-Json -Compress"
            )
        val_type = "file_count_json"
        title = f"Count {resource_type} ({ext_filter}) in {folder_name}"
    else:
        cmd = f"Get-ChildItem -Path '{resolved_path}' -Filter '{ext_filter}' -ErrorAction SilentlyContinue | {mode_filter} | Select-Object -ExpandProperty Name"
        val_type = "text"
        title = f"List {resource_type} in {folder_name}"

    return _single_inspect_plan(hosts, f"Action in {resolved_path}", title, cmd, "Result", val_type)


def _windows_content_search_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    match = re.search(r"(?:for|contains) ['\"]?([^'\"]+)['\"]?", request, re.IGNORECASE)
    if not match: return None
    pattern = match.group(1)
    # PRO UNIVERSAL SEARCH: Scan User Profile and all drive roots
    command = (
        f"$pattern = '{pattern}'; "
        "$roots = @($env:USERPROFILE); "
        "$drives = Get-PSDrive -PSProvider FileSystem; foreach($d in $drives) { if($d.Root -notmatch 'C:') { $roots += $d.Root } }; "
        "Get-ChildItem -Path $roots -Include *.txt,*.log,*.md,*.json,*.py,*.env,*.yaml,*.yml -Recurse -ErrorAction SilentlyContinue | "
        "Where-Object { $_.FullName -notmatch '\\\\.(cody|git|gemini|venv)' } | "
        "Select-String -Pattern $pattern | "
        "Select-Object @{Name='File';Expression={$_.Path}}, LineNumber, @{Name='Content';Expression={$_.Line.Trim()}} | "
        "ConvertTo-Json"
    )
    return _single_inspect_plan(hosts, f"Search all drives for '{pattern}'.", f"Grep for '{pattern}'", command, "JSON", "grep_json")


# --- UTILITIES ---

def _single_inspect_plan(hosts, summary, title, command, expected, val_type):
    steps = [PlanStep(id=f"builtin-{i}", title=title, host=h.name, kind="inspect", command=command, expected_signal=expected, validation_type=val_type, accept_nonzero_returncode=True) for i, h in enumerate(hosts, start=1)]
    return ExecutionPlan(summary=summary, risk="low", domain="infra", operation_class="inspect", target_hosts=[h.name for h in hosts], steps=steps, raw={"builtin": True, "handler": val_type})

def _windows_powershell_version_plan(hosts):
    return _single_inspect_plan(hosts, "PS Version", "Get PS Version", "$PSVersionTable.PSVersion | ConvertTo-Json", "JSON", "powershell_version_json")

def _windows_cleanup_plan(hosts):
    return _single_inspect_plan(hosts, "Cleanup Temp", "Cleanup", "Remove-Item $env:TEMP\\* -Recurse -Force -ErrorAction SilentlyContinue; 'Done'", "Text", "text")
