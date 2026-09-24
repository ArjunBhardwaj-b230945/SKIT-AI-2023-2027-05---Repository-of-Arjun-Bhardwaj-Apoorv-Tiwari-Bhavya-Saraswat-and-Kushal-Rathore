from fastapi import FastAPI
from dotenv import load_dotenv

from routes.auth import router as auth_router
from routes.protected import router as protected_router


# ============================================================
# Environment Configuration
# ============================================================

# Load environment variables before creating the application.
# This allows authentication configuration to be managed
# outside the source code.
load_dotenv()


# ============================================================
# FastAPI Application
# ============================================================

app = FastAPI(
    title="Authentication and User Management API",
    description=(
        "Backend API providing user registration, "
        "authentication and user management operations."
    ),
    version="1.0.0"
)


# ============================================================
# Route Registration
# ============================================================

# Authentication and user management routes.
app.include_router(
    auth_router
)

# Existing protected routes are kept connected so that the
# current authentication architecture continues to work.
app.include_router(
    protected_router
)


# ============================================================
# Root Endpoint
# ============================================================

@app.get("/")
def home():
    """
    Basic API information endpoint.
    """

    return {
        "success": True,
        "message": "Backend API is running",
        "service": "Authentication and User Management API"
    }


# ============================================================
# Health Check Endpoint
# ============================================================

@app.get("/health")
def health():
    """
    Health endpoint used to verify that the application
    process is running correctly.
    """

    return {
        "success": True,
        "status": "healthy"
    }