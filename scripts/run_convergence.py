"""Optimization training vs held-out VALIDATION convergence (exploratory diagnostic).

For a fixed (scenario, n, mode, train seed, optimizer seed), CMA-ES is run with budgets
B in {50,100,250,500,1000,2000}. pycma with a fixed seed follows the same trajectory, so the
best-so-far at budget B is the prefix of the 2000-evaluation run. Each best sequence is scored on
the frozen training draws and on VALIDATION seeds 8001-8002 (n_traj 1024), which are disjoint
from training (101-103) and from the pre-registered test seeds (9001-9005).
Also includes an ablation: timing-only optimisation started from XY phases (base_phases = XY4/XY8).

Usage: python scripts/run_convergence.py [--scenario scenario_a] [--n 8]
"""
import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402

from ddopt import sequences, simulator  # noqa: E402
from ddopt.evaluation import canonical_baselines  # noqa: E402
from ddopt.optimizer import optimize  # noqa: E402
from ddopt.provenance import run_manifest, write_run  # noqa: E402
from ddopt.scenarios import load_scenario, scenario_noise, sim_config  # noqa: E402

BUDGETS = [50, 100, 250, 500, 1000, 2000]
VAL_SEEDS = [8001, 8002]


def _score(seq, nm, cfg, draws):
    return [simulator.simulate(seq, nm, sim_config(cfg, seed=0, n_traj=d["delta"].shape[0]),
                               delta_traj=d["delta"], t_grid=d["t"], amp_eps=d["amp_eps"],
                               phase_err=d["phase_err"], return_per_traj=False).infidelity for d in draws]


def _job(args):
    scen, n, mode, base, budget = args
    cfg = load_scenario(scen)
    nm = scenario_noise(cfg)
    w = cfg["window"]
    T = w["T"]
    s = cfg["seeds"]
    c_tr = sim_config(cfg, seed=s["train"][0], n_traj=s["n_traj_train"])
    tr = simulator.frozen_draws(nm, T, c_tr)
    base_phases = None
    if base == "xy":
        fam = "xy8" if n % 8 == 0 else "xy4"
        base_phases = list(getattr(sequences, fam)(n, T, w["width"]).phases)
    res = optimize(n, T, w["width"], nm, c_tr, mode=mode, train_draws=tr, max_evals=budget,
                   seed=s["optimizer"][0], guard=w["guard"], dt_grid=w["dt_grid"],
                   base_phases=base_phases, train_seeds=[s["train"][0]],
                   sigma0=cfg["optimizer"]["sigma0"])
    val = [simulator.frozen_draws(nm, T, sim_config(cfg, seed=v, n_traj=1024)) for v in VAL_SEEDS]
    return {"mode": mode, "base_phases": base, "budget": budget, "n_evaluations": res.n_evaluations,
            "train": res.best_train_infidelity, "val_per_seed": _score(res.best_sequence, nm, cfg, val),
            "best_sequence": res.best_sequence.to_dict()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="scenario_a")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--out", default="results")
    a = ap.parse_args(argv)
    t0 = time.time()
    jobs = [(a.scenario, a.n, m, b, B) for (m, b) in [("both", "cpmg"), ("timing", "xy")] for B in BUDGETS]
    with ProcessPoolExecutor(os.cpu_count()) as ex:
        rows = list(ex.map(_job, jobs))
    cfg = load_scenario(a.scenario)
    nm = scenario_noise(cfg)
    w = cfg["window"]
    val = [simulator.frozen_draws(nm, w["T"], sim_config(cfg, seed=v, n_traj=1024)) for v in VAL_SEEDS]
    tr = [simulator.frozen_draws(nm, w["T"], sim_config(cfg, seed=cfg["seeds"]["train"][0],
                                                          n_traj=cfg["seeds"]["n_traj_train"]))]
    bl = {k: {"train": _score(sq, nm, cfg, tr)[0], "val_per_seed": _score(sq, nm, cfg, val)}
          for k, sq in canonical_baselines(a.n, w["T"], w["width"], guard=w["guard"], dt_grid=w["dt_grid"]).items()}
    for r in rows:
        print(r["mode"], r["base_phases"], r["budget"], f"train={r['train']:.4e} val={np.mean(r['val_per_seed']):.4e}")
    payload = {"scenario": a.scenario, "n": a.n, "rows": rows, "baselines": bl, "validation_seeds": VAL_SEEDS,
               "status": "EXPLORATORY diagnostic (not pre-registered)", "wall_time_s": time.time() - t0}
    cfg_rec = {k: v for k, v in cfg.items() if k != "_path"}
    man = run_manifest({"cfg": cfg_rec, "n": a.n, "budgets": BUDGETS}, seeds={"train": cfg["seeds"]["train"][:1],
                       "optimizer": cfg["seeds"]["optimizer"][:1], "validation": VAL_SEEDS}, command=sys.argv)
    print("wrote", write_run(a.out, f"convergence_{a.scenario}_n{a.n}", payload, man))


if __name__ == "__main__":
    main()
