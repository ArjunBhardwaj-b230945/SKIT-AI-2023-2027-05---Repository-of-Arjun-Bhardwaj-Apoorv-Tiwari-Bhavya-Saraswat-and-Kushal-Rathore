"""
pipeline/__init__.py
================================================================================
TaxSathi LangGraph pipeline package.

Public API — import these in Apoorv's FastAPI routers:

    from pipeline import run_chatbot, run_itr_pipeline, resume_pipeline

FastAPI usage example:

    # POST /api/chat
    @router.post("/chat")
    async def chat(req: ChatRequest):
        result = run_chatbot(
            user_message=req.message,
            conversation_history=req.history,
            session_id=req.session_id,
        )
        return result

    # POST /api/generate-itr
    @router.post("/generate-itr")
    async def generate_itr(req: ITRRequest):
        result = run_itr_pipeline(
            form16_list=req.form16_list,
            form26as=req.form26as,
            user_input=req.user_input,
            filing_date_str=req.filing_date,
        )
        # Store result["thread_id"] in session — needed for resume
        return result

    # POST /api/resume
    @router.post("/resume")
    async def resume(req: ResumeRequest):
        result = resume_pipeline(
            thread_id=req.thread_id,
            corrected_data=req.corrected_data,
        )
        return result

INTERRUPT HANDLING GUIDE FOR APOORV
-------------------------------------
When run_itr_pipeline() or resume_pipeline() returns:
    { "status": "interrupted", "interrupted": True, ... }

The graph is paused. Steps:
  1. Show interrupt_message to the user in the frontend.
  2. Collect corrected input from the user.
  3. Call resume_pipeline(thread_id, corrected_data) to continue.
  4. Repeat until status == "complete" or "error".
================================================================================
"""


from pipeline.main import (
    resume_pipeline,
    run_chatbot,
    run_itr_pipeline,
)

__all__ = [
    "run_chatbot",
    "run_itr_pipeline",
    "resume_pipeline",
]
