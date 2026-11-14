import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
TSHELL = LAB / "tshell.py"


def run_tshell(*args):
    return subprocess.run(
        [sys.executable, str(TSHELL), *map(str, args)],
        cwd=LAB,
        capture_output=True,
        text=True,
    )


class TessentShellTests(unittest.TestCase):
    def test_demo_executes_cleanly(self):
        proc = run_tshell("--demo")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Tessent Shell Demonstration Workflow", proc.stdout)
        self.assertIn("Test Coverage:", proc.stdout)
        self.assertIn("DRC Rule Excerpt", proc.stdout)

    def test_command_line_one_liner(self):
        cmd = "set_context dft -scan; report_context; add_clocks clk -off_state 0; report_clocks"
        proc = run_tshell("-c", cmd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Context: dft -scan", proc.stdout)
        self.assertIn("clk", proc.stdout)

    def test_dofile_source_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            dofile = Path(tmp) / "run_test.do"
            dofile.write_text(
                "// Test Dofile\n"
                "set_context patterns -scan\n"
                "read_verilog output/serial_adder_scan.v\n"
                "report_design\n"
                "set_system_mode analysis\n"
                "report_drc_rules\n",
                encoding="utf-8",
            )
            proc = run_tshell("-f", str(dofile))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Executing script 'run_test.do'", proc.stdout)
            self.assertIn("Design name: serial_adder_scan", proc.stdout)
            self.assertIn("System mode is now: analysis", proc.stdout)

    def test_drc_rule_reporting(self):
        proc = run_tshell("-c", "report_drc_rules t3-1; report_drc_rules c1-1; report_drc_rules d1-1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("T3-1", proc.stdout)
        self.assertIn("C1-1", proc.stdout)
        self.assertIn("D1-1", proc.stdout)

    def test_atpg_pattern_generation_and_reporting(self):
        cmd = (
            "read_verilog output/serial_adder_scan.v; "
            "add_clocks 0 clk; "
            "set_system_mode analysis; "
            "add_faults -all; "
            "create_patterns; "
            "report_patterns; "
            "simulate_patterns; "
            "report_statistics"
        )
        proc = run_tshell("-c", cmd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ATPG pattern generation completed: 6 test patterns created", proc.stdout)
        self.assertIn("Pattern #0", proc.stdout)
        self.assertIn("test coverage:", proc.stdout.lower())

    def test_positional_clock_and_hierarchical_gate_reporting(self):
        cmd = (
            "read_verilog output/serial_adder_scan.v; "
            "add_clocks 0 clk; "
            "report_clocks; "
            "report_gate /serial_adder_scan/dff_q0"
        )
        proc = run_tshell("-c", cmd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("clk             0", proc.stdout)
        self.assertIn("Gate: dff_q0 (DFF)", proc.stdout)


if __name__ == "__main__":
    unittest.main()
