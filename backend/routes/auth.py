from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from controllers.auth import signup_user, signin_user


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    role: str = "user"


class SigninRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/signup")
def signup(data: SignupRequest):
    return signup_user(
        data.email,
        data.password,
        data.role
    )


@router.post("/signin")
def signin(data: SigninRequest):
    return signin_user(
        data.email,
        data.password
    )