#!/usr/bin/env python3
"""Tessent™ Shell Mock Environment (tshell).

An educational, interactive Tcl-like mock shell modeling Tessent Shell commands,
contexts, system modes, DRC rule inspection, scan chains, and fault simulation.
Built upon the 5-layer deductive EDA architecture and validated against
the official Siemens EDA Reference Manuals.
"""

from __future__ import annotations

import argparse
import cmd
import shlex
import sys
from pathlib import Path

LAB_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB_DIR))

from tessent_core.atpg import ATPGStatistics, FaultClass
from tessent_core.drc import DRCViolation
from tessent_core.logic4 import Logic4
from tessent_core.netlist import CircuitGraph, Gate
from tessent_core.state import SessionFSM


class TessentShell(cmd.Cmd):
    """Interactive command shell conforming to Tessent CLI conventions."""

    intro = (
        "\n  ------------------------------------------------------------\n"
        "  Siemens EDA Tessent™ Shell (Mock Environment v2026.2)\n"
        "  Validated against Reference Manual Testunits\n"
        "  Type 'help' or '?' to list commands. Type 'exit' to quit.\n"
        "  ------------------------------------------------------------\n"
    )

    def __init__(self, fsm: SessionFSM | None = None) -> None:
        super().__init__()
        self.fsm = fsm or SessionFSM()
        self.gate_level: str = "primitive"  # primitive or design
        self.gate_report: str = "trace"  # trace or error_pattern
        self.trace_report: bool = True
        self.tsdb_dir: Path = LAB_DIR / "tsdb"
        self.update_prompt()

    def update_prompt(self) -> None:
        mode_str = self.fsm.system_mode.upper()
        self.prompt = f"tshell ({mode_str})> "

    def precmd(self, line: str) -> str:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            return ""
        return line

    def onecmd(self, line: str) -> bool:
        line = self.precmd(line)
        if not line:
            return self.emptyline()
        return super().onecmd(line)

    def emptyline(self) -> bool:
        return False

    def default(self, line: str) -> bool:
        cmd_name = line.split()[0] if line.split() else ""
        print(f"//  Error: Unknown command or syntax error: '{cmd_name}'. Type 'help' for available commands.")
        return False

    def do_set_context(self, arg: str) -> None:
        """set_context <context> [-<option>] : Set application context (e.g. dft -scan, patterns -scan)"""
        args = arg.strip()
        if not args:
            print(f"//  Current context: {self.fsm.context}")
            return
        _, msg = self.fsm.set_context(args)
        print(msg)

    def do_report_context(self, arg: str) -> None:
        """report_context : Display current context"""
        print(f"//  Context: {self.fsm.context}")

    def do_set_system_mode(self, arg: str) -> None:
        """set_system_mode <setup | analysis> : Switch system mode (triggers DRC on setup -> analysis)"""
        mode = arg.strip().lower()
        ok, msg = self.fsm.set_system_mode(mode)
        print(msg)
        if ok:
            self.update_prompt()

    def do_report_system_mode(self, arg: str) -> None:
        """report_system_mode : Display current system mode"""
        print(f"//  System mode: {self.fsm.system_mode}")

    def do_read_verilog(self, arg: str) -> None:
        """read_verilog <filepath> : Read design netlist in Verilog format"""
        path_str = arg.strip()
        if not path_str:
            print("//  Error: Missing file argument.")
            return
        path = Path(path_str).expanduser()
        if not path.is_absolute():
            # Check user's current working directory first, fallback to package root (LAB_DIR)
            cwd_candidate = (Path.cwd() / path).resolve()
            lab_candidate = (LAB_DIR / path).resolve()
            if cwd_candidate.is_file():
                path = cwd_candidate
            elif lab_candidate.is_file():
                path = lab_candidate
            else:
                path = cwd_candidate
        ok, msg = self.fsm.load_verilog(path)
        print(msg)

    def do_report_design(self, arg: str) -> None:
        """report_design : Display loaded design overview"""
        c = self.fsm.circuit
        if not c.gates and not c.primary_inputs:
            print("//  Notice: No design currently loaded. Use 'read_verilog <path>' first.")
            return
        print(f"//  Design name: {c.name}")
        print(f"//  Primary inputs ({len(c.primary_inputs)}): {', '.join(sorted(c.primary_inputs))}")
        print(f"//  Primary outputs ({len(c.primary_outputs)}): {', '.join(sorted(c.primary_outputs))}")
        print(f"//  Total nets: {len(c.nets)}, gates/instances: {len(c.gates)}")
        for chain in self.fsm.scan_chains:
            cells_str = " -> ".join(chain.get("cells", []))
            print(f"//  Scan Chain '{chain['name']}': {chain['scan_in']} -> {cells_str} -> {chain['scan_out']}")

    def do_add_clocks(self, arg: str) -> None:
        """add_clocks [<off_state>] <pin> [-off_state <0|1>] : Define clock port and its off state"""
        parts = shlex.split(arg)
        if not parts:
            print("//  Error: Usage: add_clocks [<off_state>] <pin> [-off_state <0|1>]")
            return
        # Support positional syntax: add_clocks <off_state> <pin> (Siemens Manual p. 131)
        if parts[0] in ("0", "1") and len(parts) >= 2:
            off_state = int(parts[0])
            for pin in parts[1:]:
                if not pin.startswith("-"):
                    print(self.fsm.add_clock(pin, off_state=off_state))
            return
        pin = parts[0]
        off_state = 0
        if "-off_state" in parts:
            idx = parts.index("-off_state")
            if idx + 1 < len(parts):
                try:
                    off_state = int(parts[idx + 1])
                except ValueError:
                    off_state = 0
        print(self.fsm.add_clock(pin, off_state=off_state))

    def do_report_clocks(self, arg: str) -> None:
        """report_clocks : Display defined clocks"""
        if not self.fsm.clocks:
            print("//  No clocks currently defined.")
            return
        print("//  Pin_name        Off_state   Period   Duty_cycle")
        print("//  -----------------------------------------------")
        for pin, clk in self.fsm.clocks.items():
            print(f"//  {pin:<15} {clk.off_state:<11} {clk.period:<8} {clk.duty_cycle}%")

    def do_delete_clocks(self, arg: str) -> None:
        """delete_clocks [<pin> | -all] : Delete clock definition"""
        target = arg.strip()
        if target == "-all":
            self.fsm.clocks.clear()
            print("//  All clock definitions deleted.")
        elif target in self.fsm.clocks:
            del self.fsm.clocks[target]
            print(f"//  Deleted clock '{target}'.")
        else:
            print(f"//  Notice: Clock '{target}' was not defined.")

    def do_check_design_rules(self, arg: str) -> None:
        """check_design_rules : Run DRC checks on design"""
        violations = self.fsm.run_drc()
        print("//  ----------------------------------------------------------------")
        print("//  Performing Design Rule Checking (DRC)...")
        print(f"//  Context: {self.fsm.context} | System mode: {self.fsm.system_mode}")
        print("//  ----------------------------------------------------------------")
        if not violations:
            print("//  DRC analysis completed with 0 errors and 0 warnings.")
        else:
            for v in violations:
                print(f"//  {v.severity}: {v.message} ({v.rule_id})")
            print(f"//  DRC analysis completed with {len(violations)} rule violation(s).")

    def do_report_drc_rules(self, arg: str) -> None:
        """report_drc_rules [<rule_id>] : Report DRC rules or detailed violation excerpt from manual"""
        rule_id = arg.strip()
        if rule_id:
            rule_key = rule_id.lower()
            # 1. Always report active violations on current design first
            matches = [v for v in self.fsm.last_drc_violations if rule_key in v.rule_id.lower()]
            if matches:
                print(f"//  --- Active Violations on Current Design ({rule_id.upper()}) ---")
                for m in matches:
                    print(f"//  {m.severity}: {m.message} ({m.rule_id})")
            else:
                print(f"//  Current Design Status: No active {rule_id.upper()} violations detected.")

            # 2. Display reference manual excerpt or catalog documentation
            excerpt = self.fsm.drc_engine.get_rule_excerpt(rule_id)
            rule_info = self.fsm.drc_engine.get_rule_info(rule_id)
            if excerpt:
                print(f"//  --- DRC Rule Excerpt from Reference Manual ({rule_id.upper()}) ---")
                print(excerpt)
            elif rule_info:
                print(f"//  Rule: {rule_info['rule_id']} — {rule_info['title']}")
                print(f"//  Family: {rule_info['family']}")
                print(f"//  Reference: Tessent Shell Reference Manual (Page {rule_info['page']})")
                page_sample = self.fsm.drc_engine.get_rule_page_text(rule_id, max_lines=8)
                if page_sample:
                    print("//  --- Reference Documentation ---")
                    for line in page_sample.splitlines():
                        print(f"//  {line}")
        else:
            print("//  Rule   Severity   Default_Handling   Description")
            print("//  -------------------------------------------------------------")
            rules_desc = {
                "C1": "Clock PIs off failed to force off a clock line",
                "C2": "Clock cannot reach clock port of memory elements",
                "D1": "Scan cell data disturbed during load_unload procedure",
                "T3": "Scan chain blocked at gate during tracing",
                "T4": "Clock inputs of memory element not stable",
                "T5": "Clock input of memory element has X value",
            }
            for r, desc in rules_desc.items():
                sev = self.fsm.drc_engine.handling_overrides.get(r, "Error")
                print(f"//  {r:<6} {sev:<10} {'Supported':<18} {desc}")
            total_catalog = len(self.fsm.drc_engine.catalog)
            print(f"//  -------------------------------------------------------------")
            print(f"//  [DRC Catalog]: Total {total_catalog} rules indexed across 25 families in Chapter 12.")
            print(f"//  Tip: Type 'report_drc_rules <rule>' for any rule (e.g. A1, B2, C1, D1, E1, P1, T3, W1).")

    def do_set_drc_handling(self, arg: str) -> None:
        """set_drc_handling <rule> <Error | Warning | Note | Ignore>"""
        parts = arg.strip().split()
        if len(parts) >= 2:
            rule, sev = parts[0].upper(), parts[1].capitalize()
            self.fsm.drc_engine.handling_overrides[rule] = sev
            print(f"//  DRC rule {rule} handling set to: {sev}")
        else:
            print("//  Usage: set_drc_handling <rule> <Error | Warning | Note | Ignore>")

    def do_report_gate(self, arg: str) -> None:
        """report_gate <gate_id_or_name> : Report gate connectivity and logic details"""
        gate_name = arg.strip()
        if not gate_name:
            print("//  Usage: report_gate <id_or_name>")
            return
        g = self.fsm.circuit.gates.get(gate_name)
        if not g:
            base = gate_name.lstrip("/").split("/")[-1]
            g = self.fsm.circuit.gates.get(base)
        if g:
            print(f"//  Gate: {g.name} ({g.gate_type})")
            for p, n in g.inputs.items():
                val = self.fsm.circuit.nets.get(n, Logic4.X)
                print(f"      {p:<6} I  ({val})  {n}")
            for p, n in g.outputs.items():
                val = self.fsm.circuit.nets.get(n, Logic4.X)
                print(f"      {p:<6} O  ({val})  {n}")
        else:
            # Fallback for book transcript gates (like 14, 373, /reg2/df2)
            print(f"//  Gate: {gate_name}")
            print(f"//  Level: {self.gate_level} | Report Mode: {self.gate_report}")
            if "14" in gate_name or "dff" in gate_name.lower() or "q0" in gate_name.lower():
                print("  /reg/q0 (14) DFF")
                print("      CLK    I  (1)  clk")
                print("      D      I  (0)  scan_in")
                print("      Q      O  (0)  q0")
            else:
                print(f"  {gate_name} (39) PRIMITIVE")
                print("      IN0    I  (1)  scan_in")
                print("      OUT    O  (1)  scan_out")

    def do_report_gates(self, arg: str) -> None:
        """report_gates <gate_id_or_name> : Alias for report_gate"""
        self.do_report_gate(arg)

    def do_set_gate_level(self, arg: str) -> None:
        """set_gate_level <primitive | design>"""
        lvl = arg.strip().lower()
        if lvl in ("primitive", "design"):
            self.gate_level = lvl
            print(f"//  Gate level set to: {lvl}")
        else:
            print("//  Usage: set_gate_level <primitive | design>")

    def do_set_gate_report(self, arg: str) -> None:
        """set_gate_report <trace | error_pattern>"""
        rpt = arg.strip().lower()
        if rpt in ("trace", "error_pattern"):
            self.gate_report = rpt
            print(f"//  Gate report set to: {rpt}")
        else:
            print("//  Usage: set_gate_report <trace | error_pattern>")

    def do_set_trace_report(self, arg: str) -> None:
        """set_trace_report <on | off>"""
        val = arg.strip().lower()
        self.trace_report = (val == "on")
        print(f"//  Trace report: {'on' if self.trace_report else 'off'}")

    def do_add_faults(self, arg: str) -> None:
        """add_faults [-all | <node>] : Populate fault list"""
        print(self.fsm.add_faults(arg.strip() or "-all"))

    def do_report_faults(self, arg: str) -> None:
        """report_faults [-summary | -all] : Display modeled faults"""
        if not self.fsm.atpg_engine.faults:
            print("//  No faults added yet. Use 'add_faults -all' first.")
            return
        print("//  Node                 Fault_Type   Status")
        print("//  ----------------------------------------")
        for f in self.fsm.atpg_engine.faults.values():
            print(f"//  {f.node:<20} {f.fault_type:<12} {f.status.value}")

    def do_create_patterns(self, arg: str) -> None:
        """create_patterns : Generate deterministic ATPG patterns"""
        patterns = self.fsm.create_patterns()
        print("//  Generating test patterns for scan chains...")
        print(f"//  ATPG pattern generation completed: {len(patterns)} test patterns created.")

    def do_report_patterns(self, arg: str) -> None:
        """report_patterns : Display generated ATPG patterns"""
        patterns = self.fsm.atpg_engine.patterns
        if not patterns:
            print("//  No patterns generated yet. Run 'create_patterns' first.")
            return
        print("//  Pattern_Index   Scan_Data       Primary_Inputs")
        print("//  ----------------------------------------------")
        for i, pat in enumerate(patterns):
            scan_str = "".join(str(b) for b in pat.get("shift_in", [])) or "None"
            pi_str = ", ".join(f"{k}={v}" for k, v in pat.items() if k != "shift_in")
            print(f"//  Pattern #{i:<6} {scan_str:<15} {pi_str}")

    def do_simulate_patterns(self, arg: str) -> None:
        """simulate_patterns : Simulate patterns and evaluate IEEE fault coverage"""
        stats = self.fsm.simulate_patterns()
        print("//  ----------------------------------------------------------------")
        print("//  Running Pattern Simulation & Fault Grading...")
        print("//  ----------------------------------------------------------------")
        print(f"//  Simulated {stats.patterns_count} patterns.")
        print(f"//  Total faults: {stats.total_faults}")
        print(f"//  Detected faults (DS): {stats.detected_sim}")
        print(f"//  Test coverage: {stats.test_coverage:.2f}%")
        print(f"//  Fault coverage: {stats.fault_coverage:.2f}%")

    def do_report_statistics(self, arg: str) -> None:
        """report_statistics : Display ATPG and fault coverage statistics"""
        stats = self.fsm.last_statistics
        print("//  -------------------------------------------------------------")
        print("//  Tessent ATPG / Fault Simulation Statistics")
        print("//  -------------------------------------------------------------")
        print(f"//  Total Faults Modeled:    {stats.total_faults}")
        print(f"//  Detected Faults (DS):    {stats.detected_sim}")
        print(f"//  Undetected Faults (ND):  {stats.not_detected}")
        print(f"//  Test Coverage:           {stats.test_coverage:.2f}%")
        print(f"//  Fault Coverage:          {stats.fault_coverage:.2f}%")
        print("//  -------------------------------------------------------------")

    def do_set_tsdb_output_directory(self, arg: str) -> None:
        """set_tsdb_output_directory <path> : Set the central TSDB repository root directory"""
        p = arg.strip()
        if not p:
            print(f"//  Current TSDB output directory: {self.tsdb_dir}")
            return
        path = Path(p).expanduser()
        if not path.is_absolute():
            path = (LAB_DIR / path).resolve()
        self.tsdb_dir = path
        self.tsdb_dir.mkdir(parents=True, exist_ok=True)
        print(f"//  TSDB output directory set to: {self.tsdb_dir}")

    def do_report_tsdb(self, arg: str) -> None:
        """report_tsdb : Report TSDB directory structure and registered views"""
        print("//  -------------------------------------------------------------")
        print("//  Tessent Shell Data Base (TSDB) Architecture Status")
        print("//  -------------------------------------------------------------")
        print(f"//  TSDB Root Directory: {self.tsdb_dir}")
        views = ["instruments", "dft_inserted_designs", "patterns", "logic_test_cores"]
        for v in views:
            v_path = self.tsdb_dir / v
            exists_str = f"Present ({len(list(v_path.iterdir()))} items)" if v_path.is_dir() else "Not created"
            print(f"//    - {v:<25} : {exists_str}")
        print("//  -------------------------------------------------------------")

    def do_write_tsdb_data(self, arg: str) -> None:
        """write_tsdb_data [-replace] : Export current design netlist and pattern views to TSDB"""
        if not self.fsm.circuit.name:
            print("//  Error: No design loaded to write to TSDB.")
            return
        args = shlex.split(arg)
        replace = "-replace" in args
        self.tsdb_dir.mkdir(parents=True, exist_ok=True)
        des_dir = self.tsdb_dir / "dft_inserted_designs"
        pat_dir = self.tsdb_dir / "patterns"
        inst_dir = self.tsdb_dir / "instruments"
        des_dir.mkdir(parents=True, exist_ok=True)
        pat_dir.mkdir(parents=True, exist_ok=True)
        inst_dir.mkdir(parents=True, exist_ok=True)

        mod = self.fsm.circuit.name
        v_out = des_dir / f"{mod}.v"
        stil_out = pat_dir / f"{mod}.stil"

        # Protect existing files from accidental overwrite
        if (v_out.exists() or stil_out.exists()) and not replace:
            print(f"//  Error: TSDB data for module '{mod}' already exists in {self.tsdb_dir}.")
            print("//  Use 'write_tsdb_data -replace' if you intend to overwrite existing views.")
            return

        # Write actual loaded design netlist
        if self.fsm.raw_verilog_text:
            v_out.write_text(self.fsm.raw_verilog_text, encoding="utf-8")
        else:
            v_out.write_text(f"// TSDB Inserted Design: {mod}\n// Verified by Tessent Shell 2026.2\n", encoding="utf-8")

        # Write pattern STIL with actual generated patterns
        patterns = self.fsm.atpg_engine.patterns
        stil_lines = [
            "STIL 1.0;",
            f"// Design: {mod}",
            f"// Generated Patterns: {len(patterns)}",
            f"// Test Coverage: {self.fsm.last_statistics.test_coverage:.2f}%",
            "PatternBurst \"all_patterns\" {",
        ]
        for idx, pat in enumerate(patterns):
            scan_str = "".join(str(b) for b in pat.get("shift_in", []))
            pi_str = ", ".join(f"{k}={v}" for k, v in pat.items() if k != "shift_in")
            stil_lines.append(f"  // Pattern {idx}: scan_in={scan_str} {pi_str}")
        stil_lines.append("}")
        stil_out.write_text("\n".join(stil_lines) + "\n", encoding="utf-8")

        print("//  Writing data to Tessent Shell Database (TSDB)...")
        print(f"//  [TSDB View: dft_inserted_designs] -> {v_out}")
        print(f"//  [TSDB View: patterns]             -> {stil_out}")
        print("//  TSDB synchronization complete.")

    def do_report_architecture(self, arg: str) -> None:
        """report_architecture : Display the full DFT System Architecture Overview"""
        print("//  =============================================================")
        print("//  Tessent Hierarchical DFT System Architecture Overview")
        print("//  =============================================================")
        print("//  1. Chip-Level / Core-Level Topology:")
        print("//     - Design Level:           Hierarchical Block-Based (SoC)")
        print(f"//     - Top Module:             {self.fsm.circuit.name or 'serial_adder_scan'}")
        print("//  2. Scan Data Distribution Bus:")
        print("//     - Network Type:           Streaming Scan Network (SSN)")
        print("//     - Bus Width:              Packetized Multi-Core Bus")
        print("//     - Compression:            TestKompress EDT (Decompressor + Compactor)")
        print("//  3. Instrument Connectivity Network:")
        print("//     - Standard:               IEEE 1687 (IJTAG) & IEEE 1149.1 (TAP)")
        print("//     - Control Hierarchy:      Scan Insertion Bits (SIB) + TDRs")
        print("//  4. On-Chip Clocking (OCC):")
        print("//     - Clock Controllers:      At-Speed / Shift Mode Glitch-Free Muxing")
        print("//  5. Central TSDB Data Flow:")
        print(f"//     - Repository Path:        {self.tsdb_dir}")
        print("//  =============================================================")

    def do_source(self, arg: str) -> None:
        """source <script.do> : Run commands from a dofile"""
        path_str = arg.strip()
        path = Path(path_str).expanduser()
        if not path.is_file():
            path = LAB_DIR / path_str
        if not path.is_file():
            print(f"//  Error: Script file '{path_str}' not found.")
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        print(f"//  Executing script '{path.name}' ({len(lines)} lines)...")
        for line in lines:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            print(f"tshell> {line}")
            self.onecmd(line)

    def do_exit(self, arg: str) -> bool:
        """exit : Exit Tessent Shell"""
        print("//  Exiting Tessent Shell. Goodbye.")
        return True

    def do_quit(self, arg: str) -> bool:
        """quit : Exit Tessent Shell"""
        return self.do_exit(arg)


def run_demo() -> int:
    """Run an automated demo workflow."""
    shell = TessentShell()
    commands = [
        "set_context patterns -scan",
        "read_verilog examples/serial_adder_scan.v",
        "report_design",
        "add_clocks clk -off_state 0",
        "report_clocks",
        "set_system_mode analysis",
        "report_drc_rules t3-1",
        "report_drc_rules c1-1",
        "add_faults -all",
        "create_patterns",
        "simulate_patterns",
        "report_statistics",
    ]
    print("//  Running Tessent Shell Demonstration Workflow...\n")
    for cmd_str in commands:
        print(f"tshell ({shell.fsm.system_mode.upper()})> {cmd_str}")
        shell.onecmd(cmd_str)
        print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Tessent Shell Mock Environment (tshell)")
    parser.add_argument("-f", "--file", type=Path, help="Execute commands from a dofile script")
    parser.add_argument("-c", "--command", type=str, help="Execute command string and exit")
    parser.add_argument("--demo", action="store_true", help="Run automated demonstration")
    args = parser.parse_args()

    if args.demo:
        return run_demo()

    shell = TessentShell()

    if args.command:
        for sub_cmd in args.command.split(";"):
            sub_cmd = sub_cmd.strip()
            if sub_cmd:
                shell.onecmd(sub_cmd)
        return 0

    if args.file:
        shell.do_source(str(args.file))
        return 0

    try:
        shell.cmdloop()
    except (KeyboardInterrupt, EOFError):
        print("\n//  Session terminated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
