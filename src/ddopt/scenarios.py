"""Scenario construction from configs (lead-owned).

All device numbers in ``configs/scenario_*.json`` are SYNTHETIC ASSUMPTIONS (see
``docs/EXPERIMENT_PLAN.md``); they are not measurements of any device.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from ddopt.contracts import ControlErrors, DetuningProfile, NoiseModel, PSDComponent, SimulationConfig

ROOT = Path(__file__).resolve().parents[2]


def _inf(x):
    return math.inf if x in ("inf", None) else float(x)


def component_from_dict(d: dict) -> PSDComponent:
    return PSDComponent(d["kind"], {k: float(v) for k, v in d["params"].items()},
                        float(d.get("omega_low", 0.0)), _inf(d.get("omega_high", "inf")))


def noise_from_dict(d: dict) -> NoiseModel:
    det = d.get("detuning", {"kind": "none"})
    nm = NoiseModel(
        components=tuple(component_from_dict(c) for c in d["components"]),
        detuning=DetuningProfile(**det),
        T1=_inf(d.get("T1", "inf")),
        metadata=d.get("metadata", {}),
    )
    nm.validate()
    return nm


def load_scenario(name_or_path: str) -> dict:
    p = Path(name_or_path)
    if not p.exists():
        p = ROOT / "configs" / f"{name_or_path}.json"
    cfg = json.loads(p.read_text())
    cfg["_path"] = str(p)
    return cfg


def scenario_noise(cfg: dict, **overrides) -> NoiseModel:
    d = dict(cfg["noise"])
    d.update(overrides)
    return noise_from_dict(d)


def sim_config(cfg: dict, *, seed: int, n_traj: int, **kw) -> SimulationConfig:
    s = cfg["simulation"]
    ce = ControlErrors(**s.get("control_errors", {}))
    return SimulationConfig(n_traj=n_traj, seed=seed, noise_dt=s["noise_dt"],
                            pulse_steps=s["pulse_steps"], include_T1=s.get("include_T1", True),
                            control_errors=kw.pop("control_errors", ce), **kw)
