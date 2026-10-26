"""Finite-pulse Monte-Carlo simulator for a single qubit under dephasing noise (Agent B).

Model (``docs/PHYSICS_CONVENTIONS.md``; hbar = 1, s, rad/s, rad)::

    H(t) = 1/2 delta(t) sigma_z + 1/2 Omega(t) [cos phi(t) sigma_x + sin phi(t) sigma_y]

* ``delta(t)`` = stochastic noise + known deterministic profile ``noise.detuning(t)`` +
  unknown static ``control_errors.detuning_offset`` (all rad/s).
* ``R_z(a) = exp(-i a/2 sigma_z) = diag(e^{-ia/2}, e^{ia/2})``.

Numerics (``propagate``)
------------------------
* Free segments ``[a, b]``: exact ``R_z(Phi(b) - Phi(a))`` where ``Phi`` is the exact integral
  of the piecewise-linear interpolant of ``delta`` on ``t_grid`` (= cumulative trapezoid at grid
  nodes, with ``delta`` linearly interpolated at the segment edges). Error O(dt^2 * delta'').
* Pulse k (square, width ``w``, Rabi ``Omega = angle (1 + eps) / w``, axis ``phi + phase_err``):
  ``pulse_steps`` = m piecewise-constant sub-steps of length w/m, ``delta`` sampled (linear
  interpolation) at sub-step midpoints; each sub-step is the exact SU(2) exponential
  ``cos(|a|h/2) I - i sin(|a|h/2) (a/|a|).sigma`` with ``a = (Omega cos, Omega sin, delta)``.
  Exact for constant ``delta`` during the pulse; otherwise midpoint-rule error O(m^-2).
* Zero-width pulses: instantaneous ideal rotation by ``angle (1 + eps)`` (detuning ignored).
* All trajectories are propagated together (vectorised elementwise 2x2 products).

Complexity: time O(n_traj * (N_grid + n_pulses * pulse_steps)), memory O(n_traj * N_grid)
(the noise array itself). Measured (this container, Linux x86_64, Python 3.13, numpy 2.x;
4 cores, see ``tests/test_simulator.py::test_propagate_timing``), median of 11 runs, 256
trajectories, n = 16 pulses of 40 ns, 8 sub-steps, T = 1 us, N_grid = 1001: ``propagate``
9-12 ms; ``simulate`` unitary path ~12 ms; ``simulate`` with T1 (per-trajectory 4x4 PTM
composition over 2n+1 segments) ~13 ms. Machine dependent; the test asserts < 50 ms.

Numerical precision (observed, see tests): unitarity error < 1e-14; agreement with a
20000-step scipy ``expm`` reference 5e-8; pulse sub-step error ~ 0.19 m^-2 and noise-grid
error ~ 1.5e-4 at dt = 1 ns for a 5 MHz-amplitude 7 MHz sinusoidal detuning (max-abs
unitary error); free evolution under a linear ramp exact to 1e-12.

Channel and fidelity (``simulate``)
-----------------------------------
* Target ``U_target = R_z(theta_vz) U_0`` with ``U_0 = sequences.ideal_unitary(seq)`` and
  ``theta_vz`` from ``virtual_z_angle`` iff ``frame_correction == "ideal_control_plus_virtual_z"``.
* Per trajectory k: PTM ``R_k`` (unitary, or composed with amplitude damping). Channel
  ``R_mean = mean_k R_k``; ``F_avg = (Tr(R_target^T R_mean) + 2)/6``; ``infidelity = 1 - F_avg``.
  Because ``F_avg`` is linear in the channel, this equals the mean of per-trajectory
  infidelities; ``infidelity_stderr = std(per-traj infidelity, ddof=1)/sqrt(n_traj)`` (MC error
  only, not model error).
* T1 (``config.include_T1`` and finite ``noise.T1``): amplitude damping PTM with
  ``gamma = 1 - exp(-t/T1)``, ``diag(1, sqrt(1-g), sqrt(1-g), 1-g)`` + ``R[3,0] = g``
  ((I,X,Y,Z) basis), composed per free segment with the segment's z-rotation (exact, AD is
  phase covariant so it commutes with z rotations). **Approximation:** during a finite pulse
  the pulse unitary is sandwiched as ``AD(w/2) . U_pulse . AD(w/2)`` (symmetric splitting,
  error O((w/T1) * Omega w) relative to solving the Lindblad equation). Pure dephasing from
  T_phi is *not* added; dephasing comes only from the sampled delta(t).

Random draws (``simulate`` / ``frozen_draws``): ``rng = np.random.default_rng(config.seed)``;
(1) stochastic noise ``ddopt.noise.sample_detuning(noise, t, n_traj, rng)`` (skipped, with no
draws, if the model has no stochastic components); (2) ``amp_eps = amp_rel_bias + amp_rel_std
* rng.standard_normal(n_traj)``; (3) ``phase_err = phase_std * rng.standard_normal(n_traj)``.
Draws (2) and (3) are always made (even with zero std) to keep the stream layout fixed.
If ``delta_traj`` is injected without ``amp_eps``/``phase_err``, (2)-(3) are drawn from a fresh
``default_rng(config.seed)`` (no noise draws precede them in that case).
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np

from ddopt.contracts import NoiseModel, PulseSequence, SimulationConfig, SimulationResult
from ddopt.sequences import ideal_unitary

__all__ = ["propagate", "simulate", "frozen_draws", "virtual_z_angle", "time_grid"]

_PAULIS = np.array(
    [
        [[1, 0], [0, 1]],
        [[0, 1], [1, 0]],
        [[0, -1j], [1j, 0]],
        [[1, 0], [0, -1]],
    ],
    dtype=complex,
)

ASSUMPTIONS = [
    "single qubit, hbar=1, H = 1/2 delta(t) Z + 1/2 Omega (cos phi X + sin phi Y)",
    "square pulses, Rabi = angle/width, no leakage, no pulse shaping/transients",
    "free segments: exact Rz with integral of piecewise-linear interpolated delta",
    "pulses: piecewise-constant sub-steps, delta at sub-step midpoints",
    "static control errors per trajectory: relative amplitude eps, common axis phase error",
    "T1: amplitude damping composed per free segment (exact); AD(w/2) U AD(w/2) during pulses (approx.)",
    "no T_phi channel beyond sampled delta(t); no SPAM; channel = mean of per-trajectory PTMs",
    "fidelity: F_avg = (Tr(R_target^T R)+2)/6 against U_target = Rz(theta_vz) U_0",
]


# ---------------------------------------------------------------------------
# small batched 2x2 algebra
# ---------------------------------------------------------------------------


def _mm(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """Batched 2x2 product A @ B over leading axes (explicit, avoids matmul overhead)."""
    C = np.empty(np.broadcast_shapes(A.shape, B.shape), dtype=complex)
    C[..., 0, 0] = A[..., 0, 0] * B[..., 0, 0] + A[..., 0, 1] * B[..., 1, 0]
    C[..., 0, 1] = A[..., 0, 0] * B[..., 0, 1] + A[..., 0, 1] * B[..., 1, 1]
    C[..., 1, 0] = A[..., 1, 0] * B[..., 0, 0] + A[..., 1, 1] * B[..., 1, 0]
    C[..., 1, 1] = A[..., 1, 0] * B[..., 0, 1] + A[..., 1, 1] * B[..., 1, 1]
    return C


def _su2_exp(ax: np.ndarray, ay: np.ndarray, az: np.ndarray, h: float | np.ndarray) -> np.ndarray:
    """exp(-i h/2 (ax X + ay Y + az Z)), elementwise over broadcast arrays."""
    ax, ay, az = np.broadcast_arrays(ax, ay, az)
    norm = np.sqrt(ax * ax + ay * ay + az * az)
    half = 0.5 * norm * h
    c = np.cos(half)
    with np.errstate(invalid="ignore", divide="ignore"):
        s_over = np.where(norm > 0, np.sin(half) / np.where(norm > 0, norm, 1.0), 0.5 * h)
    U = np.empty(ax.shape + (2, 2), dtype=complex)
    U[..., 0, 0] = c - 1j * s_over * az
    U[..., 1, 1] = c + 1j * s_over * az
    U[..., 0, 1] = -1j * s_over * (ax - 1j * ay)
    U[..., 1, 0] = -1j * s_over * (ax + 1j * ay)
    return U


def _rz(phi: np.ndarray) -> np.ndarray:
    phi = np.asarray(phi, dtype=float)
    U = np.zeros(phi.shape + (2, 2), dtype=complex)
    U[..., 0, 0] = np.exp(-0.5j * phi)
    U[..., 1, 1] = np.exp(0.5j * phi)
    return U


def _unitary_ptm(U: np.ndarray) -> np.ndarray:
    """PTM R_ij = 1/2 Tr(P_i U P_j U^dagger) for U of shape (..., 2, 2), (I,X,Y,Z) basis.

    Closed form: U/sqrt(det U) = q0 I - i (q1 X + q2 Y + q3 Z) (unit quaternion), and the
    Bloch block is the standard quaternion rotation matrix (rotation by 2 acos q0 about q)."""
    U = np.asarray(U, dtype=complex)
    V = U / np.sqrt(U[..., 0, 0] * U[..., 1, 1] - U[..., 0, 1] * U[..., 1, 0])[..., None, None]
    q0 = V[..., 0, 0].real
    q3 = -V[..., 0, 0].imag
    q2 = V[..., 1, 0].real
    q1 = -V[..., 1, 0].imag
    R = np.zeros(U.shape[:-2] + (4, 4))
    R[..., 0, 0] = 1.0
    R[..., 1, 1] = 1 - 2 * (q2 * q2 + q3 * q3)
    R[..., 1, 2] = 2 * (q1 * q2 - q0 * q3)
    R[..., 1, 3] = 2 * (q1 * q3 + q0 * q2)
    R[..., 2, 1] = 2 * (q1 * q2 + q0 * q3)
    R[..., 2, 2] = 1 - 2 * (q1 * q1 + q3 * q3)
    R[..., 2, 3] = 2 * (q2 * q3 - q0 * q1)
    R[..., 3, 1] = 2 * (q1 * q3 - q0 * q2)
    R[..., 3, 2] = 2 * (q2 * q3 + q0 * q1)
    R[..., 3, 3] = 1 - 2 * (q1 * q1 + q2 * q2)
    return R


def _ad_ptm(gamma: float) -> np.ndarray:
    s = math.sqrt(1.0 - gamma)
    R = np.diag([1.0, s, s, 1.0 - gamma])
    R[3, 0] = gamma
    return R


def _favg_from_ptm(R: np.ndarray) -> np.ndarray:
    return (np.trace(R, axis1=-2, axis2=-1) + 2.0) / 6.0


# ---------------------------------------------------------------------------
# interpolation of delta and its integral on the grid
# ---------------------------------------------------------------------------


def _locate(t_grid: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    idx = np.searchsorted(t_grid, x, side="right") - 1
    idx = np.clip(idx, 0, len(t_grid) - 2)
    h = t_grid[idx + 1] - t_grid[idx]
    s = (x - t_grid[idx]) / h
    return idx, s, h


def _delta_at(delta: np.ndarray, t_grid: np.ndarray, x: np.ndarray) -> np.ndarray:
    idx, s, _ = _locate(t_grid, x.ravel())
    d = delta[:, idx] * (1 - s) + delta[:, idx + 1] * s
    return d.reshape((delta.shape[0],) + x.shape)


def _phi_at(delta: np.ndarray, t_grid: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Exact integral from t_grid[0] to x of the linear interpolant of delta
    (cumulative trapezoid at nodes + exact partial cell)."""
    idx, s, h = _locate(t_grid, x)
    d0 = delta[:, idx]
    d1 = delta[:, idx + 1]
    dts = np.diff(t_grid)
    if np.allclose(dts, dts[0], rtol=1e-9, atol=0.0):
        # uniform grid: Phi_i = dt (S_i - (delta_0 + delta_i)/2), S = cumsum(delta)
        cs = np.cumsum(delta, axis=1)[:, idx]
        Phi_idx = dts[0] * (cs - 0.5 * (delta[:, :1] + d0))
    else:
        inc = 0.5 * (delta[:, :-1] + delta[:, 1:]) * dts
        Phi = np.concatenate([np.zeros((delta.shape[0], 1)), np.cumsum(inc, axis=1)], axis=1)
        Phi_idx = Phi[:, idx]
    return Phi_idx + h * (d0 * s + 0.5 * (d1 - d0) * s * s)


def _prep(seq: PulseSequence, delta_traj, t_grid, amp_eps, phase_err):
    delta = np.asarray(delta_traj, dtype=float)
    if delta.ndim == 1:
        delta = delta[None, :]
    t_grid = np.asarray(t_grid, dtype=float)
    if delta.ndim != 2 or delta.shape[1] != t_grid.shape[0]:
        raise ValueError(f"delta_traj shape {delta.shape} incompatible with t_grid {t_grid.shape}")
    if t_grid.shape[0] < 2 or np.any(np.diff(t_grid) <= 0):
        raise ValueError("t_grid must be strictly increasing with >= 2 points")
    tol = 1e-12 * seq.T + 1e-18
    if t_grid[0] > tol or t_grid[-1] < seq.T - tol:
        raise ValueError(f"t_grid [{t_grid[0]}, {t_grid[-1]}] does not cover [0, T={seq.T}]")
    nt = delta.shape[0]
    eps = np.zeros(nt) if amp_eps is None else np.broadcast_to(np.asarray(amp_eps, float), (nt,))
    perr = np.zeros(nt) if phase_err is None else np.broadcast_to(np.asarray(phase_err, float), (nt,))
    return delta, t_grid, eps, perr


def _segments(seq, delta, t_grid, pulse_steps, eps, perr):
    """Time-ordered list of (kind, duration, U (n_traj,2,2)) for free gaps and pulses."""
    if pulse_steps < 1:
        raise ValueError("pulse_steps must be >= 1")
    n = seq.n
    nt = delta.shape[0]
    c = np.asarray(seq.centers, float)
    w = np.asarray(seq.widths, float)
    ang = np.asarray(seq.angles, float)
    ph = np.asarray(seq.phases, float)
    starts = c - w / 2
    ends = c + w / 2
    edges = np.concatenate([[0.0], np.ravel(np.column_stack([starts, ends])), [seq.T]])
    Phi_e = _phi_at(delta, t_grid, edges)  # (nt, 2n+2)
    gap_phase = Phi_e[:, 1::2] - Phi_e[:, 0::2]  # (nt, n+1)
    gap_len = edges[1::2] - edges[0::2]
    U_gaps = _rz(gap_phase)  # (nt, n+1, 2, 2)

    U_pulses = None
    if n:
        m = pulse_steps
        finite = w > 0
        h = np.where(finite, w / m, 0.0)  # (n,)
        mids = starts[:, None] + (np.arange(m)[None, :] + 0.5) * h[:, None]  # (n, m)
        d_mid = _delta_at(delta, t_grid, mids)  # (nt, n, m)
        phi_tot = ph[None, :] + perr[:, None]  # (nt, n)
        scale = 1.0 + eps[:, None]
        with np.errstate(divide="ignore", invalid="ignore"):
            omega = np.where(finite, ang / np.where(finite, w, 1.0), 0.0)[None, :] * scale  # (nt, n)
        ax = (omega * np.cos(phi_tot))[:, :, None]
        ay = (omega * np.sin(phi_tot))[:, :, None]
        Usub = _su2_exp(ax, ay, d_mid, h[None, :, None])  # (nt, n, m, 2, 2)
        Up = Usub[:, :, 0]
        for j in range(1, m):
            Up = _mm(Usub[:, :, j], Up)
        if not np.all(finite):
            th = ang[None, :] * scale  # instantaneous ideal rotation
            Uinst = _su2_exp(np.cos(phi_tot), np.sin(phi_tot), np.zeros_like(phi_tot), th)
            Up = np.where(finite[None, :, None, None], Up, Uinst)
        U_pulses = Up
    segs = []
    for k in range(n + 1):
        segs.append(("free", float(gap_len[k]), U_gaps[:, k]))
        if k < n:
            segs.append(("pulse", float(w[k]), U_pulses[:, k]))
    return segs


def propagate(
    seq: PulseSequence,
    delta_traj: np.ndarray,
    t_grid: np.ndarray,
    *,
    pulse_steps: int = 8,
    amp_eps: np.ndarray | float | None = None,
    phase_err: np.ndarray | float | None = None,
) -> np.ndarray:
    """Propagate ``(n_traj, 2, 2)`` unitaries over ``[0, T]`` for total detuning
    ``delta_traj`` (``(n_traj, len(t_grid))`` or 1-D, rad/s) on ``t_grid`` covering [0, T].

    ``amp_eps`` (relative Rabi error, rotation angle -> angle (1+eps)) and ``phase_err`` (axis
    phase offset, rad) are scalars or per-trajectory arrays, constant over the sequence."""
    delta, t_grid, eps, perr = _prep(seq, delta_traj, t_grid, amp_eps, phase_err)
    segs = _segments(seq, delta, t_grid, pulse_steps, eps, perr)
    U = segs[0][2]
    for _, _, Us in segs[1:]:
        U = _mm(Us, U)
    return U


def time_grid(T: float, noise_dt: float) -> np.ndarray:
    """Uniform grid ``k * noise_dt``, k = 0..K, with ``K = ceil(T/noise_dt)`` so it covers T."""
    if not (noise_dt > 0):
        raise ValueError("noise_dt must be > 0")
    K = max(1, int(math.ceil(T / noise_dt - 1e-9)))
    return np.arange(K + 1) * noise_dt


def _draw_control_errors(config: SimulationConfig, n_traj: int, rng: np.random.Generator):
    ce = config.control_errors
    amp_eps = ce.amp_rel_bias + ce.amp_rel_std * rng.standard_normal(n_traj)
    phase_err = ce.phase_std * rng.standard_normal(n_traj)
    return amp_eps, phase_err


def frozen_draws(noise: NoiseModel, T: float, config: SimulationConfig) -> dict:
    """Common-random-number draws, identical to what ``simulate`` samples internally:
    ``{"t": grid, "delta": (n_traj, len(t)) stochastic part only, "amp_eps", "phase_err"}``.
    Pass back as ``simulate(seq, noise, config, delta_traj=d["delta"], t_grid=d["t"],
    amp_eps=d["amp_eps"], phase_err=d["phase_err"])`` (requires ``seq.T <= T``)."""
    noise.validate()
    t = time_grid(T, config.noise_dt)
    rng = np.random.default_rng(config.seed)
    if noise.components:
        from ddopt.noise import sample_detuning  # lazy: owned by Agent A

        delta = np.asarray(sample_detuning(noise, t, config.n_traj, rng), dtype=float)
    else:
        delta = np.zeros((config.n_traj, t.size))
    amp_eps, phase_err = _draw_control_errors(config, config.n_traj, rng)
    return {"t": t, "delta": delta, "amp_eps": amp_eps, "phase_err": phase_err}


def virtual_z_angle(seq: PulseSequence, noise: NoiseModel, config: SimulationConfig) -> float:
    """Virtual-Z angle theta maximising F_avg(R_z(theta) U_0, U_d), where U_d is the noise-free,
    control-error-free evolution under the *known* deterministic profile ``noise.detuning``
    only (the unknown ``detuning_offset`` is excluded). With ``M = U_d U_0^dagger``:
    ``|Tr(R_z(theta)^dagger M)| = |e^{i theta/2} M00 + e^{-i theta/2} M11|`` is maximal at
    ``theta = arg M11 - arg M00`` (wrapped to (-pi, pi])."""
    if noise.detuning.kind == "none":
        return 0.0
    t = time_grid(seq.T, config.noise_dt)
    d = noise.detuning(t)[None, :]
    Ud = propagate(seq, d, t, pulse_steps=config.pulse_steps)[0]
    M = Ud @ ideal_unitary(seq).conj().T
    if abs(M[0, 0]) < 1e-14 or abs(M[1, 1]) < 1e-14:
        return 0.0
    theta = float(np.angle(M[1, 1]) - np.angle(M[0, 0]))
    return float((theta + np.pi) % (2 * np.pi) - np.pi)


def simulate(
    seq: PulseSequence,
    noise: NoiseModel,
    config: SimulationConfig,
    *,
    delta_traj: np.ndarray | None = None,
    t_grid: np.ndarray | None = None,
    amp_eps: np.ndarray | None = None,
    phase_err: np.ndarray | None = None,
    return_per_traj: bool = True,
) -> SimulationResult:
    """Noise-averaged average gate infidelity of the idle window against the corrected target.

    ``delta_traj`` (optional, frozen draws / CRN) is the **stochastic** detuning only, shape
    ``(n_traj, len(t_grid))``; the deterministic profile and ``detuning_offset`` are added here.
    ``t_grid`` defaults to ``time_grid(seq.T, config.noise_dt)``. See module docstring for the
    draw order and channel construction."""
    t0 = time.perf_counter()
    seq.validate()
    noise.validate()
    if config.observable != "avg_gate_fidelity":
        raise ValueError(f"unsupported observable {config.observable!r}")
    if delta_traj is None:
        if t_grid is not None or amp_eps is not None or phase_err is not None:
            raise ValueError("t_grid/amp_eps/phase_err may only be injected together with delta_traj")
        draws = frozen_draws(noise, seq.T, config)
        t, delta, amp_eps, phase_err = draws["t"], draws["delta"], draws["amp_eps"], draws["phase_err"]
        source = "sampled" if noise.components else "none (no stochastic components)"
    else:
        t = time_grid(seq.T, config.noise_dt) if t_grid is None else np.asarray(t_grid, float)
        delta = np.asarray(delta_traj, dtype=float)
        if delta.ndim == 1:
            delta = delta[None, :]
        if amp_eps is None or phase_err is None:
            a2, p2 = _draw_control_errors(config, delta.shape[0], np.random.default_rng(config.seed))
            amp_eps = a2 if amp_eps is None else amp_eps
            phase_err = p2 if phase_err is None else phase_err
        source = "injected"
    n_traj = delta.shape[0]
    total = delta + noise.detuning(t)[None, :] + config.control_errors.detuning_offset

    total, t, eps, perr = _prep(seq, total, t, amp_eps, phase_err)
    segs = _segments(seq, total, t, config.pulse_steps, eps, perr)

    theta = virtual_z_angle(seq, noise, config) if config.frame_correction == "ideal_control_plus_virtual_z" else 0.0
    if config.frame_correction not in ("ideal_control", "ideal_control_plus_virtual_z"):
        raise ValueError(f"unknown frame_correction {config.frame_correction!r}")
    U_target = _rz(np.array(theta)) @ ideal_unitary(seq)
    R_target = _unitary_ptm(U_target)

    use_t1 = bool(config.include_T1 and math.isfinite(noise.T1))
    if use_t1:
        R = None
        Rus = _unitary_ptm(np.stack([s[2] for s in segs], axis=1))  # (nt, n_seg, 4, 4)
        for i, (kind, dur, _) in enumerate(segs):
            Ru = Rus[:, i]
            if kind == "free":
                step = _ad_ptm(1.0 - math.exp(-dur / noise.T1)) @ Ru
            else:
                A = _ad_ptm(1.0 - math.exp(-0.5 * dur / noise.T1))
                step = A @ Ru @ A
            R = step if R is None else step @ R
        R_err = np.einsum("ji,njk->nik", R_target, R)  # R_target^T R_k
        F = _favg_from_ptm(R_err)
        R_mean = R.mean(axis=0)
    else:
        U = segs[0][2]
        for _, _, Us in segs[1:]:
            U = _mm(Us, U)
        V = _mm(np.broadcast_to(U_target.conj().T, U.shape), U)
        trV = V[:, 0, 0] + V[:, 1, 1]
        F = (np.abs(trV) ** 2 + 2.0) / 6.0
        R_mean = _unitary_ptm(U).mean(axis=0)
    per = 1.0 - F
    F_chan = float(_favg_from_ptm(R_target.T @ R_mean))
    infid = 1.0 - F_chan
    stderr = float(np.std(per, ddof=1) / math.sqrt(n_traj)) if n_traj > 1 else float("nan")
    runtime = time.perf_counter() - t0
    prov: dict[str, Any] = {
        "seed": config.seed,
        "n_traj": n_traj,
        "noise_dt": config.noise_dt,
        "n_grid": int(t.size),
        "pulse_steps": config.pulse_steps,
        "include_T1": use_t1,
        "T1": noise.T1,
        "frame_correction": config.frame_correction,
        "draw_source": source,
        "draw_order": "rng=default_rng(seed): noise (if components) -> amp_eps normals -> phase_err normals",
        "sequence_label": seq.label,
        "n_pulses": seq.n,
        "mean_per_traj_infidelity": float(per.mean()),
        "assumptions": list(ASSUMPTIONS),
    }
    return SimulationResult(
        infidelity=infid,
        infidelity_stderr=stderr,
        fidelity=F_chan,
        n_traj=n_traj,
        seed=config.seed,
        virtual_z_angle=theta,
        per_traj_infidelity=[float(x) for x in per] if return_per_traj else None,
        channel_ptm=R_mean.tolist(),
        runtime_s=runtime,
        provenance=prov,
    )
