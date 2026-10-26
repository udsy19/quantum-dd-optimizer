"""Baselines, held-out evaluation and paired statistics (Agent D).

Pre-registration: ``docs/EXPERIMENT_PLAN.md``. Key rules implemented here:

* **Fair baselines.** Canonical families at the *same* n, T, pulse width, guard, clock grid,
  noise model, test draws and frame-correction privileges as the optimised sequence.
* **Selection before testing.** ``select_baseline`` picks the strongest canonical DD family by
  *training* infidelity only (frozen training draws); free evolution and the Hahn reference are
  never eligible. The choice is fixed before any test evaluation.
* **Held-out evaluation.** ``evaluate`` regenerates draws from test seeds that must be disjoint
  from the training seeds (enforced), and evaluates **every** sequence on the **same** draws for
  a given seed (paired design). Per-trajectory infidelities are returned for paired statistics.
* **Statistics.** Paired percentile bootstrap (trajectories resampled jointly for both arms;
  across seeds, seeds resampled as blocks and trajectories within each). We always report raw
  infidelities, ratio (eps_a / eps_b), reduction (1 - eps_b / eps_a) and difference with 95 %
  percentile intervals. These quantify Monte-Carlo uncertainty of the synthetic estimate given
  the model; they are **not** significance tests and do not account for model selection or
  model misspecification.

Per-trajectory infidelity: the simulator's channel infidelity equals the mean of the
per-trajectory infidelities (F_avg is linear in the channel), so mean-of-per-trajectory values
is the estimator used in the bootstrap.
"""

from __future__ import annotations

import dataclasses
import math
import time
from typing import Any, Mapping, Sequence

import numpy as np

from ddopt import sequences as seqmod
from ddopt.contracts import NoiseModel, PulseSequence, SimulationConfig
from ddopt.optimizer import (
    decode,
    draws_fingerprint,
    encode_cpmg,
    optimize,
    simulate_on_draws,
)
from ddopt.simulator import frozen_draws

__all__ = [
    "DD_FAMILIES",
    "canonical_baselines",
    "baseline_train_scores",
    "select_baseline",
    "check_disjoint",
    "evaluate",
    "evaluate_arms",
    "paired_bootstrap",
    "pooled_comparison",
    "scenario_b_arms",
    "perturbed_detuning_models",
    "robustness_sweep",
    "run_benchmark",
]

DD_FAMILIES = ("cpmg", "xy4", "xy8", "udd")  # eligible for "strongest baseline" selection
REFERENCE = ("free", "hahn")  # reported, never selected


# ---------------------------------------------------------------------------
# baselines
# ---------------------------------------------------------------------------


def canonical_baselines(
    n: int,
    T: float,
    width: float,
    *,
    guard: float = 0.0,
    dt_grid: float | None = None,
    include_hahn: bool = True,
    omitted: dict[str, str] | None = None,
) -> dict[str, PulseSequence]:
    """``free``, ``cpmg``, ``xy4`` (n%4==0), ``xy8`` (n%8==0), ``udd`` at ``n`` pulses, plus the
    ``hahn`` reference (n=1, not an equal-n competitor), all with the same width/guard/grid
    (starts snapped to ``dt_grid``). Families that are not applicable or infeasible are left out;
    pass a dict as ``omitted`` to receive ``{name: reason}``."""
    reasons: dict[str, str] = {} if omitted is None else omitted
    out: dict[str, PulseSequence] = {}
    kw = {"guard": guard, "dt_grid": dt_grid}
    builders = {
        "free": lambda: seqmod.free(T, **kw),
        "cpmg": lambda: seqmod.cpmg(n, T, width, **kw),
        "xy4": lambda: seqmod.xy4(n, T, width, **kw),
        "xy8": lambda: seqmod.xy8(n, T, width, **kw),
        "udd": lambda: seqmod.udd(n, T, width, **kw),
    }
    if include_hahn:
        builders["hahn"] = lambda: seqmod.hahn(T, width, **kw)
    for name, build in builders.items():
        if name == "xy4" and n % 4:
            reasons[name] = f"not applicable: n={n} not a multiple of 4"
            continue
        if name == "xy8" and n % 8:
            reasons[name] = f"not applicable: n={n} not a multiple of 8"
            continue
        try:
            out[name] = build()
        except ValueError as exc:
            reasons[name] = f"infeasible: {exc}"
    return out


def baseline_train_scores(
    baselines: Mapping[str, PulseSequence], noise: NoiseModel, config: SimulationConfig, train_draws: dict
) -> dict[str, dict[str, float]]:
    """Training infidelity (and MC stderr) of each baseline on the frozen training draws."""
    out = {}
    for name, seq in baselines.items():
        r = simulate_on_draws(seq, noise, config, train_draws, return_per_traj=False)
        out[name] = {"infidelity": r.infidelity, "stderr": r.infidelity_stderr,
                     "virtual_z_angle": r.virtual_z_angle}
    return out


def select_baseline(
    baselines: Mapping[str, PulseSequence],
    noise: NoiseModel,
    config: SimulationConfig,
    train_draws: dict,
    *,
    return_scores: bool = False,
):
    """Pre-registered rule: the DD family (``DD_FAMILIES``; never free/hahn) with the lowest
    **training** infidelity. Ties -> first in ``DD_FAMILIES`` order. Uses ``train_draws`` only."""
    eligible = {k: v for k, v in baselines.items() if k in DD_FAMILIES}
    if not eligible:
        raise ValueError("no eligible canonical DD baseline")
    scores = baseline_train_scores(eligible, noise, config, train_draws)
    order = [k for k in DD_FAMILIES if k in scores]
    best = min(order, key=lambda k: (scores[k]["infidelity"], order.index(k)))
    return (best, scores) if return_scores else best


# ---------------------------------------------------------------------------
# held-out evaluation
# ---------------------------------------------------------------------------


def check_disjoint(test_seeds: Sequence[int], train_seeds: Sequence[int]) -> None:
    """Raise ``ValueError`` if any test seed is also a training (or other excluded) seed."""
    overlap = sorted(set(int(s) for s in test_seeds) & set(int(s) for s in train_seeds))
    if overlap:
        raise ValueError(f"test seeds overlap training seeds: {overlap}")
    if len(set(test_seeds)) != len(list(test_seeds)):
        raise ValueError("duplicate test seeds")


def _item(v) -> tuple[PulseSequence, str | None]:
    if isinstance(v, PulseSequence):
        return v, None
    seq, frame = v
    return seq, frame


def evaluate_arms(
    arms: Mapping[str, Any],
    noise: NoiseModel,
    config: SimulationConfig,
    test_seeds: Sequence[int],
    n_traj: int | None = None,
    *,
    train_seeds: Sequence[int] | None = None,
    noise_true: NoiseModel | None = None,
    keep_per_traj: bool = True,
) -> dict[str, Any]:
    """Like ``evaluate`` but each arm is ``PulseSequence`` or ``(PulseSequence, frame_correction)``
    (frame ``None`` -> ``config.frame_correction``), so no-DD and virtual-Z-only arms can share
    draws. ``noise`` is the controller's nominal model (virtual-Z angle), ``noise_true`` the
    physical model (default nominal; may differ only in the detuning profile)."""
    if train_seeds is None:
        raise ValueError("train_seeds must be given so that test/train disjointness can be enforced")
    check_disjoint(test_seeds, train_seeds)
    items = {k: _item(v) for k, v in arms.items()}
    Ts = {seq.T for seq, _ in items.values()}
    if len(Ts) != 1:
        raise ValueError(f"all sequences must share the same window T, got {sorted(Ts)}")
    T = Ts.pop()
    nt = config.n_traj if n_traj is None else int(n_traj)
    per_seed: dict[str, dict[str, Any]] = {k: {} for k in items}
    t0 = time.perf_counter()
    fps = {}
    for s in test_seeds:
        cfg_s = dataclasses.replace(config, seed=int(s), n_traj=nt)
        draws = frozen_draws(noise, T, cfg_s)  # identical draws for every arm (paired)
        fps[int(s)] = draws_fingerprint(draws)
        for name, (seq, frame) in items.items():
            c = cfg_s if frame is None else dataclasses.replace(cfg_s, frame_correction=frame)
            r = simulate_on_draws(seq, noise, c, draws, noise_true=noise_true, return_per_traj=True)
            entry = {"infidelity": r.infidelity, "stderr": r.infidelity_stderr,
                     "virtual_z_angle": r.virtual_z_angle, "frame_correction": c.frame_correction}
            if keep_per_traj:
                entry["per_traj"] = np.asarray(r.per_traj_infidelity)
            per_seed[name][int(s)] = entry
    summary = {}
    for name in items:
        vals = np.array([per_seed[name][int(s)]["infidelity"] for s in test_seeds])
        summary[name] = {
            "mean_over_seeds": float(vals.mean()),
            "sd_over_seeds": float(vals.std(ddof=1)) if vals.size > 1 else float("nan"),
            "per_seed": [float(v) for v in vals],
        }
    return {"per_seed": per_seed, "summary": summary, "test_seeds": [int(s) for s in test_seeds],
            "n_traj": nt, "draws_sha256": fps, "wall_time_s": time.perf_counter() - t0}


def evaluate(
    sequences: Mapping[str, PulseSequence],
    noise: NoiseModel,
    config: SimulationConfig,
    test_seeds: Sequence[int],
    n_traj: int | None = None,
    *,
    train_seeds: Sequence[int] | None = None,
    noise_true: NoiseModel | None = None,
    keep_per_traj: bool = True,
) -> dict[str, Any]:
    """Held-out paired evaluation: for each test seed, one set of draws
    (``frozen_draws(noise, T, config(seed, n_traj))``) shared by all sequences.

    Returns ``{"per_seed": {name: {seed: {infidelity, stderr, per_traj, ...}}}, "summary": ...}``.
    ``train_seeds`` is required (keyword) and must be disjoint from ``test_seeds``."""
    return evaluate_arms(sequences, noise, config, test_seeds, n_traj, train_seeds=train_seeds,
                         noise_true=noise_true, keep_per_traj=keep_per_traj)


# ---------------------------------------------------------------------------
# paired bootstrap
# ---------------------------------------------------------------------------


def _stats(ma: np.ndarray, mb: np.ndarray) -> dict[str, np.ndarray]:
    with np.errstate(divide="ignore", invalid="ignore"):
        return {"ratio": ma / mb, "reduction": 1.0 - mb / ma, "difference": ma - mb}


def _summarise(point: dict, boot: dict, alpha: float, extra: dict) -> dict[str, Any]:
    out: dict[str, Any] = dict(extra)
    lo, hi = 100 * alpha / 2, 100 * (1 - alpha / 2)
    for k in ("ratio", "reduction", "difference"):
        b = boot[k][np.isfinite(boot[k])]
        out[k] = float(point[k])
        out[f"{k}_ci"] = [float(np.percentile(b, lo)), float(np.percentile(b, hi))] if b.size else [math.nan, math.nan]
    out["ci_level"] = 1 - alpha
    out["ci_method"] = "percentile bootstrap (paired)"
    return out


def paired_bootstrap(
    eps_a_per_traj: Sequence[float],
    eps_b_per_traj: Sequence[float],
    n_boot: int,
    rng: np.random.Generator,
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Paired percentile bootstrap over trajectories (same index resampled for both arms).

    Point estimates use the means ``eps_a``, ``eps_b`` of the per-trajectory infidelities:
    ``ratio = eps_a / eps_b`` (improvement factor if a = baseline, b = optimised),
    ``reduction = 1 - eps_b / eps_a``, ``difference = eps_a - eps_b``."""
    a = np.asarray(eps_a_per_traj, dtype=float)
    b = np.asarray(eps_b_per_traj, dtype=float)
    if a.shape != b.shape or a.ndim != 1 or a.size < 2:
        raise ValueError("paired arrays must be 1-D, equal length >= 2")
    n = a.size
    ma_b = np.empty(n_boot)
    mb_b = np.empty(n_boot)
    chunk = max(1, int(2e6 // n))
    for i in range(0, n_boot, chunk):
        m = min(chunk, n_boot - i)
        idx = rng.integers(0, n, size=(m, n))
        ma_b[i:i + m] = a[idx].mean(axis=1)
        mb_b[i:i + m] = b[idx].mean(axis=1)
    ma, mb = a.mean(), b.mean()
    extra = {
        "eps_a": float(ma), "eps_b": float(mb),
        "eps_a_stderr": float(a.std(ddof=1) / math.sqrt(n)),
        "eps_b_stderr": float(b.std(ddof=1) / math.sqrt(n)),
        "eps_a_ci": [float(np.percentile(ma_b, 100 * alpha / 2)), float(np.percentile(ma_b, 100 * (1 - alpha / 2)))],
        "eps_b_ci": [float(np.percentile(mb_b, 100 * alpha / 2)), float(np.percentile(mb_b, 100 * (1 - alpha / 2)))],
        "n_traj": n, "n_boot": int(n_boot),
    }
    return _summarise(_stats(np.array(ma), np.array(mb)), _stats(ma_b, mb_b), alpha, extra)


def pooled_comparison(
    eps_a_by_seed: Sequence[Sequence[float]],
    eps_b_by_seed: Sequence[Sequence[float]],
    n_boot: int,
    rng: np.random.Generator,
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Pooled paired comparison across independent test seeds (two-stage block bootstrap):
    resample seeds with replacement (blocks), then trajectories within each selected seed,
    jointly for both arms. Pooled estimate = mean over seeds of per-seed mean infidelity.
    With few seeds (e.g. 5) the seed-level resampling is coarse; report per-seed values too."""
    A = [np.asarray(x, float) for x in eps_a_by_seed]
    B = [np.asarray(x, float) for x in eps_b_by_seed]
    if len(A) != len(B) or not A:
        raise ValueError("need the same, nonzero number of seeds for both arms")
    for x, y in zip(A, B):
        if x.shape != y.shape or x.ndim != 1:
            raise ValueError("per-seed arrays must be paired 1-D arrays")
    k = len(A)
    ma_b = np.empty(n_boot)
    mb_b = np.empty(n_boot)
    for i in range(n_boot):
        sel = rng.integers(0, k, size=k)
        sa = sb = 0.0
        for j in sel:
            idx = rng.integers(0, A[j].size, size=A[j].size)
            sa += A[j][idx].mean()
            sb += B[j][idx].mean()
        ma_b[i], mb_b[i] = sa / k, sb / k
    ma = float(np.mean([x.mean() for x in A]))
    mb = float(np.mean([y.mean() for y in B]))
    extra = {
        "eps_a": ma, "eps_b": mb,
        "eps_a_per_seed": [float(x.mean()) for x in A],
        "eps_b_per_seed": [float(y.mean()) for y in B],
        "eps_a_ci": [float(np.percentile(ma_b, 100 * alpha / 2)), float(np.percentile(ma_b, 100 * (1 - alpha / 2)))],
        "eps_b_ci": [float(np.percentile(mb_b, 100 * alpha / 2)), float(np.percentile(mb_b, 100 * (1 - alpha / 2)))],
        "n_seeds": k, "n_boot": int(n_boot),
    }
    out = _summarise(_stats(np.array(ma), np.array(mb)), _stats(ma_b, mb_b), alpha, extra)
    out["ci_method"] = "two-stage paired bootstrap (seeds as blocks, trajectories within)"
    return out


# ---------------------------------------------------------------------------
# Scenario B
# ---------------------------------------------------------------------------


def scenario_b_arms(
    T: float,
    *,
    best_dd: PulseSequence,
    optimized: PulseSequence | None = None,
    guard: float = 0.0,
    dt_grid: float | None = None,
) -> dict[str, tuple[PulseSequence, str]]:
    """Pre-registered Scenario B arms: (1) no DD, no frame correction; (2) virtual-Z only
    (free evolution + virtual-Z from the nominal profile); (3) best canonical DD + virtual-Z;
    (4) optimised DD + virtual-Z (if given). Values are ``(sequence, frame_correction)``."""
    vz = "ideal_control_plus_virtual_z"
    f = seqmod.free(T, guard=guard, dt_grid=dt_grid)
    arms = {
        "1_no_dd": (f, "ideal_control"),
        "2_virtual_z_only": (f, vz),
        f"3_{best_dd.label}_plus_vz": (best_dd, vz),
    }
    if optimized is not None:
        arms["4_optimized_plus_vz"] = (optimized, vz)
    return arms


def perturbed_detuning_models(
    noise: NoiseModel,
    amplitude_scales: Sequence[float] = (0.8, 0.9, 1.0, 1.1, 1.2),
    time_shifts: Sequence[float] = (-1e-7, -5e-8, 0.0, 5e-8, 1e-7),
) -> dict[str, NoiseModel]:
    """One-dimensional perturbation sweeps of the deterministic profile: amplitude scaled
    (``amp_x<s>``) and ``t_on``/``t_off`` shifted together (``shift_<ns>ns``)."""
    d = noise.detuning
    out: dict[str, NoiseModel] = {}
    for s in amplitude_scales:
        out[f"amp_x{s:g}"] = dataclasses.replace(noise, detuning=dataclasses.replace(d, amplitude=d.amplitude * s))
    for sh in time_shifts:
        out[f"shift_{sh * 1e9:+g}ns"] = dataclasses.replace(
            noise, detuning=dataclasses.replace(d, t_on=d.t_on + sh, t_off=d.t_off + sh))
    return out


def robustness_sweep(
    arms: Mapping[str, Any],
    noise_nominal: NoiseModel,
    config: SimulationConfig,
    test_seeds: Sequence[int],
    n_traj: int | None = None,
    *,
    train_seeds: Sequence[int],
    perturbations: Mapping[str, NoiseModel] | None = None,
) -> dict[str, Any]:
    """Evaluate all arms under each perturbed *true* detuning profile while the virtual-Z angle
    is computed from ``noise_nominal`` (controller assumes nominal). Same test draws per seed for
    all arms and perturbations."""
    perts = perturbed_detuning_models(noise_nominal) if perturbations is None else perturbations
    out = {}
    for pname, nt in perts.items():
        res = evaluate_arms(arms, noise_nominal, config, test_seeds, n_traj, train_seeds=train_seeds,
                            noise_true=nt, keep_per_traj=False)
        out[pname] = {"detuning": nt.detuning.to_dict(), "summary": res["summary"]}
    return out


# ---------------------------------------------------------------------------
# benchmark driver
# ---------------------------------------------------------------------------


def _strip(per_seed: dict) -> dict:
    return {name: {str(s): {k: v for k, v in e.items() if k != "per_traj"} for s, e in d.items()}
            for name, d in per_seed.items()}


def run_benchmark(
    cfg: dict,
    n: int,
    mode: str,
    train_seed: int,
    opt_seed: int,
    test_seeds: Sequence[int],
    *,
    max_evals: int,
    n_traj_train: int,
    n_traj_test: int,
    T: float | None = None,
    sigma0: float | None = None,
    frame_correction: str | None = None,
    n_boot: int = 2000,
    boot_seed: int = 5003,
    robust: Sequence[NoiseModel] | None = None,
    scenario_b: bool | None = None,
    robustness: bool = False,
) -> dict[str, Any]:
    """One pre-registered benchmark run (JSON-friendly result).

    Steps: (1) frozen training draws from ``train_seed``; (2) canonical baselines and their
    training scores; (3) strongest baseline fixed by the training-only rule; (4) CMA-ES from
    CPMG with ``opt_seed``; (5) held-out paired evaluation of all baselines + optimised on
    ``test_seeds`` (disjoint from ``train_seed`` and ``opt_seed``, enforced); (6) paired
    bootstrap per seed and pooled, optimised vs selected and vs every baseline.
    ``frame_correction`` defaults to virtual-Z iff the scenario has a deterministic detuning.
    For such scenarios the four Scenario B arms are also evaluated (and, if ``robustness``,
    the perturbation sweep with nominal-profile virtual-Z)."""
    from ddopt.scenarios import scenario_noise, sim_config

    t_start = time.perf_counter()
    win = cfg["window"]
    T = float(win["T"] if T is None else T)
    width, guard, dt_grid = float(win["width"]), float(win["guard"]), win.get("dt_grid")
    sigma0 = float(cfg.get("optimizer", {}).get("sigma0", 0.3) if sigma0 is None else sigma0)
    noise = scenario_noise(cfg)
    has_det = noise.detuning.kind != "none"
    if frame_correction is None:
        frame_correction = "ideal_control_plus_virtual_z" if has_det else "ideal_control"
    if scenario_b is None:
        scenario_b = has_det
    check_disjoint(test_seeds, [train_seed, opt_seed])

    cfg_train = sim_config(cfg, seed=int(train_seed), n_traj=int(n_traj_train),
                           frame_correction=frame_correction)
    train_draws = frozen_draws(noise, T, cfg_train)

    omitted: dict[str, str] = {}
    baselines = canonical_baselines(n, T, width, guard=guard, dt_grid=dt_grid, omitted=omitted)
    train_scores = baseline_train_scores(baselines, noise, cfg_train, train_draws)
    selected = select_baseline(baselines, noise, cfg_train, train_draws)

    res = optimize(n, T, width, noise, cfg_train, mode=mode, train_draws=train_draws, sigma0=sigma0,
                   max_evals=int(max_evals), seed=int(opt_seed), robust=robust, guard=guard,
                   dt_grid=dt_grid, train_seeds=[int(train_seed)])
    opt_seq = res.best_sequence
    # start point must coincide with the CPMG baseline (fair "starts at CPMG" claim)
    start_seq = decode(encode_cpmg(n, T, width, guard=guard), n, T, width, mode="timing", guard=guard,
                       dt_grid=dt_grid)
    start_matches = ("cpmg" in baselines and start_seq is not None and
                     np.allclose(start_seq.centers, baselines["cpmg"].centers, rtol=0, atol=1e-15))

    seqs = dict(baselines)
    seqs["optimized"] = opt_seq
    ev = evaluate(seqs, noise, sim_config(cfg, seed=0, n_traj=int(n_traj_test), frame_correction=frame_correction),
                  test_seeds, n_traj_test, train_seeds=[int(train_seed), int(opt_seed)])
    rng = np.random.default_rng(boot_seed)
    comps: dict[str, Any] = {}
    for name in baselines:
        per_seed = {}
        for s in test_seeds:
            per_seed[str(s)] = paired_bootstrap(ev["per_seed"][name][int(s)]["per_traj"],
                                                ev["per_seed"]["optimized"][int(s)]["per_traj"], n_boot, rng)
        pooled = pooled_comparison([ev["per_seed"][name][int(s)]["per_traj"] for s in test_seeds],
                                   [ev["per_seed"]["optimized"][int(s)]["per_traj"] for s in test_seeds],
                                   n_boot, rng)
        comps[name] = {"per_seed": per_seed, "pooled": pooled,
                       "convention": "a = baseline, b = optimized; ratio = eps_base/eps_opt"}

    opt_test = ev["summary"]["optimized"]["mean_over_seeds"]
    sel_test = ev["summary"][selected]["mean_over_seeds"]
    out: dict[str, Any] = {
        "scenario": cfg.get("_path", cfg.get("description", "")),
        "n": n, "mode": mode, "T": T, "width": width, "guard": guard, "dt_grid": dt_grid,
        "frame_correction": frame_correction,
        "seeds": {"train": int(train_seed), "optimizer": int(opt_seed), "test": [int(s) for s in test_seeds],
                  "bootstrap": int(boot_seed)},
        "n_traj_train": int(n_traj_train), "n_traj_test": int(n_traj_test),
        "baselines_omitted": omitted,
        "baselines_train": train_scores,
        "selected_baseline": selected,
        "selection_rule": "lowest training infidelity among " + ",".join(DD_FAMILIES) + " (pre-registered)",
        "optimization": {
            "best_train_infidelity": res.best_train_infidelity,
            "start_train_infidelity": res.provenance["start_train_infidelity"],
            "start_matches_cpmg_baseline": bool(start_matches),
            "n_evaluations": res.n_evaluations,
            "wall_time_s": res.wall_time_s,
            "history": res.history,
            "x_best": res.x_best,
            "best_sequence": opt_seq.to_dict(),
            "provenance": res.provenance,
        },
        "test": {"summary": ev["summary"], "per_seed": _strip(ev["per_seed"]),
                 "draws_sha256": {str(k): v for k, v in ev["draws_sha256"].items()}},
        "comparisons": comps,
        "comparison_vs_selected": comps.get(selected),
        "train_test_gap": {
            "optimized": {"train": res.best_train_infidelity, "test": opt_test,
                          "test_minus_train": opt_test - res.best_train_infidelity},
            "selected_baseline": {"train": train_scores[selected]["infidelity"], "test": sel_test,
                                  "test_minus_train": sel_test - train_scores[selected]["infidelity"]},
        },
        "notes": [
            "Synthetic model; MC bootstrap CIs only, not significance tests; no hardware.",
            "Selected baseline fixed from training draws before test evaluation.",
        ],
    }
    if scenario_b:
        arms = scenario_b_arms(T, best_dd=baselines[selected], optimized=opt_seq, guard=guard, dt_grid=dt_grid)
        ev_cfg = sim_config(cfg, seed=0, n_traj=int(n_traj_test))
        evb = evaluate_arms(arms, noise, ev_cfg, test_seeds, n_traj_test, train_seeds=[int(train_seed), int(opt_seed)])
        out["scenario_b_arms"] = {"summary": evb["summary"], "per_seed": _strip(evb["per_seed"])}
        if robustness:
            perts = None
            rb = cfg.get("robustness")
            if rb:
                perts = perturbed_detuning_models(noise, rb["amplitude_scale"], rb["time_shift"])
            out["scenario_b_robustness"] = robustness_sweep(
                arms, noise, ev_cfg, test_seeds, n_traj_test,
                train_seeds=[int(train_seed), int(opt_seed)], perturbations=perts)
    out["wall_time_s"] = time.perf_counter() - t_start
    out["n_simulations_note"] = ("optimizer evaluations = n_evaluations x len(robust or [noise]); "
                                 "plus baseline training and test evaluations")
    return out
