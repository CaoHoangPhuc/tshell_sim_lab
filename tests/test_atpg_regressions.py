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


def test_fault_observable_after_capture_clock():
    # Circuit with one DFF: q <= a
    circuit = CircuitGraph("seq_single")
    circuit.add_port("clk", "in")
    circuit.add_port("reset", "in")
    circuit.add_port("a", "in")
    circuit.add_port("q", "out")
    circuit.add_gate(Gate("dff_q", "DFF", inputs={"clk": "clk", "reset": "reset", "d": "a"}, outputs={"Q": "q"}))

    engine = ATPGEngine()
    engine.populate_stuck_at_faults(circuit)
    # Target fault a/SA0 with pattern a=1
    pattern = [{"a": 1}]
    stats = engine.simulate_test_patterns(circuit, pattern)

    assert engine.faults["a/SA0"].status == FaultClass.DS
    assert stats.detected_sim > 0


def test_pattern_runner_with_custom_pin_names():
    # Circuit using custom pin names: rst, se, si, so
    circuit = CircuitGraph("custom_pins")
    circuit.add_port("clk", "in")
    circuit.add_port("rst", "in")
    circuit.add_port("se", "in")
    circuit.add_port("si", "in")
    circuit.add_port("a", "in")
    circuit.add_port("so", "out")
    circuit.add_port("q", "out")

    # Scan mux: sel=se, d0=a, d1=si -> d_mux
    circuit.add_gate(Gate("scan_mux", "IFMUX", inputs={"sel": "se", "d0": "a", "d1": "si"}, outputs={"out": "d_mux"}))
    circuit.add_gate(Gate("dff_q", "DFF", inputs={"clk": "clk", "reset": "rst", "d": "d_mux"}, outputs={"Q": "q"}))
    circuit.add_gate(Gate("buf_so", "BUF", inputs={"in": "q"}, outputs={"out": "so"}))

    engine = ATPGEngine()
    engine.populate_stuck_at_faults(circuit)
    patterns = engine.create_patterns(circuit)
    assert len(patterns) > 0
    stats = engine.simulate_test_patterns(circuit, patterns)
    assert stats.detected_sim > 0


def test_combinational_circuit_with_reset_input_does_not_mask_patterns():
    circuit = CircuitGraph("comb_reset")
    circuit.add_port("reset", "in")
    circuit.add_port("y", "out")
    circuit.add_gate(Gate("assign_y", "ASSIGN", inputs={"in": "reset"}, outputs={"out": "y"}))

    engine = ATPGEngine()
    engine.populate_stuck_at_faults(circuit)
    stats = engine.simulate_test_patterns(circuit, [{"reset": 0}, {"reset": 1}])

    assert engine.faults["reset/SA0"].status == FaultClass.DS
    assert engine.faults["reset/SA1"].status == FaultClass.DS
    assert stats.fault_coverage == 100.0


def test_combinational_circuit_with_so_output_is_observed():
    circuit = CircuitGraph("comb_so")
    circuit.add_port("a", "in")
    circuit.add_port("so", "out")
    circuit.add_gate(Gate("assign_so", "ASSIGN", inputs={"in": "a"}, outputs={"out": "so"}))

    engine = ATPGEngine()
    engine.populate_stuck_at_faults(circuit)
    stats = engine.simulate_test_patterns(circuit, [{"a": 0}, {"a": 1}])

    assert engine.faults["a/SA0"].status == FaultClass.DS
    assert engine.faults["a/SA1"].status == FaultClass.DS
    assert engine.faults["so/SA0"].status == FaultClass.DS
    assert engine.faults["so/SA1"].status == FaultClass.DS
    assert stats.fault_coverage == 100.0


def test_combinational_circuit_with_clk_input_is_tested_as_data():
    circuit = CircuitGraph("comb_clk")
    circuit.add_port("clk", "in")
    circuit.add_port("y", "out")
    circuit.add_gate(Gate("assign_y", "ASSIGN", inputs={"in": "clk"}, outputs={"out": "y"}))

    engine = ATPGEngine()
    engine.populate_stuck_at_faults(circuit)
    stats = engine.simulate_test_patterns(circuit, [{"clk": 0}, {"clk": 1}])

    assert engine.faults["clk/SA0"].status == FaultClass.DS
    assert engine.faults["clk/SA1"].status == FaultClass.DS
    assert engine.faults["y/SA0"].status == FaultClass.DS
    assert engine.faults["y/SA1"].status == FaultClass.DS
    assert stats.fault_coverage == 100.0
