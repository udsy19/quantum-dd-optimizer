"""Opt-in cross-platform DD circuit experiments via Cirq/IonQ.

IonQ uses trapped ions, not the superconducting transmon and readout-resonator
model tested elsewhere in this repository. Gate-level DD experiments here
cannot validate the specific QUA pulse-width or ac-Stark model.

Never log the API key. The service constructor reads IONQ_API_KEY from
the environment. All remote jobs require an explicit submit=True flag.
"""
from __future__ import annotations
import math
import os
from typing import Literal

def build_memory_circuit(sequence: Literal["free","xy4","xy8"], *, measure: bool = True):
    """Prepare |+>, insert identity-equivalent DD gates, measure in X basis.

    Circuit is gate-level. No physical idle duration or analog pulse timing is
    controllable here; this is only an exploratory control-error comparison.
    """
    try:
        import cirq
    except ImportError as e:
        raise RuntimeError("Install optional dependencies: pip install cirq cirq-ionq") from e
    q = cirq.LineQubit(0)
    c = cirq.Circuit(cirq.H(q))
    axes = {"free": (), "xy4": "XYXY", "xy8": "XYXYYXYX"}
    if sequence not in axes:
        raise ValueError("Unsupported sequence")
    for axis in axes[sequence]:
        c.append(cirq.X(q) if axis=="X" else cirq.Y(q))
    c.append(cirq.H(q))
    if measure:
        c.append(cirq.measure(q,key="readout"))
    return c

def run_ionq(sequence: Literal["free","xy4","xy8"], *, shots: int=100,
             target: str="simulator", submit: bool=False):
    """Prepare a small experiment; remote execution is explicitly opt-in.

    Never default to a billable QPU, and never print credentials.
    """
    if not 1 <= shots <= 10000:
        raise ValueError("Shots out of bounded exploratory range")
    circuit=build_memory_circuit(sequence)
    if not submit:
        return circuit
    key=os.environ.get("IONQ_API_KEY")
    if not key:
        raise RuntimeError("IONQ_API_KEY environment variable must be configured")
    try:
        import cirq_ionq
    except ImportError as e:
        raise RuntimeError("Install cirq-ionq explicitly") from e
    service=cirq_ionq.Service(api_key=key,default_target="simulator",api_version="v0.4")
    result=service.run(circuit=circuit,repetitions=shots,target=target)
    return result.histogram(key="readout")
