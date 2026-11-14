from tessent_core.drc import DRCEngine
from tessent_core.netlist import CircuitGraph, Gate


def test_drc_without_scan_ports_does_not_guess_chain_or_crash():
    circuit = CircuitGraph('no_output')
    circuit.add_port('clk', 'in')
    circuit.add_port('d', 'in')
    circuit.add_gate(Gate('ff', 'DFF', inputs={'clk': 'clk', 'd': 'd'}, outputs={'Q': 'q'}))
    violations = DRCEngine().run_all_checks(circuit, {'clk': 0}, [])
    assert not any(v.rule_id.startswith(('T3', 'T4', 'T5')) for v in violations)
