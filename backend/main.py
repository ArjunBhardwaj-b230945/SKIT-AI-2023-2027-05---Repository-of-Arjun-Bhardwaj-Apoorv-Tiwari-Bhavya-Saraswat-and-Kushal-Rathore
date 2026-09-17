from fastapi import FastAPI
from dotenv import load_dotenv

from routes.auth import router as auth_router
from routes.protected import router as protected_router


# ============================================================
# Environment Configuration
# ============================================================

load_dotenv()


# ============================================================
# FastAPI Application
# ============================================================

app = FastAPI(
    title="Authentication and User Management API",
    description="Backend API for authentication and user management",
    version="1.0.0"
)


# ============================================================
# Route Registration
# ============================================================

app.include_router(auth_router)

app.include_router(protected_router)


# ============================================================
# Application Health
# ============================================================

@app.get("/")
def home():
    """
    Root endpoint used to verify that the application is running.
    """

    return {
        "success": True,
        "message": "Backend API is running"
    }


@app.get("/health")
def health():
    """
    Health-check endpoint.
    """

    return {
        "success": True,
        "status": "healthy"
    }