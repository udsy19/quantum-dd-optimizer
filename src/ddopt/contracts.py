"""Shared public data contracts for ``ddopt`` (owned by the integration lead).

Every module exchanges data through the dataclasses defined here. Changing a
field name or meaning is a breaking change and must go through the lead.

Unit conventions (see ``docs/PHYSICS_CONVENTIONS.md``):

* time ``t``, ``T``, widths, gaps: seconds (s)
* angular frequency ``omega``: rad/s; detuning ``delta(t)``: rad/s
* PSD: **two-sided** ``S2(omega) = int C(tau) exp(-i omega tau) dtau`` in
  (rad/s)^2 / (rad/s) = rad^2/s, defined for omega in (-inf, inf), even in omega
* phases / angles: radians
* infidelity: dimensionless average-gate infidelity ``1 - F_avg``
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

PSDKind = Literal["one_over_f", "lorentzian", "white", "telegraph"]
DetuningKind = Literal["none", "constant", "smooth_rect"]


def _jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, complex):
        return {"re": obj.real, "im": obj.imag}
    if isinstance(obj, float) and not math.isfinite(obj):
        return str(obj)
    return obj


class JsonMixin:
    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)

    def to_json(self, **kw: Any) -> str:
        return json.dumps(self.to_dict(), **kw)


# ---------------------------------------------------------------------------
# Noise
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PSDComponent(JsonMixin):
    """One additive, stationary, zero-mean component of the dephasing noise delta(t).

    kind / params (all two-sided, rad^2/s):

    * ``one_over_f``: ``S2 = A / |omega|**alpha`` for ``omega_low <= |omega| <= omega_high``,
      zero outside. params: ``A`` [rad^2/s * (rad/s)^alpha], ``alpha`` [-].
    * ``lorentzian``: Gaussian Ornstein-Uhlenbeck process, ``C(tau) = sigma^2 exp(-|tau|/tau_c)``,
      ``S2 = 2 sigma^2 tau_c / (1 + omega^2 tau_c^2)``. params: ``sigma`` [rad/s], ``tau_c`` [s].
    * ``white``: band-limited white, ``S2 = S0`` for ``|omega| <= omega_high`` (``omega_low`` must be 0).
      params: ``S0`` [rad^2/s].
    * ``telegraph``: symmetric random telegraph noise delta = +-b, switching rate ``gamma`` [1/s]
      (each direction). Same autocorrelation/PSD as a Lorentzian with sigma=b, tau_c=1/(2 gamma)
      but **non-Gaussian**; the Gaussian filter-function formula is only an approximation.
      params: ``b`` [rad/s], ``gamma`` [1/s].

    ``omega_low``/``omega_high`` (rad/s) are hard cutoffs applied to every kind
    (``omega_high = inf`` allowed for lorentzian/telegraph).
    """

    kind: PSDKind
    params: dict[str, float]
    omega_low: float = 0.0
    omega_high: float = math.inf

    def validate(self) -> None:
        required = {
            "one_over_f": {"A", "alpha"},
            "lorentzian": {"sigma", "tau_c"},
            "white": {"S0"},
            "telegraph": {"b", "gamma"},
        }[self.kind]
        missing = required - set(self.params)
        if missing:
            raise ValueError(f"{self.kind} component missing params {sorted(missing)}")
        if any((not math.isfinite(v)) or v < 0 for v in self.params.values()):
            raise ValueError(f"{self.kind} params must be finite and nonnegative: {self.params}")
        if not (0.0 <= self.omega_low < self.omega_high):
            raise ValueError("require 0 <= omega_low < omega_high")
        if self.kind == "one_over_f" and (self.omega_low <= 0 or not math.isfinite(self.omega_high)):
            raise ValueError("one_over_f requires finite cutoffs 0 < omega_low < omega_high < inf")
        if self.kind == "white" and (self.omega_low != 0 or not math.isfinite(self.omega_high)):
            raise ValueError("white requires omega_low == 0 and finite omega_high")


@dataclass(frozen=True)
class DetuningProfile(JsonMixin):
    """Deterministic, *known-in-form* detuning d_known(t) in rad/s (e.g. ac-Stark shift
    from a neighbouring readout).

    * ``none``: d = 0
    * ``constant``: d = amplitude for all t
    * ``smooth_rect``: d = amplitude * 0.5*[tanh((t - t_on)/rise) - tanh((t - t_off)/rise)]
      (``rise`` > 0, seconds).
    """

    kind: DetuningKind = "none"
    amplitude: float = 0.0
    t_on: float = 0.0
    t_off: float = 0.0
    rise: float = 1e-9

    def validate(self) -> None:
        if self.kind == "smooth_rect" and not (self.t_off >= self.t_on and self.rise > 0):
            raise ValueError("smooth_rect requires t_off >= t_on and rise > 0")

    def __call__(self, t: np.ndarray) -> np.ndarray:
        t = np.asarray(t, dtype=float)
        if self.kind == "none":
            return np.zeros_like(t)
        if self.kind == "constant":
            return np.full_like(t, self.amplitude)
        return self.amplitude * 0.5 * (
            np.tanh((t - self.t_on) / self.rise) - np.tanh((t - self.t_off) / self.rise)
        )


@dataclass(frozen=True)
class NoiseModel(JsonMixin):
    """Total qubit-frequency fluctuation delta(t) = sum(components) (stochastic, zero mean)
    plus a deterministic ``detuning`` profile. ``T1`` in seconds (``inf`` = no relaxation)."""

    components: tuple[PSDComponent, ...] = ()
    detuning: DetuningProfile = field(default_factory=DetuningProfile)
    T1: float = math.inf
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for c in self.components:
            c.validate()
        self.detuning.validate()
        if not (self.T1 > 0):
            raise ValueError("T1 must be > 0 (use inf for no relaxation)")

    @property
    def is_gaussian(self) -> bool:
        return all(c.kind != "telegraph" for c in self.components)


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PulseSequence(JsonMixin):
    """Idle-window control schedule of ``n`` nominal pi pulses (rotation angle ``angles``).

    * The window is [0, T]. Pulse k is a square pulse of duration ``widths[k]`` centred at
      ``centers[k]``, about the equatorial axis ``cos(phases[k]) X + sin(phases[k]) Y``.
      Rabi rate during the pulse: Omega_k = angles[k] / widths[k] (rad/s).
    * ``guard``: minimum gap (s) between window edges and pulse edges, and between pulses.
    * ``dt_grid``: if not None, pulse start times must lie on multiples of dt_grid
      (hardware clock, e.g. an assumed 4 ns tick); ``validate`` checks within 1e-12 s.
    * ``widths == 0`` means ideal instantaneous pulses (analytic limit only).
    * ``label`` names the family ("free", "hahn", "cpmg", "xy4", "xy8", "udd", "optimized", ...).
    """

    T: float
    centers: tuple[float, ...] = ()
    widths: tuple[float, ...] = ()
    phases: tuple[float, ...] = ()
    angles: tuple[float, ...] = ()
    guard: float = 0.0
    dt_grid: float | None = None
    label: str = "custom"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.centers)

    def validate(self) -> None:
        n = self.n
        if not (len(self.widths) == len(self.phases) == len(self.angles) == n):
            raise ValueError("centers, widths, phases, angles must have equal length")
        if not (self.T > 0 and math.isfinite(self.T)):
            raise ValueError("T must be positive and finite")
        if any(w < 0 for w in self.widths):
            raise ValueError("widths must be nonnegative")
        tol = 1e-15 + 1e-12 * self.T
        edges = [0.0]
        prev_end = 0.0
        for k in range(n):
            start = self.centers[k] - self.widths[k] / 2
            end = self.centers[k] + self.widths[k] / 2
            if start < prev_end + self.guard - tol:
                raise ValueError(
                    f"pulse {k} starts at {start:.6e} s, violates order/guard after {prev_end:.6e} s"
                )
            prev_end = end
            edges.append(start)
        if n and prev_end > self.T - self.guard + tol:
            raise ValueError(f"last pulse ends at {prev_end:.6e} s, violates T - guard")
        if self.dt_grid is not None:
            for k in range(n):
                start = self.centers[k] - self.widths[k] / 2
                q = start / self.dt_grid
                if abs(q - round(q)) * self.dt_grid > 1e-12:
                    raise ValueError(f"pulse {k} start {start:.6e} s not on dt_grid {self.dt_grid}")

    def gaps(self) -> np.ndarray:
        """Free-evolution gaps (n+1,) between window edges and pulse edges, seconds."""
        starts = np.asarray(self.centers) - np.asarray(self.widths) / 2
        ends = np.asarray(self.centers) + np.asarray(self.widths) / 2
        bounds_lo = np.concatenate([[0.0], ends])
        bounds_hi = np.concatenate([starts, [self.T]])
        return bounds_hi - bounds_lo


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

FrameCorrection = Literal["ideal_control", "ideal_control_plus_virtual_z"]


@dataclass(frozen=True)
class ControlErrors(JsonMixin):
    """Static (per-trajectory, quasi-static) control errors.

    * ``amp_rel_std``: each trajectory draws one relative Rabi-amplitude error
      eps ~ Normal(amp_rel_bias, amp_rel_std); every pulse rotates by angle*(1+eps).
    * ``amp_rel_bias``: deterministic relative amplitude miscalibration.
    * ``phase_std``: per-trajectory common axis-phase error ~ Normal(0, phase_std) rad.
    * ``detuning_offset``: deterministic extra static detuning (rad/s) not known to the
      controller (calibration error); added to delta(t).
    """

    amp_rel_std: float = 0.0
    amp_rel_bias: float = 0.0
    phase_std: float = 0.0
    detuning_offset: float = 0.0


@dataclass(frozen=True)
class SimulationConfig(JsonMixin):
    """Numerical and statistical settings for ``simulator.simulate``.

    * ``n_traj``: Monte-Carlo noise trajectories.
    * ``seed``: integer seed of ``np.random.default_rng`` for noise + control-error draws.
    * ``noise_dt``: time step (s) of the sampled noise grid.
    * ``pulse_steps``: piecewise-constant sub-steps per finite pulse.
    * ``include_T1``: compose amplitude damping (phase-covariant, applied per free segment).
    * ``frame_correction``: target unitary = ideal net control unitary U0 (``ideal_control``)
      optionally followed by the best virtual-Z frame update computed from the *known*
      deterministic detuning (``ideal_control_plus_virtual_z``). Virtual-Z is free/instantaneous.
    * ``observable``: "avg_gate_fidelity" (only option for now).
    """

    n_traj: int = 256
    seed: int = 0
    noise_dt: float = 1e-9
    pulse_steps: int = 8
    include_T1: bool = True
    control_errors: ControlErrors = field(default_factory=ControlErrors)
    frame_correction: FrameCorrection = "ideal_control"
    observable: str = "avg_gate_fidelity"


@dataclass
class SimulationResult(JsonMixin):
    infidelity: float
    infidelity_stderr: float
    fidelity: float
    n_traj: int
    seed: int
    virtual_z_angle: float = 0.0
    per_traj_infidelity: list[float] | None = None
    channel_ptm: list[list[float]] | None = None
    runtime_s: float = 0.0
    provenance: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Spectroscopy / fitting
# ---------------------------------------------------------------------------


@dataclass
class FitResult(JsonMixin):
    model_name: str
    param_names: list[str]
    params: list[float]
    param_ci_low: list[float]
    param_ci_high: list[float]
    param_corr: list[list[float]]
    train_nll: float
    train_rmse: float
    heldout_rmse: float
    heldout_coverage: float | None
    derived: dict[str, Any] = field(default_factory=dict)  # e.g. T2*, T2_hahn with CIs
    identifiability_warnings: list[str] = field(default_factory=list)
    success: bool = True
    failure_reason: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Optimisation
# ---------------------------------------------------------------------------


@dataclass
class OptimizationResult(JsonMixin):
    best_sequence: PulseSequence
    best_train_infidelity: float
    history: list[dict[str, Any]]  # per-generation: n_evals, best, median, sigma
    n_evaluations: int
    wall_time_s: float
    optimizer_seed: int
    train_seeds: list[int]
    mode: str  # "timing", "phase", "both"
    x_best: list[float] = field(default_factory=list)
    test_scores: dict[str, Any] = field(default_factory=dict)
    baseline_comparisons: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
