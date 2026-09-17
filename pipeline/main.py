"""
pipeline/main.py
================================================================================
Entry point for Apoorv's FastAPI routers.

Three public functions:
  run_chatbot(...)        — POST /api/chat
  run_itr_pipeline(...)   — POST /api/generate-itr
  resume_pipeline(...)    — POST /api/resume  (after any interrupt)

HOW INTERRUPTS WORK IN THIS SYSTEM
------------------------------------
Two nodes can pause the graph via interrupt():

  1. cross_validation_node  — PAN mismatch between Form 16 and Form 26AS.
     Caller resumes with corrected documents:
       resume_pipeline(thread_id, {"form16_list": [...], "form26as": ...})

  2. show_errors_node — CBDT Category A validation errors found.
     Caller resumes with corrected user input / documents:
       resume_pipeline(thread_id, {"user_input": ..., "form16_list": [...]})

Both use the same resume_pipeline() function — the graph knows internally
which node it was paused at and continues from there.

THREAD ID
----------
Every ITR pipeline invocation gets a unique thread_id (UUID).
This is the key to the LangGraph checkpointer — it stores graph state
between interrupt and resume. The FastAPI layer must:
  1. Store thread_id from run_itr_pipeline() response.
  2. Pass it back in resume_pipeline() calls.
  3. Keep it for the duration of the user's ITR session.
================================================================================
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from langgraph.types import Command

from pipeline.graph import app
from pipeline.state import TaxSathiState
from tax_schemas import (
    Form16Schema,
    Form26ASSchema,
    FlagSeverity,
    UserProvidedInfo,
)


# ================================================================================
# HELPER — build a clean response dict from final graph state
# ================================================================================

def _build_itr_response(thread_id: str, final_state: TaxSathiState) -> Dict[str, Any]:
    """Extracts result fields from ITR pipeline final state into a clean dict."""
    draft     = final_state.get("draft_itr1")
    pdf_bytes = final_state.get("pdf_bytes")
    errors    = final_state.get("errors", [])

    flags = []
    if draft and draft.flags:
        flags = [
            {
                "stage":    f.stage,
                "field":    f.field,
                "issue":    f.issue,
                "severity": f.severity.value,
            }
            for f in draft.flags
        ]

    blocking = [f for f in flags if f["severity"] == "error" and f["stage"] == "itr_validation"]

    return {
        "thread_id":          thread_id,
        "status":             "complete" if final_state.get("pipeline_complete") else "incomplete",
        "pdf_bytes":          pdf_bytes,
        "flags":              flags,
        "blocking_errors":    blocking,
        "errors":             errors,
        "cbdt_error_summary": final_state.get("cbdt_error_summary"),
        "loop_count":         final_state.get("loop_count", 0),
    }


def _detect_interrupt(thread_id: str) -> Optional[Dict[str, Any]]:
    """
    Checks whether the graph is currently paused at an interrupt node.
    Returns interrupt payload dict if paused, None if completed normally.
    """
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = app.get_state(config)
        if not snapshot.next:
            return None

        for task in getattr(snapshot, "tasks", []):
            interrupts = getattr(task, "interrupts", [])
            if interrupts:
                return {
                    "interrupted":    True,
                    "interrupt_node": snapshot.next[0] if snapshot.next else "unknown",
                    "payload":        str(interrupts[0].value),
                }
    except Exception:
        pass
    return None


# ================================================================================
# PUBLIC FUNCTION 1 — run_chatbot
# ================================================================================

def run_chatbot(
    user_message: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Runs a single chatbot turn with full persistent conversation memory
    via Supabase PostgreSQL.

    Called by: POST /api/chat

    HOW CONTINUITY WORKS
    ---------------------
    The PostgreSQL checkpointer stores the full graph state (including all
    messages) after every node, keyed by thread_id (= session_id).

    First message  : pass session_id=None -> new UUID generated and returned.
                     Frontend stores this UUID.
    Follow-up turns: pass the same session_id -> checkpointer loads prior
                     state from Supabase and appends the new message.
                     Conversation history survives server restarts.

    Frontend only sends: { "message": "...", "session_id": "..." }
    No conversation_history array needed -- the DB handles it.

    Parameters
    ----------
    user_message : Current user question (plain text).
    session_id   : UUID from previous turn. None = start a new conversation.

    Returns
    -------
    {
        "response"   : str  -- formatted answer with disclaimer
        "session_id" : str  -- store this; send back on every follow-up turn
        "errors"     : list -- non-fatal errors
    }
    """
    is_new_session = session_id is None
    session_id     = session_id or str(uuid.uuid4())
    config         = {"configurable": {"thread_id": session_id}}

    if is_new_session:
        # ── New conversation ──────────────────────────────────────────────────
        # Checkpointer has no prior state for this thread_id yet.
        # Pass the complete initial state so every key is populated.
        invoke_input: TaxSathiState = {
            "intent":             "chatbot",
            "form16_list":        [],
            "form26as":           None,
            "user_input":         None,
            "filing_date_str":    None,
            "reconciled":         None,
            "draft_itr1":         None,
            "pdf_bytes":          None,
            "cbdt_error_summary": None,
            "loop_count":         0,
            "max_loops":          3,
            "messages":           [{"role": "user", "content": user_message}],
            "query":              None,
            "rag_context":        None,
            "chat_response":      None,
            "errors":             [],
            "pipeline_complete":  False,
        }
    else:
        # ── Existing conversation ─────────────────────────────────────────────
        # Send ONLY the new user message. The checkpointer loads all previous
        # state (including full message history) from Supabase automatically.
        # messages uses operator.add so the new message is APPENDED to existing
        # history. Never pass full history here — that would duplicate messages.
        invoke_input = {
            "messages":          [{"role": "user", "content": user_message}],
            "query":             None,
            "rag_context":       None,
            "chat_response":     None,
            "pipeline_complete": False,
        }

    try:
        final_state = app.invoke(invoke_input, config=config)
    except Exception as e:
        return {
            "response":   "I encountered an error. Please try again.",
            "session_id": session_id,
            "errors":     [f"Chatbot pipeline crashed: {str(e)}"],
        }

    all_messages   = final_state.get("messages", [])
    last_assistant = next(
        (m["content"] for m in reversed(all_messages) if m.get("role") == "assistant"),
        "I could not generate a response. Please try again.",
    )

    return {
        "response":   last_assistant,
        "session_id": session_id,   # frontend must store and send back each turn
        "errors":     final_state.get("errors", []),
    }


# ================================================================================
# PUBLIC FUNCTION 2 — run_itr_pipeline
# ================================================================================

def run_itr_pipeline(
    form16_list: List[Form16Schema],
    form26as: Form26ASSchema,
    user_input: UserProvidedInfo,
    filing_date_str: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Starts the ITR generation pipeline from the beginning.

    Called by: POST /api/generate-itr

    Parameters
    ----------
    form16_list     : Parsed Form 16 schema(s) from Kushal's LlamaParser.
    form26as        : Parsed Form 26AS schema from Kushal's LlamaParser.
    user_input      : Taxpayer-supplied fields (DOB, Aadhaar, bank accounts etc.)
    filing_date_str : Date the return will be filed — DD/MM/YYYY.
    thread_id       : Auto-generated if None. Store and pass to resume_pipeline()
                      if the graph is interrupted.

    Returns
    -------
    {
        "thread_id"         : str
        "status"            : "complete" | "incomplete" | "interrupted" | "error"
        "interrupted"       : bool
        "interrupt_node"    : str   — which node triggered the interrupt
        "interrupt_message" : str   — message to show the user
        "pdf_bytes"         : bytes
        "flags"             : list
        "blocking_errors"   : list
        "errors"            : list
        "cbdt_error_summary": str
        "loop_count"        : int
    }
    """
    thread_id = thread_id or str(uuid.uuid4())
    config    = {"configurable": {"thread_id": thread_id}}

    initial_state: TaxSathiState = {
        "intent":             "itr_generation",
        "form16_list":        form16_list,
        "form26as":           form26as,
        "user_input":         user_input,
        "filing_date_str":    filing_date_str,
        "reconciled":         None,
        "draft_itr1":         None,
        "pdf_bytes":          None,
        "cbdt_error_summary": None,
        "loop_count":         0,
        "max_loops":          3,
        "messages":           [],
        "query":              None,
        "rag_context":        None,
        "chat_response":      None,
        "errors":             [],
        "pipeline_complete":  False,
    }

    try:
        final_state = app.invoke(initial_state, config=config)
    except Exception as e:
        return {
            "thread_id":          thread_id,
            "status":             "error",
            "interrupted":        False,
            "interrupt_node":     None,
            "interrupt_message":  None,
            "pdf_bytes":          None,
            "flags":              [],
            "blocking_errors":    [],
            "errors":             [f"Pipeline crashed: {str(e)}"],
            "cbdt_error_summary": None,
            "loop_count":         0,
        }

    interrupt_info = _detect_interrupt(thread_id)
    if interrupt_info:
        return {
            "thread_id":          thread_id,
            "status":             "interrupted",
            "interrupted":        True,
            "interrupt_node":     interrupt_info.get("interrupt_node"),
            "interrupt_message":  interrupt_info.get("payload"),
            "pdf_bytes":          None,
            "flags":              [],
            "blocking_errors":    [],
            "errors":             [],
            "cbdt_error_summary": None,
            "loop_count":         final_state.get("loop_count", 0),
        }

    response = _build_itr_response(thread_id, final_state)
    response.update({
        "interrupted":       False,
        "interrupt_node":    None,
        "interrupt_message": None,
    })
    return response


# ================================================================================
# PUBLIC FUNCTION 3 — resume_pipeline
# ================================================================================

def resume_pipeline(
    thread_id: str,
    corrected_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Resumes an ITR pipeline paused by an interrupt node.

    Handles BOTH interrupt types:
      1. cross_validation_node (PAN mismatch):
           corrected_data = {
               "form16_list": [...],
               "form26as":    ...,
           }
      2. show_errors_node (CBDT Category A errors):
           corrected_data = {
               "user_input":  ...,
               "form16_list": [...],   # only if documents changed
               "form26as":    ...,     # only if documents changed
           }

    Called by: POST /api/resume
    """
    config = {"configurable": {"thread_id": thread_id}}

    try:
        final_state = app.invoke(Command(resume=corrected_data), config=config)
    except Exception as e:
        return {
            "thread_id":          thread_id,
            "status":             "error",
            "interrupted":        False,
            "interrupt_node":     None,
            "interrupt_message":  None,
            "pdf_bytes":          None,
            "flags":              [],
            "blocking_errors":    [],
            "errors":             [f"Resume crashed: {str(e)}"],
            "cbdt_error_summary": None,
            "loop_count":         0,
        }

    interrupt_info = _detect_interrupt(thread_id)
    if interrupt_info:
        return {
            "thread_id":          thread_id,
            "status":             "interrupted",
            "interrupted":        True,
            "interrupt_node":     interrupt_info.get("interrupt_node"),
            "interrupt_message":  interrupt_info.get("payload"),
            "pdf_bytes":          None,
            "flags":              [],
            "blocking_errors":    [],
            "errors":             [],
            "cbdt_error_summary": final_state.get("cbdt_error_summary"),
            "loop_count":         final_state.get("loop_count", 0),
        }

    response = _build_itr_response(thread_id, final_state)
    response.update({
        "interrupted":       False,
        "interrupt_node":    None,
        "interrupt_message": None,
    })
    return response


# ================================================================================
# SMOKE TEST
# ================================================================================

if __name__ == "__main__":
    """
    Run: python -m pipeline.main

    Tests chatbot only (no documents needed).
    Requires GOOGLE_API_KEY and DATABASE_URL to be set.
    """
    import os

    print("=" * 60)
    print("TaxSathi — Pipeline Smoke Test")
    print("=" * 60)

    missing = []
    if not os.getenv("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")
    if not os.getenv("DATABASE_URL"):
        missing.append("DATABASE_URL")

    if missing:
        print(f"\n⚠  Missing environment variables: {', '.join(missing)}")
        print("   Set them first:")
        for var in missing:
            print(f"   $env:{var} = \"your_value_here\"")
        print()
    else:
        print("\n[1] Chatbot — first message (new session)")
        result = run_chatbot(
            user_message="What is the standard deduction limit for salaried employees under the new regime?",
        )
        print(f"   Status     : {'OK' if not result['errors'] else 'ERRORS'}")
        print(f"   Session ID : {result['session_id']}")
        print(f"   Reply      : {result['response'][:300]}...")
        if result["errors"]:
            print(f"   Errors     : {result['errors']}")

        print("\n[2] Chatbot — follow-up (same session, DB loads history)")
        result2 = run_chatbot(
            user_message="What about the standard deduction under the old regime?",
            session_id=result["session_id"],   # same session_id — DB loads history
        )
        print(f"   Status     : {'OK' if not result2['errors'] else 'ERRORS'}")
        print(f"   Reply      : {result2['response'][:300]}...")
        if result2["errors"]:
            print(f"   Errors     : {result2['errors']}")

    print("\n" + "=" * 60)
    print("Smoke test complete.")
    print("=" * 60)