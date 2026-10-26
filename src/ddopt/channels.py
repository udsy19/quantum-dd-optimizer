"""Single-qubit CPTP channels in the Pauli-transfer-matrix (PTM) representation.

Conventions (``docs/PHYSICS_CONVENTIONS.md``; derivations in ``docs/PHYSICS.md`` section 8):

* Pauli basis order (I, X, Y, Z); ``R_ij = (1/2) Tr[P_i Lambda(P_j)]`` (real for Hermiticity-
  preserving maps). A state ``rho = (I + r.sigma)/2`` maps as ``(1, r) -> R (1, r)``.
* Composition: channels applied right-to-left, ``compose_ptm(B, A) = R_B @ R_A = B o A``.
  Infidelities are never added; channels are composed.
* ``|0>`` is the ground state (sigma_z |0> = +|0>); amplitude damping relaxes |1> -> |0> with
  probability ``gamma = 1 - exp(-t/T1)``.
* Average gate fidelity (qubit, d = 2): ``F_avg = (Tr R + 2)/6`` for the channel compared with the
  identity; to compare against a unitary target pass ``R_target.T @ R`` (PTMs of unitaries are
  orthogonal).
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "PAULIS",
    "amplitude_damping_kraus",
    "amplitude_damping_ptm",
    "dephasing_ptm",
    "unitary_ptm",
    "kraus_to_ptm",
    "ptm_to_choi",
    "compose_ptm",
    "avg_gate_fidelity_ptm",
    "amplitude_damping_infidelity",
    "is_cptp_ptm",
    "gamma_from_T1",
]

PAULIS: tuple[np.ndarray, ...] = (
    np.eye(2, dtype=complex),
    np.array([[0, 1], [1, 0]], dtype=complex),
    np.array([[0, -1j], [1j, 0]], dtype=complex),
    np.array([[1, 0], [0, -1]], dtype=complex),
)


def _check_gamma(gamma: float) -> float:
    g = float(gamma)
    if not (0.0 <= g <= 1.0):
        raise ValueError("gamma must lie in [0, 1]")
    return g


def gamma_from_T1(T: float, T1: float) -> float:
    """Amplitude-damping probability ``1 - exp(-T/T1)`` (T, T1 in s; ``T1 = inf`` gives 0)."""
    if T < 0 or not T1 > 0:
        raise ValueError("require T >= 0 and T1 > 0")
    if math.isinf(T1):
        return 0.0
    return -math.expm1(-T / T1)


def amplitude_damping_kraus(gamma: float) -> list[np.ndarray]:
    """Kraus operators ``K0 = diag(1, sqrt(1-gamma))``, ``K1 = sqrt(gamma) |0><1|``."""
    g = _check_gamma(gamma)
    return [np.array([[1, 0], [0, math.sqrt(1 - g)]], dtype=complex),
            np.array([[0, math.sqrt(g)], [0, 0]], dtype=complex)]


def kraus_to_ptm(kraus: list[np.ndarray]) -> np.ndarray:
    """4x4 real PTM of ``rho -> sum_k K rho K^dag``."""
    R = np.zeros((4, 4))
    for j, Pj in enumerate(PAULIS):
        out = sum(K @ Pj @ K.conj().T for K in kraus)
        for i, Pi in enumerate(PAULIS):
            R[i, j] = 0.5 * np.trace(Pi @ out).real
    return R


def amplitude_damping_ptm(gamma: float) -> np.ndarray:
    """PTM ``[[1,0,0,0],[0,s,0,0],[0,0,s,0],[gamma,0,0,1-gamma]]``, ``s = sqrt(1-gamma)``."""
    g = _check_gamma(gamma)
    s = math.sqrt(1 - g)
    R = np.diag([1.0, s, s, 1.0 - g])
    R[3, 0] = g
    return R


def dephasing_ptm(W: float) -> np.ndarray:
    """Pure-dephasing PTM ``diag(1, W, W, 1)`` with coherence factor ``W = <e^{i phi}>`` (real, |W| <= 1)."""
    W = float(W)
    if abs(W) > 1 + 1e-15:
        raise ValueError("|W| must be <= 1")
    return np.diag([1.0, W, W, 1.0])


def unitary_ptm(U: np.ndarray) -> np.ndarray:
    """PTM of ``rho -> U rho U^dag`` (orthogonal 4x4, global phase irrelevant)."""
    U = np.asarray(U, dtype=complex)
    return kraus_to_ptm([U])


def compose_ptm(*ptms: np.ndarray) -> np.ndarray:
    """Composition applied right-to-left: ``compose_ptm(C, B, A) = C @ B @ A`` (A acts first)."""
    R = np.eye(4)
    for P in ptms:
        R = R @ np.asarray(P, dtype=float)
    return R


def avg_gate_fidelity_ptm(R: np.ndarray) -> float:
    """Qubit average gate fidelity w.r.t. identity: ``F = (2 F_pro + 1)/3``, ``F_pro = Tr R / 4``,
    i.e. ``F = (Tr R + 2)/6``. For a unitary target use ``R_target.T @ R``."""
    R = np.asarray(R, dtype=float)
    return float((np.trace(R) + 2.0) / 6.0)


def amplitude_damping_infidelity(gamma: float) -> float:
    """``r_AD = 1 - F_avg = (2 + gamma - 2 sqrt(1-gamma))/6`` (-> gamma/3 + gamma^2/24 for small
    gamma; 1/2 at gamma = 1). Evaluated in the cancellation-free form
    ``[gamma + 2 gamma/(1 + sqrt(1-gamma))]/6``. See docs/PHYSICS.md section 8 for the derivation
    and why the master-prompt expression ``[3 - 2 sqrt(1-gamma) - gamma]/6`` is wrong."""
    g = _check_gamma(gamma)
    return (g + 2.0 * g / (1.0 + math.sqrt(1.0 - g))) / 6.0


def ptm_to_choi(R: np.ndarray) -> np.ndarray:
    """Unnormalised Choi matrix ``J = sum_ab |a><b| (x) Lambda(|a><b|)`` (4x4, trace 2)."""
    R = np.asarray(R, dtype=float)
    J = np.zeros((4, 4), dtype=complex)
    for a in range(2):
        for b in range(2):
            E = np.zeros((2, 2), dtype=complex)
            E[a, b] = 1.0
            coeff = np.array([0.5 * np.trace(P @ E) for P in PAULIS])  # E = sum_j coeff_j P_j
            out_c = R @ coeff  # Pauli coefficients of Lambda(E) (complex linear extension)
            out = sum(out_c[i] * PAULIS[i] for i in range(4))
            J += np.kron(E, out)
    return J


def is_cptp_ptm(R: np.ndarray, tol: float = 1e-10) -> bool:
    """True if ``R`` is a real 4x4 PTM that is trace preserving (first row = e_0) and completely
    positive (Choi eigenvalues >= -tol)."""
    R = np.asarray(R)
    if R.shape != (4, 4) or np.iscomplexobj(R) and np.max(np.abs(R.imag)) > tol:
        return False
    R = np.real(R).astype(float)
    if np.max(np.abs(R[0] - np.array([1.0, 0, 0, 0]))) > tol:
        return False
    J = ptm_to_choi(R)
    ev = np.linalg.eigvalsh(0.5 * (J + J.conj().T))
    return bool(ev.min() >= -tol)
