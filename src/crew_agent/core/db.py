from __future__ import annotations

sqlite3 = None
try:
    import sqlite3
except ImportError:
    pass

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crew_agent.core.paths import ensure_app_dirs


def get_db_path() -> Path:
    paths = ensure_app_dirs()
    return paths.root / "codex.db"


def init_db() -> None:
    if sqlite3 is None:
        return
    
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                request TEXT NOT NULL,
                summary TEXT,
                domain TEXT,
                risk TEXT,
                exit_code INTEGER,
                files_touched TEXT,
                rollback_triggered INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                step_id TEXT,
                title TEXT,
                command TEXT,
                host TEXT,
                success INTEGER,
                stdout TEXT,
                stderr TEXT,
                duration REAL,
                precheck_status TEXT,
                postcheck_status TEXT,
                target_path TEXT,
                destructive INTEGER DEFAULT 0,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            )
        """)
        conn.commit()


def save_message_to_db(role: str, content: str) -> None:
    if sqlite3 is None:
        return
    init_db()
    db_path = get_db_path()
    timestamp = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO conversation (timestamp, role, content) VALUES (?, ?, ?)",
            (timestamp, role, content)
        )
        conn.commit()


def get_last_messages_from_db(limit: int = 10) -> list[dict[str, str]]:
    if sqlite3 is None:
        return []
    init_db()
    db_path = get_db_path()
    messages = []
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT role, content FROM conversation ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            # Reverse to get chronological order
            for role, content in reversed(rows):
                messages.append({"role": role, "content": content})
    except Exception:
        pass
    return messages
    run_id: str,
    request: str,
    plan_summary: str,
    domain: str,
    risk: str,
    exit_code: Any,
    results: list[Any],
    rollback_triggered: bool = False
) -> None:
    if sqlite3 is None:
        return
    
    init_db()
    db_path = get_db_path()
    
    timestamp = datetime.now(timezone.utc).isoformat()
    
    try:
        final_exit_code = int(exit_code)
    except (ValueError, TypeError):
        final_exit_code = 1
    
    # Simple extraction of files touched from results if available
    files_touched = []
    for r in results:
        if hasattr(r, 'target_path') and r.target_path:
            files_touched.append(r.target_path)
    
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (id, timestamp, request, summary, domain, risk, exit_code, files_touched, rollback_triggered) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, timestamp, request, plan_summary, domain, risk, final_exit_code, ",".join(files_touched), 1 if rollback_triggered else 0)
        )
        
        for r in results:
            step_id = getattr(r, 'step_id', '')
            title = getattr(r, 'title', '')
            command = getattr(r, 'command', '')
            host = getattr(r, 'host', '')
            success = int(getattr(r, 'success', False))
            stdout = getattr(r, 'stdout', '')
            stderr = getattr(r, 'stderr', '')
            duration = getattr(r, 'duration_seconds', 0.0)
            target_path = getattr(r, 'target_path', None)
            destructive = 1 if getattr(r, 'destructive', False) else 0
            
            conn.execute("""
                INSERT INTO steps (run_id, step_id, title, command, host, success, stdout, stderr, duration, target_path, destructive)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, step_id, title, command, host, success, stdout, stderr, duration, target_path, destructive))
        
        conn.commit()


def get_recent_history_context(limit: int = 5) -> list[str]:
    if sqlite3 is None:
        return []
    
    init_db()
    db_path = get_db_path()
    
    summaries = []
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("""
                SELECT timestamp, request, summary, exit_code 
                FROM runs 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
            for row in cursor:
                status = "Succeeded" if row[3] == 0 else "Failed"
                summaries.append(f"[{row[0]}] User asked: '{row[1]}'. Result: {row[2]} ({status})")
    except Exception:
        pass
    return summaries
