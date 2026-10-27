# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Scientific results are versioned by
the pinned runs in `report/runs.json`, not by the package version.

## [Unreleased]

### Fixed
- Report wording that overstated the data: Scenario A gains are "at most about 1%" (largest ratio
  1.011), not "sub-percent"; CMA-ES gained under 0.5% over XY8 at n = 8 in two ablations rather than
  never beating it; the limitations now name all 5 of 11 pinned runs recorded from a dirty tree.
- Report figures: main Fig. 2 is a held-out ratio plot with bootstrap intervals, all figures embed
  TrueType fonts (no Type 3), panels are labelled, text is legible at print size.
- IEEE layout: 2x2 author block, date in the title block, run-in headings without doubled
  punctuation, S-prefixed supplement numbering, breakable run ids, paths and URLs.

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
- Website (online paper) rendered from the `report/` LaTeX sources at build time and redeployed by GitHub Pages on every push to `main`; CI and release workflows; issue/PR templates; Dependabot.

### Findings
- Synthetic, pre-registered: CMA-ES did not beat XY4/XY8 on held-out noise; see the paper.

[Unreleased]: https://github.com/udsy19/quantum-dd-optimizer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/udsy19/quantum-dd-optimizer/releases/tag/v0.1.0
