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

## 2026-10-26 Integration wave 2 + experiments (lead)
- Agent C (spectroscopy) merged (two commits; last 65edd4c). Container restart killed C's long pipeline run and the lead's benchmark chain; Scenario B had already completed and checksum-verified. Lost runs were re-launched; nothing was reconstructed by hand.
- Recorded runs (immutable, `results/<run_id>/`, checksums verified by `python -m ddopt.provenance verify`):
  - `benchmark_scenario_a_20261026T232517Z_1bd28ade742a` — `python scripts/run_benchmark.py --scenario scenario_a` (pre-registered).
  - `benchmark_scenario_b_20261026T234545Z_ad7b16de1c23` — `--scenario scenario_b --robustness` (pre-registered).
  - `benchmark_scenario_a_T4us_20261026T235309Z_da0c18904bc7` — `--scenario scenario_a --T 4e-6` (pre-registered alternate window).
  - `spectroscopy_scenario_a_20261026T235246Z_8b272601c344` — `python scripts/run_spectroscopy.py` (pre-registered seeds 5001-5003).
- Headline (synthetic only): in Scenario A no CMA-ES mode beats the training-selected canonical baseline (XY4/XY8) on held-out seeds; XY8 sits at the analytic T1+white floor. Scenario B: phase-only ties; timing+phase at n=4 is 2–5 % better than XY4+virtual-Z in all three training runs (CIs >1); n=8,16 ties/worse. T=4 µs: timing+phase is 2–7 % worse at n=8,16 (overfitting).
- Spectroscopy: full Gaussian model parameters all inside 95 % CIs; held-out RMSE 1.15× shot floor, coverage 0.934; T2*, T2_Hahn CIs narrowly exclude truth for this seed. Telegraph control at Scenario A parameters is near-Gaussian (weak misspecification test).
