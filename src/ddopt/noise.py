"""Stationary dephasing-noise models: PSDs, variances, autocovariances and trajectory sampling.

Conventions (binding, see ``docs/PHYSICS_CONVENTIONS.md`` and ``docs/PHYSICS.md``):

* ``delta(t)`` is the stochastic qubit-frequency fluctuation in rad/s, zero mean, stationary.
* ``C(tau) = <delta(t + tau) delta(t)>`` in rad^2/s^2.
* Two-sided PSD ``S2(omega) = int C(tau) exp(-i omega tau) dtau`` in rad^2/s, even in omega,
  so ``C(tau) = (1/2pi) int S2(omega) exp(i omega tau) domega = (1/pi) int_0^inf S2 cos(omega tau)``.
* Hard cutoffs: ``S2(omega) = 0`` unless ``omega_low <= |omega| <= omega_high``.

Sampling methods used by :func:`sample_detuning` (bias quantified by
:func:`synthesized_autocovariance`, see ``docs/PHYSICS.md`` section 6):

* ``lorentzian`` with no cutoffs: exact Ornstein-Uhlenbeck recursion (grid samples have exactly
  ``C(k dt) = sigma^2 exp(-k dt / tau_c)``, aliasing included).
* ``telegraph`` with no cutoffs: exact Markov jump sampling on the grid (stationary start).
* every other Gaussian component (and Lorentzians with cutoffs): *hybrid spectral synthesis*,
  band-limited to the grid Nyquist frequency ``pi/dt``. The spectrum is split with a smooth
  (C-infinity) partition of unity at ``omega_s ~ 16-32 x 2pi/L``. The high part is synthesised by
  FFT on a periodic grid of length ``L = M dt`` (``M >= oversample * len(t)``), whose covariance
  is the exact ``L``-periodisation of the high-part covariance; the low part (which contains all
  content below ``2pi/T`` down to ``omega_low``) is synthesised by explicit random-phase
  sinusoids at composite Gauss-Legendre nodes (log-spaced panels below ``1/T``), so its
  covariance is a converged quadrature of the exact low-part covariance.
"""

from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
from scipy import integrate, signal

from .contracts import NoiseModel, PSDComponent

__all__ = [
    "psd",
    "noise_variance",
    "band_variance",
    "autocovariance",
    "sample_detuning",
    "synthesized_autocovariance",
    "make_one_over_f",
    "make_lorentzian",
    "make_white",
    "make_telegraph",
    "lorentzian_equivalent",
]

ComponentOrModel = PSDComponent | NoiseModel


# ---------------------------------------------------------------------------
# Constructors
# ---------------------------------------------------------------------------


def make_one_over_f(A: float, alpha: float, omega_low: float, omega_high: float) -> PSDComponent:
    """``S2 = A/|omega|^alpha`` on ``omega_low <= |omega| <= omega_high`` (rad/s); A in rad^2/s*(rad/s)^alpha."""
    c = PSDComponent("one_over_f", {"A": float(A), "alpha": float(alpha)}, float(omega_low), float(omega_high))
    c.validate()
    return c


def make_lorentzian(sigma: float, tau_c: float, omega_high: float = math.inf, *,
                    omega_low: float = 0.0) -> PSDComponent:
    """Gaussian OU noise, ``C = sigma^2 exp(-|tau|/tau_c)`` (sigma rad/s, tau_c s), optional cutoffs."""
    c = PSDComponent("lorentzian", {"sigma": float(sigma), "tau_c": float(tau_c)},
                     float(omega_low), float(omega_high))
    c.validate()
    return c


def make_white(S0: float, omega_high: float) -> PSDComponent:
    """Band-limited white noise ``S2 = S0`` (rad^2/s) for ``|omega| <= omega_high``."""
    c = PSDComponent("white", {"S0": float(S0)}, 0.0, float(omega_high))
    c.validate()
    return c


def make_telegraph(b: float, gamma: float) -> PSDComponent:
    """Symmetric random telegraph noise ``delta = +-b`` (rad/s), switching rate ``gamma`` (1/s) each way."""
    c = PSDComponent("telegraph", {"b": float(b), "gamma": float(gamma)})
    c.validate()
    return c


def lorentzian_equivalent(c: PSDComponent) -> tuple[float, float]:
    """(sigma, tau_c) of the Lorentzian with the same C(tau) as a lorentzian/telegraph component."""
    if c.kind == "lorentzian":
        return c.params["sigma"], c.params["tau_c"]
    if c.kind == "telegraph":
        g = c.params["gamma"]
        return c.params["b"], (math.inf if g == 0 else 1.0 / (2.0 * g))
    raise ValueError(f"{c.kind} has no Lorentzian equivalent")


def _components(x: ComponentOrModel) -> tuple[PSDComponent, ...]:
    if isinstance(x, PSDComponent):
        x.validate()
        return (x,)
    if isinstance(x, NoiseModel):
        x.validate()
        return tuple(x.components)
    raise TypeError(f"expected PSDComponent or NoiseModel, got {type(x).__name__}")


# ---------------------------------------------------------------------------
# PSD, band variance, autocovariance
# ---------------------------------------------------------------------------


def _psd_one(c: PSDComponent, w: np.ndarray) -> np.ndarray:
    """Two-sided PSD of one component at |omega| = w >= 0 (rad^2/s), cutoffs applied."""
    p = c.params
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        if c.kind == "one_over_f":
            s = p["A"] * np.power(np.where(w > 0, w, 1.0), -p["alpha"])
        elif c.kind in ("lorentzian", "telegraph"):
            sigma, tau_c = lorentzian_equivalent(c)
            if math.isinf(tau_c):  # static limit: delta-function at 0, not representable
                raise ValueError("tau_c = inf (gamma = 0) gives a singular PSD")
            s = 2.0 * sigma**2 * tau_c / (1.0 + (w * tau_c) ** 2)
        elif c.kind == "white":
            s = np.full_like(w, p["S0"])
        else:  # pragma: no cover - guarded by validate
            raise ValueError(c.kind)
    inside = (w >= c.omega_low) & (w <= c.omega_high)
    return np.where(inside, s, 0.0)


def psd(component_or_model: ComponentOrModel, omega: np.ndarray) -> np.ndarray:
    """Two-sided PSD ``S2(omega)`` in rad^2/s; even, nonnegative, cutoffs honoured.

    A ``NoiseModel`` returns the sum of its components (telegraph components contribute their
    Lorentzian-equivalent PSD, which is exact for second-order statistics only).
    """
    w = np.abs(np.asarray(omega, dtype=float))
    out = np.zeros_like(w)
    for c in _components(component_or_model):
        out = out + _psd_one(c, w)
    return out


def _band_variance_one(c: PSDComponent, w1: float, w2: float) -> float:
    """(1/pi) int_{w1}^{w2} S2 domega over positive frequencies, analytic (rad^2/s^2)."""
    a = max(w1, c.omega_low)
    b = min(w2, c.omega_high)
    if not b > a:
        return 0.0
    p = c.params
    if c.kind == "one_over_f":
        A, al = p["A"], p["alpha"]
        k = 1.0 - al
        lr = math.log(b / a)
        if abs(k * lr) < 1e-12:
            return A / math.pi * a**k * lr
        return A / math.pi * a**k * math.expm1(k * lr) / k
    if c.kind in ("lorentzian", "telegraph"):
        sigma, tau_c = lorentzian_equivalent(c)
        ub = math.pi / 2 if math.isinf(b) else math.atan(b * tau_c)
        return 2.0 * sigma**2 / math.pi * (ub - math.atan(a * tau_c))
    if c.kind == "white":
        return p["S0"] * (b - a) / math.pi
    raise ValueError(c.kind)  # pragma: no cover


def band_variance(component_or_model: ComponentOrModel, w1: float, w2: float) -> float:
    """Variance carried by ``w1 <= |omega| <= w2``: ``(1/pi) int_{w1}^{w2} S2 domega`` (rad^2/s^2)."""
    return float(sum(_band_variance_one(c, w1, w2) for c in _components(component_or_model)))


def noise_variance(component_or_model: ComponentOrModel) -> float:
    """``<delta^2> = C(0) = (1/2pi) int S2 domega`` in rad^2/s^2 (analytic for all kinds)."""
    return band_variance(component_or_model, 0.0, math.inf)


def _autocov_one(c: PSDComponent, tau: float) -> float:
    tau = abs(float(tau))
    if tau == 0.0:
        return _band_variance_one(c, 0.0, math.inf)
    if c.kind in ("lorentzian", "telegraph") and c.omega_low == 0 and math.isinf(c.omega_high):
        sigma, tau_c = lorentzian_equivalent(c)
        return sigma**2 * math.exp(-tau / tau_c)
    if c.kind == "white":
        return c.params["S0"] / math.pi * math.sin(c.omega_high * tau) / tau
    # general: (1/pi) int_a^b S2(w) cos(w tau) dw with QUADPACK QAWO/QAWF
    a, b = c.omega_low, c.omega_high
    f = lambda w: float(_psd_one(c, np.array([w]))[0])  # noqa: E731
    if c.kind == "one_over_f":
        # integrate in panels to keep QAWO accurate across many decades
        edges = np.geomspace(a, b, max(2, int(math.ceil(math.log10(b / a))) + 1))
        tot = 0.0
        for lo, hi in zip(edges[:-1], edges[1:]):
            v, _ = integrate.quad(f, lo, hi, weight="cos", wvar=tau, limit=400)
            tot += v
        return tot / math.pi
    sigma, tau_c = lorentzian_equivalent(c)
    g = lambda w: 2.0 * sigma**2 * tau_c / (1.0 + (w * tau_c) ** 2)  # noqa: E731
    # C_cut = C_full - (1/pi) int_0^a g cos - (1/pi) int_b^inf g cos  (both pieces smooth/monotone)
    full = sigma**2 * math.exp(-tau / tau_c)
    low = 0.0
    if a > 0:
        n = max(1, int(math.ceil(a * tau / math.pi)))  # panels of <= half a period
        ed = np.linspace(0.0, a, min(n, 2000) + 1)
        low = sum(integrate.quad(g, lo, hi, weight="cos", wvar=tau, limit=200)[0]
                  for lo, hi in zip(ed[:-1], ed[1:]))
    high = 0.0
    if not math.isinf(b):
        # int_b^inf g cos(w tau) after two integrations by parts (QAWF on g'' ~ w^-4 is well behaved):
        # = -g(b) sin(b tau)/tau - g'(b) cos(b tau)/tau^2 - (1/tau^2) int_b^inf g'' cos(w tau) dw
        gp = lambda w: -4.0 * sigma**2 * tau_c**3 * w / (1.0 + (w * tau_c) ** 2) ** 2  # noqa: E731
        gpp = lambda w: (-4.0 * sigma**2 * tau_c**3 * (1.0 - 3.0 * (w * tau_c) ** 2)  # noqa: E731
                         / (1.0 + (w * tau_c) ** 2) ** 3)
        rem = integrate.quad(gpp, b, math.inf, weight="cos", wvar=tau, limlst=200)[0]
        high = -g(b) * math.sin(b * tau) / tau - gp(b) * math.cos(b * tau) / tau**2 - rem / tau**2
    return full - (low + high) / math.pi


def autocovariance(component_or_model: ComponentOrModel, tau: np.ndarray | float) -> np.ndarray:
    """Exact (analytic or QUADPACK-oscillatory-quadrature) ``C(tau)`` in rad^2/s^2."""
    comps = _components(component_or_model)
    taus = np.atleast_1d(np.asarray(tau, dtype=float))
    out = np.array([sum(_autocov_one(c, x) for c in comps) for x in taus.ravel()]).reshape(taus.shape)
    return out if np.ndim(tau) else out[0]


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

_GL8_X, _GL8_W = np.polynomial.legendre.leggauss(8)


def _smooth_step(x: np.ndarray) -> np.ndarray:
    """C-infinity step: 1 for x <= 0, 0 for x >= 1."""
    x = np.clip(x, 0.0, 1.0)
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        f1 = np.where(x < 1, np.exp(-1.0 / np.where(x < 1, 1.0 - x, 1.0)), 0.0)
        f0 = np.where(x > 0, np.exp(-1.0 / np.where(x > 0, x, 1.0)), 0.0)
        s = f1 / (f1 + f0)
    return np.where(x <= 0, 1.0, np.where(x >= 1, 0.0, s))


def _check_grid(t: np.ndarray) -> tuple[int, float]:
    t = np.asarray(t, dtype=float)
    if t.ndim != 1 or t.size < 2:
        raise ValueError("t must be a 1-D uniform grid with at least 2 points")
    dts = np.diff(t)
    dt = float(dts.mean())
    if not dt > 0 or np.max(np.abs(dts - dt)) > 1e-9 * dt + 1e-18:
        raise ValueError("t must be uniformly spaced and increasing")
    return t.size, dt


def _method(c: PSDComponent, requested: str) -> str:
    natural = c.omega_low == 0 and math.isinf(c.omega_high)
    if c.kind == "telegraph":
        if not natural:
            raise ValueError("telegraph sampling is exact Markov jumps; cutoffs cannot be honoured "
                             "(use omega_low=0, omega_high=inf)")
        return "telegraph"
    if requested == "spectral":
        return "spectral"
    if requested not in ("auto", "ou"):
        raise ValueError("method must be 'auto', 'ou' or 'spectral'")
    if c.kind == "lorentzian" and natural:
        return "ou"
    if requested == "ou":
        raise ValueError("method='ou' requires a lorentzian component without cutoffs")
    return "spectral"


class _SpectralPlan:
    """Deterministic description of the hybrid spectral synthesis for given comps and grid."""

    def __init__(self, comps: list[PSDComponent], N: int, dt: float, oversample: int, kappa: float):
        self.comps = comps
        self.N, self.dt = N, dt
        self.M = int(2 ** math.ceil(math.log2(max(16, oversample * N))))
        L = self.M * dt
        self.dw = 2 * math.pi / L
        self.wN = math.pi / dt
        tau_max = (N - 1) * dt
        wa = min(kappa * self.dw, 0.25 * self.wN)
        wb = min(2 * wa, 0.5 * self.wN)
        self.wa, self.wb = wa, wb
        S = lambda w: sum(_psd_one(c, np.abs(w)) for c in comps)  # noqa: E731
        P = lambda w: _smooth_step((w - wa) / (wb - wa))  # noqa: E731
        # --- FFT band: point weights of S*(1-P) at j*dw, j = 1..M/2-1 (Nyquist bin dropped)
        j = np.arange(self.M // 2 + 1)
        wj = j * self.dw
        wts = S(wj) * (1.0 - P(wj)) * self.dw / math.pi
        wts[0] = 0.0
        wts[-1] = 0.0
        self.fft_w = wts
        # --- low band: composite Gauss-Legendre for (1/pi) int S P cos(w tau) dw on [lo, wb]
        lo = min(c.omega_low for c in comps)
        hi = min(wb, max(c.omega_high for c in comps))
        nodes: list[np.ndarray] = []
        weights: list[np.ndarray] = []
        self.zero_mode_var = 0.0
        if hi > lo:
            w_log_top = min(hi, 1.0 / tau_max)
            w_floor = lo if lo > 0 else min(1e-6 / tau_max, 0.5 * w_log_top)
            if lo == 0:
                x = 0.5 * w_floor * (_GL8_X + 1)
                self.zero_mode_var = float(np.sum(0.5 * w_floor * _GL8_W * S(x) * P(x)) / math.pi)
            bps = {w_floor, w_log_top, hi}
            for c in comps:
                for e in (c.omega_low, c.omega_high):
                    if w_floor < e < hi:
                        bps.add(e)
            bps_arr = np.array(sorted(b for b in bps if w_floor <= b <= hi))
            h_lin = math.pi / (2 * tau_max)
            for a, b in zip(bps_arr[:-1], bps_arr[1:]):
                if b <= w_log_top * (1 + 1e-12):  # log panels, 3 per decade
                    npan = max(1, int(math.ceil(3 * math.log10(b / a))))
                    ed = np.geomspace(a, b, npan + 1)
                    for p0, p1 in zip(ed[:-1], ed[1:]):
                        u0, u1 = math.log(p0), math.log(p1)
                        u = 0.5 * (u1 - u0) * (_GL8_X + 1) + u0
                        x = np.exp(u)
                        nodes.append(x)
                        weights.append(0.5 * (u1 - u0) * _GL8_W * x)
                else:
                    npan = max(1, int(math.ceil((b - a) / h_lin)))
                    ed = np.linspace(a, b, npan + 1)
                    for p0, p1 in zip(ed[:-1], ed[1:]):
                        nodes.append(0.5 * (p1 - p0) * (_GL8_X + 1) + p0)
                        weights.append(0.5 * (p1 - p0) * _GL8_W)
        if nodes:
            x = np.concatenate(nodes)
            v = np.concatenate(weights) * S(x) * P(x) / math.pi
            keep = v > 0
            self.low_w, self.low_v = x[keep], v[keep]
        else:
            self.low_w, self.low_v = np.zeros(0), np.zeros(0)

    def covariance(self) -> np.ndarray:
        k = np.arange(self.N)
        c_fft = 0.5 * self.M * np.fft.irfft(self.fft_w, n=self.M)[: self.N]
        c_low = (self.low_v[:, None] * np.cos(np.outer(self.low_w, k * self.dt))).sum(0) if self.low_v.size else 0.0
        return c_fft + c_low + self.zero_mode_var

    def sample(self, n_traj: int, rng: np.random.Generator) -> np.ndarray:
        N, M = self.N, self.M
        out = np.empty((n_traj, N))
        amp = np.sqrt(self.fft_w)
        nz = np.nonzero(amp)[0]
        tk = np.arange(N) * self.dt
        if self.low_v.size:
            cosm = np.cos(np.outer(self.low_w, tk))
            sinm = np.sin(np.outer(self.low_w, tk))
            sv = np.sqrt(self.low_v)
        chunk = max(1, min(n_traj, int(2**23 // M)))
        for s in range(0, n_traj, chunk):
            m = min(chunk, n_traj - s)
            x = np.zeros((m, N))
            if nz.size:
                g = rng.standard_normal((2, m, nz.size))
                spec = np.zeros((m, M // 2 + 1), dtype=complex)
                spec[:, nz] = amp[nz] * (g[0] - 1j * g[1]) * (0.5 * M)
                x += np.fft.irfft(spec, n=M, axis=1)[:, :N]
            if self.low_v.size:
                g = rng.standard_normal((2, m, self.low_v.size)) * sv
                x += g[0] @ cosm + g[1] @ sinm
            if self.zero_mode_var > 0:
                x += math.sqrt(self.zero_mode_var) * rng.standard_normal((m, 1))
            out[s:s + m] = x
        return out


def _spectral_comps(comps, method):
    return [c for c in comps if _method(c, method) == "spectral"]


def synthesized_autocovariance(model: ComponentOrModel, t: np.ndarray, *, method: str = "auto",
                               oversample: int = 8, kappa: float = 16.0) -> tuple[np.ndarray, dict[str, Any]]:
    """Exact covariance ``E[x_k x_0]`` (rad^2/s^2, lags k=0..N-1) of what :func:`sample_detuning`
    generates on grid ``t`` (no Monte-Carlo noise), plus diagnostics.

    Diagnostics: ``var_target`` (analytic noise variance), ``var_synth`` (= returned[0]),
    ``var_above_nyquist`` (analytic variance at |omega| > pi/dt, dropped by the spectral method,
    retained -- aliased -- by OU/telegraph), plan sizes. Compare with :func:`autocovariance` to
    quantify sampler bias.
    """
    comps = list(_components(model))
    N, dt = _check_grid(t)
    k = np.arange(N) * dt
    cov = np.zeros(N)
    info: dict[str, Any] = {"N": N, "dt": dt, "methods": [], "var_target": 0.0, "var_above_nyquist": 0.0}
    for c in comps:
        m = _method(c, method)
        info["methods"].append(m)
        info["var_target"] += noise_variance(c)
        if m in ("ou", "telegraph"):
            sigma, tau_c = lorentzian_equivalent(c)
            cov += sigma**2 * np.exp(-k / tau_c)
        else:
            info["var_above_nyquist"] += band_variance(c, math.pi / dt, math.inf)
    sc = _spectral_comps(comps, method)
    if sc:
        plan = _SpectralPlan(sc, N, dt, oversample, kappa)
        cov += plan.covariance()
        info.update(M=plan.M, omega_split=(plan.wa, plan.wb), n_low_modes=int(plan.low_v.size),
                    zero_mode_var=plan.zero_mode_var)
    info["var_synth"] = float(cov[0])
    return cov, info


def sample_detuning(model: NoiseModel, t: np.ndarray, n_traj: int, rng: np.random.Generator, *,
                    method: str = "auto", oversample: int = 8, kappa: float = 16.0) -> np.ndarray:
    """Stochastic ``delta(t)`` samples, shape ``(n_traj, len(t))``, rad/s, on uniform grid ``t`` (s).

    Excludes the deterministic ``model.detuning`` profile. Stationary and zero-mean; the time origin
    ``t[0]`` is irrelevant. Reproducible: all randomness comes from ``rng``; OU and telegraph
    components draw in component order, then all spectral components are synthesised jointly
    (their PSDs are summed), so results depend only on (model, t, n_traj, rng state, options).

    ``method``: ``"auto"`` (OU recursion for cutoff-free Lorentzians, spectral otherwise),
    ``"spectral"`` (force spectral synthesis for every Gaussian component) or ``"ou"``.
    Telegraph components are always exact Markov jump processes and must have no cutoffs.
    Spectral synthesis is band-limited to ``|omega| < pi/dt``; a ``RuntimeWarning`` is issued if more
    than 1 % of a spectral component's variance lies above Nyquist.
    """
    if not isinstance(model, NoiseModel):
        model = NoiseModel(components=tuple(_components(model)))
    model.validate()
    N, dt = _check_grid(t)
    n_traj = int(n_traj)
    out = np.zeros((n_traj, N))
    sc = []
    for c in model.components:
        m = _method(c, method)
        if m == "ou":
            sigma, tau_c = lorentzian_equivalent(c)
            a = math.exp(-dt / tau_c)
            e = rng.standard_normal((n_traj, N))
            e[:, 1:] *= sigma * math.sqrt(-math.expm1(-2 * dt / tau_c))
            e[:, 0] *= sigma
            out += signal.lfilter([1.0], [1.0, -a], e, axis=1)
        elif m == "telegraph":
            b, g = c.params["b"], c.params["gamma"]
            s0 = np.where(rng.random((n_traj, 1)) < 0.5, 1.0, -1.0)
            p_flip = -0.5 * math.expm1(-2 * g * dt)  # P(odd # of Poisson(g dt) jumps)
            flips = rng.random((n_traj, N - 1)) < p_flip
            par = np.concatenate([np.zeros((n_traj, 1), dtype=np.int64),
                                  np.cumsum(flips, axis=1, dtype=np.int64)], axis=1)
            out += b * s0 * (1 - 2 * (par & 1))
        else:
            frac = band_variance(c, math.pi / dt, math.inf) / max(noise_variance(c), 1e-300)
            if frac > 1e-2:
                warnings.warn(f"{c.kind}: {frac:.2%} of variance lies above Nyquist pi/dt and is dropped",
                              RuntimeWarning, stacklevel=2)
            sc.append(c)
    if sc:
        out += _SpectralPlan(sc, N, dt, oversample, kappa).sample(n_traj, rng)
    return out
