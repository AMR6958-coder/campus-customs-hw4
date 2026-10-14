"""Account creation, login, logout, and the current-user lookup.

Sessions are kept in a signed, HttpOnly cookie managed by Starlette's
SessionMiddleware (configured in main.py). After a successful login or
sign-up we store only the user's id in that cookie. On each request the
``get_current_user`` dependency reads the id back and loads the user row.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from db import DB
from models import UserOut
from security import DUMMY_HASH, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_USER_KEY = "user_id"

# The store owner's account: the one that receives inventory notes. Set
# OWNER_EMAIL in backend/.env to use a different account.
DEFAULT_OWNER_EMAIL = "test@campuscustoms.yale.edu"


def owner_email() -> str:
    return os.getenv("OWNER_EMAIL", DEFAULT_OWNER_EMAIL).strip().lower()


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


def _normalize_email(value: str) -> str:
    value = value.strip().lower()
    local, at, domain = value.partition("@")
    if not at or not local or "." not in domain:
        raise ValueError("must be a valid email address")
    return value


class RegisterRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("first_name", "last_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("email")
    @classmethod
    def _clean_email(cls, value: str) -> str:
        return _normalize_email(value)


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _clean_email(cls, value: str) -> str:
        return _normalize_email(value)


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------


def _row_to_user(row: sqlite3.Row) -> UserOut:
    first, last = row["first_name"], row["last_name"]
    if not first and not last:
        # Older rows may only have the combined ``name`` column filled in.
        parts = (row["name"] or "").split(" ", 1)
        first = parts[0]
        last = parts[1] if len(parts) > 1 else ""
    return UserOut(
        id=row["id"],
        first_name=first or "",
        last_name=last or "",
        email=row["email"],
        created_at=row["created_at"],
        is_owner=row["email"].strip().lower() == owner_email(),
    )


def find_user_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def find_user_by_id(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def create_user(conn: sqlite3.Connection, data: RegisterRequest) -> UserOut:
    """Insert a new user. The password is hashed here and never stored as typed."""
    password_hash = hash_password(data.password)
    full_name = f"{data.first_name} {data.last_name}"
    try:
        cursor = conn.execute(
            """
            INSERT INTO users (name, email, password_hash, first_name, last_name)
            VALUES (?, ?, ?, ?, ?)
            """,
            (full_name, data.email, password_hash, data.first_name, data.last_name),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:  # UNIQUE constraint on email
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        ) from exc
    row = find_user_by_id(conn, cursor.lastrowid)
    assert row is not None
    return _row_to_user(row)


# --------------------------------------------------------------------------
# Current-user dependencies
# --------------------------------------------------------------------------


def get_current_user(request: Request, conn: DB) -> UserOut:
    """Dependency that requires a logged-in user (401 otherwise)."""
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in.")
    row = find_user_by_id(conn, user_id)
    if row is None:
        # The account was deleted after the cookie was issued.
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in.")
    return _row_to_user(row)


def get_optional_user(request: Request, conn: DB) -> UserOut | None:
    """Dependency that returns the user if logged in, else None."""
    try:
        return get_current_user(request, conn)
    except HTTPException:
        return None


CurrentUser = Annotated[UserOut, Depends(get_current_user)]
OptionalUser = Annotated[UserOut | None, Depends(get_optional_user)]


def require_owner(user: CurrentUser) -> UserOut:
    """Dependency for owner-only routes (inventory notes). 403 for anyone else."""
    if not user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This page is for the store owner.")
    return user


Owner = Annotated[UserOut, Depends(require_owner)]


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, request: Request, conn: DB) -> UserOut:
    if find_user_by_email(conn, data.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )
    user = create_user(conn, data)
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id  # log the new user in
    return user


@router.post("/login", response_model=UserOut)
def login(data: LoginRequest, request: Request, conn: DB) -> UserOut:
    row = find_user_by_email(conn, data.email)
    # Always run exactly one hash so the timing is the same whether or not
    # the email exists. See DUMMY_HASH in security.py.
    stored_hash = row["password_hash"] if row is not None else DUMMY_HASH
    password_ok = verify_password(data.password, stored_hash)
    if row is None or not password_ok:
        # One generic message: never reveal which half was wrong.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )
    request.session.clear()
    request.session[SESSION_USER_KEY] = row["id"]
    return _row_to_user(row)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> None:
    request.session.clear()


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return user
