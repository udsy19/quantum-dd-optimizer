"""Pre-registered synthetic spectroscopy study (docs/EXPERIMENT_PLAN.md, gate G4).

1. ddopt.spectroscopy.run_pipeline on Scenario A with the config spectroscopy seeds
   (train 5001, held-out 5002, bootstrap 5003), n_boot=200: Gaussian truth (reduced / full fits)
   and telegraph-replaced truth (misspecification control).
2. Figure data for the Gaussian truth, full model (alpha fixed = 1): the train/held-out data and
   fit are regenerated with exactly the generators run_pipeline uses (asserted equal), then
   predicted decay curves and PSD with parametric-bootstrap 95% bands are stored.
3. MLE parameters of each fit are stored so scripts/run_model_based.py can build fitted noise models.

Usage: python scripts/run_spectroscopy.py [--n-boot 200]
"""
import argparse
import math
import sys
import time

import numpy as np

from ddopt import noise as noise_mod
from ddopt import spectroscopy as sp
from ddopt.provenance import run_manifest, write_run
from ddopt.scenarios import load_scenario, scenario_noise


def nat(spec, x):
    return [math.exp(v) if lg else v for v, lg in zip(x, spec.log)]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-boot", type=int, default=200)
    ap.add_argument("--out", default="results")
    a = ap.parse_args(argv)
    t0 = time.time()
    cfg = load_scenario("scenario_a")
    pipe = sp.run_pipeline(cfg, seeds=None, n_boot=a.n_boot)
    print(f"pipeline done {time.time()-t0:.0f}s", flush=True)

    s = cfg["seeds"]["spectroscopy"]
    nm = scenario_noise(cfg)
    design = sp.default_design(shots=1000)
    cut = {}
    for c in nm.components:
        if c.kind == "one_over_f":
            cut.update(omega_low=c.omega_low, omega_high=c.omega_high)
        if c.kind == "white":
            cut["omega_high_white"] = c.omega_high
    r_tr = np.random.default_rng([s["train"], sp.hash_name("gaussian")])
    r_te = np.random.default_rng([s["heldout"], sp.hash_name("gaussian")])
    ds_tr = sp.simulate_dataset(nm, design["train"], spam=sp.DEFAULT_SPAM, rng=r_tr, method="analytic", label="train")
    d1 = sp.simulate_dataset(nm, design["heldout_new_n"], spam=sp.DEFAULT_SPAM, rng=r_te, method="analytic", label="heldout_new_n")
    d2 = sp.simulate_dataset(nm, design["heldout_new_T"], spam=sp.DEFAULT_SPAM, rng=r_te, method="analytic", label="heldout_new_T")
    fr = sp.fit(ds_tr, "full", n_boot=a.n_boot, fit_alpha=False,
                rng=np.random.default_rng([s["bootstrap"], sp.hash_name("gaussian" + "full_alpha1")]), **cut)
    ref = pipe["repeats"][0]["truths"]["gaussian"]["fits"]["full_alpha1"]
    assert np.allclose(fr.params, ref["params"], rtol=1e-10), "figure fit differs from pipeline fit"
    spec = sp._spec_of(fr)
    X = np.asarray(fr.provenance["bootstrap_x"])

    curves = {}
    Tg = np.geomspace(1e-7, 40e-6, 60)
    for fam, n in (("ramsey", 0), ("hahn", 1), ("cpmg", 4), ("cpmg", 16)):
        exps = [sp.Experiment(fam, n, float(T), 1000) for T in Tg]
        mle = sp.predict(fr, exps)
        boots = np.array([sp.predict(fr, exps, x=x) for x in X])
        truth = [sp.survival_probability(nm, e, spam=sp.DEFAULT_SPAM) for e in exps]
        curves[f"{fam}{n if fam == 'cpmg' else ''}"] = {
            "T": Tg.tolist(), "mle": mle.tolist(), "lo": np.quantile(boots, 0.025, 0).tolist(),
            "hi": np.quantile(boots, 0.975, 0).tolist(), "truth": list(map(float, truth))}

    def data_points(ds):
        return [{"label": e.label, "T": e.T, "p_hat": k / N} for e, k, N in
                zip(sp._as_exps(ds["experiments"]), ds["counts"], ds["shots"])]

    w = np.geomspace(2 * math.pi * 1e3, 2 * math.pi * 100e6, 200)
    def fitted_psd(x):
        q = dict(zip(spec.names, nat(spec, x)))
        comps = [noise_mod.make_one_over_f(q["A_ref"] * spec.omega_ref ** spec.alpha, spec.alpha, spec.omega_low, spec.omega_high),
                 noise_mod.make_white(q["S0"], spec.omega_high_white), noise_mod.make_lorentzian(q["sigma"], q["tau_c"])]
        return sum(noise_mod.psd(c, w) for c in comps)
    psd_boot = np.array([fitted_psd(x) for x in X])
    psd = {"omega": w.tolist(), "truth": noise_mod.psd(nm, w).tolist(),
           "mle": noise_mod.psd(sp.fitted_noise_model(fr), w).tolist(),
           "lo": np.quantile(psd_boot, 0.025, 0).tolist(), "hi": np.quantile(psd_boot, 0.975, 0).tolist()}
    payload = {"pipeline": pipe, "figure": {"fit": "gaussian truth, full model, alpha=1",
                                            "train": data_points(ds_tr), "heldout": data_points(d1) + data_points(d2),
                                            "curves": curves, "psd": psd},
               "status": "SYNTHETIC; pre-registered spectroscopy seeds", "wall_time_s": time.time() - t0}
    man = run_manifest({"scenario": "scenario_a", "n_boot": a.n_boot, "shots": 1000, "spam_truth": list(sp.DEFAULT_SPAM)},
                       seeds=s, command=sys.argv)
    print("wrote", write_run(a.out, "spectroscopy_scenario_a", payload, man))


if __name__ == "__main__":
    main()
