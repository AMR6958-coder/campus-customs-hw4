"""Campus Customs back end.

A FastAPI application that serves the product catalogue, product images,
user accounts, and the PydanticAI shopping assistant.

Run from the ``backend`` folder with the virtual environment active::

    uvicorn main:app --reload --port 8000

The front end's Vite dev server proxies ``/api`` and ``/media`` here.

Module map:
    main.py      this file: app setup and the product / chat routes
    auth.py      register, login, logout, current user
    agent.py     the PydanticAI agent and its tools
    tools.py     catalogue and inventory lookups (used by routes and the agent)
    models.py    Pydantic schemas shared by all of the above
    db.py        paths and the per-request SQLite connection
    security.py  password hashing
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import inventory
import tools
from agent import AgentNotConfigured, ShopDeps, run_agent
from auth import CurrentUser, OptionalUser, Owner
from auth import router as auth_router
from db import BACKEND_DIR, DB, DB_PATH, PRODUCT_IMAGE_DIR
from inventory_agent import run_review
from models import (
    ChatHistoryMessage,
    ChatRequest,
    ChatResponse,
    ChatTurn,
    InventoryReport,
    OwnerNote,
    Product,
    ProductCard,
    ProductEventIn,
    ReviewResult,
    UserOut,
)

logger = logging.getLogger("campus_customs")

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

load_dotenv(BACKEND_DIR / ".env", override=True)  # project .env beats inherited env vars

# Signs the session cookie so it cannot be forged. Keep it secret and stable;
# if it changes, every existing login is invalidated.
SESSION_SECRET = os.environ.get("SESSION_SECRET")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)
    print("WARNING: SESSION_SECRET is not set; using a temporary key. Logins will not survive a restart.")

SESSION_COOKIE_NAME = "campus_session"
SESSION_MAX_AGE_SECONDS = 14 * 24 * 60 * 60  # two weeks

# --------------------------------------------------------------------------
# App setup
# --------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Create the inventory-tracking tables if they do not exist yet."""
    conn = sqlite3.connect(DB_PATH)
    try:
        inventory.ensure_schema(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="Campus Customs API", version="0.4.0", lifespan=lifespan)

# Signed, HttpOnly session cookie. JavaScript in the browser cannot read it,
# and the signature stops anyone from editing the user id inside it.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie=SESSION_COOKIE_NAME,
    max_age=SESSION_MAX_AGE_SECONDS,
    same_site="lax",
    https_only=False,  # set True when served over HTTPS
)

# Allow the Vite dev server to call this API directly (useful if the proxy is
# not used). Tighten this list before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the product photos straight from the data folder.
app.mount(tools.MEDIA_URL_PREFIX, StaticFiles(directory=PRODUCT_IMAGE_DIR), name="product-images")

# Account routes live in auth.py.
app.include_router(auth_router)


# --------------------------------------------------------------------------
# Health and products
# --------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"status": "ok", "database_found": DB_PATH.exists()}


@app.get("/api/products", response_model=list[Product])
def list_products(conn: DB) -> list[Product]:
    return tools.fetch_products(conn)


@app.get("/api/products/{product_id}", response_model=Product)
def get_product(product_id: str, conn: DB) -> Product:
    product = tools.get_product(conn, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")
    return product


# --------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------


def _load_saved_turns(conn: sqlite3.Connection, user_id: int, limit: int) -> list[ChatTurn]:
    """The most recent messages for a user, oldest first, with the products each showed."""
    rows = conn.execute(
        "SELECT role, content, products_json FROM chat_messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [
        ChatTurn(
            role=row["role"],
            content=row["content"],
            product_ids=tools.product_ids_from_json(row["products_json"]),
        )
        for row in reversed(rows)
    ]


def _save_turn(conn: sqlite3.Connection, user_id: int, user_message: str, reply: str, products: list[Product]) -> None:
    """Persist one exchange so the assistant remembers it next time."""
    products_json = json.dumps([p.model_dump() for p in products])
    conn.execute(
        "INSERT INTO chat_messages (user_id, role, content, products_json) VALUES (?, ?, ?, ?)",
        (user_id, "user", user_message, None),
    )
    conn.execute(
        "INSERT INTO chat_messages (user_id, role, content, products_json) VALUES (?, ?, ?, ?)",
        (user_id, "assistant", reply, products_json),
    )
    conn.commit()


def _parse_products_json(raw: str | None) -> list[ProductCard]:
    """Saved rows hold full Product records (the seed data's format); return cards."""
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    cards: list[ProductCard] = []
    for item in items if isinstance(items, list) else []:
        try:
            cards.append(ProductCard.from_product(Product.model_validate(item)))
        except ValueError:
            continue
    return cards


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, user: OptionalUser, conn: DB) -> ChatResponse:
    """One turn of conversation with the shopping assistant.

    The reply comes from the PydanticAI agent in agent.py. Along with the text
    the response carries the full product records the page should display and
    the current user, so the front end has everything it needs in one call.
    """
    # Logged-in shoppers get server-side memory; anonymous ones send their own.
    history = _load_saved_turns(conn, user.id, limit=20) if user else body.history

    # Products shown most recently: from the saved record for logged-in shoppers
    # (reaches back beyond the 20-message window), else from the sent history.
    recent_ids = tools.recent_product_ids_for_user(conn, user.id) if user else []

    deps = ShopDeps(
        conn=conn,
        user=user,
        current_product_id=body.product_id,
        recent_product_ids=recent_ids,
        language=body.language,
    )

    try:
        output = await run_agent(body.message, deps, history)
    except AgentNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # network trouble, gateway errors, bad model output
        logger.exception("Agent run failed")
        raise HTTPException(
            status_code=502,
            detail="The assistant is having trouble right now. Please try again in a moment.",
        ) from exc

    # Only real catalogue items make it to the page, in the assistant's order.
    products = tools.fetch_products_in_order(conn, output.product_ids)

    if user:
        _save_turn(conn, user.id, body.message, output.reply, products)

    cards = [ProductCard.from_product(p) for p in products]
    return ChatResponse(reply=output.reply, products=cards, user=user)


@app.get("/api/chat/history", response_model=list[ChatHistoryMessage])
def chat_history(user: CurrentUser, conn: DB, limit: int = Query(default=50, ge=1, le=200)) -> list[ChatHistoryMessage]:
    """A logged-in shopper's saved conversation, oldest first."""
    rows = conn.execute(
        "SELECT id, role, content, products_json, created_at FROM chat_messages "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user.id, limit),
    ).fetchall()
    return [
        ChatHistoryMessage(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            products=_parse_products_json(row["products_json"]),
            created_at=row["created_at"],
        )
        for row in reversed(rows)
    ]


# --------------------------------------------------------------------------
# Product events (views, clicks, add-to-carts)
# --------------------------------------------------------------------------


@app.post("/api/events", status_code=204)
def track_event(body: ProductEventIn, user: OptionalUser, conn: DB) -> None:
    """Record one shopper interaction with a product. Sent by the browser."""
    recorded = inventory.record_event(
        conn,
        body.product_id,
        body.event_type,
        size=body.size,
        quantity=body.quantity,
        user_id=user.id if user else None,
    )
    if not recorded:
        raise HTTPException(status_code=404, detail=f"Product '{body.product_id}' not found")


# --------------------------------------------------------------------------
# Owner: inventory report, notes, and reviews
# --------------------------------------------------------------------------


@app.get("/api/owner/report", response_model=InventoryReport)
def owner_report(_: Owner, conn: DB) -> InventoryReport:
    """Low-stock sizes and per-product engagement, with the flags the rules produce."""
    return inventory.build_report(conn)


@app.get("/api/owner/notes", response_model=list[OwnerNote])
def owner_notes(_: Owner, conn: DB, include_resolved: bool = False) -> list[OwnerNote]:
    return inventory.list_notes(conn, include_resolved=include_resolved)


@app.post("/api/owner/notes/{note_id}/resolve", response_model=OwnerNote)
def owner_resolve_note(note_id: int, _: Owner, conn: DB) -> OwnerNote:
    note = inventory.resolve_note(conn, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@app.post("/api/owner/review", response_model=ReviewResult)
async def owner_review(_: Owner, conn: DB) -> ReviewResult:
    """Run the inventory assistant: it reads the report and sends any notes the rules call for."""
    try:
        return await run_review(conn)
    except Exception as exc:
        logger.exception("Inventory review failed")
        raise HTTPException(status_code=502, detail="The inventory review failed. Please try again.") from exc


# Re-exported for type checkers and anyone importing from main.
__all__ = ["app", "UserOut"]
