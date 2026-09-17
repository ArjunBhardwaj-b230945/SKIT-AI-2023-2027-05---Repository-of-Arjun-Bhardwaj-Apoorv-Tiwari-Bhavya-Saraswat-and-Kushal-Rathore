from fastapi import HTTPException, status
from passlib.context import CryptContext


# ============================================================
# Password Configuration
# ============================================================

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


# ============================================================
# Temporary User Storage
# ============================================================

# Temporary in-memory storage for the initial user-management
# implementation. PostgreSQL integration will be added later.
users = []


# ============================================================
# Email Utility Functions
# ============================================================

def normalize_email(email: str) -> str:
    """
    Normalize an email address before storing it.
    """

    return email.strip().lower()


def is_valid_email_format(email: str) -> bool:
    """
    Perform a basic email format check.

    Detailed email validation is handled by Pydantic
    through EmailStr at the API layer.
    """

    email = normalize_email(email)

    return (
        "@" in email
        and "." in email.split("@")[-1]
    )


# ============================================================
# Password Validation
# ============================================================

def validate_password(password: str) -> None:
    """
    Validate the basic password requirements.
    """

    if not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is required"
        )

    if len(password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must contain at least 6 characters"
        )


# ============================================================
# Password Security
# ============================================================

def hash_password(password: str) -> str:
    """
    Generate a secure password hash.

    Plain-text passwords are never stored in the user
    collection.
    """

    return pwd_context.hash(password)


def verify_password(
    password: str,
    hashed_password: str
) -> bool:
    """
    Verify a password against its stored hash.
    """

    return pwd_context.verify(
        password,
        hashed_password
    )


# ============================================================
# User Search Functions
# ============================================================

def find_user_by_email(email: str):
    """
    Search for a user using their email address.
    """

    normalized_email = normalize_email(email)

    for user in users:

        if user["email"] == normalized_email:
            return user

    return None


def find_user_by_id(user_id: int):
    """
    Search for a user using their unique identifier.
    """

    for user in users:

        if user["id"] == user_id:
            return user

    return None


# ============================================================
# User Validation
# ============================================================

def validate_user_data(
    email: str,
    password: str
) -> None:
    """
    Validate the information received during registration.
    """

    normalized_email = normalize_email(email)

    if not normalized_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required"
        )

    if not is_valid_email_format(normalized_email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format"
        )

    validate_password(password)


# ============================================================
# User Creation
# ============================================================

def create_user(
    email: str,
    password: str,
    role: str = "user"
):
    """
    Create a new user and store the user temporarily.

    Database persistence will be introduced during the
    Database Integration phase.
    """

    email = normalize_email(email)

    validate_user_data(
        email,
        password
    )

    existing_user = find_user_by_email(email)

    if existing_user:

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists"
        )

    if role not in ["user", "admin"]:

        role = "user"

    user_id = len(users) + 1

    hashed_password = hash_password(password)

    user = {
        "id": user_id,
        "email": email,
        "password": hashed_password,
        "role": role
    }

    users.append(user)

    return user


# ============================================================
# Public User Response
# ============================================================

def serialize_user(user: dict) -> dict:
    """
    Convert internal user data into a safe API response.

    Password hashes are intentionally excluded.
    """

    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"]
    }


# ============================================================
# User Registration
# ============================================================

def signup_user(
    email: str,
    password: str,
    role: str = "user"
):
    """
    Register a new user.
    """

    user = create_user(
        email=email,
        password=password,
        role=role
    )

    return {
        "success": True,
        "message": "User registered successfully",
        "user": serialize_user(user)
    }


# ============================================================
# Basic User Retrieval
# ============================================================

def get_user_profile(user_id: int):
    """
    Retrieve basic information for a registered user.
    """

    user = find_user_by_id(user_id)

    if not user:

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return serialize_user(user)