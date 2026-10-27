#!/usr/bin/env python3
"""Build the static website ("online paper") into ``site/dist/``.

The paper body is rendered from ``report/`` at build time: ``report/main.tex`` (the paper) and
``report/appendix.tex`` (supplementary appendix) are read with their ``\\input`` files, preprocessed in
memory (generated number macros expanded, IEEE front matter extracted for the page header, tables and
figures simplified, cross-references numbered as in the PDF) and converted to HTML with pandoc
(``--citeproc`` with the bundled IEEE CSL style, ``--katex`` math). Nothing is written below ``report/``.
pandoc is required; without it the build fails rather than shipping a stale page.

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

    PYTHONPATH=src python scripts/build_site.py [--out site/dist] [--pdf-dir report]

``--pdf-dir`` publishes freshly built ``main.pdf`` (as ``paper.pdf``), ``appendix.pdf`` and
``combined_report.pdf`` from that directory; CI passes it only after ``scripts/build_report.sh`` succeeds.
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
# KaTeX and the Geist fonts are self-hosted under site/src/assets (copied from the npm packages
# katex@0.16.22 and geist@1.7.2; licences alongside). No third-party requests at runtime.
KATEX_VERSION = "0.16.22"
KATEX_BASE = "assets/vendor/katex/"
KATEX_CSS_SRI = ""
KATEX_JS_SRI = ""

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
# report/ -> HTML: the paper body is rendered from the LaTeX sources at build time (pandoc)
# ---------------------------------------------------------------------------------------------
# report/ is read-only here: sources are read into memory, preprocessed, and fed to pandoc on
# stdin. Nothing is ever written below report/.
PROV_TOKEN = "ZQPROV{}ZQEND"
PROV_RE = re.compile(r"ZQPROV([A-Za-z]+)ZQEND")
APPENDIX_MARK = "ZQAPPENDIXSTART"
CSL = SRC / "csl" / "ieee.csl"
FIG_TO_CHART = {"fig:spec": "spectroscopy", "fig:bench": "benchmark", "fig:conv": "convergence",
                "fig:rob": "robustness"}


def roman(n: int) -> str:
    out = ""
    for v, s in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                 (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out += s
            n -= v
    return out


def letter(n: int) -> str:
    return chr(ord("A") + n - 1)


def strip_tex_comments(text: str) -> str:
    """TeX semantics: ``%`` drops the rest of the line, the newline and the next line's indentation
    (so a comment-only line does not end a paragraph)."""
    return re.sub(r"(?<!\\)%[^\n]*(?:\n[ \t]*)?", "", text)


def brace_group(text: str, i: int) -> tuple[str, int]:
    """Return (content, index after the group) for the balanced {...} starting at text[i]."""
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text) or text[i] != "{":
        raise BuildError(f"expected '{{' in LaTeX near: {text[max(0, i - 40):i + 40]!r}")
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    raise BuildError("unbalanced braces in LaTeX source")


def env_body(text: str, env: str) -> str | None:
    m = re.search(r"\\begin\{" + re.escape(env) + r"\}(.*?)\\end\{" + re.escape(env) + r"\}", text, re.S)
    return m.group(1) if m else None


def parse_macro_defs(text: str) -> dict[str, tuple[int, str]]:
    """``\\newcommand{\\name}[n]{body}`` -> {name: (n, body)} (balanced braces)."""
    out: dict[str, tuple[int, str]] = {}
    for m in re.finditer(r"\\newcommand\{\\([A-Za-z]+)\}(?:\[(\d)\])?", text):
        body, _ = brace_group(text, m.end())
        out[m.group(1)] = (int(m.group(2) or 0), body)
    return out


def remove_macro_defs(text: str) -> str:
    out, pos = [], 0
    for m in re.finditer(r"\\newcommand\{\\([A-Za-z]+)\}(?:\[(\d)\])?", text):
        if m.start() < pos:
            continue
        _, end = brace_group(text, m.end())
        out.append(text[pos:m.start()])
        pos = end
    out.append(text[pos:])
    return "".join(out)


def expand_macros(text: str, defs: dict[str, tuple[int, str]]) -> str:
    for _ in range(8):
        changed = False
        out, i = [], 0
        for m in re.finditer(r"\\([A-Za-z]+)", text):
            if m.start() < i or m.group(1) not in defs:
                continue
            nargs, body = defs[m.group(1)]
            end = m.end()
            if nargs:
                args = []
                for _k in range(nargs):
                    a, end = brace_group(text, end)
                    args.append(a)
                for k, a in enumerate(args, 1):
                    body = body.replace(f"#{k}", a)
            elif text[end:end + 2] == "{}":
                end += 2
            out.append(text[i:m.start()])
            out.append(body)
            i = end
            changed = True
        out.append(text[i:])
        text = "".join(out)
        if not changed:
            return text
    raise BuildError("LaTeX macro expansion did not terminate")


def strip_command(text: str, cmd: str, skip_args: int, keep_last: bool) -> str:
    """Remove ``\\cmd{a}{b}...``; optionally keep the content of the final argument."""
    out, pos = [], 0
    for m in re.finditer(r"\\" + cmd + r"(?![A-Za-z])", text):
        if m.start() < pos:
            continue
        end = m.end()
        content = ""
        for _ in range(skip_args + (1 if keep_last else 0)):
            content, end = brace_group(text, end)
        out.append(text[pos:m.start()])
        out.append(content if keep_last else "")
        pos = end
    out.append(text[pos:])
    return "".join(out)


def tex_to_text(s: str) -> str:
    """Plain text for short metadata fields (title, authors, keywords)."""
    s = re.sub(r"\\(large|Large|small|footnotesize|normalsize|scriptsize)\b", "", s)
    s = s.replace("~", " ").replace("---", "—").replace("--", "–").replace("\\&", "&")
    s = re.sub(r"\\[A-Za-z]+\*?", "", s).replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def bib_short_authors(entry: dict) -> str:
    authors = [a.strip() for a in bib_to_text(entry.get("author", "")).split(" and ") if a.strip()]
    if not authors:
        return ""
    if authors[-1] == "others" or len(authors) >= 3:
        return f"{authors[0]} et al."
    return " and ".join(authors)


class ReportRenderer:
    """Render report/main.tex and report/appendix.tex to HTML fragments with pandoc."""

    def __init__(self, report_dir: Path, macros: dict[str, str], prov: dict, ref_sha: str, bib: list[dict],
                 audit_rows: dict[str, str]):
        self.dir = report_dir
        self.macros = macros
        self.prov = prov
        self.ref_sha = ref_sha
        self.bib = {e["key"]: e for e in bib}
        self.audit_rows = audit_rows
        self.pandoc_bin = shutil.which("pandoc")
        if not self.pandoc_bin:
            raise BuildError("pandoc is required to render the paper from report/ (e.g. `sudo apt-get install "
                             "pandoc`); refusing to build a site without the paper body")

    # ---- source loading ---------------------------------------------------------------------
    def read(self, rel: str) -> str:
        p = self.dir / (rel if rel.endswith(".tex") else rel + ".tex")
        if not p.is_file():
            raise BuildError(f"\\input{{{rel}}}: {p} not found")
        text = strip_tex_comments(p.read_text(encoding="utf-8"))
        return re.sub(r"\\input\{([^}]+)\}", lambda m: self.read(m.group(1)), text)

    # ---- metadata (hero) -------------------------------------------------------------------------
    def metadata(self, full: str) -> dict:
        title_src, _ = brace_group(full, full.index("\\title") + len("\\title"))
        parts = [p for p in re.split(r"\\\\", title_src) if p.strip()]
        authors = []
        for m in re.finditer(r"\\IEEEauthorblockN", full):
            name, end = brace_group(full, m.end())
            aff = ""
            nxt = full[end:].lstrip()
            if nxt.startswith("\\IEEEauthorblockA"):
                aff, _ = brace_group(full, end + (len(full[end:]) - len(nxt)) + len("\\IEEEauthorblockA"))
            lines = [tex_to_text(x) for x in re.split(r"\\\\", aff)]
            authors.append({"name": tex_to_text(name), "affiliation": [x for x in lines if x and "@" not in x]})
        if not authors:
            raise BuildError("no \\IEEEauthorblockN author entries found in report/main.tex")
        after = full[full.index("\\maketitle"):]
        date_env = re.match(r"\\maketitle\s*\\begin\{center\}(.*?)\\end\{center\}", after, re.S)
        keywords = env_body(full, "IEEEkeywords")
        abstract = env_body(full, "abstract")
        if abstract is None:
            raise BuildError("report/main.tex has no abstract environment")
        return {"title": tex_to_text(parts[0]), "subtitle": tex_to_text(" ".join(parts[1:])),
                "authors": authors, "date": tex_to_text(date_env.group(1)) if date_env else "",
                "keywords": tex_to_text(keywords or ""), "abstract_tex": abstract}

    # ---- numbering of sections, figures, tables and equations (LaTeX order) ------------------------
    def number(self, body: str) -> tuple[dict[str, str], str]:
        """Return ({label: printed number}, body with numbered display math tagged and starred)."""
        labels: dict[str, str] = {}
        sec = sub = fig = tab = eq = 0
        appendix = False
        current = ""
        out, pos = [], 0
        token = re.compile(r"\\(section|subsection)(\*?)\{|\\begin\{(figure|table)\*?\}|\\label\{([^}]*)\}|"
                           + re.escape(APPENDIX_MARK)
                           + r"|\\begin\{(equation|multline|gather|align)(\*?)\}")
        for m in token.finditer(body):
            if m.start() < pos:
                continue
            if m.group(0) == APPENDIX_MARK:
                appendix, sec, sub = True, 0, 0
            elif m.group(1):
                if m.group(2):
                    continue
                if m.group(1) == "section":
                    sec, sub = sec + 1, 0
                    current = letter(sec) if appendix else roman(sec)
                else:
                    sub += 1
                    current = letter(sub)
            elif m.group(3):
                if m.group(3) == "figure":
                    fig += 1
                    current = str(fig)
                else:
                    tab += 1
                    current = roman(tab)
            elif m.group(4):
                labels[m.group(4)] = current
            elif m.group(5):
                env, star = m.group(5), m.group(6)
                end_tok = f"\\end{{{env}{star}}}"
                end = body.index(end_tok, m.end())
                content = body[m.end():end]
                out.append(body[pos:m.start()])
                pos = end + len(end_tok)
                lines = [ln for ln in re.split(r"\\\\(?![a-zA-Z])", content) if ln.strip()]
                if star:
                    out.append("\n\\[" + (f"\\begin{{gathered}}{content}\\end{{gathered}}" if len(lines) > 1 else content)
                               + "\\]\n")
                    continue
                if env in ("equation", "multline"):
                    eq += 1
                    lab = re.search(r"\\label\{([^}]*)\}", content)
                    if lab:
                        labels[lab.group(1)] = str(eq)
                    inner = re.sub(r"\\label\{[^}]*\}", "", content)
                    if env == "multline":
                        inner = "\\begin{gathered}" + inner + "\\end{gathered}"
                    out.append(f"\n\\[{inner}\\tag{{{eq}}}\\]\n")
                else:
                    for ln in lines:
                        tagged = not re.search(r"\\(nonumber|notag)\b", ln)
                        if tagged:
                            eq += 1
                        lab = re.search(r"\\label\{([^}]*)\}", ln)
                        if lab:
                            labels[lab.group(1)] = str(eq)
                        ln = re.sub(r"\\label\{[^}]*\}|\\nonumber|\\notag", "", ln).replace("&", "")
                        out.append(f"\n\\[{ln.strip()}" + (f"\\tag{{{eq}}}" if tagged else "") + "\\]\n")
        out.append(body[pos:])
        return labels, "".join(out)

    # ---- LaTeX preprocessing -----------------------------------------------------------------------
    def provenance_tokens(self, text: str) -> str:
        """Numbers macros with provenance become tokens (replaced by annotated spans after pandoc)."""
        names = {n for n in self.macros if n in self.prov}

        def outside(seg: str) -> str:
            return re.sub(r"\\([A-Za-z]+)(?![A-Za-z])",
                          lambda m: PROV_TOKEN.format(m.group(1)) if m.group(1) in names else m.group(0), seg)
        parts = re.split(r"((?<!\\)\$[^$]*(?<!\\)\$)", text)
        res = []
        for k, seg in enumerate(parts):
            if k % 2 == 0:
                res.append(outside(seg))
                continue
            inner = seg[1:-1].strip()
            m = re.fullmatch(r"\\([A-Za-z]+)", inner)
            res.append(PROV_TOKEN.format(m.group(1)) if m and m.group(1) in names else seg)
        return "".join(res)

    def citet(self, text: str) -> str:
        def rep(m):
            keys = [k.strip() for k in m.group(1).split(",")]
            for k in keys:
                if k not in self.bib:
                    raise BuildError(f"\\citet{{{k}}}: key not in report/refs.bib")
            return ", ".join(f"{bib_short_authors(self.bib[k])}~\\citep{{{k}}}" for k in keys)
        return re.sub(r"\\citet\{([^}]*)\}", rep, text)

    def preprocess(self, body: str, defs: dict[str, tuple[int, str]], figures_dir: Path) -> tuple[str, dict]:
        body = body.replace("\\appendices", "\n\n" + APPENDIX_MARK + "\n\n")
        body = self.provenance_tokens(body)
        body = expand_macros(body, defs)
        for k in re.findall(r"\\(?:cite|citep|citet|citealp|citeauthor)\{([^}]*)\}", body):
            for key in k.split(","):
                if key.strip() not in self.bib:
                    raise BuildError(f"citation key {key.strip()!r} not in report/refs.bib")
        body = self.citet(body)
        # booktabs header rows (between \toprule and \midrule); pandoc keeps at most one as <thead>
        self.header_rows = []
        for tb in re.findall(r"\\begin\{tabular\}(.*?)\\end\{tabular\}", body, re.S):
            head = re.search(r"\\toprule(.*?)\\midrule", tb, re.S)
            self.header_rows.append(len(re.findall(r"\\\\", head.group(1))) if head else 0)
        body = re.sub(r"\\begin\{(figure|table)\*\}", r"\\begin{\1}", body)
        body = re.sub(r"\\end\{(figure|table)\*\}", r"\\end{\1}", body)
        body = strip_command(body, "resizebox", 2, True)
        body = strip_command(body, "setlength", 2, False)
        body = re.sub(r"\\cmidrule(\([^)]*\))?\{[^}]*\}", "", body)
        body = re.sub(r"\\(addlinespace|centering|scriptsize|footnotesize|small|normalsize|large|Large)(?![A-Za-z])"
                      r"(\[[^\]]*\])?", "", body)
        body = re.sub(r"\\paragraph\{([^}]*)\}", r"\n\n\\textbf{\1} ", body)

        def graphic(m):
            name = Path(m.group(1)).stem
            png = figures_dir / f"{name}.png"
            if not png.is_file():
                raise BuildError(f"\\includegraphics{{{m.group(1)}}}: no PNG figures/{name}.png for the website")
            return f"\\includegraphics{{figures/{name}.png}}"
        body = re.sub(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}", graphic, body)
        labels, body = self.number(body)

        def ref(m):
            key = m.group(1)
            if key not in labels:
                raise BuildError(f"\\ref{{{key}}}: undefined label (would print ?? in the PDF)")
            return f"\\hyperref[{key}]{{{labels[key]}}}"
        body = re.sub(r"\\(?:ref|autoref)\{([^}]*)\}", ref, body)
        body = re.sub(r"\\eqref\{([^}]*)\}", lambda m: "(" + ref(m) + ")", body)
        return body, labels

    # ---- pandoc ----------------------------------------------------------------------------------------
    def pandoc(self, latex: str, id_prefix: str) -> str:
        doc = "\\documentclass{article}\n\\begin{document}\n" + latex + "\n\\end{document}\n"
        cmd = [self.pandoc_bin, "-f", "latex", "-t", "html5", "--katex", "--citeproc", "--wrap=none",
               "--bibliography", str(self.dir / "refs.bib"), "--csl", str(CSL), "-M", "link-citations=true",
               "--shift-heading-level-by=1", f"--id-prefix={id_prefix}"]
        try:
            r = subprocess.run(cmd, input=doc, capture_output=True, text=True, check=False)
        except OSError as e:
            raise BuildError(f"could not run pandoc: {e}") from e
        if r.returncode:
            raise BuildError(f"pandoc failed (exit {r.returncode}):\n{r.stderr.strip()}")
        bad = [ln for ln in r.stderr.splitlines() if "[WARNING]" in ln and ("Citeproc" in ln or "Could not" in ln)]
        if bad:
            raise BuildError("pandoc reported unresolved content:\n  " + "\n  ".join(bad))
        return r.stdout

    # ---- HTML post-processing -----------------------------------------------------------------------
    def postprocess(self, html_s: str, prefix: str, figures_dir: Path) -> tuple[str, list[tuple[int, str, str]]]:
        # numbered headings (IEEE: I, II ... / A, B ...; appendix sections lettered)
        toc: list[tuple[int, str, str]] = []
        sec = sub = 0
        appendix = False
        out, pos = [], 0
        for m in re.finditer(r"<p>" + APPENDIX_MARK + r"</p>\n?|<h([23])([^>]*)>(.*?)</h\1>", html_s, re.S):
            out.append(html_s[pos:m.start()])
            pos = m.end()
            if m.group(0).startswith("<p>"):
                appendix, sec, sub = True, 0, 0
                continue
            level, attrs, inner = int(m.group(1)), m.group(2), m.group(3)
            hid = re.search(r'id="([^"]+)"', attrs)
            num = ""
            if "unnumbered" not in attrs:
                if level == 2:
                    sec, sub = sec + 1, 0
                    num = f"Appendix {letter(sec)}" if appendix else f"{roman(sec)}."
                else:
                    sub += 1
                    num = f"{letter(sub)}."
            label = f'<span class="sec-n">{num}</span>' if num else ""
            out.append(f"<h{level}{attrs}>{label}{inner}</h{level}>")
            if hid:
                toc.append((level, hid.group(1), (num + " " if num else "") + re.sub(r"<[^>]+>", "", inner)))
        out.append(html_s[pos:])
        html_s = "".join(out)

        # figures: "Fig. N." label, alt text, intrinsic size, link to the interactive version
        fig_n = 0

        def figure(m):
            nonlocal fig_n
            fig_n += 1
            fid, body = m.group(1), m.group(2)
            cap = re.search(r"<figcaption>(.*?)</figcaption>", body, re.S)
            cap_html = cap.group(1) if cap else ""
            alt = esc(re.sub(r"\s+", " ", PROV_RE.sub(lambda t: tex_value_text(self.macros[t.group(1)]),
                                                         re.sub(r"<[^>]+>", "", cap_html))).strip())
            img = re.search(r'<img src="([^"]+)"[^>]*/?>', body)
            if not img:
                raise BuildError(f"figure {fid} has no image")
            w, h = png_size(figures_dir / Path(img.group(1)).name)
            label = fid[len(prefix):] if fid else ""
            chart = FIG_TO_CHART.get(label)
            link = (f' <a class="fig-interactive" href="#fig-{chart}">Interactive version</a>' if chart else "")
            return (f'<figure class="paper-figure" id="{fid}"><img src="{img.group(1)}" alt="Fig. {fig_n}. {alt}" '
                    f'width="{w}" height="{h}" loading="lazy" decoding="async">'
                    f'<figcaption><span class="fig-label">Fig. {fig_n}.</span> {cap_html}{link}</figcaption></figure>')
        html_s = re.sub(r'<figure(?: id="([^"]*)")?>(.*?)</figure>', figure, html_s, flags=re.S)

        # tables: caption outside a horizontally scrolling wrapper, "TABLE I" labels
        tab_n = 0
        header_rows = list(getattr(self, "header_rows", []))

        def table(m):
            nonlocal tab_n
            tab_n += 1
            tid, body = m.group(1) or m.group(3) or "", m.group(2) if m.group(2) is not None else m.group(4)
            cap = re.search(r"<caption>(.*?)</caption>\n?", body, re.S)
            body = body.replace(cap.group(0), "") if cap else body
            k = header_rows[tab_n - 1] if tab_n - 1 < len(header_rows) else 0
            if k and "<thead>" not in body:
                rows = re.findall(r"<tr[^>]*>.*?</tr>\n?", body, re.S)
                head = "".join(re.sub(r"<td( |>)", r'<th scope="col"\1', r).replace("</td>", "</th>") for r in rows[:k])
                for r in rows[:k]:
                    body = body.replace(r, "", 1)
                body = "<thead>\n" + head + "</thead>\n" + body
            idattr = f' id="{tid}"' if tid else ""
            return (f'<figure class="table-figure paper-table"{idattr}><figcaption><span class="fig-label">'
                    f'TABLE {roman(tab_n)}.</span> {cap.group(1) if cap else ""}</figcaption>'
                    f'<div class="table-wrap" role="region" aria-label="Table {roman(tab_n)}" tabindex="0">'
                    f'<table>{body}</table></div></figure>')
        html_s = re.sub(r'<div id="([^"]*)">\s*<table>(.*?)</table>\s*</div>|()<table>(.*?)</table>', table, html_s,
                        flags=re.S)

        # references: heading + audit status per entry
        def ref_entry(m):
            key = m.group(2)
            if key in self.audit_rows:
                badge = (f'<div class="ref-status"><span class="pill pill-ok">identity-verified (arXiv)</span>'
                         f'<span class="ref-scope">Checked: {md_inline(self.audit_rows[key])}. Publisher pagination/DOI '
                         f'not fully audited (docs/CITATION_AUDIT.md).</span></div>')
            elif "eprint" not in self.bib.get(key, {}):
                badge = '<div class="ref-status"><span class="pill pill-warn">non-public document</span></div>'
            else:
                badge = '<div class="ref-status"><span class="pill pill-warn">metadata unverified</span></div>'
            return m.group(1) + badge + m.group(3)
        html_s = re.sub(r'(<div id="' + re.escape(prefix) + r'ref-([^"]+)" class="csl-entry"[^>]*>.*?'
                        r'<div class="csl-right-inline">.*?)(</div>\s*</div>)', ref_entry, html_s, flags=re.S)
        html_s = html_s.replace(f'<div id="{prefix}refs"',
                                f'<h2 class="unnumbered refs-heading" id="{prefix}references">References</h2>\n'
                                f'<div id="{prefix}refs"', 1)
        if f'id="{prefix}refs"' in html_s:
            toc.append((2, f"{prefix}references", "References"))

        # numbers with provenance
        html_s = PROV_RE.sub(lambda t: num_span(t.group(1), self.macros, self.prov, self.ref_sha), html_s)
        return html_s, toc

    # ---- public entry points ----------------------------------------------------------------------
    def render_part(self, name: str, prefix: str, figures_dir: Path, main: bool) -> dict:
        full = self.read(name)
        defs = {**parse_macro_defs(full), "runid": (1, "\\texttt{#1}")}
        start = full.index("\\begin{document}")
        meta = self.metadata(full) if main else {"title": " — ".join(tex_to_text(p) for p in re.split(
            r"\\\\", brace_group(full, full.index("\\title") + len("\\title"))[0]) if p.strip())}
        doc = full[start + len("\\begin{document}"):full.index("\\end{document}")]
        doc = re.sub(r"\\bibliographystyle\{[^}]*\}|\\bibliography\{[^}]*\}", "", doc)
        if main:
            kw_end = doc.index("\\end{IEEEkeywords}") + len("\\end{IEEEkeywords}") if "IEEEkeywords" in doc else \
                doc.index("\\end{abstract}") + len("\\end{abstract}")
            body = doc[kw_end:]
        else:
            body = re.sub(r"\\maketitle", "", doc)
        body = remove_macro_defs(body)
        latex, labels = self.preprocess(body, defs, figures_dir)
        html_s, toc = self.postprocess(self.pandoc(latex, prefix), prefix, figures_dir)
        part = {"html": html_s, "toc": toc, "labels": labels, "title": meta["title"]}
        if main:
            abstract_latex, _ = self.preprocess(remove_macro_defs(meta.pop("abstract_tex")), defs, figures_dir)
            abstract_html = self.pandoc(abstract_latex, prefix + "abstract-")
            abstract_html = re.sub(r'<h2 class="unnumbered"[^>]*>References</h2>|<div id="[^"]*refs".*', "",
                                   abstract_html, flags=re.S)
            meta["abstract_html"] = PROV_RE.sub(lambda t: num_span(t.group(1), self.macros, self.prov, self.ref_sha),
                                                abstract_html)
            part["meta"] = meta
        return part

    def figure_captions(self, part: dict) -> dict[str, str]:
        """Rendered caption HTML of the report figures that have an interactive counterpart."""
        caps = {}
        for label, chart in FIG_TO_CHART.items():
            m = re.search(r'<figure class="paper-figure" id="[^"]*' + re.escape(label) + r'">.*?<figcaption>'
                          r'(<span class="fig-label">[^<]*</span>)(.*?)(?: <a class="fig-interactive"[^>]*>[^<]*</a>)?'
                          r'</figcaption>', part["html"], re.S)
            if m:
                caps[chart] = (m.group(1), m.group(2))
        return caps


def split_sections(part_html: str, prefix: str) -> tuple[list[dict], str]:
    """Split a rendered part at its <h2>/<h3> headings.

    Returns (sections, references_html). Each section is {id, number, title, level, html} where
    ``html`` is the content after the heading up to the next heading (the heading itself excluded)."""
    ref_start = part_html.find(f'<h2 class="unnumbered refs-heading" id="{prefix}references">')
    body, refs = (part_html[:ref_start], part_html[ref_start:]) if ref_start >= 0 else (part_html, "")
    refs = re.sub(r'^<h2[^>]*>.*?</h2>\s*', "", refs, flags=re.S).strip()
    heads = list(re.finditer(r"<h([23])([^>]*)>(.*?)</h\1>", body, re.S))
    sections = []
    if heads and body[:heads[0].start()].strip():
        raise BuildError(f"{prefix}: content before the first section heading")
    for k, m in enumerate(heads):
        end = heads[k + 1].start() if k + 1 < len(heads) else len(body)
        hid = re.search(r'id="([^"]+)"', m.group(2))
        num = re.search(r'<span class="sec-n">(.*?)</span>', m.group(3))
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", re.sub(r'<span class="sec-n">.*?</span>', "",
                                                                     m.group(3)))).strip()
        sections.append({"id": hid.group(1) if hid else "", "number": num.group(1) if num else "",
                         "title": title, "level": int(m.group(1)) - 1,
                         "html": body[m.end():end].strip()})
    return sections, refs


def render_paper(report_dir: Path, macros: dict[str, str], prov: dict, ref_sha: str, bib: list[dict],
                 audit_rows: dict[str, str], figures_dir: Path) -> dict:
    """Design-independent paper data rendered from report/ (written to data/paper.json).

    Schema::

        {title, subtitle, authors: [{name, affiliations: [str]}], date_line, keywords,
         abstract_html,
         sections: [{id, number, title, level, html}],            # report/main.tex, level 1 = \\section
         references_html,                                          # citeproc bibliography of the paper
         appendix_title, appendix_sections: [...], appendix_references_html,
         figures: [{part, id, label, number, src, width, height, caption_html}],
         labels: {paper: {latex label: printed number}, appendix: {...}},
         source: {main, appendix, pandoc}}

    HTML fragments contain pandoc ``<span class="math inline|display">`` TeX (render with KaTeX),
    ``<span class="num" data-macro=... data-provenance=...>`` numbers, ``figure.paper-figure`` images
    (``figures/<name>.png``) and ``figure.paper-table`` tables; ids are prefixed ``paper-`` / ``app-``."""
    renderer = ReportRenderer(report_dir, macros, prov, ref_sha, bib, audit_rows)
    paper = renderer.render_part("main", "paper-", figures_dir, True)
    appendix = renderer.render_part("appendix", "app-", figures_dir, False)
    meta = paper["meta"]
    sections, refs = split_sections(paper["html"], "paper-")
    app_sections, app_refs = split_sections(appendix["html"], "app-")
    figures = []
    for part, html_s in (("paper", paper["html"]), ("appendix", appendix["html"])):
        for m in re.finditer(r'<figure class="paper-figure" id="([^"]*)"><img src="([^"]+)"[^>]*width="(\d+)" '
                             r'height="(\d+)"[^>]*><figcaption><span class="fig-label">Fig\. (\d+)\.</span> (.*?)'
                             r'(?: <a class="fig-interactive"[^>]*>[^<]*</a>)?</figcaption></figure>', html_s, re.S):
            figures.append({"part": part, "id": m.group(1), "label": m.group(1).split("-", 1)[1],
                            "number": int(m.group(5)), "src": m.group(2), "width": int(m.group(3)),
                            "height": int(m.group(4)), "caption_html": m.group(6).strip()})
    version = subprocess.run([renderer.pandoc_bin, "--version"], capture_output=True, text=True).stdout.split("\n")[0]
    return {
        "title": meta["title"], "subtitle": meta.get("subtitle", ""),
        "authors": [{"name": a["name"], "affiliations": a["affiliation"]} for a in meta["authors"]],
        "date_line": meta.get("date", ""), "keywords": meta.get("keywords", ""),
        "abstract_html": meta["abstract_html"].strip(),
        "sections": sections, "references_html": refs,
        "appendix_title": appendix["title"], "appendix_sections": app_sections, "appendix_references_html": app_refs,
        "figures": figures, "labels": {"paper": paper["labels"], "appendix": appendix["labels"]},
        "source": {"main": "report/main.tex", "appendix": "report/appendix.tex", "pandoc": version},
        # full rendered parts (with headings) for templates that show the paper as one flow
        "_paper_html": paper["html"], "_appendix_html": appendix["html"],
        "_paper_toc": paper["toc"], "_appendix_toc": appendix["toc"], "_fig_caps": renderer.figure_captions(appendix),
    }


def png_size(path: Path) -> tuple[int, int]:
    with open(path, "rb") as fh:
        head = fh.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise BuildError(f"{path} is not a PNG")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


# ---------------------------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------------------------
def gh_tree(sha: str, path: str) -> str:
    return f"{REPO_URL}/tree/{sha or 'main'}/{path}"


def gh_blob(sha: str, path: str) -> str:
    return f"{REPO_URL}/blob/{sha or 'main'}/{path}"


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


HERO_CMAES_TRAIN_SEED = 101  # pre-specified training run shown in the hero (not the best of the three)


def hero_data(data: "Data", ref_sha: str) -> dict:
    """Pulse timing and held-out infidelity per sequence for the hero instrument (Scenario A, T = 2 us).

    Canonical sequences are rebuilt with the same constructors as the benchmark (same width, guard, grid);
    CMA-ES is the timing+phase result of the pre-specified training run. Infidelities are the pinned run's
    test-seed means; the floor is the analytic T1 + white-dephasing channel (as in make_report_artifacts.py).
    """
    from ddopt.evaluation import canonical_baselines
    from ddopt.scenarios import load_scenario

    run = data.runs["bench_a"]
    cfg = load_scenario("scenario_a")
    w = cfg["window"]
    out: dict = {"T": w["T"], "width": w["width"], "run_id": run["run_id"],
                 "run_href": gh_tree(ref_sha, "results/" + run["run_id"]),
                 "floor": data.mra.floor_infidelity(cfg, w["T"]), "by_n": {}, "default_n": "8"}
    test_seeds = None
    for r in run["payload"]["runs"]:
        n = r["n"]
        if n in out["by_n"]:
            continue
        test_seeds = r["seeds"]["test"]
        bl = canonical_baselines(n, w["T"], w["width"], guard=w["guard"], dt_grid=w["dt_grid"], include_hahn=False)
        summ = r["test"]["summary"]
        seqs = {k: {"centers": list(sq.centers), "phases": list(sq.phases), "eps": summ[k]["mean_over_seeds"]}
                for k, sq in bl.items() if k in summ}
        cm = [x for x in run["payload"]["runs"] if x["n"] == n and x["mode"] == "both"
              and x["seeds"]["train"] == HERO_CMAES_TRAIN_SEED]
        if len(cm) != 1:
            raise BuildError(f"hero: expected one timing+phase run with training seed {HERO_CMAES_TRAIN_SEED} at n={n}")
        bs = cm[0]["optimization"]["best_sequence"]
        seqs["cmaes"] = {"centers": bs["centers"], "phases": bs["phases"],
                         "eps": cm[0]["comparison_vs_selected"]["pooled"]["eps_b"], "train_seed": HERO_CMAES_TRAIN_SEED}
        out["by_n"][str(n)] = {"selected": r["selected_baseline"], "seqs": seqs}
    out["by_n"] = dict(sorted(out["by_n"].items(), key=lambda kv: int(kv[0])))
    out["test_seeds"] = f"{min(test_seeds)}–{max(test_seeds)}" if test_seeds else ""
    return out


def og_image(path: Path, title: str, hero: dict | None = None) -> None:
    """1200x630 social card in the site's design language (dark field, Geist, pulse-amber pulse train)."""
    import textwrap

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    fdir = SRC / "og-fonts"
    sans = font_manager.FontProperties(fname=str(fdir / "Geist-SemiBold.ttf"))
    mono = font_manager.FontProperties(fname=str(fdir / "GeistMono-Medium.ttf"))
    bg, fg, muted, subtle, amber, grid = "#08090b", "#f4f4f5", "#9a9ba3", "#80818a", "#f6c56f", "#16171b"
    fig = plt.figure(figsize=(12, 6.3), dpi=100)
    fig.patch.set_facecolor(bg)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1200)
    ax.set_ylim(0, 630)
    ax.axis("off")
    for x in range(0, 1201, 48):
        ax.plot([x, x], [0, 630], color=grid, lw=1)
    for y in range(6, 631, 48):
        ax.plot([0, 1200], [y, y], color=grid, lw=1)
    ax.text(72, 548, "IEEE MIDTERM REPORT / SYNTHETIC SIMULATION STUDY", color=subtle, fontsize=13, fontproperties=mono)
    ax.text(72, 508, "\n".join(textwrap.wrap(title, 34)[:3]), color=fg, fontsize=42, fontproperties=sans, va="top",
            linespacing=1.12)
    # pulse train: XY8 at n = 8 in the 2 us window (real timing when hero data is available)
    x0, x1, base, h = 72, 1128, 150, 70
    ax.plot([x0, x1], [base, base], color="#34353d", lw=1.2)
    centers = (hero or {}).get("by_n", {}).get("8", {}).get("seqs", {}).get("xy8", {}).get("centers") or []
    T = (hero or {}).get("T", 2e-6)
    for c in centers:
        cx = x0 + (c / T) * (x1 - x0)
        ax.add_patch(matplotlib.patches.Rectangle((cx - 7, base), 14, h, color=amber, lw=0))
    ax.text(x0, base - 34, "0", color=subtle, fontsize=12, fontproperties=mono)
    ax.text(x1, base - 34, "2.0 \u00b5s", color=subtle, fontsize=12, fontproperties=mono, ha="right")
    ax.text(72, 48, "udsy19.github.io/quantum-dd-optimizer", color=muted, fontsize=13, fontproperties=mono)
    ax.text(1128, 48, "No hardware data. Result: negative.", color=muted, fontsize=13, fontproperties=mono, ha="right")
    fig.savefig(path, facecolor=fig.get_facecolor(), metadata={"Software": None})
    plt.close(fig)


# ---------------------------------------------------------------------------------------------
# main build
# ---------------------------------------------------------------------------------------------
def build(out: Path, pdf_dir: Path | None = None, site_url: str = SITE_URL) -> dict:
    if not shutil.which("pandoc"):
        raise BuildError("pandoc is required to render the paper from report/ (e.g. `sudo apt-get install "
                         "pandoc`); refusing to build a site without the paper body")
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

    # literature status, citation metadata, hardware gates
    bib = parse_bib((ROOT / "report" / "refs.bib").read_text())
    audit = parse_md_table_after((ROOT / "docs" / "CITATION_AUDIT.md").read_text(), "## Follow-up completion")
    audit_rows = {r[0]: r[2] for r in audit if len(r) >= 3}
    cff_path = ROOT / "CITATION.cff"
    cff = parse_cff(cff_path.read_text()) if cff_path.is_file() else {}
    hw_rows = parse_md_table_after((ROOT / "docs" / "HARDWARE_PROTOCOL.md").read_text(), "## 0. Gate list")
    hw = [[r[0], r[1]] for r in hw_rows if len(r) >= 2]
    if not hw:
        raise BuildError("could not read the gate status table from docs/HARDWARE_PROTOCOL.md")

    # ---- the paper itself, rendered from report/ ------------------------------------------------
    rendered = render_paper(ROOT / "report", macros, prov, ref_sha, bib, audit_rows, ROOT / "figures")
    paper_json = {k: v for k, v in rendered.items() if not k.startswith("_")}
    paper = {"html": rendered["_paper_html"], "toc": rendered["_paper_toc"]}
    appendix = {"html": rendered["_appendix_html"], "toc": rendered["_appendix_toc"],
                "title": rendered["appendix_title"]}
    meta = {"title": rendered["title"], "subtitle": rendered["subtitle"], "date": rendered["date_line"],
            "keywords": rendered["keywords"], "abstract_html": rendered["abstract_html"],
            "authors": [{"name": a["name"], "affiliation": a["affiliations"]} for a in rendered["authors"]]}
    pandoc_version = rendered["source"]["pandoc"]
    fig_caps = rendered["_fig_caps"]
    missing = sorted(set(FIG_TO_CHART.values()) - set(fig_caps))
    if missing:
        raise BuildError(f"appendix figures for the interactive charts not found: {missing}")

    # ---- output tree -----------------------------------------------------------------------------
    if out.exists():
        shutil.rmtree(out)
    (out / "data").mkdir(parents=True)
    shutil.copytree(SRC / "assets", out / "assets")
    (out / "figures").mkdir()
    for f in sorted((ROOT / "figures").glob("*.png")):
        shutil.copy2(f, out / "figures" / f.name)
    pdfs = {}
    for src_name, dst_name in (("main.pdf", "paper.pdf"), ("appendix.pdf", "appendix.pdf"),
                               ("combined_report.pdf", "combined_report.pdf")):
        if pdf_dir and (pdf_dir / src_name).is_file():
            shutil.copy2(pdf_dir / src_name, out / dst_name)
            pdfs[dst_name] = True
    hero = hero_data(data, ref_sha)
    og_image(out / "assets" / "og.png", meta["title"], hero)

    numbers_json = {k: {"tex": v, "text": tex_value_text(v), "value": tex_value_float(v), **prov.get(k, {})}
                    for k, v in sorted(macros.items())}
    files = {"numbers.json": numbers_json, "tables.json": tables, "runs.json": run_rows,
             "benchmark.json": charts["benchmark"], "convergence.json": charts["convergence"],
             "robustness.json": charts["robustness"], "spectroscopy.json": charts["spectroscopy"],
             "tests.json": tests,
             "paper.json": paper_json}
    for name, obj in files.items():
        (out / "data" / name).write_text(dumps(obj) + "\n", encoding="utf-8")
    build_info = {"build_commit": build_sha, "dirty": dirty, "katex": KATEX_VERSION, "site_url": site_url,
                  "pinned_runs": data.runs_map, "pdfs": sorted(pdfs), "pandoc": pandoc_version,
                  "data_sha256": {n: hashlib.sha256((out / "data" / n).read_bytes()).hexdigest() for n in sorted(files)}}
    (out / "data" / "build.json").write_text(dumps(build_info) + "\n", encoding="utf-8")

    # ---- templates -----------------------------------------------------------------------------------
    def toc_html(entries: list[tuple[int, str, str]]) -> str:
        items, open_sub = [], False
        for level, hid, text in entries:
            if level == 3:
                if not open_sub:
                    items.append("<ol>")
                    open_sub = True
                items.append(f'<li><a href="#{esc(hid)}">{esc(text)}</a></li>')
            else:
                if open_sub:
                    items.append("</ol></li>")
                    open_sub = False
                elif items:
                    items.append("</li>")
                items.append(f'<li><a href="#{esc(hid)}">{esc(text)}</a>')
        items.append("</ol></li>" if open_sub else ("</li>" if items else ""))
        return "<ol>" + "".join(items) + "</ol>"

    def authors_html() -> str:
        return "".join(f'<li><span class="author-name">{esc(a["name"])}</span>'
                       f'<span class="author-aff">{"<br>".join(esc(x) for x in a["affiliation"])}</span></li>'
                       for a in meta["authors"])

    def chart_caption(chart: str, note: str = "") -> str:
        label, cap = fig_caps[chart]
        num = re.sub(r"<[^>]+>", "", label).strip().rstrip(".")
        target = next(lbl for lbl, c in FIG_TO_CHART.items() if c == chart)
        return (f'<span class="fig-label">Interactive {esc(num)} (supplementary appendix).</span> {cap}'
                + (f' <em class="site-note">{esc(note)}</em>' if note else "")
                + f' <a href="#app-{esc(target)}">Static figure</a>.')

    short = build_sha[:7] if build_sha else "unknown"
    base_path = urlparse(site_url).path or "/"
    full_title = meta["title"] + (f": {meta['subtitle']}" if meta.get("subtitle") else "")
    description = (f"{meta['subtitle'] + '. ' if meta.get('subtitle') else ''}Online version of the report by "
                   + ", ".join(a["name"] for a in meta["authors"]) + ". Synthetic simulations only; no hardware data.")
    ctx = {
        "title": esc(meta["title"]), "subtitle": esc(meta.get("subtitle", "")), "full_title": esc(full_title),
        "description": esc(description), "date_line": esc(meta.get("date", "")),
        "keywords": esc(meta.get("keywords", "")), "authors": authors_html(),
        "author_names": esc(", ".join(a["name"] for a in meta["authors"])),
        "abstract_html": meta["abstract_html"],
        "paper_html": paper["html"], "appendix_html": appendix["html"], "appendix_title": esc(appendix["title"]),
        "toc_paper": toc_html(paper["toc"]), "toc_appendix": toc_html(appendix["toc"]),
        "cap_spectroscopy": chart_caption("spectroscopy"),
        "cap_benchmark": chart_caption("benchmark", "This interactive version also plots timing-only CMA-ES on its "
                                                    "log axis; values are in the data table."),
        "cap_convergence": chart_caption("convergence"), "cap_robustness": chart_caption("robustness"),
        "site_url": esc(site_url), "base_path": esc(base_path),
        "repo_url": REPO_URL, "report_tree": gh_tree(ref_sha, "report/"),
        "katex_css": KATEX_BASE + "katex.min.css", "katex_css_sri": KATEX_CSS_SRI,
        "katex_js": KATEX_BASE + "katex.min.js", "katex_js_sri": KATEX_JS_SRI, "katex_version": KATEX_VERSION,
        "pandoc_version": esc(pandoc_version),
        "build_sha": esc(short + ("+dirty" if dirty else "")),
        "build_sha_link": f"{REPO_URL}/commit/{build_sha}" if build_sha else REPO_URL,
        "runs_table": render_runs_table(run_rows),
        "hardware_table": render_hardware(hw),
        "bibtex": esc(make_bibtex(cff, build_sha)),
        "cff_link": gh_blob(ref_sha, "CITATION.cff"),
        "tests_failed": str(tests["failures"]), "tests_errors": str(tests["errors"]),
        "tests_skipped": str(tests["skipped"]),
        "tests_run": esc(tests["run_id"]), "tests_run_link": gh_tree(ref_sha, "results/" + tests["run_id"]),
        "chart_data": dumps(charts).replace("</", "<\\/"),
        "hero_data": dumps(hero).replace("</", "<\\/"),
    }
    flags = {"paper_pdf": "paper.pdf" in pdfs, "appendix_pdf": "appendix.pdf" in pdfs,
             "combined_pdf": "combined_report.pdf" in pdfs}
    flags["any_pdf"] = any(flags.values())

    def render(tpl: str) -> str:
        for flag, on in flags.items():
            pat = rf"@@if_{flag}@@(.*?)@@endif_{flag}@@"
            tpl = re.sub(pat, (lambda m: m.group(1)) if on else "", tpl, flags=re.S)

        def sub(m):
            kind, arg = m.group(1), m.group(2)
            if kind == "num":
                return num_span(arg, macros, prov, ref_sha)
            if kind == "prov":
                return prov_footer(arg, prov, ref_sha)
            if kind == "gh":
                return esc(gh_tree(ref_sha, arg) if arg.endswith("/") or "." not in arg.rsplit("/", 1)[-1]
                           else gh_blob(ref_sha, arg))
            if kind == "run":
                rid = data.rid(arg)
                return f'<a class="run-link" href="{esc(gh_tree(ref_sha, "results/" + rid))}"><code>{esc(rid)}</code></a>'
            if arg is None and kind in ctx:
                return ctx[kind]
            raise BuildError(f"unknown template marker @@{kind}{':' + arg if arg else ''}@@")
        return re.sub(r"@@(\w+)(?::([^@]+))?@@", sub, tpl)

    index = render((SRC / "index.html").read_text(encoding="utf-8"))
    (out / "index.html").write_text(index, encoding="utf-8")
    (out / "404.html").write_text(render((SRC / "404.html").read_text(encoding="utf-8")), encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {site_url}sitemap.xml\n")
    urls = [site_url] + [site_url + p for p in sorted(pdfs)]
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                     '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                     + "".join(f"  <url><loc>{esc(u)}</loc></url>\n" for u in urls) + "</urlset>\n")
    (out / ".nojekyll").write_text("")
    return {"out": str(out), "macros": len(macros), "checked_macros": len(data.expected), "pdfs": sorted(pdfs),
            "build_commit": build_sha, "dirty": dirty, "paper_sections": len(paper["toc"]),
            "appendix_sections": len(appendix["toc"])}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "site" / "dist")
    ap.add_argument("--pdf-dir", type=Path, default=None,
                    help="directory with freshly built main.pdf, appendix.pdf and combined_report.pdf to publish "
                         "(CI passes report/ after a successful scripts/build_report.sh); omitted = no PDF links")
    ap.add_argument("--site-url", default=SITE_URL)
    a = ap.parse_args(argv)
    try:
        info = build(a.out.resolve(), a.pdf_dir, a.site_url if a.site_url.endswith("/") else a.site_url + "/")
    except BuildError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"built {info['out']} (paper: {info['paper_sections']} TOC entries, appendix: {info['appendix_sections']}; "
          f"{info['macros']} macros, {info['checked_macros']} cross-checked against payloads; "
          f"pdfs={','.join(info['pdfs']) or 'none'}; commit {info['build_commit'][:12]}"
          f"{'+dirty' if info['dirty'] else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
