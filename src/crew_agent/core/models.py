from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppConfig:
    model: str = "gemma4:latest"
    base_url: str | None = None
    planner_timeout_seconds: int = 180
    command_timeout_seconds: int = 120
    ssh_connect_timeout_seconds: int = 10
    show_planner_notes: bool = True
    operator_mode: bool = True
    permission_mode: str = "safe"
    backup_on_full: bool = True
    approval_policy: str = "risky"


@dataclass
class Host:
    name: str
    platform: str
    transport: str
    address: str | None = None
    user: str | None = None
    port: int | None = None
    shell: str | None = None
    tags: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class PlanStep:
    id: str
    title: str
    host: str
    command: str
    rationale: str = ""
    kind: str = "change"
    verify_command: str | None = None
    expected_signal: str | None = None
    validation_type: str | None = None
    accept_nonzero_returncode: bool = False
    continue_on_failure: bool = False


@dataclass
class ExecutionPlan:
    summary: str
    planner_notes: list[str] = field(default_factory=list)
    risk: str = "medium"
    domain: str = "infra"
    operation_class: str = "change"
    requires_confirmation: bool = False
    requires_unsafe: bool = False
    missing_information: list[str] = field(default_factory=list)
    target_hosts: list[str] = field(default_factory=list)
    steps: list[PlanStep] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class StepExecutionResult:
    step_id: str
    host: str
    title: str
    command: str
    success: bool
    returncode: int
    stdout: str
    stderr: str
    verify: CommandResult | None
    duration_seconds: float
    validation_type: str | None = None
    artifact_path: str | None = None
    validation_error: str | None = None
