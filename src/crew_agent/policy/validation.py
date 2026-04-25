from __future__ import annotations

import json

from crew_agent.core.models import PlanStep


def validate_step_stdout(step: PlanStep, stdout: str) -> str | None:
    text = stdout.strip()
    if step.kind == "inspect" and not text:
        return "inspection returned no stdout"

    if step.validation_type:
        return _validate_typed_output(step.validation_type, text)

    if step.kind == "inspect" and "convertto-json" in step.command.casefold():
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            return f"inspection did not return valid JSON: {exc.msg}"

    return None


def _validate_typed_output(validation_type: str, stdout: str) -> str | None:
    if not stdout:
        return "inspection returned no stdout"

    known_types = {
        "workspace_text_file",
        "workspace_file_info_json",
        "workspace_file_contains_json",
        "plain_text",
        "repo_file_text",
        "repo_search_text",
        "repo_file_list_text",
        "git_status_text",
        "test_run_text",
        "powershell_version_json",
        "os_version_json",
        "disk_space_json",
        "disk_partition_json",
        "service_status_json",
        "event_log_json",
    }
    if validation_type not in known_types:
        return None

    if validation_type == "workspace_text_file":
        if len(stdout.strip()) == 0:
            return "workspace file appears to be empty"
        return None

    if validation_type == "workspace_file_info_json":
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return f"workspace file info did not return valid JSON: {exc.msg}"
        if not isinstance(payload, dict):
            return "expected a JSON object for workspace file info"
        required = ("Path", "Name", "Parent", "Exists")
        missing = [name for name in required if name not in payload]
        if missing:
            return f"missing workspace file info fields: {', '.join(missing)}"
        if not payload.get("Exists"):
            return "workspace file was not created"
        return None

    if validation_type == "workspace_file_contains_json":
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return f"workspace file edit did not return valid JSON: {exc.msg}"
        if not isinstance(payload, dict):
            return "expected a JSON object for workspace file edit info"
        required = ("Path", "Name", "Parent", "Exists", "InsertedText", "ContainsExpected")
        missing = [name for name in required if name not in payload]
        if missing:
            return f"missing workspace file edit fields: {', '.join(missing)}"
        if not payload.get("Exists"):
            return "workspace file was not found"
        if not payload.get("ContainsExpected"):
            return "workspace file does not contain the inserted text"
        return None

    if validation_type == "plain_text":
        return None

    if validation_type in {
        "repo_file_text",
        "repo_search_text",
        "repo_file_list_text",
        "git_status_text",
        "test_run_text",
    }:
        return None

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return f"inspection did not return valid JSON: {exc.msg}"

    if validation_type == "powershell_version_json":
        if not isinstance(payload, dict):
            return "expected a JSON object for PowerShell version"
        required = ("Major", "Minor", "Build", "Revision")
        missing = [name for name in required if name not in payload]
        if missing:
            return f"missing PowerShell version fields: {', '.join(missing)}"
        return None

    if validation_type == "os_version_json":
        if not isinstance(payload, dict):
            return "expected a JSON object for OS version"
        required = ("Caption", "Version", "BuildNumber", "OSArchitecture")
        missing = [name for name in required if name not in payload]
        if missing:
            return f"missing OS version fields: {', '.join(missing)}"
        return None

    if validation_type == "disk_space_json":
        items = payload if isinstance(payload, list) else [payload]
        if not items:
            return "expected at least one fixed volume in disk-space output"
        for item in items:
            if not isinstance(item, dict):
                return "expected disk-space items to be JSON objects"
            required = ("DriveLetter", "SizeRemainingGB", "SizeGB", "PercentFree")
            missing = [name for name in required if name not in item]
            if missing:
                return f"missing disk-space fields: {', '.join(missing)}"
        return None

    if validation_type == "disk_partition_json":
        if not isinstance(payload, dict):
            return "expected a JSON object for disk inventory"
        disks = payload.get("Disks")
        partitions = payload.get("Partitions")
        if not isinstance(disks, list) or not isinstance(partitions, list):
            return "disk inventory must include Disks and Partitions arrays"
        if payload.get("DiskCount") != len(disks):
            return "DiskCount does not match the number of disks returned"
        if payload.get("PartitionCount") != len(partitions):
            return "PartitionCount does not match the number of partitions returned"
        if len(disks) == 0:
            return "expected at least one disk in disk inventory"
        return None

    if validation_type == "service_status_json":
        items = payload if isinstance(payload, list) else [payload]
        if not items:
            return "expected at least one service in service-status output"
        for item in items:
            if not isinstance(item, dict):
                return "expected service-status items to be JSON objects"
            required = ("Name", "Status")
            missing = [name for name in required if name not in item]
            if missing:
                return f"missing service-status fields: {', '.join(missing)}"
        return None

    if validation_type == "event_log_json":
        items = payload if isinstance(payload, list) else [payload]
        if not items:
            return "expected at least one event log entry"
        for item in items:
            if not isinstance(item, dict):
                return "expected event-log items to be JSON objects"
            required = ("TimeCreated", "ProviderName", "Id", "Message")
            missing = [name for name in required if name not in item]
            if missing:
                return f"missing event-log fields: {', '.join(missing)}"
        return None

    return None
