"""Reset the demo data to the seeded state.

Removes everything the site itself writes during use, and keeps the
instructor's seed data and all user accounts:

* chat_messages rows beyond the 22 seeded ones (ids > 22)
* every product_events row (views, clicks, add-to-carts)
* every owner_notes row
* output/owner_inbox.md (the plain-text copy of the owner's notes)

Run from the backend folder::

    .venv\\Scripts\\python reset_demo_data.py

Add ``--keep-notes`` to leave the owner's notes and inbox in place.
"""

from __future__ import annotations

import sqlite3
import sys

from db import DB_PATH, PROJECT_ROOT

SEED_CHAT_MAX_ID = 22
INBOX_PATH = PROJECT_ROOT / "output" / "owner_inbox.md"


def main(keep_notes: bool) -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        chat = conn.execute("DELETE FROM chat_messages WHERE id > ?", (SEED_CHAT_MAX_ID,)).rowcount
        events = conn.execute("DELETE FROM product_events").rowcount
        notes = 0 if keep_notes else conn.execute("DELETE FROM owner_notes").rowcount
        conn.commit()
    except sqlite3.OperationalError as exc:
        # product_events / owner_notes only exist once the API has started at least once.
        if "no such table" not in str(exc):
            raise
        conn.rollback()
        chat = conn.execute("DELETE FROM chat_messages WHERE id > ?", (SEED_CHAT_MAX_ID,)).rowcount
        conn.commit()
        events = notes = 0
    finally:
        conn.close()

    inbox = False
    if not keep_notes and INBOX_PATH.exists():
        INBOX_PATH.unlink()
        inbox = True

    print(f"Removed {chat} chat messages beyond the seed, {events} product events, {notes} owner notes."
          + (" Deleted output/owner_inbox.md." if inbox else ""))
    print("User accounts were kept.")


if __name__ == "__main__":
    main(keep_notes="--keep-notes" in sys.argv[1:])
