import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError, jwt
from passlib.context import CryptContext


# ============================================================
# Password Configuration
# ============================================================

# bcrypt is used for storing passwords securely.
# The original password is never stored directly in the
# application user storage.
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


# ============================================================
# JWT Configuration
# ============================================================

# These values can later be moved completely to environment
# variables when the deployment configuration is finalized.
JWT_SECRET = os.getenv(
    "JWT_SECRET",
    "development_secret"
)

JWT_ALGORITHM = os.getenv(
    "JWT_ALGORITHM",
    "HS256"
)

JWT_EXPIRES_MINUTES = int(
    os.getenv(
        "JWT_EXPIRES_MINUTES",
        "60"
    )
)


# ============================================================
# Temporary User Storage
# ============================================================

# At this stage of the project, users are intentionally kept
# in memory. PostgreSQL integration will be implemented during
# the Database Integration phase.
users = []

# This counter provides unique user IDs during the current
# application session.
next_user_id = 1


# ============================================================
# General User Utilities
# ============================================================

def normalize_email(email: str) -> str:
    """
    Normalize an email address before storing or searching it.

    This prevents situations where:
        Apoorv@gmail.com
        apoorv@gmail.com
        APOORV@GMAIL.COM

    are treated as different users.
    """

    return email.strip().lower()


def is_valid_email_format(email: str) -> bool:
    """
    Perform a basic defensive email validation.

    FastAPI's EmailStr already performs validation at the API
    layer, but this additional check keeps the controller safe
    when its functions are called directly.
    """

    normalized_email = normalize_email(email)

    if "@" not in normalized_email:
        return False

    domain = normalized_email.split("@")[-1]

    if "." not in domain:
        return False

    return True


def validate_password(password: str) -> None:
    """
    Validate password requirements before registration.
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


def validate_user_data(
    email: str,
    password: str
) -> None:
    """
    Validate data required for creating or updating a user.
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
# Password Handling
# ============================================================

def hash_password(password: str) -> str:
    """
    Convert a plain-text password into a bcrypt hash.
    """

    return pwd_context.hash(password)


def verify_password(
    password: str,
    hashed_password: str
) -> bool:
    """
    Compare a plain-text password with the stored hash.
    """

    return pwd_context.verify(
        password,
        hashed_password
    )


# ============================================================
# User Lookup Functions
# ============================================================

def find_user_by_email(email: str):
    """
    Search for a user using a normalized email address.
    """

    normalized_email = normalize_email(email)

    for user in users:
        if user["email"] == normalized_email:
            return user

    return None


def find_user_by_id(user_id: int):
    """
    Search for a user using the numeric user ID.
    """

    for user in users:
        if user["id"] == user_id:
            return user

    return None


# ============================================================
# User Serialization
# ============================================================

def serialize_user(user: dict) -> dict:
    """
    Return only safe user information.

    Password hashes are deliberately excluded from every
    normal API response.
    """

    return {
        "id": user["id"],
        "email": user["email"],
        "role": user["role"]
    }


def serialize_users(user_list: list) -> list:
    """
    Serialize multiple users using the same safe format.
    """

    return [
        serialize_user(user)
        for user in user_list
    ]


# ============================================================
# User Registration
# ============================================================

def create_user(
    email: str,
    password: str,
    role: str = "user"
):
    """
    Create a new user in temporary in-memory storage.
    """

    global next_user_id

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

    # Only supported roles are accepted at this stage.
    # More detailed authorization rules will be handled later.
    if role not in ["user", "admin"]:
        role = "user"

    hashed_password = hash_password(password)

    user = {
        "id": next_user_id,
        "email": email,
        "password": hashed_password,
        "role": role
    }

    users.append(user)

    next_user_id += 1

    return user


def signup_user(
    email: str,
    password: str,
    role: str = "user"
):
    """
    Public registration operation used by the route layer.
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
# JWT Token Handling
# ============================================================

def create_access_token(user: dict) -> str:
    """
    Create an access token after successful authentication.

    The token contains basic user information required by the
    authentication middleware.
    """

    expiration_time = (
        datetime.now(timezone.utc)
        + timedelta(
            minutes=JWT_EXPIRES_MINUTES
        )
    )

    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "exp": expiration_time
    }

    token = jwt.encode(
        payload,
        JWT_SECRET,
        algorithm=JWT_ALGORITHM
    )

    return token


# ============================================================
# User Login
# ============================================================

def login_user(
    email: str,
    password: str
):
    """
    Authenticate an existing user.

    The password provided by the client is compared against
    the bcrypt hash stored for that user.
    """

    normalized_email = normalize_email(email)

    if not normalized_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required"
        )

    if not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password is required"
        )

    user = find_user_by_email(
        normalized_email
    )

    # Do not reveal whether the email exists or the password
    # was incorrect through separate messages.
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    password_valid = verify_password(
        password,
        user["password"]
    )

    if not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    access_token = create_access_token(
        user
    )

    return {
        "success": True,
        "message": "Login successful",
        "access_token": access_token,
        "token_type": "bearer",
        "user": serialize_user(user)
    }


# ============================================================
# User Retrieval
# ============================================================

def get_user_profile(user_id: int):
    """
    Retrieve one user using the user ID.
    """

    user = find_user_by_id(
        user_id
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return {
        "success": True,
        "user": serialize_user(user)
    }


def get_all_users():
    """
    Retrieve all registered users.

    Password information is excluded through serialization.
    """

    safe_users = serialize_users(
        users
    )

    return {
        "success": True,
        "count": len(safe_users),
        "users": safe_users
    }


# ============================================================
# User Update
# ============================================================

def update_user(
    user_id: int,
    email: str | None = None,
    role: str | None = None
):
    """
    Update basic user information.

    Password updates are intentionally handled separately so
    that future password-management logic can have its own
    validation and security requirements.
    """

    user = find_user_by_id(
        user_id
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if email is not None:
        normalized_email = normalize_email(
            email
        )

        if not is_valid_email_format(
            normalized_email
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email format"
            )

        existing_user = find_user_by_email(
            normalized_email
        )

        if (
            existing_user
            and existing_user["id"] != user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email is already registered"
            )

        user["email"] = normalized_email

    if role is not None:

        if role not in ["user", "admin"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid role"
            )

        user["role"] = role

    return {
        "success": True,
        "message": "User updated successfully",
        "user": serialize_user(user)
    }


# ============================================================
# User Deletion
# ============================================================

def delete_user(user_id: int):
    """
    Delete an existing user from temporary storage.
    """

    user = find_user_by_id(
        user_id
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    users.remove(user)

    return {
        "success": True,
        "message": "User deleted successfully",
        "user_id": user_id
    }