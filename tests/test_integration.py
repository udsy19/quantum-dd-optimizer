"""Lead-owned integration tests across independently written modules (A <-> B)."""

import math

import numpy as np
import pytest
from scipy.stats import unitary_group

from ddopt import channels, filters, noise, sequences, simulator
from ddopt.contracts import NoiseModel, SimulationConfig
from ddopt.scenarios import load_scenario, scenario_noise


def test_simulator_ptm_helpers_match_channels_module():
    rng = np.random.default_rng(3)
    for _ in range(5):
        U = unitary_group.rvs(2, random_state=rng)
        assert np.allclose(simulator._unitary_ptm(U[None])[0], channels.unitary_ptm(U), atol=1e-12)
    for g in (0.0, 1e-4, 0.3, 1.0):
        assert np.allclose(simulator._ad_ptm(g), channels.amplitude_damping_ptm(g), atol=1e-14)


def test_simulator_T1_only_matches_channels_formula():
    T, T1 = 2e-6, 20e-6
    nm = NoiseModel(T1=T1)
    res = simulator.simulate(sequences.free(T), nm, SimulationConfig(n_traj=4, seed=0))
    g = channels.gamma_from_T1(T, T1)
    assert abs(res.infidelity - channels.amplitude_damping_infidelity(g)) < 1e-12


@pytest.mark.parametrize("name", ["free", "hahn", "cpmg8"])
def test_mc_vs_filter_function_scenario_a_small(name):
    """Small-budget version of gate G3 (full run: scripts/run_g3_validation.py)."""
    cfg = load_scenario("scenario_a")
    nm = scenario_noise(cfg, T1="inf")
    T, w = 2e-6, 32e-9
    seq = {"free": sequences.free(T), "hahn": sequences.hahn(T, w), "cpmg8": sequences.cpmg(8, T, w)}[name]
    chi, qerr = filters.dephasing_variance(nm, seq)
    r_ff = (1 - math.exp(-chi / 2)) / 3
    res = simulator.simulate(seq, nm, SimulationConfig(n_traj=3000, seed=11, include_T1=False))
    # 4-sigma statistical band (3 configs, fixed seed) + small discretization allowance
    assert abs(res.infidelity - r_ff) <= 4 * res.infidelity_stderr + 0.02 * r_ff


def test_scenario_configs_load_and_are_synthetic():
    for s in ("scenario_a", "scenario_b"):
        cfg = load_scenario(s)
        assert "SYNTHETIC" in cfg["description"]
        scenario_noise(cfg).validate()
