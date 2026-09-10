"""
pipeline/graph.py
================================================================================
Single unified TaxSathi LangGraph graph.

Implements the exact architecture from the project design:

         START
           ↓
    [intent_router]
    /              \\
chatbot path      itr generation path
    ↓                    ↓
[rewrite_query]   [collect_user_input]
    ↓                    ↓
[retrieve]        [receive_ocr_output]
    ↓                    ↓
[build_prompt]    [cross_validation]
    ↓                    ↓
[gemini_call]     [tax_computation]
    ↓                    ↓
[format_response] [itr_field_mapper]
    ↓                    ↓
   END            [cbdt_validation]
                  /              \\
                NO               YES
                ↓                 ↓
         [show_errors]     [pdf_generation]
                ↓                 ↓
         user corrects           END
                ↓
       [collect_user_input]  ← loop back

NODE STATUS
-----------
✅ intent_router          — routes based on uploaded documents vs text query
✅ rewrite_query_node     — Gemini rewrites query for better RAG retrieval
✅ build_prompt_node      — assembles system + context + query for Gemini
✅ gemini_call_node       — calls Gemini API
✅ format_response_node   — appends assistant reply to messages
✅ collect_user_input_node — validates UserProvidedInfo mandatory fields
✅ cross_validation_node  — PAN match, TDS match, AY check, HITL on PAN mismatch
✅ tax_computation_node   — reconciles Form 16 + 26AS; computes GTI/tax/rebate/cess
✅ itr_field_mapper_node  — maps computed values to ITR-1 fields (B1→D14)
✅ cbdt_validation_node   — runs CBDT Category A rules (partial; Sprint 3)
✅ show_errors_node       — surfaces errors to user via interrupt; loops back
✅ pdf_generation_node    — WeasyPrint HTML → PDF (stub; Sprint 5)
🔧 retrieve_node          — STUB: Kushal's RAG vector DB (Sprint 4)

ENVIRONMENT VARIABLES
---------------------
  GOOGLE_API_KEY — required for rewrite_query_node and gemini_call_node
================================================================================
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from pipeline.state import TaxSathiState
from tax_schemas import (
    FlagSeverity,
    ValidationFlag,
    map_to_itr1,
    reconcile_tax_data,
)
from tax_computation import compute_part_d


# ================================================================================
# GEMINI CLIENT
# ================================================================================

def _gemini(temperature: float = 0.2) -> ChatGoogleGenerativeAI:
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        raise EnvironmentError("GOOGLE_API_KEY environment variable is not set.")
    return ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        google_api_key=key,
        temperature=temperature,
        max_output_tokens=1024,
    )


# ================================================================================
# SYSTEM PROMPTS
# ================================================================================

REWRITE_PROMPT = """"""

ANSWER_PROMPT = """"""


# ================================================================================
# SHARED HELPER
# ================================================================================

def _parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


# ================================================================================
# ── ROUTING FUNCTIONS ──────────────────────────────────────────────────────────
# ================================================================================

def intent_router(state: TaxSathiState) -> str:
    """
    Entry point router — decides which path to take.

    Routes to ITR generation if both Form 16 and Form 26AS are present
    in state (uploaded by the user). Otherwise routes to chatbot.

    The FastAPI layer sets form16_list + form26as in state when the user
    uploads documents, and sets messages when the user sends a text query.
    """
    has_docs = (
        bool(state.get("form16_list")) and
        state.get("form26as") is not None
    )

    # Explicit intent overrides document detection
    explicit = state.get("intent")
    if explicit == "chatbot":
        return "rewrite_query"
    if explicit == "itr_generation":
        return "collect_user_input"

    # Auto-detect
    return "collect_user_input" if has_docs else "rewrite_query"


def route_after_user_input(state: TaxSathiState) -> str:
    if state.get("errors"):
        return END
    return "receive_ocr_output"


def route_after_ocr(state: TaxSathiState) -> str:
    if state.get("errors"):
        return END
    return "cross_validation"


def route_after_cross_validation(state: TaxSathiState) -> str:
    if state.get("errors"):
        return END
    return "tax_computation"


def route_after_tax_computation(state: TaxSathiState) -> str:
    if state.get("errors"):
        return END
    return "itr_field_mapper"


def route_after_itr_field_mapper(state: TaxSathiState) -> str:
    if state.get("errors"):
        return END
    return "cbdt_validation"


def route_after_cbdt_validation(state: TaxSathiState) -> str:
    """
    Core branching point — YES path goes to PDF, NO path shows errors
    and loops back to collect_user_input via show_errors_node.
    """
    draft = state.get("draft_itr1")
    if state.get("errors") or draft is None:
        return END

    category_a_errors = [
        f for f in draft.flags
        if f.severity == FlagSeverity.ERROR and f.stage == "itr_validation"
    ]

    if category_a_errors:
        return "show_errors"     # → NO path → user corrects → loop back

    return "pdf_generation"      # → YES path → generate PDF


def route_after_show_errors(state: TaxSathiState) -> str:
    """
    After show_errors_node resumes from interrupt, check loop count.
    If under max_loops, go back to collect_user_input.
    If over limit, stop to prevent infinite loops.
    """
    if state.get("loop_count", 0) >= state.get("max_loops", 3):
        return END
    return "collect_user_input"


# ================================================================================
# ── CHATBOT PATH NODES ─────────────────────────────────────────────────────────
# ================================================================================

def rewrite_query_node(state: TaxSathiState) -> TaxSathiState:
    """
    Rewrites the user's casual question into a precise retrieval query.

    Example:
      Input : "can I claim HRA and 80GG both?"
      Output: "Can an individual simultaneously claim HRA exemption u/s 10(13A)
               and deduction u/s 80GG for rent paid?"

    Falls back to the original message if Gemini is unavailable.
    """
    messages = state.get("messages", [])
    last_user_msg = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        None,
    )

    if not last_user_msg:
        return {"errors": ["rewrite_query_node: no user message found in state."]}

    try:
        response = _gemini().invoke([
            SystemMessage(content=REWRITE_PROMPT),
            HumanMessage(content=last_user_msg),
        ])
        return {"query": response.content.strip()}
    except Exception as e:
        # Graceful fallback — don't block the pipeline
        return {
            "query": last_user_msg,
            "errors": [f"rewrite_query_node: Gemini unavailable ({e}). Using original query."],
        }


def retrieve_node(state: TaxSathiState) -> TaxSathiState:
    """
    STUB — Sprint 4 (16 Nov – 20 Dec 2026).
    Calls Kushal's RAG vector DB to fetch relevant chunks from
    Income Tax Act 2025 + Income Tax Rules 2026.

    Integration (Kushal):
        from rag.retriever import retrieve_tax_context
        chunks = retrieve_tax_context(query=state["query"], top_k=5)
        rag_context = "\\n\\n---\\n\\n".join(chunks)
    """
    # TODO (Kushal - Sprint 4): replace stub with real RAG retrieval
    query = state.get("query", "")
    stub_context = (
        f"[RAG STUB — Kushal's vector DB not connected yet]\n"
        f"Query: '{query}'\n"
        f"In production this returns chunks from IT Act 2025 + IT Rules 2026."
    )
    return {"rag_context": stub_context}


def build_prompt_node(state: TaxSathiState) -> TaxSathiState:
    """
    Assembles the full prompt: retrieved context + original user question.
    Injects context as a structured message so Gemini has a clear boundary
    between reference material and the question.
    """
    rag_context = state.get("rag_context", "No context retrieved.")
    messages = state.get("messages", [])

    original_question = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        "",
    )

    combined = (
        f"REFERENCE CONTEXT (Income Tax Act 2025 + Rules 2026):\n"
        f"{'─' * 60}\n"
        f"{rag_context}\n"
        f"{'─' * 60}\n\n"
        f"USER QUESTION:\n{original_question}"
    )

    context_message = {"role": "user", "content": combined}
    return {"messages": [context_message]}


def gemini_call_node(state: TaxSathiState) -> TaxSathiState:
    """
    Sends the assembled prompt to Gemini and stores the raw answer.
    """
    messages = state.get("messages", [])
    last_content = messages[-1]["content"] if messages else ""

    try:
        response = _gemini(temperature=0.1).invoke([
            SystemMessage(content=ANSWER_PROMPT),
            HumanMessage(content=last_content),
        ])
        return {"chat_response": response.content.strip()}
    except Exception as e:
        return {
            "chat_response": (
                "I encountered an error generating your answer. "
                "Please try again or rephrase your question."
            ),
            "errors": [f"gemini_call_node: Gemini API failed — {e}"],
        }


def format_response_node(state: TaxSathiState) -> TaxSathiState:
    """
    Appends a disclaimer to the Gemini response and writes it as
    the assistant reply in the conversation history.
    """
    raw = state.get("chat_response", "")
    disclaimer = (
        "\n\n---\n"
        "⚠️ *AI-generated from Income Tax Act 2025 and Rules 2026. "
        "Verify with a qualified Chartered Accountant before filing.*"
    )
    assistant_msg = {"role": "assistant", "content": raw + disclaimer}
    return {"messages": [assistant_msg], "pipeline_complete": True}


# ================================================================================
# ── ITR GENERATION PATH NODES ──────────────────────────────────────────────────
# ================================================================================

def collect_user_input_node(state: TaxSathiState) -> TaxSathiState:
    """
    Validates UserProvidedInfo — checks that all fields ITR-1 requires
    (but Form 16/26AS cannot provide) are present.

    Mandatory:
      first_name, last_name, date_of_birth, aadhaar_number,
      primary_mobile, primary_email, filed_under_section,
      nature_of_employment, at least one bank account with refund selected.

    Also resets cbdt_error_summary so the UI can show fresh errors
    on each loop iteration.
    """
    user = state.get("user_input")
    missing = []

    if user is None:
        return {
            "errors": ["UserProvidedInfo is None — must be provided before ITR generation."],
            "cbdt_error_summary": None,
        }

    if not user.first_name or not user.last_name:
        missing.append("Name (first_name and last_name)")
    if not user.date_of_birth:
        missing.append("Date of birth (DD/MM/YYYY) — needed for tax slab selection")
    if not user.aadhaar_number:
        missing.append("Aadhaar number (12 digits) — mandatory u/s 139AA")
    if not user.primary_mobile:
        missing.append("Primary mobile number")
    if not user.primary_email:
        missing.append("Primary email address")
    if not user.filed_under_section:
        missing.append("Filing section (e.g. 139(1))")
    if not user.nature_of_employment:
        missing.append("Nature of employment (Central Govt / State Govt / PSU / Others)")
    if not user.bank_accounts:
        missing.append("At least one bank account for refund credit")
    elif not any(acc.selected_for_refund for acc in user.bank_accounts):
        missing.append("At least one bank account must be selected for refund")

    if missing:
        return {
            "errors": [f"collect_user_input: Missing required fields — {'; '.join(missing)}."],
            "cbdt_error_summary": None,
        }

    return {"cbdt_error_summary": None}


def receive_ocr_output_node(state: TaxSathiState) -> TaxSathiState:
    """
    STUB — verifies that Kushal's LlamaParser output is present in state.

    In production Kushal's parser runs before the graph and populates
    state["form16_list"] and state["form26as"] via the FastAPI upload
    endpoint. This node validates they arrived correctly.

    TODO (Kushal): if parser runs inside the graph, call it here.
    """
    form16_list = state.get("form16_list", [])
    form26as    = state.get("form26as")
    missing     = []

    if not form16_list:
        missing.append("Form 16 (no documents in form16_list)")
    if form26as is None:
        missing.append("Form 26AS (form26as is None)")

    if missing:
        return {"errors": [f"receive_ocr_output: Missing parsed documents — {'; '.join(missing)}."]}

    return {}


def cross_validation_node(state: TaxSathiState) -> TaxSathiState:
    """
    Cross-validates Form 16 and Form 26AS before computation.

    Checks:
      1. PAN consistency across all Form 16 documents and Form 26AS.
         → HITL interrupt on mismatch: pauses graph, asks user for corrected docs.
      2. Assessment year consistency.
      3. TDS amount: Form 16 Part A total TDS vs Form 26AS Part A total TDS.
      4. At least one Form 16 has a computable salary income figure.

    HITL Pattern (PAN mismatch):
      Graph pauses via interrupt(), surfaces mismatch message to user.
      FastAPI resumes with: Command(resume={"form16_list": [...], "form26as": ...})
    """
    form16_list = state.get("form16_list", [])
    form26as    = state.get("form26as")
    errors      = []

    if not form16_list or form26as is None:
        return {}  # already caught by receive_ocr_output_node

    # ── Check 1: PAN consistency ──────────────────────────────────────────────
    f16_pans = {
        f.details.employee_pan.strip().upper()
        for f in form16_list if f.details.employee_pan
    }
    f26_pan = form26as.pan.strip().upper() if form26as.pan else None

    pan_ok = (len(f16_pans) == 1 and f26_pan and next(iter(f16_pans)) == f26_pan)

    if not pan_ok:
        mismatch_msg = (
            f"PAN Mismatch Detected.\n"
            f"  Form 16 PAN(s) : {sorted(f16_pans) if f16_pans else 'not found'}\n"
            f"  Form 26AS PAN  : {f26_pan or 'not found'}\n"
            f"Please re-upload the correct documents."
        )
        # ── HITL interrupt ────────────────────────────────────────────────────
        correction = interrupt(payload=mismatch_msg)
        return {
            "form16_list": correction.get("form16_list", form16_list),
            "form26as":    correction.get("form26as", form26as),
            "errors":      [],
        }

    # ── Check 2: Assessment Year ──────────────────────────────────────────────
    f16_ays = {f.details.assessment_year for f in form16_list if f.details.assessment_year}
    if form26as.assessment_year and f16_ays and form26as.assessment_year not in f16_ays:
        errors.append(
            f"cross_validation: AY mismatch — Form 26AS AY ({form26as.assessment_year}) "
            f"does not match Form 16 AY ({f16_ays}). Verify uploaded documents."
        )

    # ── Check 3: TDS cross-check ──────────────────────────────────────────────
    # Sum of TDS across all Form 16 Part A totals vs Form 26AS Part A total
    f16_tds_list = [
        f.tax_computation.tds_per_12baa_19
        for f in form16_list
        if f.tax_computation.tds_per_12baa_19 is not None
    ]
    if f16_tds_list and form26as.total_tds_salary is not None:
        f16_tds_total = round(sum(f16_tds_list), 2)
        f26_tds_total = form26as.total_tds_salary
        if abs(f16_tds_total - f26_tds_total) > 1.0:
            errors.append(
                f"cross_validation: TDS mismatch — Form 16 total TDS (₹{f16_tds_total:,.2f}) "
                f"does not match Form 26AS Part A total TDS (₹{f26_tds_total:,.2f}). "
                f"Verify with employer before filing."
            )

    # ── Check 4: Usable salary figure ────────────────────────────────────────
    if not any(f.income_chargeable_salaries_6 is not None for f in form16_list):
        errors.append(
            "cross_validation: Could not compute 'Income chargeable under Salaries' "
            "from any Form 16. LlamaParser extraction may be incomplete."
        )

    return {"errors": errors}


def tax_computation_node(state: TaxSathiState) -> TaxSathiState:
    """
    Reconciles Form 16 + Form 26AS and computes:
      - Gross Total Income (GTI)
      - Chapter VI-A deductions
      - Net taxable income
      - Slab tax (new/old regime)
      - Rebate u/s 87A + marginal relief
      - Health & Education Cess (4%)

    Calls reconcile_tax_data() from tax_schemas.py which handles:
      - Multi-employer salary summing
      - Deduction double-count prevention
      - Interest income from Form 26AS Part A1
      - Property transaction eligibility check
    """
    try:
        reconciled = reconcile_tax_data(
            form16_documents=state.get("form16_list", []),
            form26as=state.get("form26as"),
        )

        # Block if ITR-1 ineligible (property transaction, etc.)
        if reconciled.itr1_eligible is False:
            reasons = [
                f.issue for f in reconciled.flags
                if f.severity == FlagSeverity.ERROR
            ]
            return {
                "reconciled": reconciled,
                "errors": [
                    "tax_computation: ITR-1 ineligibility detected. "
                    f"Reasons: {'; '.join(reasons)}"
                ],
            }

        return {"reconciled": reconciled}

    except Exception as e:
        return {"errors": [f"tax_computation_node crashed: {str(e)}"]}


def itr_field_mapper_node(state: TaxSathiState) -> TaxSathiState:
    """
    Maps all computed values to the exact ITR-1 field codes (B1, B2, C1...D14).

    Step 1: map_to_itr1() — populates:
      Part A (identity + regime from UserProvidedInfo + Form 16)
      Part B (B1 salary, B2 house property, B3 other sources, B4 GTI)
      Part C (C1 deductions, C2 total income)
      Schedule IT (advance tax entries from Form 26AS Part C)
      Schedule TDS (TDS entries from Form 26AS Part A + A1)

    Step 2: compute_part_d() — populates:
      Part D (D1 tax, D2 rebate, D3 after rebate, D4 cess, D5 total,
              D7 234A, D8 234B, D9 234C, D10 234F, D11 total fees,
              D12 taxes paid, D13 payable, D14 refund)
    """
    reconciled = state.get("reconciled")
    user       = state.get("user_input")

    if reconciled is None:
        return {"errors": ["itr_field_mapper: reconciled data is None."]}

    try:
        # Step 1 — map to ITR-1 structure
        draft_itr1 = map_to_itr1(reconciled=reconciled, user_input=user)

        # Step 2 — fill Part D tax computation
        filing_date = _parse_date(state.get("filing_date_str")) or date.today()
        dob         = user.date_of_birth if user else None

        draft_itr1 = compute_part_d(
            itr=draft_itr1,
            reconciled=reconciled,
            filing_date=filing_date,
            date_of_birth=dob,
        )

        return {"draft_itr1": draft_itr1}

    except Exception as e:
        return {"errors": [f"itr_field_mapper_node crashed: {str(e)}"]}


def cbdt_validation_node(state: TaxSathiState) -> TaxSathiState:
    """
    Validates the filled ITR-1 draft against CBDT Category A rules.

    Source: CBDT e-Filing ITR-1 Validation Rules AY 2025-26 V1.1 (279 rules).
    Category A violations block PDF generation.

    Currently implements:
      Rule 17  — Chapter VI-A deductions ≤ GTI
      Rule 24  — Total Income = GTI - Deductions (arithmetic check)
      Rule 117 — Total income ≤ ₹50,00,000 (ITR-1 ceiling)

    Sprint 3 (12 Oct – 15 Nov 2026): implement all 279 rules.
    See TAXSATHI_PROJECT.md Section 9.2 for the full list.
    """
    draft = state.get("draft_itr1")
    if draft is None:
        return {"errors": ["cbdt_validation: draft_itr1 is None."]}

    new_flags = []

    b4 = draft.part_b.gross_total_income_B4
    c1 = draft.part_c.total_deductions_C1
    c2 = draft.part_c.total_income_C2

    # Rule 17: Chapter VI-A deductions ≤ GTI
    if c1 is not None and b4 is not None and c1 > b4:
        new_flags.append(ValidationFlag(
            stage="itr_validation", field="part_c.total_deductions_C1",
            issue=f"Rule 17: Deductions (₹{c1:,.0f}) exceed GTI (₹{b4:,.0f}).",
            severity=FlagSeverity.ERROR,
        ))

    # Rule 24: Total Income = max(0, GTI - Deductions)
    if b4 is not None and c1 is not None and c2 is not None:
        expected = max(0, b4 - c1)
        if abs(c2 - expected) > 1:
            new_flags.append(ValidationFlag(
                stage="itr_validation", field="part_c.total_income_C2",
                issue=f"Rule 24: Total income (₹{c2:,.0f}) ≠ GTI − Deductions (₹{expected:,.0f}).",
                severity=FlagSeverity.ERROR,
            ))

    # Rule 117: ITR-1 income ceiling ₹50L
    if c2 is not None and c2 > 5_000_000:
        new_flags.append(ValidationFlag(
            stage="itr_validation", field="part_c.total_income_C2",
            issue=f"Rule 117: Income (₹{c2:,.0f}) exceeds ITR-1 ceiling of ₹50,00,000. Use ITR-2.",
            severity=FlagSeverity.ERROR,
        ))

    draft.flags.extend(new_flags)

    # Build a human-readable summary of Category A errors for show_errors_node
    cat_a = [f for f in draft.flags if f.severity == FlagSeverity.ERROR and f.stage == "itr_validation"]
    summary = None
    if cat_a:
        summary = "The following issues must be fixed before generating your ITR-1:\n" + \
                  "\n".join(f"  • {f.issue}" for f in cat_a)

    return {"draft_itr1": draft, "cbdt_error_summary": summary}


def show_errors_node(state: TaxSathiState) -> TaxSathiState:
    """
    Surfaces CBDT Category A validation errors to the user and pauses
    the graph via interrupt() until the user provides corrected input.

    Loop mechanism:
      1. Graph pauses here with interrupt().
      2. FastAPI shows errors to the user (from cbdt_error_summary).
      3. User uploads corrected documents / updates UserProvidedInfo.
      4. FastAPI resumes with Command(resume={corrected state fields}).
      5. route_after_show_errors() sends graph back to collect_user_input.

    Circuit breaker: if loop_count reaches max_loops, graph routes to END
    instead of looping again, preventing infinite retry cycles.
    """
    error_summary = state.get("cbdt_error_summary", "Validation errors found. Please review and correct your information.")
    current_loop  = state.get("loop_count", 0)
    max_loops     = state.get("max_loops", 3)

    if current_loop >= max_loops:
        return {
            "errors": [
                f"show_errors: Maximum retry limit ({max_loops}) reached. "
                f"Please consult a Chartered Accountant for manual assistance."
            ],
        }

    payload = {
        "errors":     error_summary,
        "loop_count": current_loop,
        "max_loops":  max_loops,
    }

    # Graph pauses here — FastAPI must call resume with corrected data
    correction = interrupt(payload=payload)

    # Apply corrections returned by the user
    updates = {}
    if "user_input" in correction:
        updates["user_input"] = correction["user_input"]
    if "form16_list" in correction:
        updates["form16_list"] = correction["form16_list"]
    if "form26as" in correction:
        updates["form26as"] = correction["form26as"]

    updates["loop_count"]  = current_loop + 1
    updates["draft_itr1"]  = None   # reset draft — will be recomputed
    updates["reconciled"]  = None   # reset reconciled — will be recomputed

    return updates


def pdf_generation_node(state: TaxSathiState) -> TaxSathiState:
    """
    STUB — Sprint 5 (21 Dec 2026 – 1 Feb 2027).

    Generates the final downloadable ITR-1 PDF using WeasyPrint.

    Steps to implement:
      1. Render backend/templates/itr1_template.html with Jinja2,
         injecting all draft_itr1 field values.
      2. Convert rendered HTML to PDF bytes via WeasyPrint.
      3. Store in state["pdf_bytes"].

    The HTML template must replicate the official ITR-1 (Sahaj) layout
    from the Gazette of India (AY 2026-27 version).

    Implementation sketch:
      from jinja2 import Environment, FileSystemLoader
      from weasyprint import HTML

      env      = Environment(loader=FileSystemLoader("backend/templates"))
      template = env.get_template("itr1_template.html")
      rendered = template.render(itr=state["draft_itr1"])
      pdf      = HTML(string=rendered).write_pdf()
      return {"pdf_bytes": pdf, "pipeline_complete": True}
    """
    # TODO (Sprint 5): implement WeasyPrint PDF generation
    print("[STUB] pdf_generation_node — PDF generation not yet implemented.")
    return {"pipeline_complete": False}


# ================================================================================
# GRAPH COMPILATION
# ================================================================================

def build_graph():
    """
    Builds and compiles the single unified TaxSathi StateGraph.

    Matches the exact architecture from the project design document:
      START → intent_router → chatbot path OR itr generation path

    Requires MemorySaver (or persistent checkpointer) for interrupt()
    nodes to work (cross_validation PAN mismatch and show_errors loop).
    """
    g = StateGraph(TaxSathiState)

    # ── Register all nodes ────────────────────────────────────────────────────

    # Chatbot path
    g.add_node("rewrite_query",    rewrite_query_node)
    g.add_node("retrieve",         retrieve_node)
    g.add_node("build_prompt",     build_prompt_node)
    g.add_node("gemini_call",      gemini_call_node)
    g.add_node("format_response",  format_response_node)

    # ITR generation path
    g.add_node("collect_user_input",  collect_user_input_node)
    g.add_node("receive_ocr_output",  receive_ocr_output_node)
    g.add_node("cross_validation",    cross_validation_node)
    g.add_node("tax_computation",     tax_computation_node)
    g.add_node("itr_field_mapper",    itr_field_mapper_node)
    g.add_node("cbdt_validation",     cbdt_validation_node)
    g.add_node("show_errors",         show_errors_node)
    g.add_node("pdf_generation",      pdf_generation_node)

    # ── Edges from START ──────────────────────────────────────────────────────
    g.add_conditional_edges(
        START,
        intent_router,
        {
            "rewrite_query":      "rewrite_query",
            "collect_user_input": "collect_user_input",
        },
    )

    # ── Chatbot path edges ────────────────────────────────────────────────────
    g.add_edge("rewrite_query",   "retrieve")
    g.add_edge("retrieve",        "build_prompt")
    g.add_edge("build_prompt",    "gemini_call")
    g.add_edge("gemini_call",     "format_response")
    g.add_edge("format_response", END)

    # ── ITR generation path edges ─────────────────────────────────────────────
    g.add_conditional_edges("collect_user_input",  route_after_user_input)
    g.add_conditional_edges("receive_ocr_output",  route_after_ocr)
    g.add_conditional_edges("cross_validation",    route_after_cross_validation)
    g.add_conditional_edges("tax_computation",     route_after_tax_computation)
    g.add_conditional_edges("itr_field_mapper",    route_after_itr_field_mapper)
    g.add_conditional_edges("cbdt_validation",     route_after_cbdt_validation,
        {
            "show_errors":    "show_errors",     # NO path
            "pdf_generation": "pdf_generation",  # YES path
            END:              END,
        }
    )

    # ── Loop back edge: show_errors → collect_user_input ─────────────────────
    g.add_conditional_edges(
        "show_errors",
        route_after_show_errors,
        {
            "collect_user_input": "collect_user_input",
            END:                  END,
        },
    )

    g.add_edge("pdf_generation", END)

    # ── Compile with checkpointer (required for interrupt nodes) ──────────────
    from langgraph.checkpoint.memory import MemorySaver
    return g.compile(checkpointer=MemorySaver())


# Single compiled app — import this everywhere
app = build_graph()
