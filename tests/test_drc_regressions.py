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
