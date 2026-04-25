from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from crew_agent.core.answering import AnswerSummary
from crew_agent.core.models import ExecutionPlan, Host, StepExecutionResult
from crew_agent.core.paths import ensure_app_dirs


class TerminalUI:
    def __init__(self) -> None:
        self.console = Console()
        self.last_workspace_artifact_path = self._load_last_workspace_artifact_path()

    def _make_link(self, text: str, path: str) -> str:
        """Create a terminal-compatible hyperlink (OSC 8)."""
        # Convert path to a proper file URI for maximum compatibility
        import pathlib
        uri = Path(path).resolve().as_uri()
        return f"[link={uri}]{text}[/link]"

    def banner(self, subtitle: str | None = None) -> None:
        text = "Autonomous Infrastructure Orchestrator created by Mufasa (M.Farid)"
        if subtitle:
            text = f"{text}\n{subtitle}"
        self.console.print(Panel(text, title="cody", border_style="cyan"))

    def phase(self, kind: str, message: str) -> None:
        colors = {
            "thinking": "cyan",
            "plan": "magenta",
            "exec": "yellow",
            "verify": "blue",
            "done": "green",
            "warn": "red",
        }
        color = colors.get(kind, "white")
        label = kind.upper().rjust(8)
        self.console.print(f"[bold {color}]{label}[/bold {color}] {message}")

    def show_inventory(self, hosts: list[Host]) -> None:
        table = Table(title="Inventory")
        table.add_column("Name")
        table.add_column("Platform")
        table.add_column("Transport")
        table.add_column("Address")
        table.add_column("Tags")
        table.add_column("Enabled")
        for host in hosts:
            table.add_row(
                host.name,
                host.platform,
                host.transport,
                host.address or "-",
                ", ".join(host.tags) or "-",
                "yes" if host.enabled else "no",
            )
        self.console.print(table)

    def show_plan(self, plan: ExecutionPlan, hosts: list[Host], compact: bool = False) -> None:
        host_lookup = {host.name: host for host in hosts}
        self.phase("plan", plan.summary)
        if plan.planner_notes:
            for note in plan.planner_notes:
                self.phase("thinking", note)
        if plan.missing_information:
            for item in plan.missing_information:
                self.phase("warn", f"missing information: {item}")
        if compact:
            for index, step in enumerate(plan.steps, start=1):
                host = host_lookup[step.host]
                self.console.print(
                    f"  step {index}: {host.name} | {step.kind} | {step.title}",
                    markup=False,
                )
            return
        table = Table(title=f"Execution Plan ({plan.risk} risk)")
        table.add_column("#", justify="right")
        table.add_column("Host")
        table.add_column("Platform")
        table.add_column("Kind")
        table.add_column("Title")
        table.add_column("Command")
        for index, step in enumerate(plan.steps, start=1):
            host = host_lookup[step.host]
            table.add_row(
                str(index),
                host.name,
                host.platform,
                step.kind,
                step.title,
                step.command,
            )
        if plan.steps:
            self.console.print(table)

    def show_step_start(
        self,
        index: int,
        total: int,
        step_host: str,
        title: str,
        command: str,
        show_command: bool = True,
    ) -> None:
        self.phase("exec", f"{index}/{total} {step_host}: {title}")
        if show_command:
            self.console.print(f"  command: {command}", markup=False)

    def show_step_result(self, result: StepExecutionResult, show_evidence: bool = True) -> None:
        status = "done" if result.success else "warn"
        self.phase(
            status,
            f"{result.host}: returncode={result.returncode} duration={result.duration_seconds:.1f}s",
        )
        if result.artifact_path:
            self.last_workspace_artifact_path = result.artifact_path
            self._save_last_workspace_artifact_path(result.artifact_path)
            
        if show_evidence:
            # Show the "Backend" output in a panel if there is content
            content_lines = []
            if result.stdout:
                content_lines.append(f"[bold cyan]STDOUT:[/bold cyan]\n{result.stdout}")
            if result.stderr:
                content_lines.append(f"[bold red]STDERR:[/bold red]\n{result.stderr}")
            if result.validation_error:
                content_lines.append(f"[bold yellow]VALIDATION ERROR:[/bold yellow]\n{result.validation_error}")
            
            if content_lines:
                # Limit size for very long outputs but show more than before
                body = "\n\n".join(content_lines)
                if len(body) > 3000:
                    body = body[:3000] + "\n\n... (output truncated) ..."
                
                self.console.print(
                    Panel(
                        body,
                        title=f"Backend: {result.title}",
                        border_style="blue",
                        padding=(1, 2)
                    )
                )

            # Also try to render structured JSON views if applicable
            self._render_structured_stdout(result)

        if show_evidence and result.verify is not None:
            self.phase(
                "verify",
                f"{result.host}: verify returncode={result.verify.returncode}",
            )
            if result.verify.stdout or result.verify.stderr:
                verify_lines = []
                if result.verify.stdout:
                    verify_lines.append(f"[bold cyan]VERIFY STDOUT:[/bold cyan]\n{result.verify.stdout}")
                if result.verify.stderr:
                    verify_lines.append(f"[bold red]VERIFY STDERR:[/bold red]\n{result.verify.stderr}")
                
                self.console.print(
                    Panel(
                        "\n\n".join(verify_lines),
                        title="Verification Output",
                        border_style="blue",
                        padding=(1, 2)
                    )
                )

    def _render_structured_stdout(self, result: StepExecutionResult) -> bool:
        if not result.stdout or not result.validation_type:
            return False

        # PRO JSON EXTRACTION: Find JSON even if there is prefix/suffix text
        raw = result.stdout.strip()
        start = raw.find('[') if raw.find('[') != -1 and (raw.find('{') == -1 or raw.find('[') < raw.find('{')) else raw.find('{')
        end = raw.rfind(']') if raw.rfind(']') != -1 and (raw.rfind('}') == -1 or raw.rfind(']') > raw.rfind('}')) else raw.rfind('}')
        
        if start == -1 or end == -1 or end <= start:
            return False

        json_str = raw[start : end + 1]
        try:
            payload = json.loads(json_str)
        except json.JSONDecodeError:
            return False

        if result.validation_type == "event_log_json":
            return self._render_event_log_payload(payload, result.host)
        if result.validation_type == "workspace_file_info_json":
            return self._render_workspace_file_info(payload, result.host)
        if result.validation_type == "disk_space_json":
            return self._render_disk_space_payload(payload, result.host)
        if result.validation_type == "disk_partition_json":
            return self._render_disk_inventory_payload(payload, result.host)
        if result.validation_type == "service_status_json":
            return self._render_service_status_payload(payload, result.host)
        if result.validation_type == "os_version_json":
            return self._render_single_object_payload(payload, result.host, "Operating System")
        if result.validation_type == "powershell_version_json":
            return self._render_single_object_payload(payload, result.host, "PowerShell Version")
        if result.validation_type == "grep_json":
            return self._render_grep_payload(payload, result.host)
        return False

    def _render_grep_payload(self, payload: object, host: str) -> bool:
        items = payload if isinstance(payload, list) else [payload]
        rows = [item for item in items if isinstance(item, dict)]
        if not rows:
            return False

        table = Table(title=f"Search Results ({host})", expand=True, border_style="cyan")
        table.add_column("File", style="blue")
        table.add_column("Line", justify="right", style="magenta")
        table.add_column("Content", style="green")

        for row in rows:
            file_path = str(row.get("File") or "")
            table.add_row(
                self._make_link(file_path, file_path), # Make it a link
                str(row.get("LineNumber") or ""),
                str(row.get("Content") or ""),
            )

        self.console.print(table)
        return True

    def _render_event_log_payload(self, payload: object, host: str) -> bool:
        items = payload if isinstance(payload, list) else [payload]
        rows = [item for item in items if isinstance(item, dict)]
        if not rows:
            return False

        latest = rows[0]
        summary_lines = [
            Text(f"Host: {host}", style="bold cyan"),
            Text(f"When: {self._format_time(latest.get('TimeCreated'))}", style="bold green"),
            Text(f"User: {latest.get('User') or '-'}", style="yellow"),
            Text(f"Action: {latest.get('Reason') or latest.get('ShutdownType') or '-'}", style="magenta"),
        ]
        message = str(latest.get("Message") or "").strip()
        if message:
            summary_lines.append(Text(""))
            summary_lines.append(Text(message, style="white"))
        self.console.print(
            Panel(
                Text("\n").join(summary_lines),
                title="Latest Shutdown",
                border_style="green",
            )
        )

        table = Table(title="Recent Shutdown Events", border_style="blue")
        table.add_column("When", style="green")
        table.add_column("User", style="yellow")
        table.add_column("Action", style="magenta")
        table.add_column("Provider", style="cyan")
        for item in rows[:5]:
            table.add_row(
                self._format_time(item.get("TimeCreated")),
                str(item.get("User") or "-"),
                str(item.get("Reason") or item.get("ShutdownType") or "-"),
                str(item.get("ProviderName") or "-"),
            )
        self.console.print(table)
        return True

    def _render_disk_space_payload(self, payload: object, host: str) -> bool:
        items = payload if isinstance(payload, list) else [payload]
        rows = [item for item in items if isinstance(item, dict)]
        if not rows:
            return False
        table = Table(title=f"Disk Space: {host}", border_style="green")
        table.add_column("Drive", style="cyan")
        table.add_column("Label")
        table.add_column("Free GB", justify="right", style="green")
        table.add_column("Size GB", justify="right")
        table.add_column("% Free", justify="right", style="yellow")
        for item in rows:
            table.add_row(
                str(item.get("DriveLetter") or "-"),
                str(item.get("FileSystemLabel") or "-"),
                str(item.get("SizeRemainingGB") or "-"),
                str(item.get("SizeGB") or "-"),
                str(item.get("PercentFree") or "-"),
            )
        self.console.print(table)
        return True

    def _render_workspace_file_info(self, payload: object, host: str) -> bool:
        if not isinstance(payload, dict):
            return False
        path = str(payload.get("Path") or "-")
        name = str(payload.get("Name") or "-")
        parent = str(payload.get("Parent") or "-")
        exists = "yes" if payload.get("Exists") else "no"
        lines = Text("\n").join(
            [
                Text(f"Host: {host}", style="bold cyan"),
                Text(f"Name: {name}", style="bold green"),
                Text(f"Folder: {parent}", style="yellow"),
                Text(f"Path: {path}", style="magenta"),
                Text(f"Exists: {exists}", style="white"),
            ]
        )
        self.console.print(Panel(lines, title="File Created", border_style="green"))
        return True

    def _render_disk_inventory_payload(self, payload: object, host: str) -> bool:
        if not isinstance(payload, dict):
            return False
        disks = payload.get("Disks")
        partitions = payload.get("Partitions")
        if not isinstance(disks, list) or not isinstance(partitions, list):
            return False

        summary = Text("\n").join(
            [
                Text(f"Host: {host}", style="bold cyan"),
                Text(f"Disk count: {payload.get('DiskCount', len(disks))}", style="bold green"),
                Text(f"Partition count: {payload.get('PartitionCount', len(partitions))}", style="yellow"),
            ]
        )
        self.console.print(Panel(summary, title="Disk Inventory", border_style="green"))

        table = Table(title="Disks", border_style="blue")
        table.add_column("No.", justify="right")
        table.add_column("Name", style="cyan")
        table.add_column("Size GB", justify="right")
        table.add_column("Health", style="green")
        for disk in disks:
            if not isinstance(disk, dict):
                continue
            table.add_row(
                str(disk.get("Number") or "-"),
                str(disk.get("FriendlyName") or "-"),
                str(disk.get("SizeGB") or "-"),
                str(disk.get("HealthStatus") or "-"),
            )
        self.console.print(table)
        return True

    def _render_service_status_payload(self, payload: object, host: str) -> bool:
        items = payload if isinstance(payload, list) else [payload]
        rows = [item for item in items if isinstance(item, dict)]
        if not rows:
            return False
        table = Table(title=f"Service Status: {host}", border_style="green")
        table.add_column("Name", style="cyan")
        table.add_column("Display Name")
        table.add_column("Status", style="green")
        table.add_column("Start Type", style="yellow")
        for item in rows:
            table.add_row(
                str(item.get("Name") or "-"),
                str(item.get("DisplayName") or "-"),
                str(item.get("Status") or "-"),
                str(item.get("StartType") or "-"),
            )
        self.console.print(table)
        return True

    def _render_single_object_payload(self, payload: object, host: str, title: str) -> bool:
        if not isinstance(payload, dict):
            return False
        lines = [Text(f"Host: {host}", style="bold cyan")]
        for key, value in payload.items():
            lines.append(Text(f"{key}: {value}", style="white"))
        self.console.print(Panel(Text("\n").join(lines), title=title, border_style="green"))
        return True

    def _format_time(self, value: object) -> str:
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

    def _load_last_workspace_artifact_path(self) -> str | None:
        try:
            state_file = ensure_app_dirs().state_file
            if not state_file.exists():
                return None
            payload = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        value = payload.get("last_workspace_artifact_path")
        return value if isinstance(value, str) and value else None

    def _save_last_workspace_artifact_path(self, path: str) -> None:
        try:
            state_file = ensure_app_dirs().state_file
            state_file.write_text(
                json.dumps({"last_workspace_artifact_path": path}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return

    def show_run_summary(self, results: list[StepExecutionResult], log_path: str) -> None:
        succeeded = sum(1 for result in results if result.success)
        self.phase(
            "done",
            f"completed {succeeded}/{len(results)} steps; log saved to {log_path}",
        )

    def show_answer_summaries(self, summaries: list[AnswerSummary]) -> None:
        for summary in summaries:
            body = Text("\n").join(Text(line, style="white") for line in summary.lines)
            self.console.print(
                Panel(
                    body,
                    title=summary.title,
                    border_style=summary.tone or "green",
                )
            )

    def select_option(
        self,
        title: str,
        options: list[str],
        current: str | None = None,
        help_text: str | None = None,
    ) -> str | None:
        if not options:
            self.phase("warn", "no options available")
            return None
        if os.name != "nt" or not sys.stdin.isatty() or not sys.stdout.isatty():
            return self._select_option_fallback(title, options, current=current)
        try:
            import msvcrt  # type: ignore
        except Exception:
            return self._select_option_fallback(title, options, current=current)

        index = 0
        if current in options:
            index = options.index(current)

        while True:
            self.console.clear()
            lines = []
            if help_text:
                lines.append(help_text)
                lines.append("")
            for item_index, option in enumerate(options):
                arrow = ">" if item_index == index else " "
                if option == current and item_index == index:
                    lines.append(f"{arrow} [bold green]{option}[/bold green] [cyan](current)[/cyan]")
                elif option == current:
                    lines.append(f"{arrow} [green]{option}[/green] [cyan](current)[/cyan]")
                elif item_index == index:
                    lines.append(f"{arrow} [bold yellow]{option}[/bold yellow]")
                else:
                    lines.append(f"{arrow} {option}")
            lines.append("")
            lines.append("[dim]Up/Down: move  Enter: select  Esc: cancel[/dim]")
            self.console.print(Panel("\n".join(lines), title=title, border_style="cyan"))

            key = msvcrt.getwch()
            if key in ("\r", "\n"):
                self.console.clear()
                return options[index]
            if key == "\x1b":
                self.console.clear()
                return None
            if key in ("\x00", "\xe0"):
                arrow = msvcrt.getwch()
                if arrow == "H":
                    index = (index - 1) % len(options)
                elif arrow == "P":
                    index = (index + 1) % len(options)

    def _select_option_fallback(
        self,
        title: str,
        options: list[str],
        current: str | None = None,
    ) -> str | None:
        self.phase("thinking", title)
        for index, option in enumerate(options, start=1):
            marker = "*" if option == current else " "
            self.console.print(f"  {index}. {marker} {option}", markup=False)
        self.console.print("  press Enter to cancel, or type a number: ", end="")
        try:
            response = input().strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not response:
            return None
        if response.isdigit():
            chosen = int(response)
            if 1 <= chosen <= len(options):
                return options[chosen - 1]
        return None
