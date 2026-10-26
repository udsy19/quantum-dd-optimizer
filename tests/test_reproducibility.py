"""Tests for ddopt.provenance, configs/ and scripts/make_evidence_map.py (Agent F)."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import socket
import stat
from pathlib import Path

import numpy as np
import pytest

from ddopt import provenance as pv

REPO = Path(__file__).resolve().parents[1]


def _manifest(cfg=None, **kw):
    cfg = {"a": 1, "b": [1.5, 2.5]} if cfg is None else cfg
    return pv.run_manifest(cfg, seeds={"train": [0, 1], "test": [10, 11]}, command=["python", "x.py", "--flag"], **kw)


# --------------------------------------------------------------------- manifest


def test_manifest_has_required_fields():
    m = _manifest(extra={"mc_draws": 8, "assumption": "Gaussian stationary"})
    for key in (
        "manifest_schema_version", "created_utc", "git", "platform", "python", "packages",
        "ddopt_version", "cpu_count", "config", "config_hash", "seeds", "command", "command_str", "extra",
    ):
        assert key in m, key
    assert set(m["git"]) == {"sha", "dirty"}
    assert m["created_utc"].endswith("Z")
    assert set(m["packages"]) == {"numpy", "scipy", "cma", "matplotlib"}
    assert all(isinstance(v, str) and v for v in m["packages"].values())
    assert m["packages"]["numpy"] == np.__version__
    assert m["python"]["version"].count(".") == 2
    assert m["command"] == ["python", "x.py", "--flag"]
    assert m["config_hash"] == pv.config_hash(m["config"])
    assert m["extra"]["mc_draws"] == 8
    json.dumps(m, allow_nan=False)  # strict JSON


def test_manifest_git_sha_recorded_in_checkout():
    sha = pv._git("rev-parse", "HEAD")
    if sha is None:
        pytest.skip("not a git checkout / git unavailable")
    m = _manifest()
    assert m["git"]["sha"] == sha
    assert isinstance(m["git"]["dirty"], bool)


def test_manifest_is_hostname_free():
    text = json.dumps(_manifest())
    host = socket.gethostname()
    if len(host) >= 4:  # avoid false positives on trivial hostnames
        assert host not in text
    assert "hostname" not in text.lower()


def test_missing_package_reports_not_installed():
    assert pv._package_version("surely-not-a-real-package-xyz") == pv.NOT_INSTALLED


def test_manifest_requires_seeds_and_valid_command():
    with pytest.raises(ValueError):
        pv.run_manifest({}, seeds=None, command="x")
    with pytest.raises(TypeError):
        pv.run_manifest({}, seeds=[0], command=[1, 2])
    m = pv.run_manifest({}, seeds=[0], command="python run.py --n 4")
    assert m["command"] == ["python", "run.py", "--n", "4"]


# ------------------------------------------------------------------ hashing/json


def test_config_hash_independent_of_key_order():
    a = {"x": 1, "y": {"p": 2.0, "q": [1, 2, 3]}, "z": "s"}
    b = {"z": "s", "y": {"q": [1, 2, 3], "p": 2.0}, "x": 1}
    assert pv.config_hash(a) == pv.config_hash(b)
    assert len(pv.config_hash(a)) == 64


def test_config_hash_sensitive_to_values_and_list_order():
    base = {"x": 1, "l": [1, 2]}
    assert pv.config_hash(base) != pv.config_hash({"x": 2, "l": [1, 2]})
    assert pv.config_hash(base) != pv.config_hash({"x": 1, "l": [2, 1]})


def test_config_hash_numpy_equivalence():
    assert pv.config_hash({"n": np.int64(4), "w": np.float64(0.5), "v": np.array([1, 2])}) == pv.config_hash(
        {"n": 4, "w": 0.5, "v": [1, 2]}
    )


def test_jsonable_handles_numpy_and_nonfinite():
    out = pv.jsonable(
        {"a": np.arange(3), "b": np.float32(1.5), "c": math.inf, "d": -np.inf, "e": float("nan"),
         "f": np.bool_(True), "g": 1 + 2j, "h": (1, 2), "i": Path("x/y")}
    )
    assert out == {"a": [0, 1, 2], "b": 1.5, "c": "inf", "d": "-inf", "e": "nan", "f": True,
                   "g": {"re": 1.0, "im": 2.0}, "h": [1, 2], "i": "x/y"}
    json.dumps(out, allow_nan=False)
    with pytest.raises(TypeError):
        pv.jsonable(object())


# ------------------------------------------------------------- write/load runs


def test_write_and_load_roundtrip(tmp_path):
    m = _manifest()
    payload = {"infidelity": np.array([1e-3, np.inf]), "n": np.int32(4)}
    run_dir = pv.write_run(tmp_path / "results", "unit", payload, m)
    assert run_dir.parent == tmp_path / "results"
    name, stamp, short = run_dir.name.rsplit("_", 2)
    assert name == "unit" and stamp.endswith("Z") and short == m["config_hash"][:12]
    assert sorted(p.name for p in run_dir.iterdir()) == ["SHA256SUMS", "manifest.json", "payload.json"]
    for p in run_dir.iterdir():
        assert not (p.stat().st_mode & stat.S_IWUSR), f"{p.name} should be read-only"
    run = pv.load_run(run_dir)
    assert run["run_id"] == run_dir.name
    assert run["payload"] == {"infidelity": [1e-3, "inf"], "n": 4}
    assert run["manifest"]["config_hash"] == m["config_hash"]
    assert run["manifest"]["artifacts"]["payload.json"]
    assert "run_id" not in m  # caller's manifest not mutated


def test_sha256sums_format_compatible(tmp_path):
    import hashlib

    run_dir = pv.write_run(tmp_path, "fmt", {"ok": True}, _manifest())
    for line in (run_dir / "SHA256SUMS").read_text().splitlines():
        digest, fn = line.split("  ")
        assert hashlib.sha256((run_dir / fn).read_bytes()).hexdigest() == digest


def test_write_refuses_overwrite(tmp_path):
    m = _manifest()
    first = pv.write_run(tmp_path, "dup", {"v": 1}, m)
    before = (first / "payload.json").read_text()
    with pytest.raises(FileExistsError):
        pv.write_run(tmp_path, "dup", {"v": 2}, m)  # same name/stamp/hash -> same run_id
    assert (first / "payload.json").read_text() == before


@pytest.mark.parametrize("bad", ["", "../escape", "a/b", "x y", "-lead", "a" * 65])
def test_write_rejects_bad_names(tmp_path, bad):
    with pytest.raises(ValueError):
        pv.write_run(tmp_path, bad, {}, _manifest())


def test_write_rejects_manifest_without_hash(tmp_path):
    with pytest.raises(ValueError):
        pv.write_run(tmp_path, "x", {}, {"seeds": [0]})


def _make_writable(run_dir: Path) -> None:
    for p in run_dir.iterdir():
        os.chmod(p, 0o644)


def test_load_detects_tampered_payload(tmp_path):
    run_dir = pv.write_run(tmp_path, "tamper", {"v": 1}, _manifest())
    _make_writable(run_dir)
    (run_dir / "payload.json").write_text('{"v": 2}\n')
    with pytest.raises(pv.ChecksumError):
        pv.load_run(run_dir)


def test_load_detects_tampered_manifest_config(tmp_path):
    run_dir = pv.write_run(tmp_path, "tamper2", {"v": 1}, _manifest())
    _make_writable(run_dir)
    man = json.loads((run_dir / "manifest.json").read_text())
    man["config"]["a"] = 999
    (run_dir / "manifest.json").write_text(json.dumps(man))
    with pytest.raises(pv.ChecksumError):
        pv.load_run(run_dir)


def test_load_detects_missing_and_unlisted_files(tmp_path):
    run_dir = pv.write_run(tmp_path, "files", {"v": 1}, _manifest())
    os.chmod(run_dir, 0o755)
    (run_dir / "extra.csv").write_text("x\n")
    with pytest.raises(pv.ChecksumError, match="not covered"):
        pv.load_run(run_dir)
    (run_dir / "extra.csv").unlink()
    _make_writable(run_dir)
    (run_dir / "SHA256SUMS").unlink()
    with pytest.raises(pv.ChecksumError, match="missing"):
        pv.load_run(run_dir)


# ------------------------------------------------------------------ validation


def test_validate_config_key_list_and_schema():
    pv.validate_config({"a": 1, "b": 2}, ["a", "b"])
    with pytest.raises(pv.ConfigError, match="b: missing"):
        pv.validate_config({"a": 1}, ["a", "b"])
    schema = {"__allow_extra__": False, "__optional__": ["opt"], "n": "int", "w": "float",
              "flag": "bool", "s": {"train": "list[int]"}, "opt": "str"}
    pv.validate_config({"n": 4, "w": 1, "flag": False, "s": {"train": [1, 2]}}, schema)
    with pytest.raises(pv.ConfigError) as ei:
        pv.validate_config({"n": True, "w": "x", "flag": 1, "s": {"train": [1, "2"]}, "zz": 0}, schema)
    msg = str(ei.value)
    for frag in ("n: expected int, got bool", "w: expected float", "flag: expected bool",
                 "s.train[1]", "zz: unknown key"):
        assert frag in msg, frag
    with pytest.raises(pv.ConfigError, match="non-finite"):
        pv.validate_config({"w": math.inf}, {"w": "float"})


def test_disjoint_seed_check():
    pv.check_disjoint_seeds([0, 1, 2], [10, 11])
    with pytest.raises(pv.ConfigError, match="leakage"):
        pv.check_disjoint_seeds([0, 1, 2], [2, 3])
    with pytest.raises(pv.ConfigError, match="duplicate"):
        pv.check_disjoint_seeds([0, 0], [1])


def test_smoke_config_valid_and_hash_stable(tmp_path):
    cfg = pv.load_config(REPO / "configs" / "smoke.json", pv.SMOKE_CONFIG_SCHEMA)
    pv.check_disjoint_seeds(cfg["seeds"]["train"], cfg["seeds"]["test"])
    assert cfg["physics"] is None  # placeholder carries no physics
    reordered = json.loads(json.dumps(cfg, sort_keys=True))
    assert pv.config_hash(cfg) == pv.config_hash(dict(reversed(list(reordered.items()))))
    (tmp_path / "bad.json").write_text('{"x": NaN}')
    with pytest.raises(pv.ConfigError):
        pv.load_config(tmp_path / "bad.json")


# ------------------------------------------------------------- evidence map


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_evidence_map_columns_and_current_claims(tmp_path):
    em = _load_script("make_evidence_map")
    assert em.COLUMNS == ["claim_id", "paper_section", "exact_claim", "provenance_type", "artifact_path",
                          "command", "commit_sha", "run_id", "seed", "reviewer", "verification_status"]
    claims = em.load_claims(REPO / "report" / "claims.json")
    em.validate_claims(claims)
    assert all(c["verification_status"] != "VERIFIED" for c in claims)  # nothing verified yet
    out = tmp_path / "map.csv"
    assert em.main(["--claims", str(REPO / "report" / "claims.json"), "--out", str(out)]) == 0
    assert em.main(["--claims", str(REPO / "report" / "claims.json"), "--out", str(out), "--check"]) == 0
    import csv

    rows = list(csv.DictReader(out.open()))
    assert len(rows) == len(claims) and list(rows[0]) == em.COLUMNS


def test_committed_evidence_map_up_to_date():
    em = _load_script("make_evidence_map")
    assert em.main(["--check"]) == 0


def test_evidence_map_rejects_unsupported_verified_claim():
    em = _load_script("make_evidence_map")
    base = {k: "" for k in em.COLUMNS}
    base.update(claim_id="X-1", exact_claim="Simulation predicts something.", provenance_type="model",
                reviewer="PENDING", verification_status="VERIFIED", artifact_path="results/does_not_exist")
    with pytest.raises(em.ClaimError) as ei:
        em.validate_claims([base])
    msg = str(ei.value)
    assert "does not exist" in msg and "reviewer" in msg and "without command" in msg
    with pytest.raises(em.ClaimError, match="duplicate"):
        em.validate_claims([dict(base, verification_status="PENDING")] * 2)
    with pytest.raises(em.ClaimError, match="provenance_type"):
        em.validate_claims([dict(base, verification_status="PENDING", provenance_type="vibes")])
