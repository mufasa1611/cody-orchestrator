from __future__ import annotations

import subprocess

from crewai.tools import BaseTool


BLOCKED_PATTERNS = (
    "remove-item",
    "del ",
    "erase ",
    "format-volume",
    "clear-disk",
    "diskpart",
    "shutdown",
    "stop-computer",
    "restart-computer",
    "reg delete",
    "sc.exe delete",
)


class WindowsCommandTool(BaseTool):
    name: str = "windows_command"
    description: str = (
        "Execute a Windows PowerShell command and return the exit code, stdout, "
        "and stderr. Avoid destructive commands unless unsafe mode is enabled."
    )
    allow_unsafe: bool = False
    timeout_seconds: int = 120

    def _run(self, command: str) -> str:
        lowered = f" {command.casefold()} "
        if not self.allow_unsafe and any(pattern in lowered for pattern in BLOCKED_PATTERNS):
            return (
                "Refused to run a potentially destructive PowerShell command. "
                "Re-run the CLI with --unsafe if this is intentional."
            )

        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return f"Command timed out after {self.timeout_seconds} seconds."
        except Exception as exc:
            return f"Error executing command: {exc}"

        parts = [f"Exit code: {result.returncode}"]
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if stdout:
            parts.append(f"STDOUT:\n{stdout}")
        if stderr:
            parts.append(f"STDERR:\n{stderr}")

        return "\n\n".join(parts)
