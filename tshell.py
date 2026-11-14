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
import tempfile
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
        self.tsdb_dir: Path = Path.cwd() / "tsdb"
        self.failed = False
        self.update_prompt()

    def update_prompt(self) -> None:
        mode_str = self.fsm.system_mode.upper()
        self.prompt = f"tshell ({mode_str})> "

    def precmd(self, line: str) -> str:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            return ""
        return line

    def error(self, message: str) -> None:
        self.failed = True
        print(f"//  Error: {message}")

    def onecmd(self, line: str) -> bool:
        self.failed = False
        line = self.precmd(line)
        if not line:
            return self.emptyline()
        try:
            return super().onecmd(line)
        except (ValueError, OSError) as exc:
            self.error(str(exc))
            return False

    def emptyline(self) -> bool:
        return False

    def default(self, line: str) -> bool:
        cmd_name = line.split()[0] if line.split() else ""
        self.error(f"Unknown command or syntax error: '{cmd_name}'. Type 'help' for available commands.")
        return False

    def do_set_context(self, arg: str) -> None:
        """set_context <context> [-<option>] : Set application context (e.g. dft -scan, patterns -scan)"""
        args = arg.strip()
        if not args:
            print(f"//  Current context: {self.fsm.context}")
            return
        ok, msg = self.fsm.set_context(args)
        if ok:
            print(msg)
        else:
            self.error(msg.replace("//  Error: ", "", 1))

    def do_report_context(self, arg: str) -> None:
        """report_context : Display current context"""
        print(f"//  Context: {self.fsm.context}")

    def do_set_system_mode(self, arg: str) -> None:
        """set_system_mode <setup | analysis> : Switch system mode (triggers DRC on setup -> analysis)"""
        mode = arg.strip().lower()
        ok, msg = self.fsm.set_system_mode(mode)
        if ok:
            print(msg)
            self.update_prompt()
        else:
            self.error(msg.replace("//  Error: ", "", 1))

    def do_report_system_mode(self, arg: str) -> None:
        """report_system_mode : Display current system mode"""
        print(f"//  System mode: {self.fsm.system_mode}")

    def do_read_verilog(self, arg: str) -> None:
        """read_verilog <filepath> : Read design netlist in Verilog format"""
        parts = shlex.split(arg)
        if len(parts) != 1:
            self.error("Usage: read_verilog <filepath>")
            return
        path = Path(parts[0]).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        ok, msg = self.fsm.load_verilog(path)
        if ok:
            print(msg)
        else:
            self.error(msg.replace("//  Error: ", "", 1))

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
        if len(parts) >= 2 and parts[0] in ("0", "1"):
            off_state, pins = int(parts[0]), parts[1:]
        elif len(parts) == 1 and not parts[0].startswith("-"):
            off_state, pins = 0, parts
        elif len(parts) == 3 and parts[1] == "-off_state" and parts[2] in ("0", "1"):
            off_state, pins = int(parts[2]), parts[:1]
        else:
            self.error("Usage: add_clocks [<0|1>] <pin>... or add_clocks <pin> -off_state <0|1>")
            return
        if any(pin.startswith("-") for pin in pins):
            self.error("Invalid clock pin.")
            return
        for pin in pins:
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
            self.fsm.delete_all_clocks()
            print("//  All clock definitions deleted.")
        elif self.fsm.delete_clock(target):
            print(f"//  Deleted clock '{target}'.")
        else:
            print(f"//  Notice: Clock '{target}' was not defined.")

    def do_check_design_rules(self, arg: str) -> None:
        """check_design_rules : Run DRC checks on design"""
        if not self.fsm.raw_verilog_text:
            self.error("No design loaded for DRC.")
            return
        violations = self.fsm.run_drc()
        print("//  ----------------------------------------------------------------")
        print("//  Performing Design Rule Checking (DRC)...")
        print(f"//  Context: {self.fsm.context} | System mode: {self.fsm.system_mode}")
        print("//  ----------------------------------------------------------------")
        if not violations:
            print("//  No violations found by preliminary checks; DRC is incomplete and cannot establish that the design is clean.")
        else:
            for v in violations:
                print(f"//  {v.severity}: {v.message} ({v.rule_id})")
            print(f"//  Preliminary DRC found {len(violations)} possible violation(s); checks are incomplete.")

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
                print(f"//  No recorded {rule_id.upper()} violations; checks may not have run and are incomplete.")

            # 2. Display reference manual excerpt or catalog documentation
            excerpt = self.fsm.drc_engine.get_rule_excerpt(rule_id)
            rule_info = self.fsm.drc_engine.get_rule_info(rule_id)
            if excerpt:
                print(f"//  --- Reference Manual Excerpt ({rule_id.upper()}) ---")
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
                print(f"//  {r:<6} {sev:<10} {'Incomplete':<18} {desc}")
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
            self.error("Usage: set_drc_handling <rule> <Error | Warning | Note | Ignore>")

    def do_report_gate(self, arg: str) -> None:
        """report_gate <gate_id_or_name> : Report gate connectivity and logic details"""
        gate_name = arg.strip()
        if not gate_name:
            self.error("Usage: report_gate <id_or_name>")
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
            self.error(f"Gate '{gate_name}' not found in the loaded design.")

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
            self.error("Usage: set_gate_level <primitive | design>")

    def do_set_gate_report(self, arg: str) -> None:
        """set_gate_report <trace | error_pattern>"""
        rpt = arg.strip().lower()
        if rpt in ("trace", "error_pattern"):
            self.gate_report = rpt
            print(f"//  Gate report set to: {rpt}")
        else:
            self.error("Usage: set_gate_report <trace | error_pattern>")

    def do_set_trace_report(self, arg: str) -> None:
        """set_trace_report <on | off>"""
        val = arg.strip().lower()
        if val not in ("on", "off"):
            self.error("Usage: set_trace_report <on | off>")
            return
        self.trace_report = (val == "on")
        print(f"//  Trace report: {'on' if self.trace_report else 'off'}")

    def do_add_faults(self, arg: str) -> None:
        """add_faults [-all | <node>] : Populate fault list"""
        if not self.fsm.raw_verilog_text:
            self.error("No design loaded.")
            return
        if arg.strip() not in ("", "-all"):
            self.error("Only add_faults -all is supported.")
            return
        print(self.fsm.add_faults("-all"))

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
        """create_patterns : Generate heuristic demonstration patterns."""
        if not self.fsm.raw_verilog_text:
            self.error("No design loaded.")
            return
        patterns = self.fsm.create_patterns()
        print("//  Generating test patterns for scan chains...")
        print(f"//  Generated {len(patterns)} heuristic demonstration patterns (not validated ATPG).")

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
        if not self.fsm.raw_verilog_text:
            self.error("No design loaded.")
            return
        stats = self.fsm.simulate_patterns()
        print("//  ----------------------------------------------------------------")
        print("//  Running Demonstration Pattern Simulation & Fault Grading (not validated)...")
        print("//  ----------------------------------------------------------------")
        print(f"//  Simulated {stats.patterns_count} patterns.")
        print(f"//  Total faults: {stats.total_faults}")
        print(f"//  Detected faults (DS): {stats.detected_sim}")
        print(f"//  Test coverage: {stats.test_coverage:.2f}%")
        print(f"//  Fault coverage: {stats.fault_coverage:.2f}%")

    def do_report_statistics(self, arg: str) -> None:
        """report_statistics : Display ATPG and fault coverage statistics"""
        if not self.fsm.simulation_done:
            print("//  No fault simulation statistics available; run 'simulate_patterns' first.")
            return
        stats = self.fsm.last_statistics
        print("//  -------------------------------------------------------------")
        print("//  Demonstration Fault Simulation Statistics (not validated)")
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
            path = (Path.cwd() / path).resolve()
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
        """write_tsdb_data : TSDB export is not implemented."""
        self.error("TSDB/STIL export is not implemented; no files were written.")

    def do_report_architecture(self, arg: str) -> None:
        """report_architecture : Display the full DFT System Architecture Overview"""
        if not self.fsm.raw_verilog_text or not self.fsm.circuit.gates:
            self.error("No design loaded. Architecture information is unavailable.")
            return

        c = self.fsm.circuit
        print("//  =============================================================")
        print("//  Tessent Hierarchical DFT System Architecture Overview")
        print("//  =============================================================")
        print("//  1. Design Summary:")
        print(f"//     - Top Module:             {c.name}")
        print(f"//     - Primary Inputs:         {len(c.primary_inputs)}")
        print(f"//     - Primary Outputs:        {len(c.primary_outputs)}")
        print(f"//     - Total Gates / Instances:{len(c.gates)}")
        print(f"//     - Sequential Elements:    {len(c.scan_cells)} DFF cell(s)")
        print("//  2. Scan Chain Architecture:")
        if self.fsm.scan_chains:
            for ch in self.fsm.scan_chains:
                ch_name = ch.get("name", "chain")
                si = ch.get("scan_in", "N/A")
                so = ch.get("scan_out", "N/A")
                cells_cnt = len(ch.get("cells", []))
                print(f"//     - Scan Chain '{ch_name}': {cells_cnt} cells (in: {si}, out: {so})")
        else:
            print("//     - Scan Chains:            None configured")
        print("//  3. Clock Configuration:")
        if self.fsm.clocks:
            for pin, clk in self.fsm.clocks.items():
                print(f"//     - Clock '{pin}': off-state={clk.off_state}, period={clk.period}ns")
        else:
            print("//     - Clocks:                 None defined")
        print("//  4. Advanced DFT Features:")
        print("//     - Compression (EDT):      None detected in gate netlist")
        print("//     - Packetized Bus (SSN):   None detected in gate netlist")
        print("//     - Instruments (IJTAG):    None detected in gate netlist")
        print("//     - On-Chip Clocking (OCC): None detected in gate netlist")
        print("//  5. Central TSDB Data Flow:")
        print(f"//     - Repository Path:        {self.tsdb_dir}")
        print("//  =============================================================")

    def do_source(self, arg: str) -> None:
        """source <script.do> : Run commands from a dofile"""
        parts = shlex.split(arg)
        if len(parts) != 1:
            self.error("Usage: source <script.do>")
            return
        path_str = parts[0]
        path = Path(path_str).expanduser()
        if not path.is_file():
            self.error(f"Script file '{path_str}' not found.")
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        print(f"//  Executing script '{path.name}' ({len(lines)} lines)...")
        for line in lines:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("#"):
                continue
            print(f"tshell> {line}")
            stop = self.onecmd(line)
            if self.failed or stop:
                return stop

    def do_exit(self, arg: str) -> bool:
        """exit : Exit Tessent Shell"""
        print("//  Exiting Tessent Shell. Goodbye.")
        return True

    def do_quit(self, arg: str) -> bool:
        """quit : Exit Tessent Shell"""
        return self.do_exit(arg)


def run_demo() -> int:
    """Run the demo using a temporary generated netlist, including after installation."""
    from insertion import EXAMPLE, insert_scan

    shell = TessentShell()
    with tempfile.TemporaryDirectory() as directory:
        design = Path(directory) / "serial_adder_scan.v"
        design.write_text(insert_scan(EXAMPLE)[0], encoding="utf-8")
        commands = [
            "set_context patterns -scan",
            f"read_verilog {shlex.quote(str(design))}",
            "report_design",
            "add_clocks 0 clk",
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
            stop = shell.onecmd(cmd_str)
            print()
            if shell.failed:
                return 1
            if stop:
                break
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
                stop = shell.onecmd(sub_cmd)
                if shell.failed:
                    return 1
                if stop:
                    break
        return 0

    if args.file:
        shell.onecmd("source " + shlex.quote(str(args.file)))
        return 1 if shell.failed else 0

    try:
        shell.cmdloop()
    except (KeyboardInterrupt, EOFError):
        print("\n//  Session terminated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
