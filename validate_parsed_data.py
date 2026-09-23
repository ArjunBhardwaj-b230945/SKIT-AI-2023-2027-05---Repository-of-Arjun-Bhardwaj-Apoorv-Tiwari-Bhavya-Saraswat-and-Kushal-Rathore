from __future__ import annotations
import json
import sys
from pathlib import Path
from schemas import Form16Data, Form26ASData

# TaxSathi - Document Parsing Output Validation
# User Story: Will develop and test the parsing module to convert documents into structured data.

def validate_form16(path: Path) -> list[str]:
    model = Form16Data.model_validate(json.loads(path.read_text(encoding="utf-8")))
    issues = []
    if not model.employee_pan: issues.append("PAN not extracted.")
    if not model.assessment_year: issues.append("Assessment Year not extracted.")
    if model.salary_components.total_gross_salary is None: issues.append("Gross salary not extracted.")
    if model.tax_deducted is None: issues.append("Tax deducted not extracted.")
    return issues

def validate_form26as(path: Path) -> list[str]:
    model = Form26ASData.model_validate(json.loads(path.read_text(encoding="utf-8")))
    issues = []
    if not model.pan: issues.append("PAN not extracted.")
    if not model.assessment_year: issues.append("Assessment Year not extracted.")
    if not model.part_a_tds: issues.append("No Part A TDS rows extracted; review the source table manually.")
    return issues

def main():
    if len(sys.argv) != 3:
        print("Usage: python validate_parsed_data.py <form16.json> <form26as.json>")
        raise SystemExit(1)
    f16, f26 = Path(sys.argv[1]), Path(sys.argv[2])
    a, b = validate_form16(f16), validate_form26as(f26)
    print("Form 16:", "PASS" if not a else "REVIEW")
    for x in a: print(" -", x)
    print("Form 26AS:", "PASS" if not b else "REVIEW")
    for x in b: print(" -", x)

if __name__ == "__main__":
    main()
