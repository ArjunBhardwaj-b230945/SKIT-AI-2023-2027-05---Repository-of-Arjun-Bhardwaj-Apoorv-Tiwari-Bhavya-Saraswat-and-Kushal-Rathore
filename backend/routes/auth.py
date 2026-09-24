from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr

from controllers.auth import (
    signup_user,
    login_user,
    get_user_profile,
    get_all_users,
    update_user,
    delete_user
)


# ============================================================
# Router Configuration
# ============================================================

router = APIRouter(
    prefix="/auth",
    tags=["User Management"]
)


# ============================================================
# Request Models
# ============================================================

class SignupRequest(BaseModel):
    """
    Request body used while registering a new user.
    """

    email: EmailStr
    password: str
    role: str = "user"


class LoginRequest(BaseModel):
    """
    Request body used for user authentication.
    """

    email: EmailStr
    password: str


class UpdateUserRequest(BaseModel):
    """
    Request body used to update basic user information.

    Both fields are optional because the client may update
    either the email, the role, or both.
    """

    email: EmailStr | None = None
    role: str | None = None


# ============================================================
# Registration API
# ============================================================

@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED
)
def signup(data: SignupRequest):
    """
    Register a new user.

    The controller performs validation, duplicate checking,
    password hashing and user creation.
    """

    return signup_user(
        email=data.email,
        password=data.password,
        role=data.role
    )


# ============================================================
# Login API
# ============================================================

@router.post(
    "/login",
    status_code=status.HTTP_200_OK
)
def login(data: LoginRequest):
    """
    Authenticate an existing user and return a JWT token.
    """

    return login_user(
        email=data.email,
        password=data.password
    )


# ============================================================
# Get All Users
# ============================================================

@router.get(
    "/users",
    status_code=status.HTTP_200_OK
)
def get_users():
    """
    Return all registered users.

    Sensitive password information is removed before the
    response is returned.
    """

    return get_all_users()


# ============================================================
# Get User By ID
# ============================================================

@router.get(
    "/users/{user_id}",
    status_code=status.HTTP_200_OK
)
def get_profile(user_id: int):
    """
    Return information for a specific user.
    """

    return get_user_profile(
        user_id
    )


# ============================================================
# Update User
# ============================================================

@router.put(
    "/users/{user_id}",
    status_code=status.HTTP_200_OK
)
def update_profile(
    user_id: int,
    data: UpdateUserRequest
):
    """
    Update basic information for an existing user.
    """

    return update_user(
        user_id=user_id,
        email=data.email,
        role=data.role
    )


# ============================================================
# Delete User
# ============================================================

@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_200_OK
)
def delete_profile(user_id: int):
    """
    Delete a user from the current application storage.
    """

    return delete_user(
        user_id
    )