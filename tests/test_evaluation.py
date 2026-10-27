"""Tests for ddopt.evaluation (Agent D). Tiny budgets; development seeds only (7000+)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

import ddopt.evaluation as ev
import ddopt.simulator as simmod
from ddopt import optimizer as opt
from ddopt import sequences as seqmod
from ddopt.contracts import ControlErrors, DetuningProfile, NoiseModel, SimulationConfig
from ddopt.noise import make_lorentzian, make_one_over_f
from ddopt.scenarios import load_scenario, scenario_noise, sim_config
from ddopt.simulator import frozen_draws, simulate

T, W, G, DT = 2e-6, 3.2e-8, 4e-9, 4e-9


def _noise(det=None):
    comps = (make_lorentzian(2 * math.pi * 0.15e6, 1e-3),
             make_one_over_f(4e9, 1.0, 2 * math.pi * 1e2, 2 * math.pi * 20e6))
    return NoiseModel(comps, det or DetuningProfile(), 50e-6)


def _cfg(seed=7001, n_traj=32, **kw):
    return SimulationConfig(n_traj=n_traj, seed=seed, noise_dt=2e-9, pulse_steps=4, include_T1=True,
                            control_errors=ControlErrors(amp_rel_std=0.02), **kw)


def test_canonical_baselines_feasibility_and_reasons():
    om = {}
    b4 = ev.canonical_baselines(4, T, W, guard=G, dt_grid=DT, omitted=om)
    assert set(b4) == {"free", "hahn", "cpmg", "xy4", "udd"}
    assert "xy8" in om and "multiple of 8" in om["xy8"]
    b8 = ev.canonical_baselines(8, T, W, guard=G, dt_grid=DT)
    assert {"cpmg", "xy4", "xy8", "udd"} <= set(b8)
    for s in b8.values():
        s.validate()
        assert s.dt_grid == DT
        assert all(x.n == 8 for k, x in b8.items() if k not in ("free", "hahn"))
    om2 = {}
    b_bad = ev.canonical_baselines(16, 5e-7, 4e-8, guard=G, dt_grid=DT, omitted=om2)
    assert set(b_bad) == {"free", "hahn"}
    assert all(om2[k].startswith("infeasible") for k in ("cpmg", "xy4", "xy8", "udd"))


def test_select_baseline_uses_training_draws_only(monkeypatch):
    noise = _noise()
    cfg = _cfg()
    d = frozen_draws(noise, T, cfg)
    base = ev.canonical_baselines(8, T, W, guard=G, dt_grid=DT)

    def boom(*a, **k):
        raise AssertionError("selection must not draw new noise")

    monkeypatch.setattr(ev, "frozen_draws", boom)
    monkeypatch.setattr(simmod, "frozen_draws", boom)
    name, scores = ev.select_baseline(base, noise, cfg, d, return_scores=True)
    assert name in ev.DD_FAMILIES and "free" not in scores and "hahn" not in scores
    manual = {k: opt.simulate_on_draws(base[k], noise, cfg, d).infidelity for k in scores}
    assert name == min(manual, key=manual.get)
    # different training draws may change the scores, never touch test seeds
    assert scores[name]["infidelity"] == pytest.approx(manual[name])


def test_evaluate_disjointness_enforced():
    noise = _noise()
    seqs = {"cpmg": seqmod.cpmg(4, T, W, guard=G, dt_grid=DT)}
    with pytest.raises(ValueError):
        ev.evaluate(seqs, noise, _cfg(), [7001, 7002], 16, train_seeds=[7002])
    with pytest.raises(ValueError):
        ev.evaluate(seqs, noise, _cfg(), [7001], 16)  # train_seeds missing
    with pytest.raises(ValueError):
        ev.check_disjoint([7001, 7001], [1])


def test_evaluate_paired_same_draws_and_matches_simulate():
    noise = _noise()
    cp = seqmod.cpmg(4, T, W, guard=G, dt_grid=DT)
    seqs = {"a": cp, "b": cp, "xy4": seqmod.xy4(4, T, W, guard=G, dt_grid=DT)}
    out = ev.evaluate(seqs, noise, _cfg(), [7011, 7012], 24, train_seeds=[7001])
    for s in (7011, 7012):
        pa = out["per_seed"]["a"][s]["per_traj"]
        pb = out["per_seed"]["b"][s]["per_traj"]
        assert np.array_equal(pa, pb) and pa.shape == (24,)
        ref = simulate(seqs["xy4"], noise, _cfg(seed=s, n_traj=24))
        assert out["per_seed"]["xy4"][s]["infidelity"] == pytest.approx(ref.infidelity, rel=1e-12)
        assert np.mean(out["per_seed"]["xy4"][s]["per_traj"]) == pytest.approx(ref.infidelity, rel=1e-9)
    assert out["per_seed"]["a"][7011]["infidelity"] != out["per_seed"]["a"][7012]["infidelity"]


def test_paired_bootstrap_coverage_synthetic():
    """95 % percentile CI for the ratio of means covers the truth at roughly the nominal rate."""
    rng = np.random.default_rng(7600)
    mu_a, mu_b = 0.02, 0.012
    true_ratio = mu_a / mu_b
    covered = 0
    reps = 200
    for _ in range(reps):
        common = rng.gamma(2.0, 1.0, size=200)  # correlated (paired) heavy-ish tails
        a = mu_a * (0.5 * common + 0.5 * rng.gamma(2.0, 1.0, size=200)) / 2.0
        b = mu_b * (0.5 * common + 0.5 * rng.gamma(2.0, 1.0, size=200)) / 2.0
        r = ev.paired_bootstrap(a, b, 400, rng)
        lo, hi = r["ratio_ci"]
        covered += lo <= true_ratio <= hi
        assert r["reduction"] == pytest.approx(1 - r["eps_b"] / r["eps_a"])
        assert r["difference"] == pytest.approx(r["eps_a"] - r["eps_b"])
    cov = covered / reps
    assert 0.88 <= cov <= 0.99, cov


def test_paired_bootstrap_pairing_tightens_ci():
    rng = np.random.default_rng(7601)
    common = rng.exponential(size=500)
    a = common + 0.01 * rng.standard_normal(500)
    b = common * 0.9 + 0.01 * rng.standard_normal(500)
    paired = ev.paired_bootstrap(a, b, 500, np.random.default_rng(1))
    unpaired = ev.paired_bootstrap(a, rng.permutation(b), 500, np.random.default_rng(1))
    w = lambda r: r["difference_ci"][1] - r["difference_ci"][0]  # noqa: E731
    assert w(paired) < 0.3 * w(unpaired)


def test_pooled_comparison():
    rng = np.random.default_rng(7602)
    A = [rng.exponential(0.02, size=100) for _ in range(4)]
    r_same = ev.pooled_comparison(A, A, 200, rng)
    assert r_same["ratio"] == 1.0 and r_same["ratio_ci"] == [1.0, 1.0]
    B = [a * 0.5 for a in A]
    r = ev.pooled_comparison(A, B, 200, rng)
    assert r["ratio"] == pytest.approx(2.0) and r["ratio_ci"][0] == pytest.approx(2.0)
    assert len(r["eps_a_per_seed"]) == 4


def test_scenario_b_arms_and_robustness_nominal_consistency():
    det = DetuningProfile("smooth_rect", 2 * math.pi * 0.2e6, 0.6e-6, 1.6e-6, 2e-8)
    noise = _noise(det)
    cfg = _cfg(n_traj=16, frame_correction="ideal_control_plus_virtual_z")
    best = seqmod.xy4(4, T, W, guard=G, dt_grid=DT)
    arms = ev.scenario_b_arms(T, best_dd=best, optimized=seqmod.cpmg(4, T, W, guard=G, dt_grid=DT),
                              guard=G, dt_grid=DT)
    assert list(arms) == ["1_no_dd", "2_virtual_z_only", "3_xy4_plus_vz", "4_optimized_plus_vz"]
    base = ev.evaluate_arms(arms, noise, cfg, [7021], train_seeds=[7001])
    perts = ev.perturbed_detuning_models(noise, (1.0, 1.2), (0.0,))
    rob = ev.robustness_sweep(arms, noise, cfg, [7021], train_seeds=[7001], perturbations=perts)
    for arm in arms:
        assert rob["amp_x1"]["summary"][arm]["per_seed"][0] == pytest.approx(
            base["summary"][arm]["per_seed"][0], rel=1e-12)
        assert rob["shift_+0ns"]["summary"][arm]["per_seed"][0] == pytest.approx(
            base["summary"][arm]["per_seed"][0], rel=1e-12)
    # virtual-Z angle uses the nominal profile even under perturbation
    vz_nom = base["per_seed"]["2_virtual_z_only"][7021]["virtual_z_angle"]
    res_p = ev.evaluate_arms(arms, noise, cfg, [7021], train_seeds=[7001], noise_true=perts["amp_x1.2"])
    assert res_p["per_seed"]["2_virtual_z_only"][7021]["virtual_z_angle"] == pytest.approx(vz_nom)
    # frame correction privileges: arm 1 has none, arms 2-4 the same virtual-Z privilege
    fr = {a: base["per_seed"][a][7021]["frame_correction"] for a in arms}
    assert fr["1_no_dd"] == "ideal_control"
    assert {fr[a] for a in list(arms)[1:]} == {"ideal_control_plus_virtual_z"}


@pytest.mark.parametrize("scenario", ["scenario_a", "scenario_b"])
def test_run_benchmark_tiny(scenario):
    cfg = load_scenario(scenario)
    out = ev.run_benchmark(cfg, 4, "timing", 7001, 7, [7101, 7102], max_evals=12, n_traj_train=8,
                           n_traj_test=8, n_boot=50, robustness=(scenario == "scenario_b"))
    json.dumps(out)
    assert out["selected_baseline"] in ev.DD_FAMILIES
    assert out["optimization"]["start_matches_cpmg_baseline"]
    assert out["optimization"]["best_train_infidelity"] <= out["optimization"]["start_train_infidelity"]
    assert set(out["comparisons"]) >= {"free", "cpmg", "xy4", "udd"}
    assert out["comparison_vs_selected"] is out["comparisons"][out["selected_baseline"]]
    if scenario == "scenario_b":
        assert "scenario_b_arms" in out and "scenario_b_robustness" in out
        assert out["frame_correction"] == "ideal_control_plus_virtual_z"
    with pytest.raises(ValueError):
        ev.run_benchmark(cfg, 4, "timing", 7001, 7, [7001], max_evals=12, n_traj_train=8, n_traj_test=8)
