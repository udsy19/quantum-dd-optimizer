"""Canonical and parameterised dynamical-decoupling pulse sequences (Agent B).

Conventions (binding; see ``docs/PHYSICS_CONVENTIONS.md``):

* Time in seconds, angles in radians. The idle window is ``[0, T]``.
* Every pulse is a **square** pulse of duration ``width`` centred at ``centers[k]`` with
  nominal rotation angle ``angles[k]`` (default pi) about the equatorial axis
  ``cos(phi_k) X + sin(phi_k) Y``. The Rabi rate is ``Omega_k = angles[k] / widths[k]`` (rad/s).
  ``width == 0`` denotes an ideal instantaneous pulse (analytic limit).
* Ideal pulse unitary: ``P_k = exp(-i angles[k]/2 (cos phi_k X + sin phi_k Y))``. The ideal
  net control unitary is the time-ordered product ``U_0 = P_n ... P_2 P_1`` (free evolution is
  the identity in the absence of detuning). For an even number of pi pulses ``U_0`` is
  proportional to a Pauli product (often +-I); for an **odd** number it is a pi rotation, never
  the identity. The pulse-axis phases ``phi_k`` are *control parameters*; the target-gate /
  frame correction is handled by the simulator (``U_target = R_z(theta_vz) U_0``) and is
  never folded into the pulse phases.
* Axis-phase convention of the families:

  - ``hahn``: one pi pulse at T/2, default phase 0 (X axis).
  - ``cpmg``: n pi pulses at ``T (k - 1/2)/n`` (k = 1..n), all with phase pi/2 (Y axis).
    (The Carr-Purcell-Meiboom-Gill choice: pulse axis orthogonal to the X-axis
    pi/2 preparation pulse; for gate-fidelity grading the axis choice only matters in the
    presence of control errors.)
  - ``xy4``: CPMG timing, phases X Y X Y repeated (0, pi/2, 0, pi/2), n % 4 == 0.
  - ``xy8``: CPMG timing, phases X Y X Y Y X Y X repeated, n % 8 == 0.
  - ``udd``: Uhrig centres ``T sin^2(pi k / (2n + 2))`` (k = 1..n), phase pi/2 (Y).

* Timing constraints (``PulseSequence.validate``): pulses ordered and non-overlapping, gaps
  between window edges and pulse edges and between consecutive pulses ``>= guard``; hence
  ``T >= n * width + (n + 1) * guard`` is necessary. Infeasible requests raise ``ValueError``
  (e.g. 16 x 40 ns pulses in a 500 ns window). A family with fixed centres can be infeasible
  even when ``feasible()`` is True, because its first/last centred pulse may cross the window
  edge or the guard; those cases also raise.
* ``dt_grid``: if given, pulse *start* times are rounded to the nearest multiple of
  ``dt_grid`` (e.g. a 4 ns hardware clock) and the sequence is re-validated (may raise).
  Pulse widths are not modified; whether a width is a multiple of the tick is the caller's
  responsibility (recorded in ``metadata['width_on_grid']``).
"""

from __future__ import annotations

import dataclasses
import math
from typing import Sequence

import numpy as np

from ddopt.contracts import PulseSequence

__all__ = [
    "free",
    "hahn",
    "cpmg",
    "xy4",
    "xy8",
    "udd",
    "from_gaps",
    "snap_to_grid",
    "feasible",
    "ideal_unitary",
    "pulse_unitary",
    "X_PHASE",
    "Y_PHASE",
]

X_PHASE = 0.0
Y_PHASE = math.pi / 2

_I2 = np.eye(2, dtype=complex)
_SX = np.array([[0, 1], [1, 0]], dtype=complex)
_SY = np.array([[0, -1j], [1j, 0]], dtype=complex)


def _tol(T: float) -> float:
    return 1e-15 + 1e-12 * T


def feasible(n: int, T: float, width: float, guard: float = 0.0) -> bool:
    """True iff *some* placement of ``n`` pulses of ``width`` fits in ``[0, T]`` with all
    ``n + 1`` gaps ``>= guard``, i.e. ``T >= n*width + (n+1)*guard`` (tolerance 1e-12 T).

    This is necessary but not sufficient for a specific family (fixed centres)."""
    if n < 0 or T <= 0 or width < 0 or guard < 0:
        return False
    need = n * width + (n + 1) * guard if n > 0 else 0.0
    return need <= T + _tol(T)


def _snap_starts(centers: np.ndarray, widths: np.ndarray, dt_grid: float) -> np.ndarray:
    starts = centers - widths / 2
    snapped = np.round(starts / dt_grid) * dt_grid
    return snapped + widths / 2


def _build(
    T: float,
    centers: Sequence[float],
    width: float | Sequence[float],
    phases: Sequence[float],
    *,
    guard: float,
    dt_grid: float | None,
    label: str,
    angles: Sequence[float] | None = None,
    metadata: dict | None = None,
) -> PulseSequence:
    n = len(centers)
    centers_a = np.asarray(centers, dtype=float)
    widths_a = np.broadcast_to(np.asarray(width, dtype=float), (n,)).copy()
    if angles is None:
        angles_a = np.full(n, math.pi)
    else:
        angles_a = np.asarray(angles, dtype=float)
    if len(phases) != n or len(angles_a) != n:
        raise ValueError("phases/angles length must equal number of pulses")
    if guard < 0:
        raise ValueError("guard must be nonnegative")
    if np.any(widths_a < 0):
        raise ValueError("widths must be nonnegative")
    need = float(widths_a.sum()) + ((n + 1) * guard if n > 0 else 0.0)
    if need > T + _tol(T):
        raise ValueError(
            f"infeasible: {n} pulses x {widths_a.max() if n else 0:.3e} s + guards need "
            f"{need:.3e} s > T = {T:.3e} s"
        )
    meta = dict(metadata or {})
    if dt_grid is not None:
        if not dt_grid > 0:
            raise ValueError("dt_grid must be > 0")
        unsnapped = centers_a.copy()
        centers_a = _snap_starts(centers_a, widths_a, dt_grid)
        meta["snap_max_shift_s"] = float(np.max(np.abs(centers_a - unsnapped))) if n else 0.0
        meta["width_on_grid"] = bool(
            np.all(np.abs(widths_a / dt_grid - np.round(widths_a / dt_grid)) * dt_grid < 1e-12)
        )
    seq = PulseSequence(
        T=float(T),
        centers=tuple(float(c) for c in centers_a),
        widths=tuple(float(w) for w in widths_a),
        phases=tuple(float(p) for p in phases),
        angles=tuple(float(a) for a in angles_a),
        guard=float(guard),
        dt_grid=None if dt_grid is None else float(dt_grid),
        label=label,
        metadata=meta,
    )
    seq.validate()
    return seq


def free(T: float, *, guard: float = 0.0, dt_grid: float | None = None) -> PulseSequence:
    """Free evolution (Ramsey idle, no pulses). ``U_0 = I``."""
    return _build(T, [], 0.0, [], guard=guard, dt_grid=dt_grid, label="free")


def _cpmg_centers(n: int, T: float) -> np.ndarray:
    k = np.arange(1, n + 1)
    return T * (k - 0.5) / n


def hahn(
    T: float, width: float, *, guard: float = 0.0, dt_grid: float | None = None, phase: float = X_PHASE
) -> PulseSequence:
    """Hahn echo: one pi pulse centred at T/2 about axis ``phase`` (default X)."""
    return _build(T, [T / 2], width, [phase], guard=guard, dt_grid=dt_grid, label="hahn")


def cpmg(
    n: int,
    T: float,
    width: float,
    *,
    guard: float = 0.0,
    dt_grid: float | None = None,
    phase: float = Y_PHASE,
) -> PulseSequence:
    """CPMG-n: centres ``T (k - 1/2)/n``, all pulses about axis ``phase`` (default pi/2 = Y)."""
    if n < 1:
        raise ValueError("cpmg requires n >= 1")
    return _build(T, _cpmg_centers(n, T), width, [phase] * n, guard=guard, dt_grid=dt_grid,
                  label="cpmg", metadata={"family_n": n})


def xy4(n: int, T: float, width: float, *, guard: float = 0.0, dt_grid: float | None = None) -> PulseSequence:
    """XY4 (repeated n/4 times): CPMG timing, phases X Y X Y. Requires n % 4 == 0."""
    if n < 4 or n % 4:
        raise ValueError("xy4 requires n a positive multiple of 4")
    phases = [X_PHASE, Y_PHASE, X_PHASE, Y_PHASE] * (n // 4)
    return _build(T, _cpmg_centers(n, T), width, phases, guard=guard, dt_grid=dt_grid,
                  label="xy4", metadata={"family_n": n})


def xy8(n: int, T: float, width: float, *, guard: float = 0.0, dt_grid: float | None = None) -> PulseSequence:
    """XY8 (repeated n/8 times): CPMG timing, phases X Y X Y Y X Y X. Requires n % 8 == 0."""
    if n < 8 or n % 8:
        raise ValueError("xy8 requires n a positive multiple of 8")
    X, Y = X_PHASE, Y_PHASE
    phases = [X, Y, X, Y, Y, X, Y, X] * (n // 8)
    return _build(T, _cpmg_centers(n, T), width, phases, guard=guard, dt_grid=dt_grid,
                  label="xy8", metadata={"family_n": n})


def udd(
    n: int,
    T: float,
    width: float,
    *,
    guard: float = 0.0,
    dt_grid: float | None = None,
    phase: float = Y_PHASE,
) -> PulseSequence:
    """Uhrig DD: centres ``T sin^2(pi k/(2n+2))``, k = 1..n, axis ``phase`` (default Y).

    With finite widths the outermost pulses (centres ~ T pi^2/(2n+2)^2 from the edges) are the
    first to violate the window edge / guard; that raises ``ValueError``."""
    if n < 1:
        raise ValueError("udd requires n >= 1")
    k = np.arange(1, n + 1)
    centers = T * np.sin(np.pi * k / (2 * n + 2)) ** 2
    return _build(T, centers, width, [phase] * n, guard=guard, dt_grid=dt_grid,
                  label="udd", metadata={"family_n": n})


def from_gaps(
    T: float,
    width: float | Sequence[float],
    gaps: Sequence[float],
    phases: Sequence[float],
    *,
    guard: float = 0.0,
    dt_grid: float | None = None,
    angles: Sequence[float] | None = None,
    label: str = "custom",
    rtol: float = 1e-9,
) -> PulseSequence:
    """Explicit gap parameterisation: ``gaps`` has length ``n + 1`` (free time before the first
    pulse, between pulses, after the last pulse), with ``sum(gaps) + sum(widths) == T`` to
    relative tolerance ``rtol`` (else ``ValueError``; no silent renormalisation)."""
    gaps_a = np.asarray(gaps, dtype=float)
    n = len(phases)
    if gaps_a.shape != (n + 1,):
        raise ValueError(f"gaps must have length n+1 = {n + 1}, got {gaps_a.shape}")
    widths_a = np.broadcast_to(np.asarray(width, dtype=float), (n,)).astype(float)
    total = gaps_a.sum() + widths_a.sum()
    if abs(total - T) > rtol * T + 1e-18:
        raise ValueError(f"gaps + widths sum to {total:.12e} s, not T = {T:.12e} s")
    if np.any(gaps_a < -_tol(T)):
        raise ValueError("gaps must be nonnegative")
    # start_k = g_0 + ... + g_k + w_0 + ... + w_{k-1}
    starts = np.cumsum(gaps_a[:-1]) + np.concatenate([[0.0], np.cumsum(widths_a[:-1])]) if n else np.array([])
    centers = starts + widths_a / 2
    return _build(T, centers, widths_a, list(phases), guard=guard, dt_grid=dt_grid,
                  label=label, angles=angles)


def snap_to_grid(seq: PulseSequence, dt_grid: float) -> PulseSequence:
    """Round every pulse start to the nearest multiple of ``dt_grid`` (widths unchanged) and
    re-validate; raises ``ValueError`` if snapping creates overlap / guard violations."""
    if not dt_grid > 0:
        raise ValueError("dt_grid must be > 0")
    c = np.asarray(seq.centers, dtype=float)
    w = np.asarray(seq.widths, dtype=float)
    new_c = _snap_starts(c, w, dt_grid) if seq.n else c
    meta = dict(seq.metadata)
    meta["snap_max_shift_s"] = float(np.max(np.abs(new_c - c))) if seq.n else 0.0
    out = dataclasses.replace(seq, centers=tuple(float(x) for x in new_c), dt_grid=float(dt_grid),
                              metadata=meta)
    out.validate()
    return out


def pulse_unitary(angle: float, phase: float) -> np.ndarray:
    """Ideal rotation ``exp(-i angle/2 (cos(phase) X + sin(phase) Y))``."""
    return math.cos(angle / 2) * _I2 - 1j * math.sin(angle / 2) * (
        math.cos(phase) * _SX + math.sin(phase) * _SY
    )


def ideal_unitary(seq: PulseSequence) -> np.ndarray:
    """Net ideal control unitary ``U_0 = P_n ... P_1`` (no noise, no control errors).

    Independent of pulse widths and timing (free evolution is the identity without detuning).
    """
    U = _I2.copy()
    for a, p in zip(seq.angles, seq.phases):
        U = pulse_unitary(a, p) @ U
    return U
