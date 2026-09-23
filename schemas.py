from typing import List, Optional
from pydantic import BaseModel, Field

# TaxSathi - Document Parsing
# User Story: Will develop and test the parsing module to convert documents into structured data.

class SalaryIncome(BaseModel):
    salary_17_1: Optional[float] = None
    perquisites_17_2: Optional[float] = None
    profit_in_lieu_17_3: Optional[float] = None
    total_gross_salary: Optional[float] = None

class Section10Exemptions(BaseModel):
    travel_concession_10_5: Optional[float] = None
    hra_10_13a: Optional[float] = None
    total_sec_10_exemptions: Optional[float] = None

class ChapterVIADeductions(BaseModel):
    sec_80c: Optional[float] = None
    sec_80d: Optional[float] = None
    sec_80g: Optional[float] = None
    total_chapter_vi_a: Optional[float] = None

class Form16Data(BaseModel):
    employee_pan: Optional[str] = None
    employer_tan: Optional[str] = None
    assessment_year: Optional[str] = None
    salary_components: SalaryIncome = Field(default_factory=SalaryIncome)
    exemptions: Section10Exemptions = Field(default_factory=Section10Exemptions)
    standard_deduction_16_ia: Optional[float] = None
    deductions: ChapterVIADeductions = Field(default_factory=ChapterVIADeductions)
    tax_deducted: Optional[float] = None

class TDSEntry(BaseModel):
    deductor_tan: Optional[str] = None
    deductor_name: Optional[str] = None
    total_amount_paid: Optional[float] = None
    total_tds: Optional[float] = None

class AdvanceTaxEntry(BaseModel):
    bsr_code: Optional[str] = None
    date_of_deposit: Optional[str] = None
    challan_serial_no: Optional[str] = None
    tax_amount: Optional[float] = None

class Form26ASData(BaseModel):
    pan: Optional[str] = None
    assessment_year: Optional[str] = None
    part_a_tds: List[TDSEntry] = Field(default_factory=list)
    part_c_advance_tax: List[AdvanceTaxEntry] = Field(default_factory=list)
