"""Gate G3: Monte-Carlo finite-pulse simulator vs analytic (generalized) filter function.

Pre-registered (docs/EXPERIMENT_PLAN.md): FID, Hahn, CPMG-8 at T = 2 us, Scenario A Gaussian
noise, no T1, no control errors, w = 32 ns. Criterion:
  |r_MC - r_FF| <= 1.96*SE_MC + quad_err + disc_budget
where disc_budget = |r_MC(dt) - r_MC(dt/2)| + 1.96*sqrt(SE(dt)^2 + SE(dt/2)^2) (conservative,
from independent draws) is reported separately; the primary check uses the 1 ns run.
A secondary set uses ideal instantaneous pulses (FF exact for Gaussian noise).

Usage: python scripts/run_g3_validation.py [--n-traj 16000] [--out results]
"""
import argparse
import math
import sys
import time

import numpy as np

from ddopt import filters, sequences, simulator
from ddopt.provenance import run_manifest, write_run
from ddopt.scenarios import load_scenario, scenario_noise, sim_config
from ddopt.contracts import ControlErrors


def mc(seq, nm, cfg, n_traj, seed, dt, batch=2000):
    per = []
    for b in range(math.ceil(n_traj / batch)):
        c = sim_config(cfg, seed=seed * 1000 + b, n_traj=min(batch, n_traj - b * batch),
                       control_errors=ControlErrors())
        c = c.__class__(**{**c.__dict__, "include_T1": False, "noise_dt": dt})
        per.extend(simulator.simulate(seq, nm, c).per_traj_infidelity)
    per = np.asarray(per)
    return float(per.mean()), float(per.std(ddof=1) / math.sqrt(per.size))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-traj", type=int, default=16000)
    ap.add_argument("--out", default="results")
    ap.add_argument("--seed", type=int, default=31)
    a = ap.parse_args(argv)
    cfg = load_scenario("scenario_a")
    nm = scenario_noise(cfg, T1="inf")
    T, w = cfg["window"]["T"], cfg["window"]["width"]
    cases = {
        "FID": sequences.free(T),
        "Hahn_w32": sequences.hahn(T, w),
        "CPMG8_w32": sequences.cpmg(8, T, w),
        "Hahn_inst": sequences.hahn(T, 0.0),
        "CPMG8_inst": sequences.cpmg(8, T, 0.0),
    }
    rows = []
    t0 = time.time()
    for i, (name, seq) in enumerate(cases.items()):
        chi, qerr = filters.dephasing_variance(nm, seq, rtol=1e-8)
        r_ff = (1 - math.exp(-chi / 2)) / 3
        dr_quad = math.exp(-chi / 2) / 6 * qerr
        m1, s1 = mc(seq, nm, cfg, a.n_traj, a.seed + i, 1e-9)
        m2, s2 = mc(seq, nm, cfg, a.n_traj, a.seed + 100 + i, 0.5e-9)
        disc = abs(m1 - m2) + 1.96 * math.hypot(s1, s2)
        primary_tol = 1.96 * s1 + dr_quad
        rows.append({
            "case": name, "n_pulses": seq.n, "width_s": (seq.widths[0] if seq.n else 0.0),
            "chi_ff": chi, "chi_quad_err": qerr, "r_ff": r_ff,
            "r_mc_dt1ns": m1, "se_mc_dt1ns": s1, "r_mc_dt0p5ns": m2, "se_mc_dt0p5ns": s2,
            "abs_diff_dt1ns": abs(m1 - r_ff), "z_dt1ns": (m1 - r_ff) / s1,
            "primary_tol": primary_tol, "disc_budget": disc,
            "pass_primary": abs(m1 - r_ff) <= primary_tol,
            "pass_with_disc_budget": abs(m1 - r_ff) <= primary_tol + disc,
        })
        print(f"{name:12s} r_FF={r_ff:.6e} r_MC={m1:.6e}±{s1:.1e} z={(m1-r_ff)/s1:+.2f} "
              f"dt/2: {m2:.6e}±{s2:.1e}  pass={rows[-1]['pass_primary']}", flush=True)
    payload = {"gate": "G3", "rows": rows, "n_traj_per_case": a.n_traj,
               "noise": nm.to_dict(), "T": T, "width": w, "wall_time_s": time.time() - t0,
               "criterion": "|r_MC - r_FF| <= 1.96 SE + quad; disc budget reported separately"}
    man = run_manifest({"scenario": "scenario_a", "n_traj": a.n_traj, "seed": a.seed, "T1": "off",
                        "control_errors": "off"}, seeds=[a.seed], command=sys.argv)
    p = write_run(a.out, "g3_validation", payload, man)
    print("wrote", p)


if __name__ == "__main__":
    main()
