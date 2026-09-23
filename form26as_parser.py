from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from typing import Optional
from schemas import Form26ASData

# TaxSathi - Form 26AS Parser
# User Story: Will develop and test the parsing module to convert documents into structured data.

def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def pan(text: str) -> Optional[str]:
    m = re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", text.upper())
    return m.group(0) if m else None

def assessment_year(text: str) -> Optional[str]:
    patterns = [
        r"assessment\s*year\s*[:\-]?\s*((?:20\d{2})\s*[-/]\s*(?:20\d{2}))",
        r"assessment\s*year\s*[:\-]?\s*((?:20\d{2})\s*[-/]\s*(?:\d{2}))",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return m.group(1).strip()
    return None

def parse_form26as(text: str) -> Form26ASData:
    text = clean_text(text)
    return Form26ASData(
        pan=pan(text),
        assessment_year=assessment_year(text),
        part_a_tds=[],
        part_c_advance_tax=[],
    )

def main():
    if len(sys.argv) < 2:
        print("Usage: python form26as_parser.py <form26as.txt|form26as.md> [output.json]")
        raise SystemExit(1)
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name(src.stem + "_structured.json")
    result = parse_form26as(src.read_text(encoding="utf-8"))
    out.write_text(json.dumps(result.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written: {out}")

if __name__ == "__main__":
    main()
