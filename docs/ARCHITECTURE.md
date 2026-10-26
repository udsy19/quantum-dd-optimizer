# Architecture decision record

## ADR-001 (2026-10-26) Stack
Python ≥3.11 (recorded runs: 3.13.17), NumPy/SciPy, `cma==4.5.0` (Hansen's pycma) for CMA-ES,
matplotlib for figures, pytest. No QuTiP (not needed; 2×2 algebra is done analytically and
cross-checked with `scipy.linalg.expm`). Exact versions: `requirements-lock.txt`.
QUA SDK (`qm-qua`) is **not** a dependency; the adapter in `qua/` is optional and gated.

## ADR-002 Numerical layers
1. `noise`, `filters`, `channels`: analytic filter-function layer (Gaussian dephasing) + CPTP channels.
2. `sequences`, `simulator`: finite-pulse 2×2 Monte-Carlo propagation over sampled noise
   trajectories; noise-averaged PTM, average gate fidelity against the corrected target.
3. `spectroscopy`: synthetic Ramsey/Hahn/CPMG data, fits, held-out prediction.
4. `optimizer`, `evaluation`: CMA-ES over gaps/phases, fair baselines, independent test seeds.
5. `provenance` + `scripts/`: manifests, immutable `results/<run_id>/`, figures, report tables.

## ADR-003 Ownership (disjoint files; contracts in `src/ddopt/contracts.py`, `docs/INTERFACES.md`)
| Agent | Files |
|---|---|
| Lead | `src/ddopt/contracts.py`, `src/ddopt/__init__.py`, `docs/INTERFACES.md`, `docs/PHYSICS_CONVENTIONS.md`, `docs/ARCHITECTURE.md`, `docs/PROGRESS.md`, `pyproject.toml`, `tests/test_contracts.py`, README |
| A physics | `src/ddopt/{noise,filters,channels}.py`, `tests/test_{noise,filters,channels}.py`, `docs/PHYSICS.md` |
| B control/sim | `src/ddopt/{sequences,simulator}.py`, `tests/test_{sequences,simulator}.py` |
| C spectroscopy | `src/ddopt/spectroscopy.py`, `tests/test_spectroscopy.py` |
| D optimization/stats | `src/ddopt/{optimizer,evaluation}.py`, `tests/test_{optimizer,evaluation}.py` |
| E hardware | `qua/`, `tests/test_qua_syntax.py`, `docs/HARDWARE_PROTOCOL.md` |
| F repro/report | `src/ddopt/provenance.py`, `scripts/`, `configs/`, `report/`, `docs/REPORT_REQUIREMENTS.md`, `.github/workflows/`, `tests/test_reproducibility.py` |
| G red team | `docs/REVIEW_FINDINGS.md` |

Agents run in separate git worktrees; the lead merges and re-runs the full test suite.
