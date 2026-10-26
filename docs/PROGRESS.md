# Progress / evidence tracker

2026-10-26: Public project repository created by owner. Multi-agent research plan, honest scope and acceptance gates initialized. **No simulator or real QUA hardware tests are claimed.**

## Current state
- Research topic and publication plan: documented.
- Physics code: pending.
- Canonical sequence and simulator code: pending.
- Spectroscopy code / fit: pending.
- CMA-ES: pending.
- QUA backend validation: pending.
- Actual numerical results: pending.
- IQCC access and hardware data: unconfirmed.

Future progress entries must include file paths, executed commands and evidence.

## 2026-10-26 Phase 0 (lead)
- Environment: Linux x86_64, Python 3.13.17 venv, numpy/scipy/cma 4.5.0/matplotlib/pytest (see `requirements-lock.txt`); TeX Live installed from Ubuntu packages (pdflatex, latexmk).
- Created `pyproject.toml`, `src/ddopt/contracts.py`, `docs/INTERFACES.md`, `docs/PHYSICS_CONVENTIONS.md`, ADRs, CI workflow (`.github/workflows/ci.yml`, not yet observed running on GitHub — CI status UNVERIFIED).
- `results/` and `figures/` are now tracked (they are the evidence).
- Command: `python -m pytest -q` → 4 passed (contract tests only).
- Finding: master-prompt amplitude-damping infidelity formula `[3-2√(1-γ)-γ]/6` fails the γ=0 limit; using `(2+γ-2√(1-γ))/6` (to be derived/tested by Agent A).
- Parallel agents: spawned as subagents in isolated git worktrees (see later entries).

## 2026-10-26 Integration wave 1 (lead)
Agents ran as subagents in isolated git worktrees, merged by the lead with `git merge` (commits in `git log`).
- Agent E (QUA adapter, `qua/`): merged. SDK-free translator; `qm-qua` not installed in project venv → SDK test SKIPPED. Official docs site blocked (HTTP 403 via proxy); API names checked against the qm-qua 1.4.1 wheel. **No hardware access, no job submitted.**
- Agent F (provenance, CI, report skeleton, evidence map): merged; CI file conflict resolved in favour of F's superset. CI never observed running on GitHub (UNVERIFIED).
- Agent B (sequences, simulator): merged.
- Agent A (noise, filters, channels, `docs/PHYSICS.md`): merged. Confirmed AD infidelity `(2+γ−2√(1−γ))/6`; master-prompt formula rejected (fails γ=0). Fixed one-sided PSD conversion in conventions (S1(f)=2·S2(2πf)).
- Agent D (optimizer, evaluation): merged.
- Lead: `src/ddopt/scenarios.py`, `scripts/calibrate_scenario_a.py` → `configs/scenario_{a,b}.json` (synthetic; A=5.93e9, σ=1.236e5 rad/s, S0=1e4 rad²/s), `tests/test_integration.py`.
- `python -m pytest -q` after merging D: **213 passed, 1 skipped** (skip = QUA SDK absent).
- Gate G3: `python scripts/run_g3_validation.py --n-traj 64000` → `results/g3_validation_20261026T231608Z_cbfe38b59354/`. All 5 cases (FID, Hahn w=32ns, CPMG-8 w=32ns, Hahn/CPMG-8 instantaneous) within 1.96·SE (|z| ≤ 0.95). Manifest records a dirty tree (an uncommitted test file existed at run time).
