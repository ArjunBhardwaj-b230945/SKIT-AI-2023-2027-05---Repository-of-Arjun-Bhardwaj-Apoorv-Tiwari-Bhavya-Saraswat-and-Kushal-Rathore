"""
inspect_parsed_output.py
================================================================================
TaxSathi - ITR Assistance -- LlamaParse Integration (Sprint 1)

Automated version of the "test checklist": run this AFTER
llamaparse_integration.py has saved output, to confirm the parse actually
picked up the things a Form16/Form26AS extraction pipeline will need next
sprint (PAN/TAN, headings, key sections, tables, page count).

This does NOT extract or validate tax data -- it only checks that expected
KEYWORDS are present in the parsed text, as a sanity check that LlamaParse
read the document properly. Real field-level extraction is next sprint.

Usage:
    python inspect_parsed_output.py parsed_output/form16 form16
    python inspect_parsed_output.py parsed_output/comprehensive_form_26as_sample form26as
================================================================================
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# keyword -> human-readable description of what it confirms
CHECKLISTS = {
    "form16": {
        "PAN": "PAN (employee/deductor) appears somewhere in the text",
        "TAN": "TAN (deductor) appears somewhere in the text",
        "Assessment Year": "'Assessment Year' label was picked up",
        "Salaries": "'Salaries' section header (Part B) was picked up",
        "Chapter VI": "Chapter VI-A deductions section was picked up",
    },
    "form26as": {
        "PAN": "PAN of the assessee appears somewhere in the text",
        "TDS": "'TDS' keyword (Part A) appears in the text",
        "Assessment Year": "'Assessment Year' label was picked up",
        "Advance Tax": "'Advance Tax' / Part C section was picked up",
    },
}


def run_checklist(md_path: Path, doc_type: str) -> bool:
    if not md_path.exists():
        print(f"[FAIL] Could not find {md_path} -- did the parse + save step run first?")
        return False

    text = md_path.read_text(encoding="utf-8")
    checklist = CHECKLISTS.get(doc_type)
    if checklist is None:
        print(f"[FAIL] Unknown doc_type '{doc_type}'. Expected one of: {list(CHECKLISTS)}")
        return False

    print(f"\nChecklist for {md_path.name} (doc_type={doc_type})")
    print("-" * 65)
    all_passed = bool(text.strip())
    if not text.strip():
        print("[FAIL] Parsed markdown is EMPTY -- parsing likely failed silently.")

    for keyword, description in checklist.items():
        found = keyword.lower() in text.lower()
        print(f"[{'PASS' if found else 'FAIL'}] {description}  (looked for: '{keyword}')")
        all_passed = all_passed and found

    print(f"\nCharacters extracted: {len(text)}")
    print("OVERALL:", "LOOKS GOOD" if all_passed else "NEEDS REVIEW -- see FAILs above")
    return all_passed


def check_items_json(items_path: Path) -> None:
    if not items_path.exists():
        print(f"\n[INFO] No items file at {items_path} -- structured items were not saved.")
        return
    data = json.loads(items_path.read_text(encoding="utf-8"))
    pages = data.get("pages", [])
    table_count = sum(1 for page in pages for item in page.get("items", []) if item.get("type") == "table")
    print(f"\nStructured items: {len(pages)} page(s) inspected, {table_count} table(s) detected.")
    if table_count == 0:
        print("  (Form16/Form26AS are table-heavy -- 0 tables detected may be worth a closer look.)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python inspect_parsed_output.py <path_without_extension> <form16|form26as>")
        sys.exit(1)

    base = Path(sys.argv[1])
    doc_type = sys.argv[2]
    run_checklist(base.with_suffix(".md"), doc_type)
    check_items_json(Path(f"{base}_items.json"))
