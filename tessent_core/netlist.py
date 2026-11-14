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
            d0 = in_values.get("d0", in_values.get("in0", in_values.get("d", Logic4.X)))
            d1 = in_values.get("d1", in_values.get("in1", in_values.get("scan_in", Logic4.X)))
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
        self.forced_nets: dict[str, Logic4] = {}  # Injected stuck-at fault overrides

    def clone(self) -> CircuitGraph:
        """Create an isolated, deep replica of the circuit graph with independent state."""
        new_cg = CircuitGraph(name=self.name)
        new_cg.primary_inputs = set(self.primary_inputs)
        new_cg.primary_outputs = set(self.primary_outputs)
        new_cg.scan_cells = list(self.scan_cells)
        new_cg.nets = dict(self.nets)
        new_cg.forced_nets = dict(self.forced_nets)
        for gname, g in self.gates.items():
            new_g = Gate(
                name=g.name,
                gate_type=g.gate_type,
                inputs=dict(g.inputs),
                outputs=dict(g.outputs),
                internal_state=g.internal_state,
                fault_forced_value=g.fault_forced_value,
            )
            new_cg.gates[gname] = new_g
        return new_cg

    def inject_fault(self, node: str, val: Logic4) -> None:
        """Inject a permanent stuck-at fault on a node, net, or gate output."""
        self.forced_nets[node] = val
        self.nets[node] = val
        # If node directly names a gate or output net of a gate
        for gate in self.gates.values():
            if gate.name == node or node in gate.outputs.values():
                gate.fault_forced_value = val
        self.propagate_combinational()

    def clear_faults(self) -> None:
        """Remove all injected stuck-at faults."""
        self.forced_nets.clear()
        for gate in self.gates.values():
            gate.fault_forced_value = None
        self.propagate_combinational()

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
        if name in self.forced_nets:
            self.nets[name] = self.forced_nets[name]
        elif name in self.primary_inputs or name in self.nets:
            self.nets[name] = val

    def propagate_combinational(self) -> None:
        """Topological/iterative relaxation of combinational nets until fixpoint."""
        max_iters = len(self.gates) * 2 + 5
        changed = True
        iterations = 0
        while changed and iterations < max_iters:
            changed = False
            iterations += 1

            # Re-enforce forced stuck-at nets
            for f_net, f_val in self.forced_nets.items():
                if self.nets.get(f_net) != f_val:
                    self.nets[f_net] = f_val
                    changed = True

            for gate in self.gates.values():
                if gate.gate_type.upper() == "DFF":
                    # Output of DFF is driven by internal state
                    out_net = gate.outputs.get("Q", list(gate.outputs.values())[0] if gate.outputs else None)
                    if out_net:
                        val = gate.fault_forced_value if gate.fault_forced_value is not None else gate.internal_state
                        if out_net in self.forced_nets:
                            val = self.forced_nets[out_net]
                        if self.nets.get(out_net) != val:
                            self.nets[out_net] = val
                            changed = True
                    continue

                in_vals = {pin: self.nets.get(net, Logic4.X) for pin, net in gate.inputs.items()}
                out_val = gate.evaluate_output(in_vals)
                for out_net in gate.outputs.values():
                    final_val = self.forced_nets.get(out_net, out_val)
                    if self.nets.get(out_net) != final_val:
                        self.nets[out_net] = final_val
                        changed = True

    def clock_edge(self, clock_pin: str = "clk", active_edge: str = "pos") -> None:
        """Synchronously evaluate and update memory elements on active clock edge (double-buffering)."""
        # If the primary clock pin itself is forced (stuck-at), no dynamic clock transition occurs!
        if clock_pin in self.forced_nets:
            self.propagate_combinational()
            return

        # Step 1: Ensure combinational nets are settled prior to clock edge
        self.propagate_combinational()

        # Step 2: Sample all DFF inputs synchronously at time t
        updates: dict[str, Logic4] = {}
        for gate in self.gates.values():
            if gate.gate_type.upper() == "DFF":
                gate_clk_net = gate.inputs.get("clk", gate.inputs.get("CLK", "clk"))
                # If gate's clock net is forced stuck-at, it cannot toggle
                if gate_clk_net in self.forced_nets:
                    continue

                d_net = gate.inputs.get("d", gate.inputs.get("D", list(gate.inputs.values())[0] if gate.inputs else None))
                d_val = self.nets.get(d_net, Logic4.X) if d_net else Logic4.X

                reset_net = gate.inputs.get("reset", gate.inputs.get("R", None))
                reset_val = self.nets.get(reset_net) if reset_net else Logic4.ZERO

                if reset_val == Logic4.ONE:
                    updates[gate.name] = Logic4.ZERO
                else:
                    updates[gate.name] = d_val

        # Step 3: Concurrently latch states at time t+1
        for gate_name, new_val in updates.items():
            self.gates[gate_name].internal_state = new_val

        # Step 4: Settle network post-latch
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
        clean_expr = expr.strip().strip("()")
        if re.fullmatch(r"[A-Za-z0-9_]+", clean_expr):
            graph.add_gate(Gate(name=f"buf_{target}", gate_type="BUF", inputs={"in": clean_expr}, outputs={"out": target}))
        elif "^" in expr:
            parts = [p.strip().strip("()") for p in expr.split("^")]
            graph.add_gate(Gate(name=f"xor_{target}", gate_type="XOR", inputs={"a": parts[0], "b": parts[1]}, outputs={"out": target}))
        elif "&" in expr:
            parts = [p.strip().strip("()") for p in expr.split("&")]
            graph.add_gate(Gate(name=f"and_{target}", gate_type="AND", inputs={"a": parts[0], "b": parts[1]}, outputs={"out": target}))
        elif "|" in expr:
            parts = [p.strip().strip("()") for p in expr.split("|")]
            graph.add_gate(Gate(name=f"or_{target}", gate_type="OR", inputs={"a": parts[0], "b": parts[1]}, outputs={"out": target}))

    # Extract flip-flop capture and shift sources from always blocks
    shift_sources: dict[str, str] = {}
    func_sources: dict[str, str] = {}

    scan_en_match = re.search(r"if\s*\(\s*scan_en\s*\)\s*begin(.*?)end\s*else\s*begin(.*?)end", text, re.DOTALL)
    if scan_en_match:
        shift_part = scan_en_match.group(1)
        func_part = scan_en_match.group(2)
        for m in re.finditer(r"([A-Za-z0-9_]+)\s*<=\s*([^;]+);", shift_part):
            shift_sources[m.group(1).strip()] = m.group(2).strip().strip("()")
        for m in re.finditer(r"([A-Za-z0-9_]+)\s*<=\s*([^;]+);", func_part):
            func_sources[m.group(1).strip()] = m.group(2).strip()
    else:
        for m in re.finditer(r"([A-Za-z0-9_]+)\s*<=\s*([^;]+);", text):
            target = m.group(1).strip()
            expr = m.group(2).strip()
            if not expr.startswith("1'b0"):
                func_sources[target] = expr

    # Construct flip-flops with scan multiplexers
    if reg_names:
        has_scan = "scan_en" in graph.primary_inputs or "scan_in" in graph.primary_inputs
        for i, r in enumerate(reg_names):
            # Functional capture logic for r
            d_func = func_sources.get(r, "").strip()
            clean_func = d_func.strip("()")
            d_func_net = f"dfunc_{r}"
            if not d_func:
                d_func_net = "scan_in" if i == 0 else reg_names[i - 1]
            elif re.fullmatch(r"[A-Za-z0-9_]+", clean_func):
                d_func_net = clean_func
            elif "^" in d_func:
                parts = [p.strip().strip("()") for p in d_func.split("^")]
                graph.add_gate(Gate(name=f"xor_dfunc_{r}", gate_type="XOR", inputs={"a": parts[0], "b": parts[1]}, outputs={"out": d_func_net}))
            elif "&" in d_func:
                parts = [p.strip().strip("()") for p in d_func.split("&")]
                graph.add_gate(Gate(name=f"and_dfunc_{r}", gate_type="AND", inputs={"a": parts[0], "b": parts[1]}, outputs={"out": d_func_net}))
            elif "|" in d_func:
                parts = [p.strip().strip("()") for p in d_func.split("|")]
                graph.add_gate(Gate(name=f"or_dfunc_{r}", gate_type="OR", inputs={"a": parts[0], "b": parts[1]}, outputs={"out": d_func_net}))
            else:
                d_func_net = clean_func

            # If scan chain is enabled, insert Scan MUX (sel=scan_en, in0=capture, in1=shift)
            if has_scan:
                d_shift = shift_sources.get(r, "scan_in" if i == 0 else reg_names[i - 1])
                mux_out = f"dmux_{r}"
                graph.add_gate(Gate(
                    name=f"scan_mux_{r}",
                    gate_type="MUX",
                    inputs={"sel": "scan_en", "in0": d_func_net, "in1": d_shift},
                    outputs={"out": mux_out},
                ))
                d_target = mux_out
            else:
                d_target = d_func_net

            graph.add_gate(Gate(
                name=f"dff_{r}",
                gate_type="DFF",
                inputs={"clk": "clk", "reset": "reset", "d": d_target},
                outputs={"Q": r},
            ))

    return graph
