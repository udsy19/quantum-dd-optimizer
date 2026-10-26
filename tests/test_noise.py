"""Tests for ddopt.noise: PSDs, variances, autocovariances and trajectory sampling.

Statistical tests use fixed seeds and 4-sigma acceptance (two-sided p ~ 6e-5 per check under
the null); deterministic bias checks use the exact covariance of the generator
(``synthesized_autocovariance``). Lines prefixed ``TOL`` are recorded in docs/PHYSICS.md.
"""

import math
import time
import warnings

import numpy as np
import pytest
from scipy import integrate, linalg

from ddopt import filters as ff
from ddopt import noise as nz
from ddopt.contracts import NoiseModel, PSDComponent, PulseSequence

PI = math.pi
DT = 1e-9
T = 2e-6
TGRID = np.linspace(0.0, T, int(round(T / DT)) + 1)  # 2001 points, last point exactly T

ONEF = nz.make_one_over_f(1e9, 1.0, 2 * PI * 1.0, 2 * PI * 10e6)  # omega_low << 2pi/T
LOR = nz.make_lorentzian(1e5, 0.5e-6)  # OU path
LOR_CUT = nz.make_lorentzian(1e5, 0.5e-6, 2 * PI * 50e6, omega_low=2 * PI * 1e3)  # spectral path
WHITE = nz.make_white(2e3, 2 * PI * 100e6)
CASES = {"one_over_f": ONEF, "lorentzian_ou": LOR, "lorentzian_cut": LOR_CUT, "white": WHITE}


def model(*cs):
    return NoiseModel(components=tuple(cs))


def hahn():
    return PulseSequence(T=T, centers=(T / 2,), widths=(0.0,), phases=(PI / 2,), angles=(PI,))


def trapz_weights(n, dt):
    w = np.full(n, dt)
    w[[0, -1]] *= 0.5
    return w


def y_on_grid(seq):
    y = ff.switching_function(seq, TGRID)
    for c in seq.centers:  # value at a jump point: midpoint convention (trapezoid-exact)
        k = int(round(c / DT))
        y[k] = 0.0
    return y


# ---------------------------------------------------------------------------
# PSD and variance
# ---------------------------------------------------------------------------


def test_psd_nonnegative_even_and_cutoffs():
    w = np.concatenate([-np.geomspace(1e-2, 1e12, 300), [0.0], np.geomspace(1e-2, 1e12, 300)])
    for c in list(CASES.values()) + [nz.make_telegraph(1e5, 1e6)]:
        s = nz.psd(c, w)
        assert np.all(s >= 0) and np.all(np.isfinite(s))
        assert np.array_equal(s, nz.psd(c, -w))
        outside = (np.abs(w) < c.omega_low) | (np.abs(w) > c.omega_high)
        assert np.all(s[outside] == 0)
    assert nz.psd(ONEF, np.array([2 * PI * 1e3]))[0] == pytest.approx(1e9 / (2 * PI * 1e3))
    assert nz.psd(LOR, np.array([0.0]))[0] == pytest.approx(2 * 1e10 * 0.5e-6)
    tel = nz.make_telegraph(1e5, 1e6)
    assert np.allclose(nz.psd(tel, w), nz.psd(nz.make_lorentzian(1e5, 0.5e-6), w), rtol=1e-14)
    assert np.allclose(nz.psd(model(ONEF, LOR), w), nz.psd(ONEF, w) + nz.psd(LOR, w))


@pytest.mark.parametrize("c", [
    ONEF, nz.make_one_over_f(3e7, 0.6, 1e2, 1e9), nz.make_one_over_f(1e15, 1.8, 1e3, 1e8),
    nz.make_one_over_f(1e9, 1.0 + 1e-14, 1.0, 1e8), LOR, LOR_CUT, WHITE, nz.make_telegraph(2e5, 3e6),
])
def test_noise_variance_analytic_vs_quadrature(c):
    a, b = c.omega_low, c.omega_high
    f = lambda w: float(nz.psd(c, np.array([w]))[0])  # noqa: E731
    if math.isinf(b):
        sigma, tc = nz.lorentzian_equivalent(c)
        ed = [a, 1 / tc, 100 / tc]
        ref = (sum(integrate.quad(f, x, y, epsrel=1e-13, epsabs=0)[0] for x, y in zip(ed[:-1], ed[1:]))
               + integrate.quad(lambda v: f(1 / v) / v**2 if v > 0 else 2 * sigma**2 / tc,
                                0.0, 1 / ed[-1], epsrel=1e-13, epsabs=0)[0]) / PI  # v = 1/w
    else:
        ed = np.geomspace(max(a, 1e-3), b, 60)
        ref = (integrate.quad(f, a, ed[0])[0] if a < ed[0] else 0.0)
        ref = (ref + sum(integrate.quad(f, x, y, epsrel=1e-13, epsabs=0)[0] for x, y in zip(ed[:-1], ed[1:]))) / PI
    assert nz.noise_variance(c) == pytest.approx(ref, rel=1e-9)
    assert nz.autocovariance(c, 0.0) == pytest.approx(nz.noise_variance(c), rel=1e-14)


def test_noise_variance_closed_forms_and_model_sum():
    assert nz.noise_variance(LOR) == pytest.approx(1e10)
    assert nz.noise_variance(WHITE) == pytest.approx(2e3 * 2 * PI * 100e6 / PI)
    assert nz.noise_variance(ONEF) == pytest.approx(1e9 / PI * math.log(10e6))
    assert nz.noise_variance(model(ONEF, LOR, WHITE)) == pytest.approx(
        sum(nz.noise_variance(c) for c in (ONEF, LOR, WHITE)))
    assert nz.noise_variance(model()) == 0.0


def test_autocovariance_closed_forms():
    tau = np.array([1e-9, 1e-7, 1e-6])
    assert np.allclose(nz.autocovariance(LOR, tau), 1e10 * np.exp(-tau / 0.5e-6), rtol=1e-14)
    tel = nz.make_telegraph(1e5, 2e6)
    assert np.allclose(nz.autocovariance(tel, tau), 1e10 * np.exp(-2 * 2e6 * tau), rtol=1e-14)
    # white closed form vs direct cosine quadrature
    ref = [integrate.quad(lambda w: 2e3, 0, WHITE.omega_high, weight="cos", wvar=x)[0] / PI for x in tau]
    assert np.allclose(nz.autocovariance(WHITE, tau), ref, rtol=1e-9)


def test_constructors_and_validation():
    with pytest.raises(ValueError):
        nz.make_one_over_f(1.0, 1.0, 0.0, 1e6)
    with pytest.raises(ValueError):
        nz.make_white(1.0, math.inf)
    with pytest.raises(ValueError):
        nz.make_lorentzian(-1.0, 1e-6)
    with pytest.raises(TypeError):
        nz.psd("white", np.ones(2))


# ---------------------------------------------------------------------------
# Sampler: deterministic bias of the generator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(CASES))
def test_synthesized_covariance_bias(name):
    c = CASES[name]
    cov, info = nz.synthesized_autocovariance(model(c), TGRID)
    lags = np.array([0, 1, 2, 5, 10, 30, 100, 300, 1000, 2000])
    ref = nz.autocovariance(c, lags * DT)
    rel = np.max(np.abs(cov[lags] - ref)) / ref[0]
    print(f"TOL sampler covariance bias {name} ({info['methods'][0]}): max|C_syn-C|/C(0) = {rel:.1e}, "
          f"dropped>Nyquist frac = {info['var_above_nyquist'] / info['var_target']:.1e}")
    assert rel < 3e-4


@pytest.mark.parametrize("name", list(CASES))
def test_discrete_phase_variance_bias_vs_filter_function(name):
    """Exact (no MC) variance of the trapezoid phase sum_k w_k y_k delta_k under the generator's
    covariance vs chi from the filter-function quadrature: the sampler+trapezoid bias budget."""
    c = CASES[name]
    cov, _ = nz.synthesized_autocovariance(model(c), TGRID)
    wq = trapz_weights(TGRID.size, DT)
    for seq in (PulseSequence(T=T), hahn()):
        v = wq * y_on_grid(seq)
        chi_disc = float(v @ linalg.matmul_toeplitz(cov, v))
        chi_ff, err = ff.dephasing_variance(c, seq)
        rel = abs(chi_disc - chi_ff) / chi_ff
        print(f"TOL discrete-phase bias {name} n={seq.n}: |chi_disc - chi_FF|/chi_FF = {rel:.1e}")
        assert rel < 3e-4


def test_ou_generator_is_exact():
    cov, info = nz.synthesized_autocovariance(model(LOR), TGRID)
    assert info["methods"] == ["ou"]
    assert np.allclose(cov, 1e10 * np.exp(-TGRID / 0.5e-6), rtol=1e-14)


def test_low_frequency_content_below_window_is_present():
    """1/f with omega_low = 2pi*1 Hz << 2pi/T: about 37 % of the variance lies below 2pi/T."""
    cov, info = nz.synthesized_autocovariance(model(ONEF), TGRID)
    below = nz.band_variance(ONEF, 0, 2 * PI / T)
    assert below / nz.noise_variance(ONEF) > 0.3
    assert info["var_synth"] == pytest.approx(nz.noise_variance(ONEF), rel=3e-4)
    x = nz.sample_detuning(model(ONEF), TGRID, 4000, np.random.default_rng(3))
    v = x[:, 0].var()
    se = nz.noise_variance(ONEF) * math.sqrt(2 / 3999)
    assert abs(v - nz.noise_variance(ONEF)) < 4 * se
    assert v > nz.band_variance(ONEF, 2 * PI / T, math.inf) + 4 * se  # missing-low-f sampler would fail


# ---------------------------------------------------------------------------
# Sampler: Monte-Carlo statistics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(CASES))
def test_sample_mean_variance_autocovariance(name):
    c = CASES[name]
    n = 4000
    x = nz.sample_detuning(model(c), TGRID, n, np.random.default_rng(11))
    assert x.shape == (n, TGRID.size)
    var0 = nz.noise_variance(c)
    for k in (0, 1000, 2000):  # stationarity: same statistics at different times
        assert abs(x[:, k].mean()) < 4 * math.sqrt(var0 / n)
        assert abs(x[:, k].var() - var0) < 4 * var0 * math.sqrt(2 / (n - 1)) + 3e-4 * var0
    for lag in (1, 10, 100, 500, 2000):
        Ck = float(nz.autocovariance(c, lag * DT))
        est = np.mean(x[:, 0] * x[:, lag])
        se = math.sqrt((var0**2 + Ck**2) / n)
        assert abs(est - Ck) < 4 * se + 3e-4 * var0, (lag, est, Ck, se)


@pytest.mark.parametrize("name", list(CASES))
def test_mc_phase_variance_matches_chi(name):
    """Key G3 precursor: Var of trapezoid-integrated delta over the window vs analytic chi."""
    c = CASES[name]
    n = 4000
    x = nz.sample_detuning(model(c), TGRID, n, np.random.default_rng(21))
    wq = trapz_weights(TGRID.size, DT)
    for seq in (PulseSequence(T=T), hahn()):
        phi = x @ (wq * y_on_grid(seq))
        chi_mc = phi.var(ddof=1)
        se = chi_mc * math.sqrt(2 / (n - 1))
        chi_ff, _ = ff.dephasing_variance(c, seq)
        z = (chi_mc - chi_ff) / se
        print(f"TOL MC phase variance {name} n={seq.n}: chi_MC/chi_FF - 1 = {chi_mc / chi_ff - 1:+.3e}, "
              f"z = {z:+.2f}, rel SE = {se / chi_mc:.1e}")
        assert abs(chi_mc - chi_ff) < 4 * se + 1e-4 * chi_ff
        assert abs(phi.mean()) < 4 * math.sqrt(chi_ff / n)


def test_spectral_method_reproduces_ou_statistics():
    cov_s, info = nz.synthesized_autocovariance(model(LOR), TGRID, method="spectral")
    cov_o, _ = nz.synthesized_autocovariance(model(LOR), TGRID)
    rel = np.max(np.abs(cov_s - cov_o)) / cov_o[0]
    frac = info["var_above_nyquist"] / info["var_target"]
    print(f"TOL spectral vs exact OU covariance: {rel:.1e} (above-Nyquist fraction {frac:.1e})")
    assert rel < 2 * frac + 1e-5


def test_telegraph_exact_markov_sampling():
    b, g = 2e6, 0.5e6  # b tau_c = 2: strongly non-Gaussian
    tel = nz.make_telegraph(b, g)
    n = 4000
    x = nz.sample_detuning(model(tel), TGRID, n, np.random.default_rng(5))
    assert set(np.unique(x)) <= {-b, b}
    for k in (0, 1000, 2000):
        assert abs(np.mean(x[:, k] > 0) - 0.5) < 4 * math.sqrt(0.25 / n)
    for lag in (1, 100, 500):
        Ck = b**2 * math.exp(-2 * g * lag * DT)
        est = np.mean(x[:, 0] * x[:, lag])
        se = math.sqrt((b**4 - Ck**2) / n)  # x0 xk = +-b^2
        assert abs(est - Ck) < 4 * se + 1e-12
    # non-Gaussian coherence: MC <cos phi> vs exact transfer-matrix result (Gaussian formula differs)
    wq = trapz_weights(TGRID.size, DT)
    for seq in (PulseSequence(T=T), hahn()):
        phi = x @ (wq * y_on_grid(seq))
        c = np.cos(phi)
        W_mc, se = c.mean(), c.std(ddof=1) / math.sqrt(n)
        W_ex = ff.telegraph_coherence_exact(tel, seq)
        W_g = ff.coherence(tel, seq)
        print(f"TOL telegraph n={seq.n}: W_MC={W_mc:.4f}+-{se:.4f}, W_exact={W_ex:.4f}, W_Gauss={W_g:.4f}")
        assert abs(W_mc - W_ex) < 4 * se + 2 * b * DT  # + jump-time discretisation of trapezoid
        if seq.n == 0:
            assert abs(W_mc - W_g) > 10 * se  # Gaussian formula rejected by the exact MC


def test_reproducible_and_seed_dependent():
    m = model(ONEF, LOR, nz.make_telegraph(1e5, 1e6), WHITE)
    a = nz.sample_detuning(m, TGRID, 8, np.random.default_rng(42))
    b = nz.sample_detuning(m, TGRID, 8, np.random.default_rng(42))
    c = nz.sample_detuning(m, TGRID, 8, np.random.default_rng(43))
    assert np.array_equal(a, b) and not np.allclose(a, c)
    # time origin irrelevant (stationary): shifted grid gives same draws
    d = nz.sample_detuning(m, TGRID + 5e-6, 8, np.random.default_rng(42))
    assert np.allclose(a, d, rtol=1e-12, atol=1e-6)
    assert np.array_equal(nz.sample_detuning(model(), TGRID, 3, np.random.default_rng(0)), np.zeros((3, TGRID.size)))


def test_sampler_input_validation_and_warnings():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        nz.sample_detuning(model(LOR), np.array([0.0, 1e-9, 3e-9]), 2, rng)
    with pytest.raises(ValueError):
        nz.sample_detuning(model(LOR), np.array([0.0]), 2, rng)
    tel_cut = PSDComponent("telegraph", {"b": 1e5, "gamma": 1e6}, 0.0, 1e8)
    with pytest.raises(ValueError):
        nz.sample_detuning(model(tel_cut), TGRID, 2, rng)
    with pytest.raises(ValueError):
        nz.sample_detuning(model(ONEF), TGRID, 2, rng, method="ou")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        nz.sample_detuning(model(nz.make_white(1.0, 2 * PI * 1e9)), TGRID, 2, rng)  # beyond Nyquist 500 MHz
        assert any(issubclass(x.category, RuntimeWarning) for x in w)


def test_sampler_performance_512_by_1e4():
    t = np.arange(10_000) * DT
    m = model(ONEF, LOR, WHITE, nz.make_telegraph(1e5, 1e6))
    t0 = time.perf_counter()
    x = nz.sample_detuning(m, t, 512, np.random.default_rng(1))
    el = time.perf_counter() - t0
    print(f"TOL sampler wall time 512 x 1e4 (1/f + OU + white + telegraph): {el:.2f} s")
    assert x.shape == (512, 10_000)
    assert el < 10.0
