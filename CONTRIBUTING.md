# Contributing

Thanks for helping. This is a **scientific research repository**: correctness, provenance and
honest reporting matter more than features or favourable numbers. Read [`CLAUDE.md`](CLAUDE.md)
(project rules for humans and AI agents alike), [`docs/ACCEPTANCE_GATES.md`](docs/ACCEPTANCE_GATES.md)
and [`docs/PHYSICS_CONVENTIONS.md`](docs/PHYSICS_CONVENTIONS.md) before changing code.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
python -m pytest -q                  # full suite (~35 s)
python -m pytest -q -m "not slow"    # what CI runs
```

Python ≥ 3.11. Exact versions of the recorded runs: `requirements-lock.txt`.

## Ground rules

1. **Never invent results.** No hand-typed numbers in `report/merged.tex` or the website: every number must
   come from `results/<run_id>/` via `scripts/make_report_artifacts.py` / `scripts/build_site.py`
   (embedded in the manuscript's generated blocks) and appear in `report/evidence_map.csv`.
2. **Results are immutable.** New experiments create new run directories (`ddopt.provenance.write_run`
   refuses to overwrite). To change what the paper shows, pin a different run in `report/runs.json`.
3. **Pre-registration.** Changes to scenarios, seeds, baselines, the selection rule or metrics after
   results exist must be logged under *Deviations* in `docs/EXPERIMENT_PLAN.md` and labelled
   exploratory in the paper.
4. **Held-out discipline.** Test seeds (9001–9005) must never be used for training, selection or tuning.
5. **Conventions.** Units: s, rad/s, rad; two-sided PSD in rad²/s. Public data contracts live in
   `src/ddopt/contracts.py` and `docs/INTERFACES.md`; breaking changes need review.
6. **Hardware.** No hardware submission, credential handling or device configuration without explicit
   written authorization from the project owner. Never commit secrets.
7. **Negative results are results.** Report regressions and failed checks plainly.

## Pull-request checklist

- [ ] `python -m pytest -q` passes locally (paste the summary line).
- [ ] New numerical code has tests against an analytic limit or an independent implementation.
- [ ] Any new result is a recorded run; `python -m ddopt.provenance verify results/<run_id>` passes.
- [ ] If report/site numbers changed: `scripts/make_report_artifacts.py`, `scripts/manuscript.py sync-generated --write` and `scripts/make_evidence_map.py --check` run clean.
- [ ] If the manuscript changed: edits are in `report/merged.tex` (the only canonical source, never inside generated blocks); `python scripts/manuscript.py check` and `bash scripts/build_report.sh` pass. See [`docs/LATEX_OVERLEAF_AGENT_GUIDE.md`](docs/LATEX_OVERLEAF_AGENT_GUIDE.md).
- [ ] `docs/PROGRESS.md` updated with commands and evidence.
- [ ] No secrets, tokens, private device configuration or unconsented team material.

## Commit style

Imperative subject line (`Add XY16 baseline`, `Fix grid snapping at window edge`), body explaining *why*.
