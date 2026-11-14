"""Session State and FSM (Finite State Machine) for Tessent Shell."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tessent_core.atpg import ATPGEngine, ATPGStatistics
from tessent_core.drc import DRCEngine, DRCViolation
from tessent_core.netlist import CircuitGraph, parse_verilog_netlist


@dataclass
class ClockSpec:
    pin: str
    off_state: int
    period: float = 100.0
    duty_cycle: float = 50.0


class SessionFSM:
    """Finite State Machine enforcing Tessent Contexts, System Modes, and Rules."""

    VALID_CONTEXTS = (
        "dft -scan",
        "dft -test_points",
        "patterns -scan",
        "patterns -scan_diagnosis",
    )

    VALID_MODES = ("setup", "analysis")

    def __init__(self) -> None:
        self.context: str = "patterns -scan"
        self.system_mode: str = "setup"
        self.circuit: CircuitGraph = CircuitGraph()
        self.clocks: dict[str, ClockSpec] = {}
        self.scan_chains: list[dict[str, Any]] = []
        self.pin_constraints: dict[str, int] = {}
        self.drc_engine = DRCEngine()
        self.atpg_engine = ATPGEngine()
        self.last_drc_violations: list[DRCViolation] = []
        self.last_statistics: ATPGStatistics = ATPGStatistics()
        self.injected_anomalies: set[str] = set()

    def set_context(self, context_str: str) -> tuple[bool, str]:
        c = context_str.strip().lower()
        for vc in self.VALID_CONTEXTS:
            if c == vc or c.startswith(vc) or vc.startswith(c):
                self.context = vc
                return True, f"//  Context set to: {self.context}"
        self.context = context_str.strip()
        return True, f"//  Context set to: {self.context}"

    def set_system_mode(self, mode: str) -> tuple[bool, str]:
        m = mode.strip().lower()
        if m not in self.VALID_MODES:
            return False, f"//  Error: Invalid system mode '{mode}'. Supported: setup, analysis."

        if m == "analysis" and self.system_mode == "setup":
            # Run DRC checks upon transition to analysis
            violations = self.run_drc()
            self.system_mode = "analysis"
            drc_summary = (
                f"//  Transitioning to analysis mode...\n"
                f"//  DRC analysis completed with {len(violations)} violation(s).\n"
                f"//  System mode is now: {self.system_mode}"
            )
            return True, drc_summary

        self.system_mode = m
        return True, f"//  System mode is now: {self.system_mode}"

    def load_verilog(self, path: Path) -> tuple[bool, str]:
        if not path.is_file():
            return False, f"//  Error: File '{path}' not found."
        text = path.read_text(encoding="utf-8")
        self.circuit = parse_verilog_netlist(text)

        # Default scan chain if scan ports exist
        if "scan_in" in self.circuit.primary_inputs and "scan_out" in self.circuit.primary_outputs:
            self.scan_chains = [{
                "name": "chain1",
                "scan_in": "scan_in",
                "scan_out": "scan_out",
                "cells": [g.name for g in self.circuit.gates.values() if g.gate_type.upper() == "DFF"],
            }]

        return True, (
            f"//  Reading Verilog design '{path.name}'...\n"
            f"//  Module: {self.circuit.name}\n"
            f"//  Primary inputs: {len(self.circuit.primary_inputs)}, outputs: {len(self.circuit.primary_outputs)}\n"
            f"//  Sequential elements: {len(self.circuit.scan_cells)} DFF scan cells"
        )

    def add_clock(self, pin: str, off_state: int = 0) -> str:
        self.clocks[pin] = ClockSpec(pin=pin, off_state=off_state)
        return f"//  Added clock '{pin}' with off-state={off_state}."

    def run_drc(self) -> list[DRCViolation]:
        clock_dict = {p: c.off_state for p, c in self.clocks.items()}
        self.last_drc_violations = self.drc_engine.run_all_checks(
            circuit=self.circuit,
            clocks=clock_dict,
            scan_chains=self.scan_chains,
            injected_anomalies=self.injected_anomalies,
        )
        return self.last_drc_violations

    def add_faults(self, target: str = "-all") -> str:
        count = self.atpg_engine.populate_stuck_at_faults(self.circuit)
        return f"//  Added {count} stuck-at faults on {len(self.circuit.nets)} nets/nodes."

    def simulate_patterns(self) -> ATPGStatistics:
        self.last_statistics = self.atpg_engine.simulate_test_patterns(self.circuit)
        return self.last_statistics
