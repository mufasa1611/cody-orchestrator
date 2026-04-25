from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

import yaml

from crew_agent.core.models import AppConfig, Host
from crew_agent.core.paths import ensure_app_dirs


DEFAULT_CONFIG = {
    "model": "gemma4:latest",
    "base_url": None,
    "planner_timeout_seconds": 180,
    "command_timeout_seconds": 120,
    "ssh_connect_timeout_seconds": 10,
    "show_planner_notes": True,
    "operator_mode": True,
    "permission_mode": "safe",
    "backup_on_full": True,
    "approval_policy": "risky",
}


DEFAULT_INVENTORY = {
    "hosts": [
        {
            "name": "local-win",
            "platform": "windows",
            "transport": "local",
            "address": "localhost",
            "tags": ["local", "windows"],
            "enabled": True,
        },
        {
            "name": "sample-linux",
            "platform": "linux",
            "transport": "ssh",
            "address": "192.168.1.20",
            "user": "ubuntu",
            "port": 22,
            "tags": ["linux", "example"],
            "enabled": False,
        },
    ]
}


def _read_yaml(path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML object in {path}")
    return data


def bootstrap_local_files() -> None:
    paths = ensure_app_dirs()
    if not paths.config_file.exists():
        paths.config_file.write_text(
            yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False),
            encoding="utf-8",
        )
    if not paths.inventory_file.exists():
        paths.inventory_file.write_text(
            yaml.safe_dump(DEFAULT_INVENTORY, sort_keys=False),
            encoding="utf-8",
        )


def load_config() -> AppConfig:
    bootstrap_local_files()
    paths = ensure_app_dirs()
    raw = {**DEFAULT_CONFIG, **_read_yaml(paths.config_file)}
    model = os.getenv("CODY_MODEL") or raw.get("model", DEFAULT_CONFIG["model"])
    base_url = os.getenv("CODY_BASE_URL") or raw.get("base_url")
    return AppConfig(
        model=str(model),
        base_url=base_url,
        planner_timeout_seconds=int(
            raw.get("planner_timeout_seconds", DEFAULT_CONFIG["planner_timeout_seconds"])
        ),
        command_timeout_seconds=int(
            raw.get("command_timeout_seconds", DEFAULT_CONFIG["command_timeout_seconds"])
        ),
        ssh_connect_timeout_seconds=int(
            raw.get(
                "ssh_connect_timeout_seconds",
                DEFAULT_CONFIG["ssh_connect_timeout_seconds"],
            )
        ),
        show_planner_notes=bool(
            raw.get("show_planner_notes", DEFAULT_CONFIG["show_planner_notes"])
        ),
        operator_mode=bool(
            raw.get("operator_mode", DEFAULT_CONFIG["operator_mode"])
        ),
        permission_mode=str(
            raw.get("permission_mode", DEFAULT_CONFIG["permission_mode"])
        ).lower(),
        backup_on_full=bool(raw.get("backup_on_full", DEFAULT_CONFIG["backup_on_full"])),
        approval_policy=str(
            raw.get("approval_policy", DEFAULT_CONFIG["approval_policy"])
        ).lower(),
    )


def save_config(config: AppConfig) -> None:
    paths = ensure_app_dirs()
    payload = {
        "model": config.model,
        "base_url": config.base_url,
        "planner_timeout_seconds": config.planner_timeout_seconds,
        "command_timeout_seconds": config.command_timeout_seconds,
        "ssh_connect_timeout_seconds": config.ssh_connect_timeout_seconds,
        "show_planner_notes": config.show_planner_notes,
        "operator_mode": config.operator_mode,
        "permission_mode": config.permission_mode,
        "backup_on_full": config.backup_on_full,
        "approval_policy": config.approval_policy,
    }
    paths.config_file.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def load_inventory() -> list[Host]:
    bootstrap_local_files()
    paths = ensure_app_dirs()
    raw = _read_yaml(paths.inventory_file)
    hosts_raw = raw.get("hosts", [])
    if not isinstance(hosts_raw, list):
        raise ValueError("Inventory file must contain a top-level 'hosts' list")

    hosts: list[Host] = []
    for item in hosts_raw:
        if not isinstance(item, dict):
            continue
        tags = item.get("tags") or []
        hosts.append(
            Host(
                name=str(item["name"]),
                platform=str(item["platform"]).lower(),
                transport=str(item["transport"]).lower(),
                address=item.get("address"),
                user=item.get("user"),
                port=int(item["port"]) if item.get("port") is not None else None,
                shell=item.get("shell"),
                tags=[str(tag).lower() for tag in tags],
                enabled=bool(item.get("enabled", True)),
            )
        )
    return hosts


def save_inventory(hosts: list[Host]) -> None:
    paths = ensure_app_dirs()
    payload = {"hosts": [asdict(host) for host in hosts]}
    paths.inventory_file.write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def filter_hosts(
    hosts: list[Host],
    host_names: list[str] | None = None,
    tags: list[str] | None = None,
) -> list[Host]:
    host_names = [name.lower() for name in (host_names or [])]
    tags = [tag.lower() for tag in (tags or [])]

    selected = [host for host in hosts if host.enabled]
    if host_names:
        selected = [host for host in selected if host.name.lower() in host_names]
    if tags:
        selected = [host for host in selected if all(tag in host.tags for tag in tags)]
    return selected


def host_map(hosts: list[Host]) -> dict[str, Host]:
    return {host.name: host for host in hosts}
