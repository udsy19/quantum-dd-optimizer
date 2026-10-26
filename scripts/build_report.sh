#!/usr/bin/env bash
# Build report/main.tex with latexmk and fail on errors, undefined references/citations,
# or an out-of-date evidence map.
#
#   scripts/build_report.sh            # build report/main.pdf
#   scripts/build_report.sh --clean    # remove build products
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="$ROOT/report"
PY="${PYTHON:-python3}"

if [[ "${1:-}" == "--clean" ]]; then
  (cd "$REPORT" && latexmk -C main.tex)
  exit 0
fi

command -v latexmk >/dev/null || { echo "error: latexmk not found" >&2; exit 2; }

"$PY" "$ROOT/scripts/make_evidence_map.py" --check

cd "$REPORT"
latexmk -pdf -halt-on-error -interaction=nonstopmode -file-line-error main.tex

status=0
if grep -E "There were undefined (references|citations)|Citation .* undefined|Reference .* undefined" main.log; then
  echo "error: undefined references or citations (see report/main.log)" >&2
  status=1
fi
if grep -q "Overfull \\\\hbox" main.log; then
  echo "warning: overfull hboxes present (see report/main.log)" >&2
fi
pages="$(grep -oE 'Output written on main.pdf \(([0-9]+) page' main.log | grep -oE '[0-9]+ page' | grep -oE '[0-9]+' || true)"
echo "built report/main.pdf (${pages:-?} pages)"
exit "$status"
