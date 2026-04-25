from __future__ import annotations

import os
import re
from pathlib import Path
from crewai.tools import BaseTool


class FileEditorTool(BaseTool):
    name: str = "file_editor"
    description: str = (
        "Surgically replace text in a file. Requires the file path, the exact "
        "old_string to find, and the new_string to replace it with. This is safer "
        "than overwriting the entire file."
    )

    def _run(self, file_path: str, old_string: str, new_string: str) -> str:
        path = Path(file_path).resolve()
        if not path.exists():
            return f"Error: File not found at {file_path}"
        
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading file: {e}"

        if old_string not in content:
            return (
                f"Error: Could not find the exact 'old_string' in {file_path}. "
                "Ensure the string matches exactly, including whitespace and indentation."
            )

        occurrences = content.count(old_string)
        if occurrences > 1:
            return (
                f"Error: Found {occurrences} occurrences of 'old_string'. "
                "Please provide more context to make the replacement unique."
            )

        new_content = content.replace(old_string, new_string)
        
        try:
            path.write_text(new_content, encoding="utf-8")
            return f"Successfully updated {file_path}. Replaced 1 occurrence."
        except Exception as e:
            return f"Error writing to file: {e}"
