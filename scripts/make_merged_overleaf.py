#!/usr/bin/env python3
"""Produce an editable, single-file IEEE report from the canonical split sources.

Main paper, its bibliography, and supplementary experimental results are combined
in one document. The PDF figures remain separate binary assets, delivered by CI
as part of an Overleaf-ready zip.
"""
from __future__ import annotations
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "report"
def inline(source: str, seen: tuple[str,...]=()) -> str:
    def repl(m):
        path = m.group(1).strip()
        if path in seen:
            raise RuntimeError("Recursive input: " + path)
        p = REPORT / (path if path.endswith(".tex") else path + ".tex")
        if not p.exists():
            raise FileNotFoundError(p)
        return "% BEGIN " + path + "\n" + inline(p.read_text(), seen + (path,)) + "\n% END " + path
    return re.sub(r"(?m)^\s*\\input\{([^}]+)\}", repl, source)
def build():
    main = (REPORT / "main.tex").read_text()
    bbl = REPORT / "main.bbl"
    if not bbl.exists():
        raise FileNotFoundError("Build main.pdf first to generate main.bbl")
    main = inline(main)
    main = re.sub(r"\\bibliographystyle\{[^}]+\}\s*\\bibliography\{[^}]+\}",lambda m:bbl.read_text(),main)
    appendix = inline((REPORT / "sections/results_full.tex").read_text())
    # Isolate labels belonging to the appendix and keep cross-references to main sections intact.
    labels = set(re.findall(r"\\label\{([^}]+)\}", appendix))
    for label in sorted(labels, key=len, reverse=True):
        appendix = appendix.replace(r"\label{" + label + "}", r"\label{supp:" + label + "}")
        appendix = appendix.replace(r"\ref{" + label + "}", r"\ref{supp:" + label + "}")
    appendix = appendix.replace(r"\section{Experiments and results}",r"\section{Detailed Synthetic Experiments and Results}")
    appendix = re.sub(r"\\label\{supp:sec:results\}",r"\\label{supp:sec:results}",appendix)
    tail = r"""
\clearpage
\appendices
\renewcommand{\thefigure}{S\arabic{figure}}
\renewcommand{\thetable}{S\arabic{table}}
\renewcommand{\theequation}{S\arabic{equation}}
\setcounter{figure}{0}
\setcounter{table}{0}
\setcounter{equation}{0}
\section*{Supplementary Material}
The following details and additional tables originate from the same
synthetic runs as the main paper. The source artifacts, recorded seeds and
checksum manifests are available in the public repository.
"""
    merged = main.replace(r"\end{document}", tail + "\n" + appendix + "\n" + r"\end{document}")
    # In the standalone Overleaf project, figures are adjacent to merged.tex.
    merged = merged.replace("../figures/","figures/")
    dest = REPORT / "merged.tex"
    dest.write_text("% Auto-generated from canonical report sources. Edit this one file in Overleaf.\n"
                    "% Changes made in Overleaf do not automatically write back to GitHub.\n"+merged)
    assets=REPORT / "figures"
    assets.mkdir(exist_ok=True)
    for fig in (ROOT / "figures").glob("*.pdf"):
        shutil.copy2(fig,assets / fig.name)
    return dest

if __name__=="__main__":
    print(build())
