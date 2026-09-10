from datetime import datetime, timedelta, timezone
import os

from dotenv import load_dotenv
from fastapi import HTTPException, status
from jose import jwt
from passlib.context import CryptContext

load_dotenv()

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

JWT_SECRET = os.getenv(
    "JWT_SECRET",
    "development_secret"
)

JWT_ALGORITHM = os.getenv(
    "JWT_ALGORITHM",
    "HS256"
)

JWT_EXPIRES_MINUTES = int(
    os.getenv("JWT_EXPIRES_MINUTES", "60")
)

# Temporary in-memory user storage
users = []


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str):
    return pwd_context.verify(password, hashed_password)


def create_access_token(user):
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=JWT_EXPIRES_MINUTES
    )

    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "exp": expire
    }

    token = jwt.encode(
        payload,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )

    return token


def signup_user(
    email: str,
    password: str,
    role: str = "user"
):
    email = email.strip().lower()

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email and password are required"
        )

    if len(password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least 6 characters"
        )

    existing_user = next(
        (user for user in users if user["email"] == email),
        None
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists"
        )

    if role not in ["user", "admin"]:
        role = "user"

    user = {
        "id": len(users) + 1,
        "email": email,
        "password": hash_password(password),
        "role": role
    }

    users.append(user)

    token = create_access_token(user)

    return {
        "success": True,
        "message": "Signup successful",
        "token": token
    }


def signin_user(email: str, password: str):
    email = email.strip().lower()

    user = next(
        (user for user in users if user["email"] == email),
        None
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    if not verify_password(password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    token = create_access_token(user)

    return {
        "success": True,
        "message": "Signin successful",
        "token": token
    }