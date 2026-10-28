#!/usr/bin/env bash
# Build the IEEE report from the single canonical manuscript report/merged.tex.
#
#   scripts/build_report.sh            # build and verify all report outputs
#   scripts/build_report.sh --clean    # remove build products
#
# Outputs (all untracked, see .gitignore), in report/:
#   merged.pdf            compiled from merged.tex (main paper + supplement)
#   combined_report.pdf   byte copy of merged.pdf (final submission PDF)
#   main.pdf              pages 1..p-1 (p = page of \label{supp:start}); hard max 6 pages
#   appendix.pdf          pages p..N (supplement)
#   overleaf-project.zip  merged.tex + refs.bib + referenced figures (+ README.txt)
#
# Fails on: evidence-map drift, manuscript check failure, LaTeX errors, undefined references or
# citations, missing files, main paper > 6 pages, the unzipped Overleaf project not compiling
# standalone, or merged.tex not compiling from the repository root (Overleaf root-relative paths).
# This script never modifies report/merged.tex or any other tracked file.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPORT="$ROOT/report"
PY="${PYTHON:-python3}"
MS=("$PY" "$ROOT/scripts/manuscript.py" --root "$ROOT")
MAX_MAIN_PAGES=6
LATEXMK=(latexmk -pdf -halt-on-error -interaction=nonstopmode -file-line-error)

if [[ "${1:-}" == "--clean" ]]; then
  (cd "$REPORT" && latexmk -C merged.tex >/dev/null 2>&1 || true)
  rm -f "$REPORT"/{merged,main,appendix,combined_report}.pdf "$REPORT/merged.bbl" "$REPORT/overleaf-project.zip"
  exit 0
fi

for tool in latexmk pdfinfo pdfseparate pdfunite unzip; do
  command -v "$tool" >/dev/null || { echo "error: $tool not found" >&2; exit 2; }
done

src_hash() { sha256sum "$REPORT/merged.tex" | cut -d' ' -f1; }
before="$(src_hash)"

"$PY" "$ROOT/scripts/make_evidence_map.py" --check
"${MS[@]}" check

# 1. Compile the canonical manuscript in report/.
(cd "$REPORT" && "${LATEXMK[@]}" merged.tex)
"${MS[@]}" check-log "$REPORT/merged.log" || {
  echo "error: undefined references/citations or missing files (see report/merged.log)" >&2; exit 1; }
if grep -q "destination with the same identifier" "$REPORT/merged.log"; then
  echo "warning: duplicate hyperref destinations (PDF links may jump to the wrong float; see report/merged.log)" >&2
fi
if grep -q "Overfull \\\\hbox" "$REPORT/merged.log"; then
  echo "warning: overfull hboxes present (see report/merged.log)" >&2
fi

# 2. Split at \label{supp:start}; combined_report.pdf is the unsplit PDF.
"${MS[@]}" split --pdf "$REPORT/merged.pdf" --aux "$REPORT/merged.aux" \
  --main "$REPORT/main.pdf" --supp "$REPORT/appendix.pdf" --max-main-pages "$MAX_MAIN_PAGES"
cp "$REPORT/merged.pdf" "$REPORT/combined_report.pdf"
pages() { pdfinfo "$1" | awk '/^Pages:/ {print $2}'; }
n_all="$(pages "$REPORT/combined_report.pdf")"
n_main="$(pages "$REPORT/main.pdf")"
n_supp="$(pages "$REPORT/appendix.pdf")"
if [[ "$n_all" -ne "$((n_main + n_supp))" ]]; then
  echo "error: combined PDF has $n_all pages, main + supplement = $((n_main + n_supp))" >&2; exit 1
fi
if [[ "$n_main" -gt "$MAX_MAIN_PAGES" ]]; then
  echo "error: IEEE main paper is $n_main pages (hard maximum: $MAX_MAIN_PAGES, target: 5)" >&2; exit 1
fi

# 3. Overleaf project zip, then prove it compiles standalone.
"${MS[@]}" zip --out "$REPORT/overleaf-project.zip"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/zip"
unzip -q "$REPORT/overleaf-project.zip" -d "$TMP/zip"
if ! (cd "$TMP/zip" && "${LATEXMK[@]}" merged.tex >"$TMP/zip.out" 2>&1); then
  tail -n 40 "$TMP/zip.out" >&2
  echo "error: the unzipped Overleaf project does not compile standalone" >&2; exit 1
fi
"${MS[@]}" check-log "$TMP/zip/merged.log" || {
  echo "error: the unzipped Overleaf project has unresolved references/citations or missing files" >&2; exit 1; }

# 4. Compile from the repository root (Overleaf resolves paths relative to the project root).
mkdir -p "$TMP/repo/report"
cp "$REPORT/merged.tex" "$REPORT/refs.bib" "$TMP/repo/report/"
cp -r "$ROOT/figures" "$TMP/repo/figures"
if ! (cd "$TMP/repo" && "${LATEXMK[@]}" report/merged.tex >"$TMP/root.out" 2>&1); then
  tail -n 40 "$TMP/root.out" >&2
  echo "error: report/merged.tex does not compile from the repository root" >&2; exit 1
fi
"${MS[@]}" check-log "$TMP/repo/merged.log" || {
  echo "error: root-relative build has unresolved references/citations or missing files" >&2; exit 1; }

if [[ "$(src_hash)" != "$before" ]]; then
  echo "error: report/merged.tex changed during the build (the build must never write it)" >&2; exit 1
fi
echo "outputs: report/merged.pdf report/combined_report.pdf report/main.pdf report/appendix.pdf report/overleaf-project.zip"
echo "built report/combined_report.pdf ($n_all pages; main $n_main, supplement $n_supp)"
