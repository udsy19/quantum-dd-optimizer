"""Tests for ddopt.filters: switching functions, filter functions, chi quadrature and analytic limits.

Lines printed with prefix ``TOL`` are the measured tolerances recorded in docs/PHYSICS.md
(run with ``-s`` to see them).
"""

import math

import numpy as np
import pytest
from scipy import integrate

from ddopt import filters as ff
from ddopt import noise as nz
from ddopt.contracts import NoiseModel, PulseSequence

T = 2e-6
PI = math.pi


def mkseq(centers, width=0.0, phases=None, angles=None, T=T):
    n = len(centers)
    phases = (PI / 2,) * n if phases is None else tuple(phases)
    angles = (PI,) * n if angles is None else tuple(angles)
    return PulseSequence(T=T, centers=tuple(centers), widths=(width,) * n, phases=phases, angles=angles)


def cpmg(n, width=0.0, T=T, phases=None):
    return mkseq([T * (k - 0.5) / n for k in range(1, n + 1)], width, phases, T=T)


def udd(n, width=0.0, T=T):
    return mkseq([T * math.sin(PI * k / (2 * n + 2)) ** 2 for k in range(1, n + 1)], width, T=T)


FID = PulseSequence(T=T)
HAHN = mkseq([T / 2])


def _series(x, coef):
    return sum((-x) ** k / math.factorial(k) * coef(k) for k in range(2, 40))


def lor_fid_exact(sig, tc, T):
    """OU FID: chi = 2 sig^2 tc^2 (x - 1 + e^{-x}), x = T/tc (series for small x: no cancellation)."""
    x = T / tc
    br = _series(x, lambda k: 1.0) if x < 0.5 else x - 1 + math.exp(-x)
    return 2 * sig**2 * tc**2 * br


def lor_hahn_exact(sig, tc, T):
    """OU Hahn: chi = 2 sig^2 tc^2 (x - 3 + 4 e^{-x/2} - e^{-x})."""
    x = T / tc
    br = _series(x, lambda k: 4 * 2.0**-k - 1) if x < 0.5 else x - 3 + 4 * math.exp(-x / 2) - math.exp(-x)
    return 2 * sig**2 * tc**2 * br


def chi_time_domain_lorentzian_inst(seq, sig, tc):
    """chi = int int y(t) y(t') sigma^2 exp(-|t-t'|/tc) dt dt' by 2-D adaptive quadrature over
    the rectangles of piecewise-constant y (independent of the frequency-domain code)."""
    edges = [0.0] + list(seq.centers) + [seq.T]
    signs = [(-1) ** k for k in range(len(edges) - 1)]
    tot = 0.0
    f = lambda tp, t: sig**2 * math.exp(-abs(t - tp) / tc)  # noqa: E731
    kw = dict(epsabs=0, epsrel=1e-12)
    for i in range(len(signs)):
        for j in range(len(signs)):
            a, b, c, d = edges[i], edges[i + 1], edges[j], edges[j + 1]
            if i == j:  # kink on the diagonal: integrate the smooth triangle t' < t twice
                v = 2 * integrate.dblquad(f, a, b, lambda t: a, lambda t: t, **kw)[0]
            else:
                v = integrate.dblquad(f, a, b, c, d, **kw)[0]
            tot += signs[i] * signs[j] * v
    return tot


# ---------------------------------------------------------------------------
# switching function / filter function
# ---------------------------------------------------------------------------


def test_switching_function_ideal_and_finite():
    t = np.linspace(0, T, 1001)
    y = ff.switching_function(cpmg(2), t)
    assert np.all(y[t < T / 4] == 1) and np.all(y[(t > T / 4) & (t < 3 * T / 4)] == -1) and y[-1] == 1
    assert ff.switching_function(FID, np.array([-1e-9, T + 1e-9])).tolist() == [0.0, 0.0]
    w = 100e-9
    seq = mkseq([T / 2], w, phases=[0.0])
    tt = np.linspace(T / 2 - w / 2, T / 2 + w / 2, 11)
    yz = ff.switching_function(seq, tt)
    assert np.allclose(yz, np.cos(PI * (tt - tt[0]) / w), atol=1e-12)
    # X pulse: toggling sigma_z picks up a y-component cos(phi) sin(theta)
    v = ff.toggling_vector(seq, tt)
    assert np.allclose(v[1], np.sin(PI * (tt - tt[0]) / w), atol=1e-12) and np.allclose(v[0], 0)
    # second pulse in CPMG-2: y_z = -cos(theta) during it (sign carried)
    s2 = cpmg(2, w)
    c2 = s2.centers[1]
    tt2 = np.linspace(c2 - w / 2, c2 + w / 2, 7)
    assert np.allclose(ff.switching_function(s2, tt2), -np.cos(PI * (tt2 - tt2[0]) / w), atol=1e-12)


def test_toggling_vector_unit_norm_arbitrary_phases_angles():
    seq = mkseq([0.3e-6, 0.9e-6, 1.5e-6], 80e-9, phases=[0.0, 1.1, 2.5], angles=[PI, 0.7 * PI, 1.3])
    t = np.linspace(0, T, 5001)
    v = ff.toggling_vector(seq, t)
    assert np.allclose(np.linalg.norm(v, axis=0), 1.0, atol=1e-12)


def test_filter_function_closed_forms_ideal():
    w = np.concatenate([[0.0, 1e-3], np.linspace(1e3, 3e8, 400)])
    with np.errstate(invalid="ignore", divide="ignore"):
        f_fid = np.where(w > 0, 4 * np.sin(w * T / 2) ** 2 / w**2, T**2)
        f_hahn = np.where(w > 0, 16 * np.sin(w * T / 4) ** 4 / w**2, 0.0)
    assert np.allclose(ff.filter_function(FID, w), f_fid, rtol=1e-12, atol=1e-30)
    assert np.allclose(ff.filter_function(HAHN, w), f_hahn, rtol=1e-10, atol=1e-28)
    assert ff.filter_function(FID, 0.0) == pytest.approx(T**2)


@pytest.mark.parametrize("seq", [
    cpmg(4, 100e-9, phases=[0, PI / 2, 0, PI / 2]),
    mkseq([0.4e-6, 1.2e-6], 150e-9, phases=[0.3, 2.0], angles=[PI, 0.6 * PI]),
    udd(3, 60e-9),
])
def test_filter_function_matches_numerical_fourier(seq):
    t = np.linspace(0, T, 400_001)
    v = ff.toggling_vector(seq, t)
    w = np.array([0.0, 2e5, 3.3e6, 1.7e7, 6e7, 2.2e8])
    Ynum = integrate.simpson(v[:, None, :] * np.exp(1j * np.outer(w, t))[None], x=t, axis=-1)
    Y = ff.fourier_toggling(seq, w)
    scale = np.abs(Y).max()
    # simpson across the y-kinks at pulse edges limits accuracy to ~1e-9 relative
    assert np.max(np.abs(Y - Ynum)) < 1e-8 * scale
    assert np.allclose(ff.filter_function(seq, w), (np.abs(Ynum) ** 2).sum(0), rtol=1e-6, atol=1e-8 * scale**2)
    assert np.abs(Y[:2]).max() > 1e-3 * scale  # finite pulses: transverse components present


def test_cpmg_passband_peak():
    for n in (4, 8, 16):
        s = cpmg(n)
        w0 = PI * n / T
        w = np.linspace(0.5 * w0, 1.5 * w0, 20001)
        wpk = w[np.argmax(ff.filter_function(s, w))]
        print(f"TOL cpmg{n} passband peak / (pi n/T) - 1 = {wpk / w0 - 1:.2e}")
        assert abs(wpk / w0 - 1) < 0.05
        # filter at the peak ~ (4T/(pi n))^2 * n^2 / ... grows as T^2 (coherent accumulation)
        assert ff.filter_function(s, w0) > 0.3 * T**2


# ---------------------------------------------------------------------------
# chi: analytic limits
# ---------------------------------------------------------------------------


def test_lorentzian_fid_hahn_exact_and_error_estimate_honest():
    sig = 1e5
    for tc in (2e-8, 0.5e-6, 5e-6, 1e-3):
        for seq, exact in ((FID, lor_fid_exact(sig, tc, T)), (HAHN, lor_hahn_exact(sig, tc, T))):
            chi, err = ff.dephasing_variance(nz.make_lorentzian(sig, tc), seq)
            rel = abs(chi - exact) / exact
            print(f"TOL lorentzian tc={tc:.0e} {seq.n}-pulse: rel err {rel:.1e}, est {err / exact:.1e}")
            assert rel < 1e-6
            assert abs(chi - exact) <= err + 1e-12 * exact


def test_quasistatic_limit_fid_and_hahn_cancellation():
    sig = 1e5
    chi0 = sig**2 * T**2
    prev = None
    for tc in (1e-4, 1e-3, 1e-2):
        fid, _ = ff.dephasing_variance(nz.make_lorentzian(sig, tc), FID)
        assert fid / chi0 == pytest.approx(1 - T / (3 * tc), rel=1e-4)
        hahn, _ = ff.dephasing_variance(nz.make_lorentzian(sig, tc), HAHN)
        assert hahn / chi0 < T / tc  # quasi-static noise cancelled (O(T/tc) residue)
        assert hahn * tc / (sig**2 * T**3 / 6) == pytest.approx(1.0, rel=2 * T / tc)  # chi ~ 1/tc
        if prev is not None:
            assert hahn / prev == pytest.approx(0.1, rel=1e-2)
        prev = hahn


def test_white_noise_chi_equals_S0_T_independent_of_pulses():
    S0, wh = 1e4, 2 * PI * 1e12
    for seq in (FID, HAHN, cpmg(8), udd(6)):
        chi, err = ff.dephasing_variance(nz.make_white(S0, wh), seq)
        D = 2 + 4 * seq.n  # sum of squared jumps of y (window edges + pi pulses)
        expected = S0 * T - S0 * D / (PI * wh)  # finite band: missing (1/pi) int_wh^inf S0 D/w^2
        rel = abs(chi - expected) / (S0 * T)
        print(f"TOL white n={seq.n}: |chi - S0(T - D/(pi wh))|/S0T = {rel:.1e}, est {err / (S0 * T):.1e}")
        assert rel < 1e-7
        assert chi == pytest.approx(S0 * T, rel=1e-5)


def test_time_domain_double_integral_matches_frequency_formula():
    sig = 1e5
    for tc in (0.1e-6, 1e-6):
        for seq in (HAHN, cpmg(2), udd(3)):
            chi, err = ff.dephasing_variance(nz.make_lorentzian(sig, tc), seq)
            td = chi_time_domain_lorentzian_inst(seq, sig, tc)
            print(f"TOL time-domain 2D quad tc={tc:.0e} n={seq.n}: rel diff {abs(chi - td) / td:.1e}")
            assert abs(chi - td) / td < 1e-7


def test_time_domain_finite_pulses_vector_ff():
    """chi(generalised FF) = int int y(t).y(t') C(t-t') via autocorrelation of sampled y."""
    sig, tc = 1e5, 0.3e-6
    seq = cpmg(4, 120e-9, phases=[0, PI / 2, 0, PI / 2])
    N = 200_001
    t = np.linspace(0, T, N)
    dt = t[1] - t[0]
    v = ff.toggling_vector(seq, t)
    wq = np.full(N, dt)
    wq[[0, -1]] *= 0.5  # trapezoid weights
    vw = v * wq
    R = sum(np.fft.irfft(np.fft.rfft(vw[a], 2 * N) * np.conj(np.fft.rfft(vw[a], 2 * N)), 2 * N)[:N] for a in range(3))
    lags = np.arange(N) * dt
    C = sig**2 * np.exp(-lags / tc)
    td = C[0] * R[0] + 2 * np.sum(C[1:] * R[1:])
    chi, _ = ff.dephasing_variance(nz.make_lorentzian(sig, tc), seq)
    rel = abs(chi - td) / chi
    print(f"TOL time-domain finite pulses (grid 1e-11 s): rel diff {rel:.1e}")
    assert rel < 1e-4


def test_one_over_f_against_independent_quad():
    A = 1e9
    for alpha in (0.7, 1.0, 1.5):
        c = nz.make_one_over_f(A, alpha, 2 * PI * 1.0, 2 * PI * 10e6)
        for seq, fexpr in ((FID, lambda w: 4 * np.sin(w * T / 2) ** 2 / w**2),
                           (HAHN, lambda w: 16 * np.sin(w * T / 4) ** 4 / w**2)):
            edges = np.geomspace(c.omega_low, c.omega_high, 120)
            ref = sum(integrate.quad(lambda w: A * w**-alpha * fexpr(w), a, b, limit=500,
                                     epsabs=0, epsrel=1e-12)[0] for a, b in zip(edges[:-1], edges[1:])) / PI
            chi, err = ff.dephasing_variance(c, seq)
            rel = abs(chi - ref) / ref
            print(f"TOL 1/f alpha={alpha} n={seq.n}: rel diff vs scipy.quad {rel:.1e}, est {err / ref:.1e}")
            assert rel < 1e-8


def test_quadrature_convergence_in_rtol():
    noise = NoiseModel((nz.make_one_over_f(1e9, 1.0, 2 * PI, 2 * PI * 1e7), nz.make_lorentzian(3e5, 0.5e-6),
                        nz.make_white(1e3, 2 * PI * 1e8)))
    for seq in (FID, cpmg(8, 32e-9), udd(8)):
        vals = {r: ff.dephasing_variance(noise, seq, rtol=r) for r in (1e-3, 1e-6, 1e-9)}
        best = vals[1e-9][0]
        for r, (chi, err) in vals.items():
            print(f"TOL convergence n={seq.n} w={seq.widths[:1]} rtol={r:.0e}: |chi-chi_best|/chi={abs(chi - best) / best:.1e} est={err / best:.1e}")
        assert abs(vals[1e-6][0] - best) / best < 1e-6
        assert abs(vals[1e-3][0] - best) / best < 1e-3


def test_finite_width_converges_to_instantaneous():
    noise = NoiseModel((nz.make_one_over_f(1e9, 1.0, 2 * PI, 2 * PI * 1e7), nz.make_lorentzian(3e5, 0.5e-6)))
    chi0, _ = ff.dephasing_variance(noise, cpmg(8))
    diffs = []
    ws = (64e-9, 32e-9, 16e-9, 8e-9, 4e-9)
    for w in ws:
        chi, _ = ff.dephasing_variance(noise, cpmg(8, w))
        diffs.append(abs(chi - chi0) / chi0)
        print(f"TOL finite->instantaneous CPMG8 w={w:.0e}: rel diff {diffs[-1]:.2e}")
    assert all(d2 < d1 for d1, d2 in zip(diffs[:-1], diffs[1:]))
    assert diffs[-1] < 5e-4
    # measured convergence order (centred symmetric pulses: O(w) term cancels -> ~O(w^2))
    order = math.log(diffs[0] / diffs[-1]) / math.log(ws[0] / ws[-1])
    print(f"TOL finite->instantaneous convergence order {order:.2f}")
    assert 1.7 < order < 2.3


def test_generalised_ff_dominates_z_component():
    seq = cpmg(8, 32e-9)
    w = np.linspace(1e4, 1e9, 2000)
    Y = ff.fourier_toggling(seq, w)
    assert np.all(ff.filter_function(seq, w) >= np.abs(Y[2]) ** 2 - 1e-30)


def test_limits_zero_noise_small_T_high_noise():
    assert ff.dephasing_variance(NoiseModel(), cpmg(4)) == (0.0, 0.0)
    assert ff.dephasing_infidelity(NoiseModel(), cpmg(4)) == 0.0
    assert ff.coherence(nz.make_lorentzian(0.0, 1e-6), FID) == 1.0
    sig, tc = 1e5, 1e-6
    for Tsmall in (1e-9, 1e-12):
        chi, _ = ff.dephasing_variance(nz.make_lorentzian(sig, tc), PulseSequence(T=Tsmall))
        assert chi == pytest.approx(sig**2 * Tsmall**2, rel=1e-3)
        assert ff.dephasing_infidelity(nz.make_lorentzian(sig, tc), PulseSequence(T=Tsmall)) == pytest.approx(
            sig**2 * Tsmall**2 / 6, rel=1e-3)
    big = nz.make_lorentzian(1e9, 1e-6)
    assert ff.dephasing_infidelity(big, FID) == pytest.approx(1 / 3, abs=1e-12)
    assert ff.coherence(big, FID) < 1e-12


def test_model_sum_and_telegraph_equivalence():
    a, b = nz.make_lorentzian(1e5, 0.4e-6), nz.make_one_over_f(1e9, 1.0, 1.0, 1e8)
    s = cpmg(4, 20e-9)
    tot, _ = ff.dephasing_variance(NoiseModel((a, b)), s)
    assert tot == pytest.approx(ff.dephasing_variance(a, s)[0] + ff.dephasing_variance(b, s)[0], rel=1e-12)
    tg = nz.make_telegraph(1e5, 1 / (2 * 0.4e-6))
    assert ff.dephasing_variance(tg, s)[0] == pytest.approx(ff.dephasing_variance(a, s)[0], rel=1e-12)


def test_telegraph_exact_coherence():
    b, g = 2e6, 3e6  # b < gamma: overdamped
    tel = nz.make_telegraph(b, g)
    mu = math.sqrt(g**2 - b**2)
    W = math.exp(-g * T) * (math.cosh(mu * T) + g / mu * math.sinh(mu * T))
    assert ff.telegraph_coherence_exact(tel, FID) == pytest.approx(W, rel=1e-10)
    # weak coupling (b tau_c << 1): Gaussian approximation accurate
    weak = nz.make_telegraph(1e5, 5e7)
    for s in (FID, HAHN, cpmg(4)):
        Wg = ff.coherence(weak, s)
        We = ff.telegraph_coherence_exact(weak, s)
        assert abs(We - Wg) < 1e-3 * (1 - Wg) + 1e-12
    # strong slow telegraph: Gaussian approximation fails (FID: W -> ~cos(bT)-like, not exp(-b^2T^2/2))
    strong = nz.make_telegraph(3e6, 1e4)
    We, Wg = ff.telegraph_coherence_exact(strong, FID), ff.coherence(strong, FID)
    print(f"TOL telegraph strong FID: exact W={We:.4f}, Gaussian W={Wg:.4f}")
    assert abs(We - Wg) > 0.3
    with pytest.raises(ValueError):
        ff.telegraph_coherence_exact(strong, cpmg(2, 40e-9))
