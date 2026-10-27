# Releasing

Releases are cut from `main` by the project owner. Package versions follow SemVer; the
scientific content of a release is defined by the runs pinned in `report/runs.json`.

## Checklist

1. **Green main.** CI (`ci.yml`) and Pages (`pages.yml`) green on the commit to release.
2. **Evidence.** `python -m ddopt.provenance verify results/*/` passes for every pinned run;
   `python scripts/make_report_artifacts.py && python scripts/make_evidence_map.py --check` is clean;
   `bash scripts/build_report.sh` builds with no undefined references.
3. **Review.** Open findings in `docs/REVIEW_FINDINGS.md` are resolved or disclosed; a human has
   reviewed the evidence ledger; citation status is stated (`docs/CITATION_AUDIT.md`).
4. **Version bump.** Update `version` in `pyproject.toml` and `src/ddopt/__init__.py`, and
   `version`/`date-released` in `CITATION.cff`.
5. **Changelog.** Move *Unreleased* entries under the new version with today's date; update links.
6. **Tag.** `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`. Without push access for
   tags, run the *release* workflow by hand on `main` (Actions → release → Run workflow) with the
   tag as input; it creates the tag at the tested commit. A release published from the web UI
   also works: the workflow then attaches its assets to that release.
7. **Automation.** `.github/workflows/release.yml` runs the tests, builds the sdist/wheel and the
   paper PDF, and creates a GitHub Release with those assets and the changelog section.
8. **Announce carefully.** Release notes must keep the wording rules of
   `docs/REPORT_REQUIREMENTS.md` (synthetic only, no hardware claims).

Do not publish to PyPI or submit the paper anywhere without explicit approval from the owner and
co-authors.
