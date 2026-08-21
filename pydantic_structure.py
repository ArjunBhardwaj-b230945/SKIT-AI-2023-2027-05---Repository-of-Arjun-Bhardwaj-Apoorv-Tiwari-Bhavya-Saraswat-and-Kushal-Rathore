from pydantic import BaseModel, Field
from typing import List, Optional

# --- Form 16 Sub-Schemas ---

class SalaryIncome(BaseModel):
    salary_17_1: float = Field(default=0.0, description="Salary as per section 17(1)")
    perquisites_17_2: float = Field(default=0.0, description="Value of perquisites under section 17(2)")
    profit_in_lieu_17_3: float = Field(default=0.0, description="Profits in lieu of salary under section 17(3)")
    total_gross_salary: float = Field(default=0.0)

class Section10Exemptions(BaseModel):
    travel_concession_10_5: float = Field(default=0.0)
    hra_10_13a: float = Field(default=0.0)
    total_sec_10_exemptions: float = Field(default=0.0)

class ChapterVIADeductions(BaseModel):
    sec_80c: float = Field(default=0.0, description="Deductible amount for 80C")
    sec_80d: float = Field(default=0.0, description="Deductible amount for 80D")
    sec_80g: float = Field(default=0.0, description="Deductible amount for 80G")
    total_chapter_vi_a: float = Field(default=0.0)

class Form16Schema(BaseModel):
    employee_pan: str = Field(description="PAN of the Employee")
    employer_tan: str = Field(description="TAN of the Deductor")
    assessment_year: str 
    opting_out_115bac: str = Field(description="Whether opting out of taxation u/s 115BAC(1A)? YES/NO")
    salary_components: SalaryIncome
    exemptions: Section10Exemptions
    standard_deduction_16_ia: float = Field(default=50000.0)
    deductions: ChapterVIADeductions
    net_tax_payable: float = Field(default=0.0)

# --- Form 26AS Sub-Schemas ---

class TDSEntry(BaseModel):
    deductor_tan: str
    deductor_name: str
    total_amount_paid: float
    total_tds: float

class AdvanceTaxEntry(BaseModel):
    bsr_code: str
    date_of_deposit: str
    challan_serial_no: str
    tax_amount: float

class Form26ASSchema(BaseModel):
    pan: str
    assessment_year: str
    part_a_tds: List[TDSEntry] = Field(default_factory=list)
    part_c_advance_tax: List[AdvanceTaxEntry] = Field(default_factory=list)