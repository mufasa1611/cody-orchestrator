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
                exit_code INTEGER
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
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
        """)
        conn.commit()


def save_run_to_db(
    run_id: str,
    request: str,
    plan_summary: str,
    domain: str,
    risk: str,
    exit_code: Any,
    results: list[Any]
) -> None:
    if sqlite3 is None:
        return
    
    init_db()
    db_path = get_db_path()
    
    timestamp = datetime.now(timezone.utc).isoformat()
    
    # PRO SAFETY: Ensure exit_code is a valid integer
    try:
        final_exit_code = int(exit_code)
    except (ValueError, TypeError):
        final_exit_code = 1
    
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (id, timestamp, request, summary, domain, risk, exit_code) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, timestamp, request, plan_summary, domain, risk, final_exit_code)
        )
        
        for r in results:
            # results are StepExecutionResult objects or dicts depending on caller
            # to be safe we handle both
            step_id = getattr(r, 'step_id', r.get('step_id') if isinstance(r, dict) else '')
            title = getattr(r, 'title', r.get('title') if isinstance(r, dict) else '')
            command = getattr(r, 'command', r.get('command') if isinstance(r, dict) else '')
            host = getattr(r, 'host', r.get('host') if isinstance(r, dict) else '')
            success = int(getattr(r, 'success', r.get('success') if isinstance(r, dict) else False))
            stdout = getattr(r, 'stdout', r.get('stdout') if isinstance(r, dict) else '')
            stderr = getattr(r, 'stderr', r.get('stderr') if isinstance(r, dict) else '')
            duration = getattr(r, 'duration_seconds', r.get('duration_seconds') if isinstance(r, dict) else 0.0)
            
            conn.execute("""
                INSERT INTO steps (run_id, step_id, title, command, host, success, stdout, stderr, duration)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (run_id, step_id, title, command, host, success, stdout, stderr, duration))
        
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
