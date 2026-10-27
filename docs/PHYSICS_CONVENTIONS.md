# Physics conventions (binding for all modules)

Owner: integration lead. Detailed derivations: `docs/PHYSICS.md` (Agent A).

* **Units.** ħ = 1. Time in s. Angular frequency and detuning in rad/s. Angles in rad.
* **Hamiltonian (lab/rotating frame of the qubit drive).**
  `H(t) = ½[δ(t) + d(t) + δ_off] σ_z + ½ Ω(t)[cos φ(t) σ_x + sin φ(t) σ_y]`
  with δ(t) zero-mean stationary stochastic noise, d(t) a deterministic profile
  (`DetuningProfile`, e.g. ac-Stark shift during a neighbouring readout), δ_off an
  unknown static calibration offset (`ControlErrors.detuning_offset`), Ω the Rabi rate.
* **Noise statistics.** Gaussian stationary unless a `telegraph` component is present.
  Autocorrelation `C(τ) = ⟨δ(t+τ)δ(t)⟩`.
* **PSD.** Two-sided `S2(ω) = ∫ C(τ) e^{-iωτ} dτ`, ω ∈ (−∞,∞), so
  `C(0) = (1/2π) ∫ S2(ω) dω`. A one-sided PSD in ordinary frequency f (Hz), normalised so `⟨δ²⟩ = ∫_0^∞ S1(f) df`, is
  `S1(f) = 2·S2(2πf)` (corrected after Agent A review; an earlier draft had a spurious 2π) — never mix; all code uses S2 in rad²/s.
* **Fourier / filter.** `Y(ω) = ∫_0^T y(t) e^{iωt} dt`, `F(ω) = |Y(ω)|²` (s²).
  Accumulated phase `ϕ = ∫ δ(t) y(t) dt`, `χ = Var ϕ = (1/2π)∫ S2(ω) F(ω) dω`.
* **Switching function.** y(t) = toggling-frame z-component: ±1 between ideal π pulses,
  starting at +1; finite pulses use the generalized (vector) filter function.
* **Coherence / fidelity.** Gaussian: `W = ⟨e^{iϕ}⟩ = e^{−χ/2}`. Pure-dephasing average gate
  infidelity `r = (1 − W)/3` (from F_avg = (2F_pro + 1)/3, F_pro = (1+W)/2).
* **T1.** Amplitude damping with `γ = 1 − e^{−t/T1}` per free segment. PTM
  diag(1, √(1−γ), √(1−γ), 1−γ) with translation (γ in the Z-row of the identity column).
  Average infidelity of AD alone: `r_AD = (2 + γ − 2√(1−γ))/6` (→ γ/3 for small γ, ½ at γ=1).
  **Note:** the master prompt states `[3 − 2√(1−γ) − γ]/6`; that expression gives 1/6 at γ=0
  and fails the T=0 limit, so it is treated as a typo. See `docs/PHYSICS.md` for derivation.
  Channels are **composed** (PTM products), never added. AD is phase-covariant, so it commutes
  with z-rotations; T1 during finite pulses is an approximation documented in the simulator.
* **Target and frame correction.** Fidelity is computed against `U_target = R_z(θ_vz) U_0`
  where U_0 is the ideal net control unitary of the sequence (no noise, no errors) and
  θ_vz = 0 unless `frame_correction == "ideal_control_plus_virtual_z"`, in which case θ_vz is
  the virtual-Z angle that best cancels the *known* deterministic detuning d(t) (computed
  noise-free, error-free). Optimizers may not grade a non-identity gate against identity.
* **Average gate fidelity** of a channel with PTM R: `F_avg = (Tr R + 2)/6` for a qubit,
  evaluated on `R_target^T R` (i.e. the channel `U_target† · Λ`).
