# Independent reviewer findings (Agent G, scientific red team)

Reviewed integration head `e0e9516` of `claude/focused-archimedes-4i4x55` (2026-10-27).
Scope: physics, leakage, fairness, statistics, reproducibility, report and gates G0–G9.
I own only this file. I did not modify code, results or the report. All reruns used scratch
copies or read-only access. Scratch scripts are under the session scratchpad. They are
referenced by name below and are not committed.

## Summary verdict

**Not releasable as is: one HIGH and six MEDIUM findings are open. I found no critical
defect.**

The core machinery holds up under independent checks:

* **PSD and filter-function code.** Prefactors and filter functions match my brute-force
  computation to 6e-5 (free evolution) and 1e-6 (XY8-8).
* **Fidelity formulas.** The AD and fidelity formulas are correct, and so is the sign of the
  virtual-Z correction.
* **Seed separation.** Training and test seeds are disjoint by construction and by
  enforcement.
* **Reproducibility.** The stored test infidelities reproduce bitwise. Checksums verify. The
  test suite reproduces. All report macros regenerate identically from the pinned runs.
* **Scenario A conclusion.** The negative Scenario A result is sound, and "XY8 at the
  T1 + white floor" is a fair description (1.3 % above the floor).

The main problem is what the report says about the one positive result. The abstract cites a
Scenario B n=4 timing+phase gain (ratio 1.024–1.050). The pre-registered robustness sweep
shows that this gain **reverses under ±50–100 ns readout-timing shifts in all three training
runs**, and the report does not say so (H1). The pre-registered RQ4 asks exactly whether a
gain survives readout uncertainty, so the answer the report currently gives is incomplete.
Several descriptive claims are also wrong or overstated (M1–M4).

## Findings

| ID | Sev. | Location | Description | Evidence | Recommended fix |
|---|---|---|---|---|---|
| H1 | **high** | `report/sections/abstract.tex:13-14`; `report/sections/results.tex:107-118`; Fig. 4 via `scripts/make_report_artifacts.py:300-306` (`n_show = 8`, `rs[0]` only) | **Headline result.** The only positive result in the abstract, Scenario B n=4 timing+phase, is fragile, and the robustness evidence against it is not reported. **Reversal under timing shifts.** The CMA-ES+virtual-Z arm becomes up to 1.9× *worse* than XY4+virtual-Z under ±50/±100 ns shifts, in every training run. **Same at n=8.** Runs 102 and 103 degrade to ≈2.0e-2 against 1.02e-2. **Selective presentation.** The text and Fig. 4 show only n=8, training run 1, which is the most robust of the three. They describe only the virtual-Z and DD+virtual-Z arms. **Likely mechanism.** The optimized n=4 sequences need large nominal virtual-Z angles (0.36 rad, −0.17 rad, −0.03 rad, against −0.0003 rad for XY4), so they rely on knowing the Stark profile exactly. | Ran `scratchpad/rob.py` on `results/benchmark_scenario_b_*/payload.json` (mode `both`, ε for XY4+VZ against CMA+VZ). **n=4, train 101:** shift −100 ns 1.106e-2 vs **1.605e-2**; −50 ns 1.107e-2 vs 1.177e-2. **n=4, train 102:** +100 ns 1.112e-2 vs **1.454e-2**; +50 ns 1.110e-2 vs 1.285e-2. **n=4, train 103:** +100 ns 1.112e-2 vs **2.111e-2**; amplitude ×0.8 1.088e-2 vs 1.172e-2. **n=8:** train 102 −100 ns 1.016e-2 vs 1.989e-2; train 103 −100 ns 1.016e-2 vs 2.079e-2. Virtual-Z angles are from `test.per_seed.optimized.9001.virtual_z_angle`. | **Abstract and RQ4.** State that the timing+phase gain does not survive ±50 ns timing uncertainty, or ±20 % amplitude uncertainty in one run. **Fig. 4.** Show all three training runs and n=4. **Results text.** Add CMA+VZ min/max macros. **Phase-only.** Mention that phase-only n=4 *does* stay ahead of XY4+VZ across the whole sweep in all runs (see M2). |
| M1 | medium | `report/sections/results.tex:60-61` | **False mechanistic claim.** The report says phase-only CMA-ES "rediscovers XY4/XY8-like axes". **n=4:** all three solutions put every pulse on *one* axis with π sign flips, i.e. a phase-alternated CPMG (a ā ā a or a a ā ā), which cancels amplitude over-rotation pairwise. That is not XY4. **n=8, 16:** the phases are scattered, non-canonical sets with no XY8 structure. | Ran `scratchpad/phases2.py` on the Scenario A payload. Phases relative to the first pulse, in units of π/2. **n=4 phase, train 101:** [0, 2.0, 2.03, 0.02]. **train 102:** [0, 3.98, 1.99, 2.01]. **train 103:** [0, 2.0, 1.99, 3.99]. **n=8 phase, train 101:** [0, 1.43, 1.17, 3.06, 3.22, 1.8, 2.28, 0.39]. | Replace the sentence with: "phase-only finds sign-alternated single-axis sequences at n=4 and non-canonical phase sets at n=8, 16 that match XY4/XY8 within 0.4 %". Give the reason (cancellation of amplitude errors). Consider adding phase-alternated CPMG as a canonical baseline. |
| M2 | medium | `abstract.tex:13-14`; `results.tex:107-113` | **Post-hoc highlighting and multiple comparisons.** **Number of comparisons.** About 27 pooled comparisons in Scenario B alone (3 n × 3 modes × 3 runs), and more than 100 across all variants. **Bonferroni over the 27 Scenario B comparisons.** Under a normal approximation from the percentile CIs, only training run 102 of n=4 timing+phase survives; runs 101 and 103 do not. **Wrong mode highlighted.** The robust n=4 effect is phase-only (1.008–1.048, tight CIs, and it holds across the robustness sweep), yet the abstract cites timing+phase. **Scenario A wording.** The text says "No CMA-ES mode improves", but phase-only at n=4 has CIs excluding 1 (1.001–1.002), a negligible gain. **"Pooled" intervals.** "Pooled 95 % MC intervals 1.004–1.077" is actually the envelope of three per-run CIs. | **Pooled ratio_ci, Scenario B n=4 both:** [1.004, 1.064], [1.023, 1.077], [1.008, 1.040]. Approximate z = 2.16, 3.6, 2.9 against a Bonferroni(27) threshold of 3.11. **Phase-only:** [1.006, 1.011], [1.046, 1.051], [1.006, 1.011]. **Phase-only under perturbation** (`scratchpad/rob.py … phase`): CMA ≤ XY4+VZ at every amplitude and shift point in all 3 runs. **Scenario A phase n=4:** ratio_ci [1.001, 1.003], [1.000, 1.003], [1.001, 1.003]. | **Exploratory label.** Call any positive cell exploratory and selected post hoc. **Correction.** Report a Holm/Bonferroni-adjusted statement, or no significance language at all. **Abstract.** Lead with the robust phase-only n=4 observation, with its size (≤5 %). **CI label.** Call the interval an "envelope of per-run 95 % CIs". **Scenario A.** Say "no practically relevant improvement (≤0.2 %)". |
| M3 | medium | `report/sections/methods.tex:31-40`; `results.tex:22-40`; `src/ddopt/spectroscopy.py:8-48` | **Spectroscopy is close to an "inverse crime", and the report does not disclose it.** **Shared forward model.** The Gaussian truth data come from the *same analytic filter-function forward model* that is fitted (`method="analytic"`), with instantaneous pulses and no amplitude errors. **Favourable fixed inputs.** T1 is fixed to the true value, and the 1/f and white cutoffs are fixed to the true values. Held-out RMSE 1.15× floor and coverage 0.934 therefore mostly test the statistics of the fit, not model adequacy. **Uninformative CIs.** The "every parameter CI contains truth" statement hides that the CIs span orders of magnitude. **Single seed.** Only one data seed is used. | **Payload** (`pipeline.repeats[0].truths.gaussian.fits.full_alpha1`): MLE S0 = 1.37e4 against truth 1.0e4, with CI [2.3, 2.4e4]. σ CI is [6.9e3, 3.7e5] against truth 1.24e5. τ_c is 0.33 µs against 0.5 µs, with CI [3.8e-8, 3.6e-6] s. **Docstring.** `spectroscopy.py:12-14` ("instantaneous by default") and `:38-41` ("defaults = Scenario A config values, i.e. the favourable case"). | **Methods.** State that the forward model is shared, pulses are instantaneous, T1 is known exactly, cutoffs are at the truth and no control errors are present. **Results.** Quote the CI widths. **G4.** Label it as only partially met (see the gate table). **Future work.** Generate data with the finite-pulse MC simulator. |
| M4 | medium | `report/evidence_map.csv` (PROV-02); `results.tex:16`; `scripts/make_report_artifacts.py:181-182` (bench table caption) | **Ledger and number hygiene.** **Stale ledger row.** PROV-02 still asserts "All simulation experiments are NOT RUN in this draft; no numerical result is reported", which is now false. **Overstated G3 precision.** The report says "mutually consistent at the ~10⁻³ relative level", which is hard-coded and overstated. The G3 test resolution is 1.96·SE/r ≈ 1.0–1.1 % for all rows. **False table caption.** The caption claims "MC standard errors ≲1 % of ε", which is false for CPMG, free evolution, UDD and timing-only. **Unreviewed ledger.** All 218 rows have reviewer PENDING, and 203 are UNVERIFIED. | **G3 payload:** se/r = 1.17e-4/2.18e-2 = 0.54 % (FID); 1.84e-5/3.55e-3 = 0.52 % (CPMG8_w32). **Standard errors** (`scratchpad/se.py`, Scenario A): pooled relative SE up to 1.51 % (CPMG-8, UDD-8, timing-only-8), 1.46 % (free evolution); per-seed up to 3.5 %. **Ledger** (`grep -v ^GEN- report/evidence_map.csv`): PROV-02 present. | **PROV-02.** Remove or rewrite it. **G3 wording.** Write "consistent within the ≈1 % (95 %) MC resolution". **Caption.** Write "≲1.5 % (pooled), ≲3.5 % per seed", or generate the caption from the data. **Ledger.** Set `verification_status`/`reviewer` only for the rows reproduced below. |
| M5 | medium | `report/sections/introduction.tex:26-27` (RQ5); `docs/CLAUDE_CODE_MASTER_PROMPT.md` P5.2; `discussion.tex` | **Robustness coverage is incomplete, and the gaps are not stated.** **Promised but not evaluated:** RQ5 and P5.2 promise drift and calibration error, smoothness, and control quantization. **What was tested:** Stark amplitude and timing, plus the no-amp, no-T1 and colored ablations, plus the fitted-model pipeline. **Untested:** `detuning_offset` drift is never non-zero, the Stark rise time is never varied, and the timing grid is fixed at 4 ns. | `grep detuning_offset configs/*.json` gives 0.0 everywhere. `perturbed_detuning_models` (`evaluation.py:366-380`) only scales amplitude and shifts t_on/t_off. | **Discussion.** List the untested items as NOT RUN, or narrow RQ5. **G6.** Mark it PARTIAL until this is done. |
| M6 | medium | `scripts/run_benchmark.py:67` (manifest built after the run); `src/ddopt/provenance.py:172-177` | **Provenance capture time.** The git SHA and dirty flag are recorded at *write* time, not at start. **Scenario A example.** The run started at ≈23:20:37Z (created 23:25:17 minus 280 s wall time). That is before the benchmark driver was committed (`db1534d`, 23:21:05), yet the manifest records `c7d1e5b`, clean. **Benign here.** `src/ddopt` (excluding spectroscopy) is unchanged from `4b4a6dc` to HEAD, and I reproduced values bitwise. **Weak provenance elsewhere.** 5 of 11 runs are `dirty: true` with no diff or untracked list recorded. | `scratchpad/times.py`: Scenario A `created 23:25:17 wall_s=280 sha=c7d1e5b dirty=False`. `git log`: `db1534d 23:21:05 Add pre-registered benchmark driver`. `git diff --stat 4b4a6dc 995776a -- src/ddopt scripts/run_benchmark.py configs/scenario_a.json configs/scenario_b.json` shows additions only (spectroscopy.py, run_benchmark.py). Dirty runs: noT1, noamp, T4us, spectroscopy, test_suite. | **Capture at start.** Record the git state when the run starts, and fail if the tree is dirty, or store `git diff` and the untracked list in the manifest. **Report.** Disclose that some manifests are dirty. |
| L1 | low | `results.tex:68-71`; `scripts/make_report_artifacts.py:98-105` | **Floor statement checked; it is fair but model-internal.** The "T1 + white floor" uses χ = S0·T and ignores the 100 MHz cutoff. The cutoff effect is negligible, so the floor is a valid lower bound within this model (Gaussian, AD composed per segment, symmetric AD splitting during pulses). | **Independent filter function** (`scratchpad/indep_ff.py`): χ_white(XY8-8) = 1.99893e-2 against S0·T = 2e-2. **Floor:** cutoff-aware 9.89891e-3 against 9.89900e-3 used. **XY8-16:** 1.0032e-2 is 1.3 % above the floor (pooled SE 0.6 %). **Colored residual:** filter function + AD predicts 2.4e-4 for XY8-8. | Optional: say "within 1.3 % of" instead of "at". Note that the floor depends on the AD-during-pulse approximation. |
| L2 | low | `report/generated/ablation_table.tex` (no-amp rows) | **Baseline-selection noise inflates some ablation ratios.** With 256 training trajectories, the training-only rule picks UDD at n=8 in the no-amp ablation, although CPMG, XY4 and XY8 are better on test. The phase-only ratios of 1.007–1.009 there are a selection artefact. | **No-amp n=8:** sel=udd with 1.0193e-2, against cpmg 1.0112e-2, xy4 1.0108e-2 and xy8 1.0109e-2. Optimized: 1.0107e-2. | Add a column or footnote with the ratio against the best baseline on test. |
| L3 | low | `docs/EXPERIMENT_PLAN.md` deviations; `results.tex:129-141` | **Test seeds reused after the primary result was seen.** Seeds 9001–9005 were used for all post-hoc exploratory runs (ablations, T=4 µs, model-based). This is disclosed as exploratory, but these seeds are no longer untouched held-out data. | `report/runs.json` and the payload `grid.test_seeds`. | Use fresh test seeds for any confirmatory follow-up. |
| L4 | low | `scripts/run_benchmark.py:55` | **Bootstrap seed reuse.** The benchmark bootstrap reuses the spectroscopy bootstrap seed 5003. This causes no leakage, but it breaks "disjoint by construction". | `boot_seed=s["spectroscopy"]["bootstrap"]` | Give the benchmark its own bootstrap seed. |
| L5 | low | `report/generated/benchmark_table.tex` | **Stale stub.** An unused stub table containing "NOT RUN" is still in the tree. | `grep -n input report/sections/*.tex` (it is never input). | Delete it. |
| L6 | low | `report/main.tex` title; Figs. 1 and 4 | **Title and figures.** "Hardware-Aware" in the title may be read as a hardware claim, although only hardware-*motivated* constraints are modelled. In Figs. 1 and 4, axis labels and legends are tiny (≈4 pt when printed). The page-count convention (5–7 pages, with or without references) is not stated. | Rendered `pdftoppm -r 70`: pages 4 and 5. | Use "hardware-constrained" or drop the word. Enlarge the fonts. State the page rule. |
| L7 | low | `src/ddopt/spectroscopy.py` `fit` | **MLE depends slightly on the multistart RNG.** The MLE changes by up to 4e-4 relative when the fit's RNG changes, because of the flat likelihood directions. | `scratchpad/specrepro.py`: max relative difference 4.1e-4 (S0, σ, τ_c). | Note it; tighten the optimizer tolerance or seed the starts separately. |
| L8 | low | `results.tex:64-66` | **Context for the timing-only result.** The timing-only losses mainly show that CPMG with Y pulses accumulates the 2 % amplitude error coherently: CPMG-16 has ε = 0.141, worse than free evolution at 0.029. This is correctly disclosed. However, the timing-only arm cannot answer "does timing optimization help". | Payload: cpmg-16 1.4129e-1, free 2.8829e-2. | Optional: run timing-only from XY8 phases on test. The convergence run already does this exploratorily. |

No critical findings. I checked for and did **not** find any of the following:

* **Test/train leakage.** All draws use `default_rng(seed)`, and test seeds 9001–9005 never
  appear in training or selection (`evaluation.py:458,481`, `check_disjoint`).
  CRN/frozen draws are used only in training. Selection uses training draws only
  (`evaluation.py:466-467`).
* **Wrong target unitary.** Zero-noise ε = 0 for all families and all optimized sequences.
* **Virtual-Z sign error.** Stark-only free evolution: ε = 0 with virtual-Z and 0.2303
  without, with θ = 1.2566 rad = +∫d dt. In Scenario B, the virtual-Z-only arm equals
  Scenario A free evolution, 2.8829e-2, to every printed digit.
* **Unequal treatment of baselines and the optimizer.** Same T, w, guard, grid, draws and
  frame privileges. The start point equals the CPMG baseline (`start_matches_cpmg_baseline`
  is true in all 81 runs I inspected).
* **Hardware or measured claims.** None found, in the report or in `qua/`. The QUA adapter is
  labelled "NOT HARDWARE TESTED".
* **Unflagged citations.** Every citation is flagged as metadata unverified.

## Physics re-derivation (checklist item 1)

* **PSD prefactor.** With S2(ω) = ∫C e^{−iωτ}dτ, C(0) = (1/2π)∫S2 dω, and χ = Var ∫δy dt =
  (1/2π)∫S2|Y|²dω. My brute-force time-grid Fourier transform agrees with
  `filters.dephasing_variance` to within 6.4e-5 (FID) and 1.1e-6 (XY8-8, 32 ns pulses, vector
  filter).
* **Coherence and infidelity.** W = ⟨e^{iφ}⟩ = e^{−χ/2} for Gaussian φ. F_pro = (1+W)/2 and
  F_avg = (2F_pro+1)/3, so r = (1−W)/3. This matches `PHYSICS.md` §3.
* **Amplitude damping.** Tr R_AD = 2 + 2√(1−γ) − γ gives r_AD = (2+γ−2√(1−γ))/6, which is
  correct. The master-prompt formula fails at γ = 0, and its rejection is justified.
* **Average gate fidelity from the PTM.** `simulator._favg_from_ptm` uses
  F_avg = (Tr R + 2)/6, and the unitary path uses (|Tr V|²+2)/6. Both are correct for d = 2.
  `R_err = einsum("ji,njk->nik")` is R_targetᵀR, which is correct.
* **Virtual-Z.** With M = U_d U_0†, |Tr(R_z(θ)†M)| is maximal at θ = arg M11 − arg M00
  (`simulator.py:344`). I re-derived this, and it is numerically confirmed (see above).
* **Phase projection** (`optimizer.py:243-247`). It preserves U_0 = ±I. XY-type solutions
  remain reachable through π-shifted equivalents (for example (π, π/2, 0, π/2)), so the
  projection does not block them. The optimizer simply did not converge to them (M1).
* **White floor.** Σ_a y_a² = 1 holds for finite pulses, so by Parseval χ_white = S0·T up to a
  cutoff correction of ≈5e-4 relative (measured). AD's effect on Tr R is pulse-independent
  under the symmetric splitting. The floor is therefore a valid model-internal lower bound
  (L1).

## Reproduced numbers

| Quantity | Stored | Re-computed (red team) | Command / script |
|---|---|---|---|
| Scenario A, XY8 n=8, test seed 9001, ε | 1.018431e-02 | 1.018431e-02 (bitwise) | `scratchpad/repro1.py` (direct `simulator.simulate`, seed 9001, 1024 traj) |
| Scenario A, CPMG n=8, seed 9001, ε | 4.875755e-02 | 4.875755e-02 | same |
| G3 CPMG8_w32 r_FF | 3.547771e-03 | 3.547771e-03 | `scratchpad/g3row.py` |
| G3 CPMG8_w32 r_MC | 3.5527e-3 ± 1.8e-5 (64000 traj) | 3.4890e-3 ± 5.2e-5 (8000 traj, new seed 777), z = −1.13 against FF | same |
| G3 Hahn_w32 r_FF / r_MC | 6.087021e-3 / 6.0929e-3 | 6.087021e-3 / 5.969e-3 ± 9.6e-5, z = −1.23 | same |
| χ FID (Scenario A Gaussian) | 1.351758e-1 (ddopt) | 1.351845e-1 (independent brute force) | `scratchpad/indep_ff.py` |
| χ XY8-8, 32 ns | 2.143051e-2 (ddopt) | 2.143054e-2 (independent) | same |
| XY8-8 ε without amplitude error | 1.0109e-2 (MC, noamp ablation) | 1.01343e-2 (filter function + AD), within 0.4 SE | same |
| Floor (T1 + white) | 9.90e-3 (`\FloorA`) | 9.89900e-3; cutoff-aware 9.89891e-3 | same |
| Spectroscopy MLE (Gaussian, full, α=1) | A_ref 11272.33, S0 13721.5, σ 127787, τ_c 3.3118e-7 | 11272.33, 13724.3, 127746, 3.3132e-7 (max relative difference 4.1e-4) | `scratchpad/specrepro.py` |
| Test suite | 249 passed, 1 skipped | 249 passed, 1 skipped (61 s) | `python -m pytest -q -p no:cacheprovider` |
| Checksums | — | 11/11 OK | `python -m ddopt.provenance verify results/<all 11 dirs>` |
| Report macros, tables, ledger | `report/generated/*`, `evidence_map.csv` | identical except the commit stamp (scratch copy without .git) | `python scripts/make_report_artifacts.py` in a scratch copy, then `diff -r` |
| Evidence-map rows pointing to existing artifacts | 218 | 218/218 exist; 203/203 macros have ledger rows; 0 undefined macros | `scratchpad/macros.py`; `make_evidence_map.py --check` |
| Report build | — | latexmk OK, 7 pages, no undefined references or citations, no overfull hbox | `latexmk -pdf` on a scratch copy; `pdftoppm -r 70`; all 7 pages inspected |

Hard-coded numbers in `report/sections/*.tex` that are neither macros nor config or
convention values:

* `results.tex:16` "~10⁻³ relative" — overstated (M4).
* `results.tex:25` "106 held-out points" — correct: 2×27 + 4×13.
* `results.tex:131` "two orders of magnitude" — correct: 9.75e-5 against 1.00e-2.
* `discussion.tex:11` "a few percent" — correct.
* The bench table caption "≲1 %" — wrong (M4).

Everything else with digits is a config value, a convention, a seed or a section label.

## Gate status

| Gate | Status | Evidence |
|---|---|---|
| G0 environment | PARTIAL | venv + `requirements-lock.txt`; tests pass locally. CI has never been observed running on GitHub, and no clean-clone install is recorded (`docs/PROGRESS.md`). |
| G1 theory | PASS | Explicit conventions in `PHYSICS_CONVENTIONS.md` and `PHYSICS.md`. My independent χ matches to ≤6e-5. AD formula derived and verified. |
| G2 controls | PASS | Zero-noise ε = 0 for all families and optimized sequences, odd and even n (`scratchpad/g2.py`). Guard and grid are enforced in decode/validate. Convergence tests are in the passing suite. |
| G3 MC physics | PASS (wording issue M4) | `results/g3_validation_*`: 5/5 within 1.96 SE (|z| ≤ 0.95). An independent-seed rerun of 2 rows gives z = −1.13 and −1.23. The discretization budget is reported. |
| G4 fit | PARTIAL | Held-out schedules and times, a bootstrap and a misspecification control all exist. But the data come from the same analytic forward model with truth-fixed T1 and cutoffs, there is one seed, the telegraph control is weak (as the report admits), and the CIs are uninformative (M3). Label exploratory. |
| G5 fairness | PASS (with caveats) | Same T, w, guard, grid, draws and frame for all arms. Selection is training-only. Test seeds are disjoint (enforced). ≥4 baselines per n (counting free evolution). Caveats: disclosed smoke-run contact with the test seeds, and selection noise (L2). |
| G6 robustness | PARTIAL | Stark amplitude and timing sweeps, three ablations and model mismatch were run. The negative robustness result for CMA-ES is **not reported** (H1). Drift, smoothness and quantization were not run (M5). |
| G7 QUA | NOT DEMONSTRATED (labelling correct) | The SDK-free translator is labelled "NOT HARDWARE TESTED". The SDK test is skipped (qm-qua not installed), and there is no compile or simulate run ID. The report states this correctly. No hardware claims. |
| G8 report | PARTIAL | All 203 numeric macros trace to checksum-verified runs, and the macros regenerate identically. But PROV-02 is stale and false, there are hard-coded wrong statements (M4), all ledger rows are UNVERIFIED/PENDING, and manifests record the SHA at the end of a run and are sometimes dirty (M6). |
| G9 review | FAIL (until H1 and M1–M6 are resolved) | This review. Citation metadata is unverified because the network is blocked; the report states this. PDF visual QA was done (L6). |

## Not checked / could not check

* **Full benchmark reruns.** I did not rerun the Scenario A or B benchmarks, the ablations,
  T=4 µs, model-based, convergence or CMA-ES optimizations (tens of CPU-minutes to hours
  each). I reproduced individual simulator evaluations and verified that the code is
  unchanged since those runs (`git diff --stat 4b4a6dc 995776a`).
* **Telegraph runs.** I did not check the telegraph-truth spectroscopy runs, the bootstrap CI
  computation, or the T2-derived CIs.
* **Lindblad reference.** I did not compare the T1-during-pulse approximation against a
  Lindblad solution.
* **Infrastructure.** I could not check GitHub CI, a clean-clone install, QM SDK
  compilation (not installed) or citation metadata (no network to primary sources).
* **Authorship.** I did not check author and contribution claims; they are marked PENDING in
  the report.
