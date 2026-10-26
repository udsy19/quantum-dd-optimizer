# Quantum DD Optimizer

> **Project stage: research design / implementation pending.** No validated simulation results, working numerical pipeline, IQCC hardware data, or optimized-device gains have been established.

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

These files are **deliverables to create**, not functionality currently claimed to exist.

## Evidence policy

The previous draft's claims of seven passing tests, 1% agreement, 1% fit recovery or 1.7–1.8× improvement are unverified and must never be repeated as outcomes without real reproducible runs. CMA-ES is an evolution strategy, not an RL agent. QUA compilation is not IQCC hardware validation. A positive, neutral, or negative result is a valid research outcome if the protocol and evidence are sound.

The course-supplied PDF describes *another* completed SAC readout optimization project and lists dynamical decoupling as a potential follow-up topic; its hardware results are **not our team's DD results**.

## Original research report

The revised draft manuscript is currently distributed as an editable LaTeX attachment and PDF in the project conversation. The repository's report source/binaries must be added separately before stating that the report was pushed. Do not fabricate a replacement with unverifiable figures.

Confirm license choice and author consent before publishing more team material.
