<div align="center">

# Quantum DD Optimizer

**Model-based dynamical decoupling under hardware timing constraints for idle superconducting qubits**

Christian De Zabala F. · Madeline Feldner · Zarar Haider · Udaya Vijay Anand — Columbia University

A pre-registered, held-out synthetic benchmark of CMA-ES–optimized dynamical-decoupling (DD) sequences against canonical DD, with explicit noise floors, full provenance and an honest negative result.

[![CI](https://github.com/udsy19/quantum-dd-optimizer/actions/workflows/ci.yml/badge.svg)](https://github.com/udsy19/quantum-dd-optimizer/actions/workflows/ci.yml)
[![Pages](https://github.com/udsy19/quantum-dd-optimizer/actions/workflows/pages.yml/badge.svg)](https://github.com/udsy19/quantum-dd-optimizer/actions/workflows/pages.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-black.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-black.svg)
![Status](https://img.shields.io/badge/results-synthetic%20only-orange.svg)

[**Website / online paper**](https://udsy19.github.io/quantum-dd-optimizer/) ·
[Paper source (IEEE)](report/) ·
[Experiment plan](docs/EXPERIMENT_PLAN.md) ·
[Red-team review](docs/REVIEW_FINDINGS.md) ·
[Progress log](docs/PROGRESS.md)

</div>

> [!IMPORTANT]
> **Everything here is a simulation of a synthetic model.** No quantum hardware (IQCC or other)
> has been accessed or used, and no measured data exist. "CMA-ES" is an evolution strategy, not
> reinforcement learning. Badges for CI and Pages show live status; neither had been observed
> running at the time of writing.

---

## TL;DR

| Question | Answer (synthetic model, held-out noise) |
|---|---|
| Does the finite-pulse Monte-Carlo simulator agree with filter-function theory? | **Yes.** All 5 pre-registered cases agree within 1.96 SE (max \|z\| = 0.95). |
| Can synthetic Ramsey/Hahn/CPMG spectroscopy recover a *predictive* noise model? | **Yes for prediction** (held-out RMSE 1.15× the shot-noise floor, 95 % coverage 0.934); **no for unique spectrum reconstruction**. |
| Does CMA-ES beat the strongest canonical DD (XY4/XY8) in the pre-registered Scenario A? | **No.** XY8 reaches 1.00×10⁻², essentially the T1 + white-noise floor of 9.90×10⁻³. |
| With a deterministic readout-like Stark shift + virtual-Z (Scenario B)? | Nominal gains of 2–5 % at n = 4 only. The timing+phase variant **reverses** under ±100 ns timing shifts (worst case 2.11×10⁻² vs 1.13×10⁻² for XY4+VZ); phase-only remains marginally better, model-specific. |
| Do more headroom or fitted noise models help? | **No.** Training gains do not generalize (overfitting to frozen noise draws). |

Every number above is generated from checksum-verified runs listed in [`report/runs.json`](report/runs.json)
and traced in [`report/evidence_map.csv`](report/evidence_map.csv).

## Contents

- [What this is](#what-this-is)
- [Quick start](#quick-start)
- [Reproduce the study](#reproduce-the-study)
- [Repository layout](#repository-layout)
- [Physics conventions](#physics-conventions)
- [Scientific integrity](#scientific-integrity)
- [Hardware status](#hardware-status)
- [Website](#website)
- [Citing](#citing)
- [Contributing, releases, security](#contributing-releases-security)
- [License](#license)

## What this is

An idle qubit waiting during a neighbour's mid-circuit measurement dephases (stochastic noise)
and picks up deterministic phase (readout-induced ac-Stark shifts). Dynamical decoupling fights
both. This project asks whether **model-based optimization** of DD pulse timings and phases
beats strong canonical sequences **when the comparison is made fair**:

- same idle window *T*, pulse count *n*, pulse width, guard spacing, controller grid and frame-correction privileges;
- strongest baseline chosen by a **pre-registered training-only rule**;
- all arms scored on **independent held-out noise seeds**;
- explicit physical floors (T1, white noise) shown alongside every result.

Components (`src/ddopt/`):

| Module | Purpose |
|---|---|
| `noise` | Two-sided PSD models (1/f, Lorentzian/OU, white, telegraph), exact samplers |
| `filters` | Switching / generalized vector filter functions, χ quadrature with error estimates |
| `channels` | Pauli-transfer-matrix channels, amplitude damping, average gate fidelity |
| `sequences` | Free, Hahn, CPMG, XY4, XY8, UDD with feasibility, guard and grid validation |
| `simulator` | Finite-pulse Monte-Carlo propagation, noise-averaged channel, virtual-Z |
| `spectroscopy` | Synthetic Ramsey/Hahn/CPMG data, binomial-likelihood fits, held-out scoring |
| `optimizer` | CMA-ES (pycma 4.5.0) over gaps/phases with target-preserving phase projection |
| `evaluation` | Baselines, pre-registered selection, paired block bootstrap, Scenario B arms |
| `provenance` | Immutable run directories with manifests and SHA-256 checksums |
| `qua/` | SDK-free QUA schedule adapter — **template, not hardware tested** |

## Quick start

```bash
git clone https://github.com/udsy19/quantum-dd-optimizer.git
cd quantum-dd-optimizer
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
python -m pytest -q          # ~250 tests, ~35 s
```

```python
from ddopt import sequences, simulator
from ddopt.scenarios import load_scenario, scenario_noise, sim_config

cfg = load_scenario("scenario_a")                 # synthetic assumptions, see configs/
noise = scenario_noise(cfg)
seq = sequences.xy8(8, T=2e-6, width=32e-9, guard=4e-9, dt_grid=4e-9)
res = simulator.simulate(seq, noise, sim_config(cfg, seed=1, n_traj=512))
print(f"{res.infidelity:.3e} ± {res.infidelity_stderr:.1e}")
```

Exact versions used for the recorded runs: [`requirements-lock.txt`](requirements-lock.txt) (Python 3.13.17, Linux x86-64).

## Reproduce the study

Each script writes a new immutable `results/<run_id>/` (payload, manifest with git SHA / versions / seeds / command, `SHA256SUMS`) and refuses to overwrite.

```bash
python scripts/run_g3_validation.py --n-traj 64000                 # G3: Monte Carlo vs filter function
python scripts/run_spectroscopy.py                                 # G4: synthetic spectroscopy, held-out scoring
python scripts/run_benchmark.py --scenario scenario_a              # pre-registered benchmark
python scripts/run_benchmark.py --scenario scenario_b --robustness # Stark shift + robustness sweep
python scripts/run_benchmark.py --scenario scenario_a --T 4e-6 --name benchmark_scenario_a_T4us
python scripts/run_model_based.py --spectroscopy-run <spectroscopy run id>
python scripts/run_convergence.py --scenario scenario_a --n 8      # exploratory
python scripts/run_tests_recorded.py                               # stores the test-suite outcome

python -m ddopt.provenance verify results/<run_id>                 # checksum verification
python scripts/make_report_artifacts.py                            # figures, tables, number macros, ledger
bash scripts/build_report.sh                                       # report/main.pdf (latexmk)
python scripts/build_site.py                                       # website into site/dist/
```

Approximate wall time on 4 CPU cores: benchmark A ≈ 5 min, B with robustness ≈ 20 min, G3 ≈ 7 min, spectroscopy ≈ 2–6 min.

## Repository layout

```
src/ddopt/        library (see table above) + contracts.py (typed public data contracts)
tests/            unit, integration and reproducibility tests
configs/          synthetic scenario configs (all values are assumptions)
scripts/          seeded experiment, report and site entry points
results/          immutable recorded runs (evidence)            figures/   generated figures
report/           LaTeX paper, generated tables/macros, claims ledger
site/             website source; built to site/dist in CI
qua/              gated, SDK-free QUA adapter (not hardware tested)
docs/             plan, conventions, physics derivations, review, audits, progress
```

## Physics conventions

ħ = 1; times in s; angular frequencies and detunings in rad/s; **two-sided** PSD
S₂(ω) = ∫ C(τ) e^{−iωτ} dτ in rad²/s; Y(ω) = ∫₀ᵀ y(t) e^{iωt} dt; χ = (1/2π) ∫ S₂ |Y|² dω;
W = e^{−χ/2} (Gaussian); pure-dephasing infidelity r = (1 − W)/3; amplitude damping γ = 1 − e^{−t/T₁}
with r_AD = (2 + γ − 2√(1−γ))/6; F_avg = (Tr R + 2)/6; fidelity graded against the ideal net
control unitary (plus virtual-Z where allowed). Full statement: [`docs/PHYSICS_CONVENTIONS.md`](docs/PHYSICS_CONVENTIONS.md);
derivations and measured tolerances: [`docs/PHYSICS.md`](docs/PHYSICS.md).

## Scientific integrity

- **Pre-registration:** scenarios, seeds, baselines, selection rule and metrics were committed before any optimization run ([`docs/EXPERIMENT_PLAN.md`](docs/EXPERIMENT_PLAN.md)); deviations are logged there, including one plumbing smoke run that touched held-out seeds and the post-hoc exploratory ablations.
- **No mutable "latest":** the report and website read only runs pinned in [`report/runs.json`](report/runs.json), verified by checksum.
- **Independent review:** an AI red-team pass re-derived the conventions, reproduced numbers bit-for-bit and found no critical defect; its high-severity finding is incorporated ([`docs/REVIEW_FINDINGS.md`](docs/REVIEW_FINDINGS.md)). Human review of the evidence ledger is pending.
- **Known limitations:** synthetic Gaussian stationary noise; Scenario B models a deterministic shift only (no measurement-induced dephasing); T1 during pulses approximated. The 12 public references were identity-checked against their arXiv records (title, authors, year, abstract); publisher pagination/DOIs are not fully audited ([`docs/CITATION_AUDIT.md`](docs/CITATION_AUDIT.md)).

## Hardware status

**Not run.** There is no IQCC access, authorization, calibration or run ID. `qua/` translates a
`PulseSequence` into a clock-cycle schedule and, if the QM SDK is installed, a QUA program
object — it never opens a connection or executes. Protocols and gates for prospective,
authorized hardware work: [`docs/HARDWARE_PROTOCOL.md`](docs/HARDWARE_PROTOCOL.md).

## Website

The online paper at **https://udsy19.github.io/quantum-dd-optimizer/** is generated from the same
pinned runs by `scripts/build_site.py` and deployed by [`.github/workflows/pages.yml`](.github/workflows/pages.yml)
on pushes to `main`. One-time setup: *Settings → Pages → Build and deployment → Source: GitHub Actions*.

## Citing

See [`CITATION.cff`](CITATION.cff) (GitHub shows a "Cite this repository" button).

## The paper

`bash scripts/build_report.sh` builds the IEEE conference-format paper (`report/main.pdf`; five-page
target, hard six-page cap enforced by the script), the separately compiled supplementary appendix
(`report/appendix.pdf`) and **one combined PDF** (`report/combined_report.pdf`: main paper followed by
the appendix; the appendix does not count toward the page limit). Sources stay separately editable in
`report/main.tex` and `report/appendix.tex`. The build needs `texlive-publishers` (IEEEtran, IEEEtranN),
`latexmk` and `poppler-utils` (`pdfinfo`, `pdfunite`). CI builds and uploads all three PDFs; the website
links the combined PDF. Individual contribution attributions await confirmation by all four authors.

## Contributing, releases, security

- [CONTRIBUTING.md](CONTRIBUTING.md) — development setup, evidence rules, PR checklist
- [RELEASING.md](RELEASING.md) and [CHANGELOG.md](CHANGELOG.md) — versioning and release procedure
- [SECURITY.md](SECURITY.md) — reporting vulnerabilities; never commit credentials or device configs
- [docs/ABOUT.md](docs/ABOUT.md) — project background and repository "About" metadata

## License

[MIT](LICENSE) © 2026 Udaya Vijay Anand. Team material beyond this repository requires the authors' consent before publication.
