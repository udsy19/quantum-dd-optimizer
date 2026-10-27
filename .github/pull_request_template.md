## Summary

<!-- What changed and why. -->

## Evidence

<!-- Test summary line; new run IDs; commands. -->

## Checklist

- [ ] `python -m pytest -q` passes
- [ ] New results are recorded runs and verify (`python -m ddopt.provenance verify ...`)
- [ ] Report/site numbers regenerated if affected; `make_evidence_map.py --check` clean
- [ ] Deviations from the pre-registered plan logged in `docs/EXPERIMENT_PLAN.md`
- [ ] `docs/PROGRESS.md` updated
- [ ] No secrets, device configuration or unconsented team material
