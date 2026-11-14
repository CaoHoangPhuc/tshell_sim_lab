import unittest
import subprocess
import sys
from pathlib import Path

from scan_sim import Fault, ScanCircuit, run_case


class ScanCircuitTests(unittest.TestCase):
    def test_shift_order_and_serial_output(self):
        circuit = ScanCircuit()
        self.assertEqual([circuit.shift(bit) for bit in (1, 0, 1)], [0, 0, 1])
        self.assertEqual(circuit.state, (1, 0))

    def test_capture_uses_old_state_simultaneously(self):
        circuit = ScanCircuit()
        circuit.shift(1)
        circuit.shift(0)  # q0=0, q1=1
        circuit.capture(a=0, b=1)
        self.assertEqual(circuit.state, (1, 0))
        self.assertEqual(circuit.output(), 1)

    def test_fault_can_be_activated_and_observed(self):
        self.assertTrue(run_case("detected").detected)

    def test_fault_can_be_masked_by_test_vector(self):
        self.assertFalse(run_case("masked").detected)

    def test_d_fault_changes_capture_and_propagates_to_scan_out(self):
        good = ScanCircuit()
        bad = ScanCircuit(Fault("d0", 0))
        for circuit in (good, bad):
            circuit.capture(a=1, b=0)
        self.assertEqual(good.state, (1, 0))
        self.assertEqual(bad.state, (0, 0))
        self.assertEqual([good.shift(0), good.shift(0)], [0, 1])
        self.assertEqual([bad.shift(0), bad.shift(0)], [0, 0])

    def test_rejects_invalid_fault_and_non_binary_input(self):
        with self.assertRaises(ValueError):
            Fault("missing", 0)
        with self.assertRaises(ValueError):
            Fault("q0", 2)
        with self.assertRaises(ValueError):
            ScanCircuit().capture(a=2, b=0)

    def test_stuck_at_one_is_observable_on_serial_output(self):
        circuit = ScanCircuit(Fault("q1", 1))
        self.assertEqual(circuit.shift(0), 1)

    def test_cli_treats_expected_fault_detection_as_passing_case(self):
        script = Path(__file__).resolve().parents[1] / "scan_sim.py"
        result = subprocess.run([sys.executable, str(script), "--case", "detected"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn("[PASS] detected", result.stdout)
        self.assertIn("mismatch detected=True; expected detection=True", result.stdout)
        self.assertNotIn("[PASS] masked", result.stdout)


if __name__ == "__main__":
    unittest.main()
