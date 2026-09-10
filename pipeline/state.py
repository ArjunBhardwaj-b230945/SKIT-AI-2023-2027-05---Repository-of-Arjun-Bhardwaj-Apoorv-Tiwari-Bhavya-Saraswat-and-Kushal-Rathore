"""
pipeline/state.py
================================================================================
Shared state for the single unified TaxSathi LangGraph graph.
Both the chatbot path and the ITR generation path read from and write to
this same state object.
================================================================================
"""

import operator
from typing import Annotated, List, Optional, TypedDict

from tax_schemas import (
    Form16Schema,
    Form26ASSchema,
    ITR1Schema,
    ReconciledTaxData,
    UserProvidedInfo,
)


class TaxSathiState(TypedDict):

    # ── Routing ───────────────────────────────────────────────────────────────
    # Set by intent_router. Values: "chatbot" | "itr_generation"
    intent: Optional[str]

    # ── ITR Pipeline — Inputs ─────────────────────────────────────────────────
    form16_list: List[Form16Schema]       # one per employer; set before graph runs
    form26as: Optional[Form26ASSchema]    # set before graph runs
    user_input: Optional[UserProvidedInfo]
    filing_date_str: Optional[str]        # DD/MM/YYYY — for 234A/B/F computation

    # ── ITR Pipeline — Intermediate Outputs ──────────────────────────────────
    reconciled: Optional[ReconciledTaxData]   # after tax_computation_node
    draft_itr1: Optional[ITR1Schema]           # after itr_field_mapper_node
    pdf_bytes: Optional[bytes]                 # after pdf_generation_node

    # ── Loop Control (ITR error → user corrects → retry) ─────────────────────
    cbdt_error_summary: Optional[str]   # human-readable errors shown to user
    loop_count: int                     # how many times we have looped back
    max_loops: int                      # circuit breaker — default 3

    # ── Chatbot Fields ────────────────────────────────────────────────────────
    messages: Annotated[List[dict], operator.add]   # append-only conversation history
    query: Optional[str]                             # rewritten retrieval query
    rag_context: Optional[str]                       # chunks from Kushal's RAG
    chat_response: Optional[str]                     # raw Gemini answer

    # ── Shared ────────────────────────────────────────────────────────────────
    errors: Annotated[List[str], operator.add]   # append-only; never overwritten
    pipeline_complete: bool
