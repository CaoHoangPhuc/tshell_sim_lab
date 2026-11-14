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
        self.assertIn("ATPG pattern generation completed: 6 test patterns created", proc.stdout)
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

    def test_write_tsdb_prevents_overwrite_without_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            tsdb_dir = Path(tmp) / "tsdb_test"
            cmd1 = (
                f"read_verilog examples/serial_adder_scan.v; "
                f"set_tsdb_output_directory {tsdb_dir}; "
                f"write_tsdb_data"
            )
            proc1 = run_tshell("-c", cmd1)
            self.assertEqual(proc1.returncode, 0, proc1.stderr)
            self.assertIn("TSDB synchronization complete", proc1.stdout)

            # Second write without -replace must fail/refuse to overwrite
            cmd2 = (
                f"read_verilog examples/serial_adder_scan.v; "
                f"set_tsdb_output_directory {tsdb_dir}; "
                f"write_tsdb_data"
            )
            proc2 = run_tshell("-c", cmd2)
            self.assertIn("already exists", proc2.stdout)

            # Write with -replace must succeed
            cmd3 = (
                f"read_verilog examples/serial_adder_scan.v; "
                f"set_tsdb_output_directory {tsdb_dir}; "
                f"write_tsdb_data -replace"
            )
            proc3 = run_tshell("-c", cmd3)
            self.assertIn("TSDB synchronization complete", proc3.stdout)

    def test_report_drc_rules_shows_active_violations_alongside_excerpt(self):
        # Circuit with active C2 violation: floating clock that drives no DFF
        with tempfile.TemporaryDirectory() as tmp:
            circuit_file = Path(tmp) / "floating_clk.v"
            circuit_file.write_text(
                "module floating_clk(clk, float_clk, a, q);\n"
                "  input clk, float_clk, a;\n"
                "  output q;\n"
                "  reg q;\n"
                "  always @(posedge clk) q <= a;\n"
                "endmodule\n"
            )
            cmd = (
                f"read_verilog {circuit_file}; "
                f"add_clocks 0 clk float_clk; "
                f"set_system_mode analysis; "
                f"report_drc_rules c2"
            )
            proc = run_tshell("-c", cmd)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            # Must show BOTH the active violation on current design AND the manual excerpt!
            self.assertIn("Active Violations on Current Design", proc.stdout)
            self.assertIn("Clock float_clk cannot reach", proc.stdout)
            self.assertIn("DRC Rule Excerpt", proc.stdout)


if __name__ == "__main__":
    unittest.main()
