"""
inspect_parsed_output.py
================================================================================
TanSathi - ITR Assistance -- LlamaParse Integration (Sprint 1)

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
import re
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


def _keyword_present(keyword: str, text: str) -> bool:
    """
    Word-boundary match, NOT a plain substring check.

    A plain `keyword.lower() in text.lower()` check is a real bug here: 'TAN'
    matches inside 'STANDARD' ('S-TAN-dard'), and 'PAN' matches inside common
    words like 'company' or 'expand'. Form16 literally contains the phrase
    "Standard deduction under section 16(ia)" -- so the old check would report
    "TAN detected" as PASS even on a document where no TAN was ever parsed,
    which defeats the purpose of the check.
    """
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


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
        found = _keyword_present(keyword, text)
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

    # Normalize once: strip any suffix the caller might have accidentally included
    # (e.g. "...form16.md" instead of "...form16"), so the .md path and the
    # _items.json path are always derived consistently from the same base --
    # previously the .md path was extension-aware (.with_suffix) while the
    # _items.json path was built by raw string concatenation, which could
    # silently diverge if a suffix was present.
    base = Path(sys.argv[1])
    base = base.with_suffix("") if base.suffix else base
    doc_type = sys.argv[2]

    passed = run_checklist(base.with_suffix(".md"), doc_type)
    check_items_json(Path(f"{base}_items.json"))

    # A "test checklist" that always exits 0 can't gate anything (CI, or just
    # "did this actually work before I move to the next sprint"). Signal failure.
    sys.exit(0 if passed else 1)
