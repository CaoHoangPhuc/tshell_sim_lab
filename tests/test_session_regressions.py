import contextlib
import io
import subprocess
import sys
from pathlib import Path

from tessent_core.drc import DRCViolation
from tessent_core.state import SessionFSM
from tshell import TessentShell

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tshell.py'


def run(*args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd or ROOT, text=True, capture_output=True)


def test_batch_stops_and_returns_error_for_unknown_or_missing_file(tmp_path):
    for first in ('not_a_command', 'read_verilog missing.v', 'report_gate missing'):
        p = run('-c', first + '; report_context', cwd=tmp_path)
        assert p.returncode != 0
        assert 'Context:' not in p.stdout
    p = run('-f', str(tmp_path / 'missing.do'))
    assert p.returncode != 0


def test_source_stops_after_bad_command(tmp_path):
    script = tmp_path / 'run.do'
    script.write_text('not_a_command\nreport_context\n')
    p = run('-f', str(script))
    assert p.returncode != 0
    assert 'Context:' not in p.stdout


def test_failed_write_tsdb_never_creates_or_overwrites(tmp_path):
    p = tmp_path / 'dft_inserted_designs' / 'top.v'
    p.parent.mkdir()
    p.write_text('keep me')
    shell = TessentShell()
    shell.tsdb_dir = tmp_path
    shell.onecmd('write_tsdb_data -replace')
    assert p.read_text() == 'keep me'
    assert not (tmp_path / 'patterns').exists()
    assert shell.failed


def test_actual_drc_violations_are_reported_and_not_confused_with_examples():
    shell = TessentShell()
    shell.fsm.last_drc_violations = [DRCViolation('C1-1', 'Error', 'Clock', 'CURRENT_DESIGN_FAILURE')]
    with contextlib.redirect_stdout(io.StringIO()) as out:
        shell.onecmd('report_drc_rules C1-1')
    assert 'CURRENT_DESIGN_FAILURE' in out.getvalue()


def test_no_design_never_reports_clean_drc():
    p = run('-c', 'check_design_rules')
    assert p.returncode != 0
    assert '0 errors and 0 warnings' not in p.stdout


def test_design_load_clears_previous_design_state(tmp_path):
    first = ROOT / 'examples' / 'serial_adder_scan.v'
    second = tmp_path / 'two.v'
    second.write_text('module two(a,y);\ninput a;\noutput y;\nassign y = a;\nendmodule\n')
    fsm = SessionFSM()
    assert fsm.load_verilog(first)[0]
    fsm.add_clock('clk')
    fsm.add_faults()
    assert fsm.load_verilog(second)[0]
    assert not fsm.scan_chains and not fsm.atpg_engine.faults and not fsm.clocks


def test_relative_verilog_path_is_resolved_from_working_directory(tmp_path):
    design = tmp_path / 'relative.v'
    design.write_text('module relative(a,y);\ninput a;\noutput y;\nassign y = a;\nendmodule\n')
    p = run('-c', 'read_verilog relative.v; report_design', cwd=tmp_path)
    assert p.returncode == 0, p.stdout
    assert 'Design name: relative' in p.stdout


def test_invalid_arguments_and_missing_design_fail_batch():
    for command in ('set_context invalid', 'add_clocks clk -off_state nope',
                    'create_patterns', 'add_faults -all', 'simulate_patterns',
                    'set_system_mode analysis'):
        p = run('-c', command)
        assert p.returncode != 0, (command, p.stdout)


def test_unknown_gate_does_not_invent_connectivity():
    p = run('-c', 'report_gate imaginary')
    assert p.returncode != 0
    assert 'PRIMITIVE' not in p.stdout


def test_drc_with_design_is_clearly_incomplete():
    p = run('-c', f'read_verilog {ROOT / "examples/serial_adder_scan.v"}; check_design_rules')
    assert p.returncode == 0, p.stdout
    assert 'incomplete' in p.stdout.lower()
    assert '0 errors and 0 warnings' not in p.stdout


def test_batch_file_and_verilog_paths_support_spaces(tmp_path):
    design = tmp_path / 'my design.v'
    design.write_text('module relative(a,y);\ninput a;\noutput y;\nassign y = a;\nendmodule\n')
    dofile = tmp_path / 'my commands.do'
    dofile.write_text('read_verilog "my design.v"\nreport_design\n')
    p = run('-f', str(dofile), cwd=tmp_path)
    assert p.returncode == 0, p.stdout
    assert 'Design name: relative' in p.stdout


def test_add_faults_clears_stale_statistics():
    shell = TessentShell()
    shell.onecmd(f"read_verilog {ROOT / 'examples/serial_adder_scan.v'}")
    shell.onecmd("add_clocks 0 clk")
    shell.onecmd("set_system_mode analysis")
    shell.onecmd("add_faults -all")
    shell.onecmd("create_patterns")
    shell.onecmd("simulate_patterns")
    assert shell.fsm.simulation_done
    assert shell.fsm.last_statistics.test_coverage > 0

    # Now add_faults again - should invalidate stale statistics
    shell.onecmd("add_faults -all")
    assert not shell.fsm.simulation_done
    assert shell.fsm.last_statistics.total_faults == 0

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        shell.onecmd("report_statistics")
    assert "No fault simulation statistics available" in buf.getvalue()


def test_delete_clocks_clears_stale_drc_violations():
    shell = TessentShell()
    shell.fsm.last_drc_violations = [DRCViolation('C1-1', 'Error', 'Clock', 'FAILED')]
    shell.fsm.clocks['clk'] = None

    shell.onecmd("delete_clocks -all")
    assert len(shell.fsm.last_drc_violations) == 0

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        shell.onecmd("report_drc_rules c1-1")
    assert "Active Violations on Current Design" not in buf.getvalue()


def test_report_architecture_checks_loaded_design():
    shell = TessentShell()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        shell.onecmd("report_architecture")
    assert "No design loaded" in buf.getvalue()
    assert shell.failed

    shell2 = TessentShell()
    shell2.onecmd(f"read_verilog {ROOT / 'examples/serial_adder_scan.v'}")
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        shell2.onecmd("report_architecture")
    out = buf2.getvalue()
    assert "Top Module:             serial_adder_scan" in out
    assert "None detected in gate netlist" in out
