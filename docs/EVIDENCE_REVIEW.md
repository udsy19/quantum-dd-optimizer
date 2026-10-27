# Evidence ledger pre-check (IEEE main paper)

> **AI pre-check, NOT an approval; reviewer and approval status must be filled in by a human.**
>
> An AI release-verification agent prepared this table on 2026-10-27. A "yes" in the Match column
> only means that the value printed in the paper equals a value the agent re-read or recomputed from
> the checksum-verified run artifact. It does not verify the physics, the simulator, the
> experimental design or the wording. Every row in `report/evidence_map.csv` is still
> `PENDING` / `UNVERIFIED`. This file does not change that status. Only a named human reviewer can
> fill in the Reviewer and Approved columns below and update the ledger.

## Scope and method

- Commit checked: `0bc48e45c351fc1a03543ad9ace41f45f545e56f` (origin/main at the time of review).
- Claims checked: 22 numerical or numerically testable claims from the IEEE main paper
  (`report/sections/abstract.tex`, `introduction.tex`, `methods.tex`, `results.tex`,
  `discussion.tex`), with priority on the headline numbers.
- Loading: each pinned run in `report/runs.json` was loaded with `ddopt.provenance.load_run`, which
  checks `SHA256SUMS`, the manifest config hash and the run id.
- Recomputation: the agent wrote its own extraction script and did not call
  `scripts/make_report_artifacts.py`. The script was kept in the agent's scratch directory and
  is not committed. It differs from the generator in these ways:
  - Benchmark ratios are recomputed from the raw per-seed infidelities
    (`runs[*].test.per_seed[<arm>][<seed>].infidelity`), not from the `pooled` or `summary` blocks.
  - Scenario B robustness wins and worst cases are recomputed from per-seed lists for all 10
    perturbation profiles.
  - The $T_1$-plus-white-noise floor is recomputed from a closed form
    ($\mathrm{Tr}\,R = 1 + 2W\sqrt{1-\gamma} + (1-\gamma)$, $F_{\rm avg}=(\mathrm{Tr}\,R+2)/6$) and the
    scenario config stored in the `bench_a` manifest. It does not use `ddopt.channels`.
  - Spectroscopy values are re-read from the stored held-out block. The RMSE ratio is re-divided
    from `rmse` and `shot_noise_rmse`.
  - The script does not regenerate the held-out predictions themselves.
- Paper values are the generated macros in `report/generated/numbers.tex` and `status.tex`, or the
  literal text where the source hard-codes the number.

## Checksum verification of pinned runs

`PYTHONPATH=src python -m ddopt.provenance verify results/<run>` printed `OK` for all 11 runs in
`report/runs.json` (exit 0):

| Key | Run id | Checksums | Manifest git SHA | Recorded dirty |
|---|---|---|---|---|
| g3 | g3_validation_20261026T231608Z_cbfe38b59354 | OK | 2170bfed8720 | no |
| bench_a | benchmark_scenario_a_20261026T232517Z_1bd28ade742a | OK | c7d1e5bf033c | no |
| bench_b | benchmark_scenario_b_20261026T234545Z_ad7b16de1c23 | OK | 1222d72f7b3d | no |
| spectroscopy | spectroscopy_scenario_a_20261026T235246Z_8b272601c344 | OK | 5a5a916739e8 | **yes** |
| bench_a_T4 | benchmark_scenario_a_T4us_20261026T235309Z_da0c18904bc7 | OK | 0efe3b028193 | **yes** |
| convergence | convergence_scenario_a_n8_20261026T235358Z_a8cb70bbe957 | OK | 198e798b91cb | no |
| model_based | model_based_scenario_a_20261026T235628Z_373dfea37a30 | OK | 9b6b91807051 | no |
| abl_colored | ablation_colored_20261026T235750Z_91695709bda1 | OK | 05193d1330aa | no |
| abl_noamp | ablation_noamp_20261027T000041Z_323cd5f2b975 | OK | 995776abadc4 | **yes** |
| abl_noT1 | ablation_noT1_20261027T000317Z_20454f2f5af9 | OK | 995776abadc4 | **yes** |
| tests | test_suite_20261027T000401Z_2fc21cc36501 | OK | 995776abadc4 | **yes** |

Checksums only show that the files are unchanged since they were recorded. They do not show
which code produced the files. 5 of the 11 pinned runs record a dirty working tree, including the
pre-registered spectroscopy (G4) run and the pre-registered $T=4\,\mu$s benchmark. The main paper
(Sec. VI-b) says "several *exploratory* runs were marked dirty". The reviewer should decide
whether that wording is accurate.

## Claim table

Match = the paper value equals the recomputed value at the precision printed in the paper.
"no" in rows 9 and 17 means the **text** is not supported as written. The macro numbers in
those rows do match.

| # | Paper location | Claim (paraphrased) | Macro | Value in paper | Value recomputed | Artifact | Match | Note | Reviewer | Approved |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Abstract; V-A | Largest MC vs filter-function \|z\| over the predetermined configurations | `GthreeMaxZ` | 0.95 | 0.9544 | results/g3_validation_20261026T231608Z_cbfe38b59354/payload.json | yes | | | |
| 2 | Abstract; V-A | Five predetermined configurations, all within criterion | (text) | 5, all pass | 5 rows, all `pass_primary`=True | results/g3_validation_20261026T231608Z_cbfe38b59354/payload.json | yes | | | |
| 3 | Abstract; V-A | Held-out RMSE = 1.15x shot-noise floor (Gaussian truth, full model) | `SpecGaussFullRmseRatio` | 1.15 | 0.010753 / 0.009320 = 1.1538 | results/spectroscopy_scenario_a_20261026T235246Z_8b272601c344/payload.json | yes | run recorded dirty | | |
| 4 | V-A | 95% predictive coverage on held-out points | `SpecGaussFullCov` | 0.934 | 0.9340 (99/106) | results/spectroscopy_scenario_a_20261026T235246Z_8b272601c344/payload.json | yes | run recorded dirty | | |
| 5 | V-A | 106 held-out synthetic decay measurements | hard-coded | 106 | 106 (figure.heldout, design.n_heldout, heldout.n) | results/spectroscopy_scenario_a_20261026T235246Z_8b272601c344/payload.json | yes | hard-coded number; no ledger row | | |
| 6 | IV-c | 14 log-spaced idle times in [0.1, 40] us, 1000 shots per point | hard-coded | 14; 0.1-40 us; 1000 | 14; 0.10-40.0 us; 1000 | results/spectroscopy_scenario_a_20261026T235246Z_8b272601c344/payload.json | yes | hard-coded; no ledger row | | |
| 7 | Abstract; V-B | $T_1$-plus-white-noise floor at T = 2 us | `FloorA` | 9.90e-3 | 9.9007e-3 (closed form) | results/benchmark_scenario_a_20261026T232517Z_1bd28ade742a/manifest.json (config) | yes | analytic, computed from config; not a stored artifact field | | |
| 8 | Abstract; V-B | Selected baseline (XY8) infidelity at n = 16, Scenario A | `BenchASixteenSelEps` | 1.00e-2 | 1.0032e-2, selected = XY8 in all 9 runs | results/benchmark_scenario_a_20261026T232517Z_1bd28ade742a/payload.json | yes | | | |
| 9 | Abstract; V-B | Scenario A: no practically meaningful CMA-ES gain; "Some sub-percent differences occur" | (text) | "sub-percent" | max ratio eps_sel/eps_CMA = 1.0112 (n = 4, timing+phase) | results/benchmark_scenario_a_20261026T232517Z_1bd28ade742a/payload.json | **no** | 1.011 is a 1.1% lower infidelity, so "sub-percent" is not strictly accurate. Suggest "differences of at most about 1%". | | |
| 10 | Abstract | Training-only rule selects XY4 (n = 4), XY8 (n = 8, 16) | `BenchA*Sel` | XY4 / XY8 / XY8 | xy4 / xy8 / xy8 | results/benchmark_scenario_a_20261026T232517Z_1bd28ade742a/payload.json | yes | | | |
| 11 | Abstract; V-C | Scenario B, n = 4, timing+phase: few-percent nominal gain over XY4+VZ | `BenchBFourBothRatioLo/Hi` | 1.024-1.050 | 1.0238-1.0497 | results/benchmark_scenario_b_20261026T234545Z_ad7b16de1c23/payload.json | yes | | | |
| 12 | Abstract; V-C | Scenario B, n = 4, phase-only nominal ratio | `BenchBFourPhaseRatioLo/Hi` | 1.008-1.048 | 1.0085-1.0485 | results/benchmark_scenario_b_20261026T234545Z_ad7b16de1c23/payload.json | yes | | | |
| 13 | Abstract | CMA-ES beat XY4 by a few percent "only at n = 4" | (text) | no few-percent gain at n = 8, 16 | max ratio at n = 8/16 = 1.0043 (n = 8, timing+phase) | results/benchmark_scenario_b_20261026T234545Z_ad7b16de1c23/payload.json | yes | True at the few-percent level. Some n = 8 runs (phase-only, timing+phase) still beat the baseline by 0.2-0.4%. | | |
| 14 | Abstract; V-C | n = 4 timing+phase gain reverses under timing shifts: worst case vs XY4+VZ | `RobBFourBothWorstMax`, `RobBFourDDWorst` | 2.11e-2 vs 1.13e-2 | 2.1114e-2 vs 1.1333e-2 | results/benchmark_scenario_b_20261026T234545Z_ad7b16de1c23/payload.json | yes | | | |
| 15 | V-C (detail in App. C-e) | n = 4 timing+phase wins over XY4+VZ in 3-8 of 10 profiles | `RobBFourBothWinsMin/Max` | 3-8 | [8, 6, 3] of 10 | results/benchmark_scenario_b_20261026T234545Z_ad7b16de1c23/payload.json | yes | The 10 profiles include 2 nominal duplicates (`amp_x1`, `shift_+0ns`). | | |
| 16 | Abstract; V-C | n = 4 phase-only keeps a marginal advantage in all perturbations | `RobBFourPhaseWinsMin/Max`, `RobBFourPhaseWorstMax` | 10/10; worst 1.12e-2 | [10, 10, 10]; worst 1.1156e-2 | results/benchmark_scenario_b_20261026T234545Z_ad7b16de1c23/payload.json | yes | | | |
| 17 | V-D | With white noise and $T_1$ removed, "CMA-ES still fails to beat XY8 in held-out evaluation" | (text); `AblColoredSixteenBothRatioLo/Hi` | timing+phase n = 16: 0.394-0.566 | 0.394-0.566. Runs with ratio > 1 vs XY8: colored n = 8 phase-only 1.002-1.004; no-$T_1$ n = 8 timing+phase up to 1.004; no-$T_1$ n = 8 phase-only up to 1.001 | results/ablation_colored_20261026T235750Z_91695709bda1/payload.json; results/ablation_noT1_20261027T000317Z_20454f2f5af9/payload.json | **no** | The macro values match. The blanket sentence is contradicted by marginal (at most 0.4%) wins over XY8. Suggest "did not beat XY8 by more than 0.4% in any configuration and lost substantially at n = 16". The no-$T_1$ run is recorded dirty. | | |
| 18 | Abstract | Optimizing on fitted models did not help: fitted-full, n = 4 ratio range | `MBFitFullFourRatioLo/Hi` | 0.982-1.011 | 0.9816-1.0107 | results/model_based_scenario_a_20261026T235628Z_373dfea37a30/payload.json | yes | The upper end is above 1. "Did not help" is a summary judgement for the reviewer. | | |
| 19 | Abstract | Training gains did not generalize (n = 8, timing+phase, 2000-eval budget) | `ConvTrainFinal`, `ConvValFinal`, `ConvBestBaselineVal` | train 9.37e-3; val 1.03e-2 vs XY8 1.03e-2 | train 9.366e-3 (XY8 train 1.078e-2); val 1.034e-2 vs XY8 val 1.027e-2 | results/convergence_scenario_a_n8_20261026T235358Z_a8cb70bbe957/payload.json | yes | Exploratory: one training run, two validation seeds | | |
| 20 | IV-f | Historical full-suite record: 249 passed, 0 failed, 0 errors, 1 skipped | `GenTestSummary` (status.tex) | 249/0/0/1 | passed 249, failures 0, errors 0, skipped 1 | results/test_suite_20261027T000401Z_2fc21cc36501/payload.json | yes | Run recorded dirty. Ledger row `GEN-TestsPassed`. Current main gives 257 passed, 1 skipped on 3.11 and 3.13, so the snapshot is historical. | | |
| 21 | IV-d/e | 2000-eval budget; 256 train / 1024 test trajectories; train seeds 101-103; optimizer seeds 1-3; test seeds 9001-9005; pycma 4.5.0 | hard-coded | as stated | 2000; 256; 1024; [101,102,103]; [1,2,3]; [9001..9005]; cma 4.5.0 | results/benchmark_scenario_a_20261026T232517Z_1bd28ade742a/{payload,manifest}.json | yes | hard-coded; no ledger row | | |
| 22 | IV-a | T = 2 us, w = 32 ns, 4 ns guard and grid, T1 = 100 us, S0 = 1e4 rad^2/s, tau_c = 0.5 us, Rabi error sd 0.02 | hard-coded | as stated | 2e-6; 3.2e-8; 4e-9; 4e-9; 1e-4; 1e4; 5e-7; 0.02 | results/benchmark_scenario_a_20261026T232517Z_1bd28ade742a/manifest.json (config) | yes | hard-coded; no ledger row | | |

## Summary

- 22 claims checked. 20 match. 2 are text-versus-artifact discrepancies (rows 9 and 17). In both,
  the printed numbers are correct but the surrounding sentence overstates them.
- Every generated macro the agent checked equals the artifact at the printed precision.
- Hard-coded numbers in the main text have no row in `report/evidence_map.csv`. These are rows 5,
  6, 21 and 22. `docs/REPORT_REQUIREMENTS.md` asks for a ledger entry for every numerical figure.
- Provenance caveat: 5 of the 11 pinned runs were recorded from a dirty tree. See the table above.
- Reproduction (the scratch script is not committed): load each run with
  `ddopt.provenance.load_run`, then apply the extraction rules in "Scope and method".

## Human sign-off

| Field | Value |
|---|---|
| Reviewer name | |
| Date | |
| Rows approved | |
| Rows rejected / needing text change | |
| Ledger (`report/evidence_map.csv`) updated by | |
