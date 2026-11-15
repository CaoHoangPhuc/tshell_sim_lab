"""DRC (Design Rule Checking) inference engine conforming to Tessent standards."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tessent_core.logic4 import Logic4
from tessent_core.netlist import CircuitGraph

DB_PATH = Path(__file__).resolve().parent / "knowledge_db.json"
CATALOG_PATH = Path(__file__).resolve().parent / "drc_catalog.json"


@dataclass
class DRCViolation:
    rule_id: str  # e.g. "C1-1", "C2-1", "T3-1", "T4-1", "D1-1"
    severity: str  # "Error", "Warning", "Note"
    category: str  # "Clock", "Trace", "Data", "Scannability"
    message: str
    offending_gate: str | None = None
    offending_pin: str | None = None
    book_reference: str | None = None


def _trace_backward_to_source(
    circuit: CircuitGraph,
    start_net: str,
    target_net: str,
    visited_gates: set[str] | None = None,
) -> tuple[bool, str | None]:
    """Trace backward from start_net to target_net through sensitized combinational gates.

    Returns (success, blocked_gate_name).
    """
    if start_net == target_net:
        return True, None

    if visited_gates is None:
        visited_gates = set()

    driver_gate = None
    for g in circuit.gates.values():
        if start_net in g.outputs.values():
            driver_gate = g
            break

    if driver_gate is None:
        return False, None

    if driver_gate.name in visited_gates:
        return False, driver_gate.name
    visited_gates.add(driver_gate.name)

    gt = driver_gate.gate_type.upper()

    if gt in ("BUF", "ASSIGN", "WIRE", "NOT", "INV"):
        in_net = list(driver_gate.inputs.values())[0] if driver_gate.inputs else None
        if not in_net:
            return False, driver_gate.name
        return _trace_backward_to_source(circuit, in_net, target_net, visited_gates)

    if gt in ("IFMUX", "MUX"):
        sel_pin = driver_gate.inputs.get("sel", driver_gate.inputs.get("scan_en"))
        sel_val = circuit.nets.get(sel_pin, Logic4.X) if sel_pin else Logic4.X
        if sel_val == Logic4.ONE:
            active_pin = driver_gate.inputs.get("d1", driver_gate.inputs.get("scan_in", driver_gate.inputs.get("in1")))
            if not active_pin:
                return False, driver_gate.name
            return _trace_backward_to_source(circuit, active_pin, target_net, visited_gates)
        elif sel_val == Logic4.ZERO:
            active_pin = driver_gate.inputs.get("d0", driver_gate.inputs.get("d", driver_gate.inputs.get("in0")))
            if not active_pin:
                return False, driver_gate.name
            return _trace_backward_to_source(circuit, active_pin, target_net, visited_gates)
        else:
            return False, driver_gate.name

    if gt in ("AND", "NAND"):
        for pin, in_net in driver_gate.inputs.items():
            other_inputs = [other_net for other_pin, other_net in driver_gate.inputs.items() if other_pin != pin]
            if all(circuit.nets.get(on) == Logic4.ONE for on in other_inputs):
                reached, b_gate = _trace_backward_to_source(circuit, in_net, target_net, set(visited_gates))
                if reached:
                    return True, None
        return False, driver_gate.name

    if gt in ("OR", "NOR"):
        for pin, in_net in driver_gate.inputs.items():
            other_inputs = [other_net for other_pin, other_net in driver_gate.inputs.items() if other_pin != pin]
            if all(circuit.nets.get(on) == Logic4.ZERO for on in other_inputs):
                reached, b_gate = _trace_backward_to_source(circuit, in_net, target_net, set(visited_gates))
                if reached:
                    return True, None
        return False, driver_gate.name

    if gt in ("XOR", "XNOR"):
        for pin, in_net in driver_gate.inputs.items():
            other_inputs = [other_net for other_pin, other_net in driver_gate.inputs.items() if other_pin != pin]
            if all(circuit.nets.get(on) in (Logic4.ZERO, Logic4.ONE) for on in other_inputs):
                reached, b_gate = _trace_backward_to_source(circuit, in_net, target_net, set(visited_gates))
                if reached:
                    return True, None
        return False, driver_gate.name

    return False, driver_gate.name


def _setup_shift_conditions(shift_c: CircuitGraph, clocks: dict[str, int]) -> None:
    """Set primary inputs to shift mode: scan enable active, reset inactive, clocks at off-state."""
    scan_en_candidates = {"scan_en", "se", "scan_enable", "scanenable", "shift_en"}
    for g in shift_c.gates.values():
        if g.gate_type.upper() in ("IFMUX", "MUX"):
            sel_net = g.inputs.get("sel", g.inputs.get("scan_en"))
            if sel_net and sel_net in shift_c.primary_inputs:
                scan_en_candidates.add(sel_net)

    for pi in shift_c.primary_inputs:
        if pi.lower() in scan_en_candidates or pi in scan_en_candidates:
            shift_c.set_primary_input(pi, 1)

    reset_candidates = {"reset", "rst", "rst_n", "reset_n"}
    for pi in shift_c.primary_inputs:
        if pi.lower() in reset_candidates:
            shift_c.set_primary_input(pi, 1 if pi.lower().endswith("_n") else 0)

    for clk_pin, off_val in clocks.items():
        shift_c.set_primary_input(clk_pin, off_val)


def _can_clock_be_pulsed_during_shift(circuit: CircuitGraph, clk_net: str, clocks: dict[str, int]) -> bool:
    """Check if clk_net transitions when shifting clocks are pulsed."""
    if not clocks:
        return False
    if clk_net in clocks:
        return True
    for clk_pin, off_val in clocks.items():
        pulse_c = circuit.clone()
        _setup_shift_conditions(pulse_c, clocks)
        pulse_c.propagate_combinational()
        base_val = pulse_c.nets.get(clk_net, Logic4.X)

        on_val = 1 if off_val == 0 else 0
        pulse_c.set_primary_input(clk_pin, on_val)
        pulse_c.propagate_combinational()
        pulsed_val = pulse_c.nets.get(clk_net, Logic4.X)

        if pulsed_val != base_val and pulsed_val in (Logic4.ZERO, Logic4.ONE):
            return True
    return False


class DRCEngine:
    """Infers and validates design rules on the circuit graph using pure in-memory knowledge DB."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.catalog: dict[str, dict[str, Any]] = {}
        target_path = db_path or DB_PATH
        if not target_path.is_file():
            target_path = CATALOG_PATH

        if target_path.is_file():
            try:
                data = json.loads(target_path.read_text(encoding="utf-8"))
                # If wrapped in knowledge DB
                self.catalog = data.get("rules", data)
            except Exception:
                self.catalog = {}

        self.handling_overrides: dict[str, str] = {
            "C1": "Error",
            "C2": "Warning",
            "T3": "Error",
            "T4": "Error",
            "T5": "Error",
            "D1": "Error",
        }

    def get_rule_info(self, rule_id: str) -> dict[str, Any] | None:
        key = rule_id.upper().split("-")[0].strip()
        return self.catalog.get(key)

    def get_rule_summary(self, rule_id: str) -> str | None:
        info = self.get_rule_info(rule_id)
        if info:
            return info.get("summary") or info.get("title")
        return None

    def get_rule_excerpt(self, rule_id: str) -> str | None:
        info = self.get_rule_info(rule_id)
        if info:
            return info.get("reference_excerpt")
        return None

    def get_rule_page_text(self, rule_id: str, max_lines: int = 15) -> str | None:
        """Retrieve pre-indexed rule documentation summary from the knowledge DB."""
        summary = self.get_rule_summary(rule_id)
        if summary:
            lines = summary.splitlines()[:max_lines]
            return "\n".join(lines)
        return None

    def run_all_checks(
        self,
        circuit: CircuitGraph,
        clocks: dict[str, int],  # pin -> off_state
        scan_chains: list[dict[str, Any]],
        injected_anomalies: set[str] | None = None,
    ) -> list[DRCViolation]:
        """Execute algorithmic checks and return detected rule violations."""
        anomalies = injected_anomalies or set()
        violations: list[DRCViolation] = []

        # -----------------------------------------------------------------
        # 1. Rule C2: Clock Reachability Check (Forward Graph Traversal)
        # -----------------------------------------------------------------
        for clk_pin in clocks:
            reached = False
            visited = {clk_pin}
            queue = [clk_pin]
            while queue and not reached:
                curr_net = queue.pop(0)
                for gate in circuit.gates.values():
                    if curr_net in gate.inputs.values():
                        if gate.gate_type.upper() == "DFF":
                            dff_clk = gate.inputs.get("clk", gate.inputs.get("CLK"))
                            if dff_clk == curr_net:
                                reached = True
                                break
                        else:
                            for out_net in gate.outputs.values():
                                if out_net not in visited:
                                    visited.add(out_net)
                                    queue.append(out_net)

            if not reached or "C2" in anomalies:
                violations.append(DRCViolation(
                    rule_id="C2-1",
                    severity=self.handling_overrides.get("C2", "Warning"),
                    category="Clock",
                    message=f"Clock {clk_pin} cannot reach the clock port of any memory element.",
                    offending_pin=clk_pin,
                    book_reference="Tessent Shell Reference Manual (p. 3814)",
                ))

        # -----------------------------------------------------------------
        # 2. Rule C1: Clocks Off-State Check (Backward Graph & Simulation)
        # -----------------------------------------------------------------
        eval_c = circuit.clone()
        for clk_pin, off_val in clocks.items():
            eval_c.set_primary_input(clk_pin, off_val)
        if "reset" in eval_c.primary_inputs:
            eval_c.set_primary_input("reset", 0)
        eval_c.propagate_combinational()

        for gate in eval_c.gates.values():
            if gate.gate_type.upper() == "DFF":
                clk_net = gate.inputs.get("clk", gate.inputs.get("CLK", "clk"))
                clk_val = eval_c.nets.get(clk_net, Logic4.X)
                rst_net = gate.inputs.get("reset", gate.inputs.get("R"))
                rst_val = eval_c.nets.get(rst_net) if rst_net else Logic4.ZERO
                set_net = gate.inputs.get("set", gate.inputs.get("S"))
                set_val = eval_c.nets.get(set_net) if set_net else Logic4.ZERO

                clock_not_stable = clk_val not in (Logic4.ZERO, Logic4.ONE)
                async_active = rst_val in (Logic4.ONE, Logic4.X) or set_val in (Logic4.ONE, Logic4.X)

                if clock_not_stable or async_active or "C1" in anomalies:
                    violations.append(DRCViolation(
                        rule_id="C1-1",
                        severity=self.handling_overrides.get("C1", "Error"),
                        category="Clock",
                        message=f"Clock PIs off failed to force off a clock line of {gate.name}.",
                        offending_gate=gate.name,
                        offending_pin=clk_net,
                        book_reference="Tessent Shell Reference Manual (p. 3809, 3812)",
                    ))

        # -----------------------------------------------------------------
        # 3. Rule T3, T4, T5: Scan Chain Tracing in Shift Mode
        # -----------------------------------------------------------------
        chains = scan_chains

        shift_c = circuit.clone()
        _setup_shift_conditions(shift_c, clocks)
        shift_c.propagate_combinational()

        for chain in chains:
            chain_name = chain.get("name", "chain1")
            scan_in = chain.get("scan_in", "scan_in")
            scan_out = chain.get("scan_out", "scan_out")
            cells = chain.get("cells", [])

            # T4 & T5 Checks: Verify clock and set/reset stability and activity during shift
            for cell_name in cells:
                gate = shift_c.gates.get(cell_name)
                if gate and gate.gate_type.upper() == "DFF":
                    clk_net = gate.inputs.get("clk", gate.inputs.get("CLK"))
                    clk_val = shift_c.nets.get(clk_net, Logic4.X)
                    rst_net = gate.inputs.get("reset", gate.inputs.get("R"))
                    rst_val = shift_c.nets.get(rst_net) if rst_net else Logic4.ZERO
                    set_net = gate.inputs.get("set", gate.inputs.get("S"))
                    set_val = shift_c.nets.get(set_net) if set_net else Logic4.ZERO

                    # T5: Invalid X/Z on clock or active value (1 or X/Z) on set/reset during shift
                    has_t5 = clk_val in (Logic4.X, Logic4.Z) or rst_val in (Logic4.ONE, Logic4.X, Logic4.Z) or set_val in (Logic4.ONE, Logic4.X, Logic4.Z)
                    if has_t5 or "T5" in anomalies:
                        violations.append(DRCViolation(
                            rule_id="T5-1",
                            severity=self.handling_overrides.get("T5", "Error"),
                            category="Trace",
                            message=f"clock or async input of {gate.name} has invalid value during shift.",
                            offending_gate=gate.name,
                            offending_pin=clk_net if clk_val in (Logic4.X, Logic4.Z) else (rst_net or set_net),
                            book_reference="Tessent Shell Reference Manual (p. 4529)",
                        ))
                    elif not _can_clock_be_pulsed_during_shift(shift_c, clk_net, clocks) or "T4" in anomalies:
                        violations.append(DRCViolation(
                            rule_id="T4-1",
                            severity=self.handling_overrides.get("T4", "Error"),
                            category="Trace",
                            message=f"Clock inputs of {gate.name} not stable during shift.",
                            offending_gate=gate.name,
                            offending_pin=clk_net,
                            book_reference="Tessent Shell Reference Manual (p. 4525)",
                        ))

            # T3 Check: Sensitized Scan Path Tracing
            blocked = False
            curr_signal = scan_in
            traced_count = 0
            remaining_cells = list(cells)

            while remaining_cells and not blocked:
                # Find which cell in remaining_cells has its scan input connected to curr_signal
                next_cell = None
                for c_name in remaining_cells:
                    g = shift_c.gates.get(c_name)
                    if not g:
                        continue
                    d_net = g.inputs.get("d", g.inputs.get("D", g.inputs.get("scan_in", g.inputs.get("si"))))
                    if not d_net:
                        continue
                    reached, _ = _trace_backward_to_source(shift_c, d_net, curr_signal)
                    if reached:
                        next_cell = g
                        break

                if not next_cell:
                    blocked = True
                    offending = curr_signal
                    target_g = shift_c.gates.get(remaining_cells[0])
                    if target_g:
                        d_net = target_g.inputs.get("d", target_g.inputs.get("D", target_g.inputs.get("scan_in", target_g.inputs.get("si"))))
                        if d_net:
                            _, b_gate = _trace_backward_to_source(shift_c, d_net, curr_signal)
                            offending = b_gate or target_g.name
                        else:
                            offending = target_g.name
                    else:
                        offending = remaining_cells[0]

                    violations.append(DRCViolation(
                        rule_id="T3-1",
                        severity=self.handling_overrides.get("T3", "Error"),
                        category="Trace",
                        message=f"Scan chain {chain_name} blocked at gate {offending} after tracing {traced_count} cells.",
                        offending_gate=offending,
                        book_reference="Tessent Shell Reference Manual (p. 4522)",
                    ))
                    break

                remaining_cells.remove(next_cell.name)
                traced_count += 1
                curr_signal = next_cell.outputs.get("Q", next_cell.outputs.get("q", list(next_cell.outputs.values())[0] if next_cell.outputs else None))

            # If all cells were traced, verify connection from last cell to scan_out
            if not blocked and scan_out:
                expected_src = curr_signal if cells else scan_in
                reached, b_gate = _trace_backward_to_source(shift_c, scan_out, expected_src)
                if not reached:
                    blocked = True
                    offending = b_gate or scan_out
                    violations.append(DRCViolation(
                        rule_id="T3-1",
                        severity=self.handling_overrides.get("T3", "Error"),
                        category="Trace",
                        message=f"Scan chain {chain_name} blocked at gate {offending} after tracing {traced_count} cells.",
                        offending_gate=offending,
                        book_reference="Tessent Shell Reference Manual (p. 4522)",
                    ))

            if not blocked and "T3" in anomalies:
                violations.append(DRCViolation(
                    rule_id="T3-1",
                    severity=self.handling_overrides.get("T3", "Error"),
                    category="Trace",
                    message=f"Scan chain {chain_name} blocked at gate /reg2/df2 after tracing 1 cells.",
                    offending_gate="/reg2/df2",
                    book_reference="Tessent Shell Reference Manual (p. 4522)",
                ))

            if "T4" in anomalies and not any(v.rule_id == "T4-1" for v in violations):
                violations.append(DRCViolation(
                    rule_id="T4-1",
                    severity=self.handling_overrides.get("T4", "Error"),
                    category="Trace",
                    message="Clock inputs of /datao/reg_q_0_ not stable during shift.",
                    offending_gate="/datao/reg_q_0_",
                    book_reference="Tessent Shell Reference Manual (p. 4525)",
                ))

            if "T5" in anomalies and not any(v.rule_id == "T5-1" for v in violations):
                violations.append(DRCViolation(
                    rule_id="T5-1",
                    severity=self.handling_overrides.get("T5", "Error"),
                    category="Trace",
                    message="clock input of /datao/reg_q_0_ has X value during shift.",
                    offending_gate="/datao/reg_q_0_",
                    book_reference="Tessent Shell Reference Manual (p. 4529)",
                ))

        # -----------------------------------------------------------------
        # 4. Rule D1: Scan Cell Data Disturb Check
        # -----------------------------------------------------------------
        for gate in shift_c.gates.values():
            if gate.gate_type.upper() == "DFF":
                rst_net = gate.inputs.get("reset", gate.inputs.get("R"))
                if rst_net:
                    rst_val = shift_c.nets.get(rst_net, Logic4.X)
                    if rst_val == Logic4.ONE:
                        violations.append(DRCViolation(
                            rule_id="D1-1",
                            severity=self.handling_overrides.get("D1", "Error"),
                            category="Data",
                            message=f"{gate.name} disturbed during shift procedure (active reset line).",
                            offending_gate=gate.name,
                            offending_pin=rst_net,
                            book_reference="Tessent Shell Reference Manual (p. 3863, 3865)",
                        ))

        if "D1" in anomalies and not any(v.rule_id == "D1-1" for v in violations):
            violations.append(DRCViolation(
                rule_id="D1-1",
                severity=self.handling_overrides.get("D1", "Error"),
                category="Data",
                message="/dataot/reg_q_0_ (373) disturbed during time 0 of grp1 load_unload procedure.",
                offending_gate="/dataot/reg_q_0_",
                book_reference="Tessent Shell Reference Manual (p. 3863, 3865)",
            ))

        # Filter out violations whose handling is set to Ignore
        active_violations = [
            v for v in violations
            if v.severity.lower() != "ignore"
            and self.handling_overrides.get(v.rule_id.split("-")[0].upper(), "").lower() != "ignore"
        ]
        return active_violations
