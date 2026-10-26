"""Synthetic dephasing spectroscopy and system identification (Agent C).

Everything in this module is **synthetic**: datasets are generated from a declared truth model
and the fits are tested against that truth. No hardware data are used or implied.

Observable and forward model (binding assumptions of this module)
-----------------------------------------------------------------
* Preparation of ``|+>`` (ideal pi/2), idle window ``[0, T]`` with a family of ideal pi pulses,
  ideal readout projection onto the *ideal* final state ``U_0 |+>`` (``U_0`` = net ideal control
  unitary, see ``ddopt.sequences.ideal_unitary``; e.g. for Hahn-X ``U_0 |+> = |+>`` up to phase).
  Families: ``ramsey`` (free, n=0), ``hahn`` (n=1, X axis, centre T/2), ``cpmg`` (n pulses, Y axis,
  centres ``T (k - 1/2)/n``). Pulses are **instantaneous by default** (``width = 0``); then the
  toggling function is ``y(t) = +-1`` and ``chi = Var(phi)`` exactly. ``Experiment.width > 0`` makes
  the forward model use the generalized filter function (leading order); the *fit* basis supports
  only ``width = 0`` (raises otherwise).
* Ideal return probability ``p = 1/2 [1 + W_T1(T) W_phi(T)]`` with
  ``W_phi = <cos phi>``, ``phi = int delta(t) y(t) dt``. For Gaussian noise ``W_phi = exp(-chi/2)``,
  ``chi = (1/2pi) int S2 F domega`` (two-sided PSD in rad^2/s, ``docs/PHYSICS_CONVENTIONS.md``).
  ``W_T1 = exp(-T/(2 T1))`` is the transverse amplitude-damping factor (pulses instantaneous, so
  no T1 during pulses; amplitude damping is phase covariant and commutes with the pi pulses' effect
  on the transverse component up to the sign absorbed in ``U_0``). The longitudinal (translation)
  part of amplitude damping does not enter the projection on an equatorial state.
* The deterministic detuning and the static calibration offset are **ignored** (Scenario A has
  none). Telegraph components are non-Gaussian: ``method="analytic"`` uses their Gaussian
  (Lorentzian-equivalent) approximation, ``method="exact"`` the exact 2-state transfer matrix
  (``filters.telegraph_coherence_exact``), ``method="mc"`` Monte-Carlo trajectories from
  ``noise.sample_detuning``. Independent components factorize exactly: ``W = W_gauss * W_tel``.
* SPAM is a separate affine map ``p_meas = a + b p`` (a, b declared in the truth manifest).
  Counts are ``Binomial(shots, p_meas)``.

Fit models (``fit``)
--------------------
* ``reduced``: 1/f (``S2 = A_ref (|omega|/omega_ref)^-alpha`` on fixed cutoffs) + white ``S0``.
* ``full``: reduced + Lorentzian ``(sigma, tau_c)``.
* ``alpha`` fixed (default 1.0, a declared prior assumption) or free (``fit_alpha=True``).
* The 1/f cutoffs and the white cutoff are **fixed model assumptions** (defaults = Scenario A
  config values, i.e. the favourable case where the assumed cutoffs equal the truth). The low
  cutoff is not identifiable from T <= 40 us data (FID chi depends on it only logarithmically and
  is degenerate with A).
* **T1 is treated as known** (from a separate T1 experiment; synthetic study: equal to the truth,
  declared in ``dataset["calibration"]``). For instantaneous pulses white dephasing and T1 enter
  every observable only through ``exp(-T (S0/2 + 1/(2 T1)))`` (up to the white-noise cutoff
  correction of relative size ~ (4n+2)/(pi omega_high T)) -- degenerate, so S0 is identifiable
  only given T1.
* SPAM: fitted jointly by default (``spam="fit"``): ``a + b`` is pinned by short-T points and
  ``a + b/2`` by fully decayed Ramsey points, and a joint fit propagates SPAM uncertainty into the
  bootstrap. It is parameterized by the two identified combinations ``spam_hi = a + b`` and
  ``spam_mid = a + b/2`` (with W >= 0 the ideal p lies in [1/2, 1], so only this range is
  observed); (a, b) and their CIs are reported as derived quantities, with a warning if the fitted
  map is unphysical (a < 0 or a + b > 1). In the (a, b) parameterization the two are ~99%
  correlated and ``a`` hits its physical bound a >= 0 for some seeds. Alternatively
  ``spam=(a, b)`` fixes it from a declared calibration (its own error is then *not* propagated).
* All positive parameters are fitted in natural-log space with box bounds (L-BFGS-B, multiple
  starts), binomial negative log likelihood. Uncertainty: parametric bootstrap (refit on data
  simulated from the MLE with the training design). Parametric bootstrap assumes the fitted model is
  correct; under misspecification its intervals are too narrow (that is what held-out coverage
  measures).

Chi is linear in each amplitude (A_ref, S0, sigma^2); per-experiment basis integrals are cached:
1/f via ``filters.dephasing_variance`` (one call per experiment and alpha node; cubic spline in
alpha when alpha is free), white and Lorentzian via exact closed forms in the jump representation
``chi = - sum_{m,m'} J_m J_m' H(tau_m - tau_m')`` with ``H'' = C`` (validated against
``filters.dephasing_variance`` in tests).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from scipy import interpolate, optimize, special, stats

from . import filters, noise as noise_mod, sequences
from .contracts import FitResult, NoiseModel, PSDComponent, _jsonable

__all__ = [
    "Experiment",
    "survival_probability",
    "simulate_dataset",
    "fit",
    "score_heldout",
    "predict",
    "fitted_noise_model",
    "default_design",
    "run_pipeline",
    "chi_closed_form",
    "MODEL_NAMES",
]

TWO_PI = 2.0 * math.pi
# Default fixed cutoffs (rad/s) = Scenario A config values (configs/scenario_a.json).
DEFAULT_OMEGA_LOW = TWO_PI * 1.0
DEFAULT_OMEGA_HIGH = TWO_PI * 1e7
DEFAULT_OMEGA_HIGH_WHITE = TWO_PI * 1e8
DEFAULT_OMEGA_REF = TWO_PI * 1e5  # 1/f amplitude reference frequency (reduces A-alpha correlation)
DEFAULT_SPAM = (0.05, 0.90)       # declared synthetic SPAM truth: p_meas = a + b p
MODEL_NAMES = ("reduced", "full")
_P_EPS = 1e-12


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Experiment:
    """One idle experiment: ``family`` in {"ramsey", "hahn", "cpmg"}, ``n`` pi pulses, idle time
    ``T`` (s), ``shots`` repetitions, pulse ``width`` (s; 0 = instantaneous, the default)."""

    family: str
    n: int
    T: float
    shots: int
    width: float = 0.0

    def __post_init__(self):
        if self.family not in ("ramsey", "hahn", "cpmg"):
            raise ValueError(f"unknown family {self.family!r}")
        want = {"ramsey": 0, "hahn": 1}.get(self.family)
        if want is not None and self.n != want:
            raise ValueError(f"{self.family} requires n={want}")
        if self.family == "cpmg" and self.n < 1:
            raise ValueError("cpmg requires n >= 1")
        if not (self.T > 0 and math.isfinite(self.T)):
            raise ValueError("T must be positive and finite")
        if int(self.shots) < 1:
            raise ValueError("shots must be >= 1")
        if self.width < 0:
            raise ValueError("width must be >= 0")

    @property
    def label(self) -> str:
        return self.family if self.family != "cpmg" else f"cpmg{self.n}"

    def sequence(self):
        if self.family == "ramsey":
            return sequences.free(self.T)
        if self.family == "hahn":
            return sequences.hahn(self.T, self.width)
        return sequences.cpmg(self.n, self.T, self.width)

    def jumps(self) -> tuple[np.ndarray, np.ndarray]:
        """Jump times tau_m and jumps J_m of the instantaneous-pulse switching function y(t)."""
        if self.n == 0:
            return np.array([0.0, self.T]), np.array([1.0, -1.0])
        c = np.asarray(self.sequence().centers)
        J = np.empty(self.n + 2)
        J[0] = 1.0
        J[1:-1] = -2.0 * (-1.0) ** np.arange(self.n)
        J[-1] = -((-1.0) ** self.n)
        return np.concatenate([[0.0], c, [self.T]]), J

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Experiment":
        return Experiment(d["family"], int(d["n"]), float(d["T"]), int(d["shots"]), float(d.get("width", 0.0)))


def _as_exps(experiments) -> list[Experiment]:
    return [e if isinstance(e, Experiment) else Experiment.from_dict(e) for e in experiments]


def default_design(*, shots: int = 1000, T_min: float = 1e-7, T_max: float = 40e-6, n_times: int = 14,
                   train_families: Sequence[tuple[str, int]] = (("ramsey", 0), ("hahn", 1), ("cpmg", 2), ("cpmg", 4)),
                   heldout_counts: Sequence[int] = (8, 16)) -> dict[str, list[Experiment]]:
    """Pre-registered synthetic schedule.

    * train: ``train_families`` at ``n_times`` log-spaced times in ``[T_min, T_max]``;
    * heldout_new_n: CPMG-``heldout_counts`` at train times *and* unseen times;
    * heldout_new_T: the training families at the ``n_times - 1`` unseen geometric-midpoint times.
    """
    tt = np.geomspace(T_min, T_max, n_times)
    tu = np.sqrt(tt[:-1] * tt[1:])
    mk = lambda fam, n, T: Experiment(fam, n, float(T), int(shots))  # noqa: E731
    train = [mk(f, n, T) for f, n in train_families for T in tt]
    new_n = [mk("cpmg", n, T) for n in heldout_counts for T in np.sort(np.concatenate([tt, tu]))]
    new_T = [mk(f, n, T) for f, n in train_families for T in tu]
    return {"train": train, "heldout_new_n": new_n, "heldout_new_T": new_T,
            "times_train": tt.tolist(), "times_unseen": tu.tolist()}


# ---------------------------------------------------------------------------
# Closed-form chi for instantaneous pulses (jump representation)
# ---------------------------------------------------------------------------


def _phi_exp(x: np.ndarray) -> np.ndarray:
    """e^{-x} - 1 + x, stable for small x >= 0."""
    small = x < 1e-3
    xs = np.where(small, x, 0.0)
    ser = xs * xs * (0.5 - xs * (1.0 / 6.0 - xs / 24.0))
    return np.where(small, ser, np.expm1(-np.where(small, 1.0, x)) + np.where(small, 1.0, x))


def _H_lorentzian(d: np.ndarray, tau_c) -> np.ndarray:
    """H with H'' = exp(-|d|/tau_c) (unit sigma), constant dropped: tau_c^2 (e^{-x} - 1 + x)."""
    return tau_c**2 * _phi_exp(np.abs(d) / tau_c)


def _H_white(d: np.ndarray, omega_high: float) -> np.ndarray:
    """H with H'' = (1/pi) sin(w d)/d (unit S0, |omega| <= w): (1/pi)[d Si(w d) + (cos(w d) - 1)/w]."""
    ad = np.abs(d)
    si, _ = special.sici(omega_high * ad)
    return (ad * si + np.cos(omega_high * ad) / omega_high - 1.0 / omega_high) / math.pi


def chi_closed_form(component: PSDComponent, exp: Experiment) -> float:
    """Exact chi (rad^2) for a white / lorentzian / telegraph (Gaussian-equivalent) component and
    instantaneous pulses, via ``chi = -sum J_m J_m' H(tau_m - tau_m')``."""
    if exp.width != 0:
        raise ValueError("closed form requires instantaneous pulses")
    tau, J = exp.jumps()
    d = tau[:, None] - tau[None, :]
    JJ = J[:, None] * J[None, :]
    if component.kind == "white":
        return float(-component.params["S0"] * np.sum(JJ * _H_white(d, component.omega_high)))
    if component.kind in ("lorentzian", "telegraph"):
        if component.omega_low != 0 or math.isfinite(component.omega_high):
            raise ValueError("closed form lorentzian requires no cutoffs")
        sigma, tau_c = noise_mod.lorentzian_equivalent(component)
        return float(-sigma**2 * np.sum(JJ * _H_lorentzian(d, tau_c)))
    raise ValueError(f"no closed form for {component.kind}")


_CHI_CACHE: dict[tuple, float] = {}


def _component_key(c: PSDComponent, exp: Experiment) -> tuple:
    return (c.kind, tuple(sorted(c.params.items())), c.omega_low, c.omega_high,
            exp.family, exp.n, exp.T, exp.width)


def _chi_component(c: PSDComponent, exp: Experiment) -> float:
    key = _component_key(c, exp)
    if key in _CHI_CACHE:
        return _CHI_CACHE[key]
    if exp.width == 0 and (c.kind == "white" or (c.kind in ("lorentzian", "telegraph")
                                                 and c.omega_low == 0 and math.isinf(c.omega_high))):
        val = chi_closed_form(c, exp)
    else:
        val = filters.dephasing_variance(c, exp.sequence())[0]
    if len(_CHI_CACHE) < 200_000:
        _CHI_CACHE[key] = val
    return val


def _chi_gaussian(noise: NoiseModel, exp: Experiment, *, include_telegraph: bool) -> float:
    return float(sum(_chi_component(c, exp) for c in noise.components
                     if include_telegraph or c.kind != "telegraph"))


# ---------------------------------------------------------------------------
# Forward model
# ---------------------------------------------------------------------------


def _w_t1(T, T1: float):
    return np.exp(-np.asarray(T) / (2.0 * T1)) if math.isfinite(T1) else np.ones_like(np.asarray(T, float))


def _telegraph_mc(comps: list[PSDComponent], exp: Experiment, rng: np.random.Generator, n_traj: int,
                  steps_per_half_gap: int = 8) -> tuple[float, float]:
    """MC estimate (mean, standard error) of <cos phi> for telegraph components, instantaneous pulses.

    Uniform grid with M = 2 max(n,1) m cells so every pulse centre is on the grid; m chosen so that
    dt <= 1/(20 max(gamma, b)) and >= ``steps_per_half_gap`` cells per half gap. phi = sum y_j delta_j dt
    (left-point rule, delta held over each cell)."""
    if exp.width != 0:
        raise ValueError("mc telegraph forward model requires instantaneous pulses")
    rate = max(max(c.params["gamma"], c.params["b"]) for c in comps)
    half = max(exp.n, 1) * 2
    m = max(steps_per_half_gap, int(math.ceil(exp.T * 20.0 * rate / half)))
    M = half * m
    t = np.linspace(0.0, exp.T, M + 1)
    tm = t[:-1] + 0.5 * exp.T / M
    y = filters.switching_function(exp.sequence(), tm)
    nm = NoiseModel(components=tuple(comps))
    delta = noise_mod.sample_detuning(nm, t, n_traj, rng)[:, :-1]
    phi = delta @ y * (exp.T / M)
    c = np.cos(phi)
    return float(c.mean()), float(c.std(ddof=1) / math.sqrt(n_traj))


def _coherence(noise: NoiseModel, exp: Experiment, method: str, rng=None, n_traj: int = 2000) -> tuple[float, float]:
    """(W_phi, MC standard error) for one experiment."""
    tel = [c for c in noise.components if c.kind == "telegraph"]
    if method == "analytic" or not tel:
        return math.exp(-0.5 * _chi_gaussian(noise, exp, include_telegraph=True)), 0.0
    wg = math.exp(-0.5 * _chi_gaussian(noise, exp, include_telegraph=False))
    if method == "exact":
        wt = 1.0
        for c in tel:
            wt *= filters.telegraph_coherence_exact(c, exp.sequence())
        return wg * wt, 0.0
    if method == "mc":
        if rng is None:
            raise ValueError("mc requires rng")
        m, se = _telegraph_mc(tel, exp, rng, n_traj)
        return wg * m, wg * se
    raise ValueError("method must be 'analytic', 'exact' or 'mc'")


def survival_probability(noise: NoiseModel, exp: Experiment, *, spam=(0.0, 1.0), width: float | None = None,
                         method: str = "analytic", rng=None, n_traj: int = 2000) -> float:
    """``p_meas = a + b * 1/2 [1 + W_T1 W_phi]`` for one experiment (see module docstring).

    ``width`` (s) overrides ``exp.width`` if given. ``method`` as in :func:`simulate_dataset`."""
    if width is not None:
        exp = dataclasses.replace(exp, width=float(width))
    W, _ = _coherence(noise, exp, method, rng, n_traj)
    p = 0.5 * (1.0 + float(_w_t1(exp.T, noise.T1)) * W)
    a, b = spam
    return float(a + b * p)


def _noise_to_dict(noise: NoiseModel) -> dict:
    return json.loads(noise.to_json())


def simulate_dataset(noise: NoiseModel, experiments, *, spam=DEFAULT_SPAM, rng, method: str = "analytic",
                     n_traj: int = 2000, label: str = "") -> dict:
    """Synthetic dataset with binomial shot noise.

    ``rng``: ``np.random.Generator`` or int seed (an int is recorded in the manifest). The same
    generator is used first for MC coherence draws (``method="mc"``), then for the binomial counts.
    ``method``: ``"analytic"`` (Gaussian filter function for every component; telegraph via its
    Gaussian/Lorentzian equivalent), ``"exact"`` (Gaussian part analytic x exact telegraph transfer
    matrix), ``"mc"`` (Gaussian part analytic x MC telegraph trajectories, ``n_traj`` each).

    Returns a JSON-friendly dict with ``experiments``, ``shots``, ``counts``, ``p_obs``, and a
    ``truth`` manifest (true noise model, SPAM, method, seed, experiment list, assumptions) and a
    ``calibration`` block of quantities a fitter may legitimately treat as known (T1).
    """
    seed = None
    if not isinstance(rng, np.random.Generator):
        seed = int(rng)
        rng = np.random.default_rng(seed)
    exps = _as_exps(experiments)
    a, b = float(spam[0]), float(spam[1])
    if not (0 <= a and 0 < b and a + b <= 1):
        raise ValueError("SPAM requires 0 <= a, 0 < b, a + b <= 1")
    W = np.empty(len(exps))
    W_se = np.empty(len(exps))
    for i, e in enumerate(exps):
        W[i], W_se[i] = _coherence(noise, e, method, rng, n_traj)
    T = np.array([e.T for e in exps])
    p_ideal = 0.5 * (1.0 + _w_t1(T, noise.T1) * W)
    p_meas = a + b * p_ideal
    shots = np.array([e.shots for e in exps], dtype=np.int64)
    counts = rng.binomial(shots, np.clip(p_meas, 0.0, 1.0))
    truth = {
        "noise": _noise_to_dict(noise),
        "spam": {"a": a, "b": b, "map": "p_meas = a + b * p"},
        "method": method,
        "n_traj_mc": n_traj if method == "mc" else None,
        "seed": seed,
        "W_phi": W.tolist(),
        "W_phi_mc_stderr": W_se.tolist(),
        "p_ideal": p_ideal.tolist(),
        "p_meas": p_meas.tolist(),
        "assumptions": ["prepare |+>, project on ideal U0|+>", "instantaneous pulses unless width>0",
                        "W_T1 = exp(-T/(2 T1))", "deterministic detuning ignored",
                        "binomial shot noise", "SPAM affine p_meas = a + b p"],
    }
    return {
        "label": label,
        "experiments": [e.to_dict() for e in exps],
        "shots": shots.tolist(),
        "counts": counts.tolist(),
        "p_obs": (counts / shots).tolist(),
        "truth": truth,
        "calibration": {"T1": noise.T1 if math.isfinite(noise.T1) else "inf",
                        "T1_source": "assumed known from a separate T1 experiment (synthetic: equal to truth)"},
    }


# ---------------------------------------------------------------------------
# Fit model specification and basis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Spec:
    model_name: str
    fit_alpha: bool
    alpha: float
    spam_mode: str  # "fit" | "fixed"
    spam_fixed: tuple[float, float]
    T1: float
    omega_low: float
    omega_high: float
    omega_high_white: float
    omega_ref: float
    alpha_nodes: tuple[float, ...]
    names: tuple[str, ...]
    lo: tuple[float, ...]
    hi: tuple[float, ...]
    log: tuple[bool, ...]

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["T1"] = self.T1 if math.isfinite(self.T1) else "inf"
        return d

    @staticmethod
    def from_dict(d: dict) -> "_Spec":
        d = dict(d)
        d["T1"] = math.inf if d["T1"] == "inf" else float(d["T1"])
        for k in ("spam_fixed", "alpha_nodes", "names", "lo", "hi", "log"):
            d[k] = tuple(d[k])
        return _Spec(**d)


DEFAULT_BOUNDS = {  # natural units; log-space for positive parameters
    "A_ref": (1e0, 1e8),     # rad^2/s at omega_ref
    "alpha": (0.4, 1.6),
    "S0": (1e0, 1e7),        # rad^2/s
    "sigma": (1e3, 1e7),     # rad/s
    "tau_c": (1e-8, 1e-4),   # s
    "spam_hi": (0.5, 1.0),   # = a + b: measured p for perfect coherence (p = 1)
    "spam_mid": (0.25, 0.75),  # = a + b/2: measured p for complete dephasing (p = 1/2)
}
_LOGP = {"A_ref", "S0", "sigma", "tau_c"}


def _make_spec(model_name, *, bounds, fit_alpha, alpha, spam, T1, omega_low, omega_high, omega_high_white,
               omega_ref, n_alpha_nodes=13) -> _Spec:
    if model_name not in MODEL_NAMES:
        raise ValueError(f"model_name must be one of {MODEL_NAMES}")
    b = dict(DEFAULT_BOUNDS)
    b.update(bounds or {})
    names = ["A_ref"] + (["alpha"] if fit_alpha else []) + ["S0"]
    if model_name == "full":
        names += ["sigma", "tau_c"]
    if isinstance(spam, str):
        if spam != "fit":
            raise ValueError("spam must be 'fit' or a declared (a, b) tuple")
        spam_mode, spam_fixed = "fit", (math.nan, math.nan)
        names += ["spam_hi", "spam_mid"]
    else:
        spam_mode, spam_fixed = "fixed", (float(spam[0]), float(spam[1]))
    lo = tuple(float(math.log(b[n][0]) if n in _LOGP else b[n][0]) for n in names)
    hi = tuple(float(math.log(b[n][1]) if n in _LOGP else b[n][1]) for n in names)
    a_lo, a_hi = b["alpha"]
    nodes = tuple(np.linspace(a_lo, a_hi, n_alpha_nodes).tolist()) if fit_alpha else (float(alpha),)
    return _Spec(model_name, bool(fit_alpha), float(alpha), spam_mode, spam_fixed, float(T1),
                 float(omega_low), float(omega_high), float(omega_high_white), float(omega_ref), nodes,
                 tuple(names), lo, hi, tuple(n in _LOGP for n in names))


class _Basis:
    """Cached per-experiment basis for fast chi(theta) evaluation over a fixed experiment list."""

    def __init__(self, spec: _Spec, exps: list[Experiment]):
        if any(e.width != 0 for e in exps):
            raise ValueError("fit basis supports instantaneous pulses only (width = 0)")
        self.spec = spec
        self.exps = exps
        self.T = np.array([e.T for e in exps])
        self.shots = np.array([e.shots for e in exps], dtype=float)
        self.wt1 = _w_t1(self.T, spec.T1)
        # 1/f with A = 1 at the alpha nodes
        vals = np.empty((len(exps), len(spec.alpha_nodes)))
        for j, al in enumerate(spec.alpha_nodes):
            c = noise_mod.make_one_over_f(1.0, al, spec.omega_low, spec.omega_high)
            for i, e in enumerate(exps):
                vals[i, j] = _chi_component(c, e)
        if spec.fit_alpha:
            self.f_spline = interpolate.CubicSpline(np.array(spec.alpha_nodes), np.log(vals), axis=1)
            self.f_fixed = None
        else:
            self.f_fixed = vals[:, 0]
        cw = noise_mod.make_white(1.0, spec.omega_high_white)
        self.w = np.array([_chi_component(cw, e) for e in exps])
        # padded jump-pair arrays for the Lorentzian closed form
        P = max((e.n + 2) ** 2 for e in exps)
        self.d = np.zeros((len(exps), P))
        self.JJ = np.zeros((len(exps), P))
        for i, e in enumerate(exps):
            tau, J = e.jumps()
            dd = np.abs(tau[:, None] - tau[None, :]).ravel()
            self.d[i, :dd.size] = dd
            self.JJ[i, :dd.size] = (J[:, None] * J[None, :]).ravel()

    def unpack(self, x: np.ndarray) -> dict[str, float]:
        return {n: (math.exp(v) if lg else float(v)) for n, v, lg in zip(self.spec.names, x, self.spec.log)}

    def chi(self, x: np.ndarray) -> np.ndarray:
        q = self.unpack(x)
        s = self.spec
        if s.fit_alpha:
            al = q["alpha"]
            f1 = np.exp(self.f_spline(al))
        else:
            al = s.alpha
            f1 = self.f_fixed
        A = q["A_ref"] * s.omega_ref**al
        chi = A * f1 + q["S0"] * self.w
        if s.model_name == "full":
            chi = chi - q["sigma"] ** 2 * np.sum(self.JJ * _H_lorentzian(self.d, q["tau_c"]), axis=1)
        return chi

    def spam(self, x: np.ndarray) -> tuple[float, float]:
        if self.spec.spam_mode == "fixed":
            return self.spec.spam_fixed
        q = self.unpack(x)
        return _spam_ab(q["spam_hi"], q["spam_mid"])

    def p_ideal(self, x: np.ndarray) -> np.ndarray:
        return 0.5 * (1.0 + self.wt1 * np.exp(-0.5 * self.chi(x)))

    def p_meas(self, x: np.ndarray) -> np.ndarray:
        a, b = self.spam(x)
        return np.clip(a + b * self.p_ideal(x), _P_EPS, 1.0 - _P_EPS)


def _spam_ab(hi: float, mid: float) -> tuple[float, float]:
    """(a, b) from the identified SPAM combinations hi = a + b, mid = a + b/2."""
    return 2.0 * mid - hi, 2.0 * (hi - mid)


def _nll(basis: _Basis, x: np.ndarray, k: np.ndarray) -> float:
    p = basis.p_meas(x)
    N = basis.shots
    return float(-np.sum(k * np.log(p) + (N - k) * np.log1p(-p)))


def _nll_floor(k: np.ndarray, N: np.ndarray) -> float:
    """Saturated-model NLL (p = k/N) -- used to report the deviance."""
    f = k / N
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(k > 0, k * np.log(np.where(f > 0, f, 1)), 0.0) + \
            np.where(N - k > 0, (N - k) * np.log(np.where(f < 1, 1 - f, 1)), 0.0)
    return float(-t.sum())


def _minimize(basis: _Basis, k: np.ndarray, starts: list[np.ndarray]):
    lo, hi = np.array(basis.spec.lo), np.array(basis.spec.hi)
    out = []
    for x0 in starts:
        try:
            r = optimize.minimize(lambda x: _nll(basis, x, k), np.clip(x0, lo, hi), method="L-BFGS-B",
                                  bounds=list(zip(lo, hi)), options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-8})
            out.append(r)
        except (FloatingPointError, ValueError):  # pragma: no cover - defensive
            continue
    return out


def _random_starts(spec: _Spec, rng: np.random.Generator, n: int) -> list[np.ndarray]:
    lo, hi = np.array(spec.lo), np.array(spec.hi)
    span = hi - lo
    starts = [lo + 0.5 * span]
    starts += [lo + span * (0.05 + 0.9 * rng.random(lo.size)) for _ in range(max(0, n - 1))]
    return starts


def _pearson(k, N, p):
    return float(np.sum((k - N * p) ** 2 / (N * p * (1 - p))))


# ---------------------------------------------------------------------------
# Derived quantities (T2*, T2 Hahn) on a fixed T grid
# ---------------------------------------------------------------------------

_T2_GRID = np.geomspace(5e-8, 4e-4, 60)


def _one_over_e_time(T: np.ndarray, W: np.ndarray) -> float:
    """First crossing of W(T) = 1/e by linear interpolation of ln(-ln W) vs ln T; inf if none."""
    W = np.clip(W, 1e-300, 1.0)
    above = W > math.exp(-1)
    idx = np.nonzero(above[:-1] & ~above[1:])[0]
    if W[0] <= math.exp(-1):
        return float(T[0])
    if idx.size == 0:
        return math.inf
    i = idx[0]
    g = lambda w: math.log(max(-math.log(w), 1e-300))  # noqa: E731
    x0, x1 = math.log(T[i]), math.log(T[i + 1])
    g0, g1 = g(W[i]), g(W[i + 1])
    return float(math.exp(x0 + (0.0 - g0) * (x1 - x0) / (g1 - g0)))


def _t2_basis(spec: _Spec) -> dict[str, _Basis]:
    return {fam: _Basis(spec, [Experiment(fam, n, float(T), 1) for T in _T2_GRID])
            for fam, n in (("ramsey", 0), ("hahn", 1))}


def _t2_from_basis(tb: dict[str, _Basis], x: np.ndarray) -> dict[str, float]:
    out = {}
    for fam, key in (("ramsey", "T2star"), ("hahn", "T2_hahn")):
        b = tb[fam]
        wphi = np.exp(-0.5 * b.chi(x))
        out[key] = _one_over_e_time(_T2_GRID, b.wt1 * wphi)
        out[key + "_phi_only"] = _one_over_e_time(_T2_GRID, wphi)
    return out


def truth_t2(noise: NoiseModel, method: str = "exact") -> dict[str, float]:
    """T2* and T2_Hahn (1/e times of W_T1 W_phi and of W_phi alone) of a truth model on the same grid."""
    out = {}
    for fam, n, key in (("ramsey", 0, "T2star"), ("hahn", 1, "T2_hahn")):
        exps = [Experiment(fam, n, float(T), 1) for T in _T2_GRID]
        wphi = np.array([_coherence(noise, e, method if method != "mc" else "exact")[0] for e in exps])
        out[key] = _one_over_e_time(_T2_GRID, _w_t1(_T2_GRID, noise.T1) * wphi)
        out[key + "_phi_only"] = _one_over_e_time(_T2_GRID, wphi)
    return out


# ---------------------------------------------------------------------------
# Fit
# ---------------------------------------------------------------------------


def _dataset_arrays(ds: dict) -> tuple[list[Experiment], np.ndarray, np.ndarray]:
    exps = _as_exps(ds["experiments"])
    return exps, np.asarray(ds["counts"], dtype=float), np.asarray(ds["shots"], dtype=float)


def _fit_core(dataset_train: dict, spec: _Spec, *, n_boot: int, rng: np.random.Generator, n_starts: int,
              gof_pmin: float, corr_warn: float) -> FitResult:
    """Fit on training data only. Never receives held-out observations (leakage guard)."""
    t0 = time.perf_counter()
    exps, k, N = _dataset_arrays(dataset_train)
    basis = _Basis(spec, exps)
    lo, hi = np.array(spec.lo), np.array(spec.hi)
    span = hi - lo
    res = _minimize(basis, k, _random_starts(spec, rng, n_starts))
    warnings_: list[str] = []
    failure: list[str] = []
    conv = [r for r in res if r.success and np.isfinite(r.fun)]
    if not conv:
        failure.append("optimizer did not converge from any start")
        conv = [r for r in res if np.isfinite(r.fun)]
    best = min(conv, key=lambda r: r.fun)
    xhat = best.x
    # multimodality check among converged starts
    for r in conv:
        if r is best:
            continue
        if r.fun - best.fun < 1.0 and np.max(np.abs(r.x - xhat) / span) > 0.05:
            warnings_.append(f"near-degenerate optimum (dNLL={r.fun - best.fun:.3g}) at a distinct point: "
                             "likelihood ridge / multimodality")
            break
    q = basis.unpack(xhat)
    at_bound = [n for n, v, l_, h_ in zip(spec.names, xhat, lo, hi)
                if min(v - l_, h_ - v) < 1e-3 * (h_ - l_)]
    if at_bound:
        failure.append(f"MLE at parameter bound(s): {at_bound}")
    p_hat = basis.p_meas(xhat)
    dof = max(1, len(k) - len(spec.names))
    chi2 = _pearson(k, N, p_hat)
    gof_p = float(stats.chi2.sf(chi2, dof))
    if gof_p < gof_pmin:
        failure.append(f"training goodness of fit rejected: Pearson chi2/dof={chi2 / dof:.3g}, p={gof_p:.2e} < {gof_pmin:g}")
    train_rmse = float(np.sqrt(np.mean((k / N - p_hat) ** 2)))
    floor = float(np.sqrt(np.mean(p_hat * (1 - p_hat) / N)))

    # parametric bootstrap
    tb = _t2_basis(spec)
    boot_x = []
    n_fail = 0
    p_clip = np.clip(p_hat, 0, 1)
    for _ in range(int(n_boot)):
        kb = rng.binomial(N.astype(np.int64), p_clip).astype(float)
        rb = _minimize(basis, kb, [xhat])
        rb = [r for r in rb if np.isfinite(r.fun)]
        if not rb or not rb[0].success:
            n_fail += 1
        if rb:
            boot_x.append(rb[0].x)
    boot_x = np.array(boot_x).reshape(-1, len(spec.names))
    if n_boot and n_fail > 0.1 * n_boot:
        warnings_.append(f"{n_fail}/{n_boot} bootstrap refits did not report convergence")
    nat = lambda X: np.where(np.array(spec.log), np.exp(X), X)  # noqa: E731
    if boot_x.shape[0] >= 2:
        ci_lo_t = np.quantile(boot_x, 0.025, axis=0)
        ci_hi_t = np.quantile(boot_x, 0.975, axis=0)
        sd = boot_x.std(axis=0, ddof=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            corr = np.corrcoef(boot_x, rowvar=False) if np.all(sd > 0) else np.full((len(sd),) * 2, np.nan)
        corr = np.atleast_2d(corr)
        ci_lo, ci_hi = nat(ci_lo_t).tolist(), nat(ci_hi_t).tolist()
        for i in range(len(spec.names)):
            for j in range(i + 1, len(spec.names)):
                if np.isfinite(corr[i, j]) and abs(corr[i, j]) > corr_warn:
                    warnings_.append(f"|corr({spec.names[i]}, {spec.names[j]})| = {abs(corr[i, j]):.3f} > {corr_warn} "
                                     "(bootstrap, transformed coordinates): weakly identifiable combination")
        for i, n in enumerate(spec.names):
            tol = 1e-3 * span[i]
            if ci_lo_t[i] - lo[i] < tol or hi[i] - ci_hi_t[i] < tol:
                warnings_.append(f"95% bootstrap CI of {n} reaches a bound: not identified within bounds")
        t2_boot = [_t2_from_basis(tb, xb) for xb in boot_x]
    else:
        ci_lo = ci_hi = [math.nan] * len(spec.names)
        corr = np.full((len(spec.names),) * 2, np.nan)
        t2_boot = []
        warnings_.append("no bootstrap (n_boot < 2): no uncertainty quantified")
    warnings_.append("T1 treated as known (separate T1 experiment); with instantaneous pulses S0 and 1/T1 are "
                     "degenerate (both enter as exp(-T(S0/2 + 1/(2T1))) for every sequence, up to the "
                     "white-noise cutoff correction ~ (4n+2)/(pi omega_high T))")
    warnings_.append("1/f cutoffs fixed by assumption (omega_low not identifiable from T<=40us; degenerate with A)")
    if not spec.fit_alpha:
        warnings_.append(f"alpha fixed at {spec.alpha} by assumption (not fitted)")

    derived: dict[str, Any] = {}
    t2_hat = _t2_from_basis(tb, xhat)
    for key, v in t2_hat.items():
        vals = np.array([d[key] for d in t2_boot]) if t2_boot else np.array([])
        fin = vals[np.isfinite(vals)]
        derived[key] = {"value_s": v,
                        "ci95_s": [float(np.quantile(fin, 0.025)), float(np.quantile(fin, 0.975))] if fin.size >= 2 else None,
                        "n_boot_infinite": int(vals.size - fin.size)}
    if spec.spam_mode == "fit":
        a_hat, b_hat = _spam_ab(q["spam_hi"], q["spam_mid"])
        ab_boot = np.array([_spam_ab(*nat(xb)[-2:]) for xb in boot_x]) if boot_x.shape[0] >= 2 else None
        for j, nm_ in enumerate(("spam_a", "spam_b")):
            derived[nm_] = {"value": (a_hat, b_hat)[j],
                            "ci95": None if ab_boot is None else [float(np.quantile(ab_boot[:, j], 0.025)),
                                                                  float(np.quantile(ab_boot[:, j], 0.975))]}
        if a_hat < 0 or a_hat + b_hat > 1:
            warnings_.append(f"fitted SPAM map unphysical (a={a_hat:.3g}, a+b={a_hat + b_hat:.3g})")
    derived["A_rad2_s_rad_s_alpha"] = q["A_ref"] * spec.omega_ref ** q.get("alpha", spec.alpha)
    derived.update(train_chi2=chi2, train_dof=dof, train_chi2_pvalue=gof_p,
                   train_deviance=2 * (best.fun - _nll_floor(k, N)), train_shot_noise_rmse=floor,
                   n_train=int(len(k)), n_boot_requested=int(n_boot), n_boot_used=int(boot_x.shape[0]),
                   n_boot_nonconverged=n_fail)
    corr_list = [[float(v) if np.isfinite(v) else None for v in row] for row in corr]
    return FitResult(
        model_name=spec.model_name,
        param_names=list(spec.names),
        params=[q[n] for n in spec.names],
        param_ci_low=[float(v) for v in ci_lo],
        param_ci_high=[float(v) for v in ci_hi],
        param_corr=corr_list,
        train_nll=float(best.fun),
        train_rmse=train_rmse,
        heldout_rmse=math.nan,
        heldout_coverage=None,
        derived=derived,
        identifiability_warnings=warnings_,
        success=not failure,
        failure_reason="; ".join(failure) if failure else None,
        provenance={"model_spec": spec.to_dict(), "x_hat": xhat.tolist(), "bootstrap_x": boot_x.tolist(),
                    "n_starts": n_starts, "optimizer": "scipy L-BFGS-B, binomial NLL, log-space positive params",
                    "bootstrap": "parametric (training design, MLE p, binomial)",
                    "corr_coordinates": "natural-log for A_ref,S0,sigma,tau_c; linear for alpha,spam",
                    "train_data_hash": _hash_obs(dataset_train), "fit_runtime_s": time.perf_counter() - t0},
    )


def _hash_obs(ds: dict) -> str:
    return hashlib.sha256(json.dumps([ds["experiments"], ds["counts"], ds["shots"]]).encode()).hexdigest()[:16]


def fit(dataset_train: dict, model_name: str, *, bounds: dict | None = None, n_boot: int = 200,
        rng: np.random.Generator | int = 0, dataset_test: dict | None = None, fit_alpha: bool = False,
        alpha: float = 1.0, spam="fit", T1: float | None = None, omega_low: float = DEFAULT_OMEGA_LOW,
        omega_high: float = DEFAULT_OMEGA_HIGH, omega_high_white: float = DEFAULT_OMEGA_HIGH_WHITE,
        omega_ref: float = DEFAULT_OMEGA_REF, n_starts: int = 8, gof_pmin: float = 1e-4,
        corr_warn: float = 0.9) -> FitResult:
    """Fit ``model_name`` ("reduced" | "full") to ``dataset_train`` by binomial maximum likelihood.

    The fit uses only ``dataset_train`` (its ``experiments``, ``shots``, ``counts`` and its declared
    ``calibration["T1"]`` unless ``T1`` is given); the truth manifest is never read. If
    ``dataset_test`` is given, it is passed **only** to :func:`score_heldout` after the fit and
    bootstrap are complete; the fitted parameters are identical with or without it.

    Failure criteria (``success=False`` + ``failure_reason``): no start converged; MLE within
    1e-3 x (bound span) of a bound; training Pearson goodness-of-fit p-value < ``gof_pmin``.
    Identifiability warnings: bootstrap |corr| > ``corr_warn``; 95% CI reaching a bound;
    near-degenerate distinct optima; standing structural degeneracies (T1/S0, cutoffs, fixed alpha).
    """
    if not isinstance(rng, np.random.Generator):
        rng = np.random.default_rng(int(rng))
    if T1 is None:
        t1 = dataset_train.get("calibration", {}).get("T1", "inf")
        T1 = math.inf if t1 == "inf" else float(t1)
    spec = _make_spec(model_name, bounds=bounds, fit_alpha=fit_alpha, alpha=alpha, spam=spam, T1=T1,
                      omega_low=omega_low, omega_high=omega_high, omega_high_white=omega_high_white,
                      omega_ref=omega_ref)
    result = _fit_core(dataset_train, spec, n_boot=n_boot, rng=rng, n_starts=n_starts, gof_pmin=gof_pmin,
                       corr_warn=corr_warn)
    if dataset_test is not None:
        score = score_heldout(result, dataset_test)
        result.heldout_rmse = score["rmse"]
        result.heldout_coverage = score["coverage95"]
        result.derived["heldout"] = score
    return result


# ---------------------------------------------------------------------------
# Prediction and held-out scoring
# ---------------------------------------------------------------------------


def _spec_of(fit_: FitResult) -> _Spec:
    return _Spec.from_dict(fit_.provenance["model_spec"])


def predict(fit: FitResult, experiments, *, include_spam: bool = True, x: Sequence[float] | None = None) -> np.ndarray:
    """Predicted (measured, if ``include_spam``) survival probabilities at the MLE (or at ``x``)."""
    spec = _spec_of(fit)
    b = _Basis(spec, _as_exps(experiments))
    xx = np.asarray(fit.provenance["x_hat"] if x is None else x, dtype=float)
    return b.p_meas(xx) if include_spam else b.p_ideal(xx)


def score_heldout(fit: FitResult, dataset_test: dict, *, cov_level: float = 0.95, gof_pmin: float = 1e-4,
                  coverage_min: float = 0.85, groups: dict[str, list[int]] | None = None) -> dict:
    """Score a finished fit on held-out observations (the only place test counts are read).

    * ``rmse``: RMSE of observed fraction vs MLE prediction; ``shot_noise_rmse``: sqrt(mean p(1-p)/N)
      (the RMSE expected for a perfect model); ``rmse_ratio`` = rmse / shot_noise_rmse.
    * ``coverage95``: fraction of held-out counts inside the 95% predictive interval of the
      bootstrap-mixture-of-binomials predictive distribution (parameter + shot noise), computed
      exactly from binomial CDFs (no extra randomness). Discrete counts make it slightly conservative.
    * ``chi2``: sum of z^2 with z = (k/N - p_hat)/sqrt(E_b[p(1-p)]/N + Var_b p), and its p-value.
    * ``misspecification_flags``: chi2 p-value < ``gof_pmin``; coverage < ``coverage_min``.
    """
    spec = _spec_of(fit)
    exps, k, N = _dataset_arrays(dataset_test)
    basis = _Basis(spec, exps)
    xhat = np.asarray(fit.provenance["x_hat"])
    p_hat = basis.p_meas(xhat)
    X = np.asarray(fit.provenance["bootstrap_x"]).reshape(-1, len(spec.names))
    PB = np.array([basis.p_meas(xb) for xb in X]) if X.shape[0] else p_hat[None, :]
    alpha_ = 1 - cov_level
    cdf_k = stats.binom.cdf(k[None, :], N[None, :], PB).mean(0)
    cdf_km1 = stats.binom.cdf(k[None, :] - 1, N[None, :], PB).mean(0)
    covered = (cdf_k >= alpha_ / 2) & (cdf_km1 < 1 - alpha_ / 2)
    var = (PB * (1 - PB)).mean(0) / N + (PB.var(0, ddof=1) if PB.shape[0] > 1 else 0.0)
    z = (k / N - p_hat) / np.sqrt(var)
    chi2 = float(np.sum(z**2))
    pval = float(stats.chi2.sf(chi2, len(k)))
    resid = k / N - p_hat
    rmse = float(np.sqrt(np.mean(resid**2)))
    floor = float(np.sqrt(np.mean(p_hat * (1 - p_hat) / N)))
    flags = []
    if pval < gof_pmin:
        flags.append(f"held-out chi2/n={chi2 / len(k):.3g} (p={pval:.2e}) rejects the fitted model")
    cov = float(covered.mean())
    if cov < coverage_min:
        flags.append(f"held-out 95% predictive coverage {cov:.3f} < {coverage_min}")
    out = {"n": int(len(k)), "rmse": rmse, "shot_noise_rmse": floor, "rmse_ratio": rmse / floor,
           "coverage95": cov, "chi2": chi2, "chi2_pvalue": pval, "misspecification_flags": flags,
           "max_abs_z": float(np.max(np.abs(z))), "test_data_hash": _hash_obs(dataset_test)}
    if groups:
        out["groups"] = {}
        for g, idx in groups.items():
            idx = np.asarray(idx, dtype=int)
            out["groups"][g] = {"n": int(idx.size), "rmse": float(np.sqrt(np.mean(resid[idx] ** 2))),
                                "shot_noise_rmse": float(np.sqrt(np.mean(p_hat[idx] * (1 - p_hat[idx]) / N[idx]))),
                                "coverage95": float(covered[idx].mean())}
    labels = [e.label for e in exps]
    out["by_label"] = {}
    for lab in sorted(set(labels)):
        idx = np.array([i for i, l_ in enumerate(labels) if l_ == lab])
        out["by_label"][lab] = {"n": int(idx.size), "rmse": float(np.sqrt(np.mean(resid[idx] ** 2))),
                                "coverage95": float(covered[idx].mean()),
                                "mean_z": float(np.mean(z[idx]))}
    return out


def fitted_noise_model(fit: FitResult, T1: float | None = None) -> NoiseModel:
    """NoiseModel (MLE point estimate) for the simulator/optimizer, with the fit's fixed cutoffs.

    ``T1`` defaults to the value the fit treated as known. SPAM is not part of the noise model.
    """
    spec = _spec_of(fit)
    q = dict(zip(fit.param_names, fit.params))
    al = q.get("alpha", spec.alpha)
    comps = [noise_mod.make_one_over_f(q["A_ref"] * spec.omega_ref**al, al, spec.omega_low, spec.omega_high),
             noise_mod.make_white(q["S0"], spec.omega_high_white)]
    if spec.model_name == "full":
        comps.append(noise_mod.make_lorentzian(q["sigma"], q["tau_c"]))
    nm = NoiseModel(components=tuple(comps), T1=spec.T1 if T1 is None else float(T1),
                    metadata={"source": "ddopt.spectroscopy.fitted_noise_model", "model_name": spec.model_name,
                              "fit_success": fit.success, "synthetic": True})
    nm.validate()
    return nm


# ---------------------------------------------------------------------------
# Pipeline (Scenario A spectroscopy study)
# ---------------------------------------------------------------------------


def _merge_datasets(dss: list[dict]) -> tuple[dict, dict[str, list[int]]]:
    out = {"label": "+".join(d["label"] for d in dss), "experiments": [], "shots": [], "counts": [], "p_obs": [],
           "truth": [d["truth"] for d in dss], "calibration": dss[0]["calibration"]}
    groups = {}
    for d in dss:
        i0 = len(out["counts"])
        for key in ("experiments", "shots", "counts", "p_obs"):
            out[key] += list(d[key])
        groups[d["label"]] = list(range(i0, len(out["counts"])))
    return out, groups


def _seed_triplets(cfg: dict, seeds) -> list[dict]:
    if seeds is None:
        s = cfg["seeds"]["spectroscopy"]
        return [{"train": int(s["train"]), "heldout": int(s["heldout"]), "bootstrap": int(s["bootstrap"])}]
    out = []
    for s in seeds:
        if isinstance(s, dict):
            out.append({k: int(s[k]) for k in ("train", "heldout", "bootstrap")})
        else:
            out.append({"train": int(s), "heldout": int(s) + 1_000_000, "bootstrap": int(s) + 2_000_000})
    return out


def _summ(fr: FitResult, truth_params: dict, truth_t2: dict) -> dict:
    d = fr.to_dict()
    d["provenance"] = {k: v for k, v in d["provenance"].items() if k != "bootstrap_x"}
    rec = {}
    for n, v, l_, h_ in zip(fr.param_names, fr.params, fr.param_ci_low, fr.param_ci_high):
        tv = truth_params.get(n)
        rec[n] = {"fit": v, "ci95": [l_, h_], "truth": tv,
                  "truth_in_ci": (None if tv is None or not (math.isfinite(l_) and math.isfinite(h_))
                                  else bool(l_ <= tv <= h_))}
    d["param_vs_truth"] = rec
    t2 = {}
    for key, tv in truth_t2.items():
        fv = fr.derived.get(key, {})
        ci = fv.get("ci95_s")
        t2[key] = {"fit_s": fv.get("value_s"), "ci95_s": ci, "truth_s": tv,
                   "truth_in_ci": None if ci is None else bool(ci[0] <= tv <= ci[1])}
    d["t2_vs_truth"] = t2
    return d


def _truth_params(noise: NoiseModel, spam, omega_ref: float) -> dict:
    out = {"spam_hi": spam[0] + spam[1], "spam_mid": spam[0] + 0.5 * spam[1], "spam_a": spam[0], "spam_b": spam[1]}
    for c in noise.components:
        if c.kind == "one_over_f":
            out["alpha"] = c.params["alpha"]
            out["A_ref"] = c.params["A"] / omega_ref ** c.params["alpha"]
        elif c.kind == "white":
            out["S0"] = c.params["S0"]
        elif c.kind in ("lorentzian", "telegraph"):
            out["sigma"], out["tau_c"] = noise_mod.lorentzian_equivalent(c)
    return out


def run_pipeline(cfg: dict, seeds=None, n_boot: int = 200, *, shots: int = 1000, spam=DEFAULT_SPAM,
                 n_starts: int = 8, fits: Sequence[tuple[str, bool]] = (("reduced", False), ("full", False), ("full", True)),
                 misspec_fits: Sequence[tuple[str, bool]] = (("reduced", False), ("full", False)),
                 design_kw: dict | None = None) -> dict:
    """Full synthetic Scenario A spectroscopy study (JSON-friendly dict).

    Truths: (1) ``gaussian`` = Scenario A noise from ``cfg``; (2) ``telegraph`` = the Lorentzian
    replaced by symmetric telegraph noise with b = sigma, gamma = 1/(2 tau_c) (same second-order
    statistics, non-Gaussian; data generated with the exact transfer-matrix method).
    For each repeat (``seeds``: list of ints or {train, heldout, bootstrap} dicts; default = the
    config's spectroscopy seeds) and truth: simulate train and held-out data with independent
    generators, fit each model in ``fits`` (``(model_name, fit_alpha)``), score on held-out data.
    """
    from .scenarios import scenario_noise  # local import: lead-owned module

    t_start = time.perf_counter()
    noise_g = scenario_noise(cfg)
    comps = []
    for c in noise_g.components:
        if c.kind == "lorentzian":
            sig, tc = noise_mod.lorentzian_equivalent(c)
            comps.append(noise_mod.make_telegraph(sig, 1.0 / (2.0 * tc)))
        else:
            comps.append(c)
    noise_t = dataclasses.replace(noise_g, components=tuple(comps))
    cutoffs = {}
    for c in noise_g.components:
        if c.kind == "one_over_f":
            cutoffs.update(omega_low=c.omega_low, omega_high=c.omega_high)
        if c.kind == "white":
            cutoffs["omega_high_white"] = c.omega_high
    design = default_design(shots=shots, **(design_kw or {}))
    truths = {"gaussian": (noise_g, "analytic", fits), "telegraph": (noise_t, "exact", misspec_fits)}
    out: dict[str, Any] = {
        "description": "Synthetic spectroscopy study on Scenario A (ALL DATA SYNTHETIC; no hardware).",
        "config_path": cfg.get("_path"),
        "design": {"shots_per_point": shots, "times_train_s": design["times_train"],
                   "times_unseen_s": design["times_unseen"],
                   "train": "ramsey, hahn(X), cpmg2(Y), cpmg4(Y) at times_train",
                   "heldout_new_n": "cpmg8, cpmg16 at times_train + times_unseen",
                   "heldout_new_T": "ramsey, hahn, cpmg2, cpmg4 at times_unseen",
                   "pulses": "instantaneous", "spam_truth": list(spam),
                   "n_train": len(design["train"]),
                   "n_heldout": len(design["heldout_new_n"]) + len(design["heldout_new_T"])},
        "fit_settings": {"n_boot": n_boot, "n_starts": n_starts, "spam": "fit jointly",
                         "T1": "known (= truth)", "cutoffs_fixed": cutoffs, "omega_ref": DEFAULT_OMEGA_REF,
                         "alpha_fixed": 1.0, "bounds": DEFAULT_BOUNDS},
        "repeats": [],
    }
    for st in _seed_triplets(cfg, seeds):
        rep: dict[str, Any] = {"seeds": st, "truths": {}}
        for tname, (nm, method, fitlist) in truths.items():
            t0 = time.perf_counter()
            # independent generators per truth/repeat; train and heldout never share a generator
            r_tr = np.random.default_rng([st["train"], hash_name(tname)])
            r_te = np.random.default_rng([st["heldout"], hash_name(tname)])
            ds_tr = simulate_dataset(nm, design["train"], spam=spam, rng=r_tr, method=method, label="train")
            d1 = simulate_dataset(nm, design["heldout_new_n"], spam=spam, rng=r_te, method=method, label="heldout_new_n")
            d2 = simulate_dataset(nm, design["heldout_new_T"], spam=spam, rng=r_te, method=method, label="heldout_new_T")
            ds_te, groups = _merge_datasets([d1, d2])
            tp = _truth_params(nm, spam, DEFAULT_OMEGA_REF)
            tt2 = truth_t2(nm, "exact")
            entry = {"truth_noise": ds_tr["truth"]["noise"], "data_method": method, "truth_params": tp,
                     "truth_T2": tt2, "fits": {}}
            for model_name, fa in fitlist:
                key = model_name + ("_alpha_free" if fa else "_alpha1")
                tf = time.perf_counter()
                fr = fit(ds_tr, model_name, n_boot=n_boot, n_starts=n_starts, fit_alpha=fa,
                         rng=np.random.default_rng([st["bootstrap"], hash_name(tname + key)]), **cutoffs)
                score = score_heldout(fr, ds_te, groups=groups)
                fr.heldout_rmse = score["rmse"]
                fr.heldout_coverage = score["coverage95"]
                fr.derived["heldout"] = score
                s = _summ(fr, tp, tt2)
                s["runtime_s"] = time.perf_counter() - tf
                entry["fits"][key] = s
            entry["runtime_s"] = time.perf_counter() - t0
            rep["truths"][tname] = entry
        out["repeats"].append(rep)
    out["runtime_s"] = time.perf_counter() - t_start
    return _jsonable(out)


def hash_name(s: str) -> int:
    """Stable small integer from a string (for seeding sub-streams; Python's hash() is salted)."""
    return int(hashlib.sha256(s.encode()).hexdigest()[:8], 16)
