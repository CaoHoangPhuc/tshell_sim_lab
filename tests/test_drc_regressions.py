from tessent_core.drc import DRCEngine
from tessent_core.netlist import CircuitGraph, Gate


def test_drc_without_scan_ports_does_not_guess_chain_or_crash():
    circuit = CircuitGraph('no_output')
    circuit.add_port('clk', 'in')
    circuit.add_port('d', 'in')
    circuit.add_gate(Gate('ff', 'DFF', inputs={'clk': 'clk', 'd': 'd'}, outputs={'Q': 'q'}))
    violations = DRCEngine().run_all_checks(circuit, {'clk': 0}, [])
    assert not any(v.rule_id.startswith(('T3', 'T4', 'T5')) for v in violations)


def test_set_drc_handling_ignore_filters_out_violation():
    circuit = CircuitGraph('unreached_clock')
    circuit.add_port('clk', 'in')
    circuit.add_port('d', 'in')
    # ff has clock 'other_clk' which is not in clocks dict -> triggers C2 violation
    circuit.add_gate(Gate('ff', 'DFF', inputs={'clk': 'other_clk', 'd': 'd'}, outputs={'Q': 'q'}))

    engine = DRCEngine()
    violations_default = engine.run_all_checks(circuit, {'clk': 0}, [])
    assert any(v.rule_id.startswith('C2') for v in violations_default)

    # Now override C2 to Ignore
    engine.handling_overrides['C2'] = 'Ignore'
    violations_ignored = engine.run_all_checks(circuit, {'clk': 0}, [])
    assert not any(v.rule_id.startswith('C2') for v in violations_ignored)


def test_c1_passes_when_clock_off_state_is_one():
    # Active-low clock: off-state is 1
    circuit = CircuitGraph('active_low_clk')
    circuit.add_port('clk_n', 'in')
    circuit.add_port('d', 'in')
    circuit.add_gate(Gate('ff', 'DFF', inputs={'clk': 'clk_n', 'd': 'd'}, outputs={'Q': 'q'}))

    engine = DRCEngine()
    violations = engine.run_all_checks(circuit, clocks={'clk_n': 1}, scan_chains=[])
    assert not any(v.rule_id.startswith('C1') for v in violations)


def test_c1_fails_when_clock_is_unknown_x():
    circuit = CircuitGraph('unknown_clk')
    circuit.add_port('clk', 'in')
    circuit.add_port('floating_ctrl', 'in')
    circuit.add_port('d', 'in')
    # Clock gated with floating/unknown signal
    circuit.add_gate(Gate('g_and', 'AND', inputs={'in0': 'clk', 'in1': 'floating_ctrl'}, outputs={'out': 'gated_clk'}))
    circuit.add_gate(Gate('ff', 'DFF', inputs={'clk': 'gated_clk', 'd': 'd'}, outputs={'Q': 'q'}))

    engine = DRCEngine()
    # When clk off-state is 1, 1 AND X is X -> triggers C1!
    violations = engine.run_all_checks(circuit, clocks={'clk': 1}, scan_chains=[])
    assert any(v.rule_id.startswith('C1') for v in violations)
