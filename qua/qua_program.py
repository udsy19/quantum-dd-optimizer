"""Optional QUA program builder (requires the ``qm-qua`` SDK).

*** NOT HARDWARE TESTED ***

Builds a QUA ``program()`` object for the idle window described by a
:class:`qua.adapter.HardwareSchedule`. This module deliberately:

* never creates a manager / connection object, never opens a socket, never calls any
  execute / simulate / compile entry point -- building a ``Program`` object and serializing
  it to text are purely local operations of the SDK;
* contains no credentials, host names or device configuration;
* emits only the idle-window statements (no readout, no state preparation, no averaging
  loop); those belong to the protocols in ``docs/HARDWARE_PROTOCOL.md`` and require an
  authorized, calibrated configuration.

API names used (``qm.qua.program``, ``play``, ``wait``, ``frame_rotation_2pi`` and
``qm.generate_qua_script``) were checked against the source/docstrings of ``qm-qua`` 1.4.1
(PyPI wheel, accessed 2026-10-26). A local syntax/serialization check is **not** a cloud
simulator run and **not** a hardware run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qua.adapter import NOT_HARDWARE_TESTED, WATERMARK, HardwareSchedule

SDK_MISSING_MESSAGE = (
    "The Quantum Machines QUA SDK ('qm' module, PyPI package 'qm-qua') is not importable. "
    "qua.qua_program is optional; the SDK-free translator qua.adapter.to_schedule works "
    "without it. To enable local syntax/serialization checks install the vendor-pinned "
    "version in a separate environment (see docs/HARDWARE_PROTOCOL.md, 'Reproducible SDK "
    "setup'). Installing the SDK does not grant or imply hardware access."
)


def _import_qua() -> Any:
    try:
        from qm import qua  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise ImportError(SDK_MISSING_MESSAGE) from exc
    return qua


@dataclass
class QuaBuild:
    """Result of :func:`build_qua_program`; carries the watermark alongside the program."""

    program: Any
    schedule: HardwareSchedule
    NOT_HARDWARE_TESTED: bool = NOT_HARDWARE_TESTED
    watermark: str = WATERMARK


def build_qua_program(schedule: HardwareSchedule) -> QuaBuild:
    """Return a :class:`QuaBuild` with a QUA ``Program`` replaying ``schedule``.

    Raises ImportError (with setup instructions) if the SDK is not installed.
    """
    schedule.check()
    qua = _import_qua()
    with qua.program() as prog:
        for ins in schedule.instructions:
            if ins.kind == "wait":
                qua.wait(int(ins.cycles), ins.element)
            elif ins.kind == "play":
                qua.play(ins.operation, ins.element, duration=int(ins.cycles))
            elif ins.kind == "frame_rotation_2pi":
                qua.frame_rotation_2pi(float(ins.turns), ins.element)
            else:  # pragma: no cover
                raise ValueError(f"unknown instruction kind {ins.kind!r}")
    return QuaBuild(program=prog, schedule=schedule)


def qua_script_text(build: QuaBuild) -> str:
    """Serialize the program to QUA Python source (local, offline) with the watermark prepended."""
    try:
        from qm import generate_qua_script  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ImportError(SDK_MISSING_MESSAGE) from exc
    body = generate_qua_script(build.program)
    header = (
        f"# {WATERMARK}\n"
        "# NOT HARDWARE TESTED. Placeholder element/operation names. Do not run without the\n"
        "# calibration gates and explicit written authorization in docs/HARDWARE_PROTOCOL.md.\n"
    )
    return header + body
