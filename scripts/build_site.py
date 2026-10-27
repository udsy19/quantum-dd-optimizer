#!/usr/bin/env python3
"""Build the static website ("online paper") into ``site/dist/``.

Every number on the site is read from repository artifacts at build time:

* headline numbers: ``report/generated/numbers.tex`` macros, each linked to its provenance row
  (run id, command, code commit) in ``report/claims.json`` (``GEN-<macro>``);
* tables and chart data: recomputed from the runs pinned in ``report/runs.json``, loaded with
  ``ddopt.provenance.load_run`` so that every checksum is verified before anything is read;
* a cross-check recomputes the benchmark/robustness/spectroscopy/G3/model-based macros from
  the payloads and refuses to build if ``numbers.tex`` disagrees (stale macros).

The build is deterministic (no timestamps, sorted JSON) and needs no network. Templates, CSS
and JS live in ``site/src/``; the output directory is git-ignored and built in CI
(``.github/workflows/pages.yml``).

Usage::

    PYTHONPATH=src python scripts/build_site.py [--out site/dist] [--pdf report/main.pdf]
"""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ddopt.provenance import load_run  # noqa: E402

SRC = ROOT / "site" / "src"
REPO_URL = "https://github.com/udsy19/quantum-dd-optimizer"
SITE_URL = "https://udsy19.github.io/quantum-dd-optimizer/"
TITLE = ("Model-Based Dynamical Decoupling under Hardware Timing Constraints "
         "for Idle Superconducting Qubits")
DESCRIPTION = ("Pre-registered synthetic-simulation study: model-based CMA-ES optimization of "
               "dynamical-decoupling timings and phases did not beat XY4/XY8 on held-out noise. "
               "No hardware data.")

# KaTeX is loaded from jsDelivr with Subresource Integrity. The hashes were computed from the
# files of the npm package katex@0.16.22 (jsDelivr /npm/ serves the npm tarball unchanged).
KATEX_VERSION = "0.16.22"
KATEX_BASE = f"https://cdn.jsdelivr.net/npm/katex@{KATEX_VERSION}/dist/"
KATEX_CSS_SRI = "sha384-5TcZemv2l/9On385z///+d7MSYlvIEw9FuZTIdZ14vJLqWphw7e7ZPuOiCHJcFCP"
KATEX_JS_SRI = "sha384-cMkvdD8LoxVzGF/RPUKAcvmm49FQ0oxwDF3BGKtDXcEc+T1b2N+teh/OJfpU0jr6"

NUM_WORD = {4: "Four", 8: "Eight", 16: "Sixteen"}
MODE_LABEL = {"timing": "timing-only", "phase": "phase-only", "both": "timing+phase"}
MODE_TAG = {"timing": "Timing", "phase": "Phase", "both": "Both"}

ROLE_INFO = {
    "g3": ("Gate G3: Monte Carlo vs filter function", "predetermined configurations"),
    "bench_a": ("Scenario A benchmark, T = 2 µs", "pre-registered"),
    "bench_b": ("Scenario B benchmark + robustness sweep", "pre-registered"),
    "spectroscopy": ("Synthetic spectroscopy (gate G4)", "pre-registered"),
    "bench_a_T4": ("Scenario A benchmark, T = 4 µs", "pre-registered"),
    "convergence": ("Training vs validation convergence, n = 8", "exploratory"),
    "model_based": ("Model-based pipeline (CMA-ES on fitted models)", "pipeline run"),
    "abl_colored": ("Ablation: colored noise only", "exploratory (post hoc)"),
    "abl_noamp": ("Ablation: no amplitude error", "exploratory (post hoc)"),
    "abl_noT1": ("Ablation: no T1", "exploratory (post hoc)"),
    "tests": ("Recorded pytest run", "test record"),
}


class BuildError(RuntimeError):
    """The site cannot be built from the artifacts as they stand."""


# ---------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------
def esc(s: object) -> str:
    return html.escape(str(s), quote=True)


def dumps(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def mean(xs) -> float:
    xs = list(xs)
    return float(sum(xs) / len(xs))


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def build_commit() -> tuple[str, bool]:
    sha = os.environ.get("GITHUB_SHA") or git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=no")) if not os.environ.get("GITHUB_SHA") else False
    return sha, dirty


def load_mra():
    """Import scripts/make_report_artifacts.py for its pure payload-summary helpers."""
    path = ROOT / "scripts" / "make_report_artifacts.py"
    spec = importlib.util.spec_from_file_location("_make_report_artifacts", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_newcommands(text: str) -> dict[str, str]:
    """Parse ``\\newcommand{\\Name}{value}`` with balanced braces in the value."""
    out: dict[str, str] = {}
    for m in re.finditer(r"\\newcommand\{\\([A-Za-z]+)\}\{", text):
        i, depth = m.end(), 1
        start = i
        while depth:
            if i >= len(text):
                raise BuildError(f"unbalanced braces in macro {m.group(1)}")
            c = text[i]
            depth += (c == "{") - (c == "}")
            i += 1
        out[m.group(1)] = text[start:i - 1]
    return out


_SCI = re.compile(r"^(-?\d+(?:\.\d+)?)\\times10\^\{(-?\d+)\}$")


def tex_value_html(v: str) -> str:
    parts = []
    for p in v.split("/"):
        m = _SCI.match(p)
        parts.append(f"{m.group(1)}×10<sup>{m.group(2).replace('-', '−')}</sup>" if m else esc(p))
    return "/".join(parts)


def tex_value_text(v: str) -> str:
    parts = []
    for p in v.split("/"):
        m = _SCI.match(p)
        parts.append(f"{m.group(1)}e{m.group(2)}" if m else p)
    return "/".join(parts)


def tex_value_float(v: str):
    m = _SCI.match(v)
    if m:
        return float(m.group(1)) * 10 ** int(m.group(2))
    try:
        return float(v)
    except ValueError:
        return None


def seeds_text(seeds: dict) -> str:
    def rng(v):
        if isinstance(v, list) and v and all(isinstance(x, int) for x in v):
            if len(v) > 2 and v == list(range(v[0], v[0] + len(v))):
                return f"{v[0]}–{v[-1]}"
            return ", ".join(map(str, v))
        return str(v)
    if not isinstance(seeds, dict):
        return rng(seeds) if seeds else ""
    return " · ".join(f"{k} {rng(v)}" for k, v in seeds.items())


def bib_to_text(s: str) -> str:
    rep = [("{\\'n}", "ń"), ("{\\'A}", "Á"), ("\\'n", "ń"), ("\\'A", "Á"), ("$\\pi$", "π"),
           ("\\_", "_"), ("--", "–")]
    for a, b in rep:
        s = s.replace(a, b)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def parse_bib(text: str) -> list[dict]:
    entries = []
    for m in re.finditer(r"@(\w+)\{([^,]+),", text):
        i, depth = m.end(), 1
        while depth and i < len(text):
            depth += (text[i] == "{") - (text[i] == "}")
            i += 1
        body = text[m.end():i - 1]
        fields = {}
        for fm in re.finditer(r"(\w+)\s*=\s*\{", body):
            j, d = fm.end(), 1
            while d:
                d += (body[j] == "{") - (body[j] == "}")
                j += 1
            fields[fm.group(1).lower()] = body[fm.end():j - 1]
        entries.append({"type": m.group(1).lower(), "key": m.group(2).strip(), **fields})
    return entries


def parse_md_table_after(text: str, heading: str) -> list[list[str]]:
    """Rows of the first markdown table following ``heading`` (header and rule removed)."""
    idx = text.find(heading)
    if idx < 0:
        return []
    rows, started = [], False
    for line in text[idx:].splitlines()[1:]:
        if line.startswith("|"):
            started = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                continue
            rows.append(cells)
        elif started:
            break
    return rows[1:]


def md_inline(s: str) -> str:
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(\w[^*]*?)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"(https://[^\s;,)]+)", r'<a href="\1">\1</a>', s)
    return s


def parse_cff(text: str) -> dict:
    out: dict = {"authors": []}
    cur = None
    for line in text.splitlines():
        m = re.match(r'^([a-z-]+):\s*"?(.*?)"?\s*$', line)
        if m and not line.startswith(" "):
            if m.group(1) != "authors":
                out[m.group(1)] = m.group(2)
            continue
        m = re.match(r'^\s*-?\s*(family-names|given-names):\s*"?(.*?)"?\s*$', line)
        if m:
            if m.group(1) == "family-names":
                cur = {"family": m.group(2)}
                out["authors"].append(cur)
            elif cur is not None:
                cur["given"] = m.group(2)
    return out


# ---------------------------------------------------------------------------------------------
# data extraction from checksum-verified runs
# ---------------------------------------------------------------------------------------------
class Data:
    def __init__(self, mra):
        self.mra = mra
        self.runs_map = {k: v for k, v in json.loads((ROOT / "report" / "runs.json").read_text()).items()
                         if not k.startswith("_")}
        self.runs = {k: load_run(ROOT / "results" / v) for k, v in self.runs_map.items()}
        self.expected: dict[str, str] = {}  # macro name -> recomputed value (cross-check)
        self.cfg_a = mra.load_scenario("scenario_a")
        self.cfg_b = mra.load_scenario("scenario_b")

    def rid(self, role: str) -> str:
        return self.runs[role]["run_id"]

    def expect(self, name: str, value: str) -> None:
        self.expected[name] = value

    # ---- benchmark -------------------------------------------------------------------------
    def bench(self) -> dict:
        mra = self.mra
        panels = []
        for role, pid, title, cfg in (("bench_a", "A", "Scenario A", self.cfg_a),
                                      ("bench_b", "B", "Scenario B (virtual-Z)", self.cfg_b)):
            summ = mra.bench_summary(self.runs[role])
            floor = mra.floor_infidelity(cfg, 2e-6)
            groups = []
            for n, e in sorted(summ.items()):
                modes = {}
                for m, rs in e["modes"].items():
                    modes[m] = {"mean_eps": mean(x["eps_opt"] for x in rs),
                                "runs": [{"train_seed": x["train_seed"], "eps": x["eps_opt"], "ratio": x["ratio"],
                                          "ratio_ci": x["ratio_ci"]} for x in rs]}
                groups.append({"n": n, "baselines": e["baselines"], "selected": e["selected_all"],
                               "omitted": e["omitted"], "modes": modes})
                tag = NUM_WORD[n]
                for m, rs in e["modes"].items():
                    lo, hi = min(x["ratio"] for x in rs), max(x["ratio"] for x in rs)
                    self.expect(f"Bench{pid}{tag}{MODE_TAG[m]}RatioLo", f"{lo:.3f}")
                    self.expect(f"Bench{pid}{tag}{MODE_TAG[m]}RatioHi", f"{hi:.3f}")
                    if pid == "B":
                        self.expect(f"BenchB{tag}{MODE_TAG[m]}CILo", f"{min(x['ratio_ci'][0] for x in rs):.3f}")
                        self.expect(f"BenchB{tag}{MODE_TAG[m]}CIHi", f"{max(x['ratio_ci'][1] for x in rs):.3f}")
                if pid == "A":
                    self.expect(f"BenchA{tag}Sel", e["selected"].upper())
                    self.expect(f"BenchA{tag}SelEps", mra.fmt(e["baselines"][e["selected"]]))
            if pid == "A":
                self.expect("FloorA", mra.fmt(floor))
            panels.append({"id": pid, "title": title, "run_id": self.rid(role), "floor": floor,
                           "T": 2e-6, "groups": groups,
                           "command": "python " + self.runs[role]["manifest"].get("command_str", "")})
        return {"panels": panels}

    def bench_table(self, bench: dict) -> dict:
        m3 = self.mra.m3
        rows = []
        for p in bench["panels"]:
            for i, g in enumerate(p["groups"]):
                b = g["baselines"]
                cells = [p["title"] if i == 0 else "", str(g["n"])]
                cells += [m3(b[k]) if k in b else "—" for k in ("free", "cpmg", "xy4", "xy8", "udd")]
                cells.append("/".join(x.upper() for x in sorted(g["selected"])))
                for m in ("timing", "phase", "both"):
                    md = g["modes"].get(m)
                    if md:
                        rat = [r["ratio"] for r in md["runs"]]
                        cells.append(f"{m3(md['mean_eps'])} ({min(rat):.3f}–{max(rat):.3f})")
                    else:
                        cells.append("—")
                rows.append({"cells": cells, "group_start": i == 0, "run": p["run_id"]})
        se = [self.mra.max_rel_se(self.runs[r]) for r in ("bench_a", "bench_b")]
        pooled, per = max(x[0] for x in se), max(x[1] for x in se)
        return {
            "id": "bench", "title": "Held-out benchmark, T = 2 µs, w = 32 ns",
            "caption": ("Infidelity 10³ε averaged over test seeds 9001–9005 (1024 trajectories each; MC standard "
                        f"error of each 5-seed mean ≤ {100 * pooled:.1f}% of ε, per seed ≤ {100 * per:.1f}%). "
                        "“Sel.” = baseline selected by the pre-registered training-only rule. CMA-ES: mean ε over "
                        "3 independent training runs and, in parentheses, the range of ε<sub>sel</sub>/ε<sub>CMA</sub> "
                        "over runs (&gt; 1 favours CMA-ES). Scenario B arms all use virtual-Z from the nominal Stark "
                        "profile. UDD-16 is infeasible on the 4 ns grid."),
            "group_header": [("", 2), ("Canonical baselines", 5), ("", 1), ("CMA-ES (ratio range)", 3)],
            "header": ["Scenario", "n", "Free", "CPMG", "XY4", "XY8", "UDD", "Sel.", "timing-only", "phase-only",
                       "timing+phase"],
            "rows": rows, "runs": [self.rid("bench_a"), self.rid("bench_b")]}

    # ---- G3 ----------------------------------------------------------------------------------
    def g3_table(self) -> dict:
        run = self.runs["g3"]
        names = {"FID": "Free (Ramsey)", "Hahn_w32": "Hahn, w = 32 ns", "CPMG8_w32": "CPMG-8, w = 32 ns",
                 "Hahn_inst": "Hahn, instantaneous", "CPMG8_inst": "CPMG-8, instantaneous"}
        rows = []
        for r in run["payload"]["rows"]:
            rows.append({"cells": [names[r["case"]], f"{r['r_ff'] * 1e3:.3f}",
                                   f"{r['r_mc_dt1ns'] * 1e3:.3f} ± {r['se_mc_dt1ns'] * 1e3:.3f}",
                                   f"{r['z_dt1ns']:+.2f}".replace("-", "−"), "yes" if r["pass_primary"] else "no"],
                         "run": run["run_id"]})
        rows_p = run["payload"]["rows"]
        rel = [100 * r["se_mc_dt1ns"] / r["r_mc_dt1ns"] for r in rows_p]
        self.expect("GthreeRelSELo", f"{min(rel):.2f}")
        self.expect("GthreeRelSEHi", f"{max(rel):.2f}")
        self.expect("GthreeMaxZ", f"{max(abs(r['z_dt1ns']) for r in rows_p):.2f}")
        self.expect("GthreeNtraj", f"{run['payload']['n_traj_per_case']}")
        return {"id": "g3", "title": "Gate G3: Monte Carlo versus filter function",
                "caption": (f"Finite-pulse simulator, {run['payload']['n_traj_per_case']} noise trajectories per row, "
                            "dt = 1 ns, versus the filter-function prediction r = (1 − e<sup>−χ/2</sup>)/3; Scenario A "
                            "Gaussian noise without T<sub>1</sub> or control errors, T = 2 µs. Pass criterion: "
                            "|r<sub>MC</sub> − r<sub>FF</sub>| ≤ 1.96 SE + quadrature error."),
                "header": ["Configuration", "10³ r_FF", "10³ r_MC ± SE", "z", "Pass"],
                "rows": rows, "runs": [run["run_id"]]}

    # ---- Scenario B robustness ---------------------------------------------------------------
    def _rob_runs(self):
        return [r for r in self.runs["bench_b"]["payload"]["runs"]
                if "scenario_b_robustness" in r and r["mode"] in ("phase", "both")]

    @staticmethod
    def _series(r, arm, key):
        def val(k):
            return float(k.split("_")[-1].replace("x", "").replace("ns", ""))
        rob = r["scenario_b_robustness"]
        ks = sorted([k for k in rob if k.startswith(key)], key=val)
        ys = [next(v["mean_over_seeds"] for a, v in rob[k]["summary"].items() if a.startswith(arm)) for k in ks]
        names = [next(a for a in rob[k]["summary"] if a.startswith(arm)) for k in ks]
        return [val(k) for k in ks], ys, names[0] if names else ""

    def robustness(self) -> dict:
        rs4 = sorted([r for r in self._rob_runs() if r["n"] == 4], key=lambda r: (r["mode"], r["seeds"]["train"]))
        panels = []
        for key, label in (("amp", "Stark amplitude / nominal"), ("shift", "Readout timing shift (ns)")):
            x, vz, vz_name = self._series(rs4[0], "2", key)
            _, dd, dd_name = self._series(rs4[0], "3", key)
            series = [{"key": "vz", "family": "free", "label": "No DD + virtual-Z", "arm": vz_name, "y": vz},
                      {"key": "dd", "family": "xy4", "label": "XY4 + virtual-Z", "arm": dd_name, "y": dd}]
            for r in rs4:
                _, y, nm = self._series(r, "4", key)
                series.append({"key": f"{r['mode']}-{r['seeds']['train']}", "family": r["mode"],
                               "label": f"CMA-ES {MODE_LABEL[r['mode']]} + VZ (train seed {r['seeds']['train']})",
                               "arm": nm, "train_seed": r["seeds"]["train"], "y": y})
            panels.append({"id": key, "xlabel": label, "x": x, "series": series})
        return {"n": 4, "run_id": self.rid("bench_b"), "panels": panels,
                "command": "python " + self.runs["bench_b"]["manifest"].get("command_str", "")}

    def robustness_table(self) -> dict:
        m3, fmt = self.mra.m3, self.mra.fmt
        runs = self._rob_runs()
        rows = []
        for n in sorted({r["n"] for r in runs}):
            r0 = [r for r in runs if r["n"] == n][0]
            dd = [v for key in ("amp", "shift") for v in self._series(r0, "3", key)[1]]
            vz = [v for key in ("amp", "shift") for v in self._series(r0, "2", key)[1]]
            sel = r0["selected_baseline"].upper()
            for mode in ("phase", "both"):
                cells, wins = [], []
                for r in sorted([r for r in runs if r["n"] == n and r["mode"] == mode], key=lambda r: r["seeds"]["train"]):
                    cm = [v for key in ("amp", "shift") for v in self._series(r, "4", key)[1]]
                    cells.append(m3(max(cm)))
                    wins.append(sum(c < d for c, d in zip(cm, dd)))
                rows.append({"cells": [str(n), MODE_LABEL[mode], m3(max(vz)), f"{m3(max(dd))} ({sel})",
                                       " / ".join(cells), " / ".join(map(str, wins))],
                             "run": self.rid("bench_b"), "group_start": mode == "phase"})
                nn, ml = NUM_WORD[n], {"phase": "Phase", "both": "Both"}[mode]
                self.expect(f"RobB{nn}{ml}WinsMin", str(min(wins)))
                self.expect(f"RobB{nn}{ml}WinsMax", str(max(wins)))
                self.expect(f"RobB{nn}{ml}WorstMax", fmt(max(float(c) for c in cells) / 1e3))
                if mode == "phase":
                    self.expect(f"RobB{nn}DDWorst", fmt(max(dd)))
                    self.expect(f"RobB{nn}VzWorst", fmt(max(vz)))
                    self.expect(f"RobB{nn}VzBest", fmt(min(vz)))
        arms = [r for r in runs if r["n"] == 8][0]["scenario_b_arms"]["summary"]
        for a_, v in arms.items():
            nm_ = {"1": "NoDD", "2": "VzOnly", "3": "DDVz", "4": "CMAVz"}[a_[0]]
            self.expect(f"BArm{nm_}", fmt(v["mean_over_seeds"]))
        return {"id": "robustness", "title": "Scenario B robustness (pre-registered sweep)",
                "caption": ("Worst-case 10³ε over 10 perturbed Stark profiles (amplitude ×{0.8, …, 1.2}, timing "
                            "±{50, 100} ns and nominal); virtual-Z always from the nominal profile. CMA-ES values for "
                            "training runs 101/102/103, and in how many of the 10 perturbations CMA-ES beats the "
                            "selected DD + virtual-Z."),
                "header": ["n", "CMA-ES mode", "VZ only", "DD + VZ", "CMA-ES + VZ (runs)", "wins / 10"],
                "rows": rows, "runs": [self.rid("bench_b")]}

    # ---- spectroscopy --------------------------------------------------------------------------
    def spectroscopy(self) -> dict:
        p = self.runs["spectroscopy"]["payload"]
        fg = p["figure"]
        ps = fg["psd"]
        two_pi = 2 * math.pi
        curves = {}
        for k, c in fg["curves"].items():
            curves[k] = {"T_us": [t * 1e6 for t in c["T"]], "mle": c["mle"], "lo": c["lo"], "hi": c["hi"]}
        held = [{"label": d["label"], "T_us": d["T"] * 1e6, "p_hat": d["p_hat"]} for d in fg["heldout"]]
        return {"run_id": self.rid("spectroscopy"), "fit": fg["fit"],
                "psd": {"f_hz": [w / two_pi for w in ps["omega"]], "mle": ps["mle"], "lo": ps["lo"],
                        "hi": ps["hi"], "truth": ps["truth"]},
                "curves": curves,
                "heldout": [d for d in held if d["label"] in curves],
                "heldout_other": sorted({d["label"] for d in held if d["label"] not in curves}),
                "n_heldout_total": len(held),
                "command": "python " + self.runs["spectroscopy"]["manifest"].get("command_str", "")}

    def spectroscopy_table(self) -> dict:
        run = self.runs["spectroscopy"]
        p = run["payload"]
        rep = p["pipeline"]["repeats"][0]
        nice = {"reduced_alpha1": "reduced", "full_alpha1": "full (α = 1)", "full_alpha_free": "full (α free)"}
        rows = []
        for tn, t in rep["truths"].items():
            for k, fr in t["fits"].items():
                h = fr["derived"]["heldout"]
                floor_ = h.get("shot_noise_rmse")
                t2 = fr["t2_vs_truth"]

                def t2c(key):
                    v = t2[key]
                    return (f"{v['fit_s'] * 1e6:.2f} [{v['ci95_s'][0] * 1e6:.2f}, {v['ci95_s'][1] * 1e6:.2f}]"
                            + ("" if v["truth_in_ci"] else " *"))
                rows.append({"cells": [tn, nice[k], f"{h['rmse'] / floor_:.2f}", f"{h['coverage95']:.3f}",
                                       t2c("T2star"), t2c("T2_hahn"), "yes" if fr["success"] else "no"],
                             "run": run["run_id"]})
                tag = {"gaussian": "Gauss", "telegraph": "Tel"}[tn] + \
                    {"reduced_alpha1": "Red", "full_alpha1": "Full", "full_alpha_free": "FullAf"}[k]
                self.expect(f"Spec{tag}RmseRatio", f"{h['rmse'] / floor_:.2f}")
                self.expect(f"Spec{tag}Cov", f"{h['coverage95']:.3f}")
        tt = rep["truths"]["gaussian"]["truth_T2"]
        self.expect("SpecTruthTtwoStar", f"{tt['T2star'] * 1e6:.2f}")
        self.expect("SpecTruthTtwoHahn", f"{tt['T2_hahn'] * 1e6:.2f}")
        return {"id": "spectroscopy", "title": "Synthetic spectroscopy (gate G4)",
                "caption": (f"Held-out RMSE of P(+) relative to the shot-noise floor, 95% predictive coverage on "
                            f"{p['pipeline']['design']['n_heldout']} held-out points, and 1/e times (fit [95% bootstrap "
                            "CI], µs; * = CI excludes truth). Truth: T<sub>2</sub>* = "
                            f"{tt['T2star'] * 1e6:.2f} µs, T<sub>2</sub><sup>Hahn</sup> = {tt['T2_hahn'] * 1e6:.2f} µs. "
                            "“telegraph” = Lorentzian replaced by telegraph noise (misspecification control). Seeds "
                            f"5001/5002/5003, n<sub>boot</sub> = {p['pipeline']['fit_settings']['n_boot']}."),
                "header": ["Truth", "Fit model", "RMSE / floor", "Coverage", "T2* (µs)", "T2 Hahn (µs)", "Success"],
                "rows": rows, "runs": [run["run_id"]]}

    # ---- ablations -----------------------------------------------------------------------------
    def ablation_table(self) -> dict:
        mra = self.mra
        variants = [("bench_a", "A (pre-registered), T = 2 µs", "scenario_a", 2e-6, "BenchA"),
                    ("bench_a_T4", "A, T = 4 µs (pre-registered)", "scenario_a", 4e-6, "BenchATfour"),
                    ("abl_noamp", "A without amplitude error †", "scenario_a_noamp", 2e-6, "AblNoAmp"),
                    ("abl_noT1", "A without T1 †", "scenario_a_noT1", 2e-6, "AblNoTone"),
                    ("abl_colored", "A, colored noise only †", "scenario_a_colored", 2e-6, "AblColored")]
        rows = []
        for role, name, scen, T, tagp in variants:
            smm = mra.bench_summary(self.runs[role])
            fl = mra.floor_infidelity(mra.load_scenario(scen), T)
            for i, (n, e) in enumerate(sorted(smm.items())):
                cells = [name if i == 0 else "", str(n), mra.sel_label(e), mra.sel_eps(e), mra.m3(fl)]
                for m in ("timing", "phase", "both"):
                    rs = e["modes"].get(m, [])
                    cells.append(f"{min(x['ratio'] for x in rs):.3f}–{max(x['ratio'] for x in rs):.3f}" if rs else "—")
                    if rs and tagp != "BenchA":
                        self.expect(f"{tagp}{NUM_WORD[n]}{MODE_TAG[m]}RatioLo", f"{min(x['ratio'] for x in rs):.3f}")
                        self.expect(f"{tagp}{NUM_WORD[n]}{MODE_TAG[m]}RatioHi", f"{max(x['ratio'] for x in rs):.3f}")
                if tagp != "BenchA":
                    self.expect(f"{tagp}{NUM_WORD[n]}Sel", mra.sel_label(e))
                    self.expect(f"{tagp}{NUM_WORD[n]}SelEps", mra.sel_eps(e, mra.fmt))
                rows.append({"cells": cells, "group_start": i == 0, "run": self.rid(role)})
        return {"id": "ablation", "title": "Held-out comparison across scenario variants",
                "caption": ("Test seeds 9001–9005. Ratio = ε<sub>selected</sub>/ε<sub>CMA</sub> (range over 3 training "
                            "runs; &gt; 1 favours CMA-ES). Floor = analytic T<sub>1</sub> amplitude damping composed "
                            "with white dephasing over T (pulse-independent). † Post-hoc exploratory ablations added "
                            "after seeing the pre-registered results."),
                "header": ["Variant", "n", "Sel.", "10³ ε_sel", "10³ × floor", "timing-only", "phase-only",
                           "timing+phase"],
                "rows": rows, "runs": [self.rid(v[0]) for v in variants]}

    # ---- model-based -----------------------------------------------------------------------------
    def model_based_table(self) -> dict:
        run = self.runs["model_based"]
        p = run["payload"]
        m3 = self.mra.m3
        names = {"truth": "truth", "fitted_full_alpha1": "fitted full", "fitted_reduced_alpha1": "fitted reduced"}
        by: dict = {}
        for r in p["rows"]:
            by.setdefault((r["source"], r["n"]), []).append(r)
        rows = []
        for (src, n), rs in sorted(by.items(), key=lambda kv: (kv[0][1], list(names).index(kv[0][0]))):
            rat = [x["pooled"]["ratio"] for x in rs]
            lo = min(x["pooled"]["ratio_ci"][0] for x in rs)
            hi = max(x["pooled"]["ratio_ci"][1] for x in rs)
            sel = {x["selected_baseline"] for x in rs}
            rows.append({"cells": [names[src], str(n), "/".join(sorted(s.upper() for s in sel)),
                                   m3(mean(x["pooled"]["eps_a"] for x in rs)), m3(mean(x["pooled"]["eps_b"] for x in rs)),
                                   f"{min(rat):.3f}–{max(rat):.3f}", f"[{lo:.3f}, {hi:.3f}]"],
                         "run": run["run_id"], "group_start": src == "truth"})
            tag = {"truth": "Truth", "fitted_full_alpha1": "FitFull", "fitted_reduced_alpha1": "FitRed"}[src]
            self.expect(f"MB{tag}{NUM_WORD[n]}RatioLo", f"{min(rat):.3f}")
            self.expect(f"MB{tag}{NUM_WORD[n]}RatioHi", f"{max(rat):.3f}")
        return {"id": "model_based", "title": "Model-based pipeline",
                "caption": ("Baseline selection and CMA-ES (timing+phase) trained on the noise model in column 1; all "
                            "arms evaluated on the <em>true</em> Scenario A model (test seeds 9001–9005). Fitted models "
                            f"come from run <code>{esc(p['spectroscopy_run'])}</code>. CI = envelope of pooled "
                            "paired-bootstrap 95% intervals over the 3 training runs."),
                "header": ["Training model", "n", "Sel.", "10³ ε_sel", "10³ ε_CMA", "Ratio", "CI envelope"],
                "rows": rows, "runs": [run["run_id"], p["spectroscopy_run"]]}

    # ---- convergence ---------------------------------------------------------------------------
    def convergence(self) -> dict:
        fmt = self.mra.fmt
        p = self.runs["convergence"]["payload"]
        series = []
        for mode, base, fam, label in (("both", "cpmg", "both", "CMA-ES timing+phase (from CPMG)"),
                                       ("timing", "xy", "timing", "CMA-ES timing-only (XY phases)")):
            rs = sorted([r for r in p["rows"] if r["mode"] == mode and r["base_phases"] == base], key=lambda r: r["budget"])
            series.append({"key": f"{mode}-train", "family": fam, "split": "train", "label": f"{label}: training",
                           "points": [{"x": r["n_evaluations"], "y": r["train"], "budget": r["budget"]} for r in rs]})
            series.append({"key": f"{mode}-val", "family": fam, "split": "validation", "label": f"{label}: validation",
                           "points": [{"x": r["n_evaluations"], "y": mean(r["val_per_seed"]), "budget": r["budget"],
                                       "per_seed": r["val_per_seed"]} for r in rs]})
        best = min(("xy4", "xy8"), key=lambda k: mean(p["baselines"][k]["val_per_seed"]))
        bl = p["baselines"][best]
        last = [r for r in p["rows"] if r["mode"] == "both" and r["budget"] == max(x["budget"] for x in p["rows"])][0]
        self.expect("ConvTrainFinal", fmt(last["train"]))
        self.expect("ConvValFinal", fmt(mean(last["val_per_seed"])))
        self.expect("ConvBestBaselineVal", fmt(mean(bl["val_per_seed"])))
        return {"run_id": self.rid("convergence"), "status": p.get("status", ""), "n": p["n"],
                "validation_seeds": p.get("validation_seeds"), "series": series,
                "baseline": {"family": best, "label": best.upper(), "train": bl["train"],
                             "validation": mean(bl["val_per_seed"])},
                "command": "python " + self.runs["convergence"]["manifest"].get("command_str", "")}

    # ---- run registry ------------------------------------------------------------------------
    def run_rows(self) -> list[dict]:
        out = []
        for role, r in self.runs.items():
            m = r["manifest"]
            g = m.get("git", {})
            desc, status = ROLE_INFO.get(role, (role, ""))
            out.append({"role": role, "description": desc, "status": status, "run_id": r["run_id"],
                        "command": "python " + m.get("command_str", ""), "git_sha": g.get("sha") or "",
                        "dirty": bool(g.get("dirty")), "created_utc": m.get("created_utc", ""),
                        "seeds": m.get("seeds", {}), "seeds_text": seeds_text(m.get("seeds", {}) or {}),
                        "payload_sha256": m.get("artifacts", {}).get("payload.json", ""),
                        "python": m.get("python", {}).get("version", ""), "packages": m.get("packages", {})})
        return out

    def tests_counts(self) -> dict:
        t = self.runs["tests"]["payload"]
        return {**t["counts"], "run_id": self.rid("tests"), "skipped_detail": t.get("skipped", [])}


# ---------------------------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------------------------
def gh_tree(sha: str, path: str) -> str:
    return f"{REPO_URL}/tree/{sha or 'main'}/{path}"


def gh_blob(sha: str, path: str) -> str:
    return f"{REPO_URL}/blob/{sha or 'main'}/{path}"


def render_table(t: dict, ref_sha: str) -> str:
    out = [f'<figure class="table-figure" id="tab-{esc(t["id"])}">',
           f'<figcaption><span class="fig-label">Table · {esc(t["title"])}</span> {t["caption"]} '
           + "Run" + ("s" if len(t["runs"]) > 1 else "") + ": "
           + ", ".join(f'<a class="run-link" href="{esc(gh_tree(ref_sha, "results/" + r))}"><code>{esc(r)}</code></a>'
                       for r in t["runs"]) + ".</figcaption>",
           f'<div class="table-wrap" role="region" aria-label="{esc(t["title"])}" tabindex="0"><table>', "<thead>"]
    if t.get("group_header"):
        out.append("<tr class=\"group-head\">" + "".join(
            f'<th scope="colgroup" colspan="{span}">{esc(lbl)}</th>' if lbl else f'<td colspan="{span}"></td>'
            for lbl, span in t["group_header"]) + "</tr>")
    def head_html(h: str) -> str:
        return re.sub(r"(\w)_(\w+)", r"\1<sub>\2</sub>", esc(h))
    out.append("<tr>" + "".join(f'<th scope="col">{head_html(h)}</th>' for h in t["header"]) + "</tr></thead><tbody>")
    for row in t["rows"]:
        cls = ' class="group-start"' if row.get("group_start") else ""
        cells = []
        for j, c in enumerate(row["cells"]):
            if j == 0:
                cells.append(f'<th scope="row">{esc(c)}</th>')
            else:
                numeric = bool(re.search(r"\d\.\d", c) or re.fullmatch(r"[\d\s/]+", c))
                klass = ' class="num-cell"' if numeric else ""
                m = re.fullmatch(r"([\d.]+) \(([\d.–]+)\)", c)
                inner = (f'{esc(m.group(1))}<span class="cell-sub">({esc(m.group(2))})</span>' if m else esc(c))
                cells.append(f'<td{klass} data-provenance="{esc(row["run"])}">{inner}</td>')
        out.append(f"<tr{cls}>" + "".join(cells) + "</tr>")
    out.append("</tbody></table></div></figure>")
    return "\n".join(out)


def render_runs_table(rows: list[dict]) -> str:
    out = ['<div class="table-wrap" role="region" aria-label="Pinned runs" tabindex="0"><table class="runs">',
           '<thead><tr><th scope="col">Run</th><th scope="col">Command, code commit and seeds</th></tr></thead><tbody>']
    for r in rows:
        sha = r["git_sha"]
        commit = (f'<a href="{REPO_URL}/commit/{esc(sha)}"><code>{esc(sha[:12])}</code></a>' if sha else "—") + \
            (' <span class="pill pill-warn" title="Working tree had uncommitted changes when this run was recorded">dirty</span>'
             if r["dirty"] else "")
        status_cls = "pill-ok" if r["status"] == "pre-registered" else ("pill-warn" if "exploratory" in r["status"] else "")
        out.append(f'<tr><th scope="row"><span class="run-role">{esc(r["description"])}</span>'
                   f'<a class="run-link" href="{esc(gh_tree(sha, "results/" + r["run_id"]))}"><code>{esc(r["run_id"])}</code></a>'
                   f'<span class="run-status"><span class="pill {status_cls}">{esc(r["status"])}</span></span></th>'
                   f'<td><dl><dt>Command</dt><dd><code>{esc(r["command"])}</code></dd>'
                   f'<dt>Commit</dt><dd>{commit}</dd>'
                   f'<dt>Seeds</dt><dd>{esc(r["seeds_text"]) or "—"}</dd>'
                   f'<dt>Recorded</dt><dd>{esc(r["created_utc"][:19].replace("T", " "))} UTC</dd></dl></td></tr>')
    out.append("</tbody></table></div>")
    return "\n".join(out)


def num_span(name: str, macros: dict, prov: dict, ref_sha: str) -> str:
    if name not in macros:
        raise BuildError(f"template references unknown macro \\{name}")
    p = prov.get(name)
    if not p:
        raise BuildError(f"macro \\{name} has no GEN-{name} provenance row in report/claims.json")
    v = macros[name]
    return (f'<span class="num" tabindex="0" data-macro="{esc(name)}" data-provenance="{esc(p["run_id"])}" '
            f'data-cmd="{esc(p["command"])}" data-commit="{esc(p["commit_sha"])}" data-claim="{esc(p["claim"])}" '
            f'data-href="{esc(gh_tree(ref_sha, "results/" + p["run_id"]))}">{tex_value_html(v)}</span>')


def prov_footer(name: str, prov: dict, ref_sha: str) -> str:
    p = prov[name]
    return (f'<footer class="card-prov"><a href="{esc(gh_tree(ref_sha, "results/" + p["run_id"]))}" '
            f'title="Run directory (payload, manifest, checksums)"><code>{esc(p["run_id"])}</code></a>'
            f'<code class="cmd">{esc(p["command"])}</code></footer>')


def render_references(entries: list[dict], order: list[str], audit_rows: dict) -> str:
    out = ['<ol class="refs">']
    by = {e["key"]: e for e in entries}
    keys = order + [k for k in by if k not in order]
    for k in keys:
        e = by[k]
        authors = [a.strip() for a in bib_to_text(e.get("author", "")).split(" and ")]
        if authors and authors[-1] == "others":
            authors = authors[:-1]
            auth = ", ".join(authors) + " et al."
        else:
            auth = ", ".join(authors)
        venue = " ".join(x for x in (bib_to_text(e.get("journal", "")), e.get("volume", ""),
                                     e.get("pages", "")) if x)
        year = e.get("year", "")
        link = e.get("url", "")
        eprint = e.get("eprint", "")
        if k in audit_rows:
            status = ('<span class="pill pill-ok">identity-verified (arXiv)</span>'
                      f'<span class="ref-scope">Checked: {md_inline(audit_rows[k])}. Publisher pagination/DOI not fully audited.</span>')
        elif e["type"] == "misc" and not eprint:
            status = ('<span class="pill pill-warn">non-public</span>'
                      f'<span class="ref-scope">{esc(bib_to_text(e.get("note", "")))}</span>')
        else:
            status = '<span class="pill pill-warn">metadata unverified</span>'
        out.append(f'<li id="ref-{esc(k)}"><span class="ref-auth">{esc(auth)}</span> '
                   f'<span class="ref-title">{esc(bib_to_text(e.get("title", "")))}</span>'
                   + (f' <span class="ref-venue">{esc(venue)}</span>' if venue else "")
                   + (f' ({esc(year)})' if year else "") + "."
                   + (f' <a href="{esc(link)}">arXiv:{esc(eprint)}</a>' if link else "")
                   + f'<div class="ref-status">{status}</div></li>')
    out.append("</ol>")
    return "\n".join(out)


def render_hardware(rows: list[list[str]]) -> str:
    out = ['<div class="table-wrap" role="region" aria-label="Hardware gates" tabindex="0"><table class="hw">',
           '<thead><tr><th scope="col">Gate</th><th scope="col">Status (docs/HARDWARE_PROTOCOL.md)</th></tr></thead><tbody>']
    for gate, status in rows:
        out.append(f'<tr><th scope="row">{esc(gate)}</th><td>{md_inline(status)}</td></tr>')
    out.append("</tbody></table></div>")
    return "\n".join(out)


def make_bibtex(cff: dict, build_sha: str) -> str:
    authors = " and ".join(f'{a["family"]}, {a.get("given", "")}'.strip(", ") for a in cff.get("authors", []))
    year = (cff.get("date-released") or "")[:4]
    lines = ["@software{quantum_dd_optimizer_" + (year or "nd") + ",",
             f"  title   = {{{cff.get('title', '')}}},",
             f"  author  = {{{authors}}},",
             f"  version = {{{cff.get('version', '')}}},",
             f"  year    = {{{year}}},",
             f"  url     = {{{cff.get('url', '')}}},",
             "  note    = {Synthetic simulations only; no hardware data. Metadata from CITATION.cff.}",
             "}"]
    return "\n".join(lines)


def og_image(path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(12, 6.3), dpi=100)
    fig.patch.set_facecolor("#0a0a0b")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1200)
    ax.set_ylim(0, 630)
    ax.axis("off")
    for x in range(0, 1201, 40):
        ax.plot([x, x], [0, 630], color="#ffffff", alpha=0.035, lw=1)
    for y in range(0, 631, 40):
        ax.plot([0, 1200], [y, y], color="#ffffff", alpha=0.035, lw=1)
    ax.text(72, 520, "ONLINE PAPER  ·  SYNTHETIC SIMULATION STUDY", color="#a5a3ff", fontsize=15,
            family="DejaVu Sans", weight="bold")
    ax.text(72, 470, "Model-Based Dynamical Decoupling under\nHardware Timing Constraints for Idle\n"
            "Superconducting Qubits", color="#ededec", fontsize=40, family="DejaVu Sans", weight="bold",
            va="top", linespacing=1.18)
    x = 72
    for label, fg, bg in (("Synthetic simulation", "#ededec", "#1d1d21"), ("Pre-registered", "#ededec", "#1d1d21"),
                          ("No hardware data", "#ffd38a", "#2b2110"), ("Results negative", "#ffb4a8", "#2d1512")):
        w = 15 + 10.6 * len(label)
        ax.add_patch(matplotlib.patches.FancyBboxPatch((x, 92), w, 40, boxstyle="round,pad=0,rounding_size=20",
                                                       fc=bg, ec="#3a3a40", lw=1))
        ax.text(x + w / 2, 112, label, color=fg, fontsize=15, ha="center", va="center", family="DejaVu Sans")
        x += w + 14
    ax.text(72, 48, "udsy19.github.io/quantum-dd-optimizer", color="#8f8e89", fontsize=14, family="DejaVu Sans")
    fig.savefig(path, facecolor=fig.get_facecolor(), metadata={"Software": None})
    plt.close(fig)


# ---------------------------------------------------------------------------------------------
# main build
# ---------------------------------------------------------------------------------------------
def build(out: Path, pdf: Path | None, site_url: str = SITE_URL) -> dict:
    mra = load_mra()
    data = Data(mra)
    macros = parse_newcommands((ROOT / "report" / "generated" / "numbers.tex").read_text())
    claims = json.loads((ROOT / "report" / "claims.json").read_text())["claims"]
    prov = {}
    for c in claims:
        if c["claim_id"].startswith("GEN-"):
            prov[c["claim_id"][4:]] = {"run_id": c["run_id"], "command": c["command"],
                                       "commit_sha": c["commit_sha"], "claim": c["exact_claim"],
                                       "artifact": c["artifact_path"]}
    build_sha, dirty = build_commit()
    ref_sha = build_sha if build_sha and not dirty else "main"

    bench = data.bench()
    tables = {t["id"]: t for t in (data.bench_table(bench), data.g3_table(), data.spectroscopy_table(),
                                   data.robustness_table(), data.ablation_table(), data.model_based_table())}
    charts = {"benchmark": bench, "convergence": data.convergence(), "robustness": data.robustness(),
              "spectroscopy": data.spectroscopy()}
    tests = data.tests_counts()
    data.expect("TestsPassed", str(tests["passed"]))

    # stale-macro guard: every macro we can recompute must match numbers.tex exactly
    bad = [f"\\{k}: numbers.tex={macros.get(k)!r} recomputed={v!r}" for k, v in sorted(data.expected.items())
           if macros.get(k) != v]
    if bad:
        raise BuildError("numbers.tex disagrees with the pinned payloads (re-run make_report_artifacts.py):\n  "
                         + "\n  ".join(bad))
    run_rows = data.run_rows()

    # literature
    bib = parse_bib((ROOT / "report" / "refs.bib").read_text())
    audit = parse_md_table_after((ROOT / "docs" / "CITATION_AUDIT.md").read_text(), "## Follow-up completion")
    audit_rows = {r[0]: r[2] for r in audit if len(r) >= 3}
    cff_path = ROOT / "CITATION.cff"
    cff = parse_cff(cff_path.read_text()) if cff_path.is_file() else {}
    hw_rows = parse_md_table_after((ROOT / "docs" / "HARDWARE_PROTOCOL.md").read_text(), "## 0. Gate list")
    hw = [[r[0], r[1]] for r in hw_rows if len(r) >= 2]
    if not hw:
        raise BuildError("could not read the gate status table from docs/HARDWARE_PROTOCOL.md")

    # ---- output tree -----------------------------------------------------------------------------
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    shutil.copytree(SRC / "assets", out / "assets")
    (out / "figures").mkdir()
    for f in sorted((ROOT / "figures").glob("*.png")):
        shutil.copy2(f, out / "figures" / f.name)
    has_pdf = bool(pdf and pdf.is_file())
    if has_pdf:
        shutil.copy2(pdf, out / "paper.pdf")
    og_image(out / "assets" / "og.png")

    numbers_json = {k: {"tex": v, "text": tex_value_text(v), "value": tex_value_float(v), **prov.get(k, {})}
                    for k, v in sorted(macros.items())}
    files = {"numbers.json": numbers_json, "tables.json": tables, "runs.json": run_rows,
             "benchmark.json": charts["benchmark"], "convergence.json": charts["convergence"],
             "robustness.json": charts["robustness"], "spectroscopy.json": charts["spectroscopy"],
             "tests.json": tests}
    for name, obj in files.items():
        (out / "data" / name).write_text(dumps(obj) + "\n", encoding="utf-8")
    build_info = {"build_commit": build_sha, "dirty": dirty, "katex": KATEX_VERSION, "site_url": site_url,
                  "pinned_runs": data.runs_map, "pdf_included": has_pdf,
                  "data_sha256": {n: hashlib.sha256((out / "data" / n).read_bytes()).hexdigest() for n in sorted(files)}}
    (out / "data" / "build.json").write_text(dumps(build_info) + "\n", encoding="utf-8")

    # ---- templates -----------------------------------------------------------------------------------
    cite_order: list[str] = []

    def cite(keys: str) -> str:
        links = []
        for k in keys.split(","):
            k = k.strip()
            if k not in {e["key"] for e in bib}:
                raise BuildError(f"unknown citation key {k}")
            if k not in cite_order:
                cite_order.append(k)
            links.append(f'<a class="cite" href="#ref-{esc(k)}">{cite_order.index(k) + 1}</a>')
        return '<span class="cites">[' + ", ".join(links) + "]</span>"

    short = build_sha[:7] if build_sha else "unknown"
    base_path = urlparse(site_url).path or "/"
    ctx = {
        "title": esc(TITLE), "description": esc(DESCRIPTION), "site_url": esc(site_url), "base_path": esc(base_path),
        "repo_url": REPO_URL, "katex_css": KATEX_BASE + "katex.min.css", "katex_css_sri": KATEX_CSS_SRI,
        "katex_js": KATEX_BASE + "katex.min.js", "katex_js_sri": KATEX_JS_SRI, "katex_version": KATEX_VERSION,
        "build_sha": esc(short + ("+dirty" if dirty else "")),
        "build_sha_link": f"{REPO_URL}/commit/{build_sha}" if build_sha else REPO_URL,
        "ref_sha": ref_sha,
        "runs_table": render_runs_table(run_rows),
        "hardware_table": render_hardware(hw),
        "bibtex": esc(make_bibtex(cff, build_sha)),
        "cff_link": gh_blob(ref_sha, "CITATION.cff"),
        "tests_passed": str(tests["passed"]), "tests_failed": str(tests["failures"]),
        "tests_errors": str(tests["errors"]), "tests_skipped": str(tests["skipped"]),
        "tests_run": esc(tests["run_id"]), "tests_run_link": gh_tree(ref_sha, "results/" + tests["run_id"]),
        "chart_data": dumps(charts).replace("</", "<\\/"),
        "spec_heldout_other": esc(", ".join(re.sub(r"^cpmg(\d+)$", r"CPMG-\1", x) for x in
                                            charts["spectroscopy"]["heldout_other"]) or "no other"),
    }

    def render(tpl: str) -> str:
        if has_pdf:
            tpl = re.sub(r"@@if_pdf@@(.*?)@@endif_pdf@@", r"\1", tpl, flags=re.S)
        else:
            tpl = re.sub(r"@@if_pdf@@.*?@@endif_pdf@@", "", tpl, flags=re.S)

        def sub(m):
            kind, arg = m.group(1), m.group(2)
            if kind == "num":
                return num_span(arg, macros, prov, ref_sha)
            if kind == "prov":
                return prov_footer(arg, prov, ref_sha)
            if kind == "cite":
                return cite(arg)
            if kind == "table":
                return render_table(tables[arg], ref_sha)
            if kind == "gh":
                return esc(gh_tree(ref_sha, arg) if arg.endswith("/") or "." not in arg.rsplit("/", 1)[-1]
                           else gh_blob(ref_sha, arg))
            if kind == "run":
                rid = data.rid(arg)
                return f'<a class="run-link" href="{esc(gh_tree(ref_sha, "results/" + rid))}"><code>{esc(rid)}</code></a>'
            if arg is None and kind in ctx:
                return ctx[kind]
            if kind == "references":
                return "@@references@@"
            raise BuildError(f"unknown template marker @@{kind}{':' + arg if arg else ''}@@")
        return re.sub(r"@@(\w+)(?::([^@]+))?@@", sub, tpl)

    index = render((SRC / "index.html").read_text(encoding="utf-8"))
    index = index.replace("@@references@@", render_references(bib, cite_order, audit_rows))
    (out / "index.html").write_text(index, encoding="utf-8")
    (out / "404.html").write_text(render((SRC / "404.html").read_text(encoding="utf-8")), encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {site_url}sitemap.xml\n")
    urls = [site_url] + ([site_url + "paper.pdf"] if has_pdf else [])
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                     '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     + "".join(f"  <url><loc>{esc(u)}</loc></url>\n" for u in urls) + "</urlset>\n")
    (out / ".nojekyll").write_text("")
    return {"out": str(out), "macros": len(macros), "checked_macros": len(data.expected), "pdf": has_pdf,
            "build_commit": build_sha, "dirty": dirty}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "site" / "dist")
    ap.add_argument("--pdf", type=Path, default=ROOT / "report" / "main.pdf",
                    help="compiled paper PDF to publish as paper.pdf (skipped if missing)")
    ap.add_argument("--site-url", default=SITE_URL)
    a = ap.parse_args(argv)
    try:
        info = build(a.out.resolve(), a.pdf, a.site_url if a.site_url.endswith("/") else a.site_url + "/")
    except BuildError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"built {info['out']} ({info['macros']} macros, {info['checked_macros']} cross-checked against payloads; "
          f"pdf={'yes' if info['pdf'] else 'no'}; commit {info['build_commit'][:12]}{'+dirty' if info['dirty'] else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
