"""Graph-based netlist representation and logic propagation engine."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from tessent_core.logic4 import (
    Logic4,
    and4,
    buf4,
    mux21,
    not4,
    or4,
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
    internal_state: Logic4 = Logic4.X  # Verilog registers start unknown until initialized
    fault_forced_value: Logic4 | None = None  # Injected stuck-at fault
    reset_kind: str = "async"  # Parser explicitly marks synchronous resets

    def evaluate_output(self, in_values: dict[str, Logic4]) -> Logic4:
        if self.fault_forced_value is not None:
            return self.fault_forced_value

        gt = self.gate_type.upper()
        if gt.startswith("CONST"):
            return Logic4.from_val(gt[5:])
        if gt == "NOT" or gt == "INV":
            in_val = list(in_values.values())[0] if in_values else Logic4.X
            return not4(in_val)
        if gt == "BUF":
            in_val = list(in_values.values())[0] if in_values else Logic4.X
            return buf4(in_val)
        if gt in ("ASSIGN", "WIRE"):
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
        if gt == "IFMUX":
            # A Verilog procedural if takes its else branch for X/Z.
            return in_values.get("d1", Logic4.X) if in_values.get("sel") == Logic4.ONE else in_values.get("d0", Logic4.X)
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
                reset_kind=g.reset_kind,
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
            self.nets[name] = Logic4.Z

    def add_gate(self, gate: Gate) -> None:
        self.gates[gate.name] = gate
        for net in gate.inputs.values():
            if net not in self.nets:
                self.nets[net] = Logic4.Z
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
        """Pulse a clock and update flops only on a rising event at their clock pin.

        This models the synchronous-reset, positive-edge subset emitted by
        insertion.py. It does not model asynchronous events or gate delays.
        """
        if active_edge != "pos":
            raise ValueError("only positive-edge clocks are supported")
        self.propagate_combinational()
        previous = {name: self.nets.get(g.inputs.get("clk", g.inputs.get("CLK", "clk")), Logic4.X)
                    for name, g in self.gates.items() if g.gate_type.upper() == "DFF"}
        if clock_pin not in self.forced_nets:
            self.nets[clock_pin] = Logic4.ONE
        self.propagate_combinational()

        updates: dict[str, Logic4] = {}
        for gate in self.gates.values():
            if gate.gate_type.upper() != "DFF":
                continue
            clk_net = gate.inputs.get("clk", gate.inputs.get("CLK", "clk"))
            clk_val = self.nets.get(clk_net, Logic4.X)
            # Verilog includes X/Z -> 1 in positive-edge events; a stable 1
            # is never an event, including a clock forced stuck at 1.
            if previous[gate.name] == Logic4.ONE or clk_val != Logic4.ONE:
                continue
            d_net = gate.inputs.get("d", gate.inputs.get("D"))
            d_val = self.nets.get(d_net, Logic4.X) if d_net else Logic4.X
            reset_net = gate.inputs.get("reset", gate.inputs.get("R"))
            reset_val = self.nets.get(reset_net, Logic4.X) if reset_net else Logic4.ZERO
            updates[gate.name] = Logic4.ZERO if reset_val == Logic4.ONE else d_val

        for gate_name, new_val in updates.items():
            self.gates[gate_name].internal_state = new_val
        if clock_pin not in self.forced_nets:
            self.nets[clock_pin] = Logic4.ZERO
        self.propagate_combinational()



class _SubsetParser:
    """Read a small, explicit scalar Verilog subset; reject everything else.

    Supported: non-ANSI ports, scalar declarations, bitwise expressions,
    built-in logic primitives, and the synchronous reset/scan always block
    produced by insertion.py. This is not a general Verilog parser.
    """

    _token = re.compile(r"\s+|//[^\n]*|/\*[\s\S]*?\*/|1'[bB][01xXzZ]|[A-Za-z_][A-Za-z0-9_$]*|<=|[(),;@~&|^=]")
    _ident = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
    _ops = {'|': (1, 'OR'), '^': (2, 'XOR'), '&': (3, 'AND')}
    _primitives = {'and', 'or', 'xor', 'nand', 'nor', 'not', 'buf'}

    def __init__(self, source: str):
        self.tokens: list[tuple[str, int]] = []
        offset = 0
        while offset < len(source):
            match = self._token.match(source, offset)
            if not match:
                raise ValueError(f"unsupported Verilog token at line {source.count(chr(10), 0, offset) + 1}")
            tok = match.group()
            if not tok.isspace() and not tok.startswith(('//', '/*')):
                self.tokens.append((tok, source.count('\n', 0, offset) + 1))
            offset = match.end()
        self.i = 0
        self.declared: set[str] = set()
        self.regs: set[str] = set()
        self.inputs: set[str] = set()
        self.outputs: set[str] = set()
        self.driven: set[str] = set()
        self.number = 0
        self.constant_nets: dict[str, str] = {}

    def peek(self) -> str:
        return self.tokens[self.i][0] if self.i < len(self.tokens) else '<end>'

    def fail(self, reason: str) -> None:
        line = self.tokens[self.i][1] if self.i < len(self.tokens) else (self.tokens[-1][1] if self.tokens else 1)
        raise ValueError(f"{reason} at line {line} (near {self.peek()!r})")

    def take(self, value: str) -> None:
        if self.peek() != value:
            self.fail(f"expected {value!r}")
        self.i += 1

    def name(self) -> str:
        name = self.peek()
        if not self._ident.fullmatch(name) or name in {'input', 'output', 'wire', 'reg', 'module', 'endmodule', 'always', 'begin', 'end', 'if', 'else', 'assign', 'posedge'}:
            self.fail('expected scalar identifier; unsupported construct')
        self.i += 1
        return name

    def names(self) -> list[str]:
        result = [self.name()]
        while self.peek() == ',':
            self.take(',')
            result.append(self.name())
        return result

    def expression(self, priority: int = 0):
        if self.peek() == '~':
            self.take('~')
            left = ('NOT', self.expression(4))
        elif self.peek() == '(':
            self.take('(')
            left = self.expression()
            self.take(')')
        elif re.fullmatch(r"1'[bB][01xXzZ]", self.peek()):
            left = ('literal', self.peek()[-1].upper())
            self.i += 1
        else:
            left = ('net', self.name())
        while self.peek() in self._ops and self._ops[self.peek()][0] >= priority:
            prec, op = self._ops[self.peek()]
            self.i += 1
            left = (op, left, self.expression(prec + 1))
        return left

    def assignment_block(self) -> dict[str, tuple]:
        compound = self.peek() == 'begin'
        if compound:
            self.take('begin')
        result = {}
        while True:
            if compound and self.peek() == 'end':
                break
            target = self.name()
            if target in result:
                self.fail('duplicate register assignment')
            self.take('<=')
            result[target] = self.expression()
            self.take(';')
            if not compound:
                break
        if compound:
            self.take('end')
        return result

    def temp(self, label: str) -> str:
        while True:
            self.number += 1
            name = f'__tsim_{label}_{self.number}'
            if name not in self.declared and name not in self.graph.gates:
                return name

    def expr_net(self, expr) -> str:
        op = expr[0]
        if op == 'net':
            if expr[1] not in self.declared:
                self.fail(f"undeclared signal {expr[1]!r}")
            return expr[1]
        if op == 'literal':
            if expr[1] not in self.constant_nets:
                name = self.temp('const')
                self.graph.add_gate(Gate(name=name, gate_type=f'CONST{expr[1]}', outputs={'out': name}))
                self.constant_nets[expr[1]] = name
            return self.constant_nets[expr[1]]
        ins = {'a': self.expr_net(expr[1])}
        if len(expr) > 2:
            ins['b'] = self.expr_net(expr[2])
        name = self.temp('expr')
        self.graph.add_gate(Gate(name=name, gate_type=op, inputs=ins, outputs={'out': name}))
        return name

    def drive(self, target: str) -> None:
        if target not in self.declared:
            self.fail(f"undeclared signal {target!r}")
        if target in self.inputs or target in self.driven:
            self.fail(f"input or multiply driven signal {target!r}")
        self.driven.add(target)

    def parse(self) -> CircuitGraph:
        self.take('module')
        module = self.name()
        self.graph = CircuitGraph(module)
        self.take('(')
        ports = self.names() if self.peek() != ')' else []
        self.take(')'); self.take(';')
        if len(ports) != len(set(ports)):
            self.fail('duplicate port')
        while self.peek() in ('input', 'output', 'wire', 'reg'):
            kind = self.peek(); self.i += 1
            names = self.names(); self.take(';')
            for name in names:
                if name in self.declared:
                    # Classic Verilog permits output q; reg q; for an output register.
                    if kind == 'reg' and name in self.outputs and name not in self.regs:
                        self.regs.add(name)
                        continue
                    self.fail(f"duplicate declaration {name!r}")
                self.declared.add(name)
                if kind == 'input':
                    self.inputs.add(name); self.graph.add_port(name, 'in')
                elif kind == 'output':
                    self.outputs.add(name); self.graph.add_port(name, 'out')
                elif kind == 'reg':
                    self.regs.add(name); self.graph.nets[name] = Logic4.X
                else:
                    self.graph.nets[name] = Logic4.Z
        if set(ports) != self.inputs | self.outputs:
            self.fail('module ports must exactly match scalar input/output declarations')
        while self.peek() != 'endmodule':
            if self.peek() == 'assign':
                self.take('assign'); dest = self.name(); self.take('=')
                expr = self.expression(); self.take(';')
                self.drive(dest)
                if dest in self.regs:
                    self.fail('continuous assignment to a register is unsupported')
                self.graph.add_gate(Gate(self.temp('assign'), 'ASSIGN', {'in': self.expr_net(expr)}, {'out': dest}))
            elif self.peek() in self._primitives:
                kind = self.peek(); self.i += 1
                name = self.name(); self.take('('); pins = self.names(); self.take(')'); self.take(';')
                if len(pins) < 2 or (kind in ('not', 'buf') and len(pins) != 2) or (kind not in ('not', 'buf') and len(pins) < 3):
                    self.fail('unsupported primitive pin count')
                if name in self.graph.gates:
                    self.fail('duplicate gate name')
                for pin in pins:
                    if pin not in self.declared:
                        self.fail(f'undeclared signal {pin!r}')
                self.drive(pins[0])
                self.graph.add_gate(Gate(name, kind.upper(), {f'in{i}': net for i, net in enumerate(pins[1:])}, {'out': pins[0]}))
            elif self.peek() == 'always':
                self.take('always'); self.take('@'); self.take('('); self.take('posedge')
                clk = self.name(); self.take(')'); self.take('begin')
                if clk != 'clk' or clk not in self.inputs:
                    self.fail("unsupported clock: only the primary input 'clk' is supported")
                self.take('if'); self.take('('); reset = self.name(); self.take(')')
                resets = self.assignment_block(); self.take('else')
                scan_en = None
                shifts = None
                if self.peek() == 'if':
                    self.take('if'); self.take('('); scan_en = self.name(); self.take(')')
                    shifts = self.assignment_block(); self.take('else')
                captures = self.assignment_block(); self.take('end')
                if reset not in self.declared or (scan_en is not None and scan_en not in self.declared):
                    self.fail('undeclared reset or scan enable')
                if not resets or set(resets) != set(captures) or (shifts is not None and set(resets) != set(shifts)):
                    self.fail('reset, shift and capture must assign the same registers')
                if any(expr != ('literal', '0') for expr in resets.values()):
                    self.fail('only synchronous active-high reset to zero is supported')
                for dest in resets:
                    if dest not in self.regs:
                        self.fail(f"expected declared register {dest!r}")
                    self.drive(dest)
                    d_net = self.expr_net(captures[dest])
                    if shifts is not None:
                        d1 = self.expr_net(shifts[dest])
                        mux_net = self.temp('scan_mux')
                        self.graph.add_gate(Gate(mux_net, 'IFMUX', {'sel': scan_en, 'd0': d_net, 'd1': d1}, {'out': mux_net}))
                        d_net = mux_net
                    if f'dff_{dest}' in self.graph.gates:
                        self.fail(f'duplicate gate name dff_{dest!s}')
                    self.graph.add_gate(Gate(f'dff_{dest}', 'DFF', {'clk': clk, 'reset': reset, 'd': d_net}, {'Q': dest}, reset_kind='sync'))
                    if shifts is None:
                        self.graph.scan_cells.remove(f'dff_{dest}')
            else:
                self.fail('unsupported Verilog statement')
        self.take('endmodule')
        if self.peek() != '<end>':
            self.fail('unsupported content after endmodule')
        return self.graph


def parse_verilog_netlist(text: str) -> CircuitGraph:
    """Parse a documented scalar Verilog subset; reject unsupported syntax."""
    return _SubsetParser(text).parse()
