from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from controllers.auth import (
    signup_user,
    get_user_profile
)


# ============================================================
# Authentication Router
# ============================================================

router = APIRouter(
    prefix="/auth",
    tags=["User Management"]
)


# ============================================================
# Request Schemas
# ============================================================

class SignupRequest(BaseModel):
    """
    Request structure used for user registration.
    """

    email: EmailStr
    password: str
    role: str = "user"


class UserProfileRequest(BaseModel):
    """
    Request structure for retrieving a user profile.
    """

    user_id: int


# ============================================================
# User Registration API
# ============================================================

@router.post("/signup")
def signup(data: SignupRequest):
    """
    Register a new user.
    """

    return signup_user(
        email=data.email,
        password=data.password,
        role=data.role
    )


# ============================================================
# Basic User Profile API
# ============================================================

@router.get("/users/{user_id}")
def get_profile(user_id: int):
    """
    Retrieve basic information about a registered user.
    """

    return get_user_profile(user_id)