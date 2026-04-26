from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from crew_agent.core.db import get_recent_history_context
from crew_agent.core.paths import ensure_app_dirs


DEFAULT_ASSISTANT_NAME = "Codin"
MEMO_FILENAME = "memo.md"


@dataclass(frozen=True)
class WorkspaceMemory:
    assistant_name: str = DEFAULT_ASSISTANT_NAME
    user_name: str | None = None
    note_lines: tuple[str, ...] = ()
    history_summaries: tuple[str, ...] = ()


def get_memo_path(cwd: Path | None = None) -> Path:
    base = (cwd or Path.cwd()).resolve()
    return base / MEMO_FILENAME


def load_workspace_memory(cwd: Path | None = None) -> WorkspaceMemory:
    path = get_memo_path(cwd)
    history = tuple(get_recent_history_context(limit=10))
    
    if not path.exists():
        return WorkspaceMemory(history_summaries=history)

    text = _read_memo_text(path).strip()
    if not text:
        return WorkspaceMemory(history_summaries=history)

    assistant_name = DEFAULT_ASSISTANT_NAME
    user_name: str | None = None
    notes: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("-"):
            continue
        value = line[1:].strip()
        lowered = value.casefold()
        if lowered.startswith("assistant name:"):
            candidate = value.split(":", 1)[1].strip()
            if candidate:
                assistant_name = candidate
            continue
        if lowered.startswith("user name:"):
            candidate = value.split(":", 1)[1].strip()
            if candidate:
                user_name = candidate
            continue
        if lowered.startswith("purpose:"):
            continue
        if value:
            notes.append(value)

    return WorkspaceMemory(
        assistant_name=assistant_name,
        user_name=user_name,
        note_lines=tuple(notes),
        history_summaries=history,
    )


def save_step_to_history(request: str, summary: str) -> None:
    paths = ensure_app_dirs()
    history_file = paths.runs_dir / "history.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request": request,
        "summary": summary,
    }
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _load_history_summaries(limit: int = 10) -> tuple[str, ...]:
    paths = ensure_app_dirs()
    history_file = paths.runs_dir / "history.jsonl"
    if not history_file.exists():
        return ()
    
    summaries = []
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line in lines[-limit:]:
                data = json.loads(line)
                summaries.append(f"Previously ({data['timestamp']}): {data['summary']}")
    except Exception:
        pass
    return tuple(summaries)


def is_greeting(request: str) -> bool:
    greetings = {"hi", "hello", "hey", "greetings", "good morning", "good evening", "yo"}
    return request.strip().lower().rstrip("!?.") in greetings


def extract_assistant_name_assignment(request: str) -> str | None:
    lowered = " ".join(request.casefold().split())
    if any(
        phrase in lowered
        for phrase in (
            "what is your name",
            "who are you",
            "do you know your name",
            "tell me your name",
        )
    ):
        return None

    patterns = (
        r"\byour name from now on is\s+([A-Za-z][A-Za-z0-9 _-]{0,40})",
        r"\byour name is\s+([A-Za-z][A-Za-z0-9 _-]{0,40})",
        r"\blike your name\s+([A-Za-z][A-Za-z0-9 _-]{0,40})",
        r"\bremember your name is\s+([A-Za-z][A-Za-z0-9 _-]{0,40})",
        r"\bcall yourself\s+([A-Za-z][A-Za-z0-9 _-]{0,40})",
    )
    for pattern in patterns:
        match = re.search(pattern, request, flags=re.IGNORECASE)
        if match:
            candidate = re.sub(
                r"\s+(?:can you|could you|would you|please|save|remember|note|write|keep)\b.*$",
                "",
                match.group(1),
                flags=re.IGNORECASE,
            )
            name = _normalize_name(candidate)
            if name:
                return name
    return None


def is_identity_question(request: str) -> bool:
    lowered = " ".join(request.casefold().split())
    return any(
        phrase in lowered
        for phrase in (
            "what is your name",
            "who are you",
            "do you know your name",
            "tell me your name",
            "can you tell me your name",
        )
    )


def extract_user_name_assignment(request: str) -> str | None:
    lowered = " ".join(request.casefold().split())
    if any(
        phrase in lowered
        for phrase in (
            "what is my name",
            "do you know my name",
            "tell me my name",
            "who am i",
        )
    ):
        return None

    patterns = (
        r"\bmy name is\s+([A-Za-z][A-Za-z0-9 _-]{0,40})",
        r"\bcall me\s+([A-Za-z][A-Za-z0-9 _-]{0,40})",
        r"\bi am\s+([A-Za-z][A-Za-z0-9 _-]{0,40})\b(?:\s*(?:and|,|\.|!|\?|$))",
        r"\bi'm\s+([A-Za-z][A-Za-z0-9 _-]{0,40})\b(?:\s*(?:and|,|\.|!|\?|$))",
    )
    for pattern in patterns:
        match = re.search(pattern, request, flags=re.IGNORECASE)
        if match:
            candidate = re.sub(
                r"\s+(?:can you|could you|would you|please|save|remember|note|write|keep)\b.*$",
                "",
                match.group(1),
                flags=re.IGNORECASE,
            )
            name = _normalize_name(candidate)
            if name:
                return name
    return None


def is_user_identity_question(request: str) -> bool:
    lowered = " ".join(request.casefold().split())
    return any(
        phrase in lowered
        for phrase in (
            "what is my name",
            "do you know my name",
            "tell me my name",
            "who am i",
            "so what is my name",
        )
    )


def is_memory_recall_question(request: str) -> bool:
    lowered = " ".join(request.casefold().split())
    return any(
        phrase in lowered
        for phrase in (
            "what do you know about me",
            "what have you remembered",
            "what did i ask you to remember",
            "what important info",
            "what info did you save",
            "what did you save about me",
        )
    )


def should_save_workspace_memory(request: str) -> bool:
    if extract_assistant_name_assignment(request):
        return True
    if extract_user_name_assignment(request):
        return True
    return extract_remembered_note(request) is not None


def build_memo_content(
    request: str,
    existing: WorkspaceMemory | None = None,
) -> str:
    memory = existing or WorkspaceMemory()
    assistant_name = extract_assistant_name_assignment(request) or memory.assistant_name
    user_name = extract_user_name_assignment(request) or memory.user_name

    notes = list(memory.note_lines)
    request_note = extract_remembered_note(request)
    if request_note and request_note not in notes:
        notes.append(request_note)

    lines = [
        "# Memo",
        "",
        f"- Assistant name: {assistant_name}",
    ]
    if user_name:
        lines.append(f"- User name: {user_name}")
    lines.extend([
        "- Purpose: Store important local notes for this workspace.",
    ])
    for note in notes:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def save_workspace_memory(
    request: str,
    cwd: Path | None = None,
) -> Path:
    path = get_memo_path(cwd)
    existing = load_workspace_memory(path.parent)
    path.write_text(build_memo_content(request=request, existing=existing), encoding="utf-8")
    return path


def summarize_workspace_memory(memory: WorkspaceMemory) -> str:
    lines: list[str] = []
    if memory.user_name:
        lines.append(f"Your name here is {memory.user_name}.")
    if memory.note_lines:
        lines.append("Remembered notes:")
        lines.extend(f"- {note}" for note in memory.note_lines[:5])
    if not lines:
        return "I have not saved any important workspace facts yet."
    return "\n".join(lines)


def extract_remembered_note(request: str) -> str | None:
    compact = " ".join(request.split()).strip()
    if not compact:
        return None

    patterns = (
        r"\bremember(?: that)?\s+(.+)",
        r"\bnote down(?: that)?\s+(.+)",
        r"\bnote(?: that)?\s+(.+)",
        r"\bkeep in mind(?: that)?\s+(.+)",
        r"\bsave(?: that)?\s+(.+?)(?:\s+in your memo(?: file)?|\s+to your memo(?: file)?|\s+in memory|\s*$)",
        r"\bimportant[:\s]+(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            candidate = _clean_remembered_note(match.group(1))
            if candidate:
                return f"Remembered: {candidate}"

    if extract_user_name_assignment(request) or extract_assistant_name_assignment(request):
        return None

    lowered = compact.casefold()
    if any(term in lowered for term in ("remember", "memo", "memory", "important", "save this")):
        candidate = _clean_remembered_note(compact)
        if candidate:
            return f"Saved from request: {candidate}"
    return None


def _normalize_name(value: str) -> str:
    cleaned = re.sub(r"[\s.!?,;:]+$", "", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\b(ok|okay|please)\b$", "", cleaned, flags=re.IGNORECASE).strip()
    if not cleaned:
        return ""
    return " ".join(part[:1].upper() + part[1:] for part in cleaned.split(" "))


def _clean_remembered_note(value: str) -> str:
    cleaned = value.strip().strip("'\"")
    cleaned = re.sub(
        r"\s+(?:in your memo(?: file)?|to your memo(?: file)?|in memory|for later)\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"[\s.!?,;:]+$", "", cleaned)
    if not cleaned:
        return ""
    if len(cleaned) > 160:
        cleaned = cleaned[:157].rstrip() + "..."
    return cleaned


def _read_memo_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")
