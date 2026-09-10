from fastapi import APIRouter, Depends

from middleware.auth import (
    authenticate_token,
    authorize_role
)


router = APIRouter(
    prefix="/api",
    tags=["Protected Routes"]
)


@router.get("/profile")
def profile(
    current_user=Depends(authenticate_token)
):
    return {
        "success": True,
        "message": "Protected profile accessed",
        "user": current_user
    }


@router.get("/dashboard")
def dashboard(
    current_user=Depends(authenticate_token)
):
    return {
        "success": True,
        "message": "Dashboard accessed successfully",
        "user": current_user
    }


@router.get("/admin")
def admin_dashboard(
    current_user=Depends(
        authorize_role("admin")
    )
):
    return {
        "success": True,
        "message": "Admin dashboard accessed",
        "user": current_user
    }