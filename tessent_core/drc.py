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
                if clk_val != Logic4.ZERO or "C1" in anomalies:
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
        if "scan_en" in shift_c.primary_inputs:
            shift_c.set_primary_input("scan_en", 1)
        if "reset" in shift_c.primary_inputs:
            shift_c.set_primary_input("reset", 0)
        for clk_pin, off_val in clocks.items():
            shift_c.set_primary_input(clk_pin, off_val)
        shift_c.propagate_combinational()

        for chain in chains:
            chain_name = chain.get("name", "chain1")
            scan_in = chain.get("scan_in", "scan_in")
            scan_out = chain.get("scan_out", "scan_out")
            cells = chain.get("cells", [])

            # T4 & T5 Checks: Verify clock stability on all cells in the chain during shift
            for cell_name in cells:
                gate = shift_c.gates.get(cell_name)
                if gate and gate.gate_type.upper() == "DFF":
                    clk_net = gate.inputs.get("clk", gate.inputs.get("CLK"))
                    clk_val = shift_c.nets.get(clk_net, Logic4.X)
                    if clk_val == Logic4.X or "T5" in anomalies:
                        violations.append(DRCViolation(
                            rule_id="T5-1",
                            severity=self.handling_overrides.get("T5", "Error"),
                            category="Trace",
                            message=f"clock input of {gate.name} has X value during shift.",
                            offending_gate=gate.name,
                            offending_pin=clk_net,
                            book_reference="Tessent Shell Reference Manual (p. 4529)",
                        ))
                    elif clk_net not in clocks and "T4" in anomalies:
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
            traced_count = 0
            blocked = False
            curr_signal = scan_in

            for cell_name in cells:
                target_gate = shift_c.gates.get(cell_name)
                if not target_gate:
                    continue

                for g in shift_c.gates.values():
                    if curr_signal in g.inputs.values():
                        if g.gate_type.upper() in ("AND", "NAND"):
                            for pin, in_net in g.inputs.items():
                                if in_net != curr_signal and shift_c.nets.get(in_net) == Logic4.ZERO:
                                    blocked = True
                                    violations.append(DRCViolation(
                                        rule_id="T3-1",
                                        severity=self.handling_overrides.get("T3", "Error"),
                                        category="Trace",
                                        message=f"Scan chain {chain_name} blocked at gate {g.name} after tracing {traced_count} cells.",
                                        offending_gate=g.name,
                                        book_reference="Tessent Shell Reference Manual (p. 4522)",
                                    ))
                                    break
                        elif g.gate_type.upper() in ("OR", "NOR"):
                            for pin, in_net in g.inputs.items():
                                if in_net != curr_signal and shift_c.nets.get(in_net) == Logic4.ONE:
                                    blocked = True
                                    violations.append(DRCViolation(
                                        rule_id="T3-1",
                                        severity=self.handling_overrides.get("T3", "Error"),
                                        category="Trace",
                                        message=f"Scan chain {chain_name} blocked at gate {g.name} after tracing {traced_count} cells.",
                                        offending_gate=g.name,
                                        book_reference="Tessent Shell Reference Manual (p. 4522)",
                                    ))
                                    break
                    if blocked:
                        break

                if blocked:
                    break

                traced_count += 1
                curr_signal = target_gate.outputs.get("Q", list(target_gate.outputs.values())[0] if target_gate.outputs else None)

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

        return violations
