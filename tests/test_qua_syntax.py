"""Tests for the SDK-free QUA adapter (qua/) -- NOT hardware tests.

Passing these tests demonstrates only internal bookkeeping (quantization, rejection,
watermarking). It says nothing about hardware behaviour. SDK-dependent tests SKIP when the
``qm`` package is absent.
"""

from __future__ import annotations

import ast
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # qua/ lives at the repo root, outside src/
    sys.path.insert(0, str(ROOT))

from ddopt.contracts import PulseSequence  # noqa: E402
from qua.adapter import (  # noqa: E402
    NOT_HARDWARE_TESTED,
    WATERMARK,
    AdapterConfig,
    ScheduleRejected,
    to_schedule,
)

NS = 1e-9
PI = math.pi


def cpmg_like(n: int, T: float, width: float, phases=None, **kw) -> PulseSequence:
    centers = tuple(T * (k + 0.5) / n for k in range(n))
    return PulseSequence(
        T=T, centers=centers, widths=(width,) * n,
        phases=tuple(phases) if phases is not None else (PI / 2,) * n,
        angles=(PI,) * n, label="cpmg_test", **kw,
    )


# ---------------------------------------------------------------- watermark


def test_watermark_constant():
    assert NOT_HARDWARE_TESTED is True
    assert "NOT_HARDWARE_TESTED" in WATERMARK


def test_watermark_in_every_output():
    s = to_schedule(cpmg_like(4, 2000 * NS, 20 * NS))
    assert s.NOT_HARDWARE_TESTED is True
    d = s.to_dict()
    assert d["NOT_HARDWARE_TESTED"] is True and d["watermark"] == WATERMARK
    assert list(d)[:2] == ["NOT_HARDWARE_TESTED", "watermark"]
    j = json.loads(s.to_json())
    assert j["NOT_HARDWARE_TESTED"] is True
    txt = s.to_text()
    assert txt.count("NOT HARDWARE TESTED") >= 2 and WATERMARK in txt
    assert "qubit_PLACEHOLDER" in txt and "pi_PLACEHOLDER" in txt


def test_watermark_tamper_detected():
    s = to_schedule(cpmg_like(2, 1000 * NS, 20 * NS))
    s.NOT_HARDWARE_TESTED = False
    with pytest.raises(AssertionError):
        s.check()


# ---------------------------------------------------------------- quantization


def test_on_grid_exact_duration_and_structure():
    # Hahn-like on-grid: T = 1000 ns, one 40 ns pulse centred at 500 ns -> edges 480/520 ns.
    seq = PulseSequence(T=1000 * NS, centers=(500 * NS,), widths=(40 * NS,), phases=(0.0,),
                        angles=(PI,), label="hahn")
    s = to_schedule(seq)
    assert s.total_cycles == 250
    assert [(i.kind, i.cycles) for i in s.instructions] == [("wait", 120), ("play", 10), ("wait", 120)]
    assert s.timed_cycles() == s.total_cycles
    assert s.rounding["max_abs_edge_error_s"] < 1e-15
    assert s.rounding["mode"] == "strict"


@pytest.mark.parametrize("n,T,w", [(1, 1000 * NS, 40 * NS), (4, 2000 * NS, 20 * NS),
                                   (8, 4000 * NS, 20 * NS), (16, 6400 * NS, 24 * NS)])
def test_total_duration_equals_T(n, T, w):
    s = to_schedule(cpmg_like(n, T, w))
    assert s.timed_cycles() == s.total_cycles
    assert abs(s.T_scheduled_s - T) <= 1e-12
    assert sum(1 for i in s.instructions if i.kind == "play") == n


def test_off_grid_rejected_in_strict_mode():
    seq = cpmg_like(3, 1000 * NS, 40 * NS)  # centres at 166.67 ns etc -> off grid
    with pytest.raises(ScheduleRejected, match="off the"):
        to_schedule(seq)


def test_off_grid_T_rejected():
    seq = PulseSequence(T=1001 * NS)
    with pytest.raises(ScheduleRejected, match="T ="):
        to_schedule(seq)


def test_rounding_mode_reports_errors_and_preserves_T_within_half_cycle():
    T = 1001 * NS
    seq = cpmg_like(3, T, 41 * NS)
    s = to_schedule(seq, AdapterConfig(allow_rounding=True))
    r = s.rounding
    assert r["mode"] == "nearest"
    half = 0.5 * s.clock_period_s
    assert 0 < r["max_abs_edge_error_s"] <= half + 1e-18
    assert len(r["edge_errors_s"]) == 2 * seq.n
    assert all(abs(e) <= half + 1e-18 for e in r["edge_errors_s"])
    assert abs(s.T_scheduled_s - T) <= half + 1e-18
    assert s.timed_cycles() == s.total_cycles
    # Reported errors are exactly (scheduled - requested).
    starts = [i.t_start_cycles for i in s.instructions if i.kind == "play"]
    for k, c in enumerate(starts):
        req = seq.centers[k] - seq.widths[k] / 2
        assert math.isclose(c * s.clock_period_s - req, r["edge_errors_s"][2 * k], abs_tol=1e-18)


def test_max_edge_error_limit():
    seq = cpmg_like(3, 1000 * NS, 40 * NS)
    with pytest.raises(ScheduleRejected, match="max_edge_error_s"):
        to_schedule(seq, AdapterConfig(allow_rounding=True, max_edge_error_s=0.1 * NS))


# ---------------------------------------------------------------- rejection


def test_sub_minimum_wait_rejected():
    # gap of 8 ns (2 cycles) between back-to-back pulses < assumed 4-cycle minimum
    seq = PulseSequence(T=400 * NS, centers=(100 * NS, 148 * NS), widths=(40 * NS, 40 * NS),
                        phases=(0.0, 0.0), angles=(PI, PI))
    with pytest.raises(ScheduleRejected, match="minimum wait"):
        to_schedule(seq)


def test_zero_gap_allowed_without_wait_instruction():
    seq = PulseSequence(T=400 * NS, centers=(100 * NS, 140 * NS), widths=(40 * NS, 40 * NS),
                        phases=(0.0, 0.0), angles=(PI, PI))
    s = to_schedule(seq)
    kinds = [i.kind for i in s.instructions]
    assert kinds == ["wait", "play", "play", "wait"]


def test_sub_minimum_pulse_rejected():
    seq = PulseSequence(T=400 * NS, centers=(200 * NS,), widths=(8 * NS,), phases=(0.0,), angles=(PI,))
    with pytest.raises(ScheduleRejected, match="minimum pulse"):
        to_schedule(seq)


def test_instantaneous_pulse_rejected():
    seq = PulseSequence(T=400 * NS, centers=(200 * NS,), widths=(0.0,), phases=(0.0,), angles=(PI,))
    with pytest.raises(ScheduleRejected, match="instantaneous"):
        to_schedule(seq)


def test_non_pi_angle_rejected():
    seq = PulseSequence(T=400 * NS, centers=(200 * NS,), widths=(40 * NS,), phases=(0.0,),
                        angles=(PI / 2,))
    with pytest.raises(ScheduleRejected, match="angle"):
        to_schedule(seq)


def test_invalid_sequence_rejected_by_contract():
    seq = PulseSequence(T=400 * NS, centers=(200 * NS, 210 * NS), widths=(40 * NS, 40 * NS),
                        phases=(0.0, 0.0), angles=(PI, PI))
    with pytest.raises(ValueError):
        to_schedule(seq)


def test_free_evolution_single_wait():
    s = to_schedule(PulseSequence(T=1000 * NS, label="free"))
    assert [(i.kind, i.cycles) for i in s.instructions] == [("wait", 250)]


def test_custom_clock_period():
    s = to_schedule(PulseSequence(T=1000 * NS), AdapterConfig(clock_period_s=1 * NS, min_wait_cycles=16))
    assert s.total_cycles == 1000


# ---------------------------------------------------------------- phases / frames


def _frame_turns(s):
    return [i.turns for i in s.instructions if i.kind == "frame_rotation_2pi"]


def test_xy4_frame_rotations_and_restore():
    seq = cpmg_like(4, 2000 * NS, 20 * NS, phases=(0.0, PI / 2, 0.0, PI / 2))
    s = to_schedule(seq)
    turns = _frame_turns(s)
    assert turns == pytest.approx([0.25, -0.25, 0.25, -0.25])
    assert sum(turns) == pytest.approx(0.0, abs=1e-15)  # frame restored at end
    plays = [i for i in s.instructions if i.kind == "play"]
    assert [p.axis_phase_rad for p in plays] == list(seq.phases)
    # frame rotations take no time on the (assumed) timeline
    assert s.timed_cycles() == s.total_cycles == 500
    assert s.rounding["n_frame_rotations"] == 4
    assert s.rounding["phase_quantization_bound_rad"] == pytest.approx(4 * 2 * PI * 2**-16)


def test_cpmg_y_axis_single_frame_then_restore():
    s = to_schedule(cpmg_like(4, 2000 * NS, 20 * NS))  # all phases pi/2
    assert _frame_turns(s) == pytest.approx([0.25, -0.25])


def test_frame_sign_flips_rotations():
    seq = cpmg_like(4, 2000 * NS, 20 * NS, phases=(0.0, PI / 2, 0.0, PI / 2))
    a = _frame_turns(to_schedule(seq))
    b = _frame_turns(to_schedule(seq, AdapterConfig(frame_sign=-1)))
    assert b == pytest.approx([-x for x in a])
    assert "REQUIRES HARDWARE CALIBRATION" in to_schedule(seq).assumptions["frame_sign"]


def test_phase_wrapping():
    seq = cpmg_like(2, 1000 * NS, 20 * NS, phases=(0.1, 0.1 + 2 * PI))
    turns = _frame_turns(to_schedule(seq))
    assert turns == pytest.approx([0.1 / (2 * PI), -0.1 / (2 * PI)])
    assert all(-0.5 < t <= 0.5 for t in turns)


def test_virtual_z_appended_after_restore():
    s = to_schedule(cpmg_like(2, 1000 * NS, 20 * NS, phases=(0.0, 0.0)), virtual_z_angle=0.3)
    assert _frame_turns(s) == pytest.approx([-0.3 / (2 * PI)])
    assert "virtual-Z" in s.instructions[-1].note


# ---------------------------------------------------------------- safety


def test_qua_package_never_connects_or_executes():
    """Static check: no manager construction / execute / simulate calls in qua/ source."""
    banned_calls = {"QuantumMachinesManager", "execute", "simulate", "open_qm", "compile"}
    for path in (ROOT / "qua").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                assert name not in banned_calls, f"{path.name} calls {name}"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {a.name for a in node.names}
                assert "QuantumMachinesManager" not in names, path.name


def test_qua_program_import_error_without_sdk():
    try:
        import qm  # noqa: F401
    except ImportError:
        from qua import qua_program

        with pytest.raises(ImportError, match="not importable"):
            qua_program.build_qua_program(to_schedule(PulseSequence(T=1000 * NS)))
    else:
        pytest.skip("qm SDK is installed; ImportError path not applicable")


# ---------------------------------------------------------------- SDK-dependent (skip if absent)


def test_qua_program_builds_and_serializes_with_sdk():
    pytest.importorskip("qm", reason="QM QUA SDK (qm-qua) not installed: SDK serialization check SKIPPED")
    from qua.qua_program import build_qua_program, qua_script_text

    seq = cpmg_like(4, 2000 * NS, 20 * NS, phases=(0.0, PI / 2, 0.0, PI / 2))
    build = build_qua_program(to_schedule(seq))
    assert build.NOT_HARDWARE_TESTED is True
    txt = qua_script_text(build)
    assert txt.startswith("# NOT_HARDWARE_TESTED")
    assert "qubit_PLACEHOLDER" in txt and "pi_PLACEHOLDER" in txt
    assert "frame_rotation_2pi" in txt and "wait(" in txt and "play(" in txt
