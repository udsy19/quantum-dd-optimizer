"""Tests for ddopt.sequences (Agent B). Run: PYTHONPATH=src python -m pytest tests/test_sequences.py"""

import math

import numpy as np
import pytest

from ddopt import sequences as S

X = np.array([[0, 1], [1, 0]], dtype=complex)
Y = np.array([[0, -1j], [1j, 0]], dtype=complex)
I2 = np.eye(2, dtype=complex)
T = 1e-6


def test_cpmg_centers_and_y_phase():
    s = S.cpmg(4, T, 20e-9)
    assert np.allclose(s.centers, T * (np.arange(1, 5) - 0.5) / 4, rtol=0, atol=1e-18)
    assert all(p == math.pi / 2 for p in s.phases)
    assert all(a == math.pi for a in s.angles)
    assert s.label == "cpmg" and s.n == 4


def test_xy4_xy8_phases_and_multiples():
    s4 = S.xy4(8, T, 20e-9)
    assert np.allclose(s4.phases, [0, math.pi / 2] * 4)
    s8 = S.xy8(8, T, 20e-9)
    X_, Y_ = 0.0, math.pi / 2
    assert np.allclose(s8.phases, [X_, Y_, X_, Y_, Y_, X_, Y_, X_])
    assert np.allclose(s8.centers, S.cpmg(8, T, 20e-9).centers)
    with pytest.raises(ValueError):
        S.xy4(6, T, 20e-9)
    with pytest.raises(ValueError):
        S.xy8(12, T, 20e-9)


def test_udd_centers():
    n = 5
    s = S.udd(n, T, 10e-9)
    k = np.arange(1, n + 1)
    assert np.allclose(s.centers, T * np.sin(np.pi * k / (2 * n + 2)) ** 2, rtol=0, atol=1e-18)
    # UDD-1 = Hahn timing, UDD-2 = CPMG-2 timing
    assert np.isclose(S.udd(1, T, 0.0).centers[0], T / 2)
    assert np.allclose(S.udd(2, T, 0.0).centers, S.cpmg(2, T, 0.0).centers)


def test_refuses_16x40ns_in_500ns():
    T5 = 500e-9
    assert not S.feasible(16, T5, 40e-9)
    for ctor in (S.cpmg, S.udd, S.xy8, S.xy4):
        with pytest.raises(ValueError):
            ctor(16, T5, 40e-9)
    with pytest.raises(ValueError):
        S.from_gaps(T5, 40e-9, [0.0] * 17, [0.0] * 16)


def test_feasible_boundary():
    assert S.feasible(4, 200e-9, 40e-9, guard=8e-9)  # 160 + 40 = 200
    assert not S.feasible(4, 200e-9, 40e-9, guard=8.1e-9)
    assert S.feasible(0, 1e-9, 0.0)


def test_family_edge_violation_raises_even_if_feasible():
    # 8 x 80 ns fits in 1 us in principle, but UDD's first centre is at T sin^2(pi/18) ~ 30 ns
    assert S.feasible(8, T, 80e-9)
    with pytest.raises(ValueError):
        S.udd(8, T, 80e-9)
    # CPMG-4 edge gap = T/8 - w/2 = 105 ns < guard 110 ns
    with pytest.raises(ValueError):
        S.cpmg(4, T, 40e-9, guard=110e-9)
    S.cpmg(4, T, 40e-9, guard=105e-9 - 1e-12)


def test_dt_grid_alignment_of_starts():
    dt = 4e-9
    s = S.cpmg(3, T, 40e-9, dt_grid=dt)
    starts = np.asarray(s.centers) - np.asarray(s.widths) / 2
    assert np.allclose(starts / dt, np.round(starts / dt), atol=1e-6)
    assert s.metadata["snap_max_shift_s"] <= dt / 2 + 1e-18
    assert s.metadata["width_on_grid"]


def test_snap_to_grid_can_refuse():
    s = S.from_gaps(50e-9, 10e-9, [3e-9, 0.5e-9, 26.5e-9], [0.0, 0.0])
    with pytest.raises(ValueError):
        S.snap_to_grid(s, 4e-9)  # starts 3 -> 4 ns (ends 14), 13.5 -> 12 ns: overlap
    ok = S.snap_to_grid(S.cpmg(4, T, 40e-9), 4e-9)
    ok.validate()
    assert ok.dt_grid == 4e-9


def test_from_gaps_roundtrip_and_sum_check():
    s = S.cpmg(4, T, 40e-9)
    g = s.gaps()
    s2 = S.from_gaps(T, 40e-9, g, s.phases)
    assert np.allclose(s2.centers, s.centers, rtol=0, atol=1e-18)
    with pytest.raises(ValueError):
        S.from_gaps(T, 40e-9, g * 1.01, s.phases)
    with pytest.raises(ValueError):
        S.from_gaps(T, 40e-9, g[:-1], s.phases)


def test_zero_width_pulses_allowed():
    s = S.cpmg(8, T, 0.0)
    s.validate()
    assert np.allclose(s.gaps().sum(), T)


def _equal_up_to_phase(A, B):
    return abs(abs(np.trace(A.conj().T @ B)) - 2) < 1e-12


def test_ideal_unitary_even_and_odd():
    # even: identity up to global phase
    for s in (S.cpmg(4, T, 20e-9), S.xy4(4, T, 20e-9), S.xy8(8, T, 20e-9), S.udd(6, T, 10e-9)):
        assert _equal_up_to_phase(S.ideal_unitary(s), I2), s.label
    # odd: a pi rotation, orthogonal to the identity (|Tr| = 0)
    for s, P in ((S.hahn(T, 20e-9), X), (S.cpmg(3, T, 20e-9), Y), (S.udd(5, T, 10e-9), Y)):
        U0 = S.ideal_unitary(s)
        assert abs(np.trace(U0)) < 1e-12, s.label
        assert _equal_up_to_phase(U0, P), s.label
    # arbitrary-phase Hahn: pi rotation about cos(p)X + sin(p)Y
    p = 0.7
    U0 = S.ideal_unitary(S.hahn(T, 20e-9, phase=p))
    assert _equal_up_to_phase(U0, math.cos(p) * X + math.sin(p) * Y)
    assert np.allclose(S.ideal_unitary(S.free(T)), I2)


def test_xy4_product_is_minus_identity_in_time_order():
    # P = -i n.sigma for a pi pulse; time order Y X Y X (X first) = (-i)^4 (YX)^2 = -I
    assert np.allclose(S.ideal_unitary(S.xy4(4, T, 20e-9)), -I2)
