"""Website build (scripts/build_site.py): paper rendered from report/, provenance, links, integrity.

The paper body is converted from report/*.tex with pandoc. When pandoc is not installed locally the
build-dependent tests are skipped with a clear reason; in CI (``CI`` set) a missing pandoc fails.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECIMAL = re.compile(r"-?\d+\.\d+")
HAVE_PANDOC = shutil.which("pandoc") is not None


def _load_builder():
    spec = importlib.util.spec_from_file_location("_build_site", ROOT / "scripts" / "build_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load_builder()

if not HAVE_PANDOC and os.environ.get("CI"):
    pytest.fail("pandoc is required in CI to render the paper from report/ (apt-get install pandoc)",
                pytrace=False)
needs_pandoc = pytest.mark.skipif(not HAVE_PANDOC, reason="pandoc not installed locally; the site renders the "
                                                           "paper from report/ with pandoc (CI installs it)")


def _tree_digest(d: Path, skip: tuple[str, ...] = ()) -> dict:
    return {str(f.relative_to(d)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(d.rglob("*")) if f.is_file() and f.name not in skip}


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    if not HAVE_PANDOC:
        pytest.skip("pandoc not installed locally; the site renders the paper from report/ with pandoc")
    before = _tree_digest(ROOT / "report")
    out = tmp_path_factory.mktemp("site") / "dist"
    info = B.build(out, None)
    assert _tree_digest(ROOT / "report") == before, "the site build must never write into report/"
    return out, info


@pytest.fixture(scope="module")
def macros():
    return B.parse_newcommands((ROOT / "report" / "generated" / "numbers.tex").read_text())


@pytest.fixture(scope="module")
def index(site):
    return (site[0] / "index.html").read_text(encoding="utf-8")


def _part(index: str, part_id: str) -> str:
    start = re.search(rf'<section [^>]*id="{part_id}"', index).start()
    return index[start:index.index("</section>", start)]


def _visible_text(fragment: str) -> str:
    """Text a reader sees before KaTeX runs, with math source and markup removed."""
    s = re.sub(r'<span class="math (?:inline|display)">.*?</span>', " ", fragment, flags=re.S)
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.S)
    return re.sub(r"<[^>]+>", " ", s)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs: list[tuple[str, str, dict]] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        for k in ("href", "src"):
            if a.get(k):
                self.refs.append((tag, a[k], a))


def _parse(html: str) -> _Links:
    p = _Links()
    p.feed(html)
    return p


def test_missing_pandoc_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setattr(B.shutil, "which", lambda name: None)
    with pytest.raises(B.BuildError, match="pandoc is required"):
        B.ReportRenderer(ROOT / "report", {}, {}, "main", [], {})


@needs_pandoc
def test_output_tree(site):
    out, info = site
    for f in ("index.html", "404.html", "robots.txt", "sitemap.xml", ".nojekyll", "assets/og.png",
              "assets/favicon.svg", "assets/style.css", "assets/app.js", "assets/charts.js", "data/numbers.json",
              "data/tables.json", "data/runs.json", "data/build.json", "data/paper.json"):
        assert (out / f).is_file(), f
    index = (out / "index.html").read_text()
    for pdf in ("paper.pdf", "appendix.pdf", "combined_report.pdf"):
        assert not (out / pdf).exists() and f'href="{pdf}"' not in index
    # every macro is re-derived from the checksum-verified payloads before the site is written
    assert info["checked_macros"] == info["macros"] > 100


@needs_pandoc
def test_paper_sections_follow_report_order(index):
    renderer = B.ReportRenderer(ROOT / "report", {}, {}, "main", [], {})
    for part_id, name in (("paper", "main"), ("appendix", "appendix")):
        tex = renderer.read(name)
        titles = [B.tex_to_text(t) for t in re.findall(r"\\section\*?\{([^}]*)\}", tex)]
        assert titles, name
        html_part = _part(index, part_id)
        heads = [re.sub(r"<[^>]+>|\s+", " ", h).strip() for h in re.findall(r"<h2[^>]*>(.*?)</h2>", html_part, re.S)]
        pos = -1
        for t in titles:
            hits = [i for i, h in enumerate(heads) if h.endswith(t)]
            assert hits, (name, t, heads)
            assert hits[0] > pos, (name, "out of order", t)
            pos = hits[0]


@needs_pandoc
def test_front_matter_from_report(index):
    main_tex = (ROOT / "report" / "main.tex").read_text()
    authors = index[index.index('<p class="authors">'):]
    authors = authors[:authors.index("</p>")]
    for name in re.findall(r"\\IEEEauthorblockN\{([^}]*)\}", main_tex):
        assert B.esc(B.tex_to_text(name)) in authors, name
    title = B.tex_to_text(re.split(r"\\\\", re.search(r"\\title\{(.*?)\}\n\\author", main_tex, re.S).group(1))[0])
    assert f"<h1 id=\"paper-title\">{B.esc(title)}</h1>" in index
    abstract = (ROOT / "report" / "sections" / "abstract.tex").read_text()
    first_sentence = B.tex_to_text(re.sub(r"%.*", "", abstract).strip().split(". ")[0])
    abstract_html = index[index.index('<div class="abstract">'):index.index('<p class="keywords">')]
    assert first_sentence.replace("'", "’") in re.sub(r"\s+", " ", _visible_text(abstract_html)), first_sentence
    assert "Index terms" in index and "dynamical decoupling" in index


@needs_pandoc
def test_rendered_tables_figures_math_and_references(index):
    paper, appendix = _part(index, "paper"), _part(index, "appendix")
    assert appendix.count('class="table-figure paper-table"') >= 5
    assert "<thead>" in appendix and "TABLE I." in appendix
    for part in (paper, appendix):
        assert 'class="paper-figure"' in part and 'src="figures/' in part
        assert part.count('class="math inline"') > 20 and 'class="math display"' in part
        assert 'class="references csl-bib-body"' in part
        assert re.search(r'class="citation"[^>]*><a href="#[a-z]+-ref-', part)
    assert "identity-verified (arXiv)" in appendix
    # cross-references resolve to anchors that exist
    ids = _parse(index).ids
    for href in re.findall(r'href="#((?:paper|app)-[^"]+)"', index):
        assert href in ids, href


@needs_pandoc
def test_no_latex_leftovers_and_macros_expanded(index, macros):
    for part_id in ("paper", "appendix"):
        text = _visible_text(_part(index, part_id))
        for bad in ("\\begin{", "\\end{", "\\input", "\\cite", "\\ref{", "\\label", "??", "ZQPROV", "ZQAPPENDIX"):
            assert bad not in text, (part_id, bad)
        assert not re.search(r"\\[A-Za-z]+", text), (part_id, re.findall(r"\\[A-Za-z]+", text)[:5])
    for name in macros:
        assert f"\\{name}" not in index, name


@needs_pandoc
def test_headline_numbers_come_from_numbers_tex(index, macros, site):
    for name in ("FloorA", "BenchASixteenSelEps", "GthreeMaxZ", "SpecGaussFullRmseRatio", "RobBFourBothWorstMax",
                 "RobBFourDDWorst", "ConvValFinal", "ConvTrainFinal", "TestsPassed"):
        assert B.tex_value_html(macros[name]) in index, name
        assert f'data-macro="{name}"' in index
    nums = json.loads((site[0] / "data" / "numbers.json").read_text())
    assert {k: v["tex"] for k, v in nums.items()} == macros
    runs = set(json.loads((ROOT / "report" / "runs.json").read_text()).values())
    spans = re.findall(r'<span class="num"[^>]*data-provenance="([^"]+)"', index)
    assert len(spans) > 30  # includes the macros inside the rendered paper text
    assert set(spans) <= runs


@needs_pandoc
def test_tables_match_generated_latex(site):
    """Every decimal in each site data table equals the corresponding generated LaTeX table."""
    tables = json.loads((site[0] / "data" / "tables.json").read_text())
    tex_files = {"bench": "bench_table.tex", "g3": "g3_table.tex", "spectroscopy": "spectroscopy_table.tex",
                 "robustness": "robustness_table.tex", "ablation": "ablation_table.tex",
                 "model_based": "model_based_table.tex"}
    assert set(tables) == set(tex_files)
    for tid, fn in tex_files.items():
        tex = (ROOT / "report" / "generated" / fn).read_text()
        body = tex.split("\\midrule", 1)[1].split("\\bottomrule", 1)[0]
        want = Counter(DECIMAL.findall(body.replace("--", " ")))
        cells = " ".join(c for r in tables[tid]["rows"] for c in r["cells"]).replace("−", "-")
        got = Counter(DECIMAL.findall(cells))
        assert got == want, (tid, (got - want), (want - got))
        assert all(r["run"] for r in tables[tid]["rows"])


@needs_pandoc
def test_no_placeholder_or_invalid_values(site):
    for f in sorted(site[0].rglob("*")):
        if f.suffix in (".html", ".json", ".xml", ".txt"):
            text = f.read_text(encoding="utf-8")
            for bad in ("NaN", "undefined", "Infinity", "@@"):
                assert bad not in text, (f.name, bad)


@needs_pandoc
def test_local_links_resolve(site):
    out = site[0]
    for page in ("index.html", "404.html"):
        p = _parse((out / page).read_text(encoding="utf-8"))
        for tag, ref, _ in p.refs:
            if ref.startswith(("http://", "https://", "mailto:")):
                continue
            if ref.startswith("#"):
                assert ref == "#" or ref[1:] in p.ids, (page, ref)
                continue
            rel = ref.split("#")[0].split("?")[0]
            if rel.startswith("/"):
                rel = rel[len("/quantum-dd-optimizer/"):] if rel.startswith("/quantum-dd-optimizer/") else rel[1:]
            target = out / rel if rel else out / "index.html"
            if target.is_dir():
                target = target / "index.html"
            assert target.is_file(), (page, ref)


@needs_pandoc
def test_scripts_and_styles_are_self_hosted(index, site):
    p = _parse(index)
    loaded = [(t, r) for t, r, a in p.refs if t == "script" or (t == "link" and a.get("rel") in ("stylesheet", "preload"))]
    assert loaded and not [r for t, r in loaded if "//" in r], loaded
    assert any("vendor/katex/katex.min.js" in r for t, r in loaded)
    for t, r in loaded:
        assert (site[0] / r.split("?")[0]).is_file(), r
    assert "script-src 'self'" in index
    assert "google-analytics" not in index and "gtag(" not in index


@needs_pandoc
def test_status_and_seo(index, site):
    for s in ("Synthetic simulation", "Pre-registered", "No hardware access", "NOT RUN", "Not run",
              'rel="canonical"', 'property="og:image"', 'name="twitter:card"', 'name="description"',
              "CITATION.cff", 'id="figures"', 'data-chart="benchmark"', 'href="#fig-benchmark"'):
        assert s in index, s
    assert "Sitemap: https://udsy19.github.io/quantum-dd-optimizer/sitemap.xml" in (site[0] / "robots.txt").read_text()


@needs_pandoc
def test_pdfs_included_and_build_deterministic(tmp_path, site):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    for name in ("main.pdf", "appendix.pdf", "combined_report.pdf"):
        (pdf_dir / name).write_bytes(b"%PDF-1.4\n%" + name.encode() + b"\n")
    out = tmp_path / "with_pdf"
    B.build(out, pdf_dir)
    index = (out / "index.html").read_text()
    assert (out / "paper.pdf").read_bytes() == (pdf_dir / "main.pdf").read_bytes()
    for href in ("paper.pdf", "appendix.pdf", "combined_report.pdf"):
        assert f'href="{href}"' in index and (out / href).is_file()
    assert "Paper and appendix (PDF)" in index

    pdfs = ("paper.pdf", "appendix.pdf", "combined_report.pdf")
    a, b = _tree_digest(site[0], pdfs), _tree_digest(out, pdfs)
    differing = {k for k in a if a[k] != b.get(k)}
    assert differing <= {"index.html", "sitemap.xml", "data/build.json"}, differing
    again = tmp_path / "again"
    B.build(again, None)
    assert _tree_digest(again) == _tree_digest(site[0])


# ---- data/paper.json: design-independent paper data for any site template ----------------------
@pytest.fixture(scope="module")
def paper_json(site):
    return json.loads((site[0] / "data" / "paper.json").read_text(encoding="utf-8"))


@needs_pandoc
def test_paper_json_schema(paper_json):
    for key in ("title", "subtitle", "authors", "date_line", "keywords", "abstract_html", "sections",
                "references_html", "appendix_title", "appendix_sections", "appendix_references_html", "figures",
                "labels", "source"):
        assert key in paper_json, key
    assert not any(k.startswith("_") for k in paper_json)
    main_tex = (ROOT / "report" / "main.tex").read_text()
    names = [B.tex_to_text(n) for n in re.findall(r"\\IEEEauthorblockN\{([^}]*)\}", main_tex)]
    assert [a["name"] for a in paper_json["authors"]] == names
    assert all(a["affiliations"] and not any("@" in x for x in a["affiliations"]) for a in paper_json["authors"])
    for sec in paper_json["sections"] + paper_json["appendix_sections"]:
        assert set(sec) == {"id", "number", "title", "level", "html"} and sec["level"] in (1, 2) and sec["id"]
    assert 'class="csl-entry"' in paper_json["references_html"]
    assert 'class="csl-entry"' in paper_json["appendix_references_html"]


@needs_pandoc
def test_paper_json_sections_in_report_order(paper_json):
    renderer = B.ReportRenderer(ROOT / "report", {}, {}, "main", [], {})
    for key, name in (("sections", "main"), ("appendix_sections", "appendix")):
        tex = renderer.read(name)
        want = [(1 if kind == "section" else 2, B.tex_to_text(t))
                for kind, t in re.findall(r"\\(section|subsection)\*?\{([^}]*)\}", tex)]
        got = [(s["level"], s["title"]) for s in paper_json[key]]
        assert got == want, (name, got, want)


@needs_pandoc
def test_paper_json_content_is_clean(paper_json, macros):
    fragments = [paper_json["abstract_html"], paper_json["references_html"], paper_json["appendix_references_html"]]
    fragments += [s["html"] for s in paper_json["sections"] + paper_json["appendix_sections"]]
    blob = "\n".join(fragments)
    text = _visible_text(blob)
    for bad in ("\\begin{", "\\end{", "\\input", "\\cite", "\\ref{", "\\label", "??", "ZQPROV", "ZQAPPENDIX"):
        assert bad not in text, bad
    assert not re.search(r"\\[A-Za-z]+", text), re.findall(r"\\[A-Za-z]+", text)[:5]
    for name in macros:
        assert f"\\{name}" not in blob, name
    assert 'data-macro="BenchASixteenSelEps"' in blob  # numbers keep their provenance
    tables = sum(s["html"].count('class="table-figure paper-table"') for s in paper_json["appendix_sections"])
    figures = paper_json["figures"]
    assert tables >= 1 and len(figures) >= 1
    assert {f["part"] for f in figures} == {"paper", "appendix"}
    assert all(f["src"].startswith("figures/") and f["width"] > 0 for f in figures)
