from __future__ import annotations

import re
import subprocess
from crew_agent.core.models import ExecutionPlan, Host, PlanStep


def build_builtin_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    """
    Entry point for high-precision local automation.
    Priority: Maintenance -> Scoped Discovery -> Grep -> Find
    """
    raw_input = request.lower()
    lowered = " ".join(request.casefold().split())
    windows_hosts = [host for host in hosts if host.platform == "windows" and host.enabled]
    if not windows_hosts:
        return None

    # 1. Identity & System (Instant)
    if _looks_like_github_cli_presence_request(lowered):
        return _windows_github_cli_presence_plan(windows_hosts)
    if ("powershell" in lowered or "pwsh" in lowered) and "version" in lowered:
        return _windows_powershell_version_plan(windows_hosts)

    # 2. Scoped Counting & Listing (The TWO-STEP Strategy)
    if _looks_like_file_query(raw_input):
        return _windows_universal_file_plan(request, windows_hosts)

    # 3. Content Search (Grep)
    if _looks_like_content_search_request(lowered):
        return _windows_content_search_plan(request, windows_hosts)

    # 4. Cleanup & Maintenance
    if _looks_like_cleanup_request(lowered):
        return _windows_cleanup_plan(windows_hosts)

    return None


# --- HELPER: Python-side Path Resolver ---

def _resolve_folder_path_locally(folder_name: str) -> str | None:
    """Uses a fast local check to find common or named folders before planning."""
    folder_name = folder_name.lower()
    
    # 1. Check special folders
    import ctypes
    from ctypes import wintypes
    
    CSIDL_PERSONAL = 5       # Documents
    CSIDL_DESKTOP = 0        # Desktop
    CSIDL_MYMUSIC = 13       # Music
    CSIDL_MYPICTURES = 39    # Pictures
    CSIDL_MYVIDEO = 14       # Videos

    def get_path(id):
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, id, None, 0, buf)
        return buf.value

    if "document" in folder_name: return get_path(CSIDL_PERSONAL)
    if "desktop" in folder_name: return get_path(CSIDL_DESKTOP)
    if "video" in folder_name: return get_path(CSIDL_MYVIDEO)
    if "music" in folder_name: return get_path(CSIDL_MYMUSIC)
    if "picture" in folder_name: return get_path(CSIDL_MYPICTURES)
    if "download" in folder_name: return f"{os.getenv('USERPROFILE')}\\Downloads"

    # 2. Check all drive roots for a match (Shallow)
    try:
        cmd = ["powershell.exe", "-NoProfile", "-Command", 
               f"$d = Get-PSDrive -PSProvider FileSystem; foreach($r in $d.Root){{ $f = Get-ChildItem -Path $r -Filter '{folder_name}' -ErrorAction SilentlyContinue | Where-Object {{ $_.PSIsContainer }} | Select-Object -First 1; if($f){{ $f.FullName; break }} }}"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except:
        pass

    return None


# --- DETECTION LOGIC ---

def _looks_like_file_query(l: str) -> bool:
    count_terms = ("how many", "count", "total", "list", "show", "contents", "folders in", "files in")
    resource_terms = ("file", "folder", "directory", "dir", "video", "document", "music", "desktop")
    return any(t in l for t in count_terms) and any(t in l for t in resource_terms)

def _looks_like_content_search_request(l: str) -> bool:
    return any(t in l for t in ("content", "inside", "contains", "grep"))

def _looks_like_cleanup_request(l: str) -> bool:
    return any(t in l for t in ("cleanup", "clean up", "wipe")) and any(t in l for t in ("temp", "tmp", "cache"))

def _looks_like_github_cli_presence_request(l: str) -> bool:
    return "github cli" in l and any(t in l for t in ("install", "available", "present", "exist"))


# --- PLAN GENERATORS (NO MORE BRITTLE ONE-LINERS) ---

def _windows_universal_file_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    lowered = request.lower()
    
    # 1. Identify Target Folder Name
    folder_name = "C:\\"
    path_match = re.search(r"(?:in|of) (?:the )?([A-Za-z0-9._-]+)", lowered)
    if path_match:
        folder_name = path_match.group(1)
    elif "documents" in lowered: folder_name = "documents"
    elif "videos" in lowered: folder_name = "videos"
    
    # 2. Resolve Path LOCALLY (Python-side)
    # This is the secret to "Pro" speed and stability
    resolved_path = _resolve_folder_path_locally(folder_name)
    if not resolved_path:
        return None # Fallback to LLM if path is mysterious
    
    # 3. Build Simple, Clean Command
    is_count = any(t in lowered for t in ("how many", "count", "total"))
    is_folder_only = "folder" in lowered
    mode_filter = "Where-Object { $_.PSIsContainer }" if is_folder_only else "Where-Object { -not $_.PSIsContainer }"
    
    if is_count:
        cmd = f"(Get-ChildItem -Path '{resolved_path}' -ErrorAction SilentlyContinue | {mode_filter} | Measure-Object).Count"
        val_type = "text"
        title = f"Count {('folders' if is_folder_only else 'files')} in {folder_name}"
    else:
        cmd = f"Get-ChildItem -Path '{resolved_path}' -ErrorAction SilentlyContinue | {mode_filter} | Select-Object -ExpandProperty Name"
        val_type = "text"
        title = f"List contents of {folder_name}"

    return _single_inspect_plan(hosts, f"Action in {resolved_path}", title, cmd, "Count or list", val_type)


def _windows_content_search_plan(request, hosts):
    match = re.search(r"(?:for|contains) ['\"]?([^'\"]+)['\"]?", request, re.IGNORECASE)
    if not match: return None
    pattern = match.group(1)
    cmd = f"Get-ChildItem -Path C:\\,D:\\ -Include *.txt,*.log,*.md,*.json,*.py -Recurse -ErrorAction SilentlyContinue | Select-String -Pattern '{pattern}' | Select-Object Path, LineNumber, Line | ConvertTo-Json"
    return _single_inspect_plan(hosts, f"Grep for '{pattern}'", f"Grep: {pattern}", cmd, "JSON", "grep_json")


# --- UTILITIES ---

def _single_inspect_plan(hosts, summary, title, command, expected, val_type):
    steps = [PlanStep(id=f"builtin-{i}", title=title, host=h.name, kind="inspect", command=command, expected_signal=expected, validation_type=val_type, accept_nonzero_returncode=True) for i, h in enumerate(hosts, start=1)]
    return ExecutionPlan(summary=summary, risk="low", domain="infra", operation_class="inspect", target_hosts=[h.name for h in hosts], steps=steps, raw={"builtin": True})

def _windows_powershell_version_plan(hosts):
    return _single_inspect_plan(hosts, "PS Version", "Get PS Version", "$PSVersionTable.PSVersion | ConvertTo-Json", "JSON", "powershell_version_json")

def _windows_cleanup_plan(hosts):
    return _single_inspect_plan(hosts, "Cleanup Temp", "Cleanup", "Remove-Item $env:TEMP\\* -Recurse -Force -ErrorAction SilentlyContinue; 'Done'", "Text", "text")
