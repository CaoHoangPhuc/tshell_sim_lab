import json
import builtins
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / 'exercises.py'


def cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          cwd=LAB, capture_output=True, text=True)


def docker_available():
    try:
        return subprocess.run(['docker', 'image', 'inspect', 'tshell-sim-lab-rtl:local'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class ExerciseTests(unittest.TestCase):
    def test_list_includes_cases(self):
        proc = cli('list')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for case in ('case01', 'case02', 'case03', 'case04', 'case05'):
            self.assertIn(case, proc.stdout)

    def test_init_is_reproducible_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / 'first', Path(tmp) / 'second'
            for target in (first, second):
                proc = cli('init', 'case01', '--dir', target)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            for filename in ('analysis.txt', 'case.json'):
                self.assertEqual((first / filename).read_bytes(), (second / filename).read_bytes())
            (first / 'analysis.txt').write_text('user changes')
            proc = cli('init', 'case01', '--dir', first)
            self.assertNotEqual(proc.returncode, 0)
            self.assertEqual((first / 'analysis.txt').read_text(), 'user changes')

    def test_run_replays_actual_manual_excerpt_without_modifying_analysis(self):
        pdf_path = LAB / 'tshell_ref.pdf' if (LAB / 'tshell_ref.pdf').is_file() else (LAB.parent / 'tshell_ref.pdf')
        if not pdf_path.is_file():
            self.skipTest("Optional reference manual tshell_ref.pdf not present in environment")
        with tempfile.TemporaryDirectory() as tmp:
            import pymupdf
            for case, page, start, end in (
                ('case01', 4522, '//  Error: Scan chain chain1 blocked at gate /reg2/df2', '(T3-1)'),
                ('case02', 4525, '//  Error: Clock inputs of /datao/reg_q_0_', '(T4-1)'),
                ('case03', 4529, '//  Error: clock input of /datao/reg_q_0_', '(T3-1)'),
                ('case04', 3812, '// Error: Clock PIs off failed to force off a clock line of /U$1/DFF1', '(C1-1)'),
                ('case05', 3865, '//  ERROR: /dataot/reg_q_0_ (373) disturbed during time 0 of grp1', '(D1-1)'),
            ):
                directory = Path(tmp) / case
                self.assertEqual(cli('init', case, '--dir', directory).returncode, 0)
                analysis = directory / 'analysis.txt'
                analysis.write_text('my analysis')
                result = cli('run', '--dir', directory)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                with pymupdf.open(pdf_path) as pdf:
                    original = pdf[page - 1].get_text()
                first = original.index(start)
                last = original.index(end, first) + len(end)
                self.assertIn(original[first:last], result.stdout)
                self.assertEqual(analysis.read_text(), 'my analysis')

    def test_replay_reports_missing_pdf_and_missing_excerpt(self):
        sys.path.insert(0, str(LAB))
        import exercises
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(exercises, 'REFERENCE', Path(tmp) / 'missing.pdf'):
                stderr = StringIO()
                with redirect_stderr(stderr):
                    self.assertEqual(exercises.replay('case01'), 2)
                self.assertIn('Không tìm thấy tài liệu', stderr.getvalue())
        with patch.object(exercises, 'book_page', return_value='no original excerpt'):
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(exercises.replay('case01'), 2)
            self.assertIn('Không tìm thấy đoạn lỗi gốc', stderr.getvalue())

    def test_replay_reports_missing_pdf_reader(self):
        sys.path.insert(0, str(LAB))
        import exercises
        real_import = builtins.__import__
        def without_pymupdf(name, *args, **kwargs):
            if name == 'pymupdf':
                raise ModuleNotFoundError('pymupdf')
            return real_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_pymupdf):
            stderr = StringIO()
            with redirect_stderr(stderr):
                self.assertEqual(exercises.replay('case01'), 2)
            self.assertIn('Thiếu PyMuPDF', stderr.getvalue())

    def test_source_accepts_only_case_pages_and_reads_actual_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'book'
            self.assertEqual(cli('init', 'case01', '--dir', directory).returncode, 0)
            result = cli('source', '--dir', directory, '--page', 4523)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('report_gate /reg2/df2', result.stdout)
            self.assertNotEqual(cli('source', '--dir', directory, '--page', 4529).returncode, 0)

    def test_commands_follow_t3_example_as_printed_in_manual(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'book'
            self.assertEqual(cli('init', 'case01', '--dir', directory).returncode, 0)
            result = cli('commands', '--dir', directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            lines = result.stdout.splitlines()
            commands = [line for line in lines if line.startswith(('set_', 'report_gate'))]
            self.assertEqual(commands, [
                'set_trace_report on', 'set_gate_level primitive', 'set_gate_report trace',
                'set_system_mode analysis', 'report_gate /reg2/df2', 'set_gate_level design',
                'report_gate /reg2/df2', 'report_gates /uu1', 'report_gates /ten_reg',
            ])
            self.assertIn('4522', result.stdout)
            self.assertIn('4523', result.stdout)
            self.assertIn('4524', result.stdout)
            self.assertIn('không thực thi', result.stdout.lower())

    def test_commands_unsupported_case_and_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'book'
            self.assertEqual(cli('init', 'case02', '--dir', directory).returncode, 0)
            result = cli('commands', '--dir', directory)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('chưa hỗ trợ', result.stderr.lower())
            (directory / 'case.json').write_text('{invalid')
            self.assertNotEqual(cli('commands', '--dir', directory).returncode, 0)

    def test_run_missing_design_is_environment_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = cli('run', '--dir', tmp)
            self.assertEqual(proc.returncode, 2)
            self.assertIn('Không tìm thấy', proc.stderr)

    def test_invalid_manifest_does_not_silently_run_legacy_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'design.v').write_text('module scan_chain; endmodule')
            (directory / 'case.json').write_text('{invalid json')
            result = cli('run', '--dir', directory)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    @unittest.skipUnless(docker_available(), 'Docker image not available')
    def test_fixtures_show_documented_symptoms_and_repair(self):
        sys.path.insert(0, str(LAB))
        import exercises
        patches = {
            'case01': ('SCAN_ENABLE = 1\'b0', 'SCAN_ENABLE = 1\'b1', 'serial output differs'),
            'case02': ('SHIFT_CLOCK = 1\'b0', 'SHIFT_CLOCK = 1\'b1', 'no binary rising edge'),
            'case03': ('SHIFT_RESET = 1\'b1', 'SHIFT_RESET = 1\'b0', 'reset during shift'),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for case, (before_text, after_text, symptom) in patches.items():
                with self.subTest(case=case):
                    directory = Path(tmp) / case
                    directory.mkdir()
                    (directory / 'case.json').write_text(json.dumps({'format': 'document-shift-v1', 'case': case}))
                    (directory / 'design.v').write_text(exercises.DESIGN)
                    index = ('case01', 'case02', 'case03').index(case)
                    values = [("1'b0", "1'b1", "1'b0"), ("1'b1", "1'b0", "1'b0"), ("1'b1", "1'b1", "1'b1")][index]
                    (directory / 'procedure.vh').write_text(''.join(f'localparam {name} = {value};\n' for name, value in zip(('SCAN_ENABLE', 'SHIFT_CLOCK', 'SHIFT_RESET'), values)))
                    procedure = directory / 'procedure.vh'
                    before = procedure.read_text()
                    self.assertEqual(before.count(before_text), 1)
                    bad = cli('run', '--dir', directory)
                    self.assertEqual(procedure.read_text(), before)
                    self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
                    self.assertIn(symptom, bad.stdout + bad.stderr)
                    procedure.write_text(before.replace(before_text, after_text))
                    fixed = cli('run', '--dir', directory)
                    self.assertEqual(fixed.returncode, 0, fixed.stdout + fixed.stderr)
                    self.assertIn('completed without mismatch', fixed.stdout)

    @unittest.skipUnless(docker_available(), 'Docker image not available')
    def test_compile_error_is_reported_as_compile_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'exercise'
            directory.mkdir()
            (directory / 'case.json').write_text(json.dumps({'format': 'document-shift-v1', 'case': 'case01'}))
            (directory / 'design.v').write_text('module scan_chain; endmodule')
            (directory / 'procedure.vh').write_text('invalid verilog syntax')
            result = cli('run', '--dir', directory)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('compile', (result.stdout + result.stderr).lower())

    @unittest.skipUnless(docker_available(), 'Docker image not available')
    def test_legacy_case_uses_original_testbench(self):
        sys.path.insert(0, str(LAB))
        from insertion import EXAMPLE, insert_scan
        good, _ = insert_scan(EXAMPLE)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'design.v').write_text(good)
            result = cli('run', '--dir', directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('155 checks', result.stdout)


if __name__ == '__main__':
    unittest.main()
