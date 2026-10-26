# Pre-registered experiment plan (lead-owned)

Committed **before** any optimization or benchmark run. Any later deviation must be logged in
the "Deviations" section with date and reason. All device parameters below are **synthetic
assumptions** chosen to be in a plausible transmon range; they are not measurements of any
device, IQCC or otherwise.

## Synthetic device (Scenario A, "truth" model)
* Idle window T = 2.0 µs (alternate window 4.0 µs for n = 16 feasibility/robustness checks).
* Square π pulses, width w = 32 ns, timing grid 4 ns (assumed controller tick), guard 4 ns.
* Dephasing noise, two-sided PSD (rad²/s), sum of:
  * 1/f: α = 1, ω_low = 2π·1 Hz, ω_high = 2π·10 MHz; amplitude A calibrated so the analytic
    Ramsey (FID) coherence W(t) = e^{-1} at t = 10 µs (T2* ≈ 10 µs).
  * Lorentzian (Gaussian OU) "TLS-like" component: τ_c = 0.5 µs, σ calibrated so that it alone
    gives an FID χ(2 µs) equal to 25 % of the 1/f χ(2 µs).
  * White floor: S0 such that χ_white(T) = S0·T equals 1/(100 µs) · T (pure dephasing rate
    contribution Γ_φ,white = S0/2 = 1/(200 µs)), ω_high = 2π·100 MHz.
* T1 = 100 µs (amplitude damping, composed per free segment).
* Control errors: per-trajectory relative amplitude error ε ~ N(0, 0.02²); no phase error;
  no static offset (static offsets are covered by the 1/f low-frequency content).
* Calibration of A, σ, S0 is done with `ddopt.filters` once and recorded in
  `configs/scenario_a.json` together with the command that produced it.

## Scenario B (spectator during neighbouring readout)
Scenario A plus a deterministic ac-Stark-like shift `smooth_rect`: amplitude 2π·0.2 MHz,
t_on = 0.6 µs, t_off = 1.6 µs, rise 20 ns. Arms: (1) no DD, (2) virtual-Z only,
(3) best canonical DD + virtual-Z, (4) optimized DD + virtual-Z. Virtual-Z angles computed from
the *nominal* profile. Robustness: evaluate with amplitude scaled by {0.8, 0.9, 1.0, 1.1, 1.2},
t_on/t_off shifted by {−100, −50, 0, +50, +100} ns, while controller assumes nominal.
This is a model of a deterministic frequency shift only, **not** a validation of measurement-induced
dephasing on hardware.

## Seeds (disjoint by construction)
* Training noise draws (frozen, CRN within a training run): seeds 101, 102, 103; n_traj = 256.
* Optimizer (CMA-ES) seeds: 1, 2, 3 (paired with training seeds).
* Test (held-out) seeds: 9001–9005; n_traj = 1024 each. Never used before final evaluation.
* Spectroscopy data seeds: 5001 (train schedules) and 5002 (held-out schedules); bootstrap seed 5003.

## Baselines and selection rule (pre-registered)
At each n, canonical baselines: CPMG-n (Y pulses), XY4-n (if n%4==0), XY8-n (if n%8==0), UDD-n,
plus free evolution (and Hahn for reference). Same T, w, guard, grid, noise model, test draws,
and frame-correction privileges as the optimized sequence. The **strongest baseline** is the
canonical sequence with the lowest infidelity on the **training** draws of the same run; it is
fixed before test evaluation. All baselines are still reported on the test set.

## Optimizer
CMA-ES (pycma 4.5.0), modes: timing-only, phase-only, timing+phase. Initial point = CPMG-n
timing (and CPMG phases for phase modes); σ0 = 0.3 in the unconstrained coordinates; budget
2000 evaluations per run (exploratory budget; increased only if logged as deviation).
Gap parameterization: n free coordinates, softmax with one coordinate fixed to 0 (no redundant
shift), minimum gap = guard, pulse starts snapped to the 4 ns grid after decoding.

## Metrics
* ε = 1 − F_avg (average gate infidelity vs corrected target), per test seed and pooled.
* Improvement factor ε_baseline/ε_opt and reduction 1 − ε_opt/ε_baseline, always with raw ε.
* Uncertainty: paired (same test draws) bootstrap over trajectories within seed, 95 % percentile
  CI; spread across the 3 independent training runs reported separately. No significance claims
  from "2 standard errors" after model selection.
* Train-vs-test gap to detect overfitting to frozen draws.

## Model-based pipeline / misspecification (G4, G6)
1. Generate synthetic Ramsey/Hahn/CPMG-{1,2,4} data from the truth (shots + SPAM).
2. Fit a reduced model (1/f + white) and the full model; evaluate held-out prediction on
   CPMG-{8,16} and unseen idle times.
3. Optimize on the fitted model, evaluate on the truth model (test seeds) — this measures gain
   that survives model mismatch. Also a deliberately misspecified truth (telegraph TLS instead of
   Gaussian Lorentzian).

## Gates checked
G1–G3 analytic/MC agreement on ≥3 predetermined configurations: FID, Hahn, CPMG-8 at T = 2 µs
with the Scenario A Gaussian noise (no T1, no control errors, w = 32 ns), using the generalized
filter function; criterion: |MC − FF| ≤ 1.96·SE_MC + quadrature error + discretization budget
(measured by halving noise_dt).

## Deviations
* 2026-10-26 (lead): one plumbing smoke run of `scripts/run_benchmark.py` (n=4, mode both,
  max_evals=40) evaluated on test seeds 9001–9005 before the main run. Output written to the
  untracked scratch directory and deleted; no parameter, budget or rule was changed afterwards.
  Disclosed here because it touched held-out seeds.
* 2026-10-26 (lead): the integration-test seed choices (11, 31) are outside all pre-registered
  seed sets.
