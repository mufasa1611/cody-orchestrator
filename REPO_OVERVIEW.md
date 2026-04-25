# Codex Repository Overview

`codex` (formerly cody-cli) is a professional autonomous infrastructure orchestrator shell.

It combines:
- **Long-term SQLite Memory**: Persistent storage of every run and step for cross-session context.
- **Agentic Loop**: Autonomous re-planning and error recovery logic.
- **Parallel Fleet Execution**: Concurrent multi-host task management.
- **Deterministic Handlers**: Fast, reliable automation for common infrastructure tasks.
- **Terminal UI**: Live backend streaming and rich result panels.

## What This Repo Contains

- `src/crew_agent/conversation/`: Routing, classification, and Ollama model adapters.
- `src/crew_agent/handlers/`: Orchestrator flow, deterministic handlers, and LLM planning integration.
- `src/crew_agent/executors/`: Execution runtime (Local, SSH, WinRM) with live STDOUT streaming.
- `src/crew_agent/core/`: Database (SQLite) logic, shared models, paths, and Terminal UI.
- `src/crew_agent/agents/definitions/`: Specialist agent metadata files.
- `tests/`: Unit and regression test suite verifying core reliability.

## Current Behavior

Codex is designed to be decisive and robust:
- **Smarter Routing**: Forced task acceptance for keywords like "search" and "find".
- **Dynamic Discovery**: Automatic network mapping with OS detection.
- **Precision Edits**: Surgical file modification system.
- **Transparent Execution**: Live "STREAM" output before the final results panel.

## CLI Exposure

The repository package remains `crew_agent` for stability, but the primary user command is:
- **`codex`**

## State & Data

- **Database**: `codex.db` stores all historical knowledge.
- **Logs**: Detailed execution JSON logs under `.cody/runs/`.
- **Backups**: Zip snapshots of target hosts under `.cody/backups/`.

---
*Created by Mufasa (M. Farid)*
