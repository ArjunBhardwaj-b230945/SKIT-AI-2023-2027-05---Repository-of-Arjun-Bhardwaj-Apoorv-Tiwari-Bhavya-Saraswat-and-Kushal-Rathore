from __future__ import annotations
import json
import re
import sys
from pathlib import Path
from typing import Optional
from schemas import Form16Data, SalaryIncome, Section10Exemptions, ChapterVIADeductions

# TaxSathi - Form 16 Parser
# User Story: Will develop and test the parsing module to convert documents into structured data.

AMOUNT = r"(?:₹|Rs\.?|INR)?\s*([0-9][0-9,]*(?:\.\d+)?)"

def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def amount(text: str, patterns: list[str]) -> Optional[float]:
    for p in patterns:
        m = re.search(p, text, re.I | re.M)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    return None

def text_value(text: str, patterns: list[str]) -> Optional[str]:
    for p in patterns:
        m = re.search(p, text, re.I | re.M)
        if m:
            return m.group(1).strip()
    return None

def pan(text: str) -> Optional[str]:
    m = re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", text.upper())
    return m.group(0) if m else None

def tan(text: str) -> Optional[str]:
    m = re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", text.upper())
    return m.group(0) if m else None

def parse_form16(text: str) -> Form16Data:
    text = clean_text(text)

    salary = SalaryIncome(
        salary_17_1=amount(text, [rf"salary.*?section\s*17\(1\).*?{AMOUNT}"]),
        perquisites_17_2=amount(text, [rf"perquisites.*?17\(2\).*?{AMOUNT}"]),
        profit_in_lieu_17_3=amount(text, [rf"profits?\s+in\s+lieu.*?17\(3\).*?{AMOUNT}"]),
        total_gross_salary=amount(text, [rf"total\s+gross\s+salary.*?{AMOUNT}", rf"gross\s+salary.*?{AMOUNT}"]),
    )

    exemptions = Section10Exemptions(
        travel_concession_10_5=amount(text, [rf"travel\s+concession.*?10\(5\).*?{AMOUNT}"]),
        hra_10_13a=amount(text, [rf"house\s+rent\s+allowance.*?10\(13A\).*?{AMOUNT}", rf"HRA.*?10\(13A\).*?{AMOUNT}"]),
        total_sec_10_exemptions=amount(text, [rf"total.*?section\s*10.*?exemption.*?{AMOUNT}"]),
    )

    deductions = ChapterVIADeductions(
        sec_80c=amount(text, [rf"section\s*80C.*?{AMOUNT}", rf"\b80C\b.*?{AMOUNT}"]),
        sec_80d=amount(text, [rf"section\s*80D.*?{AMOUNT}", rf"\b80D\b.*?{AMOUNT}"]),
        sec_80g=amount(text, [rf"section\s*80G.*?{AMOUNT}", rf"\b80G\b.*?{AMOUNT}"]),
        total_chapter_vi_a=amount(text, [rf"total.*?chapter\s*VI[- ]?A.*?{AMOUNT}"]),
    )

    return Form16Data(
        employee_pan=pan(text),
        employer_tan=tan(text),
        assessment_year=text_value(text, [
            r"assessment\s*year\s*[:\-]?\s*((?:20\d{2})\s*[-/]\s*(?:20\d{2}))",
            r"assessment\s*year\s*[:\-]?\s*((?:20\d{2})\s*[-/]\s*(?:\d{2}))",
        ]),
        salary_components=salary,
        exemptions=exemptions,
        standard_deduction_16_ia=amount(text, [rf"standard\s+deduction.*?16\(ia\).*?{AMOUNT}", rf"standard\s+deduction.*?{AMOUNT}"]),
        deductions=deductions,
        tax_deducted=amount(text, [rf"total\s+tax\s+deducted.*?{AMOUNT}", rf"tax\s+deducted.*?{AMOUNT}"]),
    )

def main():
    if len(sys.argv) < 2:
        print("Usage: python form16_parser.py <form16.txt|form16.md> [output.json]")
        raise SystemExit(1)
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name(src.stem + "_structured.json")
    result = parse_form16(src.read_text(encoding="utf-8"))
    out.write_text(json.dumps(result.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written: {out}")

if __name__ == "__main__":
    main()
