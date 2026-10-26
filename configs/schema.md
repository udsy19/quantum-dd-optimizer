# Configuration and run-manifest schema (v0.1)

Owner: Agent F. Validator: `ddopt.provenance.validate_config` / `load_config`.
Configs are **strict JSON** (no `NaN`/`Infinity` literals; `load_config` rejects them).
Units follow `docs/PHYSICS_CONVENTIONS.md` (s, rad/s, rad, two-sided PSD in rad^2/s);
every physical key added in later schema versions must state its unit in this file.

## Validator spec language

`validate_config(cfg, schema)` where `schema` is either an iterable of required key names
(presence check only) or a mapping `key -> spec`:

| spec | meaning |
|---|---|
| `"str"`, `"int"`, `"float"`/`"number"` (int or float), `"bool"`, `"list"`, `"dict"`, `"null"`, `"any"` | type check (`bool` never satisfies `int`/`float`; non-finite floats rejected) |
| `"list[int]"` etc. | list whose items all satisfy the inner spec |
| `"a\|b"` | alternatives, e.g. `"null\|dict"` |
| nested mapping | nested object, validated recursively |
| `"__optional__": [...]` | keys that may be absent |
| `"__allow_extra__": false` | reject unknown keys (default: unknown keys allowed) |

All violations are collected and raised together as `ConfigError`.

## `configs/smoke.json` (schema `ddopt.provenance.SMOKE_CONFIG_SCHEMA`)

Placeholder used only to exercise provenance and CI plumbing. **It contains no physics and
supports no scientific claim.**

| key | type | meaning |
|---|---|---|
| `schema_version` | str | config schema version (`"0.1"`) |
| `name` | str | run-name prefix used in `run_id` (`[A-Za-z0-9_-]`, max 64 chars) |
| `kind` | str | `"plumbing_smoke"` for this file |
| `description` | str | free text; must not assert results |
| `seeds.train` | list[int] | seeds for training / frozen (common-random-number) draws |
| `seeds.test` | list[int] | independent held-out evaluation seeds; must be disjoint from `train` (`check_disjoint_seeds`) |
| `budget.mc_draws` | int | Monte Carlo noise draws per evaluation |
| `budget.max_evals` | int | optimizer candidate-evaluation budget |
| `budget.restarts` | int | independent optimizer restarts |
| `outputs.results_dir` | str | root directory for immutable run directories |
| `physics` | null \| object | `null` here. Experiment configs will define noise model, sequences and simulation settings in a later schema version (PENDING; depends on `ddopt.contracts`, owned by the integration lead) |

## Run directory and manifest (`write_run` / `load_run`)

`results/<run_id>/` with `run_id = <name>_<YYYYMMDDTHHMMSSZ>_<config_hash[:12]>` (stamp taken
from the manifest's `created_utc`). A run directory is written once and never overwritten
(`FileExistsError`); its files are made read-only. There is no mutable "latest" result.

* `payload.json` — run outputs (strict JSON; numpy types converted; non-finite floats stored as
  the strings `"inf"`, `"-inf"`, `"nan"`).
* `manifest.json` — keys: `manifest_schema_version`, `created_utc` (ISO-8601 UTC),
  `git.sha`, `git.dirty` (tracked files only; `null` if git unavailable),
  `platform.{system,release,machine,platform}`, `python.{version,implementation}`,
  `packages.{numpy,scipy,cma,matplotlib}` (version or `"not installed"`), `ddopt_version`,
  `cpu_count`, `config`, `config_hash` (sha256 of canonical JSON: sorted keys, no whitespace,
  UTF-8), `seeds`, `command` (argv list), `command_str`, `extra` (model assumptions, MC shots,
  device/candidate counts, runtime, artifact paths ...), `run_id`, `artifacts`
  (sha256 of `payload.json`). No hostname, username or absolute paths are recorded by default.
* `SHA256SUMS` — `sha256sum -c` compatible; covers `manifest.json` and `payload.json`.

`load_run` re-verifies every checksum, rejects unlisted files, and recomputes `config_hash`.
CLI: `python -m ddopt.provenance verify results/<run_id> [...]`.
