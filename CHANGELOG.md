# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Scientific results are versioned by
the pinned runs in `report/runs.json`, not by the package version.

## [Unreleased]

## [0.1.0] - 2026-10-27

### Added
- `ddopt` library: two-sided PSD noise models and exact samplers, generalized filter functions,
  PTM channels with amplitude damping, canonical DD sequences with timing/grid validation,
  finite-pulse Monte-Carlo simulator with virtual-Z, synthetic spectroscopy with held-out scoring,
  CMA-ES optimizer (pycma 4.5.0), paired-bootstrap evaluation, provenance with checksummed runs.
- Pre-registered experiment plan, Scenario A/B configs and ablation configs.
- Recorded runs: G3 validation, Scenario A/B benchmarks, T = 4 µs window, spectroscopy,
  model-based pipeline, ablations, convergence diagnostic, test-suite record.
- IEEE conference-format paper (≤ 6 pages; four Columbia authors) and separate supplementary appendix, generated from recorded runs; claims ledger (`report/evidence_map.csv`).
- Independent red-team review (`docs/REVIEW_FINDINGS.md`) and citation audit.
- SDK-free QUA schedule adapter (not hardware tested) and hardware protocol.
- Website (online paper) and GitHub Pages workflow; CI and release workflows.

### Findings
- Synthetic, pre-registered: CMA-ES did not beat XY4/XY8 on held-out noise; see the paper.

[Unreleased]: https://github.com/udsy19/quantum-dd-optimizer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/udsy19/quantum-dd-optimizer/releases/tag/v0.1.0
