"""Database access shared by the API modules."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from fastapi import Depends

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "campus_customs.db"
PRODUCT_IMAGE_DIR = DATA_DIR / "products"


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: open a connection per request and close it after.

    ``check_same_thread=False`` is needed because FastAPI may run this
    dependency and the endpoint that uses it on different worker threads.
    That is safe here because the connection lives for a single request and
    is never shared between requests.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["name"]
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


# Type alias so endpoints can declare ``conn: DB`` to receive a connection.
DB = Annotated[sqlite3.Connection, Depends(get_db)]
