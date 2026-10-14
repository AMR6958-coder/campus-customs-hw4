"""Inventory tracking: product events, the stock and engagement rules, and
the owner's notes.

Two tables are added to campus_customs.db on startup (the instructor's
tables are untouched):

    product_events  one row per shopper interaction (view, click, add_to_cart, order)
    owner_notes     notes the inventory assistant sends the store owner

The rules live here, in plain Python, so they can be read and tested without
a model:

* Reorder line: a size is low when its quantity is at or below
  REORDER_THRESHOLD (20%) of PAR_LEVEL (25 units, the full count in the data).
* Viewed but not ordered: a product with at least MIN_VIEWS_TO_FLAG views or
  clicks in the last ENGAGEMENT_WINDOW_DAYS and zero add-to-cart units.

In this sample store checkout is a demo, so add_to_cart is the order signal.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

from db import PROJECT_ROOT
from models import EngagementLine, InventoryReport, LowStockLine, OwnerNote

PAR_LEVEL = int(os.getenv("INVENTORY_PAR_LEVEL", "25"))
REORDER_THRESHOLD = float(os.getenv("INVENTORY_REORDER_THRESHOLD", "0.20"))
ENGAGEMENT_WINDOW_DAYS = int(os.getenv("INVENTORY_WINDOW_DAYS", "30"))
MIN_VIEWS_TO_FLAG = int(os.getenv("INVENTORY_MIN_VIEWS", "5"))
# One review sends at most this many notes of each kind; the rest wait for the next review.
MAX_NOTES_PER_REVIEW = int(os.getenv("INVENTORY_MAX_NOTES_PER_REVIEW", "10"))

# Every note is also appended here, as a plain-text "note out to the owner".
INBOX_PATH = PROJECT_ROOT / "output" / "owner_inbox.md"

EVENT_TYPES = ("view", "click", "add_to_cart", "order")
NOTE_KINDS = ("reorder", "do_not_reorder")
SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL"]


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS product_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL REFERENCES catalogue(product_id),
            event_type TEXT NOT NULL,
            size TEXT,
            quantity INTEGER NOT NULL DEFAULT 1,
            user_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_product_events_product
            ON product_events(product_id, event_type, created_at);

        CREATE TABLE IF NOT EXISTS owner_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            product_id TEXT NOT NULL REFERENCES catalogue(product_id),
            size TEXT,
            message TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


def record_event(
    conn: sqlite3.Connection,
    product_id: str,
    event_type: str,
    size: str | None = None,
    quantity: int = 1,
    user_id: int | None = None,
) -> bool:
    """Store one interaction. Returns False if the product does not exist."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type {event_type!r}")
    exists = conn.execute("SELECT 1 FROM catalogue WHERE product_id = ?", (product_id,)).fetchone()
    if exists is None:
        return False
    conn.execute(
        "INSERT INTO product_events (product_id, event_type, size, quantity, user_id) VALUES (?, ?, ?, ?, ?)",
        (product_id, event_type, size.upper() if size else None, max(1, quantity), user_id),
    )
    conn.commit()
    return True


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------


def reorder_line_units() -> int:
    """Quantity at or below which a size needs reordering (20% of 25 = 5)."""
    return int(PAR_LEVEL * REORDER_THRESHOLD)


def low_stock_lines(conn: sqlite3.Connection) -> list[LowStockLine]:
    rows = conn.execute(
        """
        SELECT i.product_id, c.name, i.size, i.quantity
        FROM inventory i JOIN catalogue c ON c.product_id = i.product_id
        WHERE i.quantity <= ?
        ORDER BY c.name
        """,
        (reorder_line_units(),),
    ).fetchall()
    lines = [
        LowStockLine(
            product_id=r["product_id"],
            name=r["name"],
            size=r["size"],
            quantity=r["quantity"],
            par_level=PAR_LEVEL,
            percent_of_par=round(100.0 * r["quantity"] / PAR_LEVEL, 1),
        )
        for r in rows
    ]
    lines.sort(key=lambda l: (l.name, SIZE_ORDER.index(l.size) if l.size in SIZE_ORDER else 99))
    return lines


def engagement_lines(conn: sqlite3.Connection) -> list[EngagementLine]:
    rows = conn.execute(
        """
        SELECT e.product_id, c.name,
               SUM(CASE WHEN e.event_type = 'view' THEN 1 ELSE 0 END) AS views,
               SUM(CASE WHEN e.event_type = 'click' THEN 1 ELSE 0 END) AS clicks,
               SUM(CASE WHEN e.event_type = 'add_to_cart' THEN e.quantity ELSE 0 END) AS cart_units,
               SUM(CASE WHEN e.event_type = 'order' THEN e.quantity ELSE 0 END) AS order_units
        FROM product_events e JOIN catalogue c ON c.product_id = e.product_id
        WHERE e.created_at >= datetime('now', ?)
        GROUP BY e.product_id
        ORDER BY views DESC, clicks DESC, c.name
        """,
        (f"-{ENGAGEMENT_WINDOW_DAYS} days",),
    ).fetchall()
    lines: list[EngagementLine] = []
    for r in rows:
        attention = int(r["views"]) + int(r["clicks"])
        converted = int(r["cart_units"]) + int(r["order_units"])
        lines.append(
            EngagementLine(
                product_id=r["product_id"],
                name=r["name"],
                views=int(r["views"]),
                clicks=int(r["clicks"]),
                add_to_cart_units=int(r["cart_units"]),
                order_units=int(r["order_units"]),
                flagged_do_not_reorder=attention >= MIN_VIEWS_TO_FLAG and converted == 0,
            )
        )
    return lines


def build_report(conn: sqlite3.Connection) -> InventoryReport:
    low = low_stock_lines(conn)
    engagement = engagement_lines(conn)

    # Reorder candidates, most urgent first: more sold-out sizes, then the
    # lowest remaining percentage, then name.
    severity: dict[str, tuple[int, float, str]] = {}
    for line in low:
        zero, worst, name = severity.get(line.product_id, (0, 100.0, line.name))
        severity[line.product_id] = (
            zero + (1 if line.quantity == 0 else 0),
            min(worst, line.percent_of_par),
            name,
        )
    reorder_ids = sorted(severity, key=lambda pid: (-severity[pid][0], severity[pid][1], severity[pid][2]))
    hold_ids = [e.product_id for e in engagement if e.flagged_do_not_reorder]

    # What this review will actually work on: skip products that already have
    # an open note of that kind, then cap the batch.
    reorder_pending = [pid for pid in reorder_ids if not has_open_note(conn, "reorder", pid)]
    hold_pending = [pid for pid in hold_ids if not has_open_note(conn, "do_not_reorder", pid)]

    return InventoryReport(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        par_level=PAR_LEVEL,
        reorder_threshold_percent=int(REORDER_THRESHOLD * 100),
        window_days=ENGAGEMENT_WINDOW_DAYS,
        min_views_to_flag=MIN_VIEWS_TO_FLAG,
        low_stock=low,
        engagement=engagement,
        flagged_reorder_products=reorder_ids,
        flagged_do_not_reorder_products=hold_ids,
        max_notes_per_review=MAX_NOTES_PER_REVIEW,
        reorder_queue=reorder_pending[:MAX_NOTES_PER_REVIEW],
        do_not_reorder_queue=hold_pending[:MAX_NOTES_PER_REVIEW],
        reorder_backlog=max(0, len(reorder_pending) - MAX_NOTES_PER_REVIEW),
        do_not_reorder_backlog=max(0, len(hold_pending) - MAX_NOTES_PER_REVIEW),
    )


# --------------------------------------------------------------------------
# Owner notes
# --------------------------------------------------------------------------


def _row_to_note(row: sqlite3.Row) -> OwnerNote:
    return OwnerNote(
        id=row["id"],
        kind=row["kind"],
        product_id=row["product_id"],
        product_name=row["name"],
        size=row["size"],
        message=row["message"],
        status=row["status"],
        created_at=row["created_at"],
    )


def list_notes(conn: sqlite3.Connection, include_resolved: bool = False) -> list[OwnerNote]:
    where = "" if include_resolved else "WHERE n.status = 'open'"
    rows = conn.execute(
        f"""
        SELECT n.*, c.name FROM owner_notes n JOIN catalogue c ON c.product_id = n.product_id
        {where}
        ORDER BY CASE n.status WHEN 'open' THEN 0 ELSE 1 END, n.id DESC
        """
    ).fetchall()
    return [_row_to_note(r) for r in rows]


def has_open_note(conn: sqlite3.Connection, kind: str, product_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM owner_notes WHERE kind = ? AND product_id = ? AND status = 'open' LIMIT 1",
        (kind, product_id),
    ).fetchone()
    return row is not None


def create_note(
    conn: sqlite3.Connection, kind: str, product_id: str, message: str, size: str | None = None
) -> OwnerNote:
    if kind not in NOTE_KINDS:
        raise ValueError(f"unknown note kind {kind!r}")
    cursor = conn.execute(
        "INSERT INTO owner_notes (kind, product_id, size, message) VALUES (?, ?, ?, ?)",
        (kind, product_id, size, message.strip()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT n.*, c.name FROM owner_notes n JOIN catalogue c ON c.product_id = n.product_id WHERE n.id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    note = _row_to_note(row)
    _append_to_inbox(note)
    return note


def resolve_note(conn: sqlite3.Connection, note_id: int) -> OwnerNote | None:
    conn.execute("UPDATE owner_notes SET status = 'resolved' WHERE id = ?", (note_id,))
    conn.commit()
    row = conn.execute(
        "SELECT n.*, c.name FROM owner_notes n JOIN catalogue c ON c.product_id = n.product_id WHERE n.id = ?",
        (note_id,),
    ).fetchone()
    return _row_to_note(row) if row else None


def _append_to_inbox(note: OwnerNote) -> None:
    """Write the note to output/owner_inbox.md so it is visible outside the app."""
    try:
        INBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
        is_new = not INBOX_PATH.exists()
        with INBOX_PATH.open("a", encoding="utf-8") as f:
            if is_new:
                f.write("# Campus Customs owner inbox\n\nNotes from the inventory assistant, newest last.\n")
            label = "Reorder" if note.kind == "reorder" else "Do not reorder"
            size = f" (sizes: {note.size})" if note.size else ""
            f.write(f"\n## [{label}] {note.product_name}{size}\n\n")
            f.write(f"_{note.created_at} UTC · note #{note.id}_\n\n{note.message}\n")
    except OSError:
        pass  # the database copy is the source of truth; the file is a convenience
