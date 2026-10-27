# Interface contract (v0.1, integration-lead owned)

Data classes live in `src/ddopt/contracts.py` (lead-owned; do not edit without lead review).
Function signatures below are the **public API** each owner must provide. Owners may add
private helpers and extra keyword-only arguments with defaults; they may not change the
positional signatures or return types without lead review.

Units: seconds, rad/s, radians, two-sided PSD in rad²/s (see `docs/PHYSICS_CONVENTIONS.md`).

## `ddopt.noise` (Agent A)
```python
def psd(component_or_model: PSDComponent | NoiseModel, omega: np.ndarray) -> np.ndarray
    # two-sided S2(omega), even in omega, >= 0, honours cutoffs. NoiseModel -> sum of components.
def noise_variance(component_or_model) -> float
    # <delta^2> = (1/2pi) int S2 domega  (rad^2/s^2), analytic where possible
def sample_detuning(model: NoiseModel, t: np.ndarray, n_traj: int, rng: np.random.Generator) -> np.ndarray
    # (n_traj, len(t)) stochastic delta(t) samples on a uniform grid t (rad/s); excludes the
    # deterministic profile. Gaussian components by spectral synthesis honouring the PSD
    # (including content below 2pi/(t[-1]-t[0]) down to omega_low); telegraph by exact
    # Markov jump simulation. Stationary, zero mean.
def make_one_over_f(A, alpha, omega_low, omega_high) -> PSDComponent  # convenience ctors
def make_lorentzian(sigma, tau_c, omega_high=inf) -> PSDComponent
def make_white(S0, omega_high) -> PSDComponent
def make_telegraph(b, gamma) -> PSDComponent
```

## `ddopt.filters` (Agent A)
```python
def switching_function(seq: PulseSequence, t: np.ndarray) -> np.ndarray
    # y(t) = z-component of toggling-frame sigma_z; +-1 between ideal pi pulses,
    # cos(theta(t)) during finite pulses (theta = accumulated rotation angle).
def filter_function(seq: PulseSequence, omega: np.ndarray) -> np.ndarray
    # |Y(omega)|^2 with Y(omega) = int_0^T y(t) e^{i omega t} dt  (units s^2).
    # Finite pulses: sum over the toggling-frame x,y,z components (generalized FF);
    # instantaneous: z only (analytic closed form).
def dephasing_variance(noise: NoiseModel | PSDComponent, seq: PulseSequence, *, rtol=1e-6) -> tuple[float, float]
    # (chi, quad_err_estimate), chi = Var(phi) = (1/2pi) int_{-inf}^{inf} S2 |Y|^2 domega
def coherence(noise, seq) -> float           # W = exp(-chi/2)  (Gaussian assumption)
def dephasing_infidelity(noise, seq) -> float  # r = (1 - W)/3
```

## `ddopt.channels` (Agent A)
```python
def amplitude_damping_kraus(gamma: float) -> list[np.ndarray]
def amplitude_damping_ptm(gamma: float) -> np.ndarray       # 4x4 Pauli transfer matrix (I,X,Y,Z)
def dephasing_ptm(W: float) -> np.ndarray
def unitary_ptm(U: np.ndarray) -> np.ndarray
def compose_ptm(*ptms) -> np.ndarray                       # apply right-to-left: compose(B, A) = B∘A
def avg_gate_fidelity_ptm(R: np.ndarray) -> float           # F = (Tr R / 4 * 2 + 1)/3  for qubit
def amplitude_damping_infidelity(gamma: float) -> float     # analytic, derived & tested
def is_cptp_ptm(R: np.ndarray, tol=1e-10) -> bool
def gamma_from_T1(T: float, T1: float) -> float             # 1 - exp(-T/T1)
```

## `ddopt.sequences` (Agent B)
```python
def free(T, *, guard=0.0, dt_grid=None) -> PulseSequence
def hahn(T, width, *, guard=0.0, dt_grid=None, phase=0.0) -> PulseSequence
def cpmg(n, T, width, **kw) -> PulseSequence   # centers T(k-1/2)/n, phase pi/2 (Y) by convention, documented
def xy4(n, T, width, **kw) -> PulseSequence    # n % 4 == 0, phases X Y X Y, CPMG timing
def xy8(n, T, width, **kw) -> PulseSequence    # n % 8 == 0, XYXYYXYX
def udd(n, T, width, **kw) -> PulseSequence    # centers T sin^2(pi k / (2n+2)), phase pi/2
def from_gaps(T, width, gaps, phases, **kw) -> PulseSequence   # explicit gap parameterisation
def snap_to_grid(seq, dt_grid) -> PulseSequence  # round pulse starts to grid, re-validate (may raise)
def feasible(n, T, width, guard=0.0) -> bool
def ideal_unitary(seq: PulseSequence) -> np.ndarray   # 2x2 net control unitary, no noise/errors
```
All constructors call `validate()` and raise `ValueError` for infeasible timing
(e.g. 16 x 40 ns pulses in a 500 ns window).

## `ddopt.simulator` (Agent B)
```python
def propagate(seq, delta_traj: np.ndarray, t_grid: np.ndarray, *, pulse_steps=8,
              amp_eps: np.ndarray | None = None, phase_err: np.ndarray | None = None) -> np.ndarray
    # (n_traj, 2, 2) unitaries; delta_traj (n_traj, len(t_grid)) total detuning rad/s
    # (stochastic + deterministic). Free segments use analytic z-rotation with
    # phase = integral of delta (trapezoid on grid, linear interpolation at segment edges);
    # pulses use piecewise-constant sub-steps.
def simulate(seq: PulseSequence, noise: NoiseModel, config: SimulationConfig,
             *, delta_traj: np.ndarray | None = None) -> SimulationResult
    # Noise-averaged channel average gate fidelity against the corrected target.
    # If delta_traj is given (frozen draws, CRN) it is used instead of sampling.
    # v0.2 (merged Agent B): delta_traj is the STOCHASTIC part only; the deterministic profile
    # and ControlErrors.detuning_offset are added inside. Extra keyword-only args:
    # t_grid, amp_eps, phase_err, return_per_traj. Draw order from default_rng(seed):
    # noise (if any stochastic component) -> amp_eps normals -> phase_err normals.
    # To reproduce a run exactly pass all four outputs of frozen_draws.
def time_grid(T, dt) -> np.ndarray   # ceil-based uniform grid covering [0, T]
def frozen_draws(noise, T, config) -> dict   # {"t": grid, "delta": (n_traj, len), "amp_eps", "phase_err"}
def virtual_z_angle(seq, noise, config) -> float
```

## `ddopt.spectroscopy` (Agent C)
```python
@dataclass class Experiment: family ("ramsey"|"hahn"|"cpmg"), n, T, shots
def survival_probability(noise, exp: Experiment, *, spam=(a, b), width=0.0) -> float
def simulate_dataset(noise, experiments, *, spam, rng, method="analytic"|"mc") -> dict
def fit(dataset_train, model_name, *, bounds, n_boot, rng, dataset_test=None) -> FitResult
def predict(fit: FitResult, experiments) -> np.ndarray
```

## `ddopt.optimizer` (Agent D)
```python
def decode(x, n, T, width, *, mode, guard, base_phases, dt_grid=None) -> PulseSequence
def optimize(n, T, width, noise, config, *, mode, train_draws, sigma0, max_evals, seed,
             x0=None, robust=None) -> OptimizationResult
```

## `ddopt.evaluation` (Agent D)
```python
def canonical_baselines(n, T, width, **kw) -> dict[str, PulseSequence]  # free + all families feasible at n
def select_baseline(baselines, noise, config, train_draws) -> str        # pre-registered: lowest TRAIN infidelity
def evaluate(sequences: dict[str, PulseSequence], noise, config, test_seeds) -> dict  # paired, independent seeds
def paired_bootstrap(a, b, n_boot, rng) -> dict   # ratio, reduction, CIs
```

## `ddopt.provenance` (Agent F)
```python
def run_manifest(config: dict, *, seeds, command, extra=None) -> dict  # git SHA, env, hashes, time
def write_run(out_dir, name, payload, manifest) -> Path   # immutable results/<run_id>/... ; refuses overwrite
```
