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

    if _looks_like_file_query(raw_input):
        return _windows_universal_file_plan(request, windows_hosts)
    
    if ("powershell" in lowered or "pwsh" in lowered) and "version" in lowered:
        return _windows_powershell_version_plan(windows_hosts)
        
    if any(t in lowered for t in ("content", "inside", "contains", "grep")):
        return _windows_content_search_plan(request, windows_hosts)

    if any(t in lowered for t in ("cleanup", "clean up", "wipe")) and any(t in lowered for t in ("temp", "tmp", "cache")):
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
           any(t in l for t in ("file", "folder", "directory", "dir", "video", "document", "music", "desktop", "download", "png", "pdf", "jpg", "jpeg", "psd"))


def _windows_universal_file_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    lowered = request.lower()
    
    # 1. Robust Path Extraction
    path_match = re.search(r"(?:in|of|inside|at|ín)\s+(?:the\s+)?([A-Za-z0-9._/\\:-]+)", lowered)
    target_name = path_match.group(1) if path_match else None
    if not target_name: return None 

    # 2. Resolve Path
    resolved_path = None
    if re.match(r"^[a-z]:\\", target_name, re.IGNORECASE):
        resolved_path = target_name
    else:
        resolved_path = _resolve_folder_path_locally(target_name)
    if not resolved_path: return None

    # 3. Intent Logic
    is_count = any(t in lowered for t in ("how many", "count", "total"))
    ext_match = re.search(r"\b([a-z0-9]{2,4})\b files?", lowered)
    found_ext = ext_match.group(1) if ext_match else None
    if found_ext in ("how", "many", "file", "folder", "list", "the"): found_ext = None

    wants_folders = any(t in lowered for t in ("folder", "directory", "dir"))
    wants_files = any(t in lowered for t in ("file", "pdf", "jpg", "png", "txt", "psd")) or (not wants_folders and found_ext is None)
    is_both = wants_folders and wants_files
    
    # Extension filtering
    ext_filter = "*"
    if not is_both:
        if found_ext: ext_filter = f"*.{found_ext}"
        elif any(t in lowered for t in ("image", "picture")): ext_filter = "*.jpg,*.jpeg,*.png,*.gif"
        elif "pdf" in lowered: ext_filter = "*.pdf"

    # 4. Command Generation
    if is_count:
        if is_both:
            resource_type = "items (files and folders)"
            cmd = (
                f"$p='{resolved_path}'; $i=@(Get-ChildItem -Path $p -Filter '{ext_filter}' -ErrorAction SilentlyContinue); "
                "$paths = $i | ForEach-Object { $_.FullName }; "
                f"[pscustomobject]@{{Folder=$p; Type='{resource_type}'; Count=$i.Count; Items=@($paths)}} | ConvertTo-Json -Compress"
            )
        elif wants_folders:
            resource_type = "folders"
            cmd = (
                f"$p='{resolved_path}'; $i=@(Get-ChildItem -Path $p -Filter '{ext_filter}' -ErrorAction SilentlyContinue | Where-Object {{ $_.PSIsContainer }}); "
                "$paths = $i | ForEach-Object { $_.FullName }; "
                f"[pscustomobject]@{{Folder=$p; Type='{resource_type}'; Count=$i.Count; Items=@($paths)}} | ConvertTo-Json -Compress"
            )
        else:
            resource_type = "files"
            cmd = (
                f"$p='{resolved_path}'; $i=@(Get-ChildItem -Path $p -Filter '{ext_filter}' -ErrorAction SilentlyContinue | Where-Object {{ -not $_.PSIsContainer }}); "
                "$paths = $i | ForEach-Object { $_.FullName }; "
                f"[pscustomobject]@{{Folder=$p; Type='{resource_type}'; Count=$i.Count; Items=@($paths)}} | ConvertTo-Json -Compress"
            )
        val_type = "file_count_json"
    else:
        resource_type = "items"
        mode_filter = ""
        if wants_folders and not wants_files: mode_filter = "| Where-Object { $_.PSIsContainer }"
        elif wants_files and not wants_folders: mode_filter = "| Where-Object { -not $_.PSIsContainer }"
        cmd = f"Get-ChildItem -Path '{resolved_path}' -Filter '{ext_filter}' -ErrorAction SilentlyContinue {mode_filter} | Select-Object -ExpandProperty Name"
        val_type = "text"

    return _single_inspect_plan(hosts, f"Action in {resolved_path}", f"Process {resource_type} in {target_name}", cmd, "Result", val_type)


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
