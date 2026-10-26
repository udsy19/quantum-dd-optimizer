#!/usr/bin/env python3
"""Build ``report/evidence_map.csv`` (claim-to-artifact ledger) from ``report/claims.json``.

Columns (docs/REPORT_REQUIREMENTS.md):
claim_id, paper_section, exact_claim, provenance_type, artifact_path, command,
commit_sha, run_id, seed, reviewer, verification_status

Rules enforced:
* every record has every column; claim_ids are unique;
* provenance_type in {literature, model, dataset, hardware};
* verification_status in {PENDING, NOT RUN, UNVERIFIED, VERIFIED, FAILED};
* a VERIFIED claim needs a non-empty artifact_path that exists, a reviewer other
  than PENDING, and, for model/dataset/hardware claims, command, commit_sha and run_id;
* hardware claims can never be VERIFIED without a run_id (no hardware claim absent ID).

Usage::

    python scripts/make_evidence_map.py            # write report/evidence_map.csv
    python scripts/make_evidence_map.py --check    # exit 1 if CSV is stale or claims invalid
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLAIMS = REPO_ROOT / "report" / "claims.json"
DEFAULT_OUT = REPO_ROOT / "report" / "evidence_map.csv"

COLUMNS = [
    "claim_id",
    "paper_section",
    "exact_claim",
    "provenance_type",
    "artifact_path",
    "command",
    "commit_sha",
    "run_id",
    "seed",
    "reviewer",
    "verification_status",
]
PROVENANCE_TYPES = {"literature", "model", "dataset", "hardware"}
STATUSES = {"PENDING", "NOT RUN", "UNVERIFIED", "VERIFIED", "FAILED"}


class ClaimError(ValueError):
    pass


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return ";".join(str(x) for x in v)
    return str(v)


def load_claims(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    claims = data["claims"] if isinstance(data, dict) else data
    if not isinstance(claims, list):
        raise ClaimError("claims.json must be a list or an object with a 'claims' list")
    return claims


def validate_claims(claims: list[dict[str, Any]], repo_root: Path = REPO_ROOT) -> None:
    errors: list[str] = []
    seen: set[str] = set()
    for i, c in enumerate(claims):
        tag = f"claim[{i}] {c.get('claim_id', '?')}"
        if not isinstance(c, dict):
            errors.append(f"{tag}: not an object")
            continue
        missing = [k for k in COLUMNS if k not in c]
        extra = [k for k in c if k not in COLUMNS and not k.startswith("_")]
        if missing:
            errors.append(f"{tag}: missing fields {missing}")
        if extra:
            errors.append(f"{tag}: unknown fields {extra}")
        cid = _cell(c.get("claim_id"))
        if not cid:
            errors.append(f"{tag}: empty claim_id")
        elif cid in seen:
            errors.append(f"{tag}: duplicate claim_id")
        seen.add(cid)
        if not _cell(c.get("exact_claim")).strip():
            errors.append(f"{tag}: empty exact_claim")
        ptype = c.get("provenance_type")
        if ptype not in PROVENANCE_TYPES:
            errors.append(f"{tag}: provenance_type {ptype!r} not in {sorted(PROVENANCE_TYPES)}")
        status = c.get("verification_status")
        if status not in STATUSES:
            errors.append(f"{tag}: verification_status {status!r} not in {sorted(STATUSES)}")
        if status == "VERIFIED":
            art = _cell(c.get("artifact_path"))
            if not art:
                errors.append(f"{tag}: VERIFIED without artifact_path")
            else:
                for a in art.split(";"):
                    if not (repo_root / a).exists():
                        errors.append(f"{tag}: artifact_path {a!r} does not exist")
            if _cell(c.get("reviewer")) in ("", "PENDING"):
                errors.append(f"{tag}: VERIFIED without a named reviewer")
            if ptype in {"model", "dataset", "hardware"}:
                for k in ("command", "commit_sha", "run_id"):
                    if not _cell(c.get(k)):
                        errors.append(f"{tag}: VERIFIED {ptype} claim without {k}")
    if errors:
        raise ClaimError("invalid claims:\n  " + "\n  ".join(errors))


def render_csv(claims: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    w.writeheader()
    for c in sorted(claims, key=lambda c: _cell(c["claim_id"])):
        w.writerow({k: _cell(c.get(k)) for k in COLUMNS})
    return buf.getvalue()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true", help="fail if the CSV is out of date")
    args = ap.parse_args(argv)
    try:
        claims = load_claims(args.claims)
        validate_claims(claims)
    except (ClaimError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = render_csv(claims)
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else None
        if current != text:
            print(f"error: {args.out} is stale; run scripts/make_evidence_map.py", file=sys.stderr)
            return 1
        print(f"ok: {args.out} up to date ({len(claims)} claims)")
        return 0
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out} ({len(claims)} claims)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
