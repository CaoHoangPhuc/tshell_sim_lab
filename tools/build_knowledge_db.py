#!/usr/bin/env python3
"""Offline Knowledge Base Ingestion Tool.

Extracts structured rule metadata, DRC reference transcripts, textbook walkthrough
commands, and case study page contents from the official reference manual PDF into
a standalone JSON database (tessent_core/knowledge_db.json).

This script is run once offline. The runtime simulation environment (tshell, drc,
exercises) reads purely from the generated JSON database with zero runtime PDF
or PyMuPDF dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF = ROOT / "tshell_ref.pdf" if (ROOT / "tshell_ref.pdf").exists() else ROOT.parent / "tshell_ref.pdf"
CATALOG_PATH = ROOT / "tessent_core" / "drc_catalog.json"
OUTPUT_DB = ROOT / "tessent_core" / "knowledge_db.json"

CASES_METADATA = {
    "case01": {
        "rule": "T3",
        "title": "Scan chain trace blocked at gate",
        "pdf_pages": [4522, 4523, 4524],
        "printed_pages": "12-790–12-792",
        "strobe_page": 4522,
        "start_marker": "//  Error: Scan chain chain1 blocked at gate /reg2/df2",
        "end_marker": "(T3-1)",
    },
    "case02": {
        "rule": "T4",
        "title": "Scan chain trace clock inputs violation",
        "pdf_pages": [4525, 4526, 4527, 4528],
        "printed_pages": "12-793–12-796",
        "strobe_page": 4525,
        "start_marker": "//  Error: Clock inputs of /datao/reg_q_0_",
        "end_marker": "(T4-1)",
    },
    "case03": {
        "rule": "T5",
        "title": "Clock has X value during scan chain trace",
        "pdf_pages": [4529, 4530, 4531],
        "printed_pages": "12-797–12-799",
        "strobe_page": 4529,
        "start_marker": "//  Error: clock input of /datao/reg_q_0_",
        "end_marker": "(T3-1)",
    },
    "case04": {
        "rule": "C1",
        "title": "Clock PIs off failed to force off a clock line of memory element",
        "pdf_pages": [3809, 3810, 3811, 3812, 3813, 3814],
        "printed_pages": "12-77–12-82",
        "strobe_page": 3812,
        "start_marker": "// Error: Clock PIs off failed to force off a clock line of /U$1/DFF1",
        "end_marker": "(C1-1)",
    },
    "case05": {
        "rule": "D1",
        "title": "Scan cell disturbed during load_unload procedure",
        "pdf_pages": [3863, 3864, 3865, 3866],
        "printed_pages": "12-131–12-134",
        "strobe_page": 3865,
        "start_marker": "//  ERROR: /dataot/reg_q_0_ (373) disturbed during time 0 of grp1",
        "end_marker": "(D1-1)",
    },
}


def build_database(pdf_path: Path, catalog_path: Path, output_path: Path) -> int:
    try:
        import pymupdf
    except ImportError:
        print("Error: PyMuPDF is required for offline ingestion. Install with: pip install pymupdf", file=sys.stderr)
        return 1

    if not pdf_path.is_file():
        print(f"Error: PDF file not found at '{pdf_path}'", file=sys.stderr)
        return 1

    if not catalog_path.is_file():
        print(f"Error: Catalog file not found at '{catalog_path}'", file=sys.stderr)
        return 1

    print(f"//  Ingesting reference knowledge from '{pdf_path.name}'...")
    with open(catalog_path, encoding="utf-8") as f:
        catalog = json.load(f)

    pdf = pymupdf.open(pdf_path)

    db = {
        "version": "2026.2",
        "rules": catalog,
        "case_studies": {},
    }

    # Extract case studies
    for cid, info in CASES_METADATA.items():
        p_num = info["strobe_page"]
        p_text = pdf[p_num - 1].get_text()
        s_idx = p_text.find(info["start_marker"])
        e_idx = p_text.find(info["end_marker"], s_idx)
        excerpt = p_text[s_idx:e_idx + len(info["end_marker"])].strip() if s_idx >= 0 and e_idx >= 0 else ""

        page_texts = {}
        for p in info["pdf_pages"]:
            page_texts[str(p)] = pdf[p - 1].get_text()

        commands_map = {}
        if cid == "case01":
            p4522 = page_texts["4522"].split("How to Debug T3 Violations Without Tessent Visualizer", 1)[1]
            prefixes = ("set_trace_report ", "set_gate_level ", "set_gate_report ",
                        "set_system_mode ", "report_gate ", "report_gates ")
            commands_map["4522"] = [l.strip() for l in p4522.splitlines() if l.strip().startswith(prefixes)]
            commands_map["4523"] = [l.strip() for l in page_texts["4523"].splitlines() if l.strip().startswith(prefixes)]
            commands_map["4524"] = [l.strip() for l in page_texts["4524"].splitlines() if l.strip().startswith(prefixes)]

        db["case_studies"][cid] = {
            "case_id": cid,
            "rule": info["rule"],
            "title": info["title"],
            "strobe_page": info["strobe_page"],
            "printed_pages": info["printed_pages"],
            "pdf_pages": info["pdf_pages"],
            "first_page": info["pdf_pages"][0],
            "last_page": info["pdf_pages"][-1],
            "excerpt": excerpt,
            "commands": commands_map,
            "page_texts": page_texts,
        }

    # Enrich core rules with summaries
    for rk in ["C1", "C2", "T3", "T4", "T5", "D1"]:
        if rk in db["rules"]:
            p = db["rules"][rk]["page"]
            txt = pdf[p - 1].get_text()
            lines = [l.strip() for l in txt.splitlines() if l.strip()]
            db["rules"][rk]["summary"] = "\n".join(lines[:12])

    db["rules"]["C1"]["reference_excerpt"] = "// Error: Clock PIs off failed to force off a clock line of /U$1/DFF1 \n// (14). (C1-1)"
    db["rules"]["C2"]["reference_excerpt"] = "// Warning: Clock clk cannot reach the clock port of any memory element. (C2-1)"
    db["rules"]["T3"]["reference_excerpt"] = "//  Error: Scan chain chain1 blocked at gate /reg2/df2 (39) after tracing 1 \ncells.  (T3-1)"
    db["rules"]["T4"]["reference_excerpt"] = "//  Error: Clock inputs of /datao/reg_q_0_ (360) never set active during\n//  shift procedure.  (T4-1)"
    db["rules"]["T5"]["reference_excerpt"] = "//  Error: clock input of /datao/reg_q_0_ (360) set to X.  (T5-1)"
    db["rules"]["D1"]["reference_excerpt"] = "//  ERROR: /dataot/reg_q_0_ (373) disturbed during time 0 of grp1 \n//         load_unload procedure. (D1-1)"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)

    print(f"//  Database generated successfully: {output_path} ({output_path.stat().st_size:,} bytes)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build offline knowledge DB from reference manual PDF.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="Path to tshell_ref.pdf")
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH, help="Path to drc_catalog.json")
    parser.add_argument("--output", type=Path, default=OUTPUT_DB, help="Output path for knowledge_db.json")
    args = parser.parse_args()

    return build_database(args.pdf, args.catalog, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
