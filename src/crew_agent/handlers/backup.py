from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from crew_agent.core.models import AppConfig, ExecutionPlan, Host
from crew_agent.core.paths import ensure_app_dirs
from crew_agent.executors.runtime import execute_host_command


def _snapshot_commands(host: Host) -> dict[str, str]:
    if host.platform == "windows":
        return {
            "hostname": "hostname",
            "powershell_version": (
                "$PSVersionTable.PSVersion | "
                "Select-Object Major,Minor,Build,Revision | ConvertTo-Json -Compress"
            ),
            "os": (
                "Get-CimInstance Win32_OperatingSystem | "
                "Select-Object Caption,Version,BuildNumber,CSName,LastBootUpTime | "
                "ConvertTo-Json -Compress"
            ),
            "services": (
                "Get-Service | Select-Object -First 50 Name,Status,StartType | "
                "ConvertTo-Json -Compress"
            ),
            "filesystems": (
                "Get-PSDrive -PSProvider FileSystem | "
                "Select-Object Name,Free,Used,Root | ConvertTo-Json -Compress"
            ),
        }
    return {
        "hostname": "hostname",
        "uname": "uname -a",
        "os_release": "cat /etc/os-release",
        "disk": "df -h",
        "services": "systemctl list-units --type=service --state=running --no-pager --no-legend | head -n 50",
    }


def create_backup_snapshot(
    request: str,
    plan: ExecutionPlan,
    hosts: list[Host],
    config: AppConfig,
) -> Path:
    paths = ensure_app_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = paths.backups_dir / f"{stamp}-{uuid4().hex[:8]}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "request": request,
        "summary": plan.summary,
        "risk": plan.risk,
        "target_hosts": plan.target_hosts,
        "created_at": datetime.now().isoformat(),
        "hosts": [],
    }

    for host in hosts:
        host_payload = {
            "name": host.name,
            "platform": host.platform,
            "transport": host.transport,
            "address": host.address,
            "snapshots": {},
        }
        for name, command in _snapshot_commands(host).items():
            result = execute_host_command(
                host=host,
                command=command,
                config=config,
                permission_mode="full",
            )
            host_payload["snapshots"][name] = {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        manifest["hosts"].append(host_payload)

    (backup_dir / "snapshot.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return backup_dir
