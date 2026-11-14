import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from insertion import EXAMPLE, insert_scan


class InsertionTests(unittest.TestCase):
    def test_two_flops_are_stitched_in_order(self):
        verilog, report = insert_scan(EXAMPLE)
        self.assertIn("module serial_adder_scan", verilog)
        self.assertIn("q0 <= scan_in;", verilog)
        self.assertIn("q1 <= q0;", verilog)
        self.assertIn("assign scan_out = q1;", verilog)
        self.assertIn("q0 <= (a ^ q1);", verilog)
        self.assertIn("q1 <= (q0 & b);", verilog)
        self.assertIn("assign sum = (q0 ^ q1);", verilog)
        self.assertIn("Flip-flops: 2", report)
        self.assertIn("scan_in -> q0 -> q1 -> scan_out", report)

    def test_can_insert_a_single_flop(self):
        spec = {"module": "one", "inputs": ["a"], "outputs": {"y": "q"},
                "flip_flops": [{"name": "q", "d": "a"}]}
        verilog, report = insert_scan(spec)
        self.assertIn("q <= scan_in;", verilog)
        self.assertIn("assign scan_out = q;", verilog)
        self.assertIn("Flip-flops: 1", report)

    def test_rejects_invalid_and_ambiguous_designs(self):
        invalid = []
        s = copy.deepcopy(EXAMPLE); s["flip_flops"][1]["name"] = "q0"; invalid.append(s)
        s = copy.deepcopy(EXAMPLE); s["flip_flops"][0]["d"] = "unknown ^ a"; invalid.append(s)
        s = copy.deepcopy(EXAMPLE); s["flip_flops"][0]["d"] = "a; $finish"; invalid.append(s)
        s = copy.deepcopy(EXAMPLE); s["inputs"].append("scan_in"); invalid.append(s)
        s = copy.deepcopy(EXAMPLE); s["flip_flops"] = []; invalid.append(s)
        s = copy.deepcopy(EXAMPLE); s["module"] = "module"; invalid.append(s)
        s = copy.deepcopy(EXAMPLE); s["inputs"].append("bad$name"); invalid.append(s)
        for spec in invalid:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                insert_scan(spec)

    def test_cli_writes_verilog_and_report_and_preserves_input(self):
        script = Path(__file__).resolve().parents[1] / "insertion.py"
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "input.json"
            original = json.dumps(EXAMPLE)
            spec.write_text(original)
            rtl = Path(tmp) / "generated" / "scan.v"
            result = subprocess.run([sys.executable, str(script), "--spec", str(spec),
                                     "-o", str(rtl)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(spec.read_text(), original)
            self.assertTrue(rtl.is_file())
            self.assertIn("scan_in -> q0 -> q1 -> scan_out", rtl.with_suffix(".scan.txt").read_text())
            collision = subprocess.run([sys.executable, str(script), "--spec", str(spec),
                                        "-o", str(spec)], capture_output=True, text=True)
            self.assertNotEqual(collision.returncode, 0)
            self.assertEqual(spec.read_text(), original)
            alias = Path(tmp) / "alias.v"
            os.link(spec, alias)
            collision = subprocess.run([sys.executable, str(script), "--spec", str(spec),
                                        "-o", str(alias)], capture_output=True, text=True)
            self.assertNotEqual(collision.returncode, 0)
            self.assertEqual(spec.read_text(), original)


if __name__ == "__main__":
    unittest.main()
