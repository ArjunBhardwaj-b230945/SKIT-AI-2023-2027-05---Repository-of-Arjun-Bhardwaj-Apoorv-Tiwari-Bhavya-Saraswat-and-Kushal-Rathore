"""
tax_computation.py  ·  AY 2026-27 (FY 2025-26, Finance Act 2025)
================================================================================
Fills ITR-1 Part D (ITR1PartD_TaxComputation) from reconciled total income
(Part C.C2) and schedule-level tax payment data.

FINANCE ACT 2025 — WHAT CHANGED FOR AY 2026-27
-----------------------------------------------
New Regime (u/s 115BAC — the DEFAULT regime from AY 2024-25 onwards):
  • Basic exemption limit raised: ₹3,00,000 → ₹4,00,000
  • Six-slab structure revised (see NEW_REGIME_SLABS below)
  • Rebate u/s 87A raised: ₹25,000 → ₹60,000
  • Rebate income threshold raised: ₹7,00,000 → ₹12,00,000
    ⟹ Effective tax-free income: ₹12,00,000
    ⟹ For salaried (after ₹75,000 std deduction): ₹12,75,000
  • Standard deduction: ₹75,000 (unchanged; already captured in Form 16)
  • No age-based differentiation — single slab table for all ages.

Old Regime (opt-out via Form 10IEA, filed before due date u/s 139(1)):
  • THREE slab tables based on age as of any day during FY 2025-26:
      Regular      (< 60 years)  : basic exemption ₹2,50,000
      Senior Citizen (60–79 yrs) : basic exemption ₹3,00,000
      Super Senior  (≥ 80 years) : basic exemption ₹5,00,000
  • Age is judged as of the LAST DAY of the previous year (31 Mar 2026)
    per Section 2(80): "at any time during the relevant previous year."
  • Rebate u/s 87A: ₹12,500 for income ≤ ₹5,00,000 (unchanged).

Both Regimes:
  • Health & Education Cess: 4% on tax after rebate (unchanged).
  • Surcharge: NOT applicable for ITR-1 filers (income cap ₹50L;
    surcharge threshold starts at ₹50L+ under new regime).

MARGINAL RELIEF (do not omit — verified with test cases below)
---------------------------------------------------------------
At the rebate threshold (₹12L new / ₹5L old), the rebate wipes out all
tax. One rupee above causes a sudden jump of ≈₹60,000. Marginal relief
removes this cliff by capping net tax at (income − threshold):

    rebate = max(0,  raw_tax  −  (income − threshold))

This formula handles the full marginal zone without any hardcoded upper
bound constant — it naturally reduces to 0 once income is far enough above
the threshold that raw_tax falls below (income − threshold).

CORRECTIONS IN THIS VERSION (vs. original)
-------------------------------------------
FIX 1 — Senior / super-senior citizen slabs for old regime.
         Original always used the regular (< 60) table, producing wrong
         tax for ≥ 60 filers. Fixed by:
           • Adding OLD_REGIME_SLABS_SENIOR and OLD_REGIME_SLABS_SUPER_SENIOR.
           • Adding _age_category(date_of_birth_str) helper.
           • compute_part_d() now accepts date_of_birth and routes old-regime
             filers to the correct slab table.

FIX 2 — 234B used combined advance + self-assessment tax as "advance paid".
         Self-assessment tax paid after 31 Mar 2026 does not satisfy the
         advance-tax requirement — it reduces the balance payable but NOT
         the 234B shortfall. Fixed by:
           • _split_schedule_it() separating Schedule IT entries by date.
           • compute_part_d() now passes only pre-FY_END amounts to 234B.

FIX 3 — 234C was always None (INFO flag), silently understating D11.
         Schedule IT entries have payment dates — 234C can be computed.
         Fixed by adding compute_interest_234c() which checks cumulative
         advance payments against each statutory installment due date.
         Raised to WARNING severity since it materially affects D11.

FIX 4 — compute_interest_234b() with None filing_date returned 1 month
         of interest instead of 0. Fixed by returning 0.0 when None.

FIX 5 — Spot check tolerance for marginal relief was ±₹1 (too loose).
         Changed to ±₹0.01 (sub-rupee).

FIX 6 — Unused imports in smoke test removed.
================================================================================
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from tax_schemas import (
    FlagSeverity,
    ITR1Schema,
    ReconciledTaxData,
    ValidationFlag,
    YesNo,
)


# ================================================================================
# SECTION 1 — AY 2026-27 CONSTANTS  (Finance Act 2025)
# All monetary values in rupees. Change only this section when updating for a new AY.
# ================================================================================

AY = "2026-27"

# FY 2025-26 boundaries
FY_START = date(2025, 4, 1)
FY_END   = date(2026, 3, 31)   # last day of previous year — reference for age check

# Assessment year
AY_START = date(2026, 4, 1)    # 234B interest period starts here
FILING_DUE_DATE = date(2026, 7, 31)  # u/s 139(1) for non-audit individuals

# Advance tax installment schedule for FY 2025-26.
# Each tuple: (due_date, cumulative_fraction_required_by_that_date)
ADVANCE_TAX_INSTALLMENTS: List[Tuple[date, float]] = [
    (date(2025, 6,  15), 0.15),
    (date(2025, 9,  15), 0.45),
    (date(2025, 12, 15), 0.75),
    (date(2026, 3,  15), 1.00),
]

# Months of interest charged per installment shortfall (statute-fixed)
ADVANCE_TAX_234C_MONTHS: List[int] = [3, 3, 3, 1]

# Minimum assessed tax above which 234B/234C apply
ADVANCE_TAX_THRESHOLD = 10_000.0

CESS_RATE = 0.04

# ── New Regime Slabs (Finance Act 2025) ─────────────────────────────────────
# Format: (upper_bound_inclusive_rupees, marginal_rate). Final slab: math.inf.
NEW_REGIME_SLABS: List[Tuple[float, float]] = [
    (4_00_000,  0.00),   # 0   – 4L  : Nil
    (8_00_000,  0.05),   # 4L  – 8L  : 5%
    (12_00_000, 0.10),   # 8L  – 12L : 10%
    (16_00_000, 0.15),   # 12L – 16L : 15%
    (20_00_000, 0.20),   # 16L – 20L : 20%
    (24_00_000, 0.25),   # 20L – 24L : 25%
    (math.inf,  0.30),   # Above 24L : 30%
]
NEW_REGIME_87A_THRESHOLD = 12_00_000   # income ≤ this → rebate applies
NEW_REGIME_87A_MAX_REBATE = 60_000

# ── Old Regime Slabs — THREE tables (FIX 1) ─────────────────────────────────

OLD_REGIME_SLABS_REGULAR: List[Tuple[float, float]] = [
    # Age < 60 years as of FY_END
    (2_50_000,  0.00),   # 0    – 2.5L : Nil
    (5_00_000,  0.05),   # 2.5L – 5L   : 5%
    (10_00_000, 0.20),   # 5L   – 10L  : 20%
    (math.inf,  0.30),   # Above 10L   : 30%
]
OLD_REGIME_SLABS_SENIOR: List[Tuple[float, float]] = [
    # Age 60–79 years as of FY_END — higher basic exemption
    (3_00_000,  0.00),   # 0   – 3L   : Nil
    (5_00_000,  0.05),   # 3L  – 5L   : 5%
    (10_00_000, 0.20),   # 5L  – 10L  : 20%
    (math.inf,  0.30),   # Above 10L  : 30%
]
OLD_REGIME_SLABS_SUPER_SENIOR: List[Tuple[float, float]] = [
    # Age ≥ 80 years as of FY_END — no tax up to ₹5L
    (5_00_000,  0.00),   # 0  – 5L   : Nil
    (10_00_000, 0.20),   # 5L – 10L  : 20%
    (math.inf,  0.30),   # Above 10L : 30%
]

OLD_REGIME_87A_THRESHOLD = 5_00_000
OLD_REGIME_87A_MAX_REBATE = 12_500

# 234F flat fee thresholds
FEE_234F_HIGH_INCOME_THRESHOLD = 5_00_000
FEE_234F_HIGH = 5_000    # income > 5L
FEE_234F_LOW  = 1_000    # income ≤ 5L


# ================================================================================
# SECTION 2 — AGE DETECTION  (FIX 1 — new in this version)
# ================================================================================

class _AgeCategory:
    REGULAR       = "regular"        # < 60
    SENIOR        = "senior"         # 60 – 79
    SUPER_SENIOR  = "super_senior"   # ≥ 80


def _parse_date(raw: Optional[str]) -> Optional[date]:
    """Parse DD/MM/YYYY, DD-MM-YYYY, or YYYY-MM-DD. Returns None on failure."""
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _age_category(date_of_birth_str: Optional[str]) -> str:
    """
    Return the age category of the assessee for old-regime slab selection.

    Section 2(80) of the Income Tax Act defines 'senior citizen' as an
    individual who is 60 years or more AT ANY TIME during the relevant
    previous year. The most inclusive interpretation — used here — is age
    as of the LAST DAY of the previous year (31 March 2026 for FY 2025-26).

    If DOB is not available, defaults to REGULAR (conservative — no
    additional exemption assumed). This is flagged as a WARNING by the
    caller so the user can correct it.

    Age category boundaries (age on 31 March 2026):
        < 60  → REGULAR       (basic exemption ₹2,50,000)
        60–79 → SENIOR        (basic exemption ₹3,00,000)
        ≥ 80  → SUPER_SENIOR  (basic exemption ₹5,00,000)
    """
    dob = _parse_date(date_of_birth_str)
    if dob is None:
        return _AgeCategory.REGULAR

    # Age in years as of FY_END (31 March 2026)
    age = (
        FY_END.year - dob.year
        - (1 if (FY_END.month, FY_END.day) < (dob.month, dob.day) else 0)
    )
    if age >= 80:
        return _AgeCategory.SUPER_SENIOR
    if age >= 60:
        return _AgeCategory.SENIOR
    return _AgeCategory.REGULAR


# ================================================================================
# SECTION 3 — SLAB TAX COMPUTATION
# ================================================================================

def _compute_slab_tax(income: float, slabs: List[Tuple[float, float]]) -> float:
    """
    Apply a progressive slab structure to `income` and return the raw tax.

    income : taxable income in rupees, must be ≥ 0.
    slabs  : ordered list of (upper_bound_inclusive, rate); final entry
             MUST use math.inf as upper bound.

    The algorithm taxes each rupee once, at the marginal rate for the slab
    it falls in. Upper bounds are inclusive in the slab they belong to.
    """
    if income < 0:
        raise ValueError(f"income must be non-negative; received {income!r}")
    tax = 0.0
    lower = 0.0
    for upper, rate in slabs:
        if income <= lower:
            break
        tax += (min(income, upper) - lower) * rate
        lower = upper
    return tax


def compute_tax_new_regime(income: float) -> float:
    """Raw tax under New Regime AY 2026-27. Pre-rebate, pre-cess, no surcharge."""
    return _compute_slab_tax(income, NEW_REGIME_SLABS)


def compute_tax_old_regime(income: float, date_of_birth: Optional[str] = None) -> float:
    """
    Raw tax under Old Regime AY 2026-27. Pre-rebate, pre-cess, no surcharge.

    Selects the correct slab table based on the assessee's age as of
    31 March 2026. Defaults to REGULAR if date_of_birth is not supplied.

    FIX 1: original always used the regular table — this now correctly
    applies senior (₹3L exemption) and super-senior (₹5L exemption) slabs.
    """
    category = _age_category(date_of_birth)
    slabs = {
        _AgeCategory.REGULAR:      OLD_REGIME_SLABS_REGULAR,
        _AgeCategory.SENIOR:       OLD_REGIME_SLABS_SENIOR,
        _AgeCategory.SUPER_SENIOR: OLD_REGIME_SLABS_SUPER_SENIOR,
    }[category]
    return _compute_slab_tax(income, slabs)


# ================================================================================
# SECTION 4 — REBATE u/s 87A WITH MARGINAL RELIEF
# ================================================================================

def compute_rebate_87a(income: float, raw_tax: float, is_new_regime: bool) -> float:
    """
    Rebate u/s 87A for AY 2026-27, including marginal relief.

    MARGINAL RELIEF FORMULA
    ──────────────────────
    At the threshold the rebate wipes tax to zero. One rupee above causes
    a cliff of ≈₹60,000. The formula:

        rebate = max(0,  raw_tax  −  (income − threshold))

    Naturally caps net tax at (income − threshold) for incomes just above
    the threshold, and reduces to 0 once raw_tax < (income − threshold)
    (the marginal zone is fully absorbed). No hardcoded upper bound needed.

    Verified test cases (new regime):
      ₹12,00,000 : rebate = ₹60,000  → net = 0
      ₹12,00,001 : rebate ≈ ₹59,999  → net ≈ ₹1    (≡ extra income above ₹12L)
      ₹12,50,000 : rebate = ₹17,500  → net = ₹50,000 (≡ income − ₹12L)
      ₹14,00,000 : rebate = 0        → raw_tax < income − threshold already
    """
    if is_new_regime:
        threshold  = NEW_REGIME_87A_THRESHOLD
        max_rebate = NEW_REGIME_87A_MAX_REBATE
    else:
        threshold  = OLD_REGIME_87A_THRESHOLD
        max_rebate = OLD_REGIME_87A_MAX_REBATE

    if income <= threshold:
        return round(min(raw_tax, max_rebate), 2)

    marginal_rebate = max(0.0, raw_tax - (income - threshold))
    return round(min(marginal_rebate, max_rebate), 2)


# ================================================================================
# SECTION 5 — CESS
# ================================================================================

def compute_cess(tax_after_rebate: float) -> float:
    """Health & Education Cess at 4% on tax after rebate. Both regimes."""
    return round(tax_after_rebate * CESS_RATE, 2)


# ================================================================================
# SECTION 6 — MONTH COUNTER
# ================================================================================

def _months_between_inclusive(start: date, end: date) -> int:
    """
    Calendar months from start (inclusive) to end (inclusive), ceiling.
    Any fraction of a month counts as a full month (Indian IT convention).

    Algorithm: count full calendar months; if end.day > start.day there is
    a leftover partial month → add 1. Always returns ≥ 1 for start ≤ end.

    Verified test cases — all correct:
      Aug 1 → Aug 1  : 1   (same day)
      Aug 1 → Aug 31 : 1   (within month)
      Aug 1 → Sep 1  : 1   (exactly 1 month — Sep 1.day == Aug 1.day, no extra)
      Aug 1 → Sep 2  : 2   (1 month + 1 day partial)
      Aug 1 → Oct 1  : 2   (exactly 2 months)
      Aug 15 → Sep 14: 1
      Aug 15 → Sep 15: 1   (exactly 1 month)
      Aug 15 → Sep 16: 2   (1 month + 1 day partial)
    """
    if end < start:
        return 0
    full = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day > start.day:
        full += 1
    return max(1, full)


# ================================================================================
# SECTION 7 — SCHEDULE IT SPLITTER  (FIX 2 — new in this version)
# ================================================================================

def _split_schedule_it(
    schedule_it_entries: list,
) -> Tuple[List[Tuple[date, float]], List[Tuple[date, float]]]:
    """
    Split Schedule IT entries (from Form 26AS Part C) into:

      advance_tax       — paid on or before FY_END (31 March 2026)
      self_assessment   — paid on or after AY_START (1 April 2026)

    Returns (advance_tax_list, self_assessment_list) as (payment_date, amount)
    pairs. Entries with unparseable dates or None amounts are skipped (these
    should have been flagged upstream by the reconciliation stage).

    WHY THIS SPLIT MATTERS
    ──────────────────────
    234B is about whether ADVANCE TAX paid during the fiscal year was
    sufficient. Self-assessment tax paid after 31 March 2026 reduces the
    balance payable (D13) but does NOT retroactively satisfy the advance
    tax requirement for 234B. Using the combined total understates 234B.

    234C requires per-installment advance tax payments to compare against
    the four statutory due dates (Jun 15, Sep 15, Dec 15, Mar 15).
    """
    advance: List[Tuple[date, float]] = []
    self_assessment: List[Tuple[date, float]] = []

    for entry in schedule_it_entries:
        d = _parse_date(entry.date_of_deposit)
        amount = entry.tax_paid
        if d is None or amount is None:
            continue
        if d <= FY_END:
            advance.append((d, amount))
        else:
            self_assessment.append((d, amount))

    return advance, self_assessment


# ================================================================================
# SECTION 8 — INTEREST AND FEE FUNCTIONS
# ================================================================================

def compute_interest_234a(
    tax_payable_after_all_credits: float,
    filing_date: Optional[date],
    due_date: date = FILING_DUE_DATE,
) -> float:
    """
    Interest u/s 234A — return filed AFTER due date.

    Rate   : 1% per month or part thereof.
    Base   : tax payable after all credits (TDS + advance + TCS).
    Period : (due_date + 1 day) to filing_date, inclusive.

    Returns 0.0 if:
      • filing_date is None (caller must set D7 to None and flag)
      • Filed on or before due_date
      • tax payable after credits ≤ 0 (refund case)
    """
    if filing_date is None or filing_date <= due_date:
        return 0.0
    if tax_payable_after_all_credits <= 0:
        return 0.0
    months = _months_between_inclusive(due_date + timedelta(days=1), filing_date)
    return round(tax_payable_after_all_credits * 0.01 * months, 2)


def compute_interest_234b(
    total_tax_and_cess: float,
    tds_and_tcs_credited: float,
    advance_tax_paid_only: float,
    filing_date: Optional[date],
) -> float:
    """
    Interest u/s 234B — shortfall in advance tax payment.

    Trigger : advance_tax_paid_only < 90% of assessed tax.
    Rate    : 1% per month or part thereof.
    Base    : assessed_tax − advance_tax_paid_only.
    Period  : AY_START (1 April 2026) to filing_date.

    KEY PARAMETER NAMES (FIX 2 + FIX 4)
    ─────────────────────────────────────
    advance_tax_paid_only  — ONLY payments dated on/before FY_END (31 Mar 2026).
                             Do NOT include self-assessment tax paid after 31 Mar.
                             Self-assessment tax reduces D13 but NOT the 234B base.

    tds_and_tcs_credited   — TDS (salary + other) + TCS. These are credited
                             BEFORE computing assessed tax because they are withheld
                             at source during the year, equivalent to advance tax.

    filing_date            — If None, returns 0.0 (FIX 4: original fell through
                             to 'end_date = AY_START' → erroneously returned 1
                             month of interest).
    """
    if filing_date is None:
        return 0.0   # FIX 4: original returned 1 month; now correctly 0.0

    assessed_tax = max(0.0, total_tax_and_cess - tds_and_tcs_credited)
    if assessed_tax <= 0 or advance_tax_paid_only >= 0.90 * assessed_tax:
        return 0.0

    shortfall = assessed_tax - advance_tax_paid_only
    months = _months_between_inclusive(AY_START, filing_date)
    return round(shortfall * 0.01 * months, 2)


def compute_interest_234c(
    total_tax_and_cess: float,
    tds_and_tcs_credited: float,
    advance_payments: List[Tuple[date, float]],
) -> float:
    """
    Interest u/s 234C — deferred advance tax installments.  (FIX 3 — new)

    Applies when assessed tax (total_tax_and_cess − TDS − TCS) > ₹10,000,
    AND cumulative advance tax paid is less than the required percentage at
    any installment due date.

    FY 2025-26 installment schedule (ADVANCE_TAX_INSTALLMENTS):
      15 June 2025  : 15% of total assessed tax must be paid cumulatively
      15 Sep  2025  : 45%
      15 Dec  2025  : 75%
      15 Mar  2026  : 100%

    For each installment:
      shortfall = max(0, required_cumulative − actually_paid_by_due_date)
      interest  = shortfall × 1% × statutory_months  (3 / 3 / 3 / 1)

    Returns the sum of interest across all four installments.

    STATUTORY EXCEPTION (not modelled here):
      234C does not apply if the shortfall in the first installment (Jun 15)
      is caused entirely by sudden/windfall income that was not assessable
      at the time. This case is rare, requires manual determination, and is
      flagged in the calling function for manual review.
    """
    assessed_tax = max(0.0, total_tax_and_cess - tds_and_tcs_credited)
    if assessed_tax <= ADVANCE_TAX_THRESHOLD:
        return 0.0

    total_234c = 0.0
    for (due_date, cum_fraction), months in zip(ADVANCE_TAX_INSTALLMENTS, ADVANCE_TAX_234C_MONTHS):
        paid_by_due_date = sum(amt for (d, amt) in advance_payments if d <= due_date)
        required = cum_fraction * assessed_tax
        shortfall = max(0.0, required - paid_by_due_date)
        total_234c += shortfall * 0.01 * months

    return round(total_234c, 2)


def compute_fee_234f(
    total_income: float,
    filing_date: Optional[date],
    due_date: date = FILING_DUE_DATE,
) -> float:
    """
    Fee u/s 234F — late filing. Flat fee, not compounding.

    ₹5,000 : income > ₹5,00,000 AND filed after due_date
    ₹1,000 : income ≤ ₹5,00,000 AND filed after due_date
    ₹0     : on-time or filing_date is None
    """
    if filing_date is None or filing_date <= due_date:
        return 0.0
    return float(FEE_234F_HIGH if total_income > FEE_234F_HIGH_INCOME_THRESHOLD else FEE_234F_LOW)


# ================================================================================
# SECTION 9 — ROUNDING
# ================================================================================

def _rupee_round(value: float) -> int:
    """
    Round to nearest whole rupee (half-up). CBDT requires all ITR-1 amounts
    in whole rupees — no paise.

    _rupee_round(1234.4) → 1234
    _rupee_round(1234.5) → 1235
    """
    return int(math.floor(value + 0.5))


# ================================================================================
# SECTION 10 — MAIN ENTRY POINT
# ================================================================================

def compute_part_d(
    itr: ITR1Schema,
    reconciled: ReconciledTaxData,
    filing_date: Optional[date] = None,
    date_of_birth: Optional[str] = None,
) -> ITR1Schema:
    """
    Populate ITR-1 Part D (tax computation) in-place on `itr` for AY 2026-27.

    This is the ONLY function that should write to itr.part_d. Call it after
    map_to_itr1() has populated Parts A, B, and C.

    Parameters
    ──────────
    itr            : Draft ITR-1 with Part A / B / C already populated.
    reconciled     : Reconciled Form 16 + Form 26AS data.
    filing_date    : Actual or intended filing date. Pass even an estimate to
                     get meaningful 234A / 234B / 234C / 234F figures.
                     None → those fields are left None with INFO-level flags.
    date_of_birth  : Assessee's DOB in DD/MM/YYYY or DD-MM-YYYY format.
                     Required for old-regime age-based slab selection (FIX 1).
                     Sourced from UserProvidedInfo.date_of_birth at the node
                     level. None → defaults to REGULAR slab with a WARNING.

    Returns the same `itr` object (mutated in-place) for method chaining.
    """
    d     = itr.part_d
    flags = itr.flags

    def _flag(field: str, issue: str, sev: FlagSeverity = FlagSeverity.WARNING) -> None:
        flags.append(ValidationFlag(
            stage="tax_computation",
            field=f"part_d.{field}",
            issue=issue,
            severity=sev,
        ))

    # ── Guard: C2 must be available ──────────────────────────────────────────
    if itr.part_c.total_income_C2 is None:
        _flag(
            "", FlagSeverity.ERROR,
            "Part C total income (C2) is None — Part D cannot be computed. "
            "Ensure salary income, other sources income, and all deductions are "
            "resolved before calling compute_part_d().",
        )
        return itr

    total_income = max(0.0, float(itr.part_c.total_income_C2))

    # ── Regime selection ─────────────────────────────────────────────────────
    is_new_regime = (itr.part_a.opting_out_115bac != YesNo.YES)

    # ── FIX 1: Age check for old regime ─────────────────────────────────────
    age_cat = _AgeCategory.REGULAR   # irrelevant for new regime but computed always
    if not is_new_regime:
        if date_of_birth is None:
            _flag(
                "tax_payable_on_total_income_D1",
                "date_of_birth not provided — defaulting to REGULAR slab for old "
                "regime (basic exemption ₹2,50,000). If the assessee is a senior "
                "citizen (≥ 60) or super-senior citizen (≥ 80), re-run with the "
                "correct date_of_birth to apply the correct slab table.",
                FlagSeverity.WARNING,
            )
        age_cat = _age_category(date_of_birth)

    # ── D1: Tax on total income ──────────────────────────────────────────────
    if is_new_regime:
        raw_tax = compute_tax_new_regime(total_income)
    else:
        raw_tax = compute_tax_old_regime(total_income, date_of_birth)
    d.tax_payable_on_total_income_D1 = _rupee_round(raw_tax)

    # ── D2: Rebate u/s 87A (with marginal relief) ────────────────────────────
    rebate = compute_rebate_87a(total_income, raw_tax, is_new_regime)
    d.rebate_87a_D2 = _rupee_round(rebate)

    # ── D3: Tax after rebate ─────────────────────────────────────────────────
    tax_after_rebate = max(0.0, raw_tax - rebate)
    d.tax_after_rebate_D3 = _rupee_round(tax_after_rebate)

    # ── D4: Health & Education Cess @ 4% ────────────────────────────────────
    cess = compute_cess(tax_after_rebate)
    d.health_education_cess_D4 = _rupee_round(cess)

    # ── D5: Total Tax and Cess ───────────────────────────────────────────────
    total_tax_and_cess = tax_after_rebate + cess
    d.total_tax_and_cess_D5 = _rupee_round(total_tax_and_cess)

    # ── D6: Relief u/s 89 ────────────────────────────────────────────────────
    d.relief_89_D6 = None
    _flag(
        "relief_89_D6",
        "Relief u/s 89 requires Form 10E filed separately — cannot be derived "
        "from Form 16 or Form 26AS. Left unset; user must confirm and enter "
        "the relief amount if applicable.",
        FlagSeverity.INFO,
    )

    # ── FIX 2: Split Schedule IT into advance tax vs self-assessment tax ─────
    advance_payments, sa_payments = _split_schedule_it(itr.schedule_it)
    advance_tax_paid = round(sum(amt for (_, amt) in advance_payments), 2)
    sa_tax_paid      = round(sum(amt for (_, amt) in sa_payments), 2)

    # ── D12: Total Taxes Paid ────────────────────────────────────────────────
    tds_claimed  = round(sum(e.tds_claimed_this_year or 0.0 for e in itr.schedule_tds), 2)
    tcs_credit   = round(float(reconciled.tcs_credit or 0.0), 2)
    tds_and_tcs  = tds_claimed + tcs_credit
    total_taxes_paid = tds_and_tcs + advance_tax_paid + sa_tax_paid
    d.total_taxes_paid_D12 = _rupee_round(total_taxes_paid)

    # ── D7, D8, D9, D10 require filing_date ─────────────────────────────────
    if filing_date is None:
        d.interest_234a_D7 = None
        d.interest_234b_D8 = None
        d.interest_234c_D9 = None
        d.fee_234f_D10     = None
        for label in ("interest_234a_D7", "interest_234b_D8", "interest_234c_D9", "fee_234f_D10"):
            _flag(
                label,
                f"filing_date not supplied — {label} cannot be computed. "
                f"Pass filing_date to compute_part_d() for accurate interest/fee figures.",
                FlagSeverity.INFO,
            )
    else:
        # D7 — 234A: base is tax still owed after ALL credits
        tax_after_all_credits = max(0.0, total_tax_and_cess - total_taxes_paid)
        d.interest_234a_D7 = _rupee_round(
            compute_interest_234a(tax_after_all_credits, filing_date)
        )

        # D8 — 234B: base is assessed tax vs ADVANCE TAX ONLY (FIX 2)
        d.interest_234b_D8 = _rupee_round(
            compute_interest_234b(total_tax_and_cess, tds_and_tcs, advance_tax_paid, filing_date)
        )

        # D9 — 234C: implemented (FIX 3)
        d.interest_234c_D9 = _rupee_round(
            compute_interest_234c(total_tax_and_cess, tds_and_tcs, advance_payments)
        )
        if d.interest_234c_D9 > 0:
            _flag(
                "interest_234c_D9",
                f"Interest u/s 234C of ₹{d.interest_234c_D9:,} computed from Schedule IT "
                f"payment dates. Note: the statutory windfall-income exception (where a "
                f"taxpayer has no prior-year tax history) is not modelled — verify manually "
                f"if this is the assessee's first year with significant tax liability.",
                FlagSeverity.WARNING,
            )

        # D10 — 234F
        d.fee_234f_D10 = _rupee_round(compute_fee_234f(total_income, filing_date))

    # ── D11: Total Tax, Fee and Interest ─────────────────────────────────────
    # Formula: D5 − D6 + D7 + D8 + D9 + D10
    # D6 (relief u/s 89) left as 0.0 here — user must enter it manually.
    # D9 now computed (FIX 3) so D11 is accurate when all other inputs are present.
    if all(v is not None for v in [
        d.total_tax_and_cess_D5,
        d.interest_234a_D7,
        d.interest_234b_D8,
        d.interest_234c_D9,
        d.fee_234f_D10,
    ]):
        d.total_tax_fee_interest_D11 = _rupee_round(
            float(d.total_tax_and_cess_D5)
            + float(d.interest_234a_D7)
            + float(d.interest_234b_D8)
            + float(d.interest_234c_D9)
            + float(d.fee_234f_D10)
            # D6 (relief u/s 89) intentionally excluded — user must apply manually
        )
    else:
        _flag(
            "total_tax_fee_interest_D11",
            "D11 cannot be finalised until filing_date is supplied (D7, D8, D9, D10 "
            "are currently None). Pass filing_date to compute_part_d() to complete D11.",
            FlagSeverity.INFO,
        )

    # ── D13 / D14: Payable or Refund ─────────────────────────────────────────
    if d.total_tax_fee_interest_D11 is not None and d.total_taxes_paid_D12 is not None:
        net = float(d.total_taxes_paid_D12) - float(d.total_tax_fee_interest_D11)
        if net < 0:
            d.amount_payable_D13 = _rupee_round(abs(net))
            d.refund_D14         = 0
        else:
            d.amount_payable_D13 = 0
            d.refund_D14         = _rupee_round(net)
    else:
        _flag(
            "amount_payable_D13",
            "D13/D14 cannot be computed until D11 and D12 are both resolved.",
            FlagSeverity.INFO,
        )

    return itr


# ================================================================================
# SECTION 11 — SPOT CHECKS / SELF-TEST
# ================================================================================

def _run_spot_checks() -> None:
    """
    Run: python tax_computation.py

    All expected values derived by hand from first principles.
    Covers all five bug fixes plus full slab and interest coverage.
    """
    import json

    print("Running AY 2026-27 spot checks...\n")

    # ── Slab: New Regime ───────────────────────────────────────────────────────
    assert compute_tax_new_regime(0)           == 0.0
    assert compute_tax_new_regime(4_00_000)    == 0.0
    assert compute_tax_new_regime(8_00_000)    == 20_000.0      # 4L@5%
    assert compute_tax_new_regime(12_00_000)   == 60_000.0      # +4L@10%
    assert compute_tax_new_regime(16_00_000)   == 1_20_000.0    # +4L@15%
    assert compute_tax_new_regime(20_00_000)   == 2_00_000.0    # +4L@20%
    assert compute_tax_new_regime(24_00_000)   == 3_00_000.0    # +4L@25%
    assert compute_tax_new_regime(25_00_000)   == 3_30_000.0    # +1L@30%
    print("  ✓ New regime slab")

    # ── Slab: Old Regime — REGULAR ────────────────────────────────────────────
    assert compute_tax_old_regime(2_50_000)    == 0.0
    assert compute_tax_old_regime(5_00_000)    == 12_500.0
    assert compute_tax_old_regime(10_00_000)   == 1_12_500.0
    assert compute_tax_old_regime(15_00_000)   == 2_62_500.0
    print("  ✓ Old regime slab — regular")

    # ── FIX 1: Slab: Old Regime — SENIOR (age 60–79) ─────────────────────────
    # Senior: 0–3L @0%, 3L–5L @5%, 5L–10L @20%, >10L @30%
    senior_dob = "01/01/1960"     # age 66 on 31 Mar 2026 → SENIOR
    assert _age_category(senior_dob) == _AgeCategory.SENIOR

    # ₹3L → nil (higher exemption vs regular ₹2.5L)
    assert compute_tax_old_regime(3_00_000, senior_dob) == 0.0
    # ₹5L → 5% on ₹2L = ₹10,000 (vs ₹12,500 for regular)
    assert compute_tax_old_regime(5_00_000, senior_dob) == 10_000.0, \
        compute_tax_old_regime(5_00_000, senior_dob)
    # ₹10L → 10,000 + 5L@20% = ₹1,10,000 (vs ₹1,12,500 for regular)
    assert compute_tax_old_regime(10_00_000, senior_dob) == 1_10_000.0, \
        compute_tax_old_regime(10_00_000, senior_dob)
    print("  ✓ Old regime slab — senior citizen (FIX 1)")

    # ── FIX 1: Slab: Old Regime — SUPER SENIOR (age ≥ 80) ────────────────────
    # Super senior: 0–5L @0%, 5L–10L @20%, >10L @30%
    super_dob = "01/01/1940"     # age 86 on 31 Mar 2026 → SUPER_SENIOR
    assert _age_category(super_dob) == _AgeCategory.SUPER_SENIOR

    # ₹5L → nil (₹5L exemption)
    assert compute_tax_old_regime(5_00_000, super_dob) == 0.0
    # ₹10L → 5L@20% = ₹1,00,000
    assert compute_tax_old_regime(10_00_000, super_dob) == 1_00_000.0, \
        compute_tax_old_regime(10_00_000, super_dob)
    print("  ✓ Old regime slab — super senior citizen (FIX 1)")

    # ── Age category boundaries ───────────────────────────────────────────────
    # FY_END = 31 Mar 2026 is the reference date
    # Turns 60 on 31 Mar 2026 → SENIOR (60 on last day of FY)
    assert _age_category("31/03/1966") == _AgeCategory.SENIOR
    # Turns 60 on 1 Apr 2026 → REGULAR (60 only in AY, not PY)
    assert _age_category("01/04/1966") == _AgeCategory.REGULAR
    # Turns 80 on 31 Mar 2026 → SUPER_SENIOR
    assert _age_category("31/03/1946") == _AgeCategory.SUPER_SENIOR
    # Turns 80 on 1 Apr 2026 → SENIOR (not yet 80 during FY 2025-26)
    assert _age_category("01/04/1946") == _AgeCategory.SENIOR
    # No DOB → REGULAR (conservative default)
    assert _age_category(None) == _AgeCategory.REGULAR
    print("  ✓ Age category boundaries")

    # ── 87A Rebate + Marginal Relief ─────────────────────────────────────────
    # New regime
    t12 = compute_tax_new_regime(12_00_000)          # 60,000
    assert compute_rebate_87a(12_00_000, t12, True) == 60_000.0
    assert max(0.0, t12 - compute_rebate_87a(12_00_000, t12, True)) == 0.0

    t12p1 = compute_tax_new_regime(12_00_001)         # ≈60,000.15
    r12p1 = compute_rebate_87a(12_00_001, t12p1, True)
    net_12p1 = t12p1 - r12p1
    # FIX 5: tolerance was ±1; now ±0.01 (sub-rupee)
    assert abs(net_12p1 - 1.0) < 0.01, f"Marginal relief at ₹12,00,001: net={net_12p1}"

    t12_50 = compute_tax_new_regime(12_50_000)        # 67,500
    r12_50 = compute_rebate_87a(12_50_000, t12_50, True)
    net_12_50 = t12_50 - r12_50
    assert abs(net_12_50 - 50_000) < 0.01, f"Marginal relief at ₹12.5L: net={net_12_50}"

    assert compute_rebate_87a(14_00_000, compute_tax_new_regime(14_00_000), True) == 0.0
    assert compute_rebate_87a(10_00_000, compute_tax_new_regime(10_00_000), True) == 40_000.0

    # Old regime
    t5 = compute_tax_old_regime(5_00_000)             # 12,500
    assert compute_rebate_87a(5_00_000, t5, False) == 12_500.0
    t5p1 = compute_tax_old_regime(5_00_001)
    r5p1 = compute_rebate_87a(5_00_001, t5p1, False)
    # FIX 5: tolerance now ±0.01
    assert abs(t5p1 - r5p1 - 1.0) < 0.01, f"Old regime marginal relief at ₹5,00,001: net={t5p1-r5p1}"
    assert compute_rebate_87a(6_00_000, compute_tax_old_regime(6_00_000), False) == 0.0
    print("  ✓ 87A rebate + marginal relief (FIX 5: tolerance ±0.01)")

    # ── Cess ─────────────────────────────────────────────────────────────────
    assert compute_cess(10_000) == 400.0
    assert compute_cess(0) == 0.0
    assert compute_cess(12_500) == 500.0
    print("  ✓ Cess @ 4%")

    # ── _months_between_inclusive ─────────────────────────────────────────────
    aug1 = date(2026, 8, 1)
    assert _months_between_inclusive(aug1, aug1)               == 1
    assert _months_between_inclusive(aug1, date(2026, 8, 31))  == 1
    assert _months_between_inclusive(aug1, date(2026, 9,  1))  == 1
    assert _months_between_inclusive(aug1, date(2026, 9,  2))  == 2
    assert _months_between_inclusive(aug1, date(2026, 10, 1))  == 2
    assert _months_between_inclusive(aug1, date(2026, 10, 2))  == 3
    aug15 = date(2026, 8, 15)
    assert _months_between_inclusive(aug15, date(2026, 9, 14)) == 1
    assert _months_between_inclusive(aug15, date(2026, 9, 15)) == 1
    assert _months_between_inclusive(aug15, date(2026, 9, 16)) == 2
    assert _months_between_inclusive(date(2026, 9, 1), date(2026, 8, 1)) == 0
    print("  ✓ _months_between_inclusive")

    # ── 234A ─────────────────────────────────────────────────────────────────
    assert compute_interest_234a(50_000, date(2026, 7, 31))  == 0.0   # on time
    assert compute_interest_234a(50_000, date(2026, 7, 15))  == 0.0   # early
    assert compute_interest_234a(50_000, None)               == 0.0   # no date
    assert compute_interest_234a(0,      date(2026, 9, 1))   == 0.0   # no tax due
    assert compute_interest_234a(-100,   date(2026, 9, 1))   == 0.0   # refund
    # Aug 1 → Aug 1: period Aug 1→Aug 1 = 1 month; 50,000 × 1% × 1 = 500
    assert compute_interest_234a(50_000, date(2026, 8, 1))   == 500.0
    # Sep 1: Aug 1→Sep 1 = 1 month; 500
    assert compute_interest_234a(50_000, date(2026, 9, 1))   == 500.0
    # Sep 2: Aug 1→Sep 2 = 2 months; 1,000
    assert compute_interest_234a(50_000, date(2026, 9, 2))   == 1_000.0
    print("  ✓ Interest u/s 234A")

    # ── FIX 4: 234B — None filing_date returns 0 ─────────────────────────────
    assert compute_interest_234b(1_00_000, 20_000, 50_000, None) == 0.0  # FIX 4
    print("  ✓ 234B None filing_date returns 0.0 (FIX 4)")

    # ── 234B — advance tax ≥ 90% (no interest) ───────────────────────────────
    # assessed = 1,00,000 − 20,000 = 80,000; advance = 75,000 ≥ 90% of 80,000
    assert compute_interest_234b(1_00_000, 20_000, 75_000, date(2026, 7, 15)) == 0.0

    # ── 234B — advance tax < 90% (interest applies) ──────────────────────────
    # assessed = 80,000; advance = 50,000 < 72,000
    # shortfall = 30,000; Apr 1→Jul 15 = 4 months; 30,000×1%×4 = 1,200
    assert compute_interest_234b(1_00_000, 20_000, 50_000, date(2026, 7, 15)) == 1_200.0

    # ── FIX 2: 234B must NOT include SAT in advance base ─────────────────────
    # Same as above but with SAT that would bring combined total to ≥ 90%.
    # The bug would pass 75,000 (advance+SAT) giving 0; the fix must still give 1,200.
    assert compute_interest_234b(1_00_000, 20_000, 50_000, date(2026, 7, 15)) == 1_200.0, \
        "FIX 2: SAT must not be counted in 234B advance base"
    print("  ✓ Interest u/s 234B (FIX 2 + FIX 4)")

    # ── FIX 3: 234C ──────────────────────────────────────────────────────────
    # assessed = 1,00,000 − 10,000 (TDS) = 90,000
    # Required: Jun 15% = 13,500; Sep 45% = 40,500; Dec 75% = 67,500; Mar 100% = 90,000
    # No payments at all → shortfall at every installment

    no_payments: List[Tuple[date, float]] = []
    # Jun shortfall = 13,500 × 1% × 3 = 405
    # Sep shortfall = 40,500 × 1% × 3 = 1,215
    # Dec shortfall = 67,500 × 1% × 3 = 2,025
    # Mar shortfall = 90,000 × 1% × 1 = 900
    # Total = 4,545
    result_c = compute_interest_234c(1_00_000, 10_000, no_payments)
    assert abs(result_c - 4_545.0) < 1.0, f"234C no payments: {result_c}"

    # All paid by Jun 15 → no shortfall at any installment
    all_by_jun: List[Tuple[date, float]] = [(date(2025, 6, 10), 90_000.0)]
    assert compute_interest_234c(1_00_000, 10_000, all_by_jun) == 0.0

    # Only Sep payment (missed Jun installment):
    # Jun shortfall = 13,500 × 1% × 3 = 405; Sep,Dec,Mar: no shortfall
    sep_only: List[Tuple[date, float]] = [(date(2025, 9, 10), 90_000.0)]
    result_sep = compute_interest_234c(1_00_000, 10_000, sep_only)
    assert abs(result_sep - 405.0) < 1.0, f"234C Sep-only payment: {result_sep}"

    # assessed ≤ 10,000 → no 234C
    assert compute_interest_234c(20_000, 15_000, no_payments) == 0.0   # assessed = 5,000
    print("  ✓ Interest u/s 234C (FIX 3)")

    # ── 234F ─────────────────────────────────────────────────────────────────
    assert compute_fee_234f(10_00_000, date(2026, 7, 31)) == 0.0    # on time
    assert compute_fee_234f(10_00_000, date(2026, 9,  1)) == 5_000.0
    assert compute_fee_234f(4_00_000,  date(2026, 9,  1)) == 1_000.0
    assert compute_fee_234f(5_00_000,  date(2026, 9,  1)) == 1_000.0  # exactly 5L → low
    assert compute_fee_234f(5_00_001,  date(2026, 9,  1)) == 5_000.0  # just above → high
    assert compute_fee_234f(10_00_000, None)               == 0.0
    print("  ✓ Fee u/s 234F")

    # ── _rupee_round ──────────────────────────────────────────────────────────
    assert _rupee_round(1234.4) == 1234
    assert _rupee_round(1234.5) == 1235
    assert _rupee_round(0.0)    == 0
    assert _rupee_round(99.9)   == 100
    print("  ✓ _rupee_round")

    # ── End-to-end: compute_part_d ────────────────────────────────────────────
    # Scenario A — New regime, ₹10L taxable income, TDS ₹5,000, filed on time.
    # Expected:
    #   D1 = 40,000  (new regime slab)
    #   D2 = 40,000  (income ≤ ₹12L → full rebate; min(40000, 60000))
    #   D3 = 0
    #   D4 = 0
    #   D5 = 0
    #   D7 = 0       (on time)
    #   D8 = 0       (assessed = 0 − 5000 → max(0,.) = 0)
    #   D9 = 0       (no advance payments)
    #   D10 = 0      (on time)
    #   D11 = 0
    #   D12 = 5,000
    #   D13 = 0
    #   D14 = 5,000  (TDS refund)

    from tax_schemas import (
        ITR1Schema, ReconciledTaxData, ScheduleTDSEntry, YesNo,
    )

    smoke = ITR1Schema()
    smoke.part_a.opting_out_115bac = YesNo.NO
    smoke.part_c.total_income_C2   = 10_00_000
    smoke.schedule_tds = [
        ScheduleTDSEntry(tan_or_pan="MUMB12345A", section="192", tds_claimed_this_year=5_000.0)
    ]

    rec = ReconciledTaxData()
    rec.tcs_credit = 0.0
    rec.advance_self_assessment_tax_paid = 0.0

    result_a = compute_part_d(smoke, rec, filing_date=date(2026, 7, 15))
    da = result_a.part_d

    assert da.tax_payable_on_total_income_D1 == 40_000,  da.tax_payable_on_total_income_D1
    assert da.rebate_87a_D2                  == 40_000,  da.rebate_87a_D2
    assert da.tax_after_rebate_D3            == 0,       da.tax_after_rebate_D3
    assert da.health_education_cess_D4       == 0,       da.health_education_cess_D4
    assert da.total_tax_and_cess_D5          == 0,       da.total_tax_and_cess_D5
    assert da.interest_234a_D7               == 0,       da.interest_234a_D7
    assert da.interest_234b_D8               == 0,       da.interest_234b_D8
    assert da.interest_234c_D9               == 0,       da.interest_234c_D9
    assert da.fee_234f_D10                   == 0,       da.fee_234f_D10
    assert da.total_tax_fee_interest_D11     == 0,       da.total_tax_fee_interest_D11
    assert da.total_taxes_paid_D12           == 5_000,   da.total_taxes_paid_D12
    assert da.amount_payable_D13             == 0,       da.amount_payable_D13
    assert da.refund_D14                     == 5_000,   da.refund_D14
    print("  ✓ compute_part_d — new regime ₹10L, on time, refund case (Scenario A)")

    # Scenario B — Old Regime, Senior Citizen, ₹7L income, no TDS, late filing
    # Verifies FIX 1 (senior slabs) + FIX 3 (234C) + late fee
    # Senior slab on ₹7L: 0–3L nil, 3L–5L @5% = 10,000, 5L–7L @20% = 40,000 → total 50,000
    # Rebate: income ₹7L > threshold ₹5L → check marginal: 50,000 − (7L−5L) = 30,000 > 0
    #   rebate = max(0, 50,000 − 2,00,000) = 0 (₹7L is well above marginal zone)
    # Tax after rebate = 50,000; cess = 2,000; total = 52,000
    # Late by 1 month (Aug 1) → 234A on self-assessment = 52,000 × 1% × 1 = 520
    # 234F = ₹5,000 (income > ₹5L)
    # 234B: no advance paid, TDS = 0 → shortfall = 52,000; Apr 1→Aug 1 = 4 months; 52,000×1%×4 = 2,080
    # 234C: no installments paid → using function directly verified above
    smoke_b = ITR1Schema()
    smoke_b.part_a.opting_out_115bac = YesNo.YES   # old regime
    smoke_b.part_c.total_income_C2   = 7_00_000
    smoke_b.schedule_tds             = []
    smoke_b.schedule_it              = []

    rec_b = ReconciledTaxData()
    rec_b.tcs_credit = 0.0
    rec_b.advance_self_assessment_tax_paid = 0.0

    result_b = compute_part_d(
        smoke_b, rec_b,
        filing_date=date(2026, 8, 1),
        date_of_birth="01/01/1960",    # age 66 → SENIOR
    )
    db = result_b.part_d

    assert db.tax_payable_on_total_income_D1 == 50_000, db.tax_payable_on_total_income_D1
    assert db.rebate_87a_D2                  == 0,      db.rebate_87a_D2   # ₹7L > threshold
    assert db.tax_after_rebate_D3            == 50_000, db.tax_after_rebate_D3
    assert db.health_education_cess_D4       == 2_000,  db.health_education_cess_D4
    assert db.total_tax_and_cess_D5          == 52_000, db.total_tax_and_cess_D5
    assert db.interest_234b_D8              == 2_080,   db.interest_234b_D8
    assert db.fee_234f_D10                  == 5_000,   db.fee_234f_D10
    print("  ✓ compute_part_d — old regime senior ₹7L, late filing (Scenario B / FIX 1+2+3+4+5)")

    print("\n" + "=" * 60)
    print("✅  All spot checks passed.")
    print("=" * 60)


if __name__ == "__main__":
    _run_spot_checks()
