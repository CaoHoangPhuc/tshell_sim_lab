#!/usr/bin/env python3
"""Build the distributable index from local metadata, without copying a manual."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / 'tessent_core' / 'drc_catalog.json'
OUTPUT_DB = ROOT / 'tessent_core' / 'knowledge_db.json'

# Page numbers are identifiers, not a copy of the manual itself.
CASES = {
    'case01': ('T3', 'Scan chain trace blocked at gate', range(4522, 4525), '12-790–12-792', 4522),
    'case02': ('T4', 'Scan chain clock activity', range(4525, 4529), '12-793–12-796', 4525),
    'case03': ('T5', 'Unknown scan chain clock', range(4529, 4532), '12-797–12-799', 4529),
    'case04': ('C1', 'Clock off-state', range(3809, 3815), '12-77–12-82', 3812),
    'case05': ('D1', 'Scan cell disturbance', range(3863, 3867), '12-131–12-134', 3865),
}


def build_database(catalog_path: Path, output_path: Path) -> None:
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    # Only these fields are part of the distribution contract; never copy
    # summaries, page text or transcripts supplied by an external source.
    fields = ('rule_id', 'family', 'title', 'page')
    rules = {key: {k: value[k] for k in fields if k in value}
             for key, value in catalog.items()}
    cases = {}
    for case_id, (rule, title, pages, printed, strobe) in CASES.items():
        pages = list(pages)
        cases[case_id] = {'case_id': case_id, 'rule': rule, 'title': title,
                          'pdf_pages': pages, 'first_page': pages[0], 'last_page': pages[-1],
                          'printed_pages': printed, 'strobe_page': strobe}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({'version': '2026.2', 'rules': rules, 'case_studies': cases},
                                      indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description='Build a metadata-only rule and case index.')
    parser.add_argument('--catalog', type=Path, default=CATALOG_PATH)
    parser.add_argument('--output', type=Path, default=OUTPUT_DB)
    args = parser.parse_args()
    try:
        build_database(args.catalog, args.output)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f'error: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
