"""Run the full pytest suite and store the outcome as an immutable run (junit XML + counts).

Usage: python scripts/run_tests_recorded.py
"""
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from ddopt.provenance import git_state, run_manifest, write_run

ROOT = Path(__file__).resolve().parents[1]


def main():
    git_at_start = git_state()
    with tempfile.TemporaryDirectory() as d:
        xml = Path(d) / "junit.xml"
        t0 = time.time()
        p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rs", f"--junitxml={xml}"], cwd=ROOT,
                           capture_output=True, text=True)
        root = ET.parse(xml).getroot()
        ts = root if root.tag == "testsuite" else root.find("testsuite")
        counts = {k: int(ts.get(k, 0)) for k in ("tests", "failures", "errors", "skipped")}
        counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
        skipped = [tc.get("classname") + "::" + tc.get("name") + " -- " + (tc.find("skipped").get("message") or "")
                   for tc in ts.iter("testcase") if tc.find("skipped") is not None]
        payload = {"counts": counts, "returncode": p.returncode, "skipped": skipped,
                   "stdout_tail": p.stdout[-4000:], "wall_time_s": time.time() - t0}
    man = run_manifest({"suite": "pytest full"}, seeds=[], command=sys.argv,
                       extra={"git_at_start": git_at_start})
    print(counts, "->", write_run(ROOT / "results", "test_suite", payload, man))
    return 0 if p.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
