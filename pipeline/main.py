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

    # Separate Category A (blocking) errors for the UI to highlight
    blocking = [f for f in flags if f["severity"] == "error" and f["stage"] == "itr_validation"]

    return {
        "thread_id":        thread_id,
        "status":           "complete" if final_state.get("pipeline_complete") else "incomplete",
        "pdf_bytes":        pdf_bytes,
        "flags":            flags,
        "blocking_errors":  blocking,
        "errors":           errors,
        "cbdt_error_summary": final_state.get("cbdt_error_summary"),
        "loop_count":       final_state.get("loop_count", 0),
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
            return None  # graph is done — not interrupted

        # Find interrupt payload from pending tasks
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
    conversation_history: Optional[List[dict]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Runs a single chatbot turn through the unified graph.

    Called by: POST /api/chat

    Parameters
    ----------
    user_message         : The user's current question.
    conversation_history : All previous turns as [{"role": ..., "content": ...}].
                           Include full history so Gemini has conversation context.
    session_id           : Optional session ID for logging. Not used for checkpointing
                           (chatbot path has no interrupts — no checkpointer needed).

    Returns
    -------
    {
        "response"   : str   — assistant's formatted answer with disclaimer
        "session_id" : str   — echo back the session ID
        "errors"     : list  — any non-fatal pipeline errors
    }
    """
    session_id = session_id or str(uuid.uuid4())

    history = list(conversation_history or [])
    history.append({"role": "user", "content": user_message})

    initial_state: TaxSathiState = {
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
        "messages":           history,
        "query":              None,
        "rag_context":        None,
        "chat_response":      None,
        "errors":             [],
        "pipeline_complete":  False,
    }

    # Chatbot needs a config with thread_id even though it has no interrupts,
    # because the graph is compiled with a checkpointer (MemorySaver).
    config = {"configurable": {"thread_id": session_id}}
    try:
        final_state = app.invoke(initial_state, config=config)
    except Exception as e:
        return {
            "response":   "I encountered an error. Please try again.",
            "session_id": session_id,
            "errors":     [f"Chatbot pipeline crashed: {str(e)}"],
        }

    # Extract last assistant message
    all_messages = final_state.get("messages", [])
    last_assistant = next(
        (m["content"] for m in reversed(all_messages) if m.get("role") == "assistant"),
        "I could not generate a response. Please try again.",
    )

    return {
        "response":   last_assistant,
        "session_id": session_id,
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
                      List supports multiple employers (job change mid-year).
    form26as        : Parsed Form 26AS schema from Kushal's LlamaParser.
    user_input      : Taxpayer-supplied fields (DOB, Aadhaar, bank accounts, etc.)
                      that cannot be extracted from Form 16 or Form 26AS.
    filing_date_str : Date the return will be filed — DD/MM/YYYY.
                      Used to compute 234A/B/F interest/fees.
                      Defaults to today's date if not provided.
    thread_id       : LangGraph thread ID for checkpointing.
                      Auto-generated if None. MUST be stored by the caller
                      and passed to resume_pipeline() if the graph is interrupted.

    Returns
    -------
    {
        "thread_id"        : str   — store this; pass to resume_pipeline() if interrupted
        "status"           : str   — "complete" | "incomplete" | "interrupted" | "error"
        "interrupted"      : bool  — True if graph paused at an interrupt node
        "interrupt_node"   : str   — which node triggered the interrupt
        "interrupt_message": str   — human-readable message to show the user
        "pdf_bytes"        : bytes — filled ITR-1 PDF (None if not yet generated)
        "flags"            : list  — all ValidationFlag dicts from draft_itr1
        "blocking_errors"  : list  — Category A CBDT errors that blocked generation
        "errors"           : list  — pipeline error strings
        "cbdt_error_summary": str — formatted summary of CBDT errors for UI
        "loop_count"       : int  — how many times the loop-back has triggered
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
            "thread_id":         thread_id,
            "status":            "error",
            "interrupted":       False,
            "interrupt_node":    None,
            "interrupt_message": None,
            "pdf_bytes":         None,
            "flags":             [],
            "blocking_errors":   [],
            "errors":            [f"Pipeline crashed: {str(e)}"],
            "cbdt_error_summary": None,
            "loop_count":        0,
        }

    # ── Check if graph paused at an interrupt node ────────────────────────────
    interrupt_info = _detect_interrupt(thread_id)
    if interrupt_info:
        return {
            "thread_id":         thread_id,
            "status":            "interrupted",
            "interrupted":       True,
            "interrupt_node":    interrupt_info.get("interrupt_node"),
            "interrupt_message": interrupt_info.get("payload"),
            "pdf_bytes":         None,
            "flags":             [],
            "blocking_errors":   [],
            "errors":            [],
            "cbdt_error_summary": None,
            "loop_count":        final_state.get("loop_count", 0),
        }

    # ── Normal completion ─────────────────────────────────────────────────────
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
    Resumes an ITR pipeline that was paused by an interrupt node.

    Handles BOTH interrupt types with the same interface:
      1. cross_validation_node (PAN mismatch):
           corrected_data = {
               "form16_list": [corrected_Form16Schema, ...],
               "form26as":    corrected_Form26ASSchema,
           }

      2. show_errors_node (CBDT Category A errors after loop):
           corrected_data = {
               "user_input":   updated_UserProvidedInfo,
               "form16_list":  [re_uploaded_Form16Schema, ...],  # if docs changed
               "form26as":     re_uploaded_Form26ASSchema,        # if docs changed
           }

    Called by: POST /api/resume

    Parameters
    ----------
    thread_id      : Returned by run_itr_pipeline(). Identifies the paused graph.
    corrected_data : Dict of state keys and their corrected values.
                     Only include fields that actually changed.

    Returns
    -------
    Same dict structure as run_itr_pipeline().
    """
    config = {"configurable": {"thread_id": thread_id}}

    try:
        final_state = app.invoke(
            Command(resume=corrected_data),
            config=config,
        )
    except Exception as e:
        return {
            "thread_id":         thread_id,
            "status":            "error",
            "interrupted":       False,
            "interrupt_node":    None,
            "interrupt_message": None,
            "pdf_bytes":         None,
            "flags":             [],
            "blocking_errors":   [],
            "errors":            [f"Resume crashed: {str(e)}"],
            "cbdt_error_summary": None,
            "loop_count":        0,
        }

    # Check if graph paused again (e.g. another CBDT error after correction)
    interrupt_info = _detect_interrupt(thread_id)
    if interrupt_info:
        return {
            "thread_id":         thread_id,
            "status":            "interrupted",
            "interrupted":       True,
            "interrupt_node":    interrupt_info.get("interrupt_node"),
            "interrupt_message": interrupt_info.get("payload"),
            "pdf_bytes":         None,
            "flags":             [],
            "blocking_errors":   [],
            "errors":            [],
            "cbdt_error_summary": final_state.get("cbdt_error_summary"),
            "loop_count":        final_state.get("loop_count", 0),
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

    Tests only the chatbot path (no documents needed).
    Requires GOOGLE_API_KEY to be set in your environment.

    For ITR pipeline testing, you need real Form16Schema + Form26ASSchema
    objects from Kushal's parser. Test that separately once parsing is ready.
    """
    import os

    print("=" * 60)
    print("TaxSathi — Pipeline Smoke Test")
    print("=" * 60)

    if not os.getenv("GOOGLE_API_KEY"):
        print("\n⚠  GOOGLE_API_KEY is not set.")
        print("   export GOOGLE_API_KEY=your_key_here\n")
    else:
        print("\n[1] Chatbot — single turn")
        result = run_chatbot(
            user_message="What is the standard deduction limit for salaried employees under the new regime?",
        )
        print(f"   Status : {'OK' if not result['errors'] else 'ERRORS'}")
        print(f"   Reply  : {result['response'][:300]}...")
        if result["errors"]:
            print(f"   Errors : {result['errors']}")

        print("\n[2] Chatbot — multi-turn (follow-up question)")
        result2 = run_chatbot(
            user_message="What about under the old regime?",
            conversation_history=[
                {"role": "user",      "content": "What is the standard deduction limit for salaried employees under the new regime?"},
                {"role": "assistant", "content": result["response"]},
            ],
        )
        print(f"   Status : {'OK' if not result2['errors'] else 'ERRORS'}")
        print(f"   Reply  : {result2['response'][:300]}...")

    print("\n" + "=" * 60)
    print("Smoke test complete.")
    print("=" * 60)