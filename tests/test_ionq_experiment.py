"""No cloud network calls, charges or credentials in the local test suite."""
import importlib.util
import pytest
from ddopt.ionq_experiment import build_memory_circuit, run_ionq

@pytest.mark.parametrize("sequence",["free","xy4","xy8"])
def test_dry_run_never_submits(sequence):
    if importlib.util.find_spec("cirq") is None:
        pytest.skip("optional cirq not installed")
    c=run_ionq(sequence,shots=20,submit=False)
    assert len(list(c.all_qubits())) == 1

def test_invalid_shots_fail_offline():
    with pytest.raises(ValueError):
        run_ionq("free",shots=0)

def test_gate_sequences_are_identity_up_to_phase():
    cirq=pytest.importorskip("cirq")
    for name in ["free","xy4","xy8"]:
        c=build_memory_circuit(name,measure=False)
        assert cirq.equal_up_to_global_phase(c.unitary(),cirq.unitary(cirq.I))
