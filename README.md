# Quantum DD Optimizer

> **Project stage: synthetic-simulation study implemented and executed; no hardware.** The numerical
> pipeline (noise models, filter functions, finite-pulse Monte-Carlo simulator, synthetic
> spectroscopy, CMA-ES optimizer, held-out evaluation, report generation) exists with tests and
> recorded runs in `results/`. **Main finding (synthetic, pre-registered): CMA-ES did not beat
> XY4/XY8 on held-out noise.** No IQCC hardware access, data or hardware-validated gains exist.

AI-driven, hardware-aware dynamical decoupling research for superconducting idle qubits, motivated by the Columbia University × Quantum Machines project brief.

## Launch Claude Code

**[READ THE COMPLETE MULTI-AGENT MASTER PROMPT](docs/CLAUDE_CODE_MASTER_PROMPT.md)**

Clone this public repository, launch Claude Code from the repo root, and tell it:

```text
Read CLAUDE.md and docs/CLAUDE_CODE_MASTER_PROMPT.md completely.
Follow the master plan end-to-end using multiple independent subagents
or worktrees with disjoint file ownership. Implement actual numerical
code, tests, synthetic datasets, optimizers, evaluation and the
5–7-page evidence-backed LaTeX report. Execute the scientific gates.
Never invent results or hardware outcomes. Keep an evidence ledger,
record all commands and return real test results plus open blockers.
Start Phase 0 now.
```

## Read next

- [Claude Code full plan](docs/CLAUDE_CODE_MASTER_PROMPT.md): seven specialized agents, phase plan, exact experiments and exit gates.
- [Scientific acceptance gates](docs/ACCEPTANCE_GATES.md): G0–G9.
- [Report requirements](docs/REPORT_REQUIREMENTS.md): paper outline, mandatory plots/tables, claim ledger.
- [Hardware protocol](docs/HARDWARE_PROTOCOL.md): IQCC authorization and measurement gates.
- [References](docs/REFERENCES.md): literature reading list and metadata verification queue.
- [Progress](docs/PROGRESS.md): honest current completion status.
- [Architecture](docs/ARCHITECTURE.md): design decisions.

## Expected end-state tree

```
src/ddopt/{noise,filters,channels,sequences,simulator,spectroscopy,optimizer,evaluation}.py
tests/                 # numerical proof, API validation, regression
configs/               # realistic and synthetic assumptions
scripts/               # seeded experiment and plot entrypoints
qua/                   # gated QUA hardware adapter
results/               # immutable raw results with manifests
figures/               # plots generated from stored runs
report/                # 5-7 page LaTeX manuscript, evidence map, PDF
.github/workflows/     # CI
```

Status: all of the above exist except `.github/workflows/` having actually run on GitHub
(CI never observed — UNVERIFIED) and any hardware execution from `qua/` (never run; not authorized).

## Reproduce

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[test]"
python -m pytest -q                                   # unit + integration tests
python scripts/run_g3_validation.py --n-traj 64000    # gate G3 (MC vs filter function)
python scripts/run_spectroscopy.py                    # synthetic spectroscopy (G4)
python scripts/run_benchmark.py --scenario scenario_a # pre-registered benchmark (also scenario_b --robustness)
python scripts/make_report_artifacts.py               # figures/tables/macros from runs pinned in report/runs.json
PYTHON=.venv/bin/python bash scripts/build_report.sh  # report/main.pdf
```
Recorded runs used by the report are listed in `report/runs.json`; each `results/<run_id>/`
holds `payload.json`, `manifest.json` (git SHA, versions, seeds, command) and `SHA256SUMS`
(`python -m ddopt.provenance verify results/<run_id>`).

## Evidence policy

The previous draft's claims of seven passing tests, 1% agreement, 1% fit recovery or 1.7–1.8× improvement are unverified and must never be repeated as outcomes without real reproducible runs. CMA-ES is an evolution strategy, not an RL agent. QUA compilation is not IQCC hardware validation. A positive, neutral, or negative result is a valid research outcome if the protocol and evidence are sound.

The course-supplied PDF describes *another* completed SAC readout optimization project and lists dynamical decoupling as a potential follow-up topic; its hardware results are **not our team's DD results**.

## Original research report

The original team manuscript was not available in this repository. `report/` contains a new
5–7-page draft generated from this repository's recorded synthetic runs; author list,
affiliations, contributions and the AI-use statement are PENDING team confirmation.

Confirm license choice and author consent before publishing more team material.

## Publication formatting

The main midterm manuscript uses IEEE conference formatting with the four confirmed author names and university emails, a five-page target and a hard six-page cap. Extended scientific results live in the separately compiled supplementary appendix. GitHub CI compiles both and checks the main paper's page count; individual contributions require team confirmation.

The IEEE report build requires the `texlive-publishers` LaTeX distribution for `IEEEtran` and `IEEEtranN`.

## One combined report

GitHub Actions now builds `report/combined_report.pdf`, containing the five-page IEEE main manuscript followed by the supplementary appendix. The appendix is part of the same PDF and repository but does not count toward the five-page main-text limit. Sources remain separately editable in `report/main.tex` and `report/appendix.tex`.
