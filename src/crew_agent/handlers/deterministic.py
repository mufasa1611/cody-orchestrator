from __future__ import annotations

import re
import os
import ctypes
import subprocess
from ctypes import wintypes
from crew_agent.core.models import ExecutionPlan, Host, PlanStep


def build_builtin_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    raw_input = request.lower()
    windows_hosts = [host for host in hosts if host.platform == "windows" and host.enabled]
    if not windows_hosts:
        return None

    if _looks_like_file_query(raw_input):
        return _windows_universal_file_plan(request, windows_hosts)
    
    # ... rest of handlers
    return None

def _resolve_folder_path_python(folder_name: str) -> str | None:
    folder_name = folder_name.lower().strip()
    
    # 1. Check Windows Known Folders
    ids = {"document": 5, "desktop": 0, "video": 14, "music": 13, "picture": 39}
    for key, cid in ids.items():
        if key in folder_name:
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, cid, None, 0, buf)
            return buf.value
            
    if "download" in folder_name:
        return os.path.join(os.environ['USERPROFILE'], 'Downloads')

    # 2. Shallow drive root check
    for drive in ['C:\\', 'D:\\', 'E:\\', 'X:\\']:
        cand = os.path.join(drive, folder_name)
        if os.path.exists(cand):
            return cand
            
    return None

def _looks_like_file_query(l: str) -> bool:
    return any(t in l for t in ("how many", "count", "total", "list", "show", "contents")) and \
           any(t in l for t in ("file", "folder", "directory", "dir", "video", "document", "music", "desktop"))

def _windows_universal_file_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    lowered = request.lower()
    match = re.search(r"(?:in|of) (?:the )?([A-Za-z0-9._/\\-]+)", lowered)
    target_name = match.group(1) if match else "videos"
    
    # DO THE WORK IN PYTHON
    resolved_path = _resolve_folder_path_python(target_name)
    if not resolved_path:
        return None

    is_count = any(t in lowered for t in ("how many", "count", "total"))
    is_folder = "folder" in lowered
    
    if is_count:
        cmd = f"@(Get-ChildItem -Path '{resolved_path}' -ErrorAction SilentlyContinue | Where-Object {{ {'$_.PSIsContainer' if is_folder else '-not $_.PSIsContainer'} }}).Count"
        title = f"Count {('folders' if is_folder else 'files')} in {target_name}"
    else:
        cmd = f"Get-ChildItem -Path '{resolved_path}' -ErrorAction SilentlyContinue | Where-Object {{ {'$_.PSIsContainer' if is_folder else '-not $_.PSIsContainer'} }} | Select-Object -ExpandProperty Name"
        title = f"List {target_name}"

    return _single_inspect_plan(hosts, f"Action in {resolved_path}", title, cmd, "Result", "text")

def _single_inspect_plan(hosts, summary, title, command, expected, val_type):
    steps = [PlanStep(id=f"builtin-{i}", title=title, host=h.name, kind="inspect", command=command, expected_signal=expected, validation_type=val_type, accept_nonzero_returncode=True) for i, h in enumerate(hosts, start=1)]
    return ExecutionPlan(summary=summary, risk="low", domain="infra", operation_class="inspect", target_hosts=[h.name for h in hosts], steps=steps, raw={"builtin": True})
