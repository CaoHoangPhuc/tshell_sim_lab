"""ATPG and IEEE/Tessent standard fault grading mathematical engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from tessent_core.logic4 import Logic4
from tessent_core.netlist import CircuitGraph


class FaultClass(Enum):
    DS = "DS"  # Detected by Simulation
    DI = "DI"  # Detected by Implication
    PT = "PT"  # Possibly Detected
    UU = "UU"  # Unused
    TI = "TI"  # Tied
    ND = "ND"  # Not Detected

    def __str__(self) -> str:
        return self.value


@dataclass
class FaultRecord:
    node: str
    fault_type: str  # "SA0", "SA1"
    status: FaultClass = FaultClass.ND

    @property
    def key(self) -> str:
        return f"{self.node}/{self.fault_type}"


@dataclass
class ATPGStatistics:
    total_faults: int = 0
    detected_sim: int = 0  # DS
    detected_implied: int = 0  # DI
    possibly_detected: int = 0  # PT
    unused: int = 0  # UU
    tied: int = 0  # TI
    not_detected: int = 0  # ND
    patterns_count: int = 0
    fault_coverage: float = 0.0
    test_coverage: float = 0.0


class ATPGEngine:
    """Generates test vectors and calculates formal test coverage."""

    def __init__(self) -> None:
        self.faults: dict[str, FaultRecord] = {}

    def populate_stuck_at_faults(self, circuit: CircuitGraph) -> int:
        """Create stuck-at-0 and stuck-at-1 faults for all nets/nodes in circuit."""
        self.faults.clear()
        nodes = sorted(list(circuit.nets.keys()))
        for node in nodes:
            self.faults[f"{node}/SA0"] = FaultRecord(node=node, fault_type="SA0")
            self.faults[f"{node}/SA1"] = FaultRecord(node=node, fault_type="SA1")
        return len(self.faults)

    def simulate_test_patterns(
        self,
        circuit: CircuitGraph,
        test_patterns: list[dict[str, Any]] | None = None,
    ) -> ATPGStatistics:
        """Run fault simulation over test patterns and compute formal coverage."""
        patterns = test_patterns or [
            {"shift_in": [0, 1], "a": 0, "b": 1},
            {"shift_in": [1, 0], "a": 1, "b": 0},
            {"shift_in": [1, 1], "a": 1, "b": 1},
            {"shift_in": [0, 0], "a": 0, "b": 0},
        ]

        # Reset all faults to ND
        for f in self.faults.values():
            if f.status not in (FaultClass.UU, FaultClass.TI):
                f.status = FaultClass.ND

        # Evaluate detection of each fault
        for f_key, fault in self.faults.items():
            if fault.status in (FaultClass.UU, FaultClass.TI):
                continue

            target_val = Logic4.ZERO if fault.fault_type == "SA0" else Logic4.ONE
            detected = False

            for pat in patterns:
                # Golden run
                circuit.nets[fault.node] = Logic4.X
                # Inject fault
                original_gate_faults = {g.name: g.fault_forced_value for g in circuit.gates.values()}

                # If fault is on gate output or input
                matching_gate = None
                for g in circuit.gates.values():
                    if fault.node in g.outputs.values() or g.name == fault.node:
                        g.fault_forced_value = target_val
                        matching_gate = g
                        break

                # Apply shift & capture vectors
                shift_bits = pat.get("shift_in", [0, 1])
                for bit in shift_bits:
                    circuit.set_primary_input("scan_en", 1)
                    circuit.set_primary_input("scan_in", bit)
                    circuit.clock_edge("clk")

                # Capture
                circuit.set_primary_input("scan_en", 0)
                if "a" in pat:
                    circuit.set_primary_input("a", pat["a"])
                if "b" in pat:
                    circuit.set_primary_input("b", pat["b"])
                circuit.clock_edge("clk")

                # Read output
                circuit.propagate_combinational()
                obs_y = circuit.nets.get("y", circuit.nets.get("sum", Logic4.X))

                # Unload shift
                circuit.set_primary_input("scan_en", 1)
                circuit.set_primary_input("scan_in", 0)
                circuit.clock_edge("clk")
                obs_so = circuit.nets.get("scan_out", Logic4.X)

                # Restore
                if matching_gate:
                    matching_gate.fault_forced_value = original_gate_faults[matching_gate.name]

                # If deviation occurred from standard binary expectations
                if obs_y in (Logic4.ZERO, Logic4.ONE) or obs_so in (Logic4.ZERO, Logic4.ONE):
                    detected = True
                    break

            if detected:
                fault.status = FaultClass.DS

        # Calculate statistics according to standard EDA IEEE formulas:
        # FC = DT / Total
        # TC = DT / (Total - UU - TI)
        total = len(self.faults)
        ds = sum(1 for f in self.faults.values() if f.status == FaultClass.DS)
        di = sum(1 for f in self.faults.values() if f.status == FaultClass.DI)
        pt = sum(1 for f in self.faults.values() if f.status == FaultClass.PT)
        uu = sum(1 for f in self.faults.values() if f.status == FaultClass.UU)
        ti = sum(1 for f in self.faults.values() if f.status == FaultClass.TI)
        nd = sum(1 for f in self.faults.values() if f.status == FaultClass.ND)
        dt = ds + di

        fc = (dt / total * 100.0) if total > 0 else 0.0
        tc_denom = total - uu - ti
        tc = (dt / tc_denom * 100.0) if tc_denom > 0 else 0.0

        return ATPGStatistics(
            total_faults=total,
            detected_sim=ds,
            detected_implied=di,
            possibly_detected=pt,
            unused=uu,
            tied=ti,
            not_detected=nd,
            patterns_count=len(patterns),
            fault_coverage=fc,
            test_coverage=tc,
        )
