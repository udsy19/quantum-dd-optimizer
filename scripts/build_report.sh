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
if command -v pdfinfo >/dev/null 2>&1; then
  pages_main="$(pdfinfo main.pdf | awk '/^Pages:/ {print $2}')"
  if [[ "$pages_main" -gt 6 ]]; then
    echo "error: IEEE main report is $pages_main pages (hard maximum: 6, target: 5)" >&2
    status=1
  fi
else
  echo "warning: pdfinfo missing; page count not independently verified" >&2
fi
latexmk -pdf -halt-on-error -interaction=nonstopmode -file-line-error appendix.tex
if grep -E "There were undefined (references|citations)|Citation .* undefined|Reference .* undefined" appendix.log; then
  echo "error: appendix has unresolved cross-references or citations" >&2
  status=1
fi
echo "built report/appendix.pdf (separate supplementary document)"
exit "$status"
