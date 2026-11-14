from tessent_core.atpg import ATPGEngine, FaultClass
from tessent_core.netlist import CircuitGraph, Gate


def test_explicit_empty_patterns_do_not_run_default_patterns():
    circuit = CircuitGraph("simple")
    circuit.add_port("a", "in")
    circuit.add_port("y", "out")
    circuit.add_gate(Gate("buffer", "BUF", inputs={"in": "a"}, outputs={"out": "y"}))
    engine = ATPGEngine()
    engine.populate_stuck_at_faults(circuit)
    engine.create_patterns(circuit)

    stats = engine.simulate_test_patterns(circuit, [])

    assert stats.patterns_count == 0
    assert stats.detected_sim == 0
    assert all(fault.status == FaultClass.ND for fault in engine.faults.values())
