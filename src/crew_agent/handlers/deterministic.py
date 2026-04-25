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
