"""Calibrate the pre-registered Scenario A synthetic noise amplitudes (docs/EXPERIMENT_PLAN.md).

Usage: python scripts/calibrate_scenario_a.py  -> writes configs/scenario_a.json and configs/scenario_b.json
Rules (pre-registered): 1/f amplitude A so that analytic FID W(10 us) = e^-1 from 1/f alone;
Lorentzian sigma so chi_L,FID(2 us) = 0.25 chi_1/f,FID(2 us); white S0 = 2/(200 us).
"""
import json
import math
import sys
from pathlib import Path

from ddopt import filters, noise, sequences

ROOT = Path(__file__).resolve().parents[1]
TWO_PI = 2 * math.pi


def main() -> None:
    T = 2.0e-6
    unit_f = noise.make_one_over_f(1.0, 1.0, TWO_PI * 1.0, TWO_PI * 10e6)
    chi1_10us, _ = filters.dephasing_variance(unit_f, sequences.free(10e-6))
    A = 2.0 / chi1_10us  # W = exp(-chi/2) = e^-1  <=> chi = 2
    f = noise.make_one_over_f(A, 1.0, TWO_PI * 1.0, TWO_PI * 10e6)
    chi_f_T, _ = filters.dephasing_variance(f, sequences.free(T))
    unit_L = noise.make_lorentzian(1.0, 0.5e-6)
    chiL_unit, _ = filters.dephasing_variance(unit_L, sequences.free(T))
    sigma = math.sqrt(0.25 * chi_f_T / chiL_unit)
    S0 = 2.0 / 200e-6
    comps = [
        {"kind": "one_over_f", "params": {"A": A, "alpha": 1.0}, "omega_low": TWO_PI * 1.0, "omega_high": TWO_PI * 10e6},
        {"kind": "lorentzian", "params": {"sigma": sigma, "tau_c": 0.5e-6}, "omega_low": 0.0, "omega_high": "inf"},
        {"kind": "white", "params": {"S0": S0}, "omega_low": 0.0, "omega_high": TWO_PI * 100e6},
    ]
    base = {
        "description": "Scenario A synthetic transmon-like idle qubit. ALL VALUES ARE SYNTHETIC ASSUMPTIONS.",
        "produced_by": "python scripts/calibrate_scenario_a.py",
        "calibration": {"chi_1overf_FID_10us": 2.0, "chi_1overf_FID_2us": chi_f_T,
                        "chi_lorentzian_FID_2us": 0.25 * chi_f_T, "units": "chi dimensionless (rad^2)"},
        "window": {"T": T, "T_alt": 4.0e-6, "width": 32e-9, "guard": 4e-9, "dt_grid": 4e-9, "n_values": [4, 8, 16]},
        "noise": {"components": comps, "T1": 100e-6, "detuning": {"kind": "none"}},
        "simulation": {"noise_dt": 1e-9, "pulse_steps": 8, "include_T1": True,
                       "control_errors": {"amp_rel_std": 0.02, "amp_rel_bias": 0.0, "phase_std": 0.0, "detuning_offset": 0.0}},
        "seeds": {"train": [101, 102, 103], "optimizer": [1, 2, 3], "test": [9001, 9002, 9003, 9004, 9005],
                  "n_traj_train": 256, "n_traj_test": 1024,
                  "spectroscopy": {"train": 5001, "heldout": 5002, "bootstrap": 5003}},
        "optimizer": {"sigma0": 0.3, "max_evals": 2000, "modes": ["timing", "phase", "both"]},
    }
    (ROOT / "configs" / "scenario_a.json").write_text(json.dumps(base, indent=2) + "\n")
    b = json.loads(json.dumps(base))
    b["description"] = ("Scenario B: Scenario A + deterministic ac-Stark-like shift during neighbouring readout. "
                        "ALL VALUES ARE SYNTHETIC ASSUMPTIONS; models a deterministic frequency shift only.")
    b["noise"]["detuning"] = {"kind": "smooth_rect", "amplitude": TWO_PI * 0.2e6, "t_on": 0.6e-6, "t_off": 1.6e-6, "rise": 20e-9}
    b["robustness"] = {"amplitude_scale": [0.8, 0.9, 1.0, 1.1, 1.2], "time_shift": [-100e-9, -50e-9, 0.0, 50e-9, 100e-9]}
    (ROOT / "configs" / "scenario_b.json").write_text(json.dumps(b, indent=2) + "\n")
    print(json.dumps({"A": A, "sigma": sigma, "S0": S0, "chi_1overf_FID_2us": chi_f_T}, indent=1))


if __name__ == "__main__":
    sys.exit(main())
