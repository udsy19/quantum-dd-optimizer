"""Run provenance: manifests, immutable result directories and config validation.

Owner: Agent F (reproducibility).  Public API (see ``docs/INTERFACES.md``)::

    run_manifest(config, *, seeds, command, extra=None) -> dict
    write_run(out_dir, name, payload, manifest) -> Path
    load_run(path) -> dict
    config_hash(cfg) -> str
    validate_config(cfg, required_keys) -> dict

Design rules
------------
* A run directory ``<out_dir>/<run_id>/`` is written **once**.  ``write_run`` refuses
  to touch an existing directory; there is no mutable "latest" result.
* ``run_id = <name>_<UTC stamp>_<first 12 hex chars of config hash>``.
* Every run directory contains ``payload.json``, ``manifest.json`` and ``SHA256SUMS``
  (``sha256sum -c`` compatible).  ``load_run`` re-verifies all checksums and the
  config hash before returning anything.
* Manifests are hostname-free and contain no user paths (privacy): the git SHA,
  platform string, Python and dependency versions, CPU count, seeds and the command.
* JSON serialisation maps numpy scalars/arrays to Python types and non-finite floats
  to the strings ``"inf"``, ``"-inf"``, ``"nan"`` (mirroring ``ddopt.contracts._jsonable``),
  so files are strict JSON.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import importlib.metadata as _md
import json
import math
import os
import platform
import re
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "TRACKED_PACKAGES",
    "ChecksumError",
    "ConfigError",
    "jsonable",
    "canonical_json",
    "config_hash",
    "run_manifest",
    "write_run",
    "load_run",
    "load_config",
    "validate_config",
    "check_disjoint_seeds",
    "SMOKE_CONFIG_SCHEMA",
]

MANIFEST_SCHEMA_VERSION = "0.1"
TRACKED_PACKAGES = ("numpy", "scipy", "cma", "matplotlib")
NOT_INSTALLED = "not installed"
SHORT_HASH_LEN = 12

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_PAYLOAD = "payload.json"
_MANIFEST = "manifest.json"
_SUMS = "SHA256SUMS"


class ChecksumError(ValueError):
    """A stored run failed integrity verification."""


class ConfigError(ValueError):
    """A configuration dictionary does not satisfy its schema."""


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def jsonable(obj: Any) -> Any:
    """Convert ``obj`` to strict-JSON-compatible Python objects.

    Mirrors ``ddopt.contracts._jsonable`` (dataclasses, numpy scalars/arrays,
    complex -> ``{"re", "im"}``, non-finite float -> string) and additionally maps
    ``Path`` to ``str`` and sets to sorted lists.  Implemented locally so this module
    has no import-time dependency on other package modules.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Mapping):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted((jsonable(v) for v in obj), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(obj, Path):
        return str(obj)
    # numpy without importing it eagerly
    mod = type(obj).__module__
    if mod == "numpy" or mod.startswith("numpy."):
        import numpy as np

        if isinstance(obj, np.ndarray):
            return jsonable(obj.tolist())
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return jsonable(float(obj))
        if isinstance(obj, np.complexfloating):
            return jsonable(complex(obj))
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return obj
    if isinstance(obj, complex):
        return {"re": jsonable(obj.real), "im": jsonable(obj.imag)}
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else str(obj)
    raise TypeError(f"object of type {type(obj).__name__} is not JSON-serialisable")


def canonical_json(obj: Any) -> str:
    """Canonical JSON: sorted keys, no whitespace, UTF-8, strict (no NaN literals)."""
    return json.dumps(
        jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _pretty_json(obj: Any) -> str:
    return json.dumps(jsonable(obj), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def config_hash(cfg: Any) -> str:
    """SHA-256 (hex) of the canonical JSON of ``cfg``; independent of dict key order."""
    return hashlib.sha256(canonical_json(cfg).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Environment capture
# ---------------------------------------------------------------------------


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip()


def _git_info() -> dict[str, Any]:
    sha = _git("rev-parse", "HEAD")
    if not sha:
        return {"sha": "unavailable", "dirty": None}
    status = _git("status", "--porcelain", "--untracked-files=no")
    info: dict[str, Any] = {"sha": sha, "dirty": None if status is None else bool(status)}
    if status:
        # record the uncommitted tracked changes so a dirty run stays reconstructible
        diff = _git("diff", "HEAD") or ""
        info["diff"] = diff
        info["diff_sha256"] = hashlib.sha256(diff.encode()).hexdigest()
    return info


def git_state() -> dict[str, Any]:
    """Current git SHA, dirty flag and (if dirty) the tracked diff. Call at the *start* of a run
    and pass as ``run_manifest(..., extra={"git_at_start": git_state()})``; the manifest's own
    ``git`` field is captured when the manifest is built (usually at the end of the run)."""
    return _git_info()


def _package_version(name: str) -> str:
    try:
        return _md.version(name)
    except _md.PackageNotFoundError:
        return NOT_INSTALLED


def _ddopt_version() -> str:
    try:
        return _md.version("ddopt")
    except _md.PackageNotFoundError:
        pass
    try:  # source checkout on PYTHONPATH without installation
        import ddopt

        v = getattr(ddopt, "__version__", None)
        return f"{v} (uninstalled source)" if v else NOT_INSTALLED
    except Exception:  # pragma: no cover - defensive
        return NOT_INSTALLED


def _utc_now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _normalise_command(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command)
    if isinstance(command, Sequence) and all(isinstance(c, str) for c in command):
        return list(command)
    raise TypeError("command must be a string or a sequence of strings")


def run_manifest(
    config: Mapping[str, Any],
    *,
    seeds: Any,
    command: str | Sequence[str],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a provenance manifest for one run.

    Parameters
    ----------
    config:
        The full run configuration (JSON-able).  Stored verbatim plus its hash.
    seeds:
        Seeds used (int, list, or mapping such as ``{"train": [...], "test": [...]}``).
        Required: a run without recorded seeds is not reproducible.
    command:
        The exact command line (``sys.argv`` or a string).
    extra:
        Optional additional JSON-able metadata (model assumptions, MC draw budget,
        candidate counts, runtime, artifact paths ...).  Stored under ``"extra"``.
    """
    if not isinstance(config, Mapping):
        raise TypeError("config must be a mapping")
    if seeds is None:
        raise ValueError("seeds must be recorded (got None)")
    cmd = _normalise_command(command)
    now = _utc_now()
    cfg = jsonable(config)
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "created_utc": now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "git": _git_info(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "platform": platform.platform(),
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "packages": {name: _package_version(name) for name in TRACKED_PACKAGES},
        "ddopt_version": _ddopt_version(),
        "cpu_count": os.cpu_count(),
        "config": cfg,
        "config_hash": config_hash(cfg),
        "seeds": jsonable(seeds),
        "command": cmd,
        "command_str": shlex.join(cmd),
        "extra": jsonable(dict(extra)) if extra is not None else {},
    }


# ---------------------------------------------------------------------------
# Immutable run directories
# ---------------------------------------------------------------------------


def _run_stamp(manifest: Mapping[str, Any]) -> str:
    created = manifest.get("created_utc")
    if isinstance(created, str):
        try:
            t = _dt.datetime.strptime(created, "%Y-%m-%dT%H:%M:%S.%fZ")
            return t.strftime("%Y%m%dT%H%M%SZ")
        except ValueError:
            pass
    return _utc_now().strftime("%Y%m%dT%H%M%SZ")


def write_run(
    out_dir: str | os.PathLike[str],
    name: str,
    payload: Any,
    manifest: Mapping[str, Any],
) -> Path:
    """Write ``payload`` and ``manifest`` to a new directory ``out_dir/<run_id>/``.

    Raises ``FileExistsError`` if the run directory already exists (never overwrites).
    The written manifest is the given one plus ``run_id`` and ``artifacts`` (the
    sha256 of ``payload.json``).  Files are made read-only after writing.
    """
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ValueError(f"invalid run name {name!r}: use [A-Za-z0-9_-], max 64 chars")
    if "config_hash" not in manifest:
        raise ValueError("manifest lacks config_hash; build it with run_manifest()")
    for key in ("run_id", "artifacts"):
        if key in manifest:
            raise ValueError(f"manifest already contains reserved key {key!r}")
    run_id = f"{name}_{_run_stamp(manifest)}_{str(manifest['config_hash'])[:SHORT_HASH_LEN]}"
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / run_id
    run_dir.mkdir(exist_ok=False)  # atomic claim; raises FileExistsError

    payload_text = _pretty_json(payload)
    (run_dir / _PAYLOAD).write_text(payload_text, encoding="utf-8")
    full_manifest = dict(jsonable(manifest))
    full_manifest["run_id"] = run_id
    full_manifest["artifacts"] = {_PAYLOAD: _sha256_file(run_dir / _PAYLOAD)}
    (run_dir / _MANIFEST).write_text(_pretty_json(full_manifest), encoding="utf-8")

    lines = [f"{_sha256_file(run_dir / fn)}  {fn}\n" for fn in sorted((_MANIFEST, _PAYLOAD))]
    (run_dir / _SUMS).write_text("".join(lines), encoding="utf-8")
    for fn in (_PAYLOAD, _MANIFEST, _SUMS):
        os.chmod(run_dir / fn, 0o444)
    return run_dir


def load_run(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load a run directory after verifying ``SHA256SUMS`` and the config hash.

    Returns ``{"run_id", "path", "manifest", "payload"}``.  Raises ``ChecksumError``
    on any mismatch, missing or unlisted file.
    """
    run_dir = Path(path)
    sums_path = run_dir / _SUMS
    if not sums_path.is_file():
        raise ChecksumError(f"{run_dir}: missing {_SUMS}")
    listed: dict[str, str] = {}
    for lineno, line in enumerate(sums_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise ChecksumError(f"{sums_path}:{lineno}: malformed line")
        listed[parts[1]] = parts[0]
    for required in (_PAYLOAD, _MANIFEST):
        if required not in listed:
            raise ChecksumError(f"{run_dir}: {required} not listed in {_SUMS}")
    present = {p.name for p in run_dir.iterdir() if p.is_file()} - {_SUMS}
    unlisted = present - set(listed)
    if unlisted:
        raise ChecksumError(f"{run_dir}: files not covered by {_SUMS}: {sorted(unlisted)}")
    for fn, digest in listed.items():
        fp = run_dir / fn
        if not fp.is_file():
            raise ChecksumError(f"{run_dir}: listed file {fn} is missing")
        actual = _sha256_file(fp)
        if actual != digest:
            raise ChecksumError(f"{run_dir}: checksum mismatch for {fn}")
    manifest = json.loads((run_dir / _MANIFEST).read_text(encoding="utf-8"))
    payload = json.loads((run_dir / _PAYLOAD).read_text(encoding="utf-8"))
    if config_hash(manifest.get("config")) != manifest.get("config_hash"):
        raise ChecksumError(f"{run_dir}: manifest config_hash does not match stored config")
    if manifest.get("artifacts", {}).get(_PAYLOAD) != listed[_PAYLOAD]:
        raise ChecksumError(f"{run_dir}: manifest artifact hash disagrees with {_SUMS}")
    if manifest.get("run_id") != run_dir.name:
        raise ChecksumError(f"{run_dir}: manifest run_id {manifest.get('run_id')!r} != directory name")
    return {"run_id": manifest["run_id"], "path": run_dir, "manifest": manifest, "payload": payload}


# ---------------------------------------------------------------------------
# Config validation (small JSON-schema-like checker; see configs/schema.md)
# ---------------------------------------------------------------------------

_TYPE_NAMES: dict[str, tuple[type, ...]] = {
    "str": (str,),
    "int": (int,),
    "float": (int, float),
    "number": (int, float),
    "bool": (bool,),
    "list": (list, tuple),
    "dict": (Mapping,),
    "null": (type(None),),
    "any": (object,),
}


def _check_type(value: Any, spec: Any, where: str, errors: list[str]) -> None:
    if isinstance(spec, Mapping):
        if not isinstance(value, Mapping):
            errors.append(f"{where}: expected object, got {type(value).__name__}")
            return
        _validate(value, spec, where, errors)
        return
    names = spec.split("|") if isinstance(spec, str) else None
    if names is not None:
        allowed: list[type] = []
        list_of: list[str] = []
        for n in names:
            n = n.strip()
            if n.startswith("list[") and n.endswith("]"):
                list_of.append(n[5:-1])
            elif n in _TYPE_NAMES:
                allowed.extend(_TYPE_NAMES[n])
            else:
                raise ValueError(f"unknown type name {n!r} in schema at {where}")
        if value is not None and isinstance(value, bool) and bool not in allowed and "any" not in names:
            errors.append(f"{where}: expected {spec}, got bool")
            return
        if allowed and isinstance(value, tuple(allowed)):
            if isinstance(value, float) and not math.isfinite(value):
                errors.append(f"{where}: non-finite number not allowed in configs")
            return
        for inner in list_of:
            if isinstance(value, (list, tuple)):
                sub: list[str] = []
                for i, item in enumerate(value):
                    _check_type(item, inner, f"{where}[{i}]", sub)
                if not sub:
                    return
                errors.extend(sub)
                return
        errors.append(f"{where}: expected {spec}, got {type(value).__name__}")
        return
    if isinstance(spec, type) or (isinstance(spec, tuple) and all(isinstance(s, type) for s in spec)):
        if not isinstance(value, spec):
            errors.append(f"{where}: expected {spec}, got {type(value).__name__}")
        return
    raise ValueError(f"invalid schema entry at {where}: {spec!r}")


def _validate(cfg: Mapping[str, Any], schema: Mapping[str, Any], prefix: str, errors: list[str]) -> None:
    allow_extra = bool(schema.get("__allow_extra__", True))
    optional = set(schema.get("__optional__", ()))
    keys = [k for k in schema if not k.startswith("__")]
    for key in keys:
        where = f"{prefix}.{key}" if prefix else key
        if key not in cfg:
            if key not in optional:
                errors.append(f"{where}: missing required key")
            continue
        _check_type(cfg[key], schema[key], where, errors)
    if not allow_extra:
        for key in cfg:
            if key not in schema:
                errors.append(f"{(prefix + '.') if prefix else ''}{key}: unknown key")


def validate_config(cfg: Mapping[str, Any], required_keys: Any) -> Mapping[str, Any]:
    """Validate ``cfg`` and return it unchanged; raise ``ConfigError`` listing all problems.

    ``required_keys`` is either an iterable of key names (presence only) or a schema
    mapping ``key -> spec`` where ``spec`` is a type-name string (``"str"``, ``"int"``,
    ``"float"``, ``"number"``, ``"bool"``, ``"list"``, ``"dict"``, ``"null"``, ``"any"``,
    ``"list[int]"``; alternatives joined by ``|``), a Python type, or a nested schema
    mapping.  Reserved schema keys: ``"__optional__"`` (iterable of optional keys) and
    ``"__allow_extra__"`` (bool, default True).  ``bool`` never satisfies ``int``/``float``.
    """
    if not isinstance(cfg, Mapping):
        raise ConfigError(f"config must be a mapping, got {type(cfg).__name__}")
    if isinstance(required_keys, Mapping):
        schema: Mapping[str, Any] = required_keys
    elif isinstance(required_keys, str):
        schema = {required_keys: "any"}
    else:
        schema = {k: "any" for k in required_keys}
    errors: list[str] = []
    _validate(cfg, schema, "", errors)
    if errors:
        raise ConfigError("invalid config:\n  " + "\n  ".join(errors))
    return cfg


def check_disjoint_seeds(train: Sequence[int], test: Sequence[int]) -> None:
    """Raise ``ConfigError`` if training and held-out test seeds overlap or repeat."""
    tr, te = list(train), list(test)
    problems = []
    if len(set(tr)) != len(tr):
        problems.append("duplicate training seeds")
    if len(set(te)) != len(te):
        problems.append("duplicate test seeds")
    overlap = sorted(set(tr) & set(te))
    if overlap:
        problems.append(f"train/test seed overlap (leakage): {overlap}")
    if problems:
        raise ConfigError("; ".join(problems))


def load_config(path: str | os.PathLike[str], schema: Any | None = None) -> dict[str, Any]:
    """Read a strict-JSON config file (no NaN/Infinity literals) and optionally validate it."""

    def _reject(token: str) -> Any:
        raise ConfigError(f"{path}: non-finite literal {token} not allowed")

    cfg = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_reject)
    if schema is not None:
        validate_config(cfg, schema)
    return cfg


#: Schema for ``configs/smoke.json`` (documented in ``configs/schema.md``).
SMOKE_CONFIG_SCHEMA: dict[str, Any] = {
    "__allow_extra__": False,
    "schema_version": "str",
    "name": "str",
    "description": "str",
    "kind": "str",
    "seeds": {"__allow_extra__": False, "train": "list[int]", "test": "list[int]"},
    "budget": {"__allow_extra__": False, "mc_draws": "int", "max_evals": "int", "restarts": "int"},
    "outputs": {"__allow_extra__": False, "results_dir": "str"},
    "physics": "null|dict",
}


def _main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin CLI
    """``python -m ddopt.provenance verify <run_dir>...`` re-checks stored runs."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2 or args[0] != "verify":
        print("usage: python -m ddopt.provenance verify RUN_DIR [RUN_DIR ...]", file=sys.stderr)
        return 2
    status = 0
    for p in args[1:]:
        try:
            run = load_run(p)
            print(f"OK   {run['run_id']}")
        except (ChecksumError, OSError, json.JSONDecodeError) as exc:
            print(f"FAIL {p}: {exc}", file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
