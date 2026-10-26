"""Tests for ddopt.spectroscopy (Agent C). All data synthetic; fixed seeds; small n_boot for speed."""

from __future__ import annotations

import copy
import json
import math

import numpy as np
import pytest
from scipy import optimize

from ddopt import filters, noise as N
from ddopt import spectroscopy as S
from ddopt.contracts import NoiseModel

W2 = 2 * math.pi
ONEF = N.make_one_over_f(5.93e9, 1.0, W2, W2 * 1e7)
WHITE = N.make_white(1e4, W2 * 1e8)
T1 = 1e-4
REDUCED_TRUTH = NoiseModel(components=(ONEF, WHITE), T1=T1)
# strongly misspecified for the reduced fit: extra Lorentzian with tau_c inside the CPMG spacing range
MISSPEC_TRUTH = NoiseModel(components=(ONEF, WHITE, N.make_lorentzian(3e5, 2e-6)), T1=T1)
TRUTH_SPAM = S.DEFAULT_SPAM
TRUE_PARAMS = {"A_ref": 5.93e9 / S.DEFAULT_OMEGA_REF, "S0": 1e4,
               "spam_hi": TRUTH_SPAM[0] + TRUTH_SPAM[1], "spam_mid": TRUTH_SPAM[0] + TRUTH_SPAM[1] / 2}


@pytest.fixture(scope="module")
def design():
    return S.default_design(n_times=10)


def _data(noise, design, seed_train, seed_test, method="analytic"):
    tr = S.simulate_dataset(noise, design["train"], rng=seed_train, method=method, label="train")
    te = S.simulate_dataset(noise, design["heldout_new_n"] + design["heldout_new_T"], rng=seed_test,
                            method=method, label="test")
    return tr, te


@pytest.fixture(scope="module")
def correct_fit(design):
    tr, te = _data(REDUCED_TRUTH, design, 12, 112)
    return tr, te, S.fit(tr, "reduced", n_boot=30, rng=212, dataset_test=te)


# --------------------------------------------------------------------------- forward model


@pytest.mark.parametrize("comp", [WHITE, N.make_lorentzian(1.2e5, 5e-7), N.make_lorentzian(1e5, 1e-4),
                                  N.make_telegraph(1e5, 1e6)])
@pytest.mark.parametrize("exp", [S.Experiment("ramsey", 0, 1e-7, 1), S.Experiment("hahn", 1, 3e-6, 1),
                                 S.Experiment("cpmg", 16, 1e-7, 1), S.Experiment("cpmg", 7, 2e-5, 1)])
def test_closed_form_chi_matches_filter_function(comp, exp):
    ref, err = filters.dephasing_variance(comp, exp.sequence())
    assert S.chi_closed_form(comp, exp) == pytest.approx(ref, rel=1e-7, abs=10 * err)


@pytest.mark.parametrize("exp", [S.Experiment("ramsey", 0, 2e-6, 1), S.Experiment("hahn", 1, 2e-6, 1),
                                 S.Experiment("cpmg", 5, 2e-6, 1), S.Experiment("cpmg", 8, 2e-6, 1)])
def test_jumps_reproduce_switching_function(exp):
    tau, J = exp.jumps()
    t = np.linspace(0, exp.T, 1001)[1:-1] + 1e-12
    y_j = np.array([J[tau <= x].sum() for x in t])
    assert np.allclose(y_j, filters.switching_function(exp.sequence(), t))
    assert abs(J.sum()) < 1e-15


def test_alpha_spline_accuracy():
    spec = S._make_spec("reduced", bounds=None, fit_alpha=True, alpha=1.0, spam="fit", T1=T1,
                        omega_low=W2, omega_high=W2 * 1e7, omega_high_white=W2 * 1e8, omega_ref=S.DEFAULT_OMEGA_REF)
    exps = [S.Experiment("ramsey", 0, 1e-5, 1), S.Experiment("cpmg", 16, 4e-5, 1), S.Experiment("hahn", 1, 1e-7, 1)]
    b = S._Basis(spec, exps)
    for al in (0.47, 0.83, 1.234, 1.55):
        ref = [filters.dephasing_variance(N.make_one_over_f(1.0, al, W2, W2 * 1e7), e.sequence())[0] for e in exps]
        assert np.allclose(np.exp(b.f_spline(al)), ref, rtol=2e-4)


def test_survival_probability_formula():
    e = S.Experiment("hahn", 1, 5e-6, 100)
    chi = filters.dephasing_variance(REDUCED_TRUTH, e.sequence())[0]
    p = 0.5 * (1 + math.exp(-e.T / (2 * T1)) * math.exp(-chi / 2))
    a, b = 0.04, 0.9
    assert S.survival_probability(REDUCED_TRUTH, e, spam=(a, b)) == pytest.approx(a + b * p, rel=1e-6)
    # no noise, no T1, no SPAM -> perfect return
    assert S.survival_probability(NoiseModel(), e) == pytest.approx(1.0)


def test_telegraph_mc_matches_exact_and_gaussian_fails():
    tel = NoiseModel(components=(N.make_telegraph(3e6, 1e5),))
    for e in (S.Experiment("ramsey", 0, 1e-6, 1), S.Experiment("cpmg", 4, 4e-6, 1), S.Experiment("hahn", 1, 2e-6, 1)):
        m, se = S._coherence(tel, e, "mc", np.random.default_rng(1), 4000)
        ex = S._coherence(tel, e, "exact")[0]
        g = S._coherence(tel, e, "analytic")[0]
        assert abs(m - ex) < 4 * se + 2e-3
        # slow strong RTN: the Gaussian (Lorentzian-equivalent) approximation is far off for these
        assert abs(g - ex) > 0.1


def test_simulate_dataset_manifest_and_reproducibility(design):
    a = S.simulate_dataset(REDUCED_TRUTH, design["train"], rng=7)
    b = S.simulate_dataset(REDUCED_TRUTH, design["train"], rng=7)
    c = S.simulate_dataset(REDUCED_TRUTH, design["train"], rng=8)
    assert a["counts"] == b["counts"] and a["counts"] != c["counts"]
    tr = a["truth"]
    assert tr["seed"] == 7 and tr["spam"]["a"] == TRUTH_SPAM[0] and tr["method"] == "analytic"
    assert len(a["experiments"]) == len(a["counts"]) == len(tr["p_meas"])
    assert all(0 <= k <= n for k, n in zip(a["counts"], a["shots"]))
    json.dumps(a)  # JSON-friendly
    assert a["calibration"]["T1"] == T1


# --------------------------------------------------------------------------- fitting


def test_recovery_within_ci_well_conditioned(correct_fit):
    """Reduced truth, reduced fit (fixed seed 12/212). Calibration of these CIs over 40 seeds is
    reported separately (not asserted here)."""
    _, _, fr = correct_fit
    assert fr.success, fr.failure_reason
    for n, v, lo, hi in zip(fr.param_names, fr.params, fr.param_ci_low, fr.param_ci_high):
        assert lo <= TRUE_PARAMS[n] <= hi, (n, lo, TRUE_PARAMS[n], hi)
        assert lo <= v <= hi
    t2 = S.truth_t2(REDUCED_TRUTH)
    for key in ("T2star", "T2_hahn"):
        lo, hi = fr.derived[key]["ci95_s"]
        assert lo <= t2[key] <= hi
    assert any("T1 treated as known" in w for w in fr.identifiability_warnings)
    corr = np.array(fr.param_corr, dtype=float)
    assert np.allclose(np.diag(corr), 1.0)


def test_heldout_near_shot_noise_floor_for_correct_model(correct_fit):
    _, _, fr = correct_fit
    h = fr.derived["heldout"]
    assert h["rmse_ratio"] < 1.25
    assert fr.heldout_rmse == pytest.approx(h["rmse"])
    assert fr.heldout_coverage >= 0.85
    assert h["misspecification_flags"] == []
    assert fr.derived["train_chi2"] / fr.derived["train_dof"] < 1.5


def test_misspecified_truth_is_diagnosed(design, correct_fit):
    """Extra Lorentzian in the truth, reduced Gaussian fit: the diagnostics must report it."""
    tr, te = _data(MISSPEC_TRUTH, design, 31, 131)
    fr = S.fit(tr, "reduced", n_boot=20, rng=231, dataset_test=te)
    h = fr.derived["heldout"]
    detected = (not fr.success) or bool(h["misspecification_flags"])
    assert detected
    assert h["rmse_ratio"] > correct_fit[2].derived["heldout"]["rmse_ratio"]
    # the full model (contains the true family) should predict the held-out data far better
    ff = S.fit(tr, "full", n_boot=10, rng=232, dataset_test=te)
    assert ff.derived["heldout"]["rmse_ratio"] < h["rmse_ratio"]


def test_no_leakage_of_test_data(design):
    tr, te = _data(REDUCED_TRUTH, design, 41, 141)
    f_without = S.fit(tr, "reduced", n_boot=8, rng=5)
    f_with = S.fit(tr, "reduced", n_boot=8, rng=5, dataset_test=te)
    # perturbed test counts and a stripped truth manifest must not change anything either
    te_bad = copy.deepcopy(te)
    te_bad["counts"] = [n - k for k, n in zip(te_bad["counts"], te_bad["shots"])]
    tr_blind = {k: v for k, v in tr.items() if k != "truth"}
    f_bad = S.fit(tr_blind, "reduced", n_boot=8, rng=5, dataset_test=te_bad)
    for f in (f_with, f_bad):
        assert f.params == f_without.params
        assert f.param_ci_low == f_without.param_ci_low
        assert f.provenance["bootstrap_x"] == f_without.provenance["bootstrap_x"]
    assert math.isnan(f_without.heldout_rmse) and f_without.heldout_coverage is None
    assert f_with.derived["heldout"]["test_data_hash"] != f_bad.derived["heldout"]["test_data_hash"]


def test_failed_fit_on_pathological_data(design):
    exps = design["train"]
    ds = {"experiments": [e.to_dict() for e in exps], "shots": [e.shots for e in exps],
          "counts": [e.shots // 2 for e in exps], "calibration": {"T1": T1}}
    for model in ("reduced", "full"):
        fr = S.fit(ds, model, n_boot=4, rng=0)
        assert not fr.success
        assert fr.failure_reason


def test_failed_fit_on_wrong_shape_data(design):
    """Data that decay and then *revive* cannot be fitted by monotone-decay models: GOF must fail."""
    exps = design["train"]
    T = np.array([e.T for e in exps])
    p = 0.5 + 0.45 * np.cos(2 * np.pi * T / 5e-6) ** 2
    ds = {"experiments": [e.to_dict() for e in exps], "shots": [e.shots for e in exps],
          "counts": [int(round(e.shots * q)) for e, q in zip(exps, p)], "calibration": {"T1": T1}}
    fr = S.fit(ds, "reduced", n_boot=4, rng=0)
    assert not fr.success and "goodness of fit" in fr.failure_reason


def test_predict_and_fitted_noise_model_consistent(correct_fit, design):
    _, _, fr = correct_fit
    exps = design["heldout_new_n"][:5]
    nm = S.fitted_noise_model(fr)
    assert nm.T1 == T1 and len(nm.components) == 2
    a, b = fr.derived["spam_a"]["value"], fr.derived["spam_b"]["value"]
    p1 = S.predict(fr, exps)
    p2 = [S.survival_probability(nm, e, spam=(a, b)) for e in exps]
    assert np.allclose(p1, p2, rtol=1e-6)
    assert np.allclose(S.predict(fr, exps, include_spam=False), (p1 - a) / b)


def test_t2_grid_interpolation_vs_root_finding():
    t2 = S.truth_t2(REDUCED_TRUTH)

    def w(T, fam, n):
        e = S.Experiment(fam, n, T, 1)
        return math.exp(-T / (2 * T1)) * math.exp(-0.5 * filters.dephasing_variance(REDUCED_TRUTH, e.sequence())[0]) - math.exp(-1)

    r = optimize.brentq(w, 1e-6, 1e-4, args=("ramsey", 0), xtol=1e-12)
    h = optimize.brentq(w, 1e-6, 2e-4, args=("hahn", 1), xtol=1e-12)
    assert t2["T2star"] == pytest.approx(r, rel=2e-3)
    assert t2["T2_hahn"] == pytest.approx(h, rel=2e-3)


def test_white_t1_near_degeneracy():
    """S0 and 1/T1 are (nearly) degenerate: shifting S0 by +D and 1/T1 by -D leaves p unchanged."""
    D = 5e3
    m1 = NoiseModel(components=(ONEF, WHITE), T1=T1)
    m2 = NoiseModel(components=(ONEF, N.make_white(1e4 + D, W2 * 1e8)), T1=1.0 / (1.0 / T1 - D))
    for e in (S.Experiment("ramsey", 0, 5e-6, 1), S.Experiment("cpmg", 4, 3e-5, 1)):
        assert S.survival_probability(m1, e) == pytest.approx(S.survival_probability(m2, e), abs=1e-5)


def test_experiment_validation():
    with pytest.raises(ValueError):
        S.Experiment("hahn", 2, 1e-6, 10)
    with pytest.raises(ValueError):
        S.Experiment("cpmg", 0, 1e-6, 10)
    with pytest.raises(ValueError):
        S.Experiment("ramsey", 0, -1.0, 10)
    with pytest.raises(ValueError):
        S._Basis(S._make_spec("reduced", bounds=None, fit_alpha=False, alpha=1.0, spam="fit", T1=T1,
                              omega_low=W2, omega_high=W2 * 1e7, omega_high_white=W2 * 1e8,
                              omega_ref=S.DEFAULT_OMEGA_REF), [S.Experiment("cpmg", 2, 1e-6, 10, width=3e-8)])


def test_run_pipeline_smoke():
    from ddopt.scenarios import load_scenario

    cfg = load_scenario("scenario_a")
    out = S.run_pipeline(cfg, seeds=[1], n_boot=3, n_starts=2, fits=(("reduced", False),),
                         misspec_fits=(("reduced", False),), design_kw={"n_times": 5})
    json.dumps(out, allow_nan=False)  # strict JSON (non-finite floats stringified)
    rep = out["repeats"][0]["truths"]
    assert set(rep) == {"gaussian", "telegraph"}
    for t in rep.values():
        f = t["fits"]["reduced_alpha1"]
        assert "heldout" in f["derived"] and "param_vs_truth" in f and "t2_vs_truth" in f
        assert "bootstrap_x" not in f["provenance"]
