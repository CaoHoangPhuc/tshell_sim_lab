#!/usr/bin/env python3
"""Replay document excerpts; preserve older standalone simulation exercises."""
from __future__ import annotations

import argparse
import json
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

# Markers identify the excerpts in the knowledge base.
BOOK_CASES = {
    'case01': (4522, 4522, 4524, '//  Error: Scan chain chain1 blocked at gate /reg2/df2', '(T3-1)'),
    'case02': (4525, 4525, 4528, '//  Error: Clock inputs of /datao/reg_q_0_', '(T4-1)'),
    'case03': (4529, 4529, 4531, '//  Error: clock input of /datao/reg_q_0_', '(T3-1)'),
    'case04': (3812, 3809, 3814, '// Error: Clock PIs off failed to force off a clock line of /U$1/DFF1', '(C1-1)'),
    'case05': (3865, 3863, 3866, '//  ERROR: /dataot/reg_q_0_ (373) disturbed during time 0 of grp1', '(D1-1)'),
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


def book_page(number: int, case: str | None = None) -> str:
    if not DB:
        raise ValueError('Không tìm thấy cơ sở dữ liệu tri thức (knowledge_db.json).')
    if case and case in CASE_STUDIES:
        texts = CASE_STUDIES[case].get('page_texts', {})
        if str(number) in texts:
            return texts[str(number)]
    for cdata in CASE_STUDIES.values():
        texts = cdata.get('page_texts', {})
        if str(number) in texts:
            return texts[str(number)]
    raise ValueError(f'Trang PDF {number} không tồn tại trong cơ sở dữ liệu tri thức.')


def replay(case: str) -> int:
    case_data = CASE_STUDIES.get(case)
    if not case_data or not case_data.get('excerpt'):
        print(f'Không tìm thấy đoạn lỗi gốc cho {case}; kiểm tra cơ sở dữ liệu tri thức.', file=sys.stderr)
        return 2
    number = case_data.get('strobe_page', case_data.get('pdf_pages', [None])[0])
    excerpt = case_data['excerpt']
    print(f'Trích trực tiếp từ PDF trang {number} (phát lại; không chạy Tessent DRC):')
    print(excerpt)
    print('Đây là log trong sách, không đánh giá bài làm hay thực thi lại thiết kế.')
    return 0


def source(directory: Path, page: int) -> int:
    try:
        meta = json.loads((directory / 'case.json').read_text(encoding='utf-8'))
        if not isinstance(meta, dict) or meta.get('format') != FORMAT or meta.get('case') not in BOOK_CASES:
            raise ValueError('Bài này không phải bài đọc nguồn từ sách.')
        case = meta['case']
        case_data = CASE_STUDIES.get(case)
        if not case_data:
            raise ValueError(f'Không tìm thấy dữ liệu bài {case} trong cơ sở tri thức.')
        first = case_data.get('first_page', case_data.get('pdf_pages', [0])[0])
        last = case_data.get('last_page', case_data.get('pdf_pages', [0])[-1])
        if page < first or page > last:
            raise ValueError(f'Bài này có trang nguồn từ {first} đến {last}.')
        original = case_data.get('page_texts', {}).get(str(page))
        if original is None:
            page_cmds = case_data.get('commands', {}).get(str(page), [])
            if page_cmds:
                original = (
                    f"--- Lệnh tham chiếu từ trang {page} (Zero-Asset Clean-Room) ---\n"
                    + "\n".join(page_cmds) + "\n\n"
                    + "// Ghi chú: Toàn văn trang sách không lưu sẵn trong repo để tuân thủ Zero-Asset Policy và LEGAL.md.\n"
                    + "// Để nạp toàn văn trang sách, chạy: python3 tools/build_knowledge_db.py --pdf <tshell_ref.pdf>\n"
                )
            else:
                original = (
                    f"--- Trang {page} (Zero-Asset Clean-Room) ---\n"
                    + "// Toàn văn trang sách không lưu sẵn trong repo để tuân thủ Zero-Asset Policy và LEGAL.md.\n"
                    + "// Để nạp toàn văn trang sách, chạy: python3 tools/build_knowledge_db.py --pdf <tshell_ref.pdf>\n"
                )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'Không thể đọc trang nguồn: {exc}', file=sys.stderr)
        return 2
    print(f'Trích trực tiếp từ PDF trang {page}; không phải output của Tessent đang chạy:')
    sys.stdout.write(original)
    return 0


def commands(directory: Path) -> int:
    """Print the non-Visualizer T3 walkthrough's command lines from the knowledge DB."""
    try:
        meta = json.loads((directory / 'case.json').read_text(encoding='utf-8'))
        if not isinstance(meta, dict) or meta.get('format') != FORMAT or meta.get('case') not in BOOK_CASES:
            raise ValueError('Bài này không phải bài đọc nguồn từ sách.')
        case = meta['case']
        case_data = CASE_STUDIES.get(case)
        if not case_data or not case_data.get('commands'):
            raise ValueError('Chưa hỗ trợ trích lệnh cho case này.')
        page_commands = case_data['commands']
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'Không thể đọc lệnh gốc: {exc}', file=sys.stderr)
        return 2
    print('Lệnh Tessent trích từ PDF để tham khảo; không thực thi Tessent:')
    for number, lines in page_commands.items():
        print(f'--- Trang PDF {number} ---')
        for line in lines:
            print(line)
    return 0


def run(directory: Path) -> int:
    design = directory / 'design.v'
    manifest_path = directory / 'case.json'
    procedure = directory / 'procedure.vh'
    try:
        if manifest_path.exists():
            meta = json.loads(manifest_path.read_text(encoding='utf-8'))
            if not isinstance(meta, dict) or meta.get('format') not in (FORMAT, LEGACY_FORMAT) or meta.get('case') not in CASES:
                raise ValueError('định dạng hoặc mã bài không hợp lệ')
            if meta['format'] == FORMAT:
                return replay(meta['case'])
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
    read = sub.add_parser('source', help='đọc trang PDF nguồn của bài từ tài liệu gốc')
    read.add_argument('--dir', required=True, type=Path)
    read.add_argument('--page', required=True, type=int)
    cmd = sub.add_parser('commands', help='xem các lệnh Tessent trích từ ví dụ T3 trong sách')
    cmd.add_argument('--dir', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'list':
        print('\n'.join(CASES))
        return 0
    if args.command == 'init':
        return init(args.case, args.dir)
    if args.command == 'source':
        return source(args.dir, args.page)
    if args.command == 'commands':
        return commands(args.dir)
    return run(args.dir)


if __name__ == '__main__':
    raise SystemExit(main())
