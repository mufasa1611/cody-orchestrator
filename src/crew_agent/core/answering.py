from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from crew_agent.core.models import ExecutionPlan, StepExecutionResult


@dataclass(frozen=True)
class AnswerSummary:
    title: str
    lines: list[str] = field(default_factory=list)
    tone: str = "green"


def build_answer_summaries(
    plan: ExecutionPlan,
    results: list[StepExecutionResult],
    ui: TerminalUI | None = None,
) -> list[AnswerSummary]:
    summaries: list[AnswerSummary] = []
    for result in results:
        if not result.success:
            continue
        summary = _build_result_summary(plan, result, ui)
        if summary is not None:
            summaries.append(summary)
    return summaries


def _build_result_summary(
    plan: ExecutionPlan,
    result: StepExecutionResult,
    ui: TerminalUI | None = None,
) -> AnswerSummary | None:
    def link(text: str, path: str) -> str:
        if ui and hasattr(ui, "_make_link"):
            return ui._make_link(text, path)
        return text

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    combined_output = "\n".join(part for part in (stdout, stderr) if part).strip()
    validation_type = result.validation_type or ""

    if validation_type == "workspace_file_info_json":
        payload = _load_json(stdout)
        if isinstance(payload, dict):
            p = payload.get('Path', '-')
            return AnswerSummary(
                title="Result",
                lines=[
                    f"Created file: {payload.get('Name', '-')}",
                    f"Folder: {payload.get('Parent', '-')}",
                    f"Path: {link(p, p)}",
                ],
            )

    if validation_type == "tool_presence_json":
        payload = _load_json(stdout)
        if isinstance(payload, dict):
            installed = bool(payload.get("Installed"))
            lines = [
                f"Tool: {payload.get('Name', '-')}",
                f"Installed: {'yes' if installed else 'no'}",
            ]
            source = str(payload.get("Source") or "").strip()
            version = str(payload.get("Version") or "").strip()
            hint = str(payload.get("Hint") or "").strip()
            if source:
                lines.append(f"Source: {source}")
            if version:
                lines.append(f"Version: {version}")
            if hint:
                lines.append(hint)
            return AnswerSummary(
                title="Answer",
                lines=lines,
                tone="green" if installed else "yellow",
            )

    if validation_type == "workspace_file_contains_json":
        payload = _load_json(stdout)
        if isinstance(payload, dict):
            return AnswerSummary(
                title="Result",
                lines=[
                    f"Updated file: {payload.get('Name', '-')}",
                    f"Folder: {payload.get('Parent', '-')}",
                    f"Inserted text: {payload.get('InsertedText', '-')}",
                    f"Path: {payload.get('Path', '-')}",
                ],
            )

    if validation_type == "repo_file_text" and combined_output:
        lines = combined_output.splitlines()
        path_line = next((line for line in lines if line.startswith("FILE: ")), "")
        preview = [line for line in lines if not line.startswith("FILE: ")][:5]
        summary_lines = []
        if path_line:
            summary_lines.append(path_line.replace("FILE: ", "File: ", 1))
        if preview:
            summary_lines.append("Preview:")
            summary_lines.extend(preview)
        return AnswerSummary(title="Answer", lines=summary_lines or lines[:5])

    if validation_type in {"repo_search_text", "repo_file_list_text", "git_status_text"} and combined_output:
        lines = combined_output.splitlines()
        if len(lines) == 1 and lines[0] in {
            "No matches found.",
            "No matching files found.",
            "No files found.",
            "Working tree clean.",
            "Not a git repository.",
            "git is not available.",
        }:
            return AnswerSummary(title="Answer", lines=[lines[0]])
        return AnswerSummary(
            title="Answer",
            lines=[f"Matches: {len(lines)}", *lines[:5]],
        )

    if validation_type == "test_run_text" and combined_output:
        return AnswerSummary(
            title="Test Results",
            lines=_summarize_test_output(combined_output),
            tone="yellow" if _tests_have_failures(combined_output) else "green",
        )

    if validation_type == "event_log_json":
        payload = _load_json(stdout)
        items = payload if isinstance(payload, list) else [payload]
        rows = [item for item in items if isinstance(item, dict)]
        if rows:
            latest = rows[0]
            initiator = _extract_initiator(str(latest.get("Message") or ""))
            lines = [
                f"Latest event: {_format_time(latest.get('TimeCreated'))}",
                f"User: {latest.get('User') or '-'}",
                f"Action: {latest.get('Reason') or latest.get('ShutdownType') or '-'}",
            ]
            if initiator:
                lines.append(f"Initiated by: {initiator}")
            return AnswerSummary(title="Answer", lines=lines)

    if validation_type == "disk_space_json":
        payload = _load_json(stdout)
        items = payload if isinstance(payload, list) else [payload]
        rows = [item for item in items if isinstance(item, dict)]
        if rows:
            lines = []
            for item in rows[:5]:
                lines.append(
                    f"{item.get('DriveLetter') or '-'}: {item.get('SizeRemainingGB') or '-'} GB free of {item.get('SizeGB') or '-'} GB ({item.get('PercentFree') or '-'}%)"
                )
            return AnswerSummary(title="Free Space", lines=lines)

    if validation_type == "disk_partition_json":
        payload = _load_json(stdout)
        if isinstance(payload, dict):
            return AnswerSummary(
                title="Answer",
                lines=[
                    f"Disk count: {payload.get('DiskCount', '-')}",
                    f"Partition count: {payload.get('PartitionCount', '-')}",
                ],
            )

    if validation_type == "service_status_json":
        payload = _load_json(stdout)
        items = payload if isinstance(payload, list) else [payload]
        rows = [item for item in items if isinstance(item, dict)]
        if rows:
            item = rows[0]
            return AnswerSummary(
                title="Answer",
                lines=[
                    f"Service: {item.get('DisplayName') or item.get('Name') or '-'}",
                    f"Status: {item.get('Status') or '-'}",
                    f"Start type: {item.get('StartType') or '-'}",
                ],
            )

    if validation_type == "os_version_json":
        payload = _load_json(stdout)
        if isinstance(payload, dict):
            return AnswerSummary(
                title="Answer",
                lines=[
                    f"OS: {payload.get('Caption') or '-'}",
                    f"Version: {payload.get('Version') or '-'}",
                    f"Build: {payload.get('BuildNumber') or '-'}",
                    f"Architecture: {payload.get('OSArchitecture') or '-'}",
                ],
            )

    if validation_type == "powershell_version_json":
        payload = _load_json(stdout)
        if isinstance(payload, dict):
            return AnswerSummary(
                title="Answer",
                lines=[
                    "PowerShell version: "
                    f"{payload.get('Major', '-')}.{payload.get('Minor', '-')}.{payload.get('Build', '-')}.{payload.get('Revision', '-')}"
                ],
            )

    if validation_type == "grep_json":
        payload = _load_json(stdout)
        items = payload if isinstance(payload, list) else [payload]
        rows = [item for item in items if isinstance(item, dict)]
        if rows:
            unique_files = sorted(list(set(row.get("File") for row in rows if row.get("File"))))
            lines = [f"Found {len(rows)} matches in {len(unique_files)} file(s):"]
            for f in unique_files[:3]:
                lines.append(f"- {f}")
            if len(unique_files) > 3:
                lines.append(f"... and {len(unique_files) - 3} more files.")
            return AnswerSummary(title="Answer", lines=lines)
        return AnswerSummary(title="Answer", lines=["No content matches found."])

    if validation_type == "file_count_json":
        payload = _load_json(stdout)
        if isinstance(payload, dict):
            count = payload.get("Count", 0)
            f_type = payload.get("Type", "items")
            folder = payload.get("Folder", "target")
            return AnswerSummary(
                title="Answer",
                lines=[f"Found {count} {f_type} in {folder}."]
            )

    if validation_type == "file_count_json":
        payload = _load_json(stdout)
        if isinstance(payload, dict):
            count = payload.get("Count", 0)
            f_type = payload.get("Type", "items")
            folder = payload.get("Folder", "target")
            return AnswerSummary(
                title="Answer",
                lines=[f"Found {count} {f_type} in {folder}."]
            )

    if result.artifact_path:
        return AnswerSummary(title="Answer", lines=[result.artifact_path])
        return AnswerSummary(title="Answer", lines=[result.artifact_path])

    if plan.operation_class == "inspect" and combined_output:
        # PRO AUTO-JSON: Detect if the model output a JSON array of items
        payload = _load_json(combined_output)
        if isinstance(payload, list) and len(payload) > 0:
            count = len(payload)
            lines = [f"Found {count} items in JSON result:"]
            for item in payload[:5]:
                if isinstance(item, dict):
                    name = item.get('Name') or item.get('FullName') or item.get('File') or str(list(item.values())[0])
                    lines.append(f"- {name}")
                else:
                    lines.append(f"- {str(item)}")
            if count > 5:
                lines.append(f"... and {count - 5} more items.")
            return AnswerSummary(title="Answer Summary", lines=lines)

        lines = [line for line in combined_output.splitlines() if line.strip() and not line.startswith("----") and line.strip().lower() not in ("name", "fullname", "count")]
        if len(lines) > 1:
            return AnswerSummary(
                title="Results",
                lines=[f"Found {len(lines)} items:"] + [f"- {line}" for line in lines[:10]] + (["..."] if len(lines) > 10 else []),
            )
        return AnswerSummary(title="Answer", lines=[combined_output[:500]])

    return None


def _load_json(text: str):
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _format_time(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        match = re.fullmatch(r"/Date\((\d+)\)/", value)
        if match:
            timestamp = int(match.group(1)) / 1000
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _extract_initiator(message: str) -> str | None:
    patterns = (
        r'The process\s+(.+?)\s+\([^)]+\)\s+has initiated',
        r'Vom Prozess\s+"(.+?)\s+\([^)]+\)"\s+wurde',
        r'The process\s+(.+?)\s+has initiated',
    )
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().strip('"')
    return None


def _summarize_test_output(output: str) -> list[str]:
    lines: list[str] = []
    pytest_summary = re.search(r"=+ (.+?) in [0-9.]+s =+", output)
    if pytest_summary:
        lines.append(pytest_summary.group(1).strip())
    unittest_ok = re.search(r"Ran (\d+) tests? in ([0-9.]+)s\s+OK", output, flags=re.DOTALL)
    if unittest_ok:
        lines.append(f"Ran {unittest_ok.group(1)} tests in {unittest_ok.group(2)}s")
        lines.append("Outcome: OK")
    unittest_failed = re.search(
        r"Ran (\d+) tests? in ([0-9.]+)s\s+FAILED\s+\((.+?)\)",
        output,
        flags=re.DOTALL,
    )
    if unittest_failed:
        lines.append(f"Ran {unittest_failed.group(1)} tests in {unittest_failed.group(2)}s")
        lines.append(f"Outcome: FAILED ({unittest_failed.group(3)})")
    if not lines:
        first_meaningful = [line.strip() for line in output.splitlines() if line.strip()]
        if first_meaningful:
            lines.append(first_meaningful[-1][:160])
    detail = _extract_test_failure_detail(output)
    if detail:
        lines.append(detail)
    return lines[:5]


def _tests_have_failures(output: str) -> bool:
    lowered = output.casefold()
    return " failed" in lowered or "failures=" in lowered or "errors=" in lowered


def _extract_test_failure_detail(output: str) -> str | None:
    match = re.search(r"(AssertionError:.+)", output)
    if match:
        return match.group(1)[:160]
    match = re.search(r"(FAILED \(.+?\))", output)
    if match:
        return match.group(1)[:160]
    return None
