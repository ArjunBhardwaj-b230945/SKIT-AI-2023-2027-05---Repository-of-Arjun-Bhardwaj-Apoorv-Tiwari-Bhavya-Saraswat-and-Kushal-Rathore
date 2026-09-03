import operator
from typing import TypedDict, Optional, List, Annotated
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command

# ==========================================
# 1. PYDANTIC SCHEMAS (The Data Enforcers)
# ==========================================

class Form16Schema(BaseModel):
    employee_pan: str = Field(description="PAN of the Employee")
    employer_tan: str = Field(description="TAN of the Deductor")
    gross_salary: float = Field(default=0.0)
    total_deductions_via: float = Field(default=0.0, description="Chapter VI-A deductions")

class Form26ASSchema(BaseModel):
    pan: str = Field(description="PAN of the Assessee")
    total_tds: float = Field(default=0.0)

class ITR1Schema(BaseModel):
    pan: str
    taxable_total_income: float = Field(default=0.0)
    refund_or_payable: float = Field(default=0.0)

# ==========================================
# 2. STATE DEFINITION (The Shared Memory)
# ==========================================

class AgentState(TypedDict):
    # Annotated with operator.add so messages append instead of overwrite
    messages: Annotated[List[dict], operator.add]
    form16_data: Optional[Form16Schema]
    form26as_data: Optional[Form26ASSchema]
    itr1_data: Optional[ITR1Schema]
    errors: List[str]

# ==========================================
# 3. NODES (The Workers)
# ==========================================

def qna_node(state: AgentState):
    """Handles general conversational questions."""
    # In reality, you'd call an LLM here with state["messages"]
    response = {"role": "assistant", "content": "I am answering your tax question."}
    return {"messages": [response]}

def validate_documents_node(state: AgentState):
    """Strictly validates extracted documents. Triggers HITL if PANs mismatch."""
    f16 = state.get("form16_data")
    f26 = state.get("form26as_data")
    
    # Edge Case: Both documents must exist to validate
    if not f16 or not f26:
        return {"errors": ["Missing one or both documents for validation."]}

    # The Fatal Error Check
    if f16.employee_pan != f26.pan:
        # Halt execution dynamically and ask human for help
        human_correction = interrupt(
            payload="PAN Mismatch Detected. Form 16 PAN does not match Form 26AS. Please upload correct documents."
        )
        # When resumed, overwrite the bad data with the human's correction
        return {
            "form16_data": human_correction.get("form16_data", f16),
            "form26as_data": human_correction.get("form26as_data", f26),
            "errors": [] # Clear errors upon successful correction
        }
        
    return {"errors": []}

def compute_itr_node(state: AgentState):
    """Deterministically maps data to ITR-1. No LLM guessing here."""
    f16 = state["form16_data"]
    f26 = state["form26as_data"]
    
    # Basic algorithmic mapping (B4 - C19 logic)
    taxable_income = f16.gross_salary - f16.total_deductions_via
    
    # Dummy tax calculation for architecture demonstration
    assumed_tax = taxable_income * 0.10 
    refund = f26.total_tds - assumed_tax
    
    itr = ITR1Schema(
        pan=f16.employee_pan,
        taxable_total_income=taxable_income,
        refund_or_payable=refund
    )
    return {"itr1_data": itr}

def respond_itr_node(state: AgentState):
    """Generates final response after ITR computation."""
    itr = state["itr1_data"]
    msg = f"Your ITR-1 is computed. Taxable Income: {itr.taxable_total_income}, Refund: {itr.refund_or_payable}"
    return {"messages": [{"role": "assistant", "content": msg}]}

# ==========================================
# 4. ROUTING LOGIC (The Traffic Controller)
# ==========================================

def route_initial_intent(state: AgentState):
    """Decides where the graph goes right after START."""
    latest_message = state["messages"][-1]["content"].lower()
    
    # If the external service injected document data, route to strict processing
    if state.get("form16_data") and state.get("form26as_data"):
        return "validate_documents"
        
    # If it's a conversational prompt
    if "how" in latest_message or "what" in latest_message or "explain" in latest_message:
        return "qna"
        
    return "qna" # Defaulting to QnA for safety

def route_after_validation(state: AgentState):
    """Checks if validation passed before computing."""
    if len(state.get("errors", [])) > 0:
        return END # Or route to a dedicated error handler node
    return "compute_itr"

# ==========================================
# 5. GRAPH COMPILATION 
# ==========================================

workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("qna", qna_node)
workflow.add_node("validate_documents", validate_documents_node)
workflow.add_node("compute_itr", compute_itr_node)
workflow.add_node("respond_itr", respond_itr_node)

# Add Edges
workflow.add_conditional_edges(START, route_initial_intent)
workflow.add_edge("qna", END)
workflow.add_conditional_edges("validate_documents", route_after_validation)
workflow.add_edge("compute_itr", "respond_itr")
workflow.add_edge("respond_itr", END)

# Compile (Requires a checkpointer in production for interrupts to work)
# from langgraph.checkpoint.memory import MemorySaver
# memory = MemorySaver()
# app = workflow.compile(checkpointer=memory)