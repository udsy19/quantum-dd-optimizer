# Prospective IQCC / Quantum Machines hardware protocol — NOT RUN

> **Status: NOT RUN. NOT HARDWARE TESTED. No hardware access, no credentials, no
> authorization.** Nothing in this document has been executed on any real device, cloud
> simulator or vendor-hosted service. No coherence time, calibration value, device
> identity or result below is a measurement. Every experiment section is a *plan*.
> Owner: Agent E (`qua/`, `tests/test_qua_syntax.py`, this file).

## 0. Gate list (original, retained verbatim)

Gate 1: Written authorization, backend/qubit identity, approved pulse/readout elements, execution windows, operational constraints and private credentials storage.
Gate 2: Vendor-configured QUA SDK installed; syntax/serialization check distinguished from cloud simulator and real device jobs.
Gate 3: Verify timing tick, pulse width, phase convention, safe power, readout and reset, T1, Ramsey T2*, Hahn T2, pulse calibration and leakage.
Gate 4: Measure spectator phase accumulation under neighbor readout across relative timing, drive-only and measurement-on controls, separate deterministic ac-Stark shift from stochastic dephasing and other errors.
Gate 5: Pre-register equal-n/T, virtual-Z and standard DD controls; randomize/interleave arms to protect against drift, use independently repeated blocks and coherent uncertainty estimates; log readout correction limitations.
Gate 6: Report actual runtime including queue/compile/calibration overhead. At 300us repetition 280k shots represent 84s nominal repetitions only.
Gate 7: Retain anonymized run IDs, times, calibration versions and raw outcomes in controlled storage. Publish only with laboratory approval.

No executable cloud job should be submitted by an autonomous agent without explicit human permission. Never commit secrets or institution-restricted device configs.

| Gate | Status (2026-10-26) |
|---|---|
| 1 Authorization / backend identity | **NOT MET** — no authorization, no backend, no credentials. |
| 2 SDK + syntax/serialization check | **PARTIAL, local only** — `qm-qua` 1.4.1 built and serialized a placeholder program offline in a scratch virtualenv (§2). This is *not* a cloud-simulator run and *not* a device run. The project venv does not contain the SDK, so the SDK test SKIPS there. |
| 3 Calibration (tick, width, phase sign, power, readout, reset, T1, T2*, T2) | **NOT RUN** |
| 4 Spectator phase under neighbour readout | **NOT RUN** |
| 5 Pre-registered interleaved comparison | **NOT RUN** (design in §6) |
| 6 Runtime / overhead accounting | **NOT RUN** (accounting template in §7) |
| 7 Data retention / approval | **NOT RUN** |

## 1. Provenance of QM/QUA API facts

The official documentation site `https://docs.quantum-machines.co/` was **not reachable**
from the build environment on 2026-10-26 (the outbound proxy refused the CONNECT with
HTTP 403; WebFetch failed with DNS resolution). API facts below were therefore read from
the **source code and docstrings of the official SDK wheel** published on PyPI:

* Package: `qm-qua` 1.4.1, `https://pypi.org/project/qm-qua/1.4.1/`, downloaded with
  `pip download qm-qua==1.4.1 --no-deps` on 2026-10-26;
  wheel `qm_qua-1.4.1-py3-none-any.whl`,
  sha256 `e6c702385298a1ed4eaa8358e5f444be80b24c581508d93c837a0e1acc7a87bb`.
  Available versions listed by `pip index versions qm-qua` on that date:
  1.4.1 (latest), 1.4.0, 1.3.1, 1.1.1, 1.1.0, 1.0.1, 1.0.0, 0.3.x, 0.2.x, 0.1.0.
  Wheel metadata: `Requires-Python >=3.10,<3.15`, BSD-3-Clause, Documentation URL
  `https://docs.quantum-machines.co/`, repository `https://github.com/qm-labs/qm-qua-sdk-public`
  (repository not fetched).
* The IQCC-specific toolchain (which QOP / `qm-qua` version the facility pins, any
  facility wrapper packages, authentication flow) is **UNVERIFIED** — no IQCC documentation
  was available. The vendor/facility-pinned version supersedes 1.4.1 (Gate 2).

| Fact used by `qua/` | Status | Source (qm-qua 1.4.1) |
|---|---|---|
| `qm.qua.program()` context manager creates a QUA program | VERIFIED | `qm/qua/_dsl/scope_functions.py` (`def program()`) |
| `wait(duration, *elements)`: "Duration is in units of the clock cycle (4ns)" | VERIFIED | `qm/qua/_dsl/wait.py` docstring |
| `wait` may add computational latency; "actual wait time should always be verified with a simulator" | VERIFIED (vendor caveat) | `wait.py` docstring |
| `play(pulse, element, duration=None, ...)`; `duration` "in units of the clock cycle (4ns)"; arbitrary waveforms can only be stretched, up to 2^24−1 cycles | VERIFIED | `qm/qua/_dsl/play.py` docstring |
| `frame_rotation_2pi(angle, *elements)`: shifts element oscillator phase by `angle`×2π; 16-bit phase resolution; `frame_rotation(angle)` = `frame_rotation_2pi(angle/2π)`; `reset_frame(*elements)` exists | VERIFIED | `qm/qua/_dsl/frame_rotation.py` |
| `align`, `measure`, `declare`, `declare_stream`, `for_`, `save`, `stream_processing`, `update_frequency`, `amp`, `strict_timing_` exported from `qm.qua` | VERIFIED (names only; not used by adapter) | `qm/qua/__init__.py` `__all__` |
| `qm.generate_qua_script(prog, config=None)` serializes a program to Python source | VERIFIED (and exercised offline, §2) | `qm/serialization/generate_qua_script.py` |
| `QuantumMachinesManager` exported from `qm` | VERIFIED (name only; **deliberately never used**) | `qm/__init__.py` |
| Integration-weight and sticky-element durations must be multiples of 4 ns | VERIFIED (config schema) | `qm/program/_qua_config_schema.py`, `qm/config/_elements/_element.py` |
| **Minimum `wait` / `play` duration of 4 cycles = 16 ns** | **UNVERIFIED — ASSUMPTION** (not found in the SDK docstrings; configurable `AdapterConfig.min_wait_cycles/min_pulse_cycles`) | — |
| Frame rotations take zero time on the element timeline | **UNVERIFIED — ASSUMPTION** | — |
| Sign relating a +θ frame rotation to the Bloch-sphere drive axis | **UNVERIFIED — REQUIRES HARDWARE CALIBRATION** | docstring states only "shift the phase of the oscillator" |
| Behaviour of `play(..., duration=)` for the facility's π pulse (constant vs arbitrary waveform) | **UNVERIFIED** | depends on device config |

## 2. SDK availability record and reproducible setup

* Project venv (`.venv`, Python 3.13.17): `import qm` → `ModuleNotFoundError`. The project
  venv was **not** modified. In that environment `tests/test_qua_syntax.py` reports the SDK
  test as **SKIPPED** with reason "QM QUA SDK (qm-qua) not installed".
* Local serialization check (Gate 2, *partial*): a separate throw-away virtualenv in the
  agent scratch directory (outside the repository) with `qm-qua==1.4.1` (pulled
  grpcio 1.85.0, protobuf 7.36.2, marshmallow 3.26.2, numpy 2.5.4). In that environment the
  full test file passed (27 passed, 1 skipped — the skipped test is the "SDK absent" path).
  `build_qua_program` + `qua_script_text` produced a QUA script containing only
  `wait`/`play`/`frame_rotation_2pi` on `qubit_PLACEHOLDER`, with `config = None`.
  On import the SDK logs `Starting session: <uuid>`; source inspection shows this is a
  locally generated id, and log upload (`qm/logging_utils.py`) happens only if a
  `datadog_token` and `upload_logs` are configured (none were). **No manager, connection,
  compile, simulate or execute call was made.** This check proves only that the adapter
  emits syntactically valid SDK calls; it is not evidence of timing, compilation against a
  real configuration, or physical behaviour.

Reproduce (do **not** install into the project venv unless the lead adds an optional
dependency group):

```bash
python -m venv /path/outside/repo/qmvenv
/path/outside/repo/qmvenv/bin/python -m pip install "qm-qua==1.4.1" numpy scipy pytest
PYTHONPATH=$PWD/src:$PWD /path/outside/repo/qmvenv/bin/python -m pytest -q tests/test_qua_syntax.py -rs
```

Replace `1.4.1` with the version pinned by the facility once known (Gate 2).

## 3. Adapter conventions (`qua/adapter.py`)

* Input: `ddopt.contracts.PulseSequence` (seconds, radians; axis `cos φ X + sin φ Y`;
  rotation `angles[k]`). Output: `HardwareSchedule` — integer clock-cycle instructions on one
  placeholder element `qubit_PLACEHOLDER` with one placeholder operation `pi_PLACEHOLDER`.
* Clock period 4 ns (verified for QUA `wait`/`play` units); configurable.
* **Strict mode (default):** every pulse start/end and `T` must lie on the clock grid within
  1e-12 s, otherwise `ScheduleRejected`. **Rounding mode** (`allow_rounding=True`): each edge is
  rounded to the nearest cycle independently; per-edge errors, width errors, T error, max and
  RMS error are reported in `schedule.rounding`; `max_edge_error_s` can bound them.
  Pulse widths are differences of rounded edges, so the summed instruction duration equals
  the rounded `T` exactly (asserted by `HardwareSchedule.check()`).
* **Rejections:** ideal zero-width pulses; rotation angles ≠ π (only one calibrated π
  operation exists); nonzero gaps shorter than `min_wait_cycles` (ASSUMED 4); pulses shorter
  than `min_pulse_cycles` (ASSUMED 4) or longer than 2^24−1 cycles; overlaps or guard
  violations after rounding; any sequence failing `PulseSequence.validate()`.
  Zero-length gaps (back-to-back pulses) emit no `wait`.
* **Phases:** implemented as cumulative frame rotations. Before pulse k the frame is moved to
  `frame_sign·φ_k` (increment wrapped to (−π, π], emitted as `frame_rotation_2pi(turns)`);
  after the last pulse the cumulative frame is undone (`restore_frame=True`). Optional target
  virtual-Z `θ_vz` (`docs/PHYSICS_CONVENTIONS.md`) is appended as a frame rotation of
  `−frame_sign·θ_vz`. `frame_sign = +1` is a **placeholder — REQUIRES HARDWARE CALIBRATION**.
  Phase quantization bound reported: `n_frame_rotations × 2π × 2^-16` rad.
* Non-uniform widths produce a warning: stretching one calibrated π pulse to several
  durations does not give π rotations (amplitude recalibration needed).
* Watermark: `NOT_HARDWARE_TESTED = True` and the `WATERMARK` string are embedded in every
  `HardwareSchedule`, its `to_dict()`/`to_json()` (first keys), its `to_text()` listing
  (header and footer), the `QuaBuild` object and the generated QUA script header.
* `qua/qua_program.py` builds a `qm.qua.program()` only if `qm` imports, else raises
  `ImportError` with setup instructions. It never constructs a manager, opens a connection,
  compiles, simulates or executes (enforced by an AST test).

## 4. Dry-run sequence (all NOT RUN beyond step 2)

1. SDK-free translation + tests (`tests/test_qua_syntax.py`) — done locally, CPU only.
2. Local SDK serialization with placeholder names — done in scratch venv (§2), *partial Gate 2*.
3. With an authorized, facility-provided configuration: compile-only / vendor simulator run
   comparing the simulated waveform timeline against `HardwareSchedule.instructions`
   (edge times, frame-rotation latency, `wait` latency). **Requires Gate 1.**
4. Hardware calibration (§5), then protocols (§6). **Requires Gates 1–3 and explicit human
   approval of each job batch.**

## 5. Calibration gates (Gate 3 detail) — NOT RUN

Each item must be logged with run ID, timestamp, calibration version and raw data before
proceeding. Values below are *what to measure*, not values.

1. **Backend assignment:** qubit, drive element, readout element and neighbour resonators
   permitted for this project (written). Element names replace placeholders via
   `AdapterConfig` only — never committed if institution-restricted.
2. **Safe envelope:** facility-approved maximum drive amplitude/power, pulse durations,
   duty cycle and readout power; adapter rejects out-of-envelope widths (to be wired to the
   approved limits).
3. **Timing:** confirm clock period, minimum `wait`/`play` length, `wait` and
   frame-rotation latencies, element delays/alignment (vendor simulator + a
   timing-sensitive experiment such as Ramsey with sub-µs steps).
4. **Control-axis sign:** determine `frame_sign` (e.g. compare `X_π/2 · frame(+θ) · X_π/2`
   Ramsey-like phase sweeps against the expected direction with a known detuning sign);
   check Y vs −Y with XY4 vs X(−Y)X(−Y) contrast.
5. **π-pulse calibration:** Rabi amplitude/duration, π and π/2 fine calibration
   (error-amplification sequences), DRAG/leakage check if transmon.
6. **Readout and reset:** assignment matrix, readout-induced state change, passive wait
   or active reset fidelity; repetition time `t_rep` chosen ≥ several T1 (or active reset).
7. **Coherence baselines:** T1, Ramsey T2*, Hahn T2 (§6.1–6.3) with uncertainties.
8. **Neighbour readout permission:** whether driving a neighbouring resonator is allowed;
   its power/duration limits.
9. **Drift & leakage monitoring:** repeat a short reference (Ramsey frequency, T1 point,
   assignment fidelity) between blocks; predefine abort thresholds.
10. **Logging:** every job's program text (watermark included), config hash, calibration
    version, timestamps, queue/compile/run times and raw shot outcomes.

## 6. Experiment protocols — ALL NOT RUN

Notation: survival/excited probability `P` estimated from N shots; binomial standard error
`sqrt(P(1−P)/N) ≤ 0.5/sqrt(N)` (e.g. ≤ 0.0158 at N = 1000). SPAM is modelled separately
(§6.9); do not fold it into decay parameters.

1. **T1.** Prepare |1⟩ (π), wait τ on a geometric grid spanning ~0.05–5×T1 (guess from
   facility data, not invented here), measure. Fit `A e^{−τ/T1} + B` with A, B free (SPAM).
   Output: T1 with CI; check residuals for non-exponential behaviour (TLS).
2. **Ramsey (T2\*, detuning).** π/2 – wait τ – π/2 with phase advanced by `2π f_art τ`
   via `frame_rotation_2pi` (artificial detuning) to separate frequency offset from decay.
   Fit decaying cosine; report T2\*, detuning, and whether the envelope is Gaussian-like or
   exponential (informative about low-frequency noise; not a unique PSD reconstruction).
3. **Hahn echo (T2).** π/2 – τ/2 – π – τ/2 – π/2(±), with phase-cycled final pulse (±X)
   to cancel SPAM offsets. Fit envelope; compare with Ramsey to bound quasi-static noise.
4. **CPMG-n.** n ∈ {1, 2, 4, 8, 16, …} at fixed total T and at varying T; Y-axis π pulses
   (contract convention φ = π/2). Use as filter-function spectroscopy input for Agent C's fit
   (held-out n/T reserved for prediction tests, Gate 5). Report pulse-error sensitivity by
   comparing CPMG vs XY4/XY8 at equal n, T.
5. **Spectator phase during neighbour readout (Gate 4).** Spectator qubit in a Ramsey
   (or echo) sequence while the *neighbour's* resonator is driven with a readout-like tone of
   duration t_ro at relative offset Δt within the idle window; sweep Δt and t_ro (and readout
   amplitude if permitted). Measure both quadratures (final π/2 about X and Y) to get phase
   φ(Δt) and contrast |W|(Δt).
6. **Drive-on vs measurement-on controls.** Same timing with (a) no neighbour tone,
   (b) neighbour tone off-resonant/detuned (drive-only, no photon build-up in resonator, if
   permitted), (c) full neighbour measurement (tone + acquisition). Differences isolate
   resonator-photon ac-Stark/dephasing from crosstalk of the drive line itself.
7. **Phase vs dephasing separation.** Deterministic ac-Stark shift appears as a
   reproducible phase linear in photon number × duration and is correctable by virtual-Z;
   stochastic measurement-induced dephasing appears as contrast loss not removable by a
   frame update. Fit φ and |W| separately; validate by applying the predicted virtual-Z
   (adapter `virtual_z_angle`) and checking residual phase ≈ 0 with unchanged contrast.
8. **Interleaved randomized baseline vs optimized arms (Gate 5).** Pre-register: arms =
   {free, Hahn, CPMG-n, XY4/XY8-n, virtual-Z-only, best standard baseline selected on
   *training* data, optimized}, all at equal n and T and passed through the *same* adapter
   settings; selection rule and primary metric fixed before data. Within each block,
   randomize arm order (seeded, seed logged); repeat B independent blocks interleaved in
   time; per-block reference measurements track drift. Estimate the paired difference
   per block, report block-bootstrap CI; a null or negative difference is a valid result.
   Optimized schedules must be generated from noise models fitted on data *not* used for
   evaluation.
9. **SPAM characterization.** Assignment matrix from |0⟩ and |1⟩ preparations each
   block; report readout correction method and its limitations (assumes state-independent
   prep errors; correction can bias low-count estimates); fit decays with free offsets
   rather than relying solely on correction.

## 7. Shot budget and overhead accounting (Gate 6)

Nominal repetition time = `N_total × t_rep`. With the hypothetical values in Gate 6:
280,000 shots × 300 µs = 280,000 × 3.00×10⁻⁴ s = **84 s** (arithmetic checked:
2.8×10⁵ × 3×10⁻⁴ = 8.4×10¹). This is **only** the sum of repetition periods. It is **not**
the session time, which additionally includes (all UNKNOWN until measured): queueing, program
compilation/loading, calibration and re-calibration runs, drift references, data transfer,
classical processing, failed/aborted jobs and human review between batches.

Illustrative decomposition (not a plan commitment, not facility data):
`N_total = N_arms × N_points × N_shots × N_blocks`, e.g. 2 × 7 × 1000 × 20 = 280,000.
A bounded budget must be pre-registered with a hard cap on total shots and on wall time;
reports must state `N_total`, `t_rep`, nominal time, and the **measured** wall-clock time
per category above.

## 8. What remains unverified

* Everything experimental: no device, no calibration, no measured T1/T2*/T2, no spectator
  phase data, no comparison of arms.
* Minimum `wait`/`play` length (16 ns assumed), frame-rotation latency, `wait` latency,
  frame-rotation sign, π-pulse waveform type and `duration` stretching behaviour.
* Facility-pinned QOP / `qm-qua` version and any IQCC wrapper or authentication API.
* Compilation against a real configuration and vendor-simulator timing.
* Whether neighbour-resonator driving is permitted on the assigned device.
* The official docs pages (unreachable from this environment) — facts above come from the
  SDK wheel only and must be re-checked against `https://docs.quantum-machines.co/` for the
  pinned version.

## 9. Access requirements (to be satisfied by the human project owner)

1. Written authorization naming the project, people, backend and permitted operations.
2. Credentials issued to a human and stored outside the repository (never in code, configs,
   logs or this repo); agents must not fetch, store or use them.
3. Facility-provided configuration (elements, operations, waveforms) kept in controlled
   storage; only placeholder names in the public repository.
4. Approved execution windows, shot/time caps and abort criteria.
5. Explicit human approval before each job batch; agents may prepare programs but must not
   submit.
6. Data-retention and publication approval from the laboratory (Gate 7).
