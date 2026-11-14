#!/usr/bin/env python3
"""Replay document excerpts; preserve older standalone simulation exercises."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LAB = Path(__file__).resolve().parent
LEGACY_TESTBENCH = LAB / 'rtl' / 'tb_exercise.v'
DOCUMENT_TESTBENCH = LAB / 'rtl' / 'tb_document_cases.v'
LEGACY_FORMAT = 'document-shift-v1'
FORMAT = 'book-replay-v1'

DB_PATH = LAB / 'tessent_core' / 'knowledge_db.json'
try:
    DB = json.loads(DB_PATH.read_text(encoding='utf-8')) if DB_PATH.is_file() else {}
except Exception:
    DB = {}
CASE_STUDIES = DB.get('case_studies', {})

# Page numbers identify case studies; the actual manual is supplied separately.
BOOK_CASES = {
    'case01': (4522, 4522, 4524, 'T3-1'),
    'case02': (4525, 4525, 4528, 'T4-1'),
    'case03': (4529, 4529, 4531, 'T5-1'),
    'case04': (3812, 3809, 3814, 'C1-1'),
    'case05': (3865, 3863, 3866, 'D1-1'),
}

# Independent teaching implementations of the conditions documented in the
# Tessent Shell Reference Manual 2026.2, T3 (4520-4524), T4 (4525-4528),
# T5 (4529-4531), C1 (3809-3814), and D1 (3860-3866). This runner does not
# execute Tessent or classify DRCs.
CASES = {
    'case01': ("1'b0", "1'b1", "1'b0"),
    'case02': ("1'b1", "1'b0", "1'b0"),
    'case03': ("1'b1", "1'b1", "1'b1"),
    'case04': ("1'b1", "1'b1", "1'b0"),
    'case05': ("1'b1", "1'b1", "1'b0"),
}

DESIGN = '''// Independent teaching model: two scan flip-flops, async active-high reset.
module scan_chain(input clk, reset, scan_en, scan_in, output scan_out);
  reg q0, q1;
  always @(posedge clk or posedge reset) begin
    if (reset) begin
      q0 <= 1'b0;
      q1 <= 1'b0;
    end else if (scan_en) begin
      q0 <= scan_in;
      q1 <= q0;
    end
  end
  assign scan_out = q1;
endmodule
'''


def init(case: str, directory: Path) -> int:
    manifest = json.dumps({'format': FORMAT, 'case': case}, indent=2) + '\n'
    try:
        directory.mkdir(parents=True, exist_ok=False)
        (directory / 'analysis.txt').write_text('', encoding='utf-8')
        (directory / 'case.json').write_text(manifest, encoding='utf-8')
    except OSError as exc:
        print(f'Không thể tạo thư mục bài (không ghi đè): {exc}', file=sys.stderr)
        return 2
    print(f'Đã tạo bài {case}: {directory / "analysis.txt"}')
    print(f'Xem trích đoạn: python3 exercises.py run --dir {shlex.quote(str(directory))}')
    return 0


def book_page(number: int, case: str | None = None, pdf_path: Path | None = None) -> str:
    """Read one page from an explicitly supplied reference PDF, never from the package."""
    selected = pdf_path or (Path(os.environ['TSHELL_REFERENCE_PDF']) if os.environ.get('TSHELL_REFERENCE_PDF') else None)
    if selected is None:
        raise ValueError('Cần cung cấp manual bằng --pdf hoặc biến TSHELL_REFERENCE_PDF.')
    if not selected.is_file():
        raise ValueError(f'Không tìm thấy PDF: {selected}')
    try:
        import pymupdf
    except ImportError as exc:
        raise ValueError('Cần cài PyMuPDF để đọc PDF: pip install pymupdf') from exc
    try:
        with pymupdf.open(selected) as pdf:
            if number < 1 or number > len(pdf):
                raise ValueError(f'Trang PDF {number} không tồn tại trong tài liệu.')
            return pdf[number - 1].get_text()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f'Không thể đọc PDF: {exc}') from exc


def replay(case: str, pdf_path: Path | None = None) -> int:
    try:
        case_data = CASE_STUDIES[case]
        number = case_data['strobe_page']
        rule = case_data['rule']
        page = book_page(number, case, pdf_path)
        # A bounded window around the occurrence is printed from the user's
        # document; it is never written to the distributable index.
        lines = page.splitlines()
        start = end = None
        for i, line in enumerate(lines):
            if f'({rule}-1)' not in line:
                continue
            found = next((j for j in range(i, max(-1, i - 8), -1)
                          if re.match(r'\s*//\s*(error|warning)', lines[j], re.IGNORECASE)), None)
            if found is not None:
                start, end = found, i
                break
        if start is None or end is None:
            raise ValueError(f'Không tìm thấy ví dụ {rule}-1 trong trang {number}.')
        excerpt = '\n'.join(lines[start:end + 1])
    except (KeyError, ValueError) as exc:
        print(f'Không thể đọc ví dụ: {exc}', file=sys.stderr)
        return 2
    print(f'Trích trực tiếp từ PDF trang {number} (phát lại; không chạy Tessent DRC):')
    print(excerpt)
    print('Đây là log trong sách, không đánh giá bài làm hay thực thi lại thiết kế.')
    return 0


def source(directory: Path, page: int, pdf_path: Path | None = None) -> int:
    try:
        meta = json.loads((directory / 'case.json').read_text(encoding='utf-8'))
        if not isinstance(meta, dict) or meta.get('format') != FORMAT or meta.get('case') not in BOOK_CASES:
            raise ValueError('Bài này không phải bài đọc nguồn từ sách.')
        case = meta['case']
        case_data = CASE_STUDIES[case]
        first, last = case_data['first_page'], case_data['last_page']
        if page < first or page > last:
            raise ValueError(f'Bài này có trang nguồn từ {first} đến {last}.')
        original = book_page(page, case, pdf_path)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'Không thể đọc trang nguồn: {exc}', file=sys.stderr)
        return 2
    print(f'Trích trực tiếp từ PDF trang {page}; không phải output của Tessent đang chạy:')
    sys.stdout.write(original)
    return 0


def commands(directory: Path, pdf_path: Path | None = None) -> int:
    """Extract the T3 walkthrough from a user-supplied manual at runtime."""
    try:
        meta = json.loads((directory / 'case.json').read_text(encoding='utf-8'))
        if not isinstance(meta, dict) or meta.get('format') != FORMAT or meta.get('case') not in BOOK_CASES:
            raise ValueError('Bài này không phải bài đọc nguồn từ sách.')
        case = meta['case']
        if case != 'case01':
            raise ValueError('Chưa hỗ trợ trích lệnh cho case này.')
        page_commands = {}
        prefixes = ('set_trace_report ', 'set_gate_level ', 'set_gate_report ',
                    'set_system_mode ', 'report_gate ', 'report_gates ')
        for number in CASE_STUDIES[case]['pdf_pages']:
            text = book_page(number, case, pdf_path)
            if number == CASE_STUDIES[case]['first_page']:
                marker = 'How to Debug T3 Violations Without Tessent Visualizer'
                if marker not in text:
                    raise ValueError(f'Không tìm thấy phần hướng dẫn trong trang {number}.')
                text = text.split(marker, 1)[1]
            page_commands[number] = [line.strip() for line in text.splitlines()
                                     if line.strip().startswith(prefixes)]
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'Không thể đọc lệnh gốc: {exc}', file=sys.stderr)
        return 2
    print('Lệnh Tessent trích từ PDF để tham khảo; không thực thi Tessent:')
    for number, lines in page_commands.items():
        print(f'--- Trang PDF {number} ---')
        for line in lines:
            print(line)
    return 0


def run(directory: Path, pdf_path: Path | None = None) -> int:
    design = directory / 'design.v'
    manifest_path = directory / 'case.json'
    procedure = directory / 'procedure.vh'
    try:
        if manifest_path.exists():
            meta = json.loads(manifest_path.read_text(encoding='utf-8'))
            if not isinstance(meta, dict) or meta.get('format') not in (FORMAT, LEGACY_FORMAT) or meta.get('case') not in CASES:
                raise ValueError('định dạng hoặc mã bài không hợp lệ')
            if meta['format'] == FORMAT:
                return replay(meta['case'], pdf_path)
            testbench = DOCUMENT_TESTBENCH
            sources = [design, procedure, testbench]
            mode = 'document'
        else:
            if procedure.exists():
                raise ValueError('thiếu case.json cho bài mô phỏng procedure')
            # Existing exercises made before document-based cases have only
            # design.v and must continue to use their original testbench.
            testbench = LEGACY_TESTBENCH
            sources = [design, testbench]
            mode = 'legacy'
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'Không thể đọc thông tin bài: {exc}', file=sys.stderr)
        return 2
    if any(not path.is_file() for path in sources):
        print('Không tìm thấy file bài hoặc testbench của lab.', file=sys.stderr)
        return 2
    missing = [tool for tool in ('iverilog', 'vvp') if shutil.which(tool) is None]
    if missing:
        print(f'Thiếu Icarus Verilog ({", ".join(missing)}). Cài iverilog và vvp để chạy bài RTL.', file=sys.stderr)
        return 2
    try:
        with tempfile.TemporaryDirectory(prefix='tshell-rtl-') as tmp:
            executable = Path(tmp) / 'simulation'
            top = 'tb_document_cases' if mode == 'document' else 'tb_scan_demo'
            command = ['iverilog', '-g2012', '-I', str(directory.resolve()), '-s', top,
                       '-o', str(executable), str(testbench.resolve()), str(design.resolve())]
            compiled = subprocess.run(command, cwd=tmp, capture_output=True, text=True, timeout=60)
            if compiled.stdout:
                print(compiled.stdout, end='')
            if compiled.stderr:
                print(compiled.stderr, end='', file=sys.stderr)
            if compiled.returncode:
                print('Lỗi compile Verilog; xem thông báo phía trên.', file=sys.stderr)
                return 1
            result = subprocess.run(['vvp', str(executable)], cwd=tmp, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        print('Không tìm thấy iverilog hoặc vvp; cài Icarus Verilog để chạy bài RTL.', file=sys.stderr)
        return 2
    except subprocess.TimeoutExpired:
        print('Quá thời gian compile hoặc mô phỏng RTL.', file=sys.stderr)
        return 2
    except OSError as exc:
        print(f'Không thể chạy công cụ RTL: {exc}', file=sys.stderr)
        return 2
    if result.stdout:
        print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr)
    if result.returncode != 0:
        print('Mô phỏng báo lỗi; xem kết quả phía trên.', file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Đọc lại ví dụ từ sách và thực hành với bài đã tạo trước đây.')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='liệt kê các bài')
    create = sub.add_parser('init', help='tạo bản sao bài trong thư mục mới')
    create.add_argument('case', choices=tuple(CASES))
    create.add_argument('--dir', required=True, type=Path)
    simulate = sub.add_parser('run', help='phát lại trích đoạn hoặc chạy bài mô phỏng cũ')
    simulate.add_argument('--dir', required=True, type=Path)
    simulate.add_argument('--pdf', type=Path, help='PDF manual cá nhân (hoặc TSHELL_REFERENCE_PDF)')
    read = sub.add_parser('source', help='đọc trang PDF nguồn của bài từ tài liệu gốc')
    read.add_argument('--dir', required=True, type=Path)
    read.add_argument('--page', required=True, type=int)
    read.add_argument('--pdf', type=Path, help='PDF manual cá nhân (hoặc TSHELL_REFERENCE_PDF)')
    cmd = sub.add_parser('commands', help='xem các lệnh Tessent trích từ ví dụ T3 trong sách')
    cmd.add_argument('--dir', required=True, type=Path)
    cmd.add_argument('--pdf', type=Path, help='PDF manual cá nhân (hoặc TSHELL_REFERENCE_PDF)')
    args = parser.parse_args()
    if args.command == 'list':
        print('\n'.join(CASES))
        return 0
    if args.command == 'init':
        return init(args.case, args.dir)
    if args.command == 'source':
        return source(args.dir, args.page, args.pdf)
    if args.command == 'commands':
        return commands(args.dir, args.pdf)
    return run(args.dir, args.pdf)


if __name__ == '__main__':
    raise SystemExit(main())
