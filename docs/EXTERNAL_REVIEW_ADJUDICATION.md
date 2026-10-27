# External scientific review: adjudicated recommendations

Review date: 2026-10-27. Original reviewer text was supplied by the project owner.
This audit distinguishes confirmed mathematical statements from hypotheses and from
new experiments. All historical run artifacts are preserved.

| Recommendation | Verdict | Evidence and disposition |
|---|---|---|
| $T_1$ + white-noise floor near 9.90e-3 | **Correct under the specified channel model** | Confirmed by analytic composition and model configuration. Incorporated into abstract, results and discussion. |
| Amplitude-damping infidelity formula | **Correct** | $(2+\gamma-2\sqrt{1-\gamma})/6$; code already matches. |
| CPMG amplitude-error growth | **Directionally correct, idealized approximation** | Fixed $Y$ axes accumulate quasi-static rotation error, confounding timing-only comparison. Numerical estimates depend on noise-channel composition; do not label this a derivation of every table number. |
| Benchmark lacks optimization headroom | **Substantially correct, wording overstated** | Near floor, the maximum *physically removable* infidelity is small, so the negative result is weak evidence about optimizer efficacy. It does not mean RQ3 was literally unanswerable. Report foregrounds this and the post-hoc colored-noise sensitivity study. |
| Replace stochastic training objective | **Valid research recommendation, not a retroactive correction** | Analytic PSD-filter score is exact only for ideal instantaneous pulses under stationary Gaussian dephasing; finite pulse uses second-order approximation, and amplitude/control errors need separate treatment. Added explicitly restricted proxy and exploratory pilot. Needs controlled new benchmark. |
| Timing-only seeded at CPMG-Y is confounded | **Correct** | Original optimizer explicitly defaults to CPMG-Y. Fair XY8-seeded timing-only experiment remains to be run, not silently substituted for original results. |
| 2000 evaluations too small to generalize | **Correct limitation** | Only statements about this configuration and budget are supported. |
| Readout-aware XY4 heuristic should win | **Plausible, not established** | Added a guarded scheduling heuristic for prospective testing. The claim it will be robust and superior is unproven and cannot be included as a result. |
| Stark-detuned pulses explain all gain | **Plausible mechanism only** | Approximate phase and detuning scaling can match order of magnitude, but pulse-level decomposition needed before causal attribution. |
| Dirty historical runs | **Confirmed** | Five of 11 pinned runs have dirty-tree provenance without diffs. Re-running clean can test sensitivity but cannot retroactively prove which old code produced those artifacts. Keep original datasets, run IDs and disclosures. |
| Pre-registration in git not independently time-stamped | **Valid** | External timestamp/hash for the *next* preregistration is appropriate. Do not describe a later timestamp as original preregistration. |
| Repeated disclaimers harm presentation | **Editorially reasonable** | Motivating introduction improved. Retain scope in abstract and discussion, and technical caveats where method-specific. |
| Rahman journal title | **Correct** | Publisher confirms *Learning how to dynamically decouple by optimizing rotational gates* (2024). Bibliography updated. |
| Green et al. publication year | **2012, not 2013** | Primary PRL record confirms 109, 020501 (2012), DOI 10.1103/PhysRevLett.109.020501. Correct entry added. |
| G4 fit intervals and held-out claims | **Known limitations** | Single synthetic data seed and correctly specified analytic generator do not show out-of-family physical predictiveness. Multi-seed/finite-pulse evaluation is future work. |
| Timing-only convergence caption contradiction | **Confirmed inconsistency, cause unverified** | Fig. S4 uses a timing-only label inconsistent with stated CPMG-Y methods and numerical table. Text now discloses unresolved provenance; definitive fix requires re-generating plot from logged configuration. |
| Main numerical table, appendix trimming | **Sound editorial ideas, layout dependent** | Need regenerate PDF and verify main paper stays <=6 pages, with evidence-backed rows only. |
| Cywinski/Alvarez diacritics | **Requires rendered-PDF QA** | BibTeX accent escape handling should be checked on compiled pages, not inferred from pdftotext alone. |
| IonQ key/experiments | **Separate platform** | IonQ gate-level trapped-ion outcomes cannot validate transmon analog timing or neighboring readout Stark model. Never claim they do. |

## Gate for the next experimental results

New runs must have distinct configurations and seed sets, clean versioned source,
independent evaluation, explicit run manifests, and separate analysis of
ideal-filter and finite-pulse objectives. The exploratory branch currently
adds a theoretical filter proxy and guarded XY4 heuristic, **not results**
supporting improvement. No IonQ remote jobs have been submitted.
