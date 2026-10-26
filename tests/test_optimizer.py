"""Tests for ddopt.optimizer (Agent D). Tiny budgets; development seeds only (7000+)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ddopt import sequences as seqmod
from ddopt import optimizer as opt
from ddopt.contracts import ControlErrors, DetuningProfile, NoiseModel, PSDComponent, SimulationConfig
from ddopt.noise import make_lorentzian, make_one_over_f
from ddopt.simulator import frozen_draws, simulate, virtual_z_angle

T, W, G, DT = 2e-6, 3.2e-8, 4e-9, 4e-9


def _toy_noise(detuning: DetuningProfile | None = None) -> NoiseModel:
    # quasi-static (tau_c >> T) + 1/f, synthetic toy values
    comps = (
        make_lorentzian(2 * math.pi * 0.15e6, 1e-3),
        make_one_over_f(4e9, 1.0, 2 * math.pi * 1e2, 2 * math.pi * 20e6),
    )
    return NoiseModel(components=comps, detuning=detuning or DetuningProfile(), T1=math.inf)


def _toy_config(seed: int = 7001, n_traj: int = 32, **kw) -> SimulationConfig:
    return SimulationConfig(n_traj=n_traj, seed=seed, noise_dt=2e-9, pulse_steps=4, include_T1=False,
                            control_errors=ControlErrors(amp_rel_std=0.01), **kw)


# ---------------------------------------------------------------------------
# decode / encode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", opt.MODES)
@pytest.mark.parametrize("n", [3, 4, 8, 16])
def test_decode_random_valid_grid_aligned(mode, n):
    rng = np.random.default_rng(7100 + n)
    dim = opt.n_params(n, mode)
    n_ok = 0
    for _ in range(40):
        x = rng.uniform(-6, 6, size=dim)
        seq = opt.decode(x, n, T, W, mode=mode, guard=G, dt_grid=DT)
        if seq is None:
            continue
        n_ok += 1
        seq.validate()  # ordered, non-overlapping, guard, grid
        assert seq.n == n and seq.dt_grid == DT
        starts = np.asarray(seq.centers) - W / 2
        assert np.allclose(starts / DT, np.round(starts / DT), atol=1e-6)
        gaps = seq.gaps()
        assert np.all(gaps >= G - 1e-15)
        assert abs(gaps.sum() + n * W - T) < 1e-15
        assert all(0 <= p < 2 * math.pi for p in seq.phases)
        ok, _ = opt.is_frame_trackable(seqmod.ideal_unitary(seq))
        assert ok
    assert n_ok >= 30  # rejections must be rare at these settings


def test_decode_tight_window_repair_or_reject():
    # 3 pulses, slack of only 2 ns: snapping often breaks the guard -> repaired or rejected
    n, w, g, dt = 3, 8e-9, 4e-9, 4e-9
    Tt = n * w + (n + 1) * g + 2e-9
    rng = np.random.default_rng(7200)
    outcomes = {"ok": 0, "repaired": 0, "rejected": 0}
    for _ in range(100):
        seq = opt.decode(rng.normal(size=n) * 3, n, Tt, w, mode="timing", guard=g, dt_grid=dt)
        if seq is None:
            outcomes["rejected"] += 1
            continue
        seq.validate()
        outcomes["repaired" if seq.metadata["grid_repaired"] else "ok"] += 1
    assert sum(outcomes.values()) == 100


@pytest.mark.parametrize("n", [2, 4, 8, 16])
def test_encode_cpmg_round_trip(n):
    z = opt.encode_cpmg(n, T, W, guard=G)
    a = opt.decode(z, n, T, W, mode="timing", guard=G)
    b = seqmod.cpmg(n, T, W, guard=G)
    assert np.allclose(a.centers, b.centers, rtol=0, atol=1e-15)
    assert np.allclose(a.phases, b.phases)
    ag = opt.decode(z, n, T, W, mode="timing", guard=G, dt_grid=DT)
    bg = seqmod.cpmg(n, T, W, guard=G, dt_grid=DT)
    assert np.allclose(ag.centers, bg.centers, rtol=0, atol=1e-15)


def test_encode_gaps_inverse():
    rng = np.random.default_rng(7300)
    n = 7
    S = opt.slack(n, T, W, G)
    w = rng.dirichlet(np.ones(n + 1))
    gaps = G + S * w
    z = opt.encode_gaps(gaps, T, W, guard=G)
    seq = opt.decode(z, n, T, W, mode="timing", guard=G)
    assert np.allclose(seq.gaps(), gaps, rtol=0, atol=1e-18)


@pytest.mark.parametrize("n", [3, 4, 5, 8])
def test_phase_closure_preserves_ideal_unitary(n):
    rng = np.random.default_rng(7400 + n)
    base = [seqmod.Y_PHASE] * n
    U_base = seqmod.ideal_unitary(seqmod.cpmg(n, T, W, guard=G))
    for _ in range(10):
        seq = opt.decode(rng.uniform(-3, 3, size=n), n, T, W, mode="phase", guard=G, base_phases=base)
        U = seqmod.ideal_unitary(seq)
        assert abs(abs(np.trace(U_base.conj().T @ U)) - 2) < 1e-9


def test_without_closure_non_pauli_rejected():
    rng = np.random.default_rng(7500)
    seq = opt.decode(rng.uniform(-3, 3, size=4), 4, T, W, mode="phase", guard=G, phase_closure=False)
    assert seq is None


def test_phase_mode_uses_base_timing():
    n = 8
    seq = opt.decode(np.zeros(n), n, T, W, mode="phase", guard=G, dt_grid=DT)
    assert np.allclose(seq.centers, seqmod.cpmg(n, T, W, guard=G, dt_grid=DT).centers, atol=1e-15)


def test_decode_bad_input():
    with pytest.raises(ValueError):
        opt.decode(np.zeros(3), 4, T, W, mode="timing", guard=G)
    with pytest.raises(ValueError):
        opt.decode(np.zeros(16), 16, 5e-7, 4e-8, mode="timing", guard=G)  # infeasible window


# ---------------------------------------------------------------------------
# simulate_on_draws (nominal-frame workaround)
# ---------------------------------------------------------------------------


def test_simulate_on_draws_matches_simulate_and_nominal_frame():
    det = DetuningProfile("smooth_rect", 2 * math.pi * 0.2e6, 0.6e-6, 1.6e-6, 2e-8)
    nominal = _toy_noise(det)
    true = NoiseModel(nominal.components, DetuningProfile("smooth_rect", 2 * math.pi * 0.24e6, 0.65e-6, 1.65e-6, 2e-8),
                      nominal.T1)
    cfg = _toy_config(frame_correction="ideal_control_plus_virtual_z")
    d = frozen_draws(nominal, T, cfg)
    seq = seqmod.xy4(4, T, W, guard=G, dt_grid=DT)
    r0 = opt.simulate_on_draws(seq, nominal, cfg, d)
    r_ref = simulate(seq, nominal, cfg)  # internal sampling with the same seed -> same draws
    assert r0.infidelity == pytest.approx(r_ref.infidelity, rel=1e-12)
    r1 = opt.simulate_on_draws(seq, nominal, cfg, d, noise_true=true)
    assert r1.virtual_z_angle == pytest.approx(virtual_z_angle(seq, nominal, cfg))
    # without frame correction the result must equal simulating the true model directly
    cfg0 = _toy_config()
    r2 = opt.simulate_on_draws(seq, nominal, cfg0, d, noise_true=true)
    r3 = simulate(seq, true, cfg0, delta_traj=d["delta"], t_grid=d["t"], amp_eps=d["amp_eps"],
                  phase_err=d["phase_err"])
    assert r2.infidelity == pytest.approx(r3.infidelity, rel=1e-10)
    with pytest.raises(ValueError):
        opt.simulate_on_draws(seq, nominal, cfg, d, noise_true=NoiseModel((), det, math.inf))


# ---------------------------------------------------------------------------
# optimize
# ---------------------------------------------------------------------------


def _run(seed=1, mode="timing", max_evals=40, n=4, robust=None, noise=None):
    noise = noise or _toy_noise()
    cfg = _toy_config()
    d = frozen_draws(noise, 1e-6, cfg)
    return opt.optimize(n, 1e-6, 2e-8, noise, cfg, mode=mode, train_draws=d, sigma0=0.3,
                        max_evals=max_evals, seed=seed, guard=G, dt_grid=DT, robust=robust), d, cfg, noise


def test_optimizer_deterministic():
    a, *_ = _run(seed=3)
    b, *_ = _run(seed=3)
    assert a.x_best == b.x_best
    assert a.best_train_infidelity == b.best_train_infidelity
    strip = lambda h: [{k: v for k, v in g.items()} for g in h]  # noqa: E731
    assert strip(a.history) == strip(b.history)


def test_optimizer_global_rng_untouched():
    np.random.seed(12345)
    before = np.random.get_state()[1].copy()
    _run(seed=2, max_evals=20)
    assert np.array_equal(np.random.get_state()[1], before)


@pytest.mark.parametrize("mode", opt.MODES)
def test_optimizer_not_worse_than_start(mode):
    res, d, cfg, noise = _run(seed=1, mode=mode, max_evals=60)
    start = res.provenance["start_train_infidelity"]
    cp = seqmod.cpmg(4, 1e-6, 2e-8, guard=G, dt_grid=DT)
    assert start == pytest.approx(opt.simulate_on_draws(cp, noise, cfg, d).infidelity, rel=1e-12)
    assert res.best_train_infidelity <= start
    # returned sequence reproduces its training score
    assert opt.simulate_on_draws(res.best_sequence, noise, cfg, d).infidelity == pytest.approx(
        res.best_train_infidelity, rel=1e-12)
    bsf = [h["best_so_far"] for h in res.history]
    assert all(x >= y for x, y in zip(bsf, bsf[1:]))
    assert res.n_evaluations <= 60
    assert res.history[-1]["n_evals"] == res.n_evaluations
    assert res.train_seeds == [cfg.seed]
    assert res.mode == mode
    res.to_json()


def test_optimizer_robust_objective_runs():
    det = DetuningProfile("smooth_rect", 2 * math.pi * 0.2e6, 0.3e-6, 0.8e-6, 2e-8)
    noise = _toy_noise(det)
    robust = [noise, NoiseModel(noise.components, DetuningProfile("smooth_rect", 2 * math.pi * 0.24e6, 0.3e-6,
                                                                  0.8e-6, 2e-8), noise.T1)]
    res, *_ = _run(seed=1, max_evals=20, robust=robust, noise=noise)
    assert res.provenance["robust_n_models"] == 2
    assert res.best_train_infidelity <= res.provenance["start_train_infidelity"]


def test_optimizer_rejects_bad_seed_and_draws():
    noise = _toy_noise()
    cfg = _toy_config()
    d = frozen_draws(noise, 1e-6, cfg)
    with pytest.raises(ValueError):
        opt.optimize(4, 1e-6, 2e-8, noise, cfg, mode="timing", train_draws=d, max_evals=10, seed=0, guard=G)
    with pytest.raises(ValueError):
        opt.optimize(4, 1e-6, 2e-8, noise, _toy_config(n_traj=16), mode="timing", train_draws=d,
                     max_evals=10, seed=1, guard=G)
