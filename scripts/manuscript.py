#!/usr/bin/env python3
"""Tooling for the single canonical manuscript ``report/merged.tex``.

``report/merged.tex`` is the one human-edited source of the IEEE paper and its supplement
(see the contract in ``docs/LATEX_OVERLEAF_AGENT_GUIDE.md``). This script never rewrites it,
except for ``sync-generated --write``, which replaces only the text between the
``% >>> BEGIN GENERATED`` / ``% <<< END GENERATED`` markers with the contents of the
corresponding ``report/generated/*.tex`` file.

Subcommands (stdlib only; ``split`` needs poppler's pdfinfo/pdfseparate/pdfunite):

  check                 pure-text consistency checks; exit 1 with messages on failure
  sync-generated        show the diff that would refresh generated blocks; exit 1 if any
      [--write]         ... and apply it (only marker-delimited content is rewritten)
  check-log LOG         fail on undefined references/citations or missing files in a LaTeX log
  split                 split merged.pdf into main.pdf / appendix.pdf at \\label{supp:start}
  zip                   deterministic Overleaf project zip (merged.tex, refs.bib, used figures)

All paths default to the repository containing this script; ``--root`` selects another tree.
"""
from __future__ import annotations

import argparse
import difflib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]

CANONICAL_PREFIX = "% CANONICAL MANUSCRIPT:"
BIB_STYLE_LINE = r"\bibliographystyle{IEEEtranN}"
BIB_LINE = r"\IfFileExists{refs.bib}{\bibliography{refs}}{\bibliography{report/refs}}"
GENERATED_HEADER_PREFIX = "% GENERATED"

BEGIN_RE = re.compile(r"^% >>> BEGIN GENERATED (\S+)(?:\s.*)?$")
END_RE = re.compile(r"^% <<< END GENERATED (\S+)\s*$")
ANY_MARKER_RE = re.compile(r"^\s*%\s*(>>>|<<<)")

INPUT_RE = re.compile(r"\\(input|include|includeonly|subfile|import|subimport|inputfrom|includefrom)(?![A-Za-z@])")
LABEL_RE = re.compile(r"\\label\s*\{([^{}]*)\}")
REF_RE = re.compile(r"\\(ref|eqref|pageref|autoref|nameref|vref|cref|Cref|cpageref|Cpageref)\*?\s*\{([^{}]*)\}")
CITE_RE = re.compile(r"\\((?:no)?cite[A-Za-z]*)\*?\s*(?:\[[^\]]*\]\s*){0,2}\{([^{}]*)\}")
GRAPHICS_RE = re.compile(r"\\includegraphics\s*\*?\s*(?:\[[^\]]*\]\s*)?\{([^{}]*)\}")
SUPP_USE_RE = re.compile(r"\\ddoptsupplement\s*\{")
BIBENTRY_RE = re.compile(r"@\s*([A-Za-z]+)\s*[{(]\s*([^,\s]+)\s*,")
GRAPHIC_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".eps")

README_TXT = """\
Overleaf project for the quantum-dd-optimizer IEEE midterm report.

* In Overleaf, set merged.tex as the main document (Menu -> Main document).
* merged.tex is the canonical manuscript; it lives in the GitHub repository at
  report/merged.tex. This zip is a snapshot built by CI; edits made in Overleaf are
  NOT synchronized automatically. Port them back to report/merged.tex via a GitHub
  commit / pull request (or Overleaf's GitHub integration, pushing to a branch).
* Blocks between "% >>> BEGIN GENERATED" and "% <<< END GENERATED" are produced by
  scripts/make_report_artifacts.py; do not edit them by hand.
"""


class ManuscriptError(Exception):
    pass


# --------------------------------------------------------------------------- helpers
def paths(root: Path) -> dict[str, Path]:
    report = root / "report"
    return {
        "root": root,
        "report": report,
        "tex": report / "merged.tex",
        "bib": report / "refs.bib",
        "generated": report / "generated",
        "figures": root / "figures",
    }


def strip_comments(text: str) -> str:
    """Remove LaTeX comments (unescaped % to end of line), keeping line structure."""
    out = []
    for line in text.split("\n"):
        m = re.search(r"(?<!\\)(?:\\\\)*%", line)
        out.append(line[: m.start() + (len(m.group(0)) - 1)] if m else line)
    return "\n".join(out)


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def bib_keys(bib_text: str) -> set[str]:
    return {key for kind, key in BIBENTRY_RE.findall(bib_text)
            if kind.lower() not in {"string", "comment", "preamble"}}


def expected_block(gen_file: Path) -> str:
    """Contents of a generated file minus its '% GENERATED' header, ending in exactly one newline."""
    text = gen_file.read_text(encoding="utf-8")
    first, _, rest = text.partition("\n")
    if not first.startswith(GENERATED_HEADER_PREFIX):
        raise ManuscriptError(f"{gen_file}: first line is not a '{GENERATED_HEADER_PREFIX} ...' header")
    rest = rest.rstrip("\n")
    return rest + "\n" if rest else ""


@dataclass
class Block:
    name: str          # e.g. report/generated/numbers.tex
    begin: int         # index of BEGIN marker line
    end: int           # index of END marker line
    content: str       # text strictly between the markers (each line keeps its '\n')


def parse_blocks(lines: list[str]) -> tuple[list[Block], list[str]]:
    """Parse generated blocks from ``lines`` (with line endings). Returns (blocks, errors)."""
    blocks: list[Block] = []
    errors: list[str] = []
    open_name: str | None = None
    open_idx = -1
    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        b, e = BEGIN_RE.match(line), END_RE.match(line)
        if b:
            if open_name is not None:
                errors.append(f"line {i + 1}: BEGIN GENERATED {b.group(1)} inside open block "
                              f"{open_name} (opened at line {open_idx + 1})")
            open_name, open_idx = b.group(1), i
        elif e:
            if open_name is None:
                errors.append(f"line {i + 1}: END GENERATED {e.group(1)} without matching BEGIN")
            elif e.group(1) != open_name:
                errors.append(f"line {i + 1}: END GENERATED {e.group(1)} does not match "
                              f"BEGIN GENERATED {open_name} at line {open_idx + 1}")
                open_name = None
            else:
                blocks.append(Block(open_name, open_idx, i, "".join(lines[open_idx + 1:i])))
                open_name = None
        elif ANY_MARKER_RE.match(line) and "GENERATED" in line:
            errors.append(f"line {i + 1}: malformed GENERATED marker: {line!r}")
    if open_name is not None:
        errors.append(f"line {open_idx + 1}: BEGIN GENERATED {open_name} is never closed")
    return blocks, errors


def normalize_block(s: str) -> str:
    s = s.rstrip("\n")
    return s + "\n" if s else ""


def resolve_generated(root: Path, name: str) -> Path:
    p = (root / name).resolve()
    gen = paths(root)["generated"].resolve()
    if p.parent != gen or p.suffix != ".tex":
        raise ManuscriptError(f"generated block names {name!r}, which is not report/generated/<name>.tex")
    return p


def resolve_figure(root: Path, name: str) -> Path | None:
    figs = paths(root)["figures"]
    cands = [name] if Path(name).suffix else [name + ext for ext in GRAPHIC_EXTS]
    for c in cands:
        p = figs / c
        if p.is_file():
            return p
    return None


def referenced_figures(text: str) -> list[str]:
    return [m.group(1).strip() for m in GRAPHICS_RE.finditer(strip_comments(text)) if "#" not in m.group(1)]


# --------------------------------------------------------------------------- check
def check(root: Path) -> list[str]:
    P = paths(root)
    errs: list[str] = []
    tex_path = P["tex"]
    if not tex_path.is_file():
        return [f"{tex_path} does not exist"]
    text = tex_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    body = strip_comments(text)

    # header
    if not lines or not lines[0].startswith(CANONICAL_PREFIX):
        errs.append(f"line 1: must start with '{CANONICAL_PREFIX}' (canonical manuscript header)")
    if len(re.findall(r"\\documentclass", body)) != 1:
        errs.append("merged.tex must contain exactly one \\documentclass")

    # no external TeX dependencies
    for m in INPUT_RE.finditer(body):
        errs.append(f"line {line_of(body, m.start())}: \\{m.group(1)} is not allowed "
                    "(merged.tex must be self-contained)")

    # generated blocks
    blocks, berrs = parse_blocks(lines)
    errs.extend(berrs)
    gen_dir = P["generated"]
    gen_files = sorted(p.name for p in gen_dir.glob("*.tex")) if gen_dir.is_dir() else []
    seen: dict[str, int] = {}
    for blk in blocks:
        seen[blk.name] = seen.get(blk.name, 0) + 1
        try:
            gfile = resolve_generated(root, blk.name)
        except ManuscriptError as e:
            errs.append(f"line {blk.begin + 1}: {e}")
            continue
        if not gfile.is_file():
            errs.append(f"line {blk.begin + 1}: generated block {blk.name} has no source file")
            continue
        try:
            want = expected_block(gfile)
        except ManuscriptError as e:
            errs.append(str(e))
            continue
        if normalize_block(blk.content) != want:
            diff = "".join(difflib.unified_diff(
                want.splitlines(keepends=True), normalize_block(blk.content).splitlines(keepends=True),
                fromfile=blk.name, tofile=f"report/merged.tex (block at line {blk.begin + 1})"))
            errs.append(f"line {blk.begin + 1}: generated block {blk.name} diverges from its source "
                        "(run: python scripts/manuscript.py sync-generated --write)\n" + diff)
    for name, n in seen.items():
        if n > 1:
            errs.append(f"generated block {name} is embedded {n} times (must be exactly once)")
    for g in gen_files:
        if f"report/generated/{g}" not in seen:
            errs.append(f"report/generated/{g} is not embedded in merged.tex")

    # labels / references
    labels: dict[str, int] = {}
    for m in LABEL_RE.finditer(body):
        lab = m.group(1).strip()
        if "#" in lab:
            continue
        ln = line_of(body, m.start())
        if lab in labels:
            errs.append(f"line {ln}: duplicate \\label{{{lab}}} (first at line {labels[lab]})")
        else:
            labels[lab] = ln
    for m in REF_RE.finditer(body):
        for lab in (x.strip() for x in m.group(2).split(",")):
            if lab and "#" not in lab and lab not in labels:
                errs.append(f"line {line_of(body, m.start())}: \\{m.group(1)}{{{lab}}} refers to an undefined label")

    # citations
    keys = bib_keys(P["bib"].read_text(encoding="utf-8")) if P["bib"].is_file() else set()
    if not P["bib"].is_file():
        errs.append(f"{P['bib']} does not exist")
    for m in CITE_RE.finditer(body):
        for key in (x.strip() for x in m.group(2).split(",")):
            if key and key != "*" and "#" not in key and key not in keys:
                errs.append(f"line {line_of(body, m.start())}: \\{m.group(1)}{{{key}}}: key not in report/refs.bib")

    # figures
    for m in GRAPHICS_RE.finditer(body):
        name = m.group(1).strip()
        if "#" in name:
            continue
        ln = line_of(body, m.start())
        if "/" in name:
            errs.append(f"line {ln}: \\includegraphics{{{name}}}: use the bare file name (\\graphicspath finds figures/)")
        elif resolve_figure(root, name) is None:
            errs.append(f"line {ln}: \\includegraphics{{{name}}}: no such file in figures/")
    if GRAPHICS_RE.search(body) and r"\graphicspath{{figures/}{../figures/}}" not in body:
        errs.append("preamble must contain \\graphicspath{{figures/}{../figures/}}")

    # bibliography + supplement
    body_lines = [ln.strip() for ln in body.split("\n")]
    style_idx = [i for i, ln in enumerate(body_lines) if ln == BIB_STYLE_LINE]
    bib_idx = [i for i, ln in enumerate(body_lines) if ln == BIB_LINE]
    if len(style_idx) != 1:
        errs.append(f"expected exactly one line '{BIB_STYLE_LINE}' (found {len(style_idx)})")
    if len(bib_idx) != 1:
        errs.append(f"expected exactly one bibliography line '{BIB_LINE}' (found {len(bib_idx)})")
    n_bib = len(re.findall(r"\\bibliography\s*\{", body))
    if bib_idx and n_bib != 2:
        errs.append("no \\bibliography{...} is allowed besides the contract bibliography line")
    supp = list(SUPP_USE_RE.finditer(body))
    if len(supp) != 1:
        errs.append(f"\\ddoptsupplement{{...}} must be used exactly once (found {len(supp)})")
    else:
        supp_line = line_of(body, supp[0].start())
        if bib_idx and supp_line <= bib_idx[0] + 1:
            errs.append(f"line {supp_line}: \\ddoptsupplement must come after the bibliography line "
                        f"(line {bib_idx[0] + 1})")
        end_doc = body.find(r"\end{document}")
        if end_doc != -1 and supp[0].start() > end_doc:
            errs.append(f"line {supp_line}: \\ddoptsupplement is after \\end{{document}}")
    if not re.search(r"\\newcommand\s*\{?\\ddoptsupplement\}?", body):
        errs.append("preamble must define \\ddoptsupplement via \\newcommand")
    if "supp:start" not in labels:
        errs.append("\\label{supp:start} is not defined (the \\ddoptsupplement definition must write it)")
    return errs


# --------------------------------------------------------------------------- sync
def sync_text(root: Path, text: str) -> str:
    lines = text.splitlines(keepends=True)
    blocks, berrs = parse_blocks(lines)
    if berrs:
        raise ManuscriptError("malformed generated markers:\n  " + "\n  ".join(berrs))
    out = list(lines)
    for blk in sorted(blocks, key=lambda b: b.begin, reverse=True):
        gfile = resolve_generated(root, blk.name)
        if not gfile.is_file():
            raise ManuscriptError(f"line {blk.begin + 1}: generated block {blk.name} has no source file")
        want = expected_block(gfile)
        if normalize_block(blk.content) != want:
            out[blk.begin + 1:blk.end] = want.splitlines(keepends=True)
    return "".join(out)


def cmd_sync(root: Path, write: bool) -> int:
    tex = paths(root)["tex"]
    text = tex.read_text(encoding="utf-8")
    new = sync_text(root, text)
    if new == text:
        print("generated blocks are up to date")
        return 0
    sys.stdout.writelines(difflib.unified_diff(
        text.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile="report/merged.tex", tofile="report/merged.tex (synced)"))
    if write:
        tex.write_text(new, encoding="utf-8")
        print("updated generated blocks in report/merged.tex")
        return 0
    print("generated blocks are out of date (apply with --write)", file=sys.stderr)
    return 1


# --------------------------------------------------------------------------- logs
LOG_PATTERNS = [
    re.compile(r"There were undefined (references|citations)"),
    re.compile(r"(Citation|Reference) `[^']*' (on page \d+ )?undefined"),
    re.compile(r"LaTeX Warning: File `[^']*' not found"),
    re.compile(r"File `[^']*' not found"),
    re.compile(r"Empty `thebibliography' environment"),
    # duplicate hyperref anchors make PDF links jump to the wrong float (e.g. Fig. S1 -> Fig. 1)
    re.compile(r"destination with the same identifier"),
]


def check_log(log: Path) -> list[str]:
    hits = []
    for i, line in enumerate(log.read_text(encoding="latin-1").splitlines(), 1):
        if any(p.search(line) for p in LOG_PATTERNS):
            hits.append(f"{log.name}:{i}: {line.strip()}")
    blg = log.with_suffix(".blg")
    if blg.is_file():
        for i, line in enumerate(blg.read_text(encoding="latin-1").splitlines(), 1):
            if "I didn't find a database entry" in line or "I couldn't open" in line:
                hits.append(f"{blg.name}:{i}: {line.strip()}")
    return hits


# --------------------------------------------------------------------------- split
def brace_groups(s: str, n: int) -> list[str]:
    """Return the first ``n`` top-level {...} groups of ``s``."""
    groups, depth, start = [], 0, -1
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                groups.append(s[start:i])
                if len(groups) == n:
                    break
    return groups


def supp_start_page(aux: Path, label: str = "supp:start") -> int:
    prefix = "\\newlabel{" + label + "}"
    for line in aux.read_text(encoding="latin-1").splitlines():
        if line.startswith(prefix):
            outer = brace_groups(line[len(prefix):], 1)
            fields = brace_groups(outer[0], 2) if outer else []
            if len(fields) < 2 or not fields[1].strip().isdigit():
                raise ManuscriptError(f"{aux}: cannot parse page of {label}: {line!r}")
            return int(fields[1])
    raise ManuscriptError(f"{aux}: \\newlabel{{{label}}} not found (is \\ddoptsupplement used?)")


def pdf_pages(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], check=True, capture_output=True, text=True).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    if not m:
        raise ManuscriptError(f"pdfinfo reported no page count for {pdf}")
    return int(m.group(1))


def extract_pages(src: Path, first: int, last: int, dest: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        # poppler prints harmless "Syntax Warning"s for some embedded figures; show them only on failure
        r = subprocess.run(["pdfseparate", "-f", str(first), "-l", str(last), str(src),
                            str(Path(td) / "p-%d.pdf")], capture_output=True, text=True)
        if r.returncode:
            raise ManuscriptError(f"pdfseparate failed on {src}:\n{r.stderr}")
        pages = [str(Path(td) / f"p-{i}.pdf") for i in range(first, last + 1)]
        tmp_out = Path(td) / "out.pdf"
        if len(pages) == 1:
            shutil.copyfile(pages[0], tmp_out)
        else:
            r = subprocess.run(["pdfunite", *pages, str(tmp_out)], capture_output=True, text=True)
            if r.returncode:
                raise ManuscriptError(f"pdfunite failed:\n{r.stderr}")
        shutil.copyfile(tmp_out, dest)


def cmd_split(pdf: Path, aux: Path, main: Path, supp: Path, max_main: int) -> int:
    for tool in ("pdfinfo", "pdfseparate", "pdfunite"):
        if shutil.which(tool) is None:
            raise ManuscriptError(f"{tool} not found (install poppler-utils)")
    total = pdf_pages(pdf)
    p = supp_start_page(aux)
    if not 2 <= p <= total:
        raise ManuscriptError(f"supplement start page {p} outside 2..{total}")
    extract_pages(pdf, 1, p - 1, main)
    extract_pages(pdf, p, total, supp)
    n_main, n_supp = pdf_pages(main), pdf_pages(supp)
    print(f"split {pdf.name}: {total} pages -> {main.name} {n_main} pages (1-{p - 1}), "
          f"{supp.name} {n_supp} pages ({p}-{total})")
    status = 0
    if n_main + n_supp != total:
        print(f"error: {n_main} + {n_supp} != {total} pages", file=sys.stderr)
        status = 1
    if n_main > max_main:
        print(f"error: main paper is {n_main} pages (hard maximum: {max_main})", file=sys.stderr)
        status = 1
    return status


# --------------------------------------------------------------------------- zip
ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def zip_members(root: Path, readme: bool = True) -> list[tuple[str, bytes]]:
    P = paths(root)
    text = P["tex"].read_text(encoding="utf-8")
    members: dict[str, bytes] = {
        "merged.tex": P["tex"].read_bytes(),
        "refs.bib": P["bib"].read_bytes(),
    }
    for name in referenced_figures(text):
        f = resolve_figure(root, name) if "/" not in name else None
        if f is None:
            raise ManuscriptError(f"\\includegraphics{{{name}}}: no such file in figures/")
        members["figures/" + f.name] = f.read_bytes()
    if readme:
        members["README.txt"] = README_TXT.encode()
    return sorted(members.items())


def cmd_zip(root: Path, out: Path, readme: bool) -> int:
    members = zip_members(root, readme)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3
            z.writestr(info, data, compresslevel=9)
    tmp.replace(out)
    print(f"wrote {out} ({len(members)} files: {', '.join(n for n, _ in members)})")
    return 0


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="repository root (default: this repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="text checks of report/merged.tex")
    s = sub.add_parser("sync-generated", help="refresh generated blocks from report/generated/*.tex")
    s.add_argument("--write", action="store_true", help="apply the update (default: diff only, exit 1 if stale)")
    s = sub.add_parser("check-log", help="fail on undefined refs/citations or missing files in a LaTeX log")
    s.add_argument("log", type=Path)
    s = sub.add_parser("split", help="split merged.pdf into main and supplement PDFs")
    s.add_argument("--pdf", type=Path, default=Path("report/merged.pdf"))
    s.add_argument("--aux", type=Path, default=Path("report/merged.aux"))
    s.add_argument("--main", type=Path, default=Path("report/main.pdf"))
    s.add_argument("--supp", type=Path, default=Path("report/appendix.pdf"))
    s.add_argument("--max-main-pages", type=int, default=6)
    s = sub.add_parser("zip", help="build the Overleaf project zip")
    s.add_argument("--out", type=Path, default=Path("report/overleaf-project.zip"))
    s.add_argument("--no-readme", action="store_true", help="omit README.txt")
    a = ap.parse_args(argv)
    root = a.root.resolve()
    try:
        if a.cmd == "check":
            errs = check(root)
            for e in errs:
                print("error: " + e, file=sys.stderr)
            if errs:
                print(f"manuscript check FAILED ({len(errs)} problem(s)) in {paths(root)['tex']}", file=sys.stderr)
                return 1
            print(f"manuscript check passed: {paths(root)['tex']}")
            return 0
        if a.cmd == "sync-generated":
            return cmd_sync(root, a.write)
        if a.cmd == "check-log":
            hits = check_log(a.log)
            for h in hits:
                print("error: " + h, file=sys.stderr)
            return 1 if hits else 0
        if a.cmd == "split":
            return cmd_split(a.pdf, a.aux, a.main, a.supp, a.max_main_pages)
        if a.cmd == "zip":
            return cmd_zip(root, a.out, not a.no_readme)
    except (ManuscriptError, OSError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
