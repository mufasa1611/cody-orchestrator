from __future__ import annotations

import re
import os
import ctypes
import subprocess
from ctypes import wintypes
from crew_agent.core.models import ExecutionPlan, Host, PlanStep


def build_builtin_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
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


def _resolve_folder_path_locally(folder_name: str) -> str | None:
    folder_name = folder_name.lower().strip()
    ids = {"document": 5, "desktop": 0, "video": 14, "music": 13, "picture": 39}
    for key, cid in ids.items():
        if key in folder_name:
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, cid, None, 0, buf)
            return buf.value
    if "download" in folder_name:
        return os.path.join(os.getenv('USERPROFILE', ''), 'Downloads')

    for drive in ['C:\\', 'D:\\', 'E:\\', 'X:\\']:
        cand = os.path.join(drive, folder_name)
        if os.path.exists(cand): return cand
    return None


def _looks_like_file_query(l: str) -> bool:
    return any(t in l for t in ("how many", "count", "total", "list", "show", "contents")) and \
           any(t in l for t in ("file", "folder", "directory", "dir", "video", "document", "music", "desktop", "download", "png", "pdf", "jpg", "jpeg"))

def _looks_like_content_search_request(l: str) -> bool:
    return any(t in l for t in ("content", "inside", "contains", "grep"))

def _looks_like_cleanup_request(l: str) -> bool:
    return any(t in l for t in ("cleanup", "clean up", "wipe")) and any(t in l for t in ("temp", "tmp", "cache"))


def _windows_universal_file_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    lowered = request.lower()
    path_match = re.search(r"(?:in|of) (?:the )?([A-Za-z0-9._/\\-]+)", lowered)
    folder_name = path_match.group(1) if path_match else "documents"
    
    resolved_path = _resolve_folder_path_locally(folder_name)
    if not resolved_path: return None

    # 3. Smart Extension & Mode Filter
    is_count = any(t in lowered for t in ("how many", "count", "total"))
    
    # PRO RESOURCE DETECTION: Explicitly check for files vs folders
    # If any extension is found, it's a FILE query
    ext_match = re.search(r"\b([a-z0-9]{2,4})\b files?", lowered)
    has_image_keyword = any(t in lowered for t in ("image", "picture"))
    
    is_file_query = ext_match is not None or has_image_keyword or "file" in lowered
    is_folder_query = ("folder" in lowered or "directory" in lowered or "dir" in lowered) and not is_file_query
    
    mode_filter = "Where-Object { $_.PSIsContainer }" if is_folder_query else "Where-Object { -not $_.PSIsContainer }"
    resource_type = "folders" if is_folder_query else "files"

    # Smart Extension Filter
    ext_filter = "*"
    if has_image_keyword:
        ext_filter = "*.jpg,*.jpeg,*.png,*.gif"
    elif ext_match:
        found_ext = ext_match.group(1)
        if found_ext not in ("how", "many", "file", "folder", "list"):
            ext_filter = f"*.{found_ext}"
    elif "pdf" in lowered: ext_filter = "*.pdf"
    elif "text" in lowered or "txt" in lowered: ext_filter = "*.txt"

    if is_count:
        # PRO UPGRADE: Use @() to force array in PowerShell so JSON is always a list
        if "," in ext_filter:
            # Multi-extension requires -Include
            include_list = "'" + "','".join(ext_filter.split(',')) + "'"
            cmd = (
                f"$p='{resolved_path}'; $i=@(Get-ChildItem -Path $p -Include {include_list} -Recurse -ErrorAction SilentlyContinue | {mode_filter}); "
                "$paths = $i | ForEach-Object { $_.FullName }; "
                f"[pscustomobject]@{{Folder=$p; Type='{resource_type}'; Count=$i.Count; Items=@($paths)}} | ConvertTo-Json -Compress"
            )
        else:
            cmd = (
                f"$p='{resolved_path}'; $i=@(Get-ChildItem -Path $p -Filter '{ext_filter}' -ErrorAction SilentlyContinue | {mode_filter}); "
                "$paths = $i | ForEach-Object { $_.FullName }; "
                f"[pscustomobject]@{{Folder=$p; Type='{resource_type}'; Count=$i.Count; Items=@($paths)}} | ConvertTo-Json -Compress"
            )
        val_type = "file_count_json"
        title = f"Count {resource_type} in {folder_name}"
    else:
        cmd = f"Get-ChildItem -Path '{resolved_path}' -Filter '{ext_filter}' -ErrorAction SilentlyContinue | {mode_filter} | Select-Object -ExpandProperty Name"
        val_type = "text"
        title = f"List {resource_type} in {folder_name}"

    return _single_inspect_plan(hosts, f"Action in {resolved_path}", title, cmd, "Result", val_type)


def _windows_content_search_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    match = re.search(r"(?:for|contains) ['\"]?([^'\"]+)['\"]?", request, re.IGNORECASE)
    if not match: return None
    pattern = match.group(1)
    command = (
        f"$pattern = '{pattern}'; "
        "Get-ChildItem -Path $env:USERPROFILE -Include *.txt,*.log,*.md,*.json,*.py -Recurse -ErrorAction SilentlyContinue | "
        "Where-Object { $_.FullName -notmatch '\\\\.(cody|git|gemini|venv)' } | "
        "Select-String -Pattern $pattern | "
        "Select-Object @{Name='File';Expression={$_.Path}}, LineNumber, @{Name='Content';Expression={$_.Line.Trim()}} | "
        "ConvertTo-Json"
    )
    return _single_inspect_plan(hosts, f"Grep for '{pattern}'", f"Grep: {pattern}", command, "JSON", "grep_json")

def _single_inspect_plan(hosts, summary, title, command, expected, val_type):
    steps = [PlanStep(id=f"builtin-{i}", title=title, host=h.name, kind="inspect", command=command, expected_signal=expected, validation_type=val_type, accept_nonzero_returncode=True) for i, h in enumerate(hosts, start=1)]
    return ExecutionPlan(summary=summary, risk="low", domain="infra", operation_class="inspect", target_hosts=[h.name for h in hosts], steps=steps, raw={"builtin": True, "handler": val_type, "specialist": "infra-inspector"})

def _windows_powershell_version_plan(hosts):
    return _single_inspect_plan(hosts, "PS Version", "Get PS Version", "$PSVersionTable.PSVersion | ConvertTo-Json", "JSON", "powershell_version_json")

def _windows_cleanup_plan(hosts):
    return _single_inspect_plan(hosts, "Cleanup", "Cleanup Temp", "Remove-Item $env:TEMP\\* -Recurse -Force -ErrorAction SilentlyContinue; 'Done'", "Text", "text")
