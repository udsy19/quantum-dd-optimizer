"""Tests for ddopt.simulator (Agent B).

All noise here is *injected* (``delta_traj``) or produced by a stub ``ddopt.noise`` module,
so these tests do not depend on Agent A's sampler. Tolerances quoted in comments are the
values observed when the tests were written (Linux x86_64, Python 3.13, numpy 2.x)."""

import math
import sys
import time
import types

import numpy as np
import pytest
from scipy.linalg import expm

from ddopt import sequences as S
from ddopt import simulator as M
from ddopt.contracts import ControlErrors, DetuningProfile, NoiseModel, SimulationConfig

X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
Z = np.diag([1.0, -1.0]).astype(complex)
I2 = np.eye(2, dtype=complex)
PAULIS = [I2, X, Y, Z]
T = 1e-6
NO_NOISE = NoiseModel()


def cfg(**kw):
    base = dict(n_traj=64, seed=0, noise_dt=1e-9, pulse_steps=8, include_T1=False)
    base.update(kw)
    return SimulationConfig(**base)


def grid(Tw=T, dt=1e-9):
    return M.time_grid(Tw, dt)


def ptm_ref(U):
    """Definition-level PTM (independent of the simulator's quaternion closed form)."""
    return np.array([[0.5 * np.trace(Pi @ U @ Pj @ U.conj().T).real for Pj in PAULIS] for Pi in PAULIS])


def families():
    return [
        S.free(T),
        S.hahn(T, 40e-9),
        S.hahn(T, 40e-9, phase=0.7),
        S.cpmg(1, T, 40e-9),
        S.cpmg(3, T, 40e-9),
        S.cpmg(4, T, 40e-9),
        S.xy4(4, T, 40e-9),
        S.xy8(8, T, 40e-9),
        S.udd(5, T, 10e-9),
        S.udd(6, T, 10e-9),
        S.cpmg(7, T, 0.0),
    ]


# ---------------------------------------------------------------------------
# propagation correctness
# ---------------------------------------------------------------------------


def test_time_grid_covers_T():
    g = M.time_grid(1.05e-6, 0.1e-6)
    assert g[-1] >= 1.05e-6 and np.allclose(np.diff(g), 0.1e-6)
    assert M.time_grid(1e-6, 1e-9).size == 1001


def test_unitarity_random_noise_and_errors():
    rng = np.random.default_rng(1)
    t = grid()
    for s in families():
        d = rng.normal(0, 2e7, (32, t.size))
        U = M.propagate(s, d, t, pulse_steps=5, amp_eps=rng.normal(0, 0.05, 32),
                        phase_err=rng.normal(0, 0.1, 32))
        err = np.abs(U @ U.conj().transpose(0, 2, 1) - I2).max()
        assert err < 1e-12, (s.label, err)


def test_ptm_closed_form_matches_definition():
    rng = np.random.default_rng(2)
    for _ in range(20):
        A = rng.normal(size=(2, 2)) + 1j * rng.normal(size=(2, 2))
        Hm = A + A.conj().T
        U = expm(-1j * Hm) * np.exp(1j * rng.uniform(0, 6.28))  # include a global phase
        assert np.allclose(M._unitary_ptm(U), ptm_ref(U), atol=1e-12)


def test_free_evolution_phase_exact_for_linear_detuning():
    # trapezoid of a piecewise-linear interpolant is exact for a linear ramp, also at
    # off-grid segment edges
    t = grid(dt=7e-9)  # T not a multiple of dt: grid overshoots T
    a, b = 3e6, 4e12
    d = a + b * t
    s = S.free(T)
    U = M.propagate(s, d, t)[0]
    phi = a * T + 0.5 * b * T**2
    assert np.allclose(U, np.diag([np.exp(-0.5j * phi), np.exp(0.5j * phi)]), atol=1e-12)


def test_propagate_matches_expm_reference():
    """Fine-step scipy expm of the same Hamiltonian (same piecewise-linear delta) agrees."""
    s = S.from_gaps(T, 100e-9, [0.2e-6, 0.3e-6, 0.3e-6], [0.3, 1.0])
    t = grid(dt=5e-9)
    d = 2e7 * np.sin(2 * np.pi * 3.3e6 * t)
    U = M.propagate(s, d, t, pulse_steps=4000)[0]
    N = 20000
    h = T / N
    Ur = I2.copy()
    for k in range(N):
        x = (k + 0.5) * h
        Hk = 0.5 * np.interp(x, t, d) * Z
        for c, p in zip(s.centers, s.phases):
            if abs(x - c) < 50e-9:
                Hk = Hk + 0.5 * (math.pi / 100e-9) * (math.cos(p) * X + math.sin(p) * Y)
        Ur = expm(-1j * h * Hk) @ Ur
    err = np.abs(U - Ur).max()
    assert err < 1e-6, err  # observed 5.1e-8


def test_pulse_steps_convergence():
    """Midpoint sub-stepping converges as m^-2 for a time-dependent detuning during pulses.
    Observed max|U_m - U_1024| (CPMG-4, 40 ns pulses, 5 MHz-amplitude 7 MHz sinusoid):
    m=1: 0.187, 2: 0.048, 4: 0.012, 8: 3.2e-3, 16: 8.0e-4, 32: 2.0e-4, 64: 5.0e-5."""
    s = S.cpmg(4, T, 40e-9)
    t = grid()
    d = (2 * np.pi * 5e6 * np.sin(2 * np.pi * 7e6 * t + 0.3))[None, :]
    Uref = M.propagate(s, d, t, pulse_steps=1024)
    errs = [np.abs(M.propagate(s, d, t, pulse_steps=m) - Uref).max() for m in (1, 2, 4, 8, 16, 32, 64)]
    ratios = np.array(errs[:-1]) / np.array(errs[1:])
    assert np.all(ratios > 3.5) and np.all(ratios < 4.5), ratios
    assert errs[3] < 4e-3  # m = 8 (default)


def test_noise_dt_convergence():
    """Grid refinement converges as dt^2. Observed max|U_dt - U_{dt=0.0625ns}| (64 sub-steps):
    8 ns: 9.3e-3, 4 ns: 2.3e-3, 2 ns: 5.8e-4, 1 ns: 1.5e-4, 0.5 ns: 3.7e-5."""
    s = S.cpmg(4, T, 40e-9)
    f = lambda tt: 2 * np.pi * 5e6 * np.sin(2 * np.pi * 7e6 * tt + 0.3)

    def run(dt):
        tt = M.time_grid(T, dt)
        return M.propagate(s, f(tt)[None, :], tt, pulse_steps=64)

    Ur = run(0.0625e-9)
    errs = [np.abs(run(dt) - Ur).max() for dt in (8e-9, 4e-9, 2e-9, 1e-9, 0.5e-9)]
    ratios = np.array(errs[:-1]) / np.array(errs[1:])
    assert np.all(ratios > 3.0) and np.all(ratios < 5.0), ratios
    assert errs[3] < 3e-4  # 1 ns (default noise_dt)


def test_grid_must_cover_window():
    s = S.hahn(T, 20e-9)
    t = np.linspace(0, 0.9 * T, 100)
    with pytest.raises(ValueError):
        M.propagate(s, np.zeros(100), t)
    with pytest.raises(ValueError):
        M.simulate(s, NO_NOISE, cfg(), delta_traj=np.zeros((4, 50)))


# ---------------------------------------------------------------------------
# target / frame logic
# ---------------------------------------------------------------------------


def test_zero_noise_compensated_infidelity():
    t = grid()
    for s in families():
        r = M.simulate(s, NO_NOISE, cfg(n_traj=4), delta_traj=np.zeros((4, t.size)))
        assert r.infidelity <= 1e-10, (s.label, s.n, r.infidelity)
        r2 = M.simulate(s, NO_NOISE, cfg(n_traj=2))  # no components: no sampler needed
        assert r2.infidelity <= 1e-10


def test_odd_n_graded_against_corrected_target_not_identity():
    t = grid()
    for s in (S.hahn(T, 40e-9), S.cpmg(3, T, 40e-9), S.udd(5, T, 10e-9)):
        U = M.propagate(s, np.zeros(t.size), t)[0]
        F_vs_identity = (abs(np.trace(U)) ** 2 + 2) / 6
        assert abs((1 - F_vs_identity) - 2 / 3) < 1e-12  # grading against I would be wrong
        r = M.simulate(s, NO_NOISE, cfg(n_traj=1), delta_traj=np.zeros((1, t.size)))
        assert r.infidelity < 1e-12
        assert abs(np.trace(S.ideal_unitary(s))) < 1e-12


def test_virtual_z_restores_free_evolution_with_known_constant_detuning():
    d0 = 2 * np.pi * 0.3e6
    nm = NoiseModel(detuning=DetuningProfile("constant", d0))
    s = S.free(T)
    r0 = M.simulate(s, nm, cfg(n_traj=2))
    assert np.isclose(r0.infidelity, (2 / 3) * math.sin(d0 * T / 2) ** 2, rtol=1e-10)
    r1 = M.simulate(s, nm, cfg(n_traj=2, frame_correction="ideal_control_plus_virtual_z"))
    assert np.isclose(r1.virtual_z_angle, (d0 * T + math.pi) % (2 * math.pi) - math.pi)
    assert r1.infidelity < 1e-12
    # an *unknown* offset is not corrected by the virtual Z
    off = 2 * np.pi * 0.1e6
    r2 = M.simulate(s, nm, cfg(n_traj=2, frame_correction="ideal_control_plus_virtual_z",
                               control_errors=ControlErrors(detuning_offset=off)))
    assert np.isclose(r2.infidelity, (2 / 3) * math.sin(off * T / 2) ** 2, rtol=1e-8)


def test_virtual_z_closed_form_is_optimal():
    nm = NoiseModel(detuning=DetuningProfile("smooth_rect", 2 * np.pi * 2e6, 0.1e-6, 0.45e-6, 10e-9))
    s = S.cpmg(3, T, 40e-9)
    c = cfg(n_traj=1)
    th = M.virtual_z_angle(s, nm, c)
    t = grid()
    Ud = M.propagate(s, nm.detuning(t), t)[0]
    U0 = S.ideal_unitary(s)
    thetas = np.linspace(-np.pi, np.pi, 20001)
    F = [(abs(np.trace((M._rz(np.array(x)) @ U0).conj().T @ Ud)) ** 2 + 2) / 6 for x in thetas]
    Fbest = max(F)
    F_th = (abs(np.trace((M._rz(np.array(th)) @ U0).conj().T @ Ud)) ** 2 + 2) / 6
    assert F_th >= Fbest - 1e-9
    rc = M.simulate(s, nm, cfg(n_traj=1, frame_correction="ideal_control_plus_virtual_z"))
    ru = M.simulate(s, nm, cfg(n_traj=1))
    assert rc.infidelity <= ru.infidelity + 1e-15
    assert np.isclose(1 - rc.infidelity, F_th, atol=1e-12)


# ---------------------------------------------------------------------------
# physics checks with injected noise
# ---------------------------------------------------------------------------


def test_quasi_static_echo_residual_vanishes_with_width():
    """Static detuning (per trajectory, sigma = 2pi x 1 MHz). Echo cancels it up to finite-width
    errors: infidelity ~ (delta w)^2, i.e. the residual rotation is O(width).
    Observed (200 traj): free 0.355; Hahn w=80,40,20,10,5,2.5 ns: 1.5e-2, 3.9e-3, 9.8e-4,
    2.5e-4, 6.2e-5, 1.5e-5; CPMG-4: 0.113, 3.9e-2, 1.1e-2, 2.8e-3, 7.1e-4, 1.8e-4."""
    rng = np.random.default_rng(0)
    t = grid()
    dk = rng.normal(0, 2 * np.pi * 1e6, 200)
    d = np.repeat(dk[:, None], t.size, axis=1)
    c = cfg(n_traj=200)
    r_free = M.simulate(S.free(T), NO_NOISE, c, delta_traj=d).infidelity
    widths = [80e-9, 40e-9, 20e-9, 10e-9, 5e-9, 2.5e-9]
    for ctor in (lambda w: S.hahn(T, w), lambda w: S.cpmg(4, T, w)):
        r = np.array([M.simulate(ctor(w), NO_NOISE, c, delta_traj=d).infidelity for w in widths])
        assert np.all(np.diff(r) < 0)
        ratios = r[:-1] / r[1:]
        assert np.all(ratios[1:] > 3.5), ratios  # -> 4 (quadratic in width) as w -> 0
        assert r[-1] < 1e-3 * r_free
    # ideal instantaneous echo cancels static detuning exactly
    r0 = M.simulate(S.hahn(T, 0.0), NO_NOISE, c, delta_traj=d).infidelity
    assert r0 < 1e-12


def test_amplitude_error_cpmg_vs_xy4_xy8():
    """Pure static amplitude error eps, no detuning (free segments are exactly identity).
    CPMG (all pulses about one axis): exact r = (2/3) sin^2(n pi eps / 2) for either axis.
    XY4: first-order toggling-frame error X - Y - X + Y = 0 -> r = O(eps^4);
    XY8: observed O(eps^6). Observed n=4, eps=0.01: CPMG 2.63e-3, XY4 1.62e-7; XY8 (n=8) 3.2e-10."""
    t = grid()
    z = np.zeros((1, t.size))
    for eps in (0.005, 0.01, 0.02):
        kw = dict(delta_traj=z, amp_eps=np.array([eps]), phase_err=np.array([0.0]))
        for n in (4, 8):
            exact = (2 / 3) * math.sin(n * math.pi * eps / 2) ** 2
            for ph in (math.pi / 2, 0.0):
                r = M.simulate(S.cpmg(n, T, 20e-9, phase=ph), NO_NOISE, cfg(n_traj=1), **kw)
                assert np.isclose(r.infidelity, exact, rtol=1e-9)
        r4 = M.simulate(S.xy4(4, T, 20e-9), NO_NOISE, cfg(n_traj=1), **kw).infidelity
        r4b = M.simulate(S.xy4(4, T, 20e-9), NO_NOISE, cfg(n_traj=1), delta_traj=z,
                         amp_eps=np.array([2 * eps]), phase_err=np.array([0.0])).infidelity
        assert 14 < r4b / r4 < 18  # quartic scaling
        assert r4 < 1e-2 * (2 / 3) * math.sin(4 * math.pi * eps / 2) ** 2  # XY4 << CPMG-4
        r8 = M.simulate(S.xy8(8, T, 20e-9), NO_NOISE, cfg(n_traj=1), **kw).infidelity
        assert r8 < r4


def test_phase_error_draws_and_amp_error_draws_used():
    c = cfg(n_traj=128, control_errors=ControlErrors(amp_rel_std=0.02, phase_std=0.05))
    t = grid()
    r = M.simulate(S.xy4(4, T, 20e-9), NO_NOISE, c, delta_traj=np.zeros((128, t.size)))
    assert r.infidelity > 0
    rng = np.random.default_rng(c.seed)
    a = 0.02 * rng.standard_normal(128)
    p = 0.05 * rng.standard_normal(128)
    r2 = M.simulate(S.xy4(4, T, 20e-9), NO_NOISE, c, delta_traj=np.zeros((128, t.size)),
                    amp_eps=a, phase_err=p)
    assert r2.infidelity == r.infidelity


def test_channel_infidelity_equals_mean_per_trajectory():
    rng = np.random.default_rng(3)
    t = grid()
    d = rng.normal(0, 3e6, (50, 1)) + rng.normal(0, 1e7, (50, t.size))
    for incl in (False, True):
        c = cfg(n_traj=50, include_T1=incl)
        r = M.simulate(S.xy4(4, T, 40e-9), NoiseModel(T1=30e-6), c, delta_traj=d)
        assert np.isclose(r.infidelity, np.mean(r.per_traj_infidelity), rtol=1e-12, atol=1e-15)
        assert np.isclose(r.infidelity_stderr, np.std(r.per_traj_infidelity, ddof=1) / math.sqrt(50))


def test_multi_seed_stderr_consistent_with_seed_spread():
    """Quasi-static Gaussian detuning, free evolution: r = (1 - exp(-sigma^2 T^2/2))/3.
    30 independent seeds x 256 trajectories. Observed: seed spread 8.9e-3, mean stderr
    1.17e-2 (ratio 0.76), mean 0.18190 vs exact 0.18199."""
    sigma = 2 * np.pi * 0.2e6
    t = grid()
    c = cfg(n_traj=256)
    vals, ses = [], []
    for seed in range(30):
        rng = np.random.default_rng(1000 + seed)
        d = np.repeat(rng.normal(0, sigma, 256)[:, None], t.size, axis=1)
        r = M.simulate(S.free(T), NO_NOISE, c, delta_traj=d)
        vals.append(r.infidelity)
        ses.append(r.infidelity_stderr)
    vals = np.array(vals)
    ratio = vals.std(ddof=1) / np.mean(ses)
    assert 0.6 < ratio < 1.5, ratio
    exact = (1 - math.exp(-(sigma * T) ** 2 / 2)) / 3
    assert abs(vals.mean() - exact) < 4 * vals.std(ddof=1) / math.sqrt(30)


# ---------------------------------------------------------------------------
# T1
# ---------------------------------------------------------------------------


def test_T1_only_free_evolution_formula():
    t = grid()
    for T1 in (2e-6, 10e-6, 100e-6):
        g = 1 - math.exp(-T / T1)
        r = M.simulate(S.free(T), NoiseModel(T1=T1), cfg(n_traj=2, include_T1=True),
                       delta_traj=np.zeros((2, t.size)))
        assert np.isclose(r.infidelity, (2 + g - 2 * math.sqrt(1 - g)) / 6, rtol=1e-12)
    # limits of the formula itself
    f = lambda g: (2 + g - 2 * math.sqrt(1 - g)) / 6
    assert f(0.0) == 0.0 and np.isclose(f(1.0), 0.5) and np.isclose(f(1e-8) / 1e-8, 1 / 3, rtol=1e-6)


def test_T1_ignored_when_disabled_or_infinite():
    t = grid()
    z = np.zeros((2, t.size))
    s = S.hahn(T, 40e-9)
    assert M.simulate(s, NoiseModel(T1=5e-6), cfg(n_traj=2, include_T1=False), delta_traj=z).infidelity < 1e-12
    assert M.simulate(s, NoiseModel(), cfg(n_traj=2, include_T1=True), delta_traj=z).infidelity < 1e-12


def _kraus_ad(g):
    return [np.array([[1, 0], [0, math.sqrt(1 - g)]]), np.array([[0, math.sqrt(g)], [0, 0]])]


def _apply_kraus(rho, ks):
    return sum(K @ rho @ K.conj().T for K in ks)


def test_T1_with_instantaneous_hahn_matches_kraus_and_six_states():
    """Width-0 Hahn with T1 and a static detuning: Lambda = Rz AD(T/2) X Rz AD(T/2) exactly.
    Compare the simulator's channel with an independent Kraus computation on the six cardinal
    states, and the F_avg formula with the six-state average fidelity."""
    T1, d0 = 3e-6, 2 * np.pi * 0.4e6
    s = S.hahn(T, 0.0)
    t = grid()
    r = M.simulate(s, NoiseModel(T1=T1), cfg(n_traj=1, include_T1=True),
                   delta_traj=np.full((1, t.size), d0))
    R = np.array(r.channel_ptm)
    g = 1 - math.exp(-(T / 2) / T1)
    Uh = np.diag([np.exp(-0.5j * d0 * T / 2), np.exp(0.5j * d0 * T / 2)])
    Px = -1j * X
    states = [np.array([1, 0]), np.array([0, 1]), np.array([1, 1]) / math.sqrt(2),
              np.array([1, -1]) / math.sqrt(2), np.array([1, 1j]) / math.sqrt(2),
              np.array([1, -1j]) / math.sqrt(2)]
    U_target = S.ideal_unitary(s)
    fids = []
    for psi in states:
        rho = np.outer(psi, psi.conj())
        out = _apply_kraus(rho, _kraus_ad(g))
        out = Uh @ out @ Uh.conj().T
        out = Px @ out @ Px.conj().T
        out = _apply_kraus(out, _kraus_ad(g))
        out = Uh @ out @ Uh.conj().T
        # simulator channel on the same state
        bloch = np.array([np.trace(P @ rho).real for P in PAULIS])
        out_sim = 0.5 * sum(v * P for v, P in zip(R @ bloch, PAULIS))
        assert np.allclose(out, out_sim, atol=1e-12)
        tgt = U_target @ psi
        fids.append(np.real(tgt.conj() @ out @ tgt))
    assert np.isclose(np.mean(fids), 1 - r.infidelity, atol=1e-12)


# ---------------------------------------------------------------------------
# draw order / CRN with a stub ddopt.noise module
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_noise(monkeypatch):
    mod = types.ModuleType("ddopt.noise")

    def sample_detuning(model, t, n_traj, rng):
        return rng.normal(0.0, 1e6, (n_traj, len(t)))

    mod.sample_detuning = sample_detuning
    monkeypatch.setitem(sys.modules, "ddopt.noise", mod)
    return mod


def test_frozen_draws_reproduce_internal_sampling(stub_noise):
    from ddopt.contracts import PSDComponent

    nm = NoiseModel(components=(PSDComponent("lorentzian", {"sigma": 1e6, "tau_c": 1e-6}),))
    c = cfg(n_traj=16, seed=7, control_errors=ControlErrors(amp_rel_std=0.01, amp_rel_bias=0.002,
                                                            phase_std=0.03))
    s = S.cpmg(4, T, 40e-9)
    r = M.simulate(s, nm, c)
    fd = M.frozen_draws(nm, T, c)
    r2 = M.simulate(s, nm, c, delta_traj=fd["delta"], t_grid=fd["t"], amp_eps=fd["amp_eps"],
                    phase_err=fd["phase_err"])
    assert r.infidelity == r2.infidelity
    # documented draw order: noise, then amp normals, then phase normals
    rng = np.random.default_rng(7)
    rng.normal(0.0, 1e6, (16, fd["t"].size))
    assert np.allclose(fd["amp_eps"], 0.002 + 0.01 * rng.standard_normal(16))
    assert np.allclose(fd["phase_err"], 0.03 * rng.standard_normal(16))
    assert r.provenance["draw_source"] == "sampled" and r.provenance["seed"] == 7
    assert r.provenance["assumptions"]
    # different seed -> different estimate
    assert M.simulate(s, nm, cfg(n_traj=16, seed=8)).infidelity != r.infidelity


# ---------------------------------------------------------------------------
# performance (recorded in the module docstring)
# ---------------------------------------------------------------------------


def test_propagate_timing():
    s = S.cpmg(16, T, 40e-9)
    t = grid()
    d = np.random.default_rng(0).normal(0, 1e7, (256, t.size))
    M.propagate(s, d, t)
    times = []
    for _ in range(7):
        t0 = time.perf_counter()
        M.propagate(s, d, t, pulse_steps=8, amp_eps=0.01, phase_err=0.01)
        times.append(time.perf_counter() - t0)
    med = float(np.median(times))
    print(f"propagate 256 traj, n=16, 8 steps, N_grid={t.size}: median {med * 1e3:.2f} ms")
    assert med < 0.05
