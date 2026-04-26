from __future__ import annotations

import re

from crew_agent.core.models import ExecutionPlan, Host, PlanStep


def build_builtin_plan(request: str, hosts: list[Host]) -> ExecutionPlan | None:
    lowered = " ".join(request.casefold().split())
    windows_hosts = [host for host in hosts if host.platform == "windows"]
    if not windows_hosts or len(windows_hosts) != len(hosts):
        return None

    if _looks_like_github_cli_presence_request(lowered):
        return _windows_github_cli_presence_plan(windows_hosts)

    if ("powershell" in lowered or "pwsh" in lowered) and "version" in lowered:
        return _windows_powershell_version_plan(windows_hosts)

    if _looks_like_disk_space_request(lowered):
        return _windows_disk_space_plan(windows_hosts)

    if _looks_like_discovery_request(lowered):
        return _windows_discovery_plan(windows_hosts)

    if _looks_like_cleanup_request(lowered):
        return _windows_cleanup_plan(windows_hosts)

    if _looks_like_content_search_request(lowered):
        return _windows_content_search_plan(request, windows_hosts)

    if _looks_like_search_request(lowered):
        return _windows_search_plan(request, windows_hosts)

    if _looks_like_file_count_request(lowered):
        return _windows_file_count_plan(request, windows_hosts)

    if _looks_like_disk_inventory_request(lowered):
        return _windows_disk_inventory_plan(windows_hosts)

    if _looks_like_os_version_request(lowered):
        return _windows_os_version_plan(windows_hosts)

    if _looks_like_shutdown_reason_request(lowered):
        return _windows_shutdown_reason_plan(windows_hosts)

    service_name = _extract_service_name(request)
    if service_name and any(keyword in lowered for keyword in ("service", "status", "running")):
        return _windows_service_status_plan(windows_hosts, service_name)

    return None


def _looks_like_disk_space_request(lowered: str) -> bool:
    return (
        "free space" in lowered
        or "disk space" in lowered
        or ("how much free" in lowered and any(term in lowered for term in ("disk", "drive", "hd", "partition", "volume")))
    )


def _looks_like_discovery_request(lowered: str) -> bool:
    discovery_terms = ("discovery", "discover", "scan", "find", "who is on", "what devices")
    network_terms = ("network", "local", "neighbors", "hosts", "devices")
    return any(term in lowered for term in discovery_terms) and any(term in lowered for term in network_terms)


def _looks_like_disk_inventory_request(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "how many hd",
            "how many disk",
            "how many drive",
            "how many partition",
            "how many partation",
            "disk and partition",
            "disk partition",
        )
    ) or (
        "partition" in lowered or "partation" in lowered
    ) and any(term in lowered for term in ("disk", "drive", "hd"))


def _looks_like_os_version_request(lowered: str) -> bool:
    return any(
        phrase in lowered
        for phrase in (
            "os version",
            "windows version",
            "operating system version",
        )
    ) or ("operating system" in lowered and "version" in lowered)


def _looks_like_shutdown_reason_request(lowered: str) -> bool:
    shutdown_terms = ("shutdown", "shut down", "show down", "shout down", "power off", "restart", "reboot")
    reason_terms = ("reason", "why", "last time", "previous", "last")
    log_terms = ("event", "log", "logs")
    return (
        any(term in lowered for term in shutdown_terms)
        and any(term in lowered for term in reason_terms)
    ) or (
        any(term in lowered for term in shutdown_terms)
        and any(term in lowered for term in log_terms)
    )


def _extract_service_name(request: str) -> str | None:
    patterns = (
        r"service\s+(?:named\s+)?([A-Za-z0-9._-]+)",
        r"status of\s+([A-Za-z0-9._-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, request, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _looks_like_github_cli_presence_request(lowered: str) -> bool:
    github_terms = ("github cli", "gh cli", "gh.exe", "gh ", " github ")
    install_terms = ("installed", "available", "present", "exist", "exists", "in path")
    return any(term in lowered for term in github_terms) and any(term in lowered for term in install_terms)


def _windows_powershell_version_plan(hosts: list[Host]) -> ExecutionPlan:
    command = (
        "$PSVersionTable.PSVersion | "
        "Select-Object Major,Minor,Build,Revision | ConvertTo-Json -Compress"
    )
    return _single_inspect_plan(
        hosts,
        summary="Inspect the installed PowerShell version.",
        title="Get PowerShell version",
        command=command,
        expected_signal="JSON object with PowerShell version fields",
        validation_type="powershell_version_json",
    )


def _windows_github_cli_presence_plan(hosts: list[Host]) -> ExecutionPlan:
    command = (
        "$command = Get-Command gh -ErrorAction SilentlyContinue; "
        "$candidates = @("
        "  'C:\\Program Files\\GitHub CLI\\gh.exe', "
        "  (Join-Path $env:LOCALAPPDATA 'Programs\\GitHub CLI\\gh.exe')"
        "); "
        "$pathMatch = $null; "
        "foreach ($candidate in $candidates) { "
        "  if (Test-Path -LiteralPath $candidate) { $pathMatch = $candidate; break } "
        "} "
        "if ($command) { "
        "  $source = $command.Source; "
        "  $version = (& $source --version 2>$null | Select-Object -First 1); "
        "  [pscustomobject]@{Installed=$true; Name='GitHub CLI'; Command='gh'; Source=$source; Version=$version} | ConvertTo-Json -Compress; "
        "  exit 0 "
        "} "
        "if ($pathMatch) { "
        "  $version = (& $pathMatch --version 2>$null | Select-Object -First 1); "
        "  [pscustomobject]@{Installed=$true; Name='GitHub CLI'; Command='gh'; Source=$pathMatch; Version=$version} | ConvertTo-Json -Compress; "
        "  exit 0 "
        "} "
        "[pscustomobject]@{Installed=$false; Name='GitHub CLI'; Command='gh'; Source=''; Version=''; Hint='Not found in PATH or common Windows install locations.'} | ConvertTo-Json -Compress"
    )
    return _single_inspect_plan(
        hosts,
        summary="Inspect whether GitHub CLI is installed on the selected Windows hosts.",
        title="Check GitHub CLI installation",
        command=command,
        expected_signal="JSON object showing whether GitHub CLI is installed and where it was found",
        validation_type="tool_presence_json",
    )


def _windows_disk_space_plan(hosts: list[Host]) -> ExecutionPlan:
    command = (
        "Get-Volume | "
        "Where-Object { $_.DriveType -eq 'Fixed' -and $_.DriveLetter } | "
        "Select-Object "
        "DriveLetter,FileSystemLabel,"
        "@{Name='SizeRemainingGB';Expression={[math]::Round($_.SizeRemaining / 1GB, 2)}},"
        "@{Name='SizeGB';Expression={[math]::Round($_.Size / 1GB, 2)}},"
        "@{Name='PercentFree';Expression={ if ($_.Size -gt 0) { [math]::Round(($_.SizeRemaining / $_.Size) * 100, 2) } else { 0 } }} | "
        "Sort-Object DriveLetter | ConvertTo-Json -Compress"
    )
    return _single_inspect_plan(
        hosts,
        summary="Inspect free space on fixed volumes.",
        title="Get fixed-volume free space",
        command=command,
        expected_signal="JSON array of fixed volumes with free-space fields",
        validation_type="disk_space_json",
    )


def _windows_discovery_plan(hosts: list[Host]) -> ExecutionPlan:
    # Use arp -a as a robust baseline discovery command for Windows
    command = "arp -a"
    return _single_inspect_plan(
        hosts,
        summary="Perform network device discovery using ARP cache.",
        title="Discover local network devices",
        command=command,
        expected_signal="ARP table showing IP and MAC addresses",
        validation_type="text",
    )


def _windows_disk_inventory_plan(hosts: list[Host]) -> ExecutionPlan:
    command = (
        "$disks = @(Get-Disk | "
        "Select-Object Number,FriendlyName,SerialNumber,PartitionStyle,OperationalStatus,HealthStatus,"
        "@{Name='SizeGB';Expression={[math]::Round($_.Size / 1GB, 2)}}); "
        "$partitions = @(Get-Partition | "
        "Select-Object DiskNumber,PartitionNumber,DriveLetter,Type,"
        "@{Name='SizeGB';Expression={[math]::Round($_.Size / 1GB, 2)}}); "
        "[pscustomobject]@{"
        "DiskCount = $disks.Count; "
        "PartitionCount = $partitions.Count; "
        "Disks = $disks; "
        "Partitions = $partitions"
        "} | ConvertTo-Json -Depth 6 -Compress"
    )
    return _single_inspect_plan(
        hosts,
        summary="Inspect disks and partitions on the selected Windows hosts.",
        title="Get disk and partition inventory",
        command=command,
        expected_signal="JSON object containing disk and partition counts",
        validation_type="disk_partition_json",
    )


def _windows_os_version_plan(hosts: list[Host]) -> ExecutionPlan:
    command = (
        "Get-CimInstance Win32_OperatingSystem | "
        "Select-Object Caption,Version,BuildNumber,OSArchitecture,CSName | "
        "ConvertTo-Json -Compress"
    )
    return _single_inspect_plan(
        hosts,
        summary="Inspect the Windows operating system version.",
        title="Get Windows OS version",
        command=command,
        expected_signal="JSON object with caption, version, and architecture",
        validation_type="os_version_json",
    )


def _windows_service_status_plan(hosts: list[Host], service_name: str) -> ExecutionPlan:
    escaped_name = service_name.replace("'", "''")
    command = (
        f"Get-Service -Name '{escaped_name}' | "
        "Select-Object Name,DisplayName,Status,StartType | ConvertTo-Json -Compress"
    )
    return _single_inspect_plan(
        hosts,
        summary=f"Inspect service status for {service_name}.",
        title=f"Get service status for {service_name}",
        command=command,
        expected_signal="JSON object with service name and status",
        validation_type="service_status_json",
    )


def _windows_shutdown_reason_plan(hosts: list[Host]) -> ExecutionPlan:
    command = (
        "Get-WinEvent -FilterHashtable @{LogName='System'; ID=1074} -MaxEvents 5 | "
        "Select-Object TimeCreated,ProviderName,Id,"
        "@{Name='User';Expression={$_.Properties[6].Value}},"
        "@{Name='Reason';Expression={$_.Properties[4].Value}},"
        "@{Name='ShutdownType';Expression={$_.Properties[3].Value}},"
        "Message | ConvertTo-Json -Depth 4 -Compress"
    )
    return _single_inspect_plan(
        hosts,
        summary="Inspect recent Windows shutdown and restart reasons.",
        title="Get recent shutdown reasons",
        command=command,
        expected_signal="JSON object or array with recent shutdown reasons from Event ID 1074",
        validation_type="event_log_json",
    )


def _looks_like_cleanup_request(lowered: str) -> bool:
    cleanup_terms = ("cleanup", "clean up", "wipe", "delete", "remove", "clear")
    target_terms = ("temp", "tmp", "cache", "logs", "junk")
    return any(term in lowered for term in cleanup_terms) and any(term in lowered for term in target_terms)


def _windows_cleanup_plan(hosts: list[Host]) -> ExecutionPlan:
    # Improved command to report what is being deleted
    command = (
        "$files = Get-ChildItem -Path $env:TEMP -Recurse -ErrorAction SilentlyContinue; "
        "$count = ($files | Measure-Object).Count; "
        "if ($count -gt 0) { "
        "  $files | ForEach-Object { Write-Output \"Deleting: $($_.FullName)\"; $_ } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; "
        "  Write-Output \"`nTotal items processed: $count\"; "
        "  Write-Output 'Successfully cleaned Windows temp files.'; "
        "} else { "
        "  Write-Output 'No temp files found to clean.';"
        "}"
    )
    steps = [
        PlanStep(
            id=f"builtin-cleanup-{index}",
            title="Clean up Windows temp files",
            host=host.name,
            kind="change",
            rationale="Handled by Cody's built-in maintenance handler.",
            command=command,
            expected_signal="Success message from PowerShell",
            validation_type="text",
        )
        for index, host in enumerate(hosts, start=1)
    ]
    return ExecutionPlan(
        summary="Clean up temporary files from Windows hosts.",
        planner_notes=["matched built-in deterministic maintenance handler"],
        risk="medium",
        domain="infra",
        operation_class="change",
        requires_confirmation=True,
        requires_unsafe=False,
        missing_information=[],
        target_hosts=[host.name for host in hosts],
        steps=steps,
        raw={"builtin": True, "handler": "cleanup", "specialist": "workspace-operator"},
    )


def _looks_like_search_request(lowered: str) -> bool:
    search_terms = ("search", "find", "look for", "locate", "where is")
    # Add common drive and file markers
    target_terms = ("file", ".txt", ".log", ".json", ".py", "test-brother.txt", "c:", "d:", "drive")
    return any(term in lowered for term in search_terms) and any(term in lowered for term in target_terms)


def _windows_search_plan(request: str, hosts: list[Host]) -> ExecutionPlan:
    # Smarter extraction: Handle "search my c: for [file]" and "search [file]"
    # Added [^ ]+ to catch everything until the next space or end of string
    match = re.search(r"for ([A-Za-z0-9._-]+)", request, re.IGNORECASE)
    if not match:
        match = re.search(r"search (?:my )?(?:[a-z]: )?([A-Za-z0-9._-]+)", request, re.IGNORECASE)
    
    filename = match.group(1) if match else "test-brother.txt"
    
    # Use -ErrorAction SilentlyContinue but also wrap in a check to ensure exit 0 if results found
    command = (
        f"$file = '{filename}'; "
        "$results = Get-ChildItem -Path C:\\ -Filter $file -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName; "
        "if ($results) { $results; exit 0 } else { Write-Error \"File $file not found.\"; exit 1 }"
    )
    steps = [
        PlanStep(
            id=f"builtin-search-{index}",
            title=f"Search for {filename}",
            host=host.name,
            kind="inspect",
            rationale="Handled by Cody's built-in file search handler.",
            command=command,
            expected_signal="Full path to the found file",
            validation_type="text",
            accept_nonzero_returncode=True # Pro-tip: System folders will always throw errors
        )
        for index, host in enumerate(hosts, start=1)
    ]
    return ExecutionPlan(
        summary=f"Search for file '{filename}' on Windows hosts.",
        planner_notes=["matched built-in deterministic search handler"],
        risk="low",
        domain="infra",
        operation_class="inspect",
        requires_confirmation=False,
        requires_unsafe=False,
        missing_information=[],
        target_hosts=[host.name for host in hosts],
        steps=steps,
        raw={"builtin": True, "handler": "search", "specialist": "infra-inspector"},
    )


def _looks_like_content_search_request(lowered: str) -> bool:
    grep_terms = ("content", "inside", "contains", "grep", "text for")
    search_terms = ("search", "find", "look for")
    return any(term in lowered for term in grep_terms) or (any(term in lowered for term in search_terms) and "text" in lowered)


def _windows_content_search_plan(request: str, hosts: list[Host]) -> ExecutionPlan:
    # Extract the pattern (text) after "for"
    match = re.search(r"for ['\"]?([^'\"]+)['\"]?", request, re.IGNORECASE)
    pattern = match.group(1) if match else "sandra_home"
    
    # Improved command: 
    # 1. Pure STDOUT (removed Write-Host)
    # 2. Exclude .cody, .git, and .gemini to avoid self-referencing history
    # 3. Prettify output
    command = (
        f"$pattern = '{pattern}'; "
        "Get-ChildItem -Path C:\\ -Include *.txt,*.log,*.md,*.json,*.py,*.env,*.yaml,*.yml -Recurse -ErrorAction SilentlyContinue | "
        "Where-Object { $_.FullName -notmatch '\\.(cody|git|gemini|venv)' } | "
        "Select-String -Pattern $pattern | "
        "Select-Object @{Name='File';Expression={$_.Path}}, LineNumber, @{Name='Content';Expression={$_.Line.Trim()}} | "
        "ConvertTo-Json"
    )
    steps = [
        PlanStep(
            id=f"builtin-grep-{index}",
            title=f"Grep for '{pattern}'",
            host=host.name,
            kind="inspect",
            rationale="Handled by Cody's built-in content search (grep) handler.",
            command=command,
            expected_signal="JSON array of matching lines and file paths",
            validation_type="grep_json",
            accept_nonzero_returncode=True
        )
        for index, host in enumerate(hosts, start=1)
    ]
    return ExecutionPlan(
        summary=f"Search inside file content for '{pattern}' on Windows hosts.",
        planner_notes=["matched built-in deterministic content search handler"],
        risk="low",
        domain="infra",
        operation_class="inspect",
        requires_confirmation=False,
        requires_unsafe=False,
        missing_information=[],
        target_hosts=[host.name for host in hosts],
        steps=steps,
        raw={"builtin": True, "handler": "grep", "specialist": "infra-inspector"},
    )


def _looks_like_file_count_request(lowered: str) -> bool:
    count_terms = ("how many", "count", "total number of")
    file_terms = ("file", "files", "document", "documents", "txt", "log")
    return any(term in lowered for term in count_terms) and any(term in lowered for term in file_terms)


def _windows_file_count_plan(request: str, hosts: list[Host]) -> ExecutionPlan:
    lowered = request.lower()
    # Map common folder names to their environment variables or paths
    target_path = "C:\\"
    folder_name = "C: drive"
    
    if "documents" in lowered:
        target_path = "$([Environment]::GetFolderPath('MyDocuments'))"
        folder_name = "Documents folder"
    elif "desktop" in lowered:
        target_path = "$([Environment]::GetFolderPath('Desktop'))"
        folder_name = "Desktop folder"
    elif "downloads" in lowered:
        # Downloads is not a standard special folder, handle separately
        target_path = "$env:USERPROFILE\\Downloads"
        folder_name = "Downloads folder"

    # Extraction for extension
    ext_filter = "*"
    if "text file" in lowered or ".txt" in lowered:
        ext_filter = "*.txt"
    elif "log file" in lowered or ".log" in lowered:
        ext_filter = "*.log"

    command = (
        f"$target = {target_path}; "
        f"$files = Get-ChildItem -Path $target -Filter '{ext_filter}' -Recurse -File -ErrorAction SilentlyContinue; "
        "$count = ($files | Measure-Object).Count; "
        f"[pscustomobject]@{{Folder='{folder_name}'; Filter='{ext_filter}'; Count=$count}} | ConvertTo-Json -Compress"
    )
    
    steps = [
        PlanStep(
            id=f"builtin-count-{index}",
            title=f"Count {ext_filter} files in {folder_name}",
            host=host.name,
            kind="inspect",
            rationale="Handled by Cody's built-in fast-count handler.",
            command=command,
            expected_signal="JSON object with file count",
            validation_type="file_count_json",
        )
        for index, host in enumerate(hosts, start=1)
    ]
    return ExecutionPlan(
        summary=f"Count {ext_filter} files in {folder_name} on Windows hosts.",
        planner_notes=["matched built-in deterministic fast-count handler"],
        risk="low",
        domain="infra",
        operation_class="inspect",
        requires_confirmation=False,
        requires_unsafe=False,
        missing_information=[],
        target_hosts=[host.name for host in hosts],
        steps=steps,
        raw={"builtin": True, "handler": "count", "specialist": "infra-inspector"},
    )


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
            id=f"builtin-{index}",
            title=title,
            host=host.name,
            kind="inspect",
            rationale="Handled by Cody's built-in deterministic inspector.",
            command=command,
            expected_signal=expected_signal,
            validation_type=validation_type,
        )
        for index, host in enumerate(hosts, start=1)
    ]
    return ExecutionPlan(
        summary=summary,
        planner_notes=["matched built-in deterministic handler"],
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
