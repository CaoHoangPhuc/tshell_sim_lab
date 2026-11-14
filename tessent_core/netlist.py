"""Graph-based netlist representation and logic propagation engine."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tessent_core.logic4 import (
    Logic4,
    and4,
    mux21,
    nand4,
    nor4,
    not4,
    or4,
    xnor4,
    xor4,
)


@dataclass
class Pin:
    name: str
    direction: str  # "in", "out"
    value: Logic4 = Logic4.X
    net_name: str | None = None


@dataclass
class Gate:
    name: str
    gate_type: str  # "AND", "OR", "XOR", "NOT", "BUF", "MUX", "DFF", "PRIMITIVE"
    inputs: dict[str, str] = field(default_factory=dict)  # pin_name -> net_name
    outputs: dict[str, str] = field(default_factory=dict)  # pin_name -> net_name
    internal_state: Logic4 = Logic4.ZERO  # For DFF / sequential elements
    fault_forced_value: Logic4 | None = None  # Injected stuck-at fault

    def evaluate_output(self, in_values: dict[str, Logic4]) -> Logic4:
        if self.fault_forced_value is not None:
            return self.fault_forced_value

        gt = self.gate_type.upper()
        if gt == "NOT" or gt == "INV":
            in_val = list(in_values.values())[0] if in_values else Logic4.X
            return not4(in_val)
        if gt == "BUF":
            return list(in_values.values())[0] if in_values else Logic4.X
        if gt == "AND":
            vals = list(in_values.values())
            res = vals[0] if vals else Logic4.X
            for v in vals[1:]:
                res = and4(res, v)
            return res
        if gt == "OR":
            vals = list(in_values.values())
            res = vals[0] if vals else Logic4.X
            for v in vals[1:]:
                res = or4(res, v)
            return res
        if gt == "XOR":
            vals = list(in_values.values())
            res = vals[0] if vals else Logic4.X
            for v in vals[1:]:
                res = xor4(res, v)
            return res
        if gt == "NAND":
            vals = list(in_values.values())
            res = vals[0] if vals else Logic4.X
            for v in vals[1:]:
                res = and4(res, v)
            return not4(res)
        if gt == "NOR":
            vals = list(in_values.values())
            res = vals[0] if vals else Logic4.X
            for v in vals[1:]:
                res = or4(res, v)
            return not4(res)
        if gt == "MUX":
            sel = in_values.get("sel", in_values.get("scan_en", Logic4.ZERO))
            d0 = in_values.get("d0", in_values.get("d", Logic4.X))
            d1 = in_values.get("d1", in_values.get("scan_in", Logic4.X))
            return mux21(sel, d0, d1)
        if gt == "DFF":
            return self.internal_state
        return Logic4.X


class CircuitGraph:
    """Manages the graph of gates, nets, and primary ports."""

    def __init__(self, name: str = "top") -> None:
        self.name = name
        self.primary_inputs: set[str] = set()
        self.primary_outputs: set[str] = set()
        self.gates: dict[str, Gate] = {}
        self.nets: dict[str, Logic4] = {}  # net_name -> current value
        self.scan_cells: list[str] = []  # Names of DFF gates in scan chains

    def add_port(self, name: str, direction: str) -> None:
        if direction == "in":
            self.primary_inputs.add(name)
            self.nets[name] = Logic4.X
        else:
            self.primary_outputs.add(name)
            self.nets[name] = Logic4.X

    def add_gate(self, gate: Gate) -> None:
        self.gates[gate.name] = gate
        for net in gate.inputs.values():
            if net not in self.nets:
                self.nets[net] = Logic4.X
        for net in gate.outputs.values():
            if net not in self.nets:
                self.nets[net] = Logic4.X
        if gate.gate_type.upper() == "DFF":
            if gate.name not in self.scan_cells:
                self.scan_cells.append(gate.name)

    def set_primary_input(self, name: str, value: Logic4 | str | int) -> None:
        val = Logic4.from_val(value)
        if name in self.primary_inputs or name in self.nets:
            self.nets[name] = val

    def propagate_combinational(self) -> None:
        """Topological/iterative relaxation of combinational nets until fixpoint."""
        max_iters = len(self.gates) * 2 + 5
        changed = True
        iterations = 0
        while changed and iterations < max_iters:
            changed = False
            iterations += 1
            for gate in self.gates.values():
                if gate.gate_type.upper() == "DFF":
                    # Output of DFF is driven by internal state
                    out_net = gate.outputs.get("Q", list(gate.outputs.values())[0] if gate.outputs else None)
                    if out_net:
                        val = gate.fault_forced_value or gate.internal_state
                        if self.nets.get(out_net) != val:
                            self.nets[out_net] = val
                            changed = True
                    continue

                in_vals = {pin: self.nets.get(net, Logic4.X) for pin, net in gate.inputs.items()}
                out_val = gate.evaluate_output(in_vals)
                for out_net in gate.outputs.values():
                    if self.nets.get(out_net) != out_val:
                        self.nets[out_net] = out_val
                        changed = True

    def clock_edge(self, clock_pin: str = "clk", active_edge: str = "pos") -> None:
        """Evaluate memory element updates on active clock edge."""
        self.propagate_combinational()
        updates = {}
        for gate in self.gates.values():
            if gate.gate_type.upper() == "DFF":
                # Check clock pin
                gate_clk_net = gate.inputs.get("clk", gate.inputs.get("CLK", "clk"))
                gate_clk_val = self.nets.get(gate_clk_net, Logic4.X)
                # D input
                d_net = gate.inputs.get("d", gate.inputs.get("D", list(gate.inputs.values())[0] if gate.inputs else None))
                d_val = self.nets.get(d_net, Logic4.X) if d_net else Logic4.X

                # Reset check (synchronous or asynchronous active high reset)
                reset_net = gate.inputs.get("reset", gate.inputs.get("R", None))
                if reset_net and self.nets.get(reset_net) == Logic4.ONE:
                    updates[gate.name] = Logic4.ZERO
                elif gate_clk_val == Logic4.ONE:
                    updates[gate.name] = d_val
                elif gate_clk_val == Logic4.X:
                    updates[gate.name] = Logic4.X

        for gate_name, new_val in updates.items():
            self.gates[gate_name].internal_state = new_val

        self.propagate_combinational()


def parse_verilog_netlist(text: str) -> CircuitGraph:
    """Parse structural Verilog netlist into CircuitGraph."""
    mod_match = re.search(r"\bmodule\s+([A-Za-z0-9_]+)\s*\((.*?)\);", text, re.DOTALL)
    mod_name = mod_match.group(1) if mod_match else "top"
    graph = CircuitGraph(name=mod_name)

    # Ports
    in_matches = re.findall(r"\binput\s+([^;]+);", text)
    for m in in_matches:
        for port in m.split(","):
            port = port.strip()
            if port:
                graph.add_port(port, "in")

    out_matches = re.findall(r"\boutput\s+([^;]+);", text)
    for m in out_matches:
        for port in m.split(","):
            port = port.strip()
            if port:
                graph.add_port(port, "out")

    # Flip-flops from reg or assign
    reg_matches = re.findall(r"\breg\s+([^;]+);", text)
    reg_names = []
    for m in reg_matches:
        for r in m.split(","):
            r = r.strip()
            if r:
                reg_names.append(r)

    # Continuous assignments: assign <net> = <expr>;
    assign_matches = re.findall(r"\bassign\s+([A-Za-z0-9_]+)\s*=\s*([^;]+);", text)
    for target, expr in assign_matches:
        target = target.strip()
        expr = expr.strip()
        # Simple signal alias
        if re.fullmatch(r"[A-Za-z0-9_]+", expr):
            graph.add_gate(Gate(name=f"buf_{target}", gate_type="BUF", inputs={"in": expr}, outputs={"out": target}))
        elif "^" in expr:
            parts = [p.strip() for p in expr.split("^")]
            graph.add_gate(Gate(name=f"xor_{target}", gate_type="XOR", inputs={"a": parts[0], "b": parts[1]}, outputs={"out": target}))
        elif "&" in expr:
            parts = [p.strip() for p in expr.split("&")]
            graph.add_gate(Gate(name=f"and_{target}", gate_type="AND", inputs={"a": parts[0], "b": parts[1]}, outputs={"out": target}))
        elif "|" in expr:
            parts = [p.strip() for p in expr.split("|")]
            graph.add_gate(Gate(name=f"or_{target}", gate_type="OR", inputs={"a": parts[0], "b": parts[1]}, outputs={"out": target}))

    # If scan chain pattern (q0 <= scan_in; q1 <= q0; etc.)
    if reg_names:
        for i, r in enumerate(reg_names):
            d_in = "scan_in" if i == 0 else reg_names[i - 1]
            graph.add_gate(Gate(
                name=f"dff_{r}",
                gate_type="DFF",
                inputs={"clk": "clk", "reset": "reset", "d": d_in},
                outputs={"Q": r},
            ))

    return graph
