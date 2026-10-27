"""New, exploratory model-based baselines and analytical DD scoring.

Not part of the historical pre-registered benchmark. Every conclusion from
these helpers requires new runs with independent seeds and artifact provenance.
"""
from __future__ import annotations

import math
import numpy as np

from ddopt.contracts import DetuningProfile, NoiseModel, PulseSequence
from ddopt import sequences
from ddopt.filters import dephasing_variance


def ideal_filter_proxy(seq: PulseSequence, noise: NoiseModel) -> float:
    """Analytic average-gate infidelity for ideal pulses, Gaussian dephasing, T1.

    r = (2 + gamma - 2 exp(-chi/2) sqrt(1-gamma))/6.

    Valid only for instantaneous pulses about equatorial axes with no
    deterministic detuning, stochastic non-Gaussianity or control error.
    Unlike a frozen-trajectory Monte Carlo objective, it has no sampling noise.
    """
    seq.validate()
    noise.validate()
    if any(w != 0.0 for w in seq.widths):
        raise ValueError("Filter proxy requires instantaneous pulses")
    if not noise.is_gaussian:
        raise ValueError("Filter proxy requires Gaussian dephasing")
    if noise.detuning.kind != "none" or noise.detuning.amplitude != 0.0:
        raise ValueError("Filter proxy does not include deterministic detuning")
    chi, _err = dephasing_variance(noise, seq)
    gamma = 0.0 if math.isinf(noise.T1) else -math.expm1(-seq.T/noise.T1)
    W=math.exp(-0.5*chi)
    return max(0.0,(2.0+gamma-2.0*W*math.sqrt(1.0-gamma))/6.0)


def readout_aware_xy4(
    T: float, width: float, readout: DetuningProfile, *,
    uncertainty: float=0.0, guard: float=0.0,
    dt_grid: float | None=None, rise_multiples: float=5.0,
) -> PulseSequence:
    """Heuristic XY4: schedule two pulses before, two after uncertain readout.

    Separates physical pulse supports from [t_on, t_off] expanded by timing
    uncertainty and rise_multiples * smooth-edge rise. Fixed 2+2 distribution,
    not a guarantee of minimax optimality. Returns a validated equal-n schedule.
    Raises if the available non-readout regions cannot hold two pulses each.
    """
    if readout.kind != "smooth_rect":
        raise ValueError("Expected a smooth_rect readout profile")
    if min(uncertainty,guard,rise_multiples,width)<0 or T<=0:
        raise ValueError("Time, width, guard and margin must be nonnegative")
    readout.validate()
    margin=uncertainty+rise_multiples*readout.rise
    left_hi=readout.t_on-margin
    right_lo=readout.t_off+margin
    if not (0.0 < left_hi < right_lo < T):
        raise ValueError("No two safe regions exist with this margin")

    def allocate(lo:float,hi:float,n:int=2)->list[float]:
        available=hi-lo-n*width
        gap=available/(n+1)
        if gap < guard-1e-14:
            raise ValueError("Insufficient readout-free time for guarded pulses")
        return [lo+(k+1)*gap+(k+0.5)*width for k in range(n)]

    centers=allocate(0.0,left_hi)+allocate(right_lo,T)
    sequence=PulseSequence(T=T,centers=tuple(centers),
        widths=(width,)*4,phases=(0.0,math.pi/2,0.0,math.pi/2),
        angles=(math.pi,)*4,guard=guard,dt_grid=None,
        label="readout_aware_xy4",
        metadata={"readout_margin_s":margin,"uncertainty_s":uncertainty,
                  "interpretation":"exploratory heuristic, not original benchmark"})
    sequence.validate()
    if dt_grid is not None:
        sequence=sequences.snap_to_grid(sequence,dt_grid)
        for c,w in zip(sequence.centers,sequence.widths):
            lo,hi=c-w/2,c+w/2
            if not (hi<=left_hi+1e-15 or lo>=right_lo-1e-15):
                raise ValueError("Clock snapping places a pulse in the readout guard region")
    return sequence
