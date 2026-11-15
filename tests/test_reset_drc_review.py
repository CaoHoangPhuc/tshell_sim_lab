import pytest

from tessent_core.drc import DRCEngine
from tessent_core.netlist import CircuitGraph, Gate, parse_verilog_netlist


def parsed_scan(reset):
    return parse_verilog_netlist(f"""
        module m(clk,{reset},scan_en,scan_in,scan_out);
        input clk,{reset},scan_en,scan_in;
        output scan_out;
        reg q;
        assign scan_out = q;
        always @(posedge clk) begin
            if ({reset}) q <= 1'b0;
            else if (scan_en) q <= scan_in;
            else q <= q;
        end
        endmodule
    """)


@pytest.mark.parametrize('reset', ['rst', 'rst_n', 'clear'])
def test_synchronous_reset_names_do_not_cause_false_c1_or_shift_violations(reset):
    circuit = parsed_scan(reset)
    chain = {'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['dff_q']}
    violations = DRCEngine().run_all_checks(circuit, {'clk': 0}, [chain])
    assert not [v for v in violations if v.rule_id in ('C1-1', 'T5-1', 'D1-1')]


def test_c1_still_detects_active_asynchronous_reset():
    circuit = CircuitGraph('async_reset')
    circuit.add_port('clk', 'in')
    circuit.add_port('rst', 'in')
    circuit.add_gate(Gate('ff', 'DFF', inputs={'clk': 'clk', 'reset': 'rst', 'd': 'd'}, outputs={'Q': 'q'}))
    circuit.set_primary_input('rst', 1)
    violations = DRCEngine().run_all_checks(circuit, {'clk': 0}, [])
    assert any(v.rule_id == 'C1-1' for v in violations)


def test_manual_reset_input_remains_asserted_during_shift():
    circuit = CircuitGraph('asserted_reset')
    for name in ('clk', 'reset', 'scan_in'):
        circuit.add_port(name, 'in')
    circuit.add_port('scan_out', 'out')
    circuit.add_gate(Gate('ff', 'DFF', inputs={'clk': 'clk', 'reset': 'reset', 'd': 'scan_in'}, outputs={'Q': 'scan_out'}))
    circuit.set_primary_input('reset', 1)
    chain = {'scan_in': 'scan_in', 'scan_out': 'scan_out', 'cells': ['ff']}
    violations = DRCEngine().run_all_checks(circuit, {'clk': 0}, [chain])
    assert {'C1-1', 'T5-1', 'D1-1'} <= {v.rule_id for v in violations}
