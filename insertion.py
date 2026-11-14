#!/usr/bin/env python3
"""Insert one generic scan chain in a deliberately restricted JSON circuit.

This educational tool does not read arbitrary RTL and is not Tessent.
"""

from __future__ import annotations

import argparse
import ast
import json
import keyword
import re
from pathlib import Path


EXAMPLE = {
    "module": "serial_adder_scan",
    "inputs": ["a", "b"],
    "outputs": {"sum": "q0 ^ q1"},
    "flip_flops": [{"name": "q0", "d": "a ^ q1"},
                   {"name": "q1", "d": "q0 & b"}],
}

KEYWORDS = frozenset("""always and assign automatic begin buf bufif0 bufif1 case casex casez
cell cmos config deassign default defparam design disable edge else end endcase endconfig
endfunction endgenerate endmodule endprimitive endspecify endtable endtask event for force forever
fork function generate genvar highz0 highz1 if ifnone incdir include initial inout input instance
integer join large liblist library localparam macromodule medium module nand negedge nmos nor
noshowcancelled not notif0 notif1 or output parameter pmos posedge primitive pull0 pull1 pulldown
pullup pulsestyle_ondetect pulsestyle_onevent rcmos real realtime reg release repeat rnmos rpmos
rtran rtranif0 rtranif1 scalared showcancelled signed small specify specparam strong0 strong1
supply0 supply1 table task time tran tranif0 tranif1 tri tri0 tri1 triand trior trireg unsigned use
vectored wait wand weak0 weak1 while wire wor xnor xor""".split())
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FIXED = {"clk", "reset", "scan_en", "scan_in", "scan_out"}


def identifier(value: object) -> str:
    if (not isinstance(value, str) or not IDENTIFIER.fullmatch(value)
            or value in KEYWORDS or keyword.iskeyword(value)):
        raise ValueError(f"invalid Verilog identifier: {value!r}")
    return value


def expression(value: object, signals: set[str]) -> str:
    """Translate scalar bitwise expressions using a whitelist, never eval them."""
    if not isinstance(value, str):
        raise ValueError("expression must be a string")
    try:
        tree = ast.parse(value, mode="eval")
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"invalid expression: {value!r}") from exc

    def render(node: ast.AST) -> str:
        if isinstance(node, ast.Name) and node.id in signals:
            return node.id
        if isinstance(node, ast.Constant) and type(node.value) is int and node.value in (0, 1):
            return f"1'b{node.value}"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert):
            return f"(~{render(node.operand)})"
        if isinstance(node, ast.BinOp) and type(node.op) in (ast.BitAnd, ast.BitOr, ast.BitXor):
            op = {ast.BitAnd: "&", ast.BitOr: "|", ast.BitXor: "^"}[type(node.op)]
            return f"({render(node.left)} {op} {render(node.right)})"
        raise ValueError(f"unsupported expression or unknown signal: {value!r}")

    return render(tree.body)


def insert_scan(spec: object) -> tuple[str, str]:
    if not isinstance(spec, dict) or set(spec) != {"module", "inputs", "outputs", "flip_flops"}:
        raise ValueError("spec must contain only module, inputs, outputs and flip_flops")
    module = identifier(spec["module"])
    inputs, outputs, flops = spec["inputs"], spec["outputs"], spec["flip_flops"]
    if not isinstance(inputs, list) or not isinstance(outputs, dict) or not outputs:
        raise ValueError("inputs must be a list and outputs a nonempty object")
    if not isinstance(flops, list) or not flops:
        raise ValueError("flip_flops must be a nonempty list")
    if any(not isinstance(f, dict) or set(f) != {"name", "d"} for f in flops):
        raise ValueError("each flip-flop must contain only name and d")
    input_names = [identifier(x) for x in inputs]
    output_names = [identifier(x) for x in outputs]
    ff_names = [identifier(f["name"]) for f in flops]
    names = input_names + output_names + ff_names
    if len(names) != len(set(names)) or set(names) & FIXED:
        raise ValueError("duplicate signal name or reserved scan/control port name")
    signals = set(input_names + ff_names)
    d = [expression(f["d"], signals) for f in flops]
    output_expr = {name: expression(expr, signals) for name, expr in outputs.items()}

    ports = ["clk", "reset", *input_names, "scan_en", "scan_in", *output_names, "scan_out"]
    lines = ["// Educational generic scan insertion; not a technology-mapped netlist.",
             f"module {module}({', '.join(ports)});",
             f"  input {', '.join(['clk', 'reset', *input_names, 'scan_en', 'scan_in'])};",
             f"  output {', '.join([*output_names, 'scan_out'])};",
             f"  reg {', '.join(ff_names)};", "",
             "  always @(posedge clk) begin", "    if (reset) begin"]
    lines.extend(f"      {name} <= 1'b0;" for name in ff_names)
    lines.append("    end else if (scan_en) begin")
    for name, source in zip(ff_names, ["scan_in", *ff_names[:-1]]):
        lines.append(f"      {name} <= {source};")
    lines.append("    end else begin")
    lines.extend(f"      {name} <= {expr};" for name, expr in zip(ff_names, d))
    lines.extend(["    end", "  end", ""])
    lines.extend(f"  assign {name} = {expr};" for name, expr in output_expr.items())
    lines.extend([f"  assign scan_out = {ff_names[-1]};", "endmodule", ""])
    chain = " -> ".join(["scan_in", *ff_names, "scan_out"])
    report = (f"Educational generic scan insertion\nModule: {module}\nFlip-flops: {len(ff_names)}\n"
              f"Chains: 1\nChain 0: {chain}\n"
              "Clock: clk (posedge); reset: synchronous active-high; scan enable: active-high\n")
    return "\n".join(lines), report


def main() -> int:
    parser = argparse.ArgumentParser(description="Insert a generic scan chain into a restricted JSON model; not Tessent.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--spec", type=Path, help="restricted JSON design description")
    source.add_argument("--example", action="store_true", help="use the built-in two-flop example")
    parser.add_argument("-o", "--output", type=Path, required=True, help="generated Verilog path")
    args = parser.parse_args()
    report_path = args.output.with_suffix(".scan.txt")
    try:
        paths = [args.output, report_path] + ([args.spec] if args.spec else [])
        collision = any(
            left.resolve() == right.resolve()
            or (left.exists() and right.exists() and left.samefile(right))
            for i, left in enumerate(paths) for right in paths[i + 1:]
        )
        if collision:
            raise ValueError("input, output and report paths must be distinct")
        spec = json.loads(args.spec.read_text(encoding="utf-8")) if args.spec else EXAMPLE
        verilog, report = insert_scan(spec)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(verilog, encoding="utf-8")
        report_path.write_text(report, encoding="utf-8")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(report, end="")
    print(f"Verilog: {args.output}\nReport: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
