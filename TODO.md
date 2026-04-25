# CODEX (Cody) Roadmap & Tasks

## 🎯 Phase 1: Reliability & Regression (Current Focus)
- [ ] Implement **Transcript Testing Framework**: A system to run a request and verify the "Chain of Thought" and resulting commands.
- [ ] Add **Mock LLM Provider**: Allow running tests without calling Ollama to ensure the orchestrator logic itself is solid.
- [ ] **Retry Logic Stress Tests**: Verify that the Agentic Loop handles 1st-step failures correctly across different scenarios.
- [ ] **Surgical Edit Validation**: Regression tests for `FileEditorTool` to ensure it never corrupts files if a string isn't found.

## 🛡️ Phase 2: Professionalization (The "Quick Wins")
- [ ] Add `LICENSE` (MIT).
- [ ] Add `CONTRIBUTING.md` & `CODE_OF_CONDUCT.md`.
- [ ] Create `CHANGELOG.md` starting from v0.2.0.
- [ ] Set up GitHub Issue Templates (Bug Report/Feature Request).

## 🚀 Phase 3: Advanced Infrastructure Features
- [ ] **Service Discovery Expansion**: Support for subnet scanning and OS fingerprinting.
- [ ] **Persistent State DB**: Move from `history.jsonl` to a proper SQLite-based "Long-term Memory".
- [ ] **Parallel Fleet Execution**: Execute the same plan across multiple hosts simultaneously.

## 🏗️ Phase 4: CI/CD & Distribution
- [ ] GitHub Actions: Auto-run tests on every push.
- [ ] Type Hinting & Linting: Ensure 100% `mypy` and `ruff` compliance.
- [ ] PyPI Preparation: Finalize `pyproject.toml` for public release.
