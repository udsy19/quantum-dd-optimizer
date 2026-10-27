#!/usr/bin/env python3
"""Exploratory deterministic timing search (ideal pulses, no Monte Carlo).

This is NOT a replacement for the finite-pulse benchmark. It answers whether
the stochastic training objective is limiting an otherwise feasible search.
No results are committed automatically, and all outputs are labeled exploratory.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from ddopt import sequences
from ddopt.research_baselines import ideal_filter_proxy
from ddopt.scenarios import load_scenario,scenario_noise


def run(n:int=8, candidates:int=20, seed:int=14017, T:float=2e-6):
    if n not in (4,8,16) or candidates<1:
        raise ValueError("n must be 4,8,16 and candidates >=1")
    cfg=load_scenario("scenario_a")
    noise=scenario_noise(cfg)
    family=sequences.xy8 if n%8==0 else sequences.xy4
    base=family(n,T,width=0.0)
    base_score=ideal_filter_proxy(base,noise)
    rng=np.random.default_rng(seed)
    best=base
    best_score=base_score
    # Ideal pulses. Full T is allocated to gaps via a Dirichlet candidate schedule.
    # This is a search diagnostic, not a claim of optimality or hardware feasibility.
    for _ in range(candidates):
        gaps=T*rng.dirichlet(np.ones(n+1))
        seq=sequences.from_gaps(T,0.0,gaps,base.phases,label="ideal_filter_candidate")
        value=ideal_filter_proxy(seq,noise)
        if value<best_score:
            best,best_score=seq,value
    return {
        "scope":"exploratory ideal-pulse synthetic filter proxy; NOT hardware",
        "n":n,"T":T,"candidate_count":candidates,"seed":seed,
        "baseline_infidelity":base_score,
        "best_infidelity":best_score,
        "best_centers_s":list(best.centers),
        "improvement_ratio":base_score/best_score if best_score>0 else None,
        "limitation":"Only Gaussian dephasing plus analytical T1. No finite-pulse errors."
    }


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--n",type=int,default=8)
    parser.add_argument("--candidates",type=int,default=20)
    parser.add_argument("--seed",type=int,default=14017)
    parser.add_argument("--output",type=Path,default=None)
    args=parser.parse_args()
    result=run(n=args.n,candidates=args.candidates,seed=args.seed)
    output=json.dumps(result,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(output+"\n")
    print(output)
