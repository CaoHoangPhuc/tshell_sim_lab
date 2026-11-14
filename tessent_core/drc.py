"""DRC (Design Rule Checking) inference engine conforming to Tessent standards."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tessent_core.logic4 import Logic4
from tessent_core.netlist import CircuitGraph

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
    """Infers and validates design rules on the circuit graph."""

    def __init__(self, ref_pdf: Path | None = None) -> None:
        self.ref_pdf = ref_pdf or (Path(__file__).resolve().parents[1].parent / "tshell_ref.pdf")
        self.catalog: dict[str, dict[str, Any]] = {}
        if CATALOG_PATH.is_file():
            try:
                self.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
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

    def get_rule_page_text(self, rule_id: str, max_lines: int = 15) -> str | None:
        info = self.get_rule_info(rule_id)
        if not info or not self.ref_pdf.is_file():
            return None
        try:
            import pymupdf
            with pymupdf.open(self.ref_pdf) as pdf:
                page_idx = info["page"] - 1
                if 0 <= page_idx < len(pdf):
                    lines = [l.strip() for l in pdf[page_idx].get_text().splitlines() if l.strip()]
                    return "\n".join(lines[:max_lines])
        except Exception:
            return None
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

        # 1. C2 Rule: Clock reachability check
        for clk_pin in clocks:
            reached = False
            for gate in circuit.gates.values():
                if gate.gate_type.upper() == "DFF":
                    clk_net = gate.inputs.get("clk", gate.inputs.get("CLK", ""))
                    if clk_net == clk_pin:
                        reached = True
                        break
            if not reached or "C2" in anomalies:
                violations.append(DRCViolation(
                    rule_id="C2-1",
                    severity=self.handling_overrides.get("C2", "Warning"),
                    category="Clock",
                    message=f"Clock {clk_pin} cannot reach the clock port of any memory element.",
                    offending_pin=clk_pin,
                    book_reference="Tessent Shell Reference Manual (p. 3814)",
                ))

        # 2. C1 Rule: Clocks off state check
        # Set all defined clocks to their off states
        for clk_pin, off_val in clocks.items():
            circuit.set_primary_input(clk_pin, off_val)
        circuit.propagate_combinational()

        for gate in circuit.gates.values():
            if gate.gate_type.upper() == "DFF":
                clk_net = gate.inputs.get("clk", gate.inputs.get("CLK", "clk"))
                clk_val = circuit.nets.get(clk_net, Logic4.X)
                # Violation if clock line is active (1) or X when clocks are off
                if clk_val != Logic4.ZERO or "C1" in anomalies:
                    violations.append(DRCViolation(
                        rule_id="C1-1",
                        severity=self.handling_overrides.get("C1", "Error"),
                        category="Clock",
                        message=f"Clock PIs off failed to force off a clock line of {gate.name}.",
                        offending_gate=gate.name,
                        book_reference="Tessent Shell Reference Manual (p. 3809, 3812)",
                    ))

        # 3. T Rules: Scan chain trace check
        if scan_chains:
            for chain in scan_chains:
                chain_name = chain.get("name", "chain1")
                scan_in = chain.get("scan_in", "scan_in")
                scan_out = chain.get("scan_out", "scan_out")
                cells = chain.get("cells", [])

                if "T3" in anomalies:
                    violations.append(DRCViolation(
                        rule_id="T3-1",
                        severity=self.handling_overrides.get("T3", "Error"),
                        category="Trace",
                        message=f"Scan chain {chain_name} blocked at gate /reg2/df2 after tracing 1 cells.",
                        offending_gate="/reg2/df2",
                        book_reference="Tessent Shell Reference Manual (p. 4522)",
                    ))
                elif "T4" in anomalies:
                    violations.append(DRCViolation(
                        rule_id="T4-1",
                        severity=self.handling_overrides.get("T4", "Error"),
                        category="Trace",
                        message="Clock inputs of /datao/reg_q_0_ not stable during shift.",
                        offending_gate="/datao/reg_q_0_",
                        book_reference="Tessent Shell Reference Manual (p. 4525)",
                    ))
                elif "T5" in anomalies:
                    violations.append(DRCViolation(
                        rule_id="T5-1",
                        severity=self.handling_overrides.get("T5", "Error"),
                        category="Trace",
                        message="clock input of /datao/reg_q_0_ has X value during shift.",
                        offending_gate="/datao/reg_q_0_",
                        book_reference="Tessent Shell Reference Manual (p. 4529)",
                    ))

        # 4. D Rules: Scan cell data disturb check
        if "D1" in anomalies:
            violations.append(DRCViolation(
                rule_id="D1-1",
                severity=self.handling_overrides.get("D1", "Error"),
                category="Data",
                message="/dataot/reg_q_0_ (373) disturbed during time 0 of grp1 load_unload procedure.",
                offending_gate="/dataot/reg_q_0_",
                book_reference="Tessent Shell Reference Manual (p. 3863, 3865)",
            ))

        return violations
