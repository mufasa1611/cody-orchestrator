# CODEX (Cody) Roadmap & Tasks

## ✅ Phase 1: Reliability & Behavioral Integrity (COMPLETE)
- [x] **Transcript Regression Tests**: Verified via `tests/regression/test_transcripts.py`.
- [x] **Orchestrator Fallback Retries**: Increased resilience with 3x re-planning loop.
- [x] **Deterministic Routing Tightening**: Added identity, discovery, and cleanup instant-handlers.
- [x] **Strict Verification**: Mandated `verify_command` in planner instructions.
- [x] **Live Backend Streaming**: Implemented line-by-line STDOUT streaming.

## ✅ Phase 2: Professionalization (COMPLETE)
- [x] **LICENSE**: Added MIT License.
- [x] **CONTRIBUTING.md & CODE_OF_CONDUCT.md**: Established community guidelines.
- [x] **CHANGELOG.md**: Documented v0.2.0 updates.
- [x] **GitHub Issue Templates**: Created Bug Report and Feature Request templates.

## ✅ Phase 3: Advanced Infrastructure Features (COMPLETE)
- [x] **Service Discovery Expansion**: Added TTL-based OS fingerprinting and ARP scanning.
- [x] **Persistent State DB**: Implemented SQLite-based "Long-term Memory" for runs and steps.
- [x] **Parallel Fleet Execution**: Implemented multi-host parallelism using ThreadPoolExecutor.

## ✅ Phase 4: CI/CD & Distribution (COMPLETE)
- [x] **GitHub Actions**: Automated pytest suite runs on every push/PR across Python 3.10-3.12.
- [x] **Type Hinting & Linting**: Implemented `mypy` and `ruff` configurations. Added `py.typed`.
- [x] **PyPI Preparation**: Finalized `pyproject.toml` with professional metadata and classifiers.

---
**Codex is now a production-grade autonomous orchestrator. Roadmap Complete.**
