"""Pre-registered DD benchmark driver (docs/EXPERIMENT_PLAN.md).

Runs ddopt.evaluation.run_benchmark for every (n, mode, training-run) combination using the
seeds in the scenario config, in parallel processes, and writes ONE immutable results/<run_id>/.

Usage:
  python scripts/run_benchmark.py --scenario scenario_a            # full pre-registered grid
  python scripts/run_benchmark.py --scenario scenario_b --robustness
  python scripts/run_benchmark.py --scenario scenario_a --T 4e-6 --name benchmark_a_T4us
"""
import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from ddopt.evaluation import run_benchmark  # noqa: E402
from ddopt.provenance import git_state, run_manifest, write_run  # noqa: E402
from ddopt.scenarios import load_scenario  # noqa: E402


def _job(args):
    cfg, n, mode, tr, op, test, kw = args
    t = time.time()
    r = run_benchmark(cfg, n, mode, tr, op, test, **kw)
    sel = r["selected_baseline"]
    pooled = r["comparison_vs_selected"]["pooled"]
    print(f"n={n:2d} {mode:6s} train={tr} sel={sel:5s} eps_sel={pooled['eps_a']:.4e} "
          f"eps_opt={pooled['eps_b']:.4e} ratio={pooled['ratio']:.3f} {pooled['ratio_ci']} "
          f"({time.time()-t:.0f}s)", flush=True)
    return r


def main(argv=None):
    git_at_start = git_state()
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="scenario_a")
    ap.add_argument("--name", default=None)
    ap.add_argument("--n", type=int, nargs="*", default=None)
    ap.add_argument("--modes", nargs="*", default=None)
    ap.add_argument("--T", type=float, default=None)
    ap.add_argument("--max-evals", type=int, default=None)
    ap.add_argument("--robustness", action="store_true")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--out", default="results")
    a = ap.parse_args(argv)
    cfg = load_scenario(a.scenario)
    s = cfg["seeds"]
    ns = a.n or cfg["window"]["n_values"]
    modes = a.modes or cfg["optimizer"]["modes"]
    max_evals = a.max_evals or cfg["optimizer"]["max_evals"]
    kw = dict(max_evals=max_evals, n_traj_train=s["n_traj_train"], n_traj_test=s["n_traj_test"],
              T=a.T, n_boot=2000, boot_seed=s["spectroscopy"]["bootstrap"], robustness=a.robustness)
    jobs = [(cfg, n, m, tr, op, s["test"], kw) for n in ns for m in modes
            for tr, op in zip(s["train"], s["optimizer"])]
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        runs = list(ex.map(_job, jobs))
    payload = {"scenario": a.scenario, "config_path": cfg["_path"], "runs": runs,
               "grid": {"n": ns, "modes": modes, "train_seeds": s["train"], "optimizer_seeds": s["optimizer"],
                        "test_seeds": s["test"]},
               "wall_time_s": time.time() - t0, "workers": a.workers}
    cfg_rec = {k: v for k, v in cfg.items() if k != "_path"}
    cfg_rec["overrides"] = {"T": a.T, "max_evals": max_evals, "n": ns, "modes": modes, "robustness": a.robustness}
    man = run_manifest(cfg_rec, seeds={"train": s["train"], "optimizer": s["optimizer"], "test": s["test"]},
                       command=sys.argv,
                       extra={"git_at_start": git_at_start})
    name = a.name or f"benchmark_{a.scenario}"
    print("wrote", write_run(a.out, name, payload, man), f"({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
