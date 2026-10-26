"""CMA-ES optimisation of dynamical-decoupling schedules (Agent D).

Conventions: seconds, rad/s, radians; see ``docs/PHYSICS_CONVENTIONS.md`` and
``docs/EXPERIMENT_PLAN.md`` (pre-registration). Nothing in this module touches test seeds;
the objective only ever sees the *frozen training draws* passed in by the caller.

Parameterisation (``decode``)
-----------------------------
A candidate ``x`` (unconstrained real vector) is mapped to a ``PulseSequence`` of ``n`` square
pi pulses of fixed ``width`` in the window ``[0, T]``:

* **Timing** (``n`` coordinates ``z``). The ``n + 1`` free-evolution gaps are
  ``g_i = guard + S * w_i`` with slack ``S = T - n*width - (n+1)*guard >= 0`` and
  ``w = softmax([0, z_1, ..., z_n])``. The first logit is fixed to 0, which removes the
  redundant common shift of a softmax (so ``n`` coordinates parameterise the ``n``-dimensional
  simplex of gaps exactly). Every decoded schedule satisfies the minimum-spacing (guard)
  constraint by construction, and ``sum(g) + n*width == T``.
* **Clock grid.** If ``dt_grid`` is given, pulse starts are rounded to the nearest grid point
  (``sequences.snap_to_grid``, identical rounding to the canonical families). Rounding can
  violate the guard (two starts moving towards each other). In that case a deterministic
  repair is attempted (forward pass pushing starts up to the first admissible grid point,
  then a backward pass pulling starts down from the window end); if the repaired schedule is
  still invalid the candidate is **rejected**: ``decode`` returns ``None`` and the optimiser
  assigns ``REJECT_PENALTY`` and counts the rejection. Repairs are counted separately.
* **Phases** (``n`` coordinates). ``phase_k = base_phases[k] + x_k`` wrapped to ``[0, 2pi)``.

Target / frame trackability
---------------------------
The simulator always grades a sequence against its *own* ideal net unitary
``U_0 = P_n ... P_1`` (optionally times a virtual-Z). For pi pulses about equatorial axes
``phi_k``, ``U_0`` is (up to global phase) a z-rotation by ``2 * sum_k (-1)^k phi_k`` (n even)
or an equatorial pi rotation about the axis ``sum_k (-1)^(n-1-k) phi_k`` (n odd). Arbitrary
phases therefore turn the idle into a non-trivial gate. **Policy:** we only allow sequences
whose ``U_0`` is proportional to a Pauli operator (I, X, Y or Z), i.e. a frame-trackable
idle. Rather than rejecting almost every phase candidate, the phase offsets are projected
onto the hyperplane ``a . x = 0`` with ``a_k = (-1)^(n-1-k)`` (``phase_closure=True``,
default). This keeps the alternating phase sum, and hence ``U_0``, *exactly* equal to that of
the base phases (CPMG: ``U_0 = +-I``). The projection direction is a flat direction of the
objective (CMA-ES tolerates this); for even ``n`` the global phase shift ``(1,...,1)`` is a
second, physical gauge direction (the noise is z-only, so a common rotation of all axes is a
symmetry). ``decode`` then checks that ``U_0`` is a Pauli (``|Tr(P^dag U_0)| = 2`` for some
Pauli P, tolerance 1e-9) and rejects otherwise (only possible with ``phase_closure=False`` or
a non-Pauli base). The base phases themselves must give a Pauli ``U_0``.

Objective
---------
``simulator.simulate`` average gate infidelity on frozen training draws (common random
numbers: the same stochastic detuning, amplitude errors and phase errors for every
candidate), with the configured frame correction. The optional ``robust`` list averages the
objective over perturbed *true* noise models while the controller (virtual-Z frame) still
uses the nominal model, see ``simulate_on_draws``.

CMA-ES: pycma 4.5.0 ``CMAEvolutionStrategy`` (ask/tell), box bounds ``[-z_bound, z_bound]`` on
timing logits and ``[-phase_bound, phase_bound]`` on phase offsets, ``sigma0`` common to all
coordinates. pycma draws from the *global* ``np.random`` state seeded with ``seed``; we save
and restore the global state around the run so callers are unaffected. ``seed`` must be a
positive integer (pycma treats 0/None as "seed from time").
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import time
from typing import Any, Sequence

import numpy as np

from ddopt import sequences as seqmod
from ddopt.contracts import NoiseModel, OptimizationResult, PulseSequence, SimulationConfig
from ddopt.simulator import simulate

__all__ = [
    "decode",
    "encode_gaps",
    "encode_cpmg",
    "slack",
    "is_frame_trackable",
    "phase_closure_vector",
    "simulate_on_draws",
    "draws_fingerprint",
    "optimize",
    "REJECT_PENALTY",
    "MODES",
]

REJECT_PENALTY = 1.0  # > max possible average gate infidelity of a qubit channel (2/3)
MODES = ("timing", "phase", "both")
_TWO_PI = 2.0 * math.pi

_PAULIS = [
    np.eye(2, dtype=complex),
    np.array([[0, 1], [1, 0]], dtype=complex),
    np.array([[0, -1j], [1j, 0]], dtype=complex),
    np.array([[1, 0], [0, -1]], dtype=complex),
]


# ---------------------------------------------------------------------------
# parameterisation
# ---------------------------------------------------------------------------


def slack(n: int, T: float, width: float, guard: float) -> float:
    """Free slack ``S = T - n*width - (n+1)*guard`` (s); negative means infeasible."""
    return T - n * width - (n + 1) * guard


def n_params(n: int, mode: str) -> int:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    return 2 * n if mode == "both" else n


def encode_gaps(gaps: Sequence[float], T: float, width: float, *, guard: float = 0.0) -> np.ndarray:
    """Exact inverse of the timing decoder: logits ``z`` (length n) with
    ``guard + S softmax([0, z]) == gaps``. Requires every gap ``> guard``."""
    g = np.asarray(gaps, dtype=float)
    n = g.size - 1
    S = slack(n, T, width, guard)
    if S <= 0:
        raise ValueError(f"no slack (S = {S:.3e} s) to encode gaps")
    if abs(g.sum() + n * width - T) > 1e-9 * T:
        raise ValueError("gaps + widths do not sum to T")
    w = (g - guard) / S
    if np.any(w <= 0):
        raise ValueError("every gap must exceed the guard to be encodable (softmax weights > 0)")
    return np.log(w[1:]) - np.log(w[0])


def cpmg_gaps(n: int, T: float, width: float) -> np.ndarray:
    """CPMG gaps for centres ``T (k - 1/2)/n``: edges ``T/(2n) - width/2``, interior ``T/n - width``."""
    tau = T / n
    g = np.full(n + 1, tau - width)
    g[0] = g[-1] = tau / 2 - width / 2
    return g


def encode_cpmg(n: int, T: float, width: float, *, guard: float = 0.0) -> np.ndarray:
    """Timing logits ``z`` that decode (without grid) exactly to CPMG-n timing."""
    return encode_gaps(cpmg_gaps(n, T, width), T, width, guard=guard)


def _decode_gaps(z: np.ndarray, n: int, T: float, width: float, guard: float) -> np.ndarray:
    S = slack(n, T, width, guard)
    if S < -1e-12 * T:
        raise ValueError(f"infeasible: n={n} pulses of {width:.3e} s with guard {guard:.3e} s exceed T={T:.3e} s")
    S = max(S, 0.0)
    logits = np.concatenate([[0.0], np.asarray(z, dtype=float)])
    logits = logits - logits.max()
    e = np.exp(logits)
    w = e / e.sum()
    return guard + S * w


def phase_closure_vector(n: int) -> np.ndarray:
    """``a_k = (-1)^(n-1-k)``; phase offsets with ``a . x = 0`` preserve ``U_0`` exactly."""
    return np.array([(-1.0) ** (n - 1 - k) for k in range(n)])


def is_frame_trackable(U0: np.ndarray, tol: float = 1e-9) -> tuple[bool, str | None]:
    """True (and the Pauli name) iff ``U0`` is proportional to I, X, Y or Z."""
    for name, P in zip("IXYZ", _PAULIS):
        if abs(abs(np.trace(P.conj().T @ U0)) - 2.0) < tol:
            return True, name
    return False, None


def _split(x: np.ndarray, n: int, mode: str) -> tuple[np.ndarray | None, np.ndarray | None]:
    x = np.asarray(x, dtype=float).ravel()
    if x.size != n_params(n, mode):
        raise ValueError(f"x has {x.size} entries, mode {mode!r} with n={n} needs {n_params(n, mode)}")
    if mode == "timing":
        return x, None
    if mode == "phase":
        return None, x
    return x[:n], x[n:]


def _repair(starts: np.ndarray, width: float, T: float, guard: float, dt: float) -> np.ndarray | None:
    """Deterministic grid repair: forward then backward pass; None if still infeasible."""
    tol = 1e-15 + 1e-12 * T
    k = np.round(starts / dt).astype(np.int64)
    n = k.size
    gk = guard / dt
    wk = width / dt
    # forward: start_j >= end_{j-1} + guard (end_{-1} = 0)
    prev_end = 0.0
    for j in range(n):
        lo = prev_end + gk
        if k[j] < lo - tol / dt:
            k[j] = int(math.ceil(lo - tol / dt))
        prev_end = k[j] + wk
    # backward: end_j <= start_{j+1} - guard (start_n = T)
    nxt = T / dt
    for j in range(n - 1, -1, -1):
        hi = nxt - gk - wk
        if k[j] > hi + tol / dt:
            k[j] = int(math.floor(hi + tol / dt))
        nxt = k[j]
    return k.astype(float) * dt


def decode(
    x: Sequence[float],
    n: int,
    T: float,
    width: float,
    *,
    mode: str,
    guard: float = 0.0,
    base_phases: Sequence[float] | None = None,
    base_x: Sequence[float] | None = None,
    dt_grid: float | None = None,
    phase_closure: bool = True,
    label: str = "optimized",
) -> PulseSequence | None:
    """Map unconstrained ``x`` to a validated ``PulseSequence`` (see module docstring), or
    ``None`` if the candidate is rejected (grid repair failed / non-Pauli ``U_0``).

    * ``mode="timing"``: ``x`` = n timing logits; phases = ``base_phases``.
    * ``mode="phase"``: ``x`` = n phase offsets; timing = ``base_x`` logits (default CPMG).
    * ``mode="both"``: ``x = [z (n), phase offsets (n)]``.
    ``base_phases`` defaults to CPMG (all pi/2). Raises ``ValueError`` for malformed input or
    infeasible ``(n, T, width, guard)``; returns ``None`` only for rejections."""
    if n < 1:
        raise ValueError("n >= 1 required")
    z, dphi = _split(x, n, mode)
    base = np.full(n, seqmod.Y_PHASE) if base_phases is None else np.asarray(base_phases, float)
    if base.shape != (n,):
        raise ValueError("base_phases must have length n")
    if z is None:
        z = encode_cpmg(n, T, width, guard=guard) if base_x is None else np.asarray(base_x, float)
    gaps = _decode_gaps(z, n, T, width, guard)
    if dphi is None:
        phases = base.copy()
    else:
        d = np.asarray(dphi, float)
        if phase_closure:
            a = phase_closure_vector(n)
            d = d - (a @ d) / n * a
        phases = base + d
    phases = np.mod(phases, _TWO_PI)
    meta: dict[str, Any] = {"mode": mode, "grid_repaired": False}
    seq = seqmod.from_gaps(T, width, gaps, list(phases), guard=guard, dt_grid=None, label=label)
    if dt_grid is not None:
        try:
            seq = seqmod.snap_to_grid(seq, dt_grid)
        except ValueError:
            starts = np.asarray(seq.centers) - width / 2
            fixed = _repair(starts, width, T, guard, dt_grid)
            if fixed is None:
                return None
            unsnapped = np.asarray(seq.centers)
            cand = dataclasses.replace(
                seq,
                centers=tuple(float(s + width / 2) for s in fixed),
                dt_grid=float(dt_grid),
                metadata={**seq.metadata,
                          "snap_max_shift_s": float(np.max(np.abs(fixed + width / 2 - unsnapped)))},
            )
            try:
                cand.validate()
            except ValueError:
                return None
            seq = cand
            meta["grid_repaired"] = True
    ok, pauli = is_frame_trackable(seqmod.ideal_unitary(seq))
    if not ok:
        return None
    meta["U0_pauli"] = pauli
    return dataclasses.replace(seq, metadata={**seq.metadata, **meta})


# ---------------------------------------------------------------------------
# objective helpers
# ---------------------------------------------------------------------------


def _same_stochastic_part(a: NoiseModel, b: NoiseModel) -> bool:
    return a.components == b.components and a.T1 == b.T1


def simulate_on_draws(
    seq: PulseSequence,
    noise: NoiseModel,
    config: SimulationConfig,
    draws: dict,
    *,
    noise_true: NoiseModel | None = None,
    return_per_traj: bool = False,
):
    """Simulate ``seq`` on frozen ``draws`` (output of ``simulator.frozen_draws``).

    ``noise`` is the controller's *nominal* model: the virtual-Z angle (if
    ``config.frame_correction == "ideal_control_plus_virtual_z"``) is computed from
    ``noise.detuning``. ``noise_true`` (default = ``noise``) is the physical model; it may only
    differ from ``noise`` in its deterministic ``detuning`` profile. Implementation (public
    simulator API only): the injected stochastic detuning is shifted by
    ``d_true(t) - d_nominal(t)``, so the simulator adds ``d_nominal`` internally and the total
    physical detuning is ``stochastic + d_true`` while the frame uses ``d_nominal``."""
    t = draws["t"]
    delta = draws["delta"]
    if noise_true is not None and noise_true is not noise:
        if not _same_stochastic_part(noise, noise_true):
            raise ValueError("noise_true may differ from the nominal model only in its detuning profile")
        delta = delta + (noise_true.detuning(t) - noise.detuning(t))[None, :]
    return simulate(seq, noise, config, delta_traj=delta, t_grid=t, amp_eps=draws["amp_eps"],
                    phase_err=draws["phase_err"], return_per_traj=return_per_traj)


def draws_fingerprint(draws: dict) -> str:
    """SHA-256 of the frozen draws (t, delta, amp_eps, phase_err) for provenance."""
    h = hashlib.sha256()
    for key in ("t", "delta", "amp_eps", "phase_err"):
        h.update(np.ascontiguousarray(np.asarray(draws[key], dtype=float)).tobytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# CMA-ES driver
# ---------------------------------------------------------------------------


def optimize(
    n: int,
    T: float,
    width: float,
    noise: NoiseModel,
    config: SimulationConfig,
    *,
    mode: str,
    train_draws: dict,
    sigma0: float = 0.3,
    max_evals: int = 2000,
    seed: int,
    x0: Sequence[float] | None = None,
    robust: Sequence[NoiseModel] | None = None,
    guard: float = 0.0,
    dt_grid: float | None = None,
    base_phases: Sequence[float] | None = None,
    base_x: Sequence[float] | None = None,
    train_seeds: Sequence[int] | None = None,
    z_bound: float = 6.0,
    phase_bound: float = 2.0 * math.pi,
    popsize: int | None = None,
    phase_closure: bool = True,
) -> OptimizationResult:
    """CMA-ES minimisation of the training infidelity (frozen draws, CRN).

    * ``x0`` defaults to CPMG-n timing (``encode_cpmg``) and zero phase offsets (base phases,
      default CPMG Y phases), i.e. CMA-ES starts *at* CPMG. ``x0`` is evaluated first and counts
      as one evaluation; the returned best is the best over all evaluations including ``x0``,
      so the training objective of the result is never worse than the start point.
    * Budget: generations are run while ``n_evals + popsize <= max_evals`` (never exceeds it).
    * ``robust``: list of *true* noise models (differing from ``noise`` only in the deterministic
      detuning profile); the objective is the mean infidelity over them with the frame computed
      from the nominal ``noise``. ``None`` -> objective on ``noise`` only.
    * Training draws must match ``config.n_traj`` and cover ``[0, T]``. ``train_seeds`` defaults
      to ``[config.seed]`` (the seed that produced the draws) and is recorded for disjointness
      checks downstream. Test seeds are never used here.
    """
    import cma  # pycma 4.5.0 (pinned in requirements-lock.txt)

    if not isinstance(seed, (int, np.integer)) or seed < 1:
        raise ValueError("optimizer seed must be a positive integer (pycma treats 0/None as time-based)")
    if max_evals < 1:
        raise ValueError("max_evals must be >= 1")
    if np.asarray(train_draws["delta"]).shape[0] != config.n_traj:
        raise ValueError("train_draws n_traj does not match config.n_traj")
    dim = n_params(n, mode)
    if dim < 2:
        raise ValueError("pycma requires dimension >= 2; use n >= 2")
    base = np.full(n, seqmod.Y_PHASE) if base_phases is None else np.asarray(base_phases, float)
    ok, _ = is_frame_trackable(seqmod.ideal_unitary(
        seqmod.from_gaps(T, 0.0, [T / (n + 1)] * (n + 1), list(base))))
    if not ok:
        raise ValueError("base_phases give a non-Pauli ideal unitary (not frame-trackable)")
    if base_x is None and mode == "phase":
        base_x = encode_cpmg(n, T, width, guard=guard)

    lb = np.empty(dim)
    ub = np.empty(dim)
    if mode in ("timing", "both"):
        lb[:n], ub[:n] = -z_bound, z_bound
    if mode == "phase":
        lb[:], ub[:] = -phase_bound, phase_bound
    if mode == "both":
        lb[n:], ub[n:] = -phase_bound, phase_bound

    if x0 is None:
        parts = []
        if mode in ("timing", "both"):
            parts.append(encode_cpmg(n, T, width, guard=guard))
        if mode in ("phase", "both"):
            parts.append(np.zeros(n))
        x0 = np.concatenate(parts)
    x0 = np.asarray(x0, dtype=float)
    if x0.shape != (dim,):
        raise ValueError(f"x0 must have shape ({dim},)")
    if np.any(x0 < lb) or np.any(x0 > ub):
        raise ValueError("x0 outside bounds")

    models = list(robust) if robust else [noise]
    stats = {"evals": 0, "rejected": 0, "repaired": 0}

    def objective(x: np.ndarray) -> float:
        stats["evals"] += 1
        seq = decode(x, n, T, width, mode=mode, guard=guard, base_phases=base, base_x=base_x,
                     dt_grid=dt_grid, phase_closure=phase_closure)
        if seq is None:
            stats["rejected"] += 1
            return REJECT_PENALTY
        if seq.metadata.get("grid_repaired"):
            stats["repaired"] += 1
        vals = [simulate_on_draws(seq, noise, config, train_draws, noise_true=m).infidelity
                for m in models]
        return float(np.mean(vals))

    saved_state = np.random.get_state()
    t_start = time.perf_counter()
    try:
        f0 = objective(x0)
        best_f, best_x = f0, x0.copy()
        history: list[dict[str, Any]] = [{
            "generation": 0, "n_evals": stats["evals"], "best": f0, "best_so_far": f0,
            "median": f0, "sigma": float(sigma0), "n_rejected": stats["rejected"],
        }]
        opts: dict[str, Any] = {"seed": int(seed), "bounds": [lb.tolist(), ub.tolist()],
                                "verbose": -9, "verb_log": 0, "verb_disp": 0,
                                "maxfevals": max_evals, "tolfun": 0.0, "tolfunhist": 0.0,
                                "tolx": 1e-12}
        if popsize is not None:
            opts["popsize"] = int(popsize)
        stop_reason = "budget"
        es = cma.CMAEvolutionStrategy(x0.tolist(), float(sigma0), opts)
        lam = es.popsize
        gen = 0
        while stats["evals"] + lam <= max_evals:
            stop = es.stop()
            if stop:
                stop_reason = ",".join(sorted(stop.keys()))
                break
            X = es.ask()
            F = [objective(np.asarray(xi)) for xi in X]
            es.tell(X, F)
            gen += 1
            i = int(np.argmin(F))
            if F[i] < best_f:
                best_f, best_x = float(F[i]), np.asarray(X[i], dtype=float).copy()
            history.append({
                "generation": gen, "n_evals": stats["evals"], "best": float(F[i]),
                "best_so_far": best_f, "median": float(np.median(F)), "sigma": float(es.sigma),
                "n_rejected": stats["rejected"],
            })
    finally:
        np.random.set_state(saved_state)
    wall = time.perf_counter() - t_start

    best_seq = decode(best_x, n, T, width, mode=mode, guard=guard, base_phases=base, base_x=base_x,
                      dt_grid=dt_grid, phase_closure=phase_closure)
    if best_seq is None:  # only if x0 itself was rejected and nothing better was found
        raise RuntimeError("no feasible candidate found (all rejected)")
    return OptimizationResult(
        best_sequence=best_seq,
        best_train_infidelity=best_f,
        history=history,
        n_evaluations=stats["evals"],
        wall_time_s=wall,
        optimizer_seed=int(seed),
        train_seeds=[int(s) for s in (train_seeds if train_seeds is not None else [config.seed])],
        mode=mode,
        x_best=[float(v) for v in best_x],
        provenance={
            "algorithm": "CMA-ES (pycma ask/tell)",
            "cma_version": getattr(cma, "__version__", "unknown"),
            "sigma0": float(sigma0),
            "popsize": int(lam),
            "max_evals": int(max_evals),
            "stop_reason": stop_reason,
            "n_rejected": stats["rejected"],
            "n_grid_repaired": stats["repaired"],
            "reject_penalty": REJECT_PENALTY,
            "x0": [float(v) for v in x0],
            "start_train_infidelity": f0,
            "bounds": {"z": float(z_bound), "phase": float(phase_bound)},
            "phase_closure": bool(phase_closure),
            "base_phases": [float(p) for p in base],
            "base_x": None if base_x is None else [float(v) for v in base_x],
            "n": n, "T": T, "width": width, "guard": guard, "dt_grid": dt_grid,
            "frame_correction": config.frame_correction,
            "n_traj_train": int(config.n_traj),
            "train_draws_sha256": draws_fingerprint(train_draws),
            "robust_n_models": len(models),
            "time_per_eval_s": wall / max(stats["evals"], 1),
        },
    )
