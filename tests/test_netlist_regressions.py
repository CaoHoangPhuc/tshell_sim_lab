import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from insertion import EXAMPLE, insert_scan
from tessent_core.logic4 import Logic4, mux21
from tessent_core.netlist import CircuitGraph, Gate, parse_verilog_netlist


class NetlistRegressionTests(unittest.TestCase):
    def test_initial_state_is_unknown_until_synchronous_reset(self):
        graph = parse_verilog_netlist(insert_scan(EXAMPLE)[0])
        graph.propagate_combinational()
        self.assertEqual(graph.nets['q0'], Logic4.X)
        self.assertEqual(graph.nets['q1'], Logic4.X)
        graph.set_primary_input('reset', 1)
        graph.clock_edge()
        self.assertEqual((graph.nets['q0'], graph.nets['q1']), (Logic4.ZERO, Logic4.ZERO))

    def test_inserted_design_capture_and_shift(self):
        graph = parse_verilog_netlist(insert_scan(EXAMPLE)[0])
        graph.set_primary_input('reset', 1); graph.clock_edge()
        for name, value in {'reset': 0, 'scan_en': 0, 'scan_in': 0, 'a': 1, 'b': 1}.items():
            graph.set_primary_input(name, value)
        graph.clock_edge()
        self.assertEqual(graph.nets['q0'], Logic4.ONE)
        self.assertEqual(graph.nets['q1'], Logic4.ZERO)
        self.assertEqual(graph.nets['sum'], Logic4.ONE)
        graph.set_primary_input('scan_en', 1)
        graph.set_primary_input('scan_in', 0)
        graph.clock_edge()
        self.assertEqual((graph.nets['q0'], graph.nets['q1']), (Logic4.ZERO, Logic4.ONE))

    def test_unknown_procedural_controls_take_else_branch(self):
        graph = parse_verilog_netlist(insert_scan(EXAMPLE)[0])
        graph.set_primary_input('reset', 1); graph.clock_edge()
        for name, value in {'reset': 'X', 'scan_en': 'X', 'scan_in': 0, 'a': 1, 'b': 1}.items():
            graph.set_primary_input(name, value)
        graph.clock_edge()
        self.assertEqual(graph.nets['q0'], Logic4.ONE)

    def test_nested_expression_and_primitive(self):
        graph = parse_verilog_netlist('''module simple(a,b,y,z); input a,b; output y,z;
            assign y=(a & b) | a; and gate1(z,a,b); endmodule''')
        for a in (0, 1):
            for b in (0, 1):
                graph.set_primary_input('a', a); graph.set_primary_input('b', b)
                graph.propagate_combinational()
                self.assertEqual(graph.nets['y'], Logic4.from_val(a))
                self.assertEqual(graph.nets['z'], Logic4.from_val(a & b))

    def test_unsupported_behavior_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unsupported|expected'):
            parse_verilog_netlist('module bad(a,y); input a; output y; always @(*) y = a; endmodule')
        with self.assertRaises(ValueError):
            parse_verilog_netlist('module bad(input a, output y); assign y=a; endmodule')

    def test_generated_design_with_internal_clock_is_rejected(self):
        rtl = insert_scan(EXAMPLE)[0]
        rtl = rtl.replace('  reg q0, q1;', '  wire ck;\n  reg q0, q1;')
        rtl = rtl.replace('  always @(posedge clk)', '  assign ck = ~clk;\n  always @(posedge ck)')
        with self.assertRaisesRegex(ValueError, 'clock'):
            parse_verilog_netlist(rtl)

    def test_stuck_high_clock_cannot_capture_repeatedly(self):
        graph = CircuitGraph()
        graph.add_port('clk', 'in'); graph.add_port('d', 'in'); graph.add_port('q', 'out')
        graph.add_gate(Gate('ff', 'DFF', inputs={'clk': 'clk', 'd': 'd'}, outputs={'Q': 'q'}, internal_state=Logic4.ZERO))
        graph.inject_fault('clk', Logic4.ONE)
        graph.set_primary_input('d', 1); graph.clock_edge()
        self.assertEqual(graph.nets['q'], Logic4.ZERO)
        graph.set_primary_input('d', 0); graph.clock_edge()
        self.assertEqual(graph.nets['q'], Logic4.ZERO)

    def test_unknown_mux_with_identical_high_impedance_inputs(self):
        self.assertEqual(mux21(Logic4.X, Logic4.Z, Logic4.Z), Logic4.Z)

    def test_buf_with_z_returns_x_and_undriven_wire_is_z(self):
        graph = parse_verilog_netlist('''module test_buf(a, y, undriven_out);
            input a;
            output y, undriven_out;
            wire floating_w;
            buf b1(y, floating_w);
        endmodule''')
        graph.propagate_combinational()
        self.assertEqual(graph.nets['floating_w'], Logic4.Z)
        self.assertEqual(graph.nets['undriven_out'], Logic4.Z)
        self.assertEqual(graph.nets['y'], Logic4.X)

    def test_continuous_assign_propagates_z_whereas_buf_gate_produces_x(self):
        graph = parse_verilog_netlist('''module test_assign_z(a, y_assign, y_buf);
            input a;
            output y_assign, y_buf;
            assign y_assign = a;
            buf b1(y_buf, a);
        endmodule''')
        graph.set_primary_input('a', Logic4.Z)
        graph.propagate_combinational()
        self.assertEqual(graph.nets['a'], Logic4.Z)
        self.assertEqual(graph.nets['y_assign'], Logic4.Z)
        self.assertEqual(graph.nets['y_buf'], Logic4.X)

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus not available')
    def test_generated_design_simulation_matches_icarus(self):
        rtl = insert_scan(EXAMPLE)[0]
        graph = parse_verilog_netlist(rtl)
        tb = ["""module tb; reg clk=0, reset=0, a=0,b=0,scan_en=0,scan_in=0; wire sum,scan_out;
        serial_adder_scan dut(clk,reset,a,b,scan_en,scan_in,sum,scan_out);
        task pulse; begin #1 clk=1; #1 clk=0; end endtask
        initial begin"""]
        graph.propagate_combinational()
        expected_initial = ''.join(str(graph.nets[n]).lower() for n in ('q0', 'q1'))
        graph.set_primary_input('reset', 1); graph.clock_edge()
        expected_after_reset = ''.join(str(graph.nets[n]).lower() for n in ('q0', 'q1'))
        tb.append('#1 $display("INITIAL %b%b",dut.q0,dut.q1); reset=1; pulse; $display("RESET %b%b",dut.q0,dut.q1); reset=0;')
        expected = []
        for first in (0, 1):
            for second in (0, 1):
                for a in (0, 1):
                    for b in (0, 1):
                        for key, value in {'reset': 1, 'scan_en': 0, 'scan_in': 0, 'a': a, 'b': b}.items():
                            graph.set_primary_input(key, value)
                        graph.clock_edge(); graph.set_primary_input('reset', 0)
                        graph.set_primary_input('scan_en', 1)
                        for bit in (first, second):
                            graph.set_primary_input('scan_in', bit); graph.clock_edge()
                        graph.set_primary_input('scan_en', 0); graph.clock_edge()
                        expected.append(''.join(str(graph.nets[n]) for n in ('q0', 'q1', 'sum', 'scan_out')))
                        tb.append(f"reset=1; a={a}; b={b}; pulse; reset=0; scan_en=1; scan_in={first}; pulse; scan_in={second}; pulse; scan_en=0; pulse; $display(\"RESULT %b%b%b%b\",dut.q0,dut.q1,sum,scan_out);")
        tb.append('$finish; end endmodule')
        with tempfile.TemporaryDirectory() as d:
            path = Path(d); (path/'design.v').write_text(rtl); (path/'tb.v').write_text('\n'.join(tb))
            subprocess.run(['iverilog','-o',str(path/'run'),str(path/'design.v'),str(path/'tb.v')], check=True, capture_output=True)
            output = subprocess.run(['vvp',str(path/'run')], check=True, capture_output=True, text=True).stdout
        self.assertIn('INITIAL ' + expected_initial, output)
        self.assertIn('RESET ' + expected_after_reset, output)
        actual = [line.split()[1] for line in output.splitlines() if line.startswith('RESULT ')]
        self.assertEqual(actual, expected)
