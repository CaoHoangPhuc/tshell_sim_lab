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


def find_pin(candidates: tuple[str, ...], available: set[str] | list[str]) -> str | None:
    avail_map = {p.lower(): p for p in available}
    for c in candidates:
        if c.lower() in avail_map:
            return avail_map[c.lower()]
    return None


def get_control_pins(circuit: CircuitGraph) -> dict[str, str | None]:
    has_flops = any(g.gate_type.upper() == "DFF" for g in circuit.gates.values())
    if not has_flops and not circuit.scan_cells:
        # Purely combinational circuit: no scan control pins
        return {
            "clk": None,
            "reset": None,
            "scan_en": None,
            "scan_in": None,
            "scan_out": None,
        }

    clk_pin = None
    reset_pin = None
    scan_en_pin = None
    scan_in_pin = None
    scan_out_pin = None

    for g in circuit.gates.values():
        if g.gate_type.upper() == "DFF":
            if not clk_pin and "clk" in g.inputs and g.inputs["clk"] in circuit.primary_inputs:
                clk_pin = g.inputs["clk"]
            if not reset_pin and "reset" in g.inputs and g.inputs["reset"] in circuit.primary_inputs:
                reset_pin = g.inputs["reset"]
        elif g.gate_type.upper() == "IFMUX":
            if not scan_en_pin and "sel" in g.inputs and g.inputs["sel"] in circuit.primary_inputs:
                scan_en_pin = g.inputs["sel"]

    if not clk_pin:
        clk_pin = find_pin(("clk", "clock", "ck"), circuit.primary_inputs) or "clk"
    if not reset_pin:
        reset_pin = find_pin(("reset", "rst", "rst_n", "reset_n"), circuit.primary_inputs)
    if not scan_en_pin:
        scan_en_pin = find_pin(("scan_en", "se", "scan_enable", "scanenable", "shift_en"), circuit.primary_inputs)
    if not scan_in_pin:
        scan_in_pin = find_pin(("scan_in", "si", "sin", "scanin"), circuit.primary_inputs)
    if not scan_out_pin:
        scan_out_pin = find_pin(("scan_out", "so", "sout", "scanout"), circuit.primary_outputs)

    return {
        "clk": clk_pin,
        "reset": reset_pin,
        "scan_en": scan_en_pin,
        "scan_in": scan_in_pin,
        "scan_out": scan_out_pin,
    }


def execute_test_pattern(
    circuit: CircuitGraph,
    pat: dict[str, Any],
) -> tuple[dict[str, Logic4], list[Logic4]]:
    """Execute one scan test pattern: Reset -> Shift-in (Load) -> Capture -> Shift-out (Unload)."""
    ctrl = get_control_pins(circuit)
    clk = ctrl["clk"]
    reset = ctrl["reset"]
    scan_en = ctrl["scan_en"]
    scan_in = ctrl["scan_in"]
    scan_out = ctrl["scan_out"]

    # 1. Reset circuit to clean slate if reset port exists
    if reset and reset in circuit.primary_inputs:
        circuit.set_primary_input(reset, 1)
        circuit.clock_edge(clk)
        circuit.set_primary_input(reset, 0)

    # 2. Shift-in (Load)
    shift_bits = pat.get("shift_in", [])
    if shift_bits and scan_en and scan_in and scan_en in circuit.primary_inputs and scan_in in circuit.primary_inputs:
        circuit.set_primary_input(scan_en, 1)
        for b in shift_bits:
            circuit.set_primary_input(scan_in, b)
            circuit.clock_edge(clk)

    # 3. Capture: Force PIs and pulse clock
    if scan_en and scan_en in circuit.primary_inputs:
        circuit.set_primary_input(scan_en, 0)

    known_ctrl = {p for p in (clk, reset, scan_en, scan_in) if p is not None}
    data_pis = [p for p in circuit.primary_inputs if p not in known_ctrl]
    for pi in data_pis:
        if pi in pat:
            circuit.set_primary_input(pi, pat[pi])

    circuit.propagate_combinational()

    scan_len = len(circuit.scan_cells) if circuit.scan_cells else len(shift_bits)
    is_scan = scan_len > 0 and bool(scan_out and scan_en and scan_out in circuit.primary_outputs and scan_en in circuit.primary_inputs)

    # Strobe Primary Outputs before capture clock (observes combinational PI->PO paths)
    obs_pos: dict[str, Logic4] = {}
    for po in circuit.primary_outputs:
        if not is_scan or po != scan_out:
            pre_val = circuit.nets.get(po, Logic4.X)
            obs_pos[f"{po}@pre"] = pre_val
            obs_pos[po] = pre_val

    # Capture pulse
    if clk and (clk in circuit.primary_inputs or any(g.gate_type.upper() == "DFF" for g in circuit.gates.values())):
        circuit.clock_edge(clk)
        circuit.propagate_combinational()

    # Strobe Primary Outputs after capture clock (observes sequential / flop-captured values on POs)
    for po in circuit.primary_outputs:
        if not is_scan or po != scan_out:
            post_val = circuit.nets.get(po, Logic4.X)
            obs_pos[f"{po}@post"] = post_val
            obs_pos[po] = post_val

    # 4. Shift-out (Unload)
    obs_scan_out: list[Logic4] = []
    scan_len = len(circuit.scan_cells) if circuit.scan_cells else len(shift_bits)
    if scan_len > 0 and scan_out and scan_en and scan_out in circuit.primary_outputs and scan_en in circuit.primary_inputs:
        circuit.set_primary_input(scan_en, 1)
        if scan_in and scan_in in circuit.primary_inputs:
            circuit.set_primary_input(scan_in, 0)
        circuit.propagate_combinational()
        for _ in range(scan_len):
            obs_scan_out.append(circuit.nets.get(scan_out, Logic4.X))
            circuit.clock_edge(clk)
            circuit.propagate_combinational()

    return obs_pos, obs_scan_out


class ATPGEngine:
    """Generates test vectors and calculates formal test coverage."""

    def __init__(self) -> None:
        self.faults: dict[str, FaultRecord] = {}
        self.patterns: list[dict[str, Any]] = []

    def populate_stuck_at_faults(self, circuit: CircuitGraph) -> int:
        """Create stuck-at-0 and stuck-at-1 faults for all nets/nodes in circuit."""
        self.faults.clear()
        nodes = sorted(list(circuit.nets.keys()))
        for node in nodes:
            self.faults[f"{node}/SA0"] = FaultRecord(node=node, fault_type="SA0")
            self.faults[f"{node}/SA1"] = FaultRecord(node=node, fault_type="SA1")
        return len(self.faults)

    def create_patterns(self, circuit: CircuitGraph) -> list[dict[str, Any]]:
        """Synthesize deterministic ATPG test patterns for the given circuit."""
        ctrl = get_control_pins(circuit)
        known_ctrl = {p for p in (ctrl["clk"], ctrl["reset"], ctrl["scan_en"], ctrl["scan_in"]) if p is not None}
        scan_len = len(circuit.scan_cells)
        pi_names = [pi for pi in sorted(circuit.primary_inputs) if pi not in known_ctrl]

        patterns: list[dict[str, Any]] = []

        if scan_len > 0:
            # 1. Base patterns: All 0s and All 1s
            pat_all0 = {"shift_in": [0] * scan_len}
            pat_all1 = {"shift_in": [1] * scan_len}
            for pi in pi_names:
                pat_all0[pi] = 0
                pat_all1[pi] = 1
            patterns.append(pat_all0)
            patterns.append(pat_all1)

            # 2. Walking 1s across scan cells
            for i in range(scan_len):
                bits = [0] * scan_len
                bits[i] = 1
                p = {"shift_in": bits}
                for j, pi in enumerate(pi_names):
                    p[pi] = (i + j) % 2
                patterns.append(p)

            # 3. Walking 0s across scan cells
            for i in range(scan_len):
                bits = [1] * scan_len
                bits[i] = 0
                p = {"shift_in": bits}
                for j, pi in enumerate(pi_names):
                    p[pi] = (i + j + 1) % 2
                patterns.append(p)
        else:
            # Combinational patterns
            p0 = {pi: 0 for pi in pi_names}
            p1 = {pi: 1 for pi in pi_names}
            patterns.extend([p0, p1])
            for i, pi in enumerate(pi_names):
                p_walk1 = {p: (1 if p == pi else 0) for p in pi_names}
                p_walk0 = {p: (0 if p == pi else 1) for p in pi_names}
                patterns.extend([p_walk1, p_walk0])

        self.patterns = patterns
        return patterns

    def simulate_test_patterns(
        self,
        circuit: CircuitGraph,
        test_patterns: list[dict[str, Any]] | None = None,
    ) -> ATPGStatistics:
        """Run true differential fault simulation over test patterns and compute formal coverage."""
        patterns = test_patterns if test_patterns is not None else (self.patterns or self.create_patterns(circuit))

        # Reset all faults to ND
        for f in self.faults.values():
            if f.status not in (FaultClass.UU, FaultClass.TI):
                f.status = FaultClass.ND

        # Step 1: Golden Run (Good Machine with no faults)
        golden_results: list[tuple[dict[str, Logic4], list[Logic4]]] = []
        for pat in patterns:
            good_c = circuit.clone()
            good_c.clear_faults()
            pos, so = execute_test_pattern(good_c, pat)
            golden_results.append((pos, so))

        # Step 2: Differential Simulation for each fault
        for f_key, fault in self.faults.items():
            if fault.status in (FaultClass.UU, FaultClass.TI):
                continue

            target_val = Logic4.ZERO if fault.fault_type == "SA0" else Logic4.ONE
            detected = False
            possibly_detected = False

            for pat, (good_pos, good_so) in zip(patterns, golden_results):
                faulty_c = circuit.clone()
                faulty_c.inject_fault(fault.node, target_val)
                f_pos, f_so = execute_test_pattern(faulty_c, pat)

                # Check PO difference
                for po, g_val in good_pos.items():
                    f_val = f_pos.get(po, Logic4.X)
                    if g_val in (Logic4.ZERO, Logic4.ONE) and f_val in (Logic4.ZERO, Logic4.ONE):
                        if g_val != f_val:
                            detected = True
                            break
                    elif g_val in (Logic4.ZERO, Logic4.ONE) and f_val in (Logic4.X, Logic4.Z):
                        possibly_detected = True

                if detected:
                    break

                # Check Scan Out difference
                for g_bit, f_bit in zip(good_so, f_so):
                    if g_bit in (Logic4.ZERO, Logic4.ONE) and f_bit in (Logic4.ZERO, Logic4.ONE):
                        if g_bit != f_bit:
                            detected = True
                            break
                    elif g_bit in (Logic4.ZERO, Logic4.ONE) and f_bit in (Logic4.X, Logic4.Z):
                        possibly_detected = True

                if detected:
                    break

            if detected:
                fault.status = FaultClass.DS
            elif possibly_detected:
                fault.status = FaultClass.PT
            else:
                fault.status = FaultClass.ND

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
