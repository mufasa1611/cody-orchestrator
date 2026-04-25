# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-04-25

### Added
- **Surgical File Editor**: New `FileEditorTool` for precise `old_string` -> `new_string` replacements.
- **Web Research**: Integrated `WebSearchTool` powered by `ddgs` for documentation and error research.
- **Service Discovery**: New `discover_hosts` tool for Windows local network scanning.
- **Rich Persistent Memory**: Automatic recording of successful steps in `history.jsonl` and injection of historical context into planning.
- **Live Backend Streaming**: Line-by-line STDOUT streaming during execution for a more transparent workflow.
- **Transcript Regression Tests**: New test suite in `tests/regression` to ensure behavioral integrity.
- **Deterministic Handlers**: Added instant-handlers for Identity, Discovery, and Cleanup tasks.

### Changed
- **Branding**: Renamed the primary command and prompt to `codex`.
- **Agentic Loop**: Increased re-planning resilience (up to 3 attempts with error context).
- **Stricter Planning**: Mandated `verify_command` for all change/edit steps to ensure "Don't claim success unless verified".
- **Improved UI**: Enhanced backend panels and structured summaries.

### Fixed
- **Orchestrator Logic**: Fixed success calculation when recovering from a failure via re-planning.
- **CLI Entry Point**: Added missing `main` block to `cli.py` for standalone execution.
- **Dependency Renaming**: Switched from `duckduckgo-search` to `ddgs` package.

## [0.1.0] - Pre-release
- Initial prototype for autonomous infrastructure orchestration.
