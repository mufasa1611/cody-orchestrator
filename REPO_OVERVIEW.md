# cody-cli Repository Overview

`cody-cli` is a local-first command-line agent shell for Cody.

It combines:

- deterministic handlers for common tasks
- local specialist agent definition files
- a planner fallback for broader infrastructure requests
- approval and validation gates around execution
- a terminal UI that shows both plans and backend tool output

## What This Repo Contains

- `src/crew_agent/conversation/`
  Front-door routing, chat/task classification, and model adapters.
- `src/crew_agent/handlers/`
  Deterministic task handlers, planner integration, orchestrator flow, and workspace logic.
- `src/crew_agent/agents/definitions/`
  Local specialist agent files such as `file-reader`, `repo-searcher`, `workspace-operator`, and `infra-planner`.
- `src/crew_agent/executors/`
  Command execution runtime for Windows local execution and remote transports.
- `src/crew_agent/policy/`
  Approval gates, validation, and execution safety checks.
- `src/crew_agent/core/`
  Shared models, paths, memory, and terminal UI helpers.
- `tests/`
  Regression coverage for memory, routing, workspace behavior, search, testing, approvals, and specialist workflows.

## Current Behavior

This version of Cody can:

- route requests to local specialist handlers before falling back to the planner
- remember stable workspace facts and recall them deterministically
- read files from the workspace and common user folders with fallback search
- search repository code with richer `ripgrep` output
- run tests and summarize failures as useful inspection output
- edit simple local workspace files with deterministic fallback location handling
- show backend stdout and stderr in a higher-visibility terminal UI

## Important Design Choice

The repository name is `cody-cli`, but the internal Python package currently remains under `crew_agent`.

That keeps the current code layout stable while exposing the user-facing CLI as:

- `cody`
- `crew-agent`

## Local Runtime State

This repo keeps user/runtime state under `.cody/`, but generated run logs, backups, temporary test artifacts, and ephemeral state files are excluded from version control.

## Recommended Next Steps

- add autonomous code-edit loops with patch/retest/retry behavior
- expand structured memory and cross-task reference resolution
- add richer specialist workflows beyond single-pass execution
- improve planner repair logic and recovery from weak model output
