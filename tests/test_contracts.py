import math

import numpy as np
import pytest

from ddopt.contracts import DetuningProfile, NoiseModel, PSDComponent, PulseSequence


def test_pulse_sequence_rejects_overlap():
    seq = PulseSequence(T=1e-6, centers=(0.5e-6, 0.51e-6), widths=(40e-9, 40e-9),
                        phases=(0.0, 0.0), angles=(math.pi, math.pi))
    with pytest.raises(ValueError):
        seq.validate()


def test_pulse_sequence_gaps_sum():
    seq = PulseSequence(T=1e-6, centers=(0.25e-6, 0.75e-6), widths=(40e-9, 40e-9),
                        phases=(0.0, 0.0), angles=(math.pi, math.pi))
    seq.validate()
    assert np.isclose(seq.gaps().sum() + 80e-9, 1e-6)


def test_psd_component_validation():
    with pytest.raises(ValueError):
        PSDComponent("one_over_f", {"A": 1.0, "alpha": 1.0}).validate()  # missing finite cutoffs
    PSDComponent("one_over_f", {"A": 1.0, "alpha": 1.0}, 1.0, 1e9).validate()


def test_noise_model_json_roundtrip_types():
    nm = NoiseModel(components=(PSDComponent("lorentzian", {"sigma": 1e5, "tau_c": 1e-6}),),
                    detuning=DetuningProfile("smooth_rect", 1e6, 1e-7, 5e-7, 1e-8), T1=50e-6)
    nm.validate()
    d = nm.to_dict()
    assert d["T1"] == 50e-6 and d["components"][0]["omega_high"] == "inf"
    assert nm.is_gaussian
