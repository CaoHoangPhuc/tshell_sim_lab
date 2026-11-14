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
        self.assertIn("DRC", proc.stdout)
        self.assertNotIn("//  Error:", proc.stdout)

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
                "read_verilog examples/serial_adder_scan.v\n"
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
            "read_verilog examples/serial_adder_scan.v; "
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
        self.assertIn("Generated 6 heuristic demonstration patterns", proc.stdout)
        self.assertIn("Pattern #0", proc.stdout)
        self.assertIn("test coverage:", proc.stdout.lower())

    def test_positional_clock_and_hierarchical_gate_reporting(self):
        cmd = (
            "read_verilog examples/serial_adder_scan.v; "
            "add_clocks 0 clk; "
            "report_clocks; "
            "report_gate /serial_adder_scan/dff_q0"
        )
        proc = run_tshell("-c", cmd)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("clk             0", proc.stdout)
        self.assertIn("Gate: dff_q0 (DFF)", proc.stdout)

    def test_write_tsdb_rejects_unsupported_export_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            tsdb_dir = Path(tmp) / "tsdb_test"
            existing = tsdb_dir / "dft_inserted_designs" / "serial_adder_scan.v"
            existing.parent.mkdir(parents=True)
            existing.write_text("existing design", encoding="utf-8")
            for option in ("", " -replace"):
                cmd = (
                    "read_verilog examples/serial_adder_scan.v; "
                    f"set_tsdb_output_directory {tsdb_dir}; "
                    f"write_tsdb_data{option}"
                )
                proc = run_tshell("-c", cmd)
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("not implemented", proc.stdout)
                self.assertEqual(existing.read_text(encoding="utf-8"), "existing design")
                self.assertFalse((tsdb_dir / "patterns").exists())

    def test_report_drc_rules_shows_current_design_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            circuit_file = Path(tmp) / "floating_clk.v"
            circuit_file.write_text(
                "module floating_clk(float_clk, a, q);\n"
                "  input float_clk, a;\n"
                "  output q;\n"
                "  assign q = a;\n"
                "endmodule\n"
            )
            cmd = (
                f"read_verilog {circuit_file}; "
                "add_clocks 0 float_clk; "
                "set_system_mode analysis; "
                "report_drc_rules c2"
            )
            proc = run_tshell("-c", cmd)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Active Violations on Current Design", proc.stdout)
            self.assertIn("Clock float_clk cannot reach", proc.stdout)


if __name__ == "__main__":
    unittest.main()
