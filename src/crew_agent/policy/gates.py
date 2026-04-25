from __future__ import annotations

import re

from crew_agent.core.models import ExecutionPlan, Host


WINDOWS_BLOCKED_PATTERNS = (
    "remove-item",
    "del ",
    "erase ",
    "format-volume",
    "clear-disk",
    "diskpart",
    "reg delete",
    "sc.exe delete",
)

LINUX_BLOCKED_PATTERNS = (
    "rm -rf /",
    "mkfs",
    "userdel",
    "iptables -f",
    "systemctl disable",
)

WINDOWS_ELEVATED_PATTERNS = (
    "shutdown",
    "stop-computer",
    "restart-computer",
    "restart-service",
    "stop-service",
    "set-service",
    "new-itemproperty",
    "set-itemproperty",
)

LINUX_ELEVATED_PATTERNS = (
    "shutdown",
    "reboot",
    "poweroff",
    "systemctl restart",
    "systemctl stop",
    "systemctl disable",
    "apt remove",
    "dnf remove",
    "yum remove",
)


def guard_command(host: Host, command: str, permission_mode: str) -> None:
    lowered = f" {command.casefold()} "
    full_only_patterns = (
        WINDOWS_BLOCKED_PATTERNS if host.platform == "windows" else LINUX_BLOCKED_PATTERNS
    )
    elevated_patterns = (
        WINDOWS_ELEVATED_PATTERNS
        if host.platform == "windows"
        else LINUX_ELEVATED_PATTERNS
    )

    if permission_mode not in {"safe", "elevated", "full"}:
        raise ValueError(f"Unknown permission mode: {permission_mode}")

    if permission_mode != "full" and any(_pattern_matches(lowered, pattern) for pattern in full_only_patterns):
        raise PermissionError(
            f"Blocked potentially destructive command for host '{host.name}'. "
            "Switch permissions to full if this is intentional."
        )
    if permission_mode == "safe" and any(_pattern_matches(lowered, pattern) for pattern in elevated_patterns):
        raise PermissionError(
            f"Blocked elevated command for host '{host.name}'. "
            "Switch permissions to elevated or full if this is intentional."
        )


def approval_reasons_for_plan(
    plan: ExecutionPlan,
    permission_mode: str,
    approval_policy: str,
) -> list[str]:
    reasons: list[str] = []
    if approval_policy == "always":
        reasons.append("approval policy is set to always")
    elif approval_policy == "risky":
        if (
            plan.domain == "infra"
            and plan.operation_class == "inspect"
            and plan.risk == "low"
            and not plan.requires_unsafe
        ):
            return reasons
        if plan.domain == "code" and plan.operation_class == "inspect" and plan.risk == "low":
            return reasons
        if plan.domain == "workspace" and plan.operation_class in {"write_text", "read"}:
            return reasons
        if plan.requires_confirmation:
            reasons.append("planner requested confirmation")
        if plan.requires_unsafe:
            reasons.append("planner marked the request as unsafe")
        if plan.risk == "high":
            reasons.append("plan risk is high")
    return reasons


def _pattern_matches(command: str, pattern: str) -> bool:
    escaped = re.escape(pattern.casefold().strip())
    escaped = escaped.replace(r"\ ", r"\s+")
    if re.fullmatch(r"[a-z0-9_.-]+", pattern.casefold().strip()):
        regex = rf"(?<![a-z0-9_.-]){escaped}(?![a-z0-9_.-])"
    else:
        regex = escaped
    return re.search(regex, command) is not None
