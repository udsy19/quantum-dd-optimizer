import math
import pytest

from ddopt.contracts import DetuningProfile, NoiseModel, PSDComponent
from ddopt.research_baselines import ideal_filter_proxy, readout_aware_xy4
from ddopt import sequences


def test_analytic_proxy_no_noise_or_relaxation():
    n=NoiseModel()
    s=sequences.xy4(2e-6,width=0.0)
    assert abs(ideal_filter_proxy(s,n)) < 1e-10


def test_analytic_proxy_recovers_amplitude_damping():
    n=NoiseModel(T1=100e-6)
    s=sequences.free(2e-6)
    g=-math.expm1(-s.T/n.T1)
    assert ideal_filter_proxy(s,n)==pytest.approx((2+g-2*math.sqrt(1-g))/6,rel=1e-7)


def test_proxy_rejects_finite_pulses():
    with pytest.raises(ValueError, match="instantaneous"):
        ideal_filter_proxy(sequences.xy4(2e-6,width=32e-9),NoiseModel())


def test_readout_aware_pulses_outside_uncertain_window():
    d=DetuningProfile(kind="smooth_rect",amplitude=2*math.pi*0.2e6,
                     t_on=.6e-6,t_off=1.6e-6,rise=20e-9)
    s=readout_aware_xy4(2e-6,32e-9,d,uncertainty=100e-9,guard=4e-9,dt_grid=4e-9)
    assert s.n==4
    s.validate()
    margin=100e-9+5*20e-9
    assert all(c+w/2<=d.t_on-margin+1e-15 or c-w/2>=d.t_off+margin-1e-15
               for c,w in zip(s.centers,s.widths))


def test_readout_aware_rejects_insufficient_window():
    d=DetuningProfile(kind="smooth_rect",t_on=.1e-6,t_off=1.9e-6,rise=20e-9)
    with pytest.raises(ValueError):
        readout_aware_xy4(2e-6,32e-9,d,uncertainty=100e-9)
