from fastapi import FastAPI
from dotenv import load_dotenv

from routes.auth import router as auth_router
from routes.protected import router as protected_router

load_dotenv()

app = FastAPI(
    title="Authentication API",
    description="JWT Authentication and Authorization System",
    version="1.0.0"
)

app.include_router(auth_router)
app.include_router(protected_router)


@app.get("/")
def home():
    return {
        "success": True,
        "message": "Authentication API is running"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }