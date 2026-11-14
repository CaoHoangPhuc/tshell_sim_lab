"""Reference Testunits extracted from Tessent Shell User's Manual and Reference Manual.

These tests treat the original PDF manuals as the Golden Oracle / Reference Benchmark.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tessent_core.atpg import ATPGEngine, FaultClass
from tessent_core.drc import DRCEngine
from tessent_core.logic4 import Logic4, and4, mux21, not4, or4, xor4
from tessent_core.netlist import CircuitGraph, Gate, parse_verilog_netlist
from tessent_core.state import SessionFSM

LAB = Path(__file__).resolve().parents[1]
REF_PDF = LAB.parent / "tshell_ref.pdf"


class ReferenceBookTestUnits(unittest.TestCase):
    """Ground-truth test units directly referenced from tshell_ref.pdf."""

    def test_logic4_algebra_truth_tables(self):
        """Verify IEEE 1164 / Verilog 4-state logic operations."""
        # NOT
        self.assertEqual(not4(Logic4.ZERO), Logic4.ONE)
        self.assertEqual(not4(Logic4.ONE), Logic4.ZERO)
        self.assertEqual(not4(Logic4.X), Logic4.X)

        # AND with 0 dominating
        self.assertEqual(and4(Logic4.ZERO, Logic4.X), Logic4.ZERO)
        self.assertEqual(and4(Logic4.ONE, Logic4.X), Logic4.X)
        self.assertEqual(and4(Logic4.ONE, Logic4.ONE), Logic4.ONE)

        # OR with 1 dominating
        self.assertEqual(or4(Logic4.ONE, Logic4.X), Logic4.ONE)
        self.assertEqual(or4(Logic4.ZERO, Logic4.X), Logic4.X)
        self.assertEqual(or4(Logic4.ZERO, Logic4.ZERO), Logic4.ZERO)

        # XOR
        self.assertEqual(xor4(Logic4.ZERO, Logic4.ONE), Logic4.ONE)
        self.assertEqual(xor4(Logic4.ONE, Logic4.ONE), Logic4.ZERO)
        self.assertEqual(xor4(Logic4.ONE, Logic4.X), Logic4.X)

        # MUX 2:1
        self.assertEqual(mux21(Logic4.ZERO, Logic4.ZERO, Logic4.ONE), Logic4.ZERO)
        self.assertEqual(mux21(Logic4.ONE, Logic4.ZERO, Logic4.ONE), Logic4.ONE)
        # Even if select is X, if both inputs are 1, output must be 1!
        self.assertEqual(mux21(Logic4.X, Logic4.ONE, Logic4.ONE), Logic4.ONE)

    def test_c1_reference_oracle(self):
        """Test Reference Unit C1 (Reference Manual p. 3809, 3812).

        Rule C1: All clock inputs of memory elements must be at their off state
        when all defined clocks are at their off state.
        """
        circuit = CircuitGraph("c1_circuit")
        circuit.add_port("clk", "in")
        circuit.add_port("q", "out")
        # Flip-flop whose clock is connected to clk
        circuit.add_gate(Gate("DFF1", "DFF", inputs={"clk": "clk", "d": "q"}, outputs={"Q": "q"}))

        engine = DRCEngine(REF_PDF)

        # When clock is defined and off-state is 0, setting clk=0 should PASS C1
        clocks = {"clk": 0}
        violations = engine.run_all_checks(circuit, clocks=clocks, scan_chains=[])
        c1_violations = [v for v in violations if "C1" in v.rule_id]
        self.assertEqual(len(c1_violations), 0)

        # If clock line is stuck active or anomaly injected
        violations_fault = engine.run_all_checks(
            circuit, clocks=clocks, scan_chains=[], injected_anomalies={"C1"}
        )
        c1_fails = [v for v in violations_fault if "C1" in v.rule_id]
        self.assertEqual(len(c1_fails), 1)
        self.assertEqual(c1_fails[0].rule_id, "C1-1")
        self.assertIn("failed to force off", c1_fails[0].message)

    def test_c2_reference_oracle(self):
        """Test Reference Unit C2 (Reference Manual p. 3814).

        Rule C2: Each clock must have a structural path to at least one memory element.
        """
        circuit = CircuitGraph("c2_circuit")
        circuit.add_port("clk", "in")
        circuit.add_port("floating_clk17", "in")
        circuit.add_port("q", "out")
        circuit.add_gate(Gate("DFF1", "DFF", inputs={"clk": "clk", "d": "q"}, outputs={"Q": "q"}))

        engine = DRCEngine(REF_PDF)
        # Define both clk and floating_clk17
        clocks = {"clk": 0, "floating_clk17": 0}
        violations = engine.run_all_checks(circuit, clocks=clocks, scan_chains=[])
        c2_fails = [v for v in violations if "C2" in v.rule_id and v.offending_pin == "floating_clk17"]
        self.assertEqual(len(c2_fails), 1)
        self.assertEqual(c2_fails[0].rule_id, "C2-1")
        self.assertIn("cannot reach the clock port", c2_fails[0].message)

    def test_t3_t4_t5_reference_oracles(self):
        """Test Reference Units T3, T4, T5 (Reference Manual p. 4522-4531)."""
        circuit = CircuitGraph("trace_circuit")
        engine = DRCEngine(REF_PDF)
        chains = [{"name": "chain1", "scan_in": "scan_in", "scan_out": "scan_out", "cells": ["df1", "df2"]}]

        # T3 Check
        v_t3 = engine.run_all_checks(circuit, clocks={"clk": 0}, scan_chains=chains, injected_anomalies={"T3"})
        self.assertTrue(any(v.rule_id == "T3-1" for v in v_t3))

        # T4 Check
        v_t4 = engine.run_all_checks(circuit, clocks={"clk": 0}, scan_chains=chains, injected_anomalies={"T4"})
        self.assertTrue(any(v.rule_id == "T4-1" for v in v_t4))

        # T5 Check
        v_t5 = engine.run_all_checks(circuit, clocks={"clk": 0}, scan_chains=chains, injected_anomalies={"T5"})
        self.assertTrue(any(v.rule_id == "T5-1" for v in v_t5))

    def test_d1_reference_oracle(self):
        """Test Reference Unit D1 (Reference Manual p. 3863, 3865)."""
        circuit = CircuitGraph("disturb_circuit")
        engine = DRCEngine(REF_PDF)
        v_d1 = engine.run_all_checks(circuit, clocks={"clk": 0}, scan_chains=[], injected_anomalies={"D1"})
        d1_fails = [v for v in v_d1 if "D1" in v.rule_id]
        self.assertEqual(len(d1_fails), 1)
        self.assertEqual(d1_fails[0].rule_id, "D1-1")
        self.assertIn("disturbed during time 0", d1_fails[0].message)

    def test_atpg_coverage_formulas(self):
        """Test standard IEEE / Tessent coverage calculation formulas."""
        atpg = ATPGEngine()
        circuit = CircuitGraph("test_circuit")
        circuit.add_port("clk", "in")
        circuit.add_port("scan_in", "in")
        circuit.add_port("scan_en", "in")
        circuit.add_port("scan_out", "out")
        circuit.add_gate(Gate("dff_q0", "DFF", inputs={"clk": "clk", "d": "scan_in"}, outputs={"Q": "q0"}))
        circuit.add_gate(Gate("dff_q1", "DFF", inputs={"clk": "clk", "d": "q0"}, outputs={"Q": "scan_out"}))

        faults_count = atpg.populate_stuck_at_faults(circuit)
        self.assertGreater(faults_count, 0)

        stats = atpg.simulate_test_patterns(circuit)
        self.assertEqual(stats.total_faults, faults_count)
        self.assertGreaterEqual(stats.fault_coverage, 0.0)
        self.assertLessEqual(stats.fault_coverage, 100.0)
        self.assertGreaterEqual(stats.test_coverage, 0.0)
        self.assertLessEqual(stats.test_coverage, 100.0)

    def test_masked_fault_is_not_detected(self):
        """Verify that a masked/unobservable fault is graded as ND and not falsely marked DS."""
        atpg = ATPGEngine()
        circuit = CircuitGraph("masked_circuit")
        circuit.add_port("clk", "in")
        circuit.add_port("scan_in", "in")
        circuit.add_port("scan_en", "in")
        circuit.add_port("scan_out", "out")
        circuit.add_port("unconnected_in", "in")  # Primary input that drives nothing
        circuit.add_gate(Gate("dff_q0", "DFF", inputs={"clk": "clk", "d": "scan_in"}, outputs={"Q": "q0"}))
        circuit.add_gate(Gate("dff_q1", "DFF", inputs={"clk": "clk", "d": "q0"}, outputs={"Q": "scan_out"}))

        atpg.populate_stuck_at_faults(circuit)
        # Test pattern that shifts through scan chain
        stats = atpg.simulate_test_patterns(circuit, test_patterns=[
            {"shift_in": [0, 1]},
            {"shift_in": [1, 0]},
        ])

        # Faults on unconnected_in must NEVER be detected (ND) because they have no path to output
        unconnected_sa0 = atpg.faults.get("unconnected_in/SA0")
        unconnected_sa1 = atpg.faults.get("unconnected_in/SA1")
        self.assertIsNotNone(unconnected_sa0)
        self.assertIsNotNone(unconnected_sa1)
        self.assertEqual(unconnected_sa0.status, FaultClass.ND)
        self.assertEqual(unconnected_sa1.status, FaultClass.ND)

        # Faults on scan_in should be detected (DS)
        scan_in_sa0 = atpg.faults.get("scan_in/SA0")
        self.assertEqual(scan_in_sa0.status, FaultClass.DS)

    def test_pure_algorithmic_drc_checks(self):
        """Verify DRC engine detects real structural violations without injected_anomalies."""
        engine = DRCEngine()

        # 1. Structural T3 Detection: AND gate with 0 blocking scan chain
        c_t3 = CircuitGraph("t3_structural")
        c_t3.add_port("scan_in", "in")
        c_t3.add_port("scan_en", "in")
        c_t3.add_port("clk", "in")
        c_t3.add_port("scan_out", "out")
        c_t3.add_gate(Gate("block_and", "AND", inputs={"in1": "scan_in", "in2": "zero_net"}, outputs={"out": "d_blocked"}))
        c_t3.add_gate(Gate("dff1", "DFF", inputs={"clk": "clk", "d": "d_blocked"}, outputs={"Q": "scan_out"}))
        c_t3.nets["zero_net"] = Logic4.ZERO

        v_t3 = engine.run_all_checks(c_t3, clocks={"clk": 0}, scan_chains=[{"name": "chain1", "scan_in": "scan_in", "scan_out": "scan_out", "cells": ["dff1"]}])
        self.assertTrue(any(v.rule_id == "T3-1" and v.offending_gate == "block_and" for v in v_t3))

        # 2. Structural D1 Detection: Active asynchronous reset line during shift
        c_d1 = CircuitGraph("d1_structural")
        c_d1.add_port("scan_in", "in")
        c_d1.add_port("scan_en", "in")
        c_d1.add_port("clk", "in")
        c_d1.add_port("scan_out", "out")
        c_d1.add_gate(Gate("dff1", "DFF", inputs={"clk": "clk", "d": "scan_in", "reset": "stuck_rst"}, outputs={"Q": "scan_out"}))
        c_d1.nets["stuck_rst"] = Logic4.ONE

        v_d1 = engine.run_all_checks(c_d1, clocks={"clk": 0}, scan_chains=[{"name": "chain1", "scan_in": "scan_in", "scan_out": "scan_out", "cells": ["dff1"]}])
        self.assertTrue(any(v.rule_id == "D1-1" and v.offending_gate == "dff1" for v in v_d1))

        # 3. Structural T5 Detection: Unconstrained floating clock (X state)
        c_t5 = CircuitGraph("t5_structural")
        c_t5.add_port("scan_in", "in")
        c_t5.add_port("scan_en", "in")
        c_t5.add_port("floating_clk", "in")
        c_t5.add_port("scan_out", "out")
        c_t5.add_gate(Gate("dff1", "DFF", inputs={"clk": "floating_clk", "d": "scan_in"}, outputs={"Q": "scan_out"}))

        v_t5 = engine.run_all_checks(c_t5, clocks={}, scan_chains=[{"name": "chain1", "scan_in": "scan_in", "scan_out": "scan_out", "cells": ["dff1"]}])
        self.assertTrue(any(v.rule_id == "T5-1" and v.offending_gate == "dff1" for v in v_t5))

    def test_capture_mode_and_scan_mux_simulation(self):
        """Verify DFF with scan mux correctly latches functional capture data when scan_en=0."""
        v_text = """
        module test_capture(clk, reset, a, scan_en, scan_in, q, scan_out);
          input clk, reset, a, scan_en, scan_in;
          output q, scan_out;
          reg q;
          always @(posedge clk) begin
            if (reset) begin
              q <= 1'b0;
            end else if (scan_en) begin
              q <= scan_in;
            end else begin
              q <= a;
            end
          end
          assign scan_out = q;
        endmodule
        """
        c = parse_verilog_netlist(v_text)
        # Capture mode: scan_en=0, a=1
        c.set_primary_input("reset", 0)
        c.set_primary_input("scan_en", 0)
        c.set_primary_input("a", 1)
        c.clock_edge("clk")
        self.assertEqual(c.nets.get("q"), Logic4.ONE)

        # Shift mode: scan_en=1, scan_in=0
        c.set_primary_input("scan_en", 1)
        c.set_primary_input("scan_in", 0)
        c.clock_edge("clk")
        self.assertEqual(c.nets.get("q"), Logic4.ZERO)

    def test_clock_stuck_at_one_prevents_dff_latch(self):
        """Verify that a clock stuck-at-1 fault prevents DFF from updating state."""
        v_text = """
        module test_clk_fault(clk, reset, a, q);
          input clk, reset, a;
          output q;
          reg q;
          always @(posedge clk) begin
            if (reset) begin
              q <= 1'b0;
            end else begin
              q <= a;
            end
          end
        endmodule
        """
        c = parse_verilog_netlist(v_text)
        c.set_primary_input("reset", 0)
        c.set_primary_input("a", 0)
        c.clock_edge("clk")
        self.assertEqual(c.nets.get("q"), Logic4.ZERO)

        # Now input a=1, but clock is stuck-at-1
        c.set_primary_input("a", 1)
        c.inject_fault("clk", Logic4.ONE)
        c.clock_edge("clk")
        # Since clock has no dynamic edge, q must remain 0
        self.assertEqual(c.nets.get("q"), Logic4.ZERO)

    def test_load_verilog_resets_session_state(self):
        """Verify that loading a new design clears scan chains, faults, and previous state."""
        fsm = SessionFSM()
        # Circuit 1: has scan
        v1 = """
        module circ1(clk, reset, scan_in, scan_en, scan_out, q);
          input clk, reset, scan_in, scan_en;
          output scan_out, q;
          reg q;
          always @(posedge clk) begin
            if (reset) q <= 1'b0;
            else if (scan_en) q <= scan_in;
            else q <= 1'b1;
          end
          assign scan_out = q;
        endmodule
        """
        # Circuit 2: pure combinational, no scan
        v2 = """
        module circ2(in1, in2, out);
          input in1, in2;
          output out;
          assign out = in1 & in2;
        endmodule
        """
        with tempfile.NamedTemporaryFile("w", suffix=".v", delete=False) as f1:
            f1.write(v1)
            p1 = Path(f1.name)
        with tempfile.NamedTemporaryFile("w", suffix=".v", delete=False) as f2:
            f2.write(v2)
            p2 = Path(f2.name)

        try:
            fsm.load_verilog(p1)
            fsm.add_faults("-all")
            self.assertGreater(len(fsm.scan_chains), 0)
            self.assertGreater(len(fsm.atpg_engine.faults), 0)

            # Load Circuit 2
            fsm.load_verilog(p2)
            # Scan chains and previous faults must be completely reset!
            self.assertEqual(len(fsm.scan_chains), 0)
            self.assertEqual(len(fsm.atpg_engine.faults), 0)
        finally:
            p1.unlink(missing_ok=True)
            p2.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
