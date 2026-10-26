"""Derive post-hoc ablation configs from configs/scenario_a.json (EXPLORATORY, not pre-registered).

  scenario_a_noamp : Scenario A without the 2 % amplitude error (dephasing + T1 only)
  scenario_a_noT1  : Scenario A without T1 (isolates the decouplable dephasing part)
Usage: python scripts/make_ablation_configs.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
base = json.loads((ROOT / "configs/scenario_a.json").read_text())

a = json.loads(json.dumps(base))
a["description"] = "ABLATION (post-hoc, exploratory) of Scenario A: amplitude error removed. SYNTHETIC ASSUMPTIONS."
a["simulation"]["control_errors"]["amp_rel_std"] = 0.0
a["produced_by"] = "python scripts/make_ablation_configs.py"
(ROOT / "configs/scenario_a_noamp.json").write_text(json.dumps(a, indent=2) + "\n")

b = json.loads(json.dumps(base))
b["description"] = "ABLATION (post-hoc, exploratory) of Scenario A: T1 removed. SYNTHETIC ASSUMPTIONS."
b["noise"]["T1"] = "inf"
b["simulation"]["include_T1"] = False
b["produced_by"] = "python scripts/make_ablation_configs.py"
(ROOT / "configs/scenario_a_noT1.json").write_text(json.dumps(b, indent=2) + "\n")
print("ok")
