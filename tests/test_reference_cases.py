"""Reference Testunits extracted from Tessent Shell User's Manual and Reference Manual.

These tests treat the original PDF manuals as the Golden Oracle / Reference Benchmark.
"""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
