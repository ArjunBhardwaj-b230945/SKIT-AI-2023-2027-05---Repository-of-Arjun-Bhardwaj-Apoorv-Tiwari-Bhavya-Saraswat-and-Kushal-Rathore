from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, computed_field, model_validator


# ================================================================================
# SECTION 0 -- SHARED HELPERS
# ================================================================================

class YesNo(str, Enum):
    YES = "YES"
    NO = "NO"


class FlagSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationFlag(BaseModel):
    """
    The ONLY mechanism by which the pipeline communicates 'something is
    missing / uncertain / inconsistent'. Every stage appends to a flags list
    instead of silently defaulting a value.
    """
    stage: str = Field(description="e.g. 'extraction', 'reconciliation', 'itr_mapping', 'itr_validation'")
    field: str = Field(description="Dotted path to the affected field")
    issue: str = Field(description="Human-readable description of the issue")
    severity: FlagSeverity = FlagSeverity.WARNING


def _sum_known(*values: Optional[float]) -> Tuple[Optional[float], bool]:
    """
    Sum only the values that are not None.
    Returns (total, is_partial): is_partial=True means at least one input was
    missing, so `total` is a lower bound, NOT a verified total. Returns
    (None, False) if every value is missing.
    """
    present = [v for v in values if v is not None]
    if not present:
        return None, False
    return round(sum(present), 2), len(present) < len(values)


def _normalize_section_code(raw: Optional[str]) -> str:
    """Normalize a free-text section reference like 'Section 80TTB' or '80 TTB' to '80TTB'."""
    if not raw:
        return ""
    s = re.sub(r"[^0-9A-Za-z]", "", raw).upper()
    return re.sub(r"^(SECTION|SEC)", "", s)


class NamedDeductionEntry(BaseModel):
    """One free-text 'section ... Rs ...' row, e.g. from Form16 item 10(m)."""
    section: Optional[str] = Field(default=None, description="Section code as printed on the form, e.g. '80DD', '80U'")
    gross_amount: Optional[float] = None
    deductible_amount: Optional[float] = None


# ================================================================================
# SECTION 1 -- FORM 16 SCHEMAS
# ================================================================================

class EmployeeEmployerDetails(BaseModel):
    """Form 16 Part A -- identification fields."""
    certificate_no: Optional[str] = None
    employer_name: Optional[str] = None
    employer_pan: Optional[str] = None
    employer_tan: Optional[str] = None
    employee_name: Optional[str] = None
    employee_pan: Optional[str] = None
    assessment_year: Optional[str] = None
    period_from: Optional[str] = None
    period_to: Optional[str] = None


class SalaryIncome(BaseModel):
    """Form 16 Part B, item 1(a)-(e)."""
    salary_17_1: Optional[float] = None
    perquisites_17_2: Optional[float] = None
    profit_in_lieu_17_3: Optional[float] = None
    salary_from_other_employers_1e: Optional[float] = None

    gross_salary_total_1d: Optional[float] = Field(default=None, description="Computed: 1(a)+1(b)+1(c)")
    gross_salary_total_1d_is_partial: bool = False

    @model_validator(mode="after")
    def _compute(self):
        total, partial = _sum_known(self.salary_17_1, self.perquisites_17_2, self.profit_in_lieu_17_3)
        self.gross_salary_total_1d = total
        self.gross_salary_total_1d_is_partial = partial
        return self


class Section10Exemptions(BaseModel):
    """Form 16 Part B, item 2 -- allowances exempt u/s 10."""
    travel_concession_10_5: Optional[float] = None
    gratuity_10_10: Optional[float] = None
    commuted_pension_10_10a: Optional[float] = None
    leave_encashment_10_10aa: Optional[float] = None
    hra_10_13a: Optional[float] = None
    other_special_allowances_10_14: Optional[float] = None
    other_exemption_10: Optional[float] = None

    total_sec_10_exemptions_2i: Optional[float] = None
    total_sec_10_exemptions_2i_is_partial: bool = False

    @model_validator(mode="after")
    def _compute(self):
        total, partial = _sum_known(
            self.travel_concession_10_5, self.gratuity_10_10, self.commuted_pension_10_10a,
            self.leave_encashment_10_10aa, self.hra_10_13a, self.other_special_allowances_10_14,
            self.other_exemption_10,
        )
        self.total_sec_10_exemptions_2i = total
        self.total_sec_10_exemptions_2i_is_partial = partial
        return self


class Section16Deductions(BaseModel):
    """Form 16 Part B, item 4 -- deductions u/s 16."""
    standard_deduction_16_ia: Optional[float] = None
    entertainment_allowance_16_ii: Optional[float] = None
    professional_tax_16_iii: Optional[float] = None

    total_deductions_16: Optional[float] = None
    total_deductions_16_is_partial: bool = False

    @model_validator(mode="after")
    def _compute(self):
        total, partial = _sum_known(self.standard_deduction_16_ia, self.entertainment_allowance_16_ii, self.professional_tax_16_iii)
        self.total_deductions_16 = total
        self.total_deductions_16_is_partial = partial
        return self


class OtherIncomeReported(BaseModel):
    """Form 16 Part B, item 7 -- other income reported by employee for TDS."""
    house_property_income_7a: Optional[float] = None
    other_sources_income_7b: Optional[float] = None

    total_other_income_8: Optional[float] = None
    total_other_income_8_is_partial: bool = False

    @model_validator(mode="after")
    def _compute(self):
        total, partial = _sum_known(self.house_property_income_7a, self.other_sources_income_7b)
        self.total_other_income_8 = total
        self.total_other_income_8_is_partial = partial
        return self


class ChapterVIADeductions(BaseModel):
    """
    Form 16 Part B, item 10 -- Chapter VI-A deductions, matching Form16's OWN
    layout: named boxes for 10(a)-(l), plus a repeatable list for 10(m) ('any
    other provision(s)').

    Form16 itself does NOT provide named boxes for 80DD/80DDB/80EE/80EEA/
    80EEB/80GG/80GGA/80GGC/80TTB/80U -- when present, they appear as free-text
    'section ... Rs ...' rows under 10(m). Each such row MUST be captured
    individually in `other_via_entries`, never collapsed into a single float,
    because ITR-1 Part C needs each of these in its own named field. Routing
    happens in map_chapter_via_to_itr1() below; anything unrecognized is
    preserved and flagged there, never dropped.
    """
    sec_80c_80ccc_80ccd1_combined: Optional[float] = None  # 10(d)
    sec_80ccd_1b: Optional[float] = None                    # 10(e)
    sec_80ccd_2: Optional[float] = None                      # 10(f)
    sec_80d: Optional[float] = None                          # 10(g)
    sec_80e: Optional[float] = None                          # 10(h)
    sec_80cch_employee: Optional[float] = None                # 10(i)
    sec_80cch_govt: Optional[float] = None                    # 10(j)
    sec_80g: Optional[float] = None                          # 10(k)
    sec_80tta: Optional[float] = None                         # 10(l)
    other_via_entries: List[NamedDeductionEntry] = Field(default_factory=list, description="Raw rows from item 10(m)")

    aggregate_chapter_via_11: Optional[float] = None
    aggregate_chapter_via_11_is_partial: bool = False

    @model_validator(mode="after")
    def _compute(self):
        named_total, named_partial = _sum_known(
            self.sec_80c_80ccc_80ccd1_combined, self.sec_80ccd_1b, self.sec_80ccd_2,
            self.sec_80d, self.sec_80e, self.sec_80cch_employee, self.sec_80cch_govt,
            self.sec_80g, self.sec_80tta,
        )
        other_amounts = [e.deductible_amount for e in self.other_via_entries if e.deductible_amount is not None]
        other_total = round(sum(other_amounts), 2) if other_amounts else None
        other_partial = len(other_amounts) < len(self.other_via_entries)

        if named_total is None and other_total is None:
            self.aggregate_chapter_via_11 = None
            self.aggregate_chapter_via_11_is_partial = False
        else:
            self.aggregate_chapter_via_11 = round((named_total or 0.0) + (other_total or 0.0), 2)
            self.aggregate_chapter_via_11_is_partial = named_partial or other_partial
        return self


class TaxComputation(BaseModel):
    """
    Form 16 Part B, items 12-21 -- as computed by the EMPLOYER for TDS
    purposes (extracted, not recomputed here). NOT the final ITR liability --
    once Form26AS other-source income/TDS/TCS are reconciled in, the ITR-level
    computation supersedes this.
    """
    total_taxable_income_12: Optional[float] = None
    tax_on_total_income_13: Optional[float] = None
    rebate_87a_14: Optional[float] = None
    surcharge_15: Optional[float] = None
    cess_16: Optional[float] = None
    tax_payable_17: Optional[float] = None
    relief_89_18: Optional[float] = None
    tds_per_12baa_19: Optional[float] = None
    tcs_per_12baa_20: Optional[float] = None
    employer_reported_net_tax_payable_21: Optional[float] = None


class Form16Schema(BaseModel):
    """
    Structured representation of ONE Form 16 (Part A + Part B / Annexure-I).
    An employee who changed jobs mid-year will have MULTIPLE instances of
    this -- see `reconcile_tax_data(form16_documents: List[Form16Schema], ...)`.
    """
    details: EmployeeEmployerDetails = Field(default_factory=EmployeeEmployerDetails)
    opting_out_115bac: Optional[YesNo] = None
    salary_components: SalaryIncome = Field(default_factory=SalaryIncome)
    exemptions: Section10Exemptions = Field(default_factory=Section10Exemptions)
    section16_deductions: Section16Deductions = Field(default_factory=Section16Deductions)
    other_income_reported: OtherIncomeReported = Field(default_factory=OtherIncomeReported)
    deductions: ChapterVIADeductions = Field(default_factory=ChapterVIADeductions)
    tax_computation: TaxComputation = Field(default_factory=TaxComputation)

    net_salary_3: Optional[float] = Field(default=None, description="Item 3: 1(d) - 2(i)")
    income_chargeable_salaries_6: Optional[float] = Field(default=None, description="Item 6: 3 + 1(e) - 5")
    gross_total_income_9: Optional[float] = Field(default=None, description="Item 9: 6 + 8")

    @model_validator(mode="after")
    def _cross_compute(self):
        if self.salary_components.gross_salary_total_1d is not None and self.exemptions.total_sec_10_exemptions_2i is not None:
            self.net_salary_3 = round(self.salary_components.gross_salary_total_1d - self.exemptions.total_sec_10_exemptions_2i, 2)

        if (
            self.net_salary_3 is not None
            and self.salary_components.salary_from_other_employers_1e is not None
            and self.section16_deductions.total_deductions_16 is not None
        ):
            self.income_chargeable_salaries_6 = round(
                self.net_salary_3 + self.salary_components.salary_from_other_employers_1e - self.section16_deductions.total_deductions_16, 2
            )

        if self.income_chargeable_salaries_6 is not None and self.other_income_reported.total_other_income_8 is not None:
            self.gross_total_income_9 = round(self.income_chargeable_salaries_6 + self.other_income_reported.total_other_income_8, 2)

        return self


# ================================================================================
# SECTION 2 -- FORM 26AS SCHEMAS
# ================================================================================

class TDSSalaryEntry(BaseModel):
    """Form 26AS Part A -- TDS on salary."""
    deductor_tan: Optional[str] = None
    deductor_name: Optional[str] = None
    total_amount_paid: Optional[float] = None
    total_tax_deducted: Optional[float] = None
    total_tax_deposited: Optional[float] = None


class TDSInterestEntry(BaseModel):
    """Form 26AS Part A1 -- TDS on FD/interest income."""
    banking_entity_tan: Optional[str] = None
    financial_institution_name: Optional[str] = None
    total_interest_paid: Optional[float] = None
    total_tax_deducted: Optional[float] = None
    total_tax_deposited: Optional[float] = None


class TDSPropertyEntry(BaseModel):
    """Form 26AS Part A2 -- TDS on sale of immovable property u/s 194IA. Any entry implies capital gains, which ITR-1 does not support."""
    buyer_pan: Optional[str] = None
    buyer_name: Optional[str] = None
    total_transaction_value: Optional[float] = None
    total_tax_deducted: Optional[float] = None
    date_of_deposit: Optional[str] = None


class TCSEntry(BaseModel):
    """Form 26AS Part B -- Tax Collected at Source."""
    collector_tan: Optional[str] = None
    collector_name: Optional[str] = None
    total_amount_debited: Optional[float] = None
    total_tax_collected: Optional[float] = None
    total_tax_deposited: Optional[float] = None


class AdvanceTaxEntry(BaseModel):
    """Form 26AS Part C -- Advance Tax / Self-Assessment Tax paid."""
    bsr_code: Optional[str] = None
    date_of_deposit: Optional[str] = None
    challan_serial_no: Optional[str] = None
    tax_amount: Optional[float] = None


class RefundEntry(BaseModel):
    """Form 26AS Part D -- refunds for prior years. Reference only."""
    assessment_year: Optional[str] = None
    mode_of_payment: Optional[str] = None
    refund_issued: Optional[float] = None
    interest_paid: Optional[float] = None
    date_of_payment: Optional[str] = None


class SFTEntry(BaseModel):
    """Form 26AS Part E -- high-value transactions (SFT/AIR). For cross-checking/flagging only."""
    reporting_entity_name: Optional[str] = None
    transaction_type: Optional[str] = None
    transaction_date: Optional[str] = None
    aggregate_value: Optional[float] = None


class Form26ASSchema(BaseModel):
    """Structured representation of one Form 26AS (Parts A, A1, A2, B, C, D, E)."""
    pan: Optional[str] = None
    assessee_name: Optional[str] = None
    financial_year: Optional[str] = None
    assessment_year: Optional[str] = None

    part_a_tds_salary: List[TDSSalaryEntry] = Field(default_factory=list)
    part_a1_tds_interest: List[TDSInterestEntry] = Field(default_factory=list)
    part_a2_tds_property: List[TDSPropertyEntry] = Field(default_factory=list)
    part_b_tcs: List[TCSEntry] = Field(default_factory=list)
    part_c_advance_tax: List[AdvanceTaxEntry] = Field(default_factory=list)
    part_d_refunds: List[RefundEntry] = Field(default_factory=list)
    part_e_sft: List[SFTEntry] = Field(default_factory=list)

    @computed_field
    @property
    def total_tds_salary(self) -> Optional[float]:
        vals = [e.total_tax_deducted for e in self.part_a_tds_salary if e.total_tax_deducted is not None]
        return round(sum(vals), 2) if vals else None

    @computed_field
    @property
    def total_tds_interest(self) -> Optional[float]:
        vals = [e.total_tax_deducted for e in self.part_a1_tds_interest if e.total_tax_deducted is not None]
        return round(sum(vals), 2) if vals else None

    @computed_field
    @property
    def total_tcs(self) -> Optional[float]:
        vals = [e.total_tax_collected for e in self.part_b_tcs if e.total_tax_collected is not None]
        return round(sum(vals), 2) if vals else None

    @computed_field
    @property
    def total_advance_self_assessment_tax(self) -> Optional[float]:
        vals = [e.tax_amount for e in self.part_c_advance_tax if e.tax_amount is not None]
        return round(sum(vals), 2) if vals else None

    @computed_field
    @property
    def total_interest_income(self) -> Optional[float]:
        vals = [e.total_interest_paid for e in self.part_a1_tds_interest if e.total_interest_paid is not None]
        return round(sum(vals), 2) if vals else None

    @computed_field
    @property
    def has_property_transaction(self) -> bool:
        return len(self.part_a2_tds_property) > 0


# ================================================================================
# SECTION 3 -- USER-SUPPLIED INFORMATION (never from Form16/Form26AS)
# ================================================================================

class BankAccount(BaseModel):
    """ITR-1 Part E. Requires user input."""
    ifsc_code: Optional[str] = None
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    account_type: Optional[str] = None
    selected_for_refund: bool = False


class HouseOwnershipType(str, Enum):
    SELF_OCCUPIED = "self_occupied"
    LET_OUT = "let_out"
    DEEMED_LET_OUT = "deemed_let_out"


class HousePropertyDetail(BaseModel):
    """User-supplied; not derivable from Form16/Form26AS."""
    address: Optional[str] = None
    ownership_type: Optional[HouseOwnershipType] = None
    annual_value: Optional[float] = None
    interest_on_borrowed_capital: Optional[float] = None


class UserProvidedInfo(BaseModel):
    """
    Everything ITR-1 needs that CANNOT come from Form16/Form26AS: identity,
    contact, address, filing metadata, bank accounts, and house property
    details. This must be collected directly from the user -- via whatever
    layer owns session/profile state (frontend form, or the AI assistant
    through conversation) -- never inferred or defaulted by the document
    pipeline. This schema only defines the shape; where it's stored/collected
    is a decision for whoever owns that layer.
    """
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    aadhaar_number: Optional[str] = None
    primary_mobile: Optional[str] = None
    primary_email: Optional[str] = None
    address_line: Optional[str] = None
    town_city: Optional[str] = None
    state: Optional[str] = None
    pin_code: Optional[str] = None
    filed_under_section: Optional[str] = Field(default=None, description="e.g. '139(1)'")
    nature_of_employment: Optional[str] = None
    opting_out_115bac_confirmed: Optional[YesNo] = Field(default=None, description="User's final confirmed choice -- overrides Form16's assumption")
    house_properties: List[HousePropertyDetail] = Field(default_factory=list)
    bank_accounts: List[BankAccount] = Field(default_factory=list)


# ================================================================================
# SECTION 4 -- RECONCILIATION LAYER
# ================================================================================

class ReconciledTaxData(BaseModel):
    """
    Output of 'Tax Data Extraction -> Structured Tax Data -> Reconciliation'.
    Merges one-or-more Form16s + Form26AS, cross-checks them, and derives what
    ITR-1 field mapping needs. Every value is extracted, reconciled, or
    explicitly flagged -- never guessed.
    """
    form16_documents: List[Form16Schema] = Field(default_factory=list)
    form26as: Optional[Form26ASSchema] = None

    resolved_pan: Optional[str] = None
    pan_consistent: Optional[bool] = None

    salary_income_for_itr: Optional[float] = Field(default=None, description="Summed across ALL Form16 documents")
    other_sources_income_for_itr: Optional[float] = None
    resolved_chapter_via_deductions: Optional[ChapterVIADeductions] = Field(default=None, description="Taken from exactly one Form16 to avoid double-counting across employers")

    tds_salary_credit: Optional[float] = None
    tds_other_credit: Optional[float] = None
    tcs_credit: Optional[float] = None
    advance_self_assessment_tax_paid: Optional[float] = None

    form16_vs_26as_salary_tds_match: Optional[bool] = None

    has_property_capital_gains: bool = False
    has_multiple_employers: bool = False
    itr1_eligible: Optional[bool] = None

    flags: List[ValidationFlag] = Field(default_factory=list)

    def add_flag(self, stage: str, field: str, issue: str, severity: FlagSeverity = FlagSeverity.WARNING) -> None:
        self.flags.append(ValidationFlag(stage=stage, field=field, issue=issue, severity=severity))


def reconcile_tax_data(form16_documents: List[Form16Schema], form26as: Optional[Form26ASSchema]) -> ReconciledTaxData:
    """Implements the 'Form16(s) + Form26AS reconciled' stage. Accepts MULTIPLE Form16s (one per employer)."""
    data = ReconciledTaxData(form16_documents=form16_documents, form26as=form26as)
    data.has_multiple_employers = len(form16_documents) > 1

    # --- PAN cross-check across ALL Form16s + Form26AS ---
    f16_pans = {f.details.employee_pan.strip().upper() for f in form16_documents if f.details.employee_pan}
    f26_pan = form26as.pan.strip().upper() if (form26as and form26as.pan) else None

    if len(f16_pans) > 1:
        data.add_flag("reconciliation", "pan", f"Uploaded Form16 documents report different employee PANs: {sorted(f16_pans)}. Verify uploads before proceeding.", FlagSeverity.ERROR)
    elif f16_pans and f26_pan:
        f16_pan = next(iter(f16_pans))
        data.pan_consistent = f16_pan == f26_pan
        data.resolved_pan = f16_pan if data.pan_consistent else None
        if not data.pan_consistent:
            data.add_flag("reconciliation", "pan", f"Form16 PAN ({f16_pan}) does not match Form26AS PAN ({f26_pan}).", FlagSeverity.ERROR)
    elif f16_pans or f26_pan:
        data.resolved_pan = next(iter(f16_pans)) if f16_pans else f26_pan
        data.add_flag("reconciliation", "pan", "PAN found in only one source; could not cross-check.", FlagSeverity.WARNING)
    else:
        data.add_flag("reconciliation", "pan", "PAN not found in any source document.", FlagSeverity.ERROR)

    # --- Salary income: summed across ALL employers ---
    salary_values = [f.income_chargeable_salaries_6 for f in form16_documents]
    known_salary = [v for v in salary_values if v is not None]
    if known_salary:
        data.salary_income_for_itr = round(sum(known_salary), 2)
    if not form16_documents:
        data.add_flag("reconciliation", "salary_income", "No Form16 documents were provided.", FlagSeverity.ERROR)
    elif len(known_salary) < len(form16_documents):
        data.add_flag("reconciliation", "salary_income", f"{len(form16_documents) - len(known_salary)} of {len(form16_documents)} Form16 document(s) did not yield a usable 'income chargeable under Salaries' figure -- total salary income is a lower bound.", FlagSeverity.ERROR)

    if data.has_multiple_employers:
        data.add_flag(
            "reconciliation", "employment",
            f"{len(form16_documents)} Form16 documents were uploaded (multiple employers this year). Salary "
            f"income has been summed across all of them. This does NOT affect ITR-1 eligibility. Per Form16's "
            f"own instructions, only ONE employer's certificate (typically the last, at the employee's option) "
            f"carries the full Chapter VI-A computation -- see the deductions flag below.",
            FlagSeverity.INFO,
        )

    # --- Chapter VI-A deductions: take from exactly ONE Form16 to avoid double-counting ---
    forms_with_deductions = [f for f in form16_documents if f.deductions.aggregate_chapter_via_11 is not None]
    if len(forms_with_deductions) == 1:
        data.resolved_chapter_via_deductions = forms_with_deductions[0].deductions
    elif len(forms_with_deductions) > 1:
        data.resolved_chapter_via_deductions = forms_with_deductions[0].deductions
        data.add_flag(
            "reconciliation", "deductions",
            f"{len(forms_with_deductions)} Form16 documents each report Chapter VI-A deductions. Only the "
            f"first was used to avoid double-counting -- verify manually which employer's figures are correct.",
            FlagSeverity.WARNING,
        )

    # --- Other sources income (interest) ---
    interest_income = form26as.total_interest_income if form26as else None
    if interest_income is not None:
        data.other_sources_income_for_itr = interest_income
    else:
        fallback = [f.other_income_reported.other_sources_income_7b for f in form16_documents if f.other_income_reported.other_sources_income_7b is not None]
        if fallback:
            data.other_sources_income_for_itr = round(sum(fallback), 2)
            data.add_flag("reconciliation", "other_sources_income", "Using Form16-reported other-income figure(s); Form26AS Part A1 was empty or unavailable.", FlagSeverity.INFO)

    # --- TDS/TCS/advance tax credits ---
    if form26as:
        data.tds_salary_credit = form26as.total_tds_salary
        data.tds_other_credit = form26as.total_tds_interest
        data.tcs_credit = form26as.total_tcs
        data.advance_self_assessment_tax_paid = form26as.total_advance_self_assessment_tax

    # --- Cross-check: SUM of Form16-reported TDS across employers vs Form26AS Part A ---
    f16_tds_values = [f.tax_computation.tds_per_12baa_19 for f in form16_documents if f.tax_computation.tds_per_12baa_19 is not None]
    if f16_tds_values and data.tds_salary_credit is not None:
        f16_tds_total = round(sum(f16_tds_values), 2)
        data.form16_vs_26as_salary_tds_match = abs(f16_tds_total - data.tds_salary_credit) < 1.0
        if not data.form16_vs_26as_salary_tds_match:
            data.add_flag("reconciliation", "tds_salary", f"Sum of Form16-reported TDS ({f16_tds_total}) does not match Form26AS Part A total ({data.tds_salary_credit}).", FlagSeverity.ERROR)

    # --- Eligibility ---
    if form26as and form26as.has_property_transaction:
        data.has_property_capital_gains = True
        data.add_flag(
            "reconciliation", "eligibility",
            "Form26AS Part A2 shows a property transaction with TDS u/s 194IA, implying capital gains income. "
            "ITR-1 does not support capital gains from property -- ITR-2 (or higher) should be used instead.",
            FlagSeverity.ERROR,
        )

    # has_multiple_employers is intentionally NOT part of eligibility: ITR-1 restricts
    # based on income TYPE and amount, not employer count.
    data.itr1_eligible = not data.has_property_capital_gains

    return data


# ================================================================================
# SECTION 5 -- ITR-1 (SAHAJ) DRAFT SCHEMA, AY 2026-27
# ================================================================================

KNOWN_ITR1_VIA_SECTIONS = {
    "80DD": "sec_80dd", "80DDB": "sec_80ddb", "80EE": "sec_80ee",
    "80EEA": "sec_80eea", "80EEB": "sec_80eeb", "80GG": "sec_80gg",
    "80GGA": "sec_80gga", "80GGC": "sec_80ggc", "80TTB": "sec_80ttb", "80U": "sec_80u",
}


class ITR1ChapterVIADeductions(BaseModel):
    """
    ITR-1 Part C -- unlike Form16, the ITR ITSELF has a separate named field
    for every section (C1-C19-ish). Populated by map_chapter_via_to_itr1(),
    which routes Form16's named boxes + free-text 'other' rows here.
    """
    sec_80c_80ccc_80ccd1_combined: Optional[float] = None
    sec_80ccd_1b: Optional[float] = None
    sec_80ccd_2: Optional[float] = None
    sec_80cch: Optional[float] = None
    sec_80d: Optional[float] = None
    sec_80dd: Optional[float] = None
    sec_80ddb: Optional[float] = None
    sec_80e: Optional[float] = None
    sec_80ee: Optional[float] = None
    sec_80eea: Optional[float] = None
    sec_80eeb: Optional[float] = None
    sec_80g: Optional[float] = None
    sec_80gg: Optional[float] = None
    sec_80gga: Optional[float] = None
    sec_80ggc: Optional[float] = None
    sec_80tta: Optional[float] = None
    sec_80ttb: Optional[float] = None
    sec_80u: Optional[float] = None
    unmapped_entries: List[NamedDeductionEntry] = Field(default_factory=list, description="Section codes that could not be matched to a known ITR-1 field -- surfaced, never dropped")

    total_deductions_C1: Optional[float] = None
    total_deductions_C1_is_partial: bool = False

    @model_validator(mode="after")
    def _compute(self):
        named_fields = [
            self.sec_80c_80ccc_80ccd1_combined, self.sec_80ccd_1b, self.sec_80ccd_2, self.sec_80cch,
            self.sec_80d, self.sec_80dd, self.sec_80ddb, self.sec_80e, self.sec_80ee, self.sec_80eea,
            self.sec_80eeb, self.sec_80g, self.sec_80gg, self.sec_80gga, self.sec_80ggc,
            self.sec_80tta, self.sec_80ttb, self.sec_80u,
        ]
        total, partial = _sum_known(*named_fields)
        unmapped_amounts = [e.deductible_amount for e in self.unmapped_entries if e.deductible_amount is not None]
        if unmapped_amounts:
            total = round((total or 0.0) + sum(unmapped_amounts), 2)
        self.total_deductions_C1 = total
        self.total_deductions_C1_is_partial = partial or bool(self.unmapped_entries)
        return self


def map_chapter_via_to_itr1(form16_deductions: ChapterVIADeductions, flags: List[ValidationFlag]) -> ITR1ChapterVIADeductions:
    """
    Routes Form16's named boxes + free-text 'other' rows into ITR-1's fully-
    named C-fields. Anything that can't be matched to a known section code is
    preserved in `unmapped_entries` and flagged -- never dropped or guessed.
    """
    values: dict = {
        "sec_80c_80ccc_80ccd1_combined": form16_deductions.sec_80c_80ccc_80ccd1_combined,
        "sec_80ccd_1b": form16_deductions.sec_80ccd_1b,
        "sec_80ccd_2": form16_deductions.sec_80ccd_2,
        "sec_80cch": _sum_known(form16_deductions.sec_80cch_employee, form16_deductions.sec_80cch_govt)[0],
        "sec_80d": form16_deductions.sec_80d,
        "sec_80e": form16_deductions.sec_80e,
        "sec_80g": form16_deductions.sec_80g,
        "sec_80tta": form16_deductions.sec_80tta,
    }
    unmapped: List[NamedDeductionEntry] = []

    for entry in form16_deductions.other_via_entries:
        code = _normalize_section_code(entry.section)
        target_attr = KNOWN_ITR1_VIA_SECTIONS.get(code)
        if target_attr:
            values[target_attr], _ = _sum_known(values.get(target_attr), entry.deductible_amount)
        else:
            unmapped.append(entry)
            flags.append(ValidationFlag(
                stage="itr_mapping", field="part_c.deductions.unmapped_entries",
                issue=f"Form16 listed a Chapter VI-A deduction under an unrecognized section code "
                      f"('{entry.section}', amount {entry.deductible_amount}). Preserved but not auto-mapped "
                      f"to an ITR-1 field -- needs manual review.",
                severity=FlagSeverity.WARNING,
            ))

    return ITR1ChapterVIADeductions(**values, unmapped_entries=unmapped)


class ITR1PartA_GeneralInfo(BaseModel):
    pan: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    aadhaar_number: Optional[str] = None
    primary_mobile: Optional[str] = None
    primary_email: Optional[str] = None
    address_line: Optional[str] = None
    town_city: Optional[str] = None
    state: Optional[str] = None
    pin_code: Optional[str] = None
    filed_under_section: Optional[str] = None
    nature_of_employment: Optional[str] = None
    opting_out_115bac: Optional[YesNo] = None


class ITR1PartB_GrossTotalIncome(BaseModel):
    salary_gross_B1: Optional[float] = None
    house_property_income_B2: Optional[float] = Field(default=None, description="NOT derivable from Form16/Form26AS -- requires user input")
    other_sources_income_B3: Optional[float] = None

    gross_total_income_B4: Optional[float] = None
    gross_total_income_B4_is_partial: bool = False


class ITR1PartC_DeductionsAndTotalIncome(BaseModel):
    deductions: ITR1ChapterVIADeductions = Field(default_factory=ITR1ChapterVIADeductions)
    total_deductions_C1: Optional[float] = None
    total_income_C2: Optional[float] = None


class ITR1PartD_TaxComputation(BaseModel):
    """Shape only -- see module docstring point 5. Not auto-populated by map_to_itr1()."""
    tax_payable_on_total_income_D1: Optional[float] = None
    rebate_87a_D2: Optional[float] = None
    tax_after_rebate_D3: Optional[float] = None
    health_education_cess_D4: Optional[float] = None
    total_tax_and_cess_D5: Optional[float] = None
    relief_89_D6: Optional[float] = None
    interest_234a_D7: Optional[float] = None
    interest_234b_D8: Optional[float] = None
    interest_234c_D9: Optional[float] = None
    fee_234f_D10: Optional[float] = None
    total_tax_fee_interest_D11: Optional[float] = None
    total_taxes_paid_D12: Optional[float] = None
    amount_payable_D13: Optional[float] = None
    refund_D14: Optional[float] = None


class ScheduleITEntry(BaseModel):
    """Advance Tax / Self-Assessment Tax, mapped from Form26AS Part C."""
    bsr_code: Optional[str] = None
    date_of_deposit: Optional[str] = None
    challan_serial_no: Optional[str] = None
    tax_paid: Optional[float] = None


class ScheduleTDSEntry(BaseModel):
    """TDS/TCS as per Form16/Form26AS, mapped for ITR-1's Schedule-TDS."""
    tan_or_pan: Optional[str] = None
    deductor_name: Optional[str] = None
    section: Optional[str] = None
    gross_payment: Optional[float] = None
    tax_deducted: Optional[float] = None
    tds_claimed_this_year: Optional[float] = None


class ITR1Schema(BaseModel):
    """
    Draft ITR-1 (SAHAJ), AY 2026-27. A DRAFT for user review only -- never
    final or legally verified. Any field left None means the system could not
    confidently populate it; it must be surfaced for manual entry/
    verification, never silently defaulted.
    """
    part_a: ITR1PartA_GeneralInfo = Field(default_factory=ITR1PartA_GeneralInfo)
    part_b: ITR1PartB_GrossTotalIncome = Field(default_factory=ITR1PartB_GrossTotalIncome)
    part_c: ITR1PartC_DeductionsAndTotalIncome = Field(default_factory=ITR1PartC_DeductionsAndTotalIncome)
    part_d: ITR1PartD_TaxComputation = Field(default_factory=ITR1PartD_TaxComputation)
    bank_accounts: List[BankAccount] = Field(default_factory=list)
    schedule_it: List[ScheduleITEntry] = Field(default_factory=list)
    schedule_tds: List[ScheduleTDSEntry] = Field(default_factory=list)

    is_draft: bool = True
    is_itr1_eligible: Optional[bool] = None
    flags: List[ValidationFlag] = Field(default_factory=list)


def map_to_itr1(reconciled: ReconciledTaxData, user_input: Optional[UserProvidedInfo] = None) -> ITR1Schema:
    """
    Populates a draft ITR-1 from reconciled document data, merged with
    optional user-supplied profile info that Form16/Form26AS cannot provide.

    OWNERSHIP NOTE: the project's original Team Responsibilities doc lists
    ITR Field Mapping and Draft ITR Generation as part of the document/ITR
    pipeline owner's stages. If sprint planning has since assigned these
    stages to a different team member, that is a real scope change worth
    confirming across the whole team before code comments/ownership are
    rewritten -- this function takes no position on who owns it, only on
    what it does.
    """
    itr = ITR1Schema()
    itr.is_itr1_eligible = reconciled.itr1_eligible
    itr.flags = list(reconciled.flags)

    form16_documents = reconciled.form16_documents
    form26as = reconciled.form26as

    # --- Part A: General Info ---
    itr.part_a.pan = reconciled.resolved_pan
    if form16_documents:
        itr.part_a.opting_out_115bac = form16_documents[-1].opting_out_115bac  # heuristic: last-listed employer

    if user_input:
        itr.part_a.first_name = user_input.first_name
        itr.part_a.middle_name = user_input.middle_name
        itr.part_a.last_name = user_input.last_name
        itr.part_a.date_of_birth = user_input.date_of_birth
        itr.part_a.aadhaar_number = user_input.aadhaar_number
        itr.part_a.primary_mobile = user_input.primary_mobile
        itr.part_a.primary_email = user_input.primary_email
        itr.part_a.address_line = user_input.address_line
        itr.part_a.town_city = user_input.town_city
        itr.part_a.state = user_input.state
        itr.part_a.pin_code = user_input.pin_code
        itr.part_a.filed_under_section = user_input.filed_under_section
        itr.part_a.nature_of_employment = user_input.nature_of_employment
        if user_input.opting_out_115bac_confirmed is not None:
            itr.part_a.opting_out_115bac = user_input.opting_out_115bac_confirmed
        itr.bank_accounts = user_input.bank_accounts
    else:
        itr.flags.append(ValidationFlag(
            stage="itr_mapping", field="part_a",
            issue="No user-provided profile data supplied. Name, DOB, Aadhaar, contact/address details, "
                  "filing section, and bank accounts are not present in Form16/Form26AS and must be "
                  "collected separately.",
            severity=FlagSeverity.WARNING,
        ))

    if itr.part_a.pan is None:
        itr.flags.append(ValidationFlag(
            stage="itr_mapping", field="part_a.pan",
            issue="PAN could not be resolved from source documents; user must enter it manually.",
            severity=FlagSeverity.ERROR,
        ))

    # --- Part B: Gross Total Income ---
    itr.part_b.salary_gross_B1 = reconciled.salary_income_for_itr
    itr.part_b.other_sources_income_B3 = reconciled.other_sources_income_for_itr
    itr.part_b.house_property_income_B2 = None  # never invent 0 -- no source document covers this
    itr.flags.append(ValidationFlag(
        stage="itr_mapping", field="part_b.house_property_income_B2",
        issue="House property income cannot be derived from Form16/Form26AS. Left unset; requires "
              "user-supplied house property details (see UserProvidedInfo.house_properties) before this "
              "can be treated as zero.",
        severity=FlagSeverity.INFO,
    ))

    b_components = [itr.part_b.salary_gross_B1, itr.part_b.other_sources_income_B3, itr.part_b.house_property_income_B2]
    known = [c for c in b_components if c is not None]
    if known:
        itr.part_b.gross_total_income_B4 = round(sum(known), 2)
    itr.part_b.gross_total_income_B4_is_partial = len(known) < len(b_components)

    if itr.part_b.salary_gross_B1 is None:
        itr.flags.append(ValidationFlag(
            stage="itr_mapping", field="part_b.salary_gross_B1",
            issue="Salary income could not be mapped -- Form16 extraction was incomplete.",
            severity=FlagSeverity.ERROR,
        ))

    # --- Part C: Deductions ---
    if reconciled.resolved_chapter_via_deductions is not None:
        itr.part_c.deductions = map_chapter_via_to_itr1(reconciled.resolved_chapter_via_deductions, itr.flags)
        itr.part_c.total_deductions_C1 = itr.part_c.deductions.total_deductions_C1
        if itr.part_b.gross_total_income_B4 is not None and itr.part_c.total_deductions_C1 is not None:
            itr.part_c.total_income_C2 = round(itr.part_b.gross_total_income_B4 - itr.part_c.total_deductions_C1, 2)

    # --- Part D: intentionally NOT computed here ---
    itr.flags.append(ValidationFlag(
        stage="itr_mapping", field="part_d",
        issue="Part D tax computation was not auto-filled. It cannot copy Form16's employer-computed figures "
              "(those assume salary-only income); it must be recomputed from part_c.total_income_C2 using a "
              "separate, currently-valid slab-rate module.",
        severity=FlagSeverity.INFO,
    ))

    # --- Schedule IT / Schedule TDS ---
    if form26as:
        for entry in form26as.part_c_advance_tax:
            itr.schedule_it.append(ScheduleITEntry(
                bsr_code=entry.bsr_code, date_of_deposit=entry.date_of_deposit,
                challan_serial_no=entry.challan_serial_no, tax_paid=entry.tax_amount,
            ))
        for entry in form26as.part_a_tds_salary:
            itr.schedule_tds.append(ScheduleTDSEntry(
                tan_or_pan=entry.deductor_tan, deductor_name=entry.deductor_name, section="192",
                gross_payment=entry.total_amount_paid, tax_deducted=entry.total_tax_deducted,
                tds_claimed_this_year=entry.total_tax_deducted,
            ))
        for entry in form26as.part_a1_tds_interest:
            itr.schedule_tds.append(ScheduleTDSEntry(
                tan_or_pan=entry.banking_entity_tan, deductor_name=entry.financial_institution_name, section="194A",
                gross_payment=entry.total_interest_paid, tax_deducted=entry.total_tax_deducted,
                tds_claimed_this_year=entry.total_tax_deducted,
            ))

    return itr


# ================================================================================
# DEMO / SELF-TEST
# ================================================================================

if __name__ == "__main__":
    import json

    def _print_result(label: str, itr: ITR1Schema) -> None:
        print(f"\n{'=' * 80}\n{label}\n{'=' * 80}")
        print("ITR-1 eligible?", itr.is_itr1_eligible)
        print("\nFlags:")
        for f in itr.flags:
            print(f"  [{f.severity.value.upper()}] ({f.stage}) {f.field}: {f.issue}")
        print("\nPart B:", json.dumps(itr.part_b.model_dump(), indent=2))
        print("\nPart C deductions:", json.dumps(itr.part_c.deductions.model_dump(), indent=2))

    # -------------------------------------------------------------------
    # DEMO 1: single employer, with an "other Chapter VI-A" row that IS
    # recognized (80TTB) and one that ISN'T (fixes Problem 1), plus a
    # property transaction (still correctly ineligible) and user_input
    # (fixes Problem 3).
    # -------------------------------------------------------------------
    form16_single = Form16Schema(
        details=EmployeeEmployerDetails(employee_pan="AAAPL1234C", employer_tan="MUMB12345A", assessment_year="2026-27"),
        opting_out_115bac=YesNo.NO,
        salary_components=SalaryIncome(salary_17_1=1200000.0, perquisites_17_2=0.0, profit_in_lieu_17_3=0.0, salary_from_other_employers_1e=0.0),
        exemptions=Section10Exemptions(hra_10_13a=120000.0),
        section16_deductions=Section16Deductions(standard_deduction_16_ia=50000.0),
        deductions=ChapterVIADeductions(
            sec_80c_80ccc_80ccd1_combined=150000.0,
            sec_80d=25000.0,
            other_via_entries=[
                NamedDeductionEntry(section="80TTB", gross_amount=10000.0, deductible_amount=10000.0),  # recognized
                NamedDeductionEntry(section="80XYZ", gross_amount=2000.0, deductible_amount=2000.0),     # NOT recognized
            ],
        ),
        tax_computation=TaxComputation(tds_per_12baa_19=95000.0),
    )

    form26as_single = Form26ASSchema(
        pan="AAAPL1234C",
        assessment_year="2026-27",
        part_a_tds_salary=[TDSSalaryEntry(deductor_tan="MUMB12345A", deductor_name="Sample Employer Pvt Ltd", total_amount_paid=1200000.0, total_tax_deducted=95000.0, total_tax_deposited=95000.0)],
        part_a1_tds_interest=[TDSInterestEntry(banking_entity_tan="DELH98765B", financial_institution_name="Sample Bank", total_interest_paid=45000.0, total_tax_deducted=4500.0, total_tax_deposited=4500.0)],
        part_a2_tds_property=[TDSPropertyEntry(buyer_pan="XYZPQ9999M", buyer_name="Sample Buyer", total_transaction_value=6500000.0, total_tax_deducted=65000.0)],
        part_c_advance_tax=[AdvanceTaxEntry(bsr_code="0020124", date_of_deposit="15-09-2025", challan_serial_no="04321", tax_amount=30000.0)],
    )

    user_info = UserProvidedInfo(
        first_name="Test", last_name="User", date_of_birth="01/01/1990",
        primary_mobile="9999999999", primary_email="test@example.com",
        filed_under_section="139(1)", nature_of_employment="Others",
        bank_accounts=[BankAccount(ifsc_code="SBIN0001234", bank_name="State Bank of India", account_number="000111222333", selected_for_refund=True)],
    )

    reconciled_1 = reconcile_tax_data([form16_single], form26as_single)
    itr_1 = map_to_itr1(reconciled_1, user_input=user_info)
    _print_result("DEMO 1: single employer (tests Problem 1 + Problem 3 fixes)", itr_1)
    assert itr_1.part_c.deductions.sec_80ttb == 10000.0, "80TTB should be routed to its named field"
    assert len(itr_1.part_c.deductions.unmapped_entries) == 1, "unrecognized code should be preserved, not dropped"
    assert itr_1.is_itr1_eligible is False, "property transaction should still correctly block ITR-1 eligibility"

    # -------------------------------------------------------------------
    # DEMO 2: TWO employers (job change mid-year), NO property transaction.
    # Fixes Problem 2: has_multiple_employers is actually computed, salary
    # is summed across both, and multiple-employers-with-deductions
    # correctly triggers the double-counting warning -- but does NOT block
    # ITR-1 eligibility (that was the bug in the old formula).
    # -------------------------------------------------------------------
    form16_job1 = Form16Schema(
        details=EmployeeEmployerDetails(employee_pan="AAAPL1234C", employer_tan="MUMB11111A", assessment_year="2026-27", period_from="01-04-2025", period_to="30-09-2025"),
        salary_components=SalaryIncome(salary_17_1=500000.0, perquisites_17_2=0.0, profit_in_lieu_17_3=0.0, salary_from_other_employers_1e=0.0),
        exemptions=Section10Exemptions(hra_10_13a=50000.0),
        section16_deductions=Section16Deductions(standard_deduction_16_ia=25000.0),
        deductions=ChapterVIADeductions(sec_80c_80ccc_80ccd1_combined=50000.0),
        tax_computation=TaxComputation(tds_per_12baa_19=30000.0),
    )
    form16_job2 = Form16Schema(
        details=EmployeeEmployerDetails(employee_pan="AAAPL1234C", employer_tan="MUMB22222B", assessment_year="2026-27", period_from="01-10-2025", period_to="31-03-2026"),
        salary_components=SalaryIncome(salary_17_1=700000.0, perquisites_17_2=0.0, profit_in_lieu_17_3=0.0, salary_from_other_employers_1e=500000.0),
        exemptions=Section10Exemptions(hra_10_13a=70000.0),
        section16_deductions=Section16Deductions(standard_deduction_16_ia=25000.0),
        deductions=ChapterVIADeductions(sec_80c_80ccc_80ccd1_combined=100000.0),  # also reports deductions -> triggers warning
        tax_computation=TaxComputation(tds_per_12baa_19=45000.0),
    )
    form26as_multi = Form26ASSchema(
        pan="AAAPL1234C",
        assessment_year="2026-27",
        part_a_tds_salary=[
            TDSSalaryEntry(deductor_tan="MUMB11111A", deductor_name="Employer One", total_amount_paid=500000.0, total_tax_deducted=30000.0, total_tax_deposited=30000.0),
            TDSSalaryEntry(deductor_tan="MUMB22222B", deductor_name="Employer Two", total_amount_paid=700000.0, total_tax_deducted=45000.0, total_tax_deposited=45000.0),
        ],
    )

    reconciled_2 = reconcile_tax_data([form16_job1, form16_job2], form26as_multi)
    itr_2 = map_to_itr1(reconciled_2, user_input=None)
    _print_result("DEMO 2: two employers, no property transaction (tests Problem 2 fix)", itr_2)
    assert reconciled_2.has_multiple_employers is True, "must detect multiple employers"
    assert itr_2.is_itr1_eligible is True, "multiple employers alone must NOT block ITR-1 eligibility"

    print("\nAll assertions passed.")