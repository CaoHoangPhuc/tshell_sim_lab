import json
import builtins
import os
import shutil
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


def icarus_available():
    return shutil.which('iverilog') is not None and shutil.which('vvp') is not None


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

    def test_distribution_contains_metadata_not_manual_text(self):
        db = json.loads((LAB / 'tessent_core' / 'knowledge_db.json').read_text())
        self.assertEqual(len(db['case_studies']), 5)
        for case in db['case_studies'].values():
            self.assertNotIn('page_texts', case)
            self.assertNotIn('excerpt', case)
            self.assertNotIn('commands', case)
        for rule in db['rules'].values():
            self.assertNotIn('summary', rule)
            self.assertNotIn('reference_excerpt', rule)

    def test_manual_requires_explicit_pdf_and_does_not_modify_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'book'
            self.assertEqual(cli('init', 'case01', '--dir', directory).returncode, 0)
            analysis = directory / 'analysis.txt'
            analysis.write_text('my analysis')
            env = dict(os.environ)
            env.pop('TSHELL_REFERENCE_PDF', None)
            result = subprocess.run([sys.executable, str(SCRIPT), 'run', '--dir', str(directory)],
                                    cwd=LAB, capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn('--pdf', result.stderr)
            self.assertEqual(analysis.read_text(), 'my analysis')

    def test_source_reads_user_supplied_pdf_and_checks_page_range(self):
        try:
            import pymupdf
        except ImportError:
            self.skipTest('PyMuPDF not installed')
        sys.path.insert(0, str(LAB))
        import exercises
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / 'book'
            directory.mkdir()
            (directory / 'case.json').write_text(json.dumps({'format': exercises.FORMAT, 'case': 'case01'}))
            pdf = Path(tmp) / 'own.pdf'
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text((72, 72), 'sample page supplied by the user')
            document.save(pdf)
            document.close()
            case = dict(exercises.CASE_STUDIES['case01'], first_page=1, last_page=1, pdf_pages=[1])
            with patch.dict(exercises.CASE_STUDIES, {'case01': case}), patch('sys.stdout', new_callable=StringIO) as out:
                self.assertEqual(exercises.source(directory, 1, pdf), 0)
                self.assertIn('sample page supplied by the user', out.getvalue())
                self.assertEqual(exercises.source(directory, 2, pdf), 2)

    def test_replay_selects_actual_occurrence_after_generic_description(self):
        sys.path.insert(0, str(LAB))
        import exercises
        page = 'generic description (T4-1)\n// Error: actual failure\n// continuation (T4-1)\n'
        with patch.object(exercises, 'book_page', return_value=page), patch('sys.stdout', new_callable=StringIO) as out:
            self.assertEqual(exercises.replay('case02'), 0)
            self.assertIn('actual failure', out.getvalue())
            self.assertNotIn('generic description', out.getvalue())

    def test_rebuild_metadata_never_embeds_manual(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'index.json'
            proc = subprocess.run([sys.executable, str(LAB / 'tools' / 'build_knowledge_db.py'),
                                   '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            generated = json.loads(output.read_text())
            self.assertNotIn('page_texts', generated['case_studies']['case01'])
            self.assertNotIn('reference_excerpt', generated['rules']['C1'])

    def test_commands_require_manual_and_reject_unsupported_case(self):
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

    def test_legacy_run_explains_missing_icarus_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'design.v').write_text('module scan_chain; endmodule')
            env = dict(os.environ, PATH=str(directory))
            result = subprocess.run([sys.executable, str(SCRIPT), 'run', '--dir', str(directory)],
                                    cwd=LAB, capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn('iverilog', result.stderr.lower())

    def test_invalid_manifest_does_not_silently_run_legacy_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'design.v').write_text('module scan_chain; endmodule')
            (directory / 'case.json').write_text('{invalid json')
            result = cli('run', '--dir', directory)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    @unittest.skipUnless(icarus_available(), 'Icarus Verilog not available')
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

    @unittest.skipUnless(icarus_available(), 'Icarus Verilog not available')
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

    @unittest.skipUnless(icarus_available(), 'Icarus Verilog not available')
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
