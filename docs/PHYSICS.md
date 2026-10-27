# Physics derivations and numerical validation (Agent A)

Owner: Agent A (physics/analytics). Code: `src/ddopt/noise.py`, `src/ddopt/filters.py`,
`src/ddopt/channels.py`. Tests: `tests/test_noise.py`, `tests/test_filters.py`,
`tests/test_channels.py`. Binding conventions: `docs/PHYSICS_CONVENTIONS.md` (lead-owned); this
document derives them and records what was **actually measured**. Everything here is synthetic
analysis: no hardware data, no fitted device parameters.

---

## 1. Hamiltonian, units, frames

ħ = 1, time in s, angular frequency and detuning in rad/s, angles in rad.

    H(t) = ½ [δ(t) + d(t) + δ_off] σ_z + ½ Ω(t) [cos φ(t) σ_x + sin φ(t) σ_y]

δ(t) is the zero-mean stationary stochastic dephasing noise (this module), d(t) a deterministic
known-in-form profile and δ_off a static unknown offset (both handled by the simulator / frame
correction, not here). The noise acts **during pulses as well as free evolution**.
|0⟩ is the ground state, σ_z|0⟩ = +|0⟩.

**Toggling frame.** Let U_c(t) be the ideal control propagator (noise-free). In the interaction
picture with respect to the control, the noise Hamiltonian becomes

    H̃(t) = ½ δ(t) U_c†(t) σ_z U_c(t) = ½ δ(t) Σ_a y_a(t) σ_a ,   a ∈ {x, y, z}

with the *toggling vector* y(t) = R_c(t)ᵀ ẑ, where R_c ∈ SO(3) is the adjoint representation of
U_c (U σ_v U† = σ_{R v}). |y(t)| = 1 inside [0, T]; we set y = 0 outside the window.

**Switching function during pulses.** Pulse k is a square pulse of width w_k about the equatorial
axis n = (cos φ, sin φ, 0), Rabi rate Ω_k = θ_k / w_k. At time t inside the pulse the accumulated
angle is θ(t) = Ω_k (t − s_k) and U_c(t) = R_n(θ(t)) U_{k−1}, R_n(θ) = exp(−iθ n·σ/2). Then
R_c = Rot(n, θ) R_{k−1} and

    y(t) = R_{k−1}ᵀ Rot(n, −θ) ẑ = R_{k−1}ᵀ [ (−sin φ, cos φ, 0) sin θ + ẑ cos θ ]

(Rodrigues: Rot(n, −θ) ẑ = ẑ cos θ − (n × ẑ) sin θ, n × ẑ = (sin φ, −cos φ, 0)). Between pulses y is
constant; after a sequence of equatorial π pulses R_{k−1}ᵀ ẑ = ±ẑ, so y = (0, 0, ±1) and, during
the next pulse, y_z = ±cos θ(t) while the transverse components are ±sin θ(t) × (equatorial unit
vector). The window starts with y = +ẑ. `filters.toggling_vector` implements exactly this for
arbitrary phases and angles (angles ≠ π are allowed; the sequence is then not a pure-dephasing
filter).

## 2. Noise statistics and the Gaussian assumption

C(τ) = ⟨δ(t+τ) δ(t)⟩ (rad²/s²). For the Gaussian kinds (one_over_f, lorentzian, white) δ is
assumed **Gaussian and stationary**; telegraph noise is stationary but **not Gaussian** (§9).

**PSD convention (two-sided, angular frequency).**

    S2(ω) = ∫ C(τ) e^{−iωτ} dτ   [rad²/s],    C(τ) = (1/2π) ∫ S2(ω) e^{iωτ} dω = (1/π) ∫_0^∞ S2 cos ωτ dω

so ⟨δ²⟩ = C(0) = (1/2π) ∫ S2 dω. S2 is real, even and ≥ 0 (Wiener–Khinchin, C positive definite).

*One-sided conversion (for comparing with literature).* A one-sided PSD in ordinary frequency,
defined by ⟨δ²⟩ = ∫_0^∞ S1(f) df, is S1(f) = 2 S2(2πf) [rad²/s² per Hz = rad²/s]. (Derivation:
(1/π)∫_0^∞ S2(ω)dω with ω = 2πf, dω = 2π df gives ∫_0^∞ 2 S2(2πf) df.) **Contract note:**
`docs/PHYSICS_CONVENTIONS.md` currently writes "S1(f) = 2·2π·S2(2πf)-type conversions"; the factor
2π is wrong for this definition of S1 — reported to the lead (§12).

**Kinds** (all with hard cutoffs: S2 = 0 unless ω_low ≤ |ω| ≤ ω_high):

| kind | S2(ω) | ⟨δ²⟩ = (1/π)∫_{a}^{b} S2 dω, a = ω_low, b = ω_high | C(τ) |
|---|---|---|---|
| one_over_f | A/|ω|^α | (A/π)(b^{1−α} − a^{1−α})/(1−α); (A/π) ln(b/a) at α=1 | QUADPACK QAWO |
| lorentzian (OU) | 2σ²τ_c/(1+ω²τ_c²) | (2σ²/π)[atan(bτ_c) − atan(aτ_c)] → σ² | σ² e^{−\|τ\|/τ_c} (no cutoffs) |
| white | S0 (ω_low = 0) | S0 b/π | (S0/π) sin(bτ)/τ |
| telegraph | same as Lorentzian, σ = b_tel, τ_c = 1/(2γ) | b_tel² | b_tel² e^{−2γ\|τ\|} |

The α → 1 limit is evaluated with `expm1` to avoid cancellation. For Lorentzians with cutoffs
`autocovariance` uses C = σ²e^{−τ/τ_c} − (1/π)∫_0^{a} − (1/π)∫_b^∞, the last term integrated twice
by parts before QAWF (direct QAWF was found to fail with IntegrationWarnings and errors up to
3.7e-7 σ²; ad-hoc check, not in the test suite).

## 3. Accumulated phase, filter function, χ, W, r

For instantaneous π pulses H̃ = ½δ(t) y_z(t) σ_z commutes with itself at all times, so the toggling-
frame propagator is exactly exp(−i φ σ_z / 2) with

    φ = ∫_0^T δ(t) y(t) dt .

Its variance, using C(t − t') = (1/2π)∫ S2 e^{iω(t−t')} dω,

    χ ≡ Var φ = ∫∫ y(t) y(t') C(t − t') dt dt' = (1/2π) ∫ S2(ω) |Y(ω)|² dω ,   Y(ω) = ∫_0^T y(t) e^{iωt} dt .

F(ω) = |Y(ω)|² in s². Closed forms: FID F = 4 sin²(ωT/2)/ω² (F(0) = T²); Hahn F = 16 sin⁴(ωT/4)/ω².
For piecewise-constant y, Y = Σ_segments y_seg e^{iωs} ∫_0^{e−s} e^{iωu} du, evaluated with a sinc
form that is exact and stable at ω → 0.

**Gaussian average.** For zero-mean Gaussian φ, W ≡ ⟨e^{iφ}⟩ = e^{−χ/2} (real). The off-diagonal
element of ρ is multiplied by W, i.e. the (noise-averaged) channel in the toggling frame is pure
dephasing with PTM diag(1, W, W, 1).

**Infidelity.** Entanglement (process) fidelity F_pro = Tr R/4 = (1 + W)/2; average gate fidelity
for a qubit F_avg = (2F_pro + 1)/3 = (2 + W)/3, hence **r = (1 − W)/3 = −expm1(−χ/2)/3**
(→ χ/6 for small χ; → 1/3 for W → 0).

**Quasi-static limit.** If C(τ) ≈ σ² over the window, χ = σ² (∫ y dt)²: FID χ = σ²T² and every
sequence with ∫ y dt = 0 (Hahn, CPMG, UDD) cancels the static part exactly. For the OU process
(exact, derived from the double integral):

    χ_FID  = 2σ²τ_c² (x − 1 + e^{−x}),                  x = T/τ_c   → σ²T²(1 − x/3) for x ≪ 1
    χ_Hahn = 2σ²τ_c² (x − 3 + 4e^{−x/2} − e^{−x})       → σ²T³/(6τ_c) for x ≪ 1  (∝ τ_c^{−1})

(the Hahn series starts at x³/12 because the x⁰, x¹ and x² coefficients cancel).

**White limit.** For S2 = S0 at all ω, (1/2π)∫S0|Y|² = S0 ∫ y² dt = S0 T for any ±1 switching
function (Parseval) — independent of instantaneous pulses. With a finite cutoff ω_h the large-ω
asymptotics F → D/ω² (§5) give χ = S0 (T − D/(π ω_h)) + O(ω_h^{−2}), D = Σ_m |J_m|² = 2 + 4n.

**Passbands.** For CPMG-n the switching function is a square wave of period 2T/n, so F peaks near
ω = πn/T (fundamental). The finite-n peak is offset; measured offsets are in §11.

## 4. Generalized (vector) filter function for finite pulses

With finite pulses H̃(t) = ½ δ(t) y(t)·σ no longer commutes at different times. First-order Magnus:
Ũ ≈ exp(−i Φ·σ / 2), Φ_a = ∫ δ y_a dt — a rotation by angle |Φ|. The entanglement fidelity of a
rotation by angle ϑ is cos²(ϑ/2) ≈ 1 − ϑ²/4, so

    F_pro ≈ 1 − ⟨|Φ|²⟩/4 = 1 − χ/4,   χ = Σ_a Var Φ_a = (1/2π) ∫ S2(ω) Σ_a |Y_a(ω)|² dω .

`filter_function` returns F(ω) = Σ_a |Y_a(ω)|² (which reduces to |Y_z|² for instantaneous π pulses,
where y_x = y_y = 0). The contract formula r = (1 − e^{−χ/2})/3 = χ/6 + O(χ²) then agrees with the
first-order Magnus result to O(χ); for finite pulses W = e^{−χ/2} is a **leading-order
approximation** (second-order Magnus terms, O(δ² T w)-type commutators, are neglected). The
finite-pulse simulator (Agent B) is the reference for that regime; G3 compares the two.

Closed form during a pulse: with y = u_c cos θ(t) + u_s sin θ(t), θ = Ω(t − s), and
E(ν, w) = ∫_0^w e^{iνu} du = w e^{iνw/2} sinc(νw/2),

    ∫_s^{s+w} y e^{iωt} dt = e^{iωs} [ u_c (E(ω+Ω,w) + E(ω−Ω,w))/2 + u_s (E(ω+Ω,w) − E(ω−Ω,w))/(2i) ] .

No numerical integration is used for F. Finite-width → instantaneous: at fixed centres the χ
difference was measured to converge at order ≈ 2 in w (centred symmetric pulses cancel the O(w)
term), see §11.

## 5. Numerical evaluation of χ (`filters.dephasing_variance`)

χ = (1/π) ∫_0^∞ S2 F dω, evaluated per PSD component over its own [ω_low, ω_high]:

1. a linear panel [0, ω_floor] (ω_floor = 10⁻⁶ min(2π/T, 1/τ_c)) if ω_low = 0;
2. log-spaced panels (4/decade, variable u = ln ω) up to 2π/T — handles 1/ω^α integrands and
   Lorentzian peaks at 1/τ_c ≪ 1/T;
3. linear panels of width π/T (resolving the e^{iωT} oscillation of F) up to ω_tail;
4. every panel: 15-point Gauss–Kronrod with embedded 7-point Gauss (QUADPACK qk15 constants);
   panels with |K15 − G7| above their share of rtol·χ/2 are bisected (up to 40 rounds);
5. tail ω > ω_tail = max(tail_factor·2π/d_min, 5 Ω_max, 8π/T)·4^k. Integration by parts gives
   Y = (i/ω) Σ_m J_m e^{iωτ_m} + R, J_m the jumps of y at times τ_m (window edges, instantaneous
   pulses), |R| ≤ B2/ω² with B2 = Σ_k |Ω_k|(2 + |θ_k|). The tail uses the diagonal part
   (1/π) D ∫ S2/ω², D = Σ|J_m|², with the **rigorous bound** (g = S2/ω² is nonincreasing, second
   mean-value theorem: |∫_a^b g cos(ωΔ)| ≤ 2g(a)/Δ)

       err_tail ≤ (1/π) [ Σ_{m≠l} |J_m·J_l| 2 g(ω_tail)/|τ_m − τ_l| + ∫ S2 (2 B1 B2/ω³ + B2²/ω⁴) ] ,  B1 = Σ|J_m| .

   k is increased until err_tail ≤ rtol·χ/2 (capped by `max_panels`). Tail moments ∫S2 ω^{−p}
   are integrated with v = ω_tail/ω on a finite interval (a direct improper QUADPACK integral
   silently returned ≈0 for the OU tail during development).

Returned error = Σ|K15 − G7| (a conservative heuristic, not a bound) + err_tail (a bound).
Measured: the reported estimate exceeded the true error in every case with an exact reference
(§11). Telegraph components use their Lorentzian-equivalent PSD (Gaussian approximation).

## 6. Sampling δ(t) (`noise.sample_detuning`)

Output: (n_traj, N) samples on a uniform grid, time origin irrelevant, all randomness from the
passed `numpy.random.Generator`.

* **OU (lorentzian, no cutoffs):** exact recursion x_{k+1} = a x_k + σ√(1 − a²) ξ_k, a = e^{−dt/τ_c},
  x_0 ~ N(0, σ²) (stationary start). Grid covariance is exactly σ² e^{−k dt/τ_c} (aliasing of
  content above π/dt included, as for point samples of the continuous process).
* **Telegraph (no cutoffs):** s_0 = ±1 with probability ½ (stationary), each step flips with
  probability P(odd Poisson(γ dt)) = (1 − e^{−2γ dt})/2: exact grid samples of the continuous-time
  chain. Cutoffs cannot be imposed on a jump process; the sampler raises `ValueError`.
* **All other Gaussian components (and Lorentzians with cutoffs):** hybrid spectral synthesis,
  **band-limited to |ω| < π/dt** (content above Nyquist is dropped, reported, and a
  `RuntimeWarning` is raised above 1 %). PSDs of all such components are summed. With
  M = 2^⌈log₂(8N)⌉ and Δω = 2π/(M dt), a C^∞ partition of unity P(ω) (1 below ω_a = 16Δω, 0
  above 2ω_a) splits S2:
  * high part S2(1 − P): FFT synthesis with point weights S2(1−P)(jΔω)Δω/π and independent
    Gaussian quadratures. By Poisson summation its grid covariance is **exactly the
    M dt-periodisation of the high-part covariance**, which is short-ranged because the partition
    is smooth — the window uses only N ≤ M/8 of the M points;
  * low part S2·P: explicit sinusoids a_q cos ω_q t + b_q sin ω_q t, a_q, b_q ~ N(0, v_q), at
    composite 8-point Gauss–Legendre nodes (3 log panels/decade from ω_low — or 10⁻⁶/T plus a
    single zero-frequency mode if ω_low = 0 — up to 1/T, then linear panels of width π/(2T));
    v_q = weight·S2·P/π. Its covariance is a converged quadrature of the exact low-part C(τ)
    for |τ| ≤ T. This is how **content below 2π/T down to ω_low** is reproduced (e.g. ≈ 37 % of
    the variance of the test 1/f spectrum with ω_low = 2π·1 Hz, T = 2 µs).

  The exact generator covariance is available without Monte-Carlo noise from
  `noise.synthesized_autocovariance`, which is how the bias is quantified (§11). The dominant
  residual is the O(Δω/ω_edge) Riemann error of a hard spectral edge (oscillating as
  cos(ω_edge τ), so it largely filters out of χ); it decreases with `oversample`.

Cost (measured): 512 × 10⁴ points for 1/f + OU + white + telegraph in 2.3–3.3 s on this machine
(4 cores), well inside the brief.

## 7. Telegraph vs Gaussian noise

Symmetric RTN δ = ±b, switching rate γ each way: C = b² e^{−2γ|τ|}, the same S2 as a Lorentzian with
σ = b, τ_c = 1/(2γ). Second-order statistics — and hence χ — coincide, but φ is not Gaussian, so
W ≠ e^{−χ/2} in general. For instantaneous π pulses (y_z = ±1 piecewise) the exact coherence is

    W = ½ (1, 1) Π_k exp[(Q + i b y_k diag(1, −1)) Δ_k] (1, 1)ᵀ,   Q = γ [[−1, 1], [1, −1]],

(`filters.telegraph_coherence_exact`; FID reproduces the textbook
W = e^{−γT}[cosh μT + (γ/μ) sinh μT], μ = √(γ² − b²)). The Gaussian formula is accurate only for
b τ_c ≪ 1 (motional narrowing); measured counter-examples are in §11. Telegraph components are
the intended *misspecification* truth for Agent C.

## 8. Channels, amplitude damping and T1

PTM in the (I, X, Y, Z) basis: R_ij = ½ Tr[P_i Λ(P_j)]. Composition right-to-left,
`compose_ptm(B, A) = R_B R_A`. CPTP check: first row = (1, 0, 0, 0) (trace preservation) and
Choi matrix J = Σ_ab |a⟩⟨b| ⊗ Λ(|a⟩⟨b|) ⪰ 0. Average gate fidelity versus identity:
F_avg = (2 F_pro + 1)/3, F_pro = Tr R/4, i.e. **F_avg = (Tr R + 2)/6**; against a unitary target V,
use R_Vᵀ R (PTMs of unitaries are orthogonal). This holds for non-unital channels too (the
non-unital column does not enter the trace).

**Amplitude damping.** K0 = diag(1, √(1−γ)), K1 = √γ |0⟩⟨1|, γ = 1 − e^{−t/T1}. Then
Λ(I) = I + γZ, Λ(X) = √(1−γ) X, Λ(Y) = √(1−γ) Y, Λ(Z) = (1−γ) Z, so

    R_AD = [[1, 0, 0, 0], [0, s, 0, 0], [0, 0, s, 0], [γ, 0, 0, 1−γ]],   s = √(1−γ).

Tr R_AD = 2 + 2s − γ, hence F_avg = (4 + 2s − γ)/6 and

    r_AD = 1 − F_avg = (2 + γ − 2√(1−γ)) / 6 = [γ + 2γ/(1 + √(1−γ))] / 6

(second form free of cancellation). Limits: r_AD(0) = 0, r_AD = γ/3 + γ²/24 + O(γ³), r_AD(1) = ½.

**Verdict on the master-prompt formula.** The master prompt states r_AD = [3 − 2√(1−γ) − γ]/6.
At γ = 0 it gives 1/6 for the identity channel, which is impossible; it is **wrong**. The lead's
(2 + γ − 2√(1−γ))/6 is **correct**. Independent numerical checks (tests): average over the six
cardinal states (a 2-design, exact) agrees to < 1e-14 for γ ∈ {0, 1e-9, 1e-4, 0.03, 0.3, 0.77, 1};
a Haar Monte-Carlo average over 2·10⁵ random pure states at γ = 0.4 agrees within 4 SE and
rejects the master-prompt value by > 50 SE.

**Composition, not addition.** For dephasing W followed by AD,
r = (2 + γ − 2sW)/6, while r_deph + r_AD exceeds it by exactly (1 − W)(1 − s)/3 (tested).
AD over consecutive segments composes to AD with γ_tot = 1 − e^{−(t1+t2)/T1} (tested); AD is
phase-covariant and commutes with z rotations, so per-free-segment application commutes with the
dephasing frame. T1 during finite pulses (AD does not commute with x/y rotations) is an
approximation that belongs to the simulator; it is not modelled here.

## 9. Limiting cases covered by tests

T → 0 (χ ≈ σ²T² → 0, γ(T=0) = 0); zero noise (χ = 0, W = 1, r = 0); high noise (W → 0, r → 1/3;
AD γ = 1 gives ½); tiny γ (γ/3 + γ²/24 to 1e-6 relative, γ down to 1e-12); CPTP for AD, dephasing,
unitaries and their compositions; non-CP transpose map and non-TP maps rejected.

## 10. Reproducing the tolerance table

    PYTHONPATH=$PWD/src /home/user/quantum-dd-optimizer/.venv/bin/python -m pytest -q -s \
        -W error::scipy.integrate.IntegrationWarning tests/test_noise.py tests/test_filters.py tests/test_channels.py

prints every `TOL` line used below. Environment: Linux x86_64, Python 3.13.17, numpy 2.5.4,
scipy 1.18.1, 4 CPUs. Recorded 2026-10-26: **71 passed** (Agent A tests) plus 4 lead contract tests.
Seeds are fixed in the tests; the statistical checks use 4σ acceptance.

## 11. Measured tolerances (from the command above; copied from its output)

T = 2 µs unless noted, rtol = 1e-6 (default).

| check | reference | measured |
|---|---|---|
| F(ω), FID/Hahn instantaneous | closed forms | rel ≤ 1e-12 / 1e-10 (asserted) |
| Y_a(ω), finite pulses (3 sequences, arbitrary phases/angles) | Simpson on 4·10⁵ points | < 1e-8 of max\|Y\| (asserted) |
| χ OU, FID and Hahn, τ_c ∈ {20 ns, 0.5 µs, 5 µs, 1 ms} | exact formulas §3 | rel err 3e-15 … 1.8e-11; estimate 5e-13 … 5e-9 (always ≥ true error) |
| χ white (ω_h = 2π·1 THz), FID/Hahn/CPMG-8/UDD-6 | S0(T − D/(πω_h)) | ≤ 1.5e-9 of S0T |
| χ vs time-domain 2-D adaptive quadrature (dblquad), OU, Hahn/CPMG-2/UDD-3 | ∫∫ y y C | rel diff 3.4e-12 … 2.8e-10 |
| χ, finite pulses (CPMG-4, w = 120 ns, XY phases) vs ∫∫ y·y C on 1e-11 s grid | time domain | rel diff 3.8e-10 |
| χ 1/f, α ∈ {0.7, 1, 1.5}, FID/Hahn | scipy.quad on 119 log panels | rel diff ≤ 7.4e-16 |
| rtol convergence (1/f + OU + white; FID, CPMG-8 w=32 ns, UDD-8) | rtol = 1e-9 run | rtol 1e-3: ≤ 2.1e-8; rtol 1e-6: ≤ 2.1e-11 |
| finite → instantaneous, CPMG-8, w = 64, 32, 16, 8, 4 ns | w = 0 | 5.5e-2, 1.5e-2, 3.8e-3, 9.6e-4, 2.4e-4; order 1.96 |
| CPMG passband peak position | πn/T | +4.1e-2 (n=4), +1.1e-2 (n=8), +2.7e-3 (n=16) |
| Quasi-static OU FID, τ_c = 0.1–10 ms | σ²T²(1 − T/3τ_c) | rel 1e-4 (asserted); Hahn ∝ 1/τ_c: ratio per decade 0.1 ± 1 % |
| sampler covariance bias, lags 0…T (exact generator covariance) | analytic C(τ) | 1/f: 1.3e-4·C(0); OU: 1e-16; cut Lorentzian: 1.5e-6; white: 6.2e-5 |
| exact Var of trapezoid phase (dt = 1 ns) vs χ_FF, FID / Hahn | filter function | 1/f 3.7e-8 / 1.6e-6; OU 2.2e-7 / 2.1e-7; cut Lor. 2.2e-7 / 1.1e-6; white 3.3e-5 / 1.0e-4 |
| same, dt-halving (ad-hoc check, FID) | — | O(dt²): OU 9.0e-7 → 2.2e-7 → 5.6e-8 for dt = 2, 1, 0.5 ns; white 1.3e-4 → 3.3e-5 → 8.3e-6 |
| MC phase variance, 4000 traj, FID/Hahn, 4 spectra | χ_FF | all \|z\| ≤ 0.99 (rel SE 2.2e-2) |
| spectral synthesis of OU vs exact OU | exact | 4.1e-4 = dropped above-Nyquist fraction |
| telegraph MC (b = 2e6 rad/s, γ = 0.5e6 /s), 4000 traj | transfer matrix | FID: −0.329 ± 0.010 vs exact −0.337 (Gaussian formula: +0.011, rejected); Hahn: 0.342 ± 0.012 vs 0.347 (Gaussian 0.261) |
| strong slow RTN (b = 3e6, γ = 1e4), FID | — | exact W = 0.940, Gaussian W ≈ 0.000 |
| AD infidelity | cardinal-state / PTM / Haar MC | < 1e-14 / < 1e-14 / within 4 SE |

Ad-hoc timings (not part of the test suite; 5 repeats, 1/f + OU + white, T = 2 µs):
`dephasing_variance` FID 4 ms, CPMG-8 instantaneous 35 ms, CPMG-8 w = 32 ns 114 ms,
CPMG-16 w = 32 ns 190 ms per call.

**G3 budget implication.** With dt = 1 ns, the sampler + trapezoid bias in Var φ is ≤ 1e-4 of χ
for these spectra (white noise near 100 MHz is the worst case), far below the ≈ 2·10⁻² relative
MC standard error of 4000 trajectories; the quadrature error of χ is < 1e-8 relative.
These are statements about this module only — the finite-pulse simulator's own discretisation
must be budgeted separately (Agent B / lead).

## 12. Known limitations and contract notes

1. W = e^{−χ/2} with the generalized filter function is leading order for finite pulses (§4).
2. Telegraph noise: χ uses the Lorentzian-equivalent PSD; exact W only for instantaneous π pulses.
   Telegraph components with cutoffs are accepted by `psd` (contract: cutoffs on every kind) but
   rejected by `sample_detuning`.
3. Spectral sampling is band-limited to π/dt whereas OU/telegraph sampling is exact at grid points
   (aliasing included): the two methods agree to the above-Nyquist fraction (≈ 2dt/(π²τ_c)).
4. `PHYSICS_CONVENTIONS.md` one-sided PSD remark: should read S1(f) = 2 S2(2πf) for
   ⟨δ²⟩ = ∫_0^∞ S1 df (§2).
5. `switching_function` returns y_z only; the simulator-comparable object for finite pulses is
   `toggling_vector` (3 components), used by `filter_function`.
6. Not modelled here: T1 during pulses, non-stationary noise, non-Gaussian 1/f (ensembles of
   fluctuators), leakage. No hardware or fitted-device numbers appear anywhere in this module.
