import subprocess
from crewai_tools import tool

@tool("windows_command")
def run_windows_command(command: str) -> str:
    """Executes a Windows PowerShell command and returns the output."""
    try:
        result = subprocess.run(
            ["powershell", "-Command", command],
            capture_output=True,
            text=True
        )
        output = ""
        if result.stdout:
            output += f"STDOUT:\n{result.stdout}\n"
        if result.stderr:
            output += f"STDERR:\n{result.stderr}\n"
        return output.strip() or "No output."
    except Exception as e:
        return f"Error executing command: {e}"