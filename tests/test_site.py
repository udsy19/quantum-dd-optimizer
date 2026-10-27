"""Website build (scripts/build_site.py): artifact-traceable numbers, links and integrity."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DECIMAL = re.compile(r"-?\d+\.\d+")


def _load_builder():
    spec = importlib.util.spec_from_file_location("_build_site", ROOT / "scripts" / "build_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load_builder()


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site") / "dist"
    info = B.build(out, None)
    return out, info


@pytest.fixture(scope="module")
def macros():
    return B.parse_newcommands((ROOT / "report" / "generated" / "numbers.tex").read_text())


@pytest.fixture(scope="module")
def index(site):
    return (site[0] / "index.html").read_text(encoding="utf-8")


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


def test_output_tree(site):
    out, info = site
    for f in ("index.html", "404.html", "robots.txt", "sitemap.xml", ".nojekyll", "assets/og.png",
              "assets/favicon.svg", "assets/style.css", "assets/app.js", "assets/charts.js", "data/numbers.json",
              "data/tables.json", "data/runs.json", "data/build.json"):
        assert (out / f).is_file(), f
    assert not (out / "paper.pdf").exists() and "paper.pdf" not in (out / "index.html").read_text()
    # every macro is re-derived from the checksum-verified payloads before the site is written
    assert info["checked_macros"] == info["macros"] > 100


def test_headline_numbers_come_from_numbers_tex(index, macros, site):
    for name in ("FloorA", "BenchASixteenSelEps", "GthreeMaxZ", "SpecGaussFullRmseRatio", "RobBFourBothWorstMax",
                 "RobBFourDDWorst", "ConvValFinal", "ConvTrainFinal", "BenchBFourBothRatioLo", "TestsPassed"):
        assert B.tex_value_html(macros[name]) in index, name
        assert f'data-macro="{name}"' in index
    nums = json.loads((site[0] / "data" / "numbers.json").read_text())
    assert {k: v["tex"] for k, v in nums.items()} == macros
    runs = set(json.loads((ROOT / "report" / "runs.json").read_text()).values())
    for m in re.finditer(r'<span class="num"[^>]*data-provenance="([^"]+)"', index):
        assert m.group(1) in runs
    assert "1.00×10<sup>−2</sup>" in index  # XY8 at n = 16 (rendered macro)


def test_tables_match_generated_latex(site):
    """Every decimal in each site table equals the corresponding generated LaTeX table."""
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


def test_no_placeholder_or_invalid_values(site):
    for f in sorted(site[0].rglob("*")):
        if f.suffix in (".html", ".json", ".xml", ".txt"):
            text = f.read_text(encoding="utf-8")
            for bad in ("NaN", "undefined", "Infinity", "@@"):
                assert bad not in text, (f.name, bad)


def test_local_links_resolve(site, index):
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


def test_external_scripts_are_pinned_with_sri(index):
    p = _parse(index)
    ext = [(t, r, a) for t, r, a in p.refs if r.startswith("https://") and t in ("script", "link")
           and (t == "script" or a.get("rel") == "stylesheet")]
    katex = [x for x in ext if "katex" in x[1]]
    assert len(katex) == 2
    for tag, ref, a in katex:
        assert re.search(r"katex@\d+\.\d+\.\d+/", ref), ref
        assert a.get("integrity", "").startswith("sha384-") and a.get("crossorigin") == "anonymous", ref
    for tag, ref, a in ext:
        if tag == "script":
            assert a.get("integrity"), ref
    assert "google-analytics" not in index and "gtag(" not in index


def test_status_and_seo(index, site):
    for s in ("Synthetic simulation", "Pre-registered", "No hardware data", "Results negative",
              "Christian De Zabala F. · Madeline Feldner · Zarar Haider · Udaya Vijay Anand", "NOT RUN", 'rel="canonical"', 'property="og:image"',
              'name="twitter:card"', 'name="description"', "identity-verified (arXiv)", "CITATION.cff"):
        assert s in index, s
    assert "Sitemap: https://udsy19.github.io/quantum-dd-optimizer/sitemap.xml" in (site[0] / "robots.txt").read_text()


def test_pdf_included_and_build_deterministic(tmp_path, site):
    fake = tmp_path / "main.pdf"
    fake.write_bytes(b"%PDF-1.4\n%test\n")
    out = tmp_path / "with_pdf"
    B.build(out, fake)
    assert (out / "paper.pdf").read_bytes() == fake.read_bytes()
    assert 'href="paper.pdf"' in (out / "index.html").read_text()

    def digest(d: Path) -> dict:
        return {str(f.relative_to(d)): hashlib.sha256(f.read_bytes()).hexdigest()
                for f in sorted(d.rglob("*")) if f.is_file() and f.name != "paper.pdf"}
    a, b = digest(site[0]), digest(out)
    # identical apart from the PDF link/sitemap entry and build.json's pdf flag
    differing = {k for k in a if a[k] != b.get(k)}
    assert differing <= {"index.html", "sitemap.xml", "data/build.json"}, differing
    again = tmp_path / "again"
    B.build(again, None)
    assert digest(again) == a
