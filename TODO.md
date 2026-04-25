# CODEX (Cody) Roadmap & Tasks

## 🎯 Phase 1: Reliability & Behavioral Integrity (Current Focus)
- [ ] **Transcript Regression Tests**: Add tests for the exact broken conversations (e.g., `nmap` failure, `echo` syntax errors).
- [ ] **Orchestrator Fallback Retries**: Enhance the loop to try safe fallback specialists/paths instead of stopping at the first failure.
- [ ] **Deterministic Routing Tightening**: Add more regex-based "Instant Handlers" for common requests to bypass the LLM planner.
- [ ] **Strict Verification ("Don't Guess, Verify")**: Ensure all core handlers require a validation signal before claiming success.

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
