import pytest
from pathlib import Path
from crew_agent.tools.file_editor import FileEditorTool

def test_file_editor_success(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("line 1\nline 2\nline 3", encoding="utf-8")
    
    tool = FileEditorTool()
    result = tool._run(str(f), "line 2", "line TWO")
    
    assert "Successfully" in result
    assert f.read_text(encoding="utf-8") == "line 1\nline TWO\nline 3"

def test_file_editor_not_found(tmp_path):
    tool = FileEditorTool()
    result = tool._run(str(tmp_path / "nonexistent.txt"), "old", "new")
    assert "Error: File not found" in result

def test_file_editor_no_match(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world", encoding="utf-8")
    
    tool = FileEditorTool()
    result = tool._run(str(f), "missing", "new")
    assert "Error: Could not find" in result

def test_file_editor_ambiguous(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("duplicate\nduplicate", encoding="utf-8")
    
    tool = FileEditorTool()
    result = tool._run(str(f), "duplicate", "single")
    assert "Error: Found 2 occurrences" in result
