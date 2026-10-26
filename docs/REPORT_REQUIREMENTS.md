# 5–7-page midterm paper: required evidence and layout

Target: conventional two-column or single-column academic article matching the supplied revised report's restrained article styling. Do not invent completed work to fill pages. Keep author list and contributions subject to team confirmation.

## Sections (suggested approximate space)
1. Abstract (~150–200 words): research question, what was actually executed, grounded results or PENDING.
2. Introduction & project bounds (~0.75 page): IQCC/Columbia motivation, idle qubit during MCM, metrics, hypotheses and scope.
3. Related work (~0.75 page): Viola/Knill/Lloyd; Cywinski; Uhrig; Bylander; Alvarez/Suter; Biercuk; Souza; Ezzell; Rahman; Tong et al.; distinguish empirical vs model-based.
4. Physical model (~0.75 page): H(t), Gaussian noise assumption, PSD convention, Y(w), chi, W, fidelity, T1 and coherent frame correction, finite control limits.
5. Methods (~1.0 page): synthetic device, spectroscopy and independent held-out fits, finite-pulse simulator, CMA-ES, canonical baselines, robustness and IQCC plan.
6. Experiments and results (~1.25–1.75 pages): only results executed; benchmark matrix, uncertainty, ablations, sensitivity plots and negative findings. If not run, use a short transparent planned-experiments section.
7. Discussion, limitations & roadmap (~0.75 page): hardware mismatch, shot noise, non-Gaussian noise, QUA access, credible future work.
8. Team contributions, AI use, references (remaining space). Appendix only if permitted.

## Minimum empirical exhibits once work exists
- PSD truth/fitted, with correct units and credible interval.
- Independent held-out Ramsey/Hahn/CPMG decay curves and uncertainty.
- Equal-n equal-T benchmark table: free, standard DD families, joint optimizer, virtual-Z where applicable, infidelity with confidence intervals.
- Optimization training vs held-out evaluation convergence.
- Robustness sensitivity to readout timing/amplitude, PSD misspecification and pulse imperfections.
- Performance summary across >=3 random seeds unless smaller exploratory budget explicitly disclosed.
- Feasibility table listing n, T, pulse width, guard spacing, timing-grid rounding.

## Claim ledger
Maintain machine-generated `report/evidence_map.csv` with:
claim_id, paper_section, exact_claim, provenance_type(literature/model/dataset/hardware), artifact_path, command, commit_sha, run_id, seed, reviewer, verification_status.
No numerical figure, author contribution, test pass count, dependency version, hardware assertion or significance statement without a corresponding ledger entry.

## Critical wording
- “Simulation predicts” only when there is a computed file, and state scenario.
- “Measured” only with raw hardware data, calibration context and run ID.
- “Hardware-ready” only after backend configuration/timing validation; SDK compile is not hardware-ready.
- “Improvement factor” and “percent reduction” must show denominator and raw infidelities.
- “AI” in this project means data-driven identification / CMA-ES; do not call CMA-ES deep RL.
- QM brief's prior SAC readout result is another project, not this DD project's result.

## Submission checks
`latexmk -pdf -halt-on-error` or equivalent; no unresolved refs, broken figure paths, unsupported citation, or placeholder pretending to be an actual result. Render all PDF pages for layout QA. Validate 5–7 pages including/excluding references per course rule; state which count is used. Ensure affiliations and contribution roster reconcile and team confirms authorship.
