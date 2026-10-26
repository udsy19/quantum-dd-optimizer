"""Toggling-frame switching functions, (generalized) filter functions and dephasing variance.

Conventions (``docs/PHYSICS_CONVENTIONS.md``, derivations in ``docs/PHYSICS.md``):

* Noise Hamiltonian ``H_n = (1/2) delta(t) sigma_z``; control propagator ``U_c(t)``.
* Toggling frame: ``U_c^dag sigma_z U_c = sum_a y_a(t) sigma_a``; ``y(t) = (y_x, y_y, y_z)`` is a unit
  vector inside [0, T] and 0 outside. Between ideal pi pulses ``y = (0, 0, +-1)``, starting at +1.
* ``Y_a(omega) = int_0^T y_a(t) exp(i omega t) dt`` (s); ``F(omega) = sum_a |Y_a|^2`` (s^2).
* ``chi = (1/2pi) int S2 F domega`` (rad^2). For instantaneous pi pulses ``chi = Var(phi)`` exactly
  and ``W = exp(-chi/2)`` is exact for Gaussian noise. For finite pulses the generalized filter
  function gives chi to leading (second) order in the noise (first-order Magnus), and
  ``W = exp(-chi/2)`` is then a leading-order approximation.

Time unit s, angular frequency rad/s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import integrate, linalg

from .contracts import NoiseModel, PSDComponent, PulseSequence
from .noise import _components, _psd_one, lorentzian_equivalent

__all__ = [
    "toggling_vector",
    "switching_function",
    "fourier_toggling",
    "filter_function",
    "dephasing_variance",
    "coherence",
    "dephasing_infidelity",
    "telegraph_coherence_exact",
    "rotation_matrix",
]

_Z = np.array([0.0, 0.0, 1.0])


def rotation_matrix(axis: np.ndarray, theta: float) -> np.ndarray:
    """SO(3) matrix of a rotation by ``theta`` (rad) about unit ``axis`` (Rodrigues).

    ``exp(-i theta n.sigma/2) sigma_v exp(+i theta n.sigma/2) = sigma_{R v}``.
    """
    n = np.asarray(axis, dtype=float)
    K = np.array([[0, -n[2], n[1]], [n[2], 0, -n[0]], [-n[1], n[0], 0]])
    return math.cos(theta) * np.eye(3) + math.sin(theta) * K + (1 - math.cos(theta)) * np.outer(n, n)


@dataclass(frozen=True)
class _Seg:
    """y(t) = u_c * cos(Om (t - s)) + u_s * sin(Om (t - s)) on [s, e]; Om = 0 means constant u_c."""

    s: float
    e: float
    om: float
    u_c: np.ndarray
    u_s: np.ndarray

    def y_at(self, t: np.ndarray) -> np.ndarray:
        th = self.om * (np.asarray(t) - self.s)
        return np.outer(self.u_c, np.cos(th)) + np.outer(self.u_s, np.sin(th))


def _segments(seq: PulseSequence) -> list[_Seg]:
    seq.validate()
    R = np.eye(3)
    segs: list[_Seg] = []
    prev = 0.0
    zero = np.zeros(3)
    for c, w, ph, th in zip(seq.centers, seq.widths, seq.phases, seq.angles):
        start, end = c - w / 2, c + w / 2
        if start > prev:
            segs.append(_Seg(prev, start, 0.0, R.T @ _Z, zero))
        n = np.array([math.cos(ph), math.sin(ph), 0.0])
        if w > 0:
            segs.append(_Seg(start, end, th / w, R.T @ _Z, R.T @ np.array([-math.sin(ph), math.cos(ph), 0.0])))
        R = rotation_matrix(n, th) @ R
        prev = max(prev, end)
    if seq.T > prev:
        segs.append(_Seg(prev, seq.T, 0.0, R.T @ _Z, zero))
    return segs


def toggling_vector(seq: PulseSequence, t: np.ndarray) -> np.ndarray:
    """(3, len(t)) toggling-frame vector ``y(t)`` (dimensionless); zero outside [0, T]."""
    t = np.atleast_1d(np.asarray(t, dtype=float))
    out = np.zeros((3, t.size))
    segs = _segments(seq)
    for i, sg in enumerate(segs):
        last = i == len(segs) - 1
        m = (t >= sg.s) & ((t <= sg.e) if last else (t < sg.e))
        if m.any():
            out[:, m] = sg.y_at(t[m])
    return out


def switching_function(seq: PulseSequence, t: np.ndarray) -> np.ndarray:
    """``y_z(t)``: +-1 between ideal pi pulses (starting at +1), ``+-cos(theta(t))`` during a finite
    equatorial pulse (theta = rotation angle accumulated within the pulse); 0 outside [0, T]."""
    return toggling_vector(seq, t)[2]


def _E(nu: np.ndarray, w: float) -> np.ndarray:
    """int_0^w exp(i nu u) du, numerically stable for nu -> 0."""
    return w * np.exp(0.5j * nu * w) * np.sinc(nu * w / (2 * math.pi))


def _fourier_segs(segs: list[_Seg], omega: np.ndarray) -> np.ndarray:
    Y = np.zeros((3, omega.size), dtype=complex)
    for sg in segs:
        w = sg.e - sg.s
        ph = np.exp(1j * omega * sg.s)
        if sg.om == 0.0:
            Y += np.outer(sg.u_c, ph * _E(omega, w))
        else:
            Ep, Em = _E(omega + sg.om, w), _E(omega - sg.om, w)
            Y += np.outer(sg.u_c, ph * 0.5 * (Ep + Em)) + np.outer(sg.u_s, ph * (Ep - Em) / 2j)
    return Y


def fourier_toggling(seq: PulseSequence, omega: np.ndarray) -> np.ndarray:
    """(3, len(omega)) complex ``Y_a(omega) = int_0^T y_a(t) e^{i omega t} dt`` (s), closed form."""
    om = np.atleast_1d(np.asarray(omega, dtype=float))
    return _fourier_segs(_segments(seq), om)


def filter_function(seq: PulseSequence, omega: np.ndarray) -> np.ndarray:
    """Generalized filter function ``F(omega) = sum_{a=x,y,z} |Y_a(omega)|^2`` (s^2).

    For instantaneous pi pulses only the z component is nonzero, and this is the standard
    ``|Y(omega)|^2``. Closed form (no numerical integration) for any widths/phases/angles.
    """
    Y = fourier_toggling(seq, omega)
    F = (Y.real**2 + Y.imag**2).sum(0)
    return F if np.ndim(omega) else F[0]


# ---------------------------------------------------------------------------
# Dephasing variance: adaptive Gauss-Kronrod over omega + rigorous asymptotic tail
# ---------------------------------------------------------------------------

# QUADPACK qk15 abscissae/weights (nonnegative half) and embedded 7-point Gauss weights.
_XK = np.array([0.991455371120812639206854697526329, 0.949107912342758524526189684047851,
                0.864864423359769072789712788640926, 0.741531185599394439863864773280788,
                0.586087235467691130294144845693013, 0.405845151377397166906606412076961,
                0.207784955007898467600689403773245, 0.0])
_WK = np.array([0.022935322010529224963732008058970, 0.063092092629978553290700663189204,
                0.104790010322250183839876322541518, 0.140653259715525918745189590510238,
                0.169004726639267902826583426598550, 0.190350578064785409913256402421014,
                0.204432940075298892414161999234649, 0.209482141084727828012999174891714])
_WG = np.array([0.129484966168869693270611432679082, 0.279705391489276667901467771423780,
                0.381830050505118944950369775488975, 0.417959183673469387755102040816327])
_X15 = np.concatenate([-_XK[:-1], _XK[::-1]])
_W15 = np.concatenate([_WK[:-1], _WK[::-1]])
_W7 = np.zeros(15)
_W7[[1, 3, 5]] = _WG[:3]
_W7[[9, 11, 13]] = _WG[2::-1]
_W7[7] = _WG[3]


def _gk_panels(f, lo: np.ndarray, hi: np.ndarray, is_log: np.ndarray):
    """Gauss-Kronrod 15 (and embedded Gauss 7) on panels; log panels use u = ln(omega)."""
    a = np.where(is_log, np.log(np.where(is_log, lo, 1.0)), lo)
    b = np.where(is_log, np.log(np.where(is_log, hi, 1.0)), hi)
    half = 0.5 * (b - a)
    x = (0.5 * (a + b))[:, None] + half[:, None] * _X15[None, :]
    w = np.where(is_log[:, None], np.exp(np.where(is_log[:, None], x, 0.0)), x)
    jac = np.where(is_log[:, None], w, 1.0) * half[:, None]
    vals = f(w.ravel()).reshape(w.shape) * jac
    return vals @ _W15, vals @ _W7


def _adaptive(f, edges: list[tuple[float, float, bool]], tol_abs_fn, max_iter: int = 40,
              max_panels: int = 2_000_000):
    lo = np.array([e[0] for e in edges])
    hi = np.array([e[1] for e in edges])
    lg = np.array([e[2] for e in edges], dtype=bool)
    K, G = _gk_panels(f, lo, hi, lg)
    for _ in range(max_iter):
        err = np.abs(K - G)
        total = K.sum()
        tol = tol_abs_fn(total)
        if err.sum() <= tol or lo.size > max_panels:
            break
        bad = err > tol / lo.size
        if not bad.any():
            bad = err >= err.max()
        mid = np.where(lg[bad], np.sqrt(lo[bad] * hi[bad]), 0.5 * (lo[bad] + hi[bad]))
        nlo = np.concatenate([lo[bad], mid])
        nhi = np.concatenate([mid, hi[bad]])
        nlg = np.concatenate([lg[bad], lg[bad]])
        nK, nG = _gk_panels(f, nlo, nhi, nlg)
        keep = ~bad
        lo, hi, lg = np.concatenate([lo[keep], nlo]), np.concatenate([hi[keep], nhi]), np.concatenate([lg[keep], nlg])
        K, G = np.concatenate([K[keep], nK]), np.concatenate([G[keep], nG])
    return float(K.sum()), float(np.abs(K - G).sum()), int(lo.size)


def _jumps(segs: list[_Seg]):
    """Discontinuities of y(t): times tau_m and jump vectors J_m = y(tau+) - y(tau-)."""
    taus, Js = [], []
    prev_end_val = np.zeros(3)
    t_prev = None
    for sg in segs:
        start_val = sg.y_at(np.array([sg.s]))[:, 0]
        if t_prev is not None and abs(sg.s - t_prev) > 0:
            raise RuntimeError("segments not contiguous")  # pragma: no cover
        J = start_val - prev_end_val
        if np.linalg.norm(J) > 1e-13:
            taus.append(sg.s)
            Js.append(J)
        prev_end_val = sg.y_at(np.array([sg.e]))[:, 0]
        t_prev = sg.e
    taus.append(segs[-1].e)
    Js.append(-prev_end_val)
    # merge coincident times
    out_t, out_J = [], []
    for t, J in zip(taus, Js):
        if out_t and abs(t - out_t[-1]) < 1e-18:
            out_J[-1] = out_J[-1] + J
        else:
            out_t.append(t)
            out_J.append(J)
    return np.array(out_t), np.array(out_J)


def _psd_moment(c: PSDComponent, a: float, b: float, p: int) -> float:
    """int_a^b S2(w) w^{-p} dw (a > 0, b may be inf) via v = a/w on the finite interval [a/b, 1]."""
    if not b > a:
        return 0.0
    f = lambda v: float(_psd_one(c, np.array([a / v]))[0]) * v ** (p - 2) if v > 0 else 0.0  # noqa: E731
    val = integrate.quad(f, a / b, 1.0, limit=200, epsabs=0.0, epsrel=1e-11)[0]
    return a ** (1 - p) * val


def _chi_component(c: PSDComponent, seq: PulseSequence, segs: list[_Seg], rtol: float,
                   tail_factor: float, max_panels: int) -> tuple[float, float, dict]:
    T = seq.T
    a, b = c.omega_low, c.omega_high
    taus, Js = _jumps(segs)
    Jn = np.linalg.norm(Js, axis=1)
    D = float((Jn**2).sum())
    dmat = np.abs(taus[:, None] - taus[None, :])
    off = ~np.eye(taus.size, dtype=bool)
    d_min = float(dmat[off].min()) if taus.size > 1 else T
    om_max = max([abs(sg.om) for sg in segs] + [0.0])
    B1 = float(Jn.sum())
    # |Y - Y_asym| <= B2/w^2, B2 = sum |jumps of dy/dt| + int |d2y/dt2| = sum_k |Om_k| (2 + |theta_k|)
    B2 = float(sum(abs(sg.om) * (2.0 + abs(sg.om) * (sg.e - sg.s)) for sg in segs))
    S = lambda w: _psd_one(c, w)  # noqa: E731
    f = lambda w: S(w) * (lambda Y: (Y.real**2 + Y.imag**2).sum(0))(_fourier_segs(segs, w)) / math.pi  # noqa: E731

    w1 = 2 * math.pi / T
    scale = [w1]
    if c.kind in ("lorentzian", "telegraph"):
        scale.append(1.0 / lorentzian_equivalent(c)[1])
    w_floor = 1e-6 * min(scale)
    h = math.pi / T
    chi = err = 0.0
    info: dict = {}
    for attempt in range(6):
        wt = max(tail_factor * 2 * math.pi / d_min, 5.0 * om_max, 4 * w1) * 4.0**attempt
        if attempt > 0 and (min(b, wt) - max(a, w1)) / h > max_panels:
            info["tail_refinement_capped"] = True
            break
        top = min(b, wt)
        edges: list[tuple[float, float, bool]] = []
        if top > a:
            lo = a
            if lo < w_floor:
                edges.append((lo, w_floor, False))
                lo = w_floor
            if lo < w1 and top > lo:
                hi = min(w1, top)
                npan = max(1, int(math.ceil(4 * math.log10(hi / lo))))
                ed = np.geomspace(lo, hi, npan + 1)
                edges += [(x, y, True) for x, y in zip(ed[:-1], ed[1:])]
                lo = hi
            if top > lo:
                npan = int(math.ceil((top - lo) / h))
                npan = min(npan, max_panels)
                ed = np.linspace(lo, top, npan + 1)
                edges += [(x, y, False) for x, y in zip(ed[:-1], ed[1:])]
        chi_p, err_p, npan_used = (0.0, 0.0, 0)
        if edges:
            chi_p, err_p, npan_used = _adaptive(f, edges, lambda tot: 0.5 * rtol * abs(tot) + 1e-300,
                                                max_panels=max_panels)
        tail = tail_err = 0.0
        if b > wt:
            ta = max(a, wt)
            g = lambda w: float(_psd_one(c, np.array([w]))[0])  # noqa: E731
            tail = D / math.pi * _psd_moment(c, ta, b, 2)
            # oscillatory cross terms: |int g cos(w d)| <= 2 g(ta)/d for monotone g = S2/w^2
            cross = 0.0
            if taus.size > 1:
                JJ = np.abs(Js @ Js.T)
                cross = float((JJ[off] / dmat[off]).sum()) * 2 * g(ta) / ta**2 / math.pi
            fin = 0.0
            if B2 > 0:
                fin = (2 * B1 * B2 * _psd_moment(c, ta, b, 3) + B2**2 * _psd_moment(c, ta, b, 4)) / math.pi
            tail_err = cross + fin
        chi, err = chi_p + tail, err_p + tail_err
        info = dict(omega_tail=wt, n_panels=npan_used, tail=tail, tail_err=tail_err, quad_err=err_p)
        if tail_err <= 0.5 * rtol * abs(chi) or b <= wt:
            break
    return chi, err, info


def dephasing_variance(noise: NoiseModel | PSDComponent, seq: PulseSequence, *, rtol: float = 1e-6,
                       tail_factor: float = 50.0, max_panels: int = 200_000,
                       return_info: bool = False):
    """``(chi, err)``: ``chi = (1/2pi) int_{-inf}^{inf} S2(omega) F(omega) domega`` (rad^2), with an
    error estimate ``err`` (rad^2) = sum of |GK15 - G7| panel differences + a rigorous bound on the
    asymptotic tail approximation.

    Integration per component over its own [omega_low, omega_high]: a linear panel [0, omega_floor],
    log panels up to 2pi/T (handles 1/omega^alpha and peaked low-frequency spectra), linear panels of
    width pi/T (resolving the e^{i omega T} oscillation) up to ``omega_tail``, each refined
    adaptively; above ``omega_tail = max(tail_factor 2pi/d_min, 5 Omega_max) * 4^k`` (k raised until
    the tail bound is below rtol/2, subject to ``max_panels``) the exact
    asymptotic ``F -> sum_m |J_m|^2 / omega^2`` (J_m: jumps of y) is integrated against S2, with the
    oscillatory cross terms and finite-pulse corrections bounded and added to ``err``.

    Telegraph components enter via their Lorentzian-equivalent PSD (Gaussian approximation).
    ``return_info=True`` appends a per-component diagnostics list.
    """
    comps = _components(noise)
    segs = _segments(seq)
    chi = err = 0.0
    infos = []
    for c in comps:
        x, e, info = _chi_component(c, seq, segs, rtol, tail_factor, max_panels)
        chi += x
        err += e
        infos.append(info)
    return (chi, err, infos) if return_info else (chi, err)


def coherence(noise: NoiseModel | PSDComponent, seq: PulseSequence, **kw) -> float:
    """``W = exp(-chi/2)`` (Gaussian assumption; exact for instantaneous pi pulses)."""
    return math.exp(-0.5 * dephasing_variance(noise, seq, **kw)[0])


def dephasing_infidelity(noise: NoiseModel | PSDComponent, seq: PulseSequence, **kw) -> float:
    """Pure-dephasing average gate infidelity ``r = (1 - W)/3`` (no T1, target = ideal control)."""
    chi = dephasing_variance(noise, seq, **kw)[0]
    return -math.expm1(-0.5 * chi) / 3.0


def telegraph_coherence_exact(component: PSDComponent, seq: PulseSequence) -> float:
    """Exact ``W = <exp(i int delta y_z dt)>`` for symmetric random telegraph noise (stationary start),
    for sequences whose toggling vector stays along z (instantaneous pi pulses about equatorial axes).

    Uses the 2-state transfer matrix ``prod_k expm((Q + i b y_k diag(1, -1)) Delta_k)`` with generator
    ``Q = gamma [[-1, 1], [1, -1]]``. Not Gaussian: differs from ``exp(-chi/2)`` unless b tau_c << 1.
    """
    if component.kind != "telegraph":
        raise ValueError("telegraph component required")
    b, g = component.params["b"], component.params["gamma"]
    segs = _segments(seq)
    Q = g * np.array([[-1.0, 1.0], [1.0, -1.0]])
    Zd = np.diag([1.0, -1.0])
    v = np.array([0.5, 0.5], dtype=complex)
    for sg in segs:
        if sg.om != 0.0 or abs(sg.u_c[0]) > 1e-12 or abs(sg.u_c[1]) > 1e-12:
            raise ValueError("exact telegraph coherence requires instantaneous pulses keeping y along z")
        v = linalg.expm((Q + 1j * b * sg.u_c[2] * Zd) * (sg.e - sg.s)) @ v
    return float(v.sum().real)
