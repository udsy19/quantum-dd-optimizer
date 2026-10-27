"""Tests for ddopt.channels: Kraus/PTM consistency, CPTP checks, fidelity formulas and limits."""

import math

import numpy as np
import pytest
from scipy.linalg import expm

from ddopt import channels as ch

X, Y, Z = ch.PAULIS[1], ch.PAULIS[2], ch.PAULIS[3]
CARDINAL = [np.array(v, dtype=complex) / np.linalg.norm(v) for v in
            ([1, 0], [0, 1], [1, 1], [1, -1], [1, 1j], [1, -1j])]


def _apply(kraus, rho):
    return sum(K @ rho @ K.conj().T for K in kraus)


def _avg_fid_states(kraus, states, U=np.eye(2)):
    vals = []
    for psi in states:
        rho = np.outer(psi, psi.conj())
        tgt = U @ psi
        vals.append((tgt.conj() @ _apply(kraus, rho) @ tgt).real)
    return float(np.mean(vals))


@pytest.mark.parametrize("gamma", [0.0, 1e-9, 1e-4, 0.03, 0.3, 0.77, 1.0])
def test_ad_infidelity_formula_vs_state_averages(gamma):
    K = ch.amplitude_damping_kraus(gamma)
    r = ch.amplitude_damping_infidelity(gamma)
    # cardinal states form a 2-design -> exact average
    assert abs((1 - _avg_fid_states(K, CARDINAL)) - r) < 1e-14
    # PTM formula
    assert abs((1 - ch.avg_gate_fidelity_ptm(ch.amplitude_damping_ptm(gamma))) - r) < 1e-14
    # closed form as derived in docs/PHYSICS.md
    assert abs(r - (2 + gamma - 2 * math.sqrt(1 - gamma)) / 6) < 1e-15


def test_ad_infidelity_haar_monte_carlo():
    rng = np.random.default_rng(12345)
    v = rng.standard_normal((200_000, 2)) + 1j * rng.standard_normal((200_000, 2))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    gamma = 0.4
    K0, K1 = ch.amplitude_damping_kraus(gamma)
    # <psi|K psi>|^2 summed over Kraus = <psi|Lambda(psi)|psi>
    f = np.abs(np.einsum("ni,ij,nj->n", v.conj(), K0, v)) ** 2 + np.abs(np.einsum("ni,ij,nj->n", v.conj(), K1, v)) ** 2
    r_mc, se = 1 - f.mean(), f.std(ddof=1) / math.sqrt(f.size)
    r = ch.amplitude_damping_infidelity(gamma)
    assert abs(r_mc - r) < 4 * se
    wrong = (3 - 2 * math.sqrt(1 - gamma) - gamma) / 6  # master-prompt expression
    assert abs(r_mc - wrong) > 50 * se


def test_master_prompt_ad_formula_fails_gamma_zero_limit():
    wrong = lambda g: (3 - 2 * math.sqrt(1 - g) - g) / 6  # noqa: E731
    assert wrong(0.0) == pytest.approx(1 / 6)  # identity channel would have infidelity 1/6: wrong
    assert ch.amplitude_damping_infidelity(0.0) == 0.0


def test_ad_limits_tiny_gamma_and_full():
    for g in (1e-12, 1e-8, 1e-5):
        r = ch.amplitude_damping_infidelity(g)
        assert r == pytest.approx(g / 3 + g**2 / 24, rel=1e-6)
        assert r > 0
    assert ch.amplitude_damping_infidelity(1.0) == pytest.approx(0.5)


def test_kraus_ptm_consistency_and_cptp():
    for g in (0.0, 0.2, 1.0):
        K = ch.amplitude_damping_kraus(g)
        assert np.allclose(sum(k.conj().T @ k for k in K), np.eye(2))
        R = ch.amplitude_damping_ptm(g)
        assert np.allclose(ch.kraus_to_ptm(K), R, atol=1e-15)
        assert ch.is_cptp_ptm(R)
        J = ch.ptm_to_choi(R)
        assert abs(np.trace(J) - 2) < 1e-14
    # Bloch-vector action: |1> (r_z = -1) relaxes to r_z = 1 - 2(1-gamma)
    g = 0.3
    out = ch.amplitude_damping_ptm(g) @ np.array([1, 0, 0, -1.0])
    assert np.allclose(out, [1, 0, 0, 2 * g - 1])


def test_dephasing_ptm_and_limits():
    for W in (1.0, 0.9, 0.0, -0.5):
        R = ch.dephasing_ptm(W)
        assert ch.is_cptp_ptm(R)
        assert (1 - ch.avg_gate_fidelity_ptm(R)) == pytest.approx((1 - W) / 3, abs=1e-15)
    assert 1 - ch.avg_gate_fidelity_ptm(ch.dephasing_ptm(0.0)) == pytest.approx(1 / 3)  # W -> 0
    assert 1 - ch.avg_gate_fidelity_ptm(ch.dephasing_ptm(1.0)) == 0.0  # zero noise


def test_non_cptp_detected():
    assert not ch.is_cptp_ptm(np.diag([1.0, 1.0, 1.0, -1.0]))  # transpose map: positive, not CP
    assert not ch.is_cptp_ptm(np.diag([1.0, 1.2, 1.0, 1.0]))
    R = np.eye(4)
    R[0, 3] = 0.1  # not trace preserving
    assert not ch.is_cptp_ptm(R)
    assert not ch.is_cptp_ptm(np.diag([1.0, 1.0, 1.0, 1.0])[:3])


def test_unitary_ptm_and_target_fidelity():
    rng = np.random.default_rng(7)
    for _ in range(5):
        H = rng.standard_normal((2, 2)) + 1j * rng.standard_normal((2, 2))
        U = expm(-1j * (H + H.conj().T))
        R = ch.unitary_ptm(U)
        assert np.allclose(R @ R.T, np.eye(4), atol=1e-13)
        assert ch.is_cptp_ptm(R)
        assert ch.avg_gate_fidelity_ptm(R.T @ R) == pytest.approx(1.0, abs=1e-13)
        # noisy channel graded against U equals state-average against U
        g = 0.1
        Kn = [U @ k for k in ch.amplitude_damping_kraus(g)]
        Rn = ch.compose_ptm(R, ch.amplitude_damping_ptm(g))
        assert ch.avg_gate_fidelity_ptm(R.T @ Rn) == pytest.approx(_avg_fid_states(Kn, CARDINAL, U), abs=1e-13)
    # pi rotation about X: PTM diag(1, 1, -1, -1)
    assert np.allclose(ch.unitary_ptm(-1j * X), np.diag([1, 1, -1, -1]), atol=1e-15)


def test_composition_order_and_not_additive():
    Rx = ch.unitary_ptm(expm(-1j * math.pi / 4 * X))  # pi/2 about X
    Rad = ch.amplitude_damping_ptm(0.5)
    # compose(B, A) = B o A: apply AD then rotation to |1>
    bloch = np.array([1, 0, 0, -1.0])
    assert np.allclose(ch.compose_ptm(Rx, Rad) @ bloch, Rx @ (Rad @ bloch))
    assert not np.allclose(ch.compose_ptm(Rx, Rad), ch.compose_ptm(Rad, Rx))
    assert np.allclose(ch.compose_ptm(), np.eye(4))
    # composed dephasing + AD vs naive sum of infidelities: sum overestimates by (1-W)(1-s)/3
    for W, g in ((0.9, 0.05), (0.5, 0.3), (0.99, 1e-3)):
        s = math.sqrt(1 - g)
        r_comp = 1 - ch.avg_gate_fidelity_ptm(ch.compose_ptm(ch.amplitude_damping_ptm(g), ch.dephasing_ptm(W)))
        r_sum = (1 - W) / 3 + ch.amplitude_damping_infidelity(g)
        assert r_comp == pytest.approx((2 + g - 2 * s * W) / 6, abs=1e-15)
        assert r_sum - r_comp == pytest.approx((1 - W) * (1 - s) / 3, abs=1e-15)
        assert ch.is_cptp_ptm(ch.compose_ptm(ch.amplitude_damping_ptm(g), ch.dephasing_ptm(W)))
    # AD is phase covariant: commutes with z rotations
    Rz = ch.unitary_ptm(expm(-1j * 0.37 * Z))
    assert np.allclose(Rz @ Rad, Rad @ Rz, atol=1e-15)


def test_ad_segments_compose_to_total_T1_decay():
    T1 = 50e-6
    g1, g2 = ch.gamma_from_T1(0.3e-6, T1), ch.gamma_from_T1(0.7e-6, T1)
    R = ch.compose_ptm(ch.amplitude_damping_ptm(g2), ch.amplitude_damping_ptm(g1))
    assert np.allclose(R, ch.amplitude_damping_ptm(ch.gamma_from_T1(1.0e-6, T1)), atol=1e-15)


def test_gamma_from_T1_limits():
    assert ch.gamma_from_T1(0.0, 1e-6) == 0.0  # T = 0
    assert ch.gamma_from_T1(1e-6, math.inf) == 0.0
    assert ch.gamma_from_T1(1e-15, 1e-4) == pytest.approx(1e-11, rel=1e-9)
    assert ch.gamma_from_T1(1.0, 1e-6) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        ch.gamma_from_T1(-1.0, 1.0)
    with pytest.raises(ValueError):
        ch.amplitude_damping_ptm(1.5)
