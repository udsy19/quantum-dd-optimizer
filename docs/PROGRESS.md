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
