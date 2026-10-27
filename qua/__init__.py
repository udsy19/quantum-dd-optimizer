"""Hardware-agnostic schedule adapter for a Quantum Machines OPX / QUA backend.

*** NOT HARDWARE TESTED ***  Nothing in this package has been executed on, compiled
for, or simulated against any real or cloud Quantum Machines backend. All element and
operation names are placeholders. See ``docs/HARDWARE_PROTOCOL.md`` for the gates that
must be passed (with explicit human authorization) before any hardware use.

Modules
-------
* :mod:`qua.adapter` -- pure-Python, SDK-free translation of a
  :class:`ddopt.contracts.PulseSequence` into a list of clock-cycle instructions.
* :mod:`qua.qua_program` -- optional builder of a QUA ``program()`` object from such a
  schedule; requires the ``qm-qua`` SDK and never opens a connection or executes anything.
"""

from qua.adapter import (
    NOT_HARDWARE_TESTED,
    WATERMARK,
    AdapterConfig,
    HardwareSchedule,
    Instruction,
    ScheduleRejected,
    to_schedule,
)

__all__ = [
    "NOT_HARDWARE_TESTED",
    "WATERMARK",
    "AdapterConfig",
    "HardwareSchedule",
    "Instruction",
    "ScheduleRejected",
    "to_schedule",
]
