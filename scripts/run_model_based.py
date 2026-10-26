"""Model-based pipeline (docs/EXPERIMENT_PLAN.md "Model-based pipeline", G4/G6).

Noise models used for TRAINING (baseline selection + CMA-ES): (i) the truth (Scenario A),
(ii) the full-model fit and (iii) the reduced-model fit from the recorded spectroscopy run
(seed-5001 data, MLE parameters; T1 treated as known). All arms are then evaluated on the
TRUE model with held-out test seeds 9001-9005. This measures how much of any gain (or loss)
survives model identification error.

Usage: python scripts/run_model_based.py --spectroscopy-run <results dir name> [--n 4 8] [--mode both]
"""
import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np  # noqa: E402

from ddopt import simulator  # noqa: E402
from ddopt.contracts import FitResult  # noqa: E402
from ddopt.evaluation import canonical_baselines, evaluate, pooled_comparison, select_baseline  # noqa: E402
from ddopt.optimizer import optimize  # noqa: E402
from ddopt.provenance import load_run, run_manifest, write_run  # noqa: E402
from ddopt.scenarios import ROOT, load_scenario, scenario_noise, sim_config  # noqa: E402
from ddopt.spectroscopy import fitted_noise_model  # noqa: E402


def models(spec_run: str):
    run = load_run(ROOT / "results" / spec_run)
    fits = run["payload"]["pipeline"]["repeats"][0]["truths"]["gaussian"]["fits"]
    out = {}
    for key in ("full_alpha1", "reduced_alpha1"):
        f = dict(fits[key])
        fr = FitResult(**{k: f[k] for k in FitResult.__dataclass_fields__ if k in f})
        out[f"fitted_{key}"] = (fitted_noise_model(fr), {"params": dict(zip(f["param_names"], f["params"])),
                                                          "success": f["success"]})
    return run["run_id"], out


def job(args):
    spec_run, src, n, mode, tr, op = args
    cfg = load_scenario("scenario_a")
    truth = scenario_noise(cfg)
    nm = truth if src == "truth" else models(spec_run)[1][src][0]
    w, s = cfg["window"], cfg["seeds"]
    c_tr = sim_config(cfg, seed=tr, n_traj=s["n_traj_train"])
    draws = simulator.frozen_draws(nm, w["T"], c_tr)
    bl = canonical_baselines(n, w["T"], w["width"], guard=w["guard"], dt_grid=w["dt_grid"])
    sel = select_baseline(bl, nm, c_tr, draws)
    res = optimize(n, w["T"], w["width"], nm, c_tr, mode=mode, train_draws=draws, max_evals=cfg["optimizer"]["max_evals"],
                   seed=op, guard=w["guard"], dt_grid=w["dt_grid"], train_seeds=[tr], sigma0=cfg["optimizer"]["sigma0"])
    seqs = {sel: bl[sel], "optimized": res.best_sequence}
    c_te = sim_config(cfg, seed=0, n_traj=s["n_traj_test"])
    ev = evaluate(seqs, truth, c_te, s["test"], s["n_traj_test"], train_seeds=[tr, op])
    a = np.array([np.mean(ev["per_seed"][sel][t]["per_traj"]) for t in s["test"]])
    pc = pooled_comparison([ev["per_seed"][sel][t]["per_traj"] for t in s["test"]],
                           [ev["per_seed"]["optimized"][t]["per_traj"] for t in s["test"]],
                           n_boot=2000, rng=np.random.default_rng(5003))
    out = {"source": src, "n": n, "mode": mode, "train_seed": tr, "opt_seed": op, "selected_baseline": sel,
           "train_opt": res.best_train_infidelity, "n_evals": res.n_evaluations,
           "test_selected": float(a.mean()), "test_optimized": pc["eps_b"], "pooled": pc,
           "best_sequence": res.best_sequence.to_dict()}
    print(f"{src:24s} n={n} {mode} tr={tr} sel={sel} eps_sel={pc['eps_a']:.4e} eps_opt={pc['eps_b']:.4e} "
          f"ratio={pc['ratio']:.3f} {np.round(pc['ratio_ci'], 3).tolist()}", flush=True)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--spectroscopy-run", required=True)
    ap.add_argument("--n", type=int, nargs="*", default=[4, 8])
    ap.add_argument("--mode", default="both")
    ap.add_argument("--out", default="results")
    a = ap.parse_args(argv)
    t0 = time.time()
    spec_id, ms = models(a.spectroscopy_run)
    cfg = load_scenario("scenario_a")
    s = cfg["seeds"]
    jobs = [(a.spectroscopy_run, src, n, a.mode, tr, op) for src in ["truth", *ms] for n in a.n
            for tr, op in zip(s["train"], s["optimizer"])]
    with ProcessPoolExecutor(os.cpu_count()) as ex:
        rows = list(ex.map(job, jobs))
    payload = {"spectroscopy_run": spec_id, "fitted_models": {k: {"noise": v[0].to_dict(), **v[1]} for k, v in ms.items()},
               "rows": rows, "test_seeds": s["test"], "evaluated_on": "TRUE Scenario A model",
               "status": "SYNTHETIC; pre-registered model-based pipeline", "wall_time_s": time.time() - t0}
    cfg_rec = {k: v for k, v in cfg.items() if k != "_path"}
    man = run_manifest({"cfg": cfg_rec, "spectroscopy_run": spec_id, "n": a.n, "mode": a.mode},
                       seeds={"train": s["train"], "optimizer": s["optimizer"], "test": s["test"]}, command=sys.argv)
    print("wrote", write_run(a.out, "model_based_scenario_a", payload, man))


if __name__ == "__main__":
    main()
