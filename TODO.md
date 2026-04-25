# CODEX (Cody) Roadmap & Tasks

## ✅ Phase 1: Reliability & Behavioral Integrity (COMPLETE)
- [x] **Transcript Regression Tests**: Verified via `tests/regression/test_transcripts.py`.
- [x] **Orchestrator Fallback Retries**: Increased resilience with 3x re-planning loop.
- [x] **Deterministic Routing Tightening**: Added identity, discovery, and cleanup instant-handlers.
- [x] **Strict Verification**: Mandated `verify_command` in planner instructions.
- [x] **Live Backend Streaming**: Implemented line-by-line STDOUT streaming.

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
