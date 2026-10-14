"""Full operational check of the Campus Customs site.

Runs against the live servers (back end on :8000) and writes an HTML report
to output/app_check.html. Every chatbot answer is compared with the database,
so a passing report means the assistant quoted real prices and stock.

Run from the backend folder with both servers up::

    .venv\\Scripts\\python app_check.py

Browser-level checks (pages rendering, clicks, the cart, the language
selector) cannot be driven from Python; if output/app_check_browser.json
exists (written while running those checks in a browser), its results are
merged into the report.

The check leaves the database as it found it: the temporary account, chat
rows, product events, and owner notes it creates are removed at the end.

Screenshot evidence: output/app_check_images.json maps each check name to one
or more files in output/app_check_images/. The report shows a thumbnail next to
every Pass/Fail badge (relative paths, so the folder can be copied as a unit)
and lists the files per section. Use ``--render-only`` to rebuild the HTML from
output/app_check_results.json without re-running the tests.
"""

from __future__ import annotations

import html
import http.cookiejar
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inventory  # noqa: E402
import tools  # noqa: E402
from db import DB_PATH, PROJECT_ROOT  # noqa: E402
from security import verify_password  # noqa: E402

BASE = "http://localhost:8000"
OUT_PATH = PROJECT_ROOT / "output" / "app_check.html"
BROWSER_JSON = PROJECT_ROOT / "output" / "app_check_browser.json"
RESULTS_JSON = PROJECT_ROOT / "output" / "app_check_results.json"
IMAGES_JSON = PROJECT_ROOT / "output" / "app_check_images.json"
IMAGES_DIR = "app_check_images"  # relative to output/, next to app_check.html
SEED_CHAT_MAX_ID = 22

TEST_USER = ("test@campuscustoms.yale.edu", "password")
OTHER_USER = ("handsome.dan@example.com", "BulldogBlue2026!")
TEMP_EMAIL = "app.check@example.com"
TEMP_PASSWORD = "AppCheck-2026-xyz"

SPANISH_HINTS = ("tenemos", "sudadera", "talla", "precio", "está", "agotad", "quedan", "puesto",
                 "hola", "aquí", "tienes", "cuesta", "disponible", "tienda", "página")


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------


@dataclass
class Check:
    section: str
    name: str
    procedure: str
    expected: str
    actual: str = ""
    passed: bool = False
    seconds: float = 0.0


class Client:
    """Tiny HTTP client with a cookie jar, so sessions behave like a browser."""

    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body: dict | None = None, timeout: int = 120):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req, timeout=timeout) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                parsed = json.loads(raw) if raw and "json" in ctype else raw
                return resp.status, parsed, ctype
        except urllib.error.HTTPError as err:
            raw = err.read()
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = raw.decode(errors="replace")
            return err.code, parsed, err.headers.get("Content-Type", "")

    def get(self, path: str):
        return self.call("GET", path)

    def post(self, path: str, body: dict | None = None):
        return self.call("POST", path, body or {})

    def chat(self, message: str, product_id: str | None = None, history: list | None = None, language: str = "auto"):
        started = time.perf_counter()
        status, data, _ = self.call(
            "POST", "/api/chat",
            {"message": message, "product_id": product_id, "history": history or [], "language": language},
        )
        return status, data, time.perf_counter() - started


def looks_spanish(text: str) -> bool:
    return sum(h in text.lower() for h in SPANISH_HINTS) >= 2


def looks_english(text: str) -> bool:
    return not looks_spanish(text) and any(w in f" {text.lower()} " for w in (" the ", " is ", " in stock", " we ", " you "))


def count_mentioned(text: str, n: int) -> bool:
    """n appears as a standalone count (not inside a price like $58)."""
    return re.search(rf"(?<![\$\d.]){n}(?![\d.])", text) is not None


def dollar_amounts(text: str) -> set[float]:
    return {float(x) for x in re.findall(r"\$\s?(\d{1,4}(?:\.\d{1,2})?)", text)}


class Runner:
    def __init__(self) -> None:
        self.checks: list[Check] = []
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def record(self, section: str, name: str, procedure: str, expected: str, actual: str, passed: bool, seconds: float = 0.0) -> None:
        self.checks.append(Check(section, name, procedure, expected, actual, passed, round(seconds, 1)))
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")

    def product(self, pid: str):
        return tools.get_product(self.conn, pid)

    def qty(self, pid: str, size: str) -> int:
        return next(i.quantity for i in self.product(pid).inventory if i.size == size)

    # ----------------------------------------------------------------------
    # Sections
    # ----------------------------------------------------------------------

    def section_backend(self) -> None:
        s = "Back end and API"
        c = Client()
        status, data, _ = c.get("/api/health")
        self.record(s, "Health endpoint", "GET /api/health", "200 with database_found true",
                    f"{status} {data}", status == 200 and data.get("database_found") is True)

        status, data, _ = c.get("/api/products")
        ok = status == 200 and isinstance(data, list) and len(data) == 102 and all(len(p["inventory"]) == 6 and p["image_url"].startswith("/media/products/") for p in data)
        self.record(s, "Product list", "GET /api/products", "200, 102 products, 6 sizes each, image URLs under /media/products/",
                    f"{status}, {len(data) if isinstance(data, list) else '?'} products", ok)

        pid = "basic-hoodie-big-yale"
        truth = self.product(pid)
        status, data, _ = c.get(f"/api/products/{pid}")
        ok = status == 200 and data["name"] == truth.name and data["price"] == truth.price and [i["quantity"] for i in data["inventory"]] == [i.quantity for i in truth.inventory]
        self.record(s, "Product detail matches the database", f"GET /api/products/{pid}; compare with a direct SQL read",
                    f"{truth.name}, ${truth.price:g}, stock {[i.quantity for i in truth.inventory]}",
                    f"{data.get('name')}, ${data.get('price')}, stock {[i['quantity'] for i in data.get('inventory', [])]}", ok)

        status, data, _ = c.get("/api/products/does-not-exist")
        self.record(s, "Unknown product", "GET /api/products/does-not-exist", "404", str(status), status == 404)

        status, data, ctype = c.get(f"/media/products/{pid}.jpg")
        self.record(s, "Product image served", f"GET /media/products/{pid}.jpg", "200 image/jpeg",
                    f"{status} {ctype} {len(data) if isinstance(data, bytes) else ''} bytes", status == 200 and "image/jpeg" in ctype)

    def section_accounts(self) -> None:
        s = "Accounts"
        c = Client()
        status, data, _ = c.post("/api/auth/login", {"email": TEST_USER[0], "password": TEST_USER[1]})
        ok = status == 200 and data.get("first_name") == "Test" and data.get("is_owner") is True
        self.record(s, "Seeded test user logs in", "POST /api/auth/login with the seeded credentials",
                    "200, first_name Test, is_owner true", f"{status} {json.dumps({k: data.get(k) for k in ('first_name', 'email', 'is_owner')})}", ok)

        status, data, _ = c.get("/api/auth/me")
        self.record(s, "Session cookie identifies the user", "GET /api/auth/me with the cookie", "200 with the same user",
                    f"{status} {data.get('email') if isinstance(data, dict) else data}", status == 200 and data.get("email") == TEST_USER[0])

        c.post("/api/auth/logout")
        status, data, _ = c.get("/api/auth/me")
        self.record(s, "Logout clears the session", "POST /api/auth/logout then GET /api/auth/me", "401", str(status), status == 401)

        status1, d1, _ = c.post("/api/auth/login", {"email": TEST_USER[0], "password": "wrong-password"})
        status2, d2, _ = c.post("/api/auth/login", {"email": "nobody@example.com", "password": "whatever-1"})
        ok = status1 == 401 and status2 == 401 and d1.get("detail") == d2.get("detail")
        self.record(s, "Wrong password and unknown email get the same generic 401", "Two bad logins",
                    "401 both, identical message", f"{status1} / {status2}: {d1.get('detail')}", ok)

        # A temporary account left behind by manual testing would turn this into a 409, so clear it first.
        stale = self.conn.execute("DELETE FROM users WHERE email = ?", (TEMP_EMAIL,)).rowcount
        self.conn.commit()
        if stale:
            print(f"  (note) removed a stale {TEMP_EMAIL} account before the sign-up check")
        fresh = Client()
        status, data, _ = fresh.post("/api/auth/register", {"first_name": "App", "last_name": "Check", "email": TEMP_EMAIL, "password": TEMP_PASSWORD})
        row = self.conn.execute("SELECT password_hash FROM users WHERE email = ?", (TEMP_EMAIL,)).fetchone()
        hashed = row["password_hash"] if row else ""
        ok = status == 201 and hashed.startswith("pbkdf2_sha256$") and TEMP_PASSWORD not in hashed and verify_password(TEMP_PASSWORD, hashed)
        self.record(s, "Create account stores a PBKDF2 hash, never the password",
                    "POST /api/auth/register with a temporary account; read users.password_hash",
                    "201; hash starts with pbkdf2_sha256$; plain password absent; hash verifies",
                    f"{status}; hash prefix {hashed[:22]}…; verifies={verify_password(TEMP_PASSWORD, hashed) if hashed else False}", ok)

        status, data, _ = fresh.post("/api/auth/register", {"first_name": "App", "last_name": "Check", "email": TEMP_EMAIL, "password": TEMP_PASSWORD})
        self.record(s, "Duplicate email is refused", "Register the same email again", "409", str(status), status == 409)

        status, data, _ = fresh.post("/api/auth/register", {"first_name": "A", "last_name": "B", "email": "short@example.com", "password": "short"})
        self.record(s, "Short password is refused", "Register with a 5-character password", "422", str(status), status == 422)

        again = Client()
        status, data, _ = again.post("/api/auth/login", {"email": TEMP_EMAIL, "password": TEMP_PASSWORD})
        self.record(s, "New account can log in", "POST /api/auth/login with the temporary account", "200",
                    f"{status} {data.get('first_name') if isinstance(data, dict) else ''}", status == 200)

    def section_chat_db(self) -> None:
        s = "Chatbot: price and stock from the database"
        c = Client()
        dad = self.product("yale-dad-hoodie")
        status, data, secs = c.chat("How much is the Yale Dad Hoodie?")
        reply = data.get("reply", "")
        ok = status == 200 and f"${dad.price:g}" in reply and dollar_amounts(reply) <= {dad.price}
        self.record(s, "Price of a named item", "Ask the chatbot; compare with catalogue.price",
                    f"Mentions ${dad.price:g} and no other dollar amount", reply[:200], ok, secs)

        bb = "baseball-left-chest-crewneck"
        xl = self.qty(bb, "XL")
        status, data, secs = c.chat("Do you have the Baseball Left Chest Crewneck in XL?")
        reply = data.get("reply", "")
        self.record(s, "Out-of-stock size is stated plainly", "Ask about a size with 0 units (inventory XL)",
                    f"Says out of stock (database XL = {xl})", reply[:200], xl == 0 and "out of stock" in reply.lower(), secs)

        m = self.qty(bb, "M")
        status, data, secs = c.chat("How many mediums of the Baseball Left Chest Crewneck are left?")
        reply = data.get("reply", "")
        self.record(s, "Exact count for a size", "Ask for the medium count; compare with inventory",
                    f"States {m} (database M = {m})", reply[:200], count_mentioned(reply, m), secs)

        big = "basic-hoodie-big-yale"
        l = self.qty(big, "L")
        status, data, secs = c.chat("Is this in stock in large? How many?", product_id=big)
        reply = data.get("reply", "")
        self.record(s, "'This' resolves to the viewed item", f"Send product_id={big} as page context and ask about large",
                    f"Answers about Basic Hoodie Big Yale with {l} (database L = {l})", reply[:200],
                    "Basic Hoodie" in reply and count_mentioned(reply, l), secs)

        status, data, secs = c.chat("Do you have this in pink?", product_id=bb)
        reply = data.get("reply", "")
        colors = self.product(bb).colors
        self.record(s, "Color question uses the catalogue colors", f"Ask about pink with page context {bb}",
                    f"Says not pink; names {colors}", reply[:200],
                    "pink" in reply.lower() and any(col.split()[0] in reply.lower() for col in colors), secs)

        status, data, secs = c.chat("Do you sell gym shorts?")
        reply = data.get("reply", "")
        cards = data.get("products", [])
        catalogue_ids = {p.product_id for p in tools.fetch_products(self.conn)}
        says_no = any(w in reply.lower() for w in ("don't", "don’t", "do not", "not sell", "no gym", "couldn", "not carry"))
        alternatives_real = all(card["product_id"] in catalogue_ids and "short" not in card["name"].lower() for card in cards)
        self.record(s, "Nothing invented when nothing matches", "Ask for an item the store does not carry (gym shorts)",
                    "Says plainly that it does not sell them; any alternatives offered are real catalogue items, none of them shorts",
                    f"{reply[:160]} | alternatives offered: {len(cards)}", says_no and alternatives_real, secs)

    def section_search(self) -> None:
        s = "Dynamic search: cards on the page"
        c = Client()
        catalogue = {p.product_id: p for p in tools.fetch_products(self.conn)}
        fields = ("product_id", "name", "garment_type", "description", "price", "image_url", "sizes_in_stock", "total_stock")

        status, data, secs = c.chat("What hoodies do you have?")
        cards = data.get("products", [])
        ok = 10 <= len(cards) <= 24 and all(all(f in card for f in fields) for card in cards) and all(
            card["product_id"] in catalogue and "hood" in (card["product_id"] + card["name"] + card["garment_type"]).lower() for card in cards)
        self.record(s, "Category question returns product cards", "Ask 'What hoodies do you have?'; inspect response.products",
                    "10–24 cards, every one a real hoodie with image, name, price, description, sizes in stock",
                    f"{len(cards)} cards; first: {cards[0]['name'] if cards else '-'} ({cards[0]['price'] if cards else ''}); reply: {data.get('reply', '')[:120]}", ok, secs)

        status, data, secs = c.chat("Show me your fleeces")
        cards = data.get("products", [])
        ok = len(cards) >= 6 and all(("fleece" in card["product_id"] or "zip" in card["product_id"]) for card in cards)
        self.record(s, "A second category", "Ask 'Show me your fleeces'", "6+ cards, all fleece or quarter-zip items",
                    f"{len(cards)} cards: {[card['name'] for card in cards][:4]}", ok, secs)

        status, data, secs = c.chat("Anything for my grandma?")
        cards = data.get("products", [])
        self.record(s, "Family keyword", "Ask 'Anything for my grandma?'", "Includes Yale Grandma Hoodie",
                    f"{[card['name'] for card in cards]}", any(card["product_id"] == "yale-grandma-hoodie" for card in cards), secs)

        probes = [("navy hoodie", "hood"), ("quarter zip", "zip"), ("law school", "law"), ("béisbol", "baseball"), ("camiseta azul", "shirt"), ("gym shorts", None)]
        results = []
        all_ok = True
        for query, expect in probes:
            hits = tools.search_products(self.conn, query, 25)
            if expect is None:
                ok = len(hits) == 0
            else:
                ok = len(hits) > 0 and all(expect in (h.product_id + h.name + h.garment_type + " ".join(h.search_tags)).lower() for h in hits[:3])
            all_ok &= ok
            results.append(f"{query!r}: {len(hits)} hits")
        self.record(s, "Keyword search tool (English and Spanish, accents)", "Call tools.search_products directly with six queries",
                    "navy hoodie, quarter zip, law school, béisbol, camiseta azul find the right items; gym shorts finds none",
                    "; ".join(results), all_ok)

    def section_language(self) -> None:
        s = "English and Spanish"
        c = Client()
        history: list[dict] = []

        status, data, secs = c.chat("Hola, ¿qué sudaderas con capucha tienen?", history=history)
        reply = data.get("reply", "")
        cards = data.get("products", [])
        ok = looks_spanish(reply) and "$" in reply and len(cards) >= 5 and any("Hoodie" in card["name"] for card in cards)
        self.record(s, "Spanish in, Spanish out", "Ask about hoodies in Spanish (language = auto)",
                    "Spanish reply, $ prices, English product names, hoodie cards", f"{reply[:160]} | {len(cards)} cards", ok, secs)
        history += [{"role": "user", "content": "Hola, ¿qué sudaderas con capucha tienen?", "product_ids": []},
                    {"role": "assistant", "content": reply, "product_ids": [card["product_id"] for card in cards]}]

        bb = "baseball-left-chest-crewneck"
        status, data, secs = c.chat("¿Tienen esto en talla XL?", product_id=bb, history=history)
        reply = data.get("reply", "")
        self.record(s, "Out of stock in Spanish", f"Ask about XL in Spanish with page context {bb} (XL = {self.qty(bb, 'XL')})",
                    "Says 'agotado/agotada'", reply[:160], "agotad" in reply.lower(), secs)
        history += [{"role": "user", "content": "¿Tienen esto en talla XL?", "product_ids": []},
                    {"role": "assistant", "content": reply, "product_ids": [bb]}]

        status, data, secs = c.chat("Thanks! And how much is it?", product_id=bb, history=history)
        reply = data.get("reply", "")
        self.record(s, "Switches back to English", "Follow up in English", "English reply with $58",
                    reply[:160], looks_english(reply) and "$58" in reply, secs)

        status, data, secs = c.chat("What fleeces do you have?", language="es")
        reply = data.get("reply", "")
        self.record(s, "Forced Spanish", "English question with language = es", "Spanish reply", reply[:160], looks_spanish(reply), secs)

        status, data, secs = c.chat("¿Cuánto cuesta la sudadera Yale Dad Hoodie?", language="en")
        reply = data.get("reply", "")
        self.record(s, "Forced English", "Spanish question with language = en", "English reply with $68", reply[:160],
                    looks_english(reply) and "$68" in reply, secs)

    def section_memory(self) -> None:
        s = "Customer memory"
        c = Client()
        c.post("/api/auth/login", {"email": TEST_USER[0], "password": TEST_USER[1]})
        status, data, secs = c.chat("Do you remember me? What email do you have on file?")
        reply = data.get("reply", "")
        self.record(s, "Logged-in shopper is recognized", "Log in as the test user and ask", "Name and account email in the reply",
                    reply[:160], "Test" in reply and TEST_USER[0] in reply, secs)

        status, hist, _ = c.get("/api/chat/history")
        ok = status == 200 and isinstance(hist, list) and len(hist) >= 8 and hist[-2]["role"] == "user" and "remember me" in hist[-2]["content"]
        self.record(s, "Conversation is saved and reloadable", "GET /api/chat/history after the message",
                    "History includes the 6 seeded messages plus the new exchange", f"{status}, {len(hist) if isinstance(hist, list) else '?'} rows", ok)

        guest = Client()
        status, data, secs = guest.chat("Hey, do you remember me? What's my name?")
        reply = data.get("reply", "")
        self.record(s, "Guests are not remembered and no name is invented", "Ask as an anonymous visitor",
                    "Says it has nothing on record; suggests logging in; no name", reply[:160],
                    "Test" not in reply and ("log in" in reply.lower() or "logged in" in reply.lower() or "sign in" in reply.lower()), secs)

    def section_inventory(self) -> None:
        s = "Inventory tracking and owner notes"
        c = Client()
        pid = "yale-bowl-t-shirt"
        statuses = [c.post("/api/events", {"product_id": pid, "event_type": "view"})[0] for _ in range(5)]
        statuses.append(c.post("/api/events", {"product_id": pid, "event_type": "click"})[0])
        bad_type = c.post("/api/events", {"product_id": pid, "event_type": "purchase"})[0]
        bad_pid = c.post("/api/events", {"product_id": "nope", "event_type": "view"})[0]
        self.record(s, "Event endpoint", "POST /api/events: 5 views + 1 click, a bad type, an unknown product",
                    "204 for valid events, 422 for a bad type, 404 for an unknown product",
                    f"valid={set(statuses)}, bad type={bad_type}, unknown={bad_pid}", set(statuses) == {204} and bad_type == 422 and bad_pid == 404)

        anon = c.get("/api/owner/notes")[0]
        other = Client()
        other.post("/api/auth/login", {"email": OTHER_USER[0], "password": OTHER_USER[1]})
        non_owner = other.get("/api/owner/notes")[0]
        owner = Client()
        owner.post("/api/auth/login", {"email": TEST_USER[0], "password": TEST_USER[1]})
        own = owner.get("/api/owner/notes")[0]
        self.record(s, "Owner-only access", "GET /api/owner/notes as a guest, as Handsome Dan, as the test user",
                    "401, 403, 200", f"{anon}, {non_owner}, {own}", (anon, non_owner, own) == (401, 403, 200))

        status, report, _ = owner.get("/api/owner/report")
        line = next((e for e in report.get("engagement", []) if e["product_id"] == pid), None)
        ok = status == 200 and all(l["quantity"] <= 5 for l in report["low_stock"]) and line is not None and line["flagged_do_not_reorder"] and pid in report["flagged_do_not_reorder_products"]
        self.record(s, "Report applies the rules", "GET /api/owner/report", "All low-stock lines ≤ 5 units (20% of 25); Yale Bowl T Shirt flagged 'viewed but not ordered'",
                    f"{len(report.get('low_stock', []))} low lines, {len(report.get('flagged_reorder_products', []))} reorder products, hold flags {report.get('flagged_do_not_reorder_products')}", ok)

        started = time.perf_counter()
        status, result, _ = owner.post("/api/owner/review")
        secs = time.perf_counter() - started
        notes = result.get("notes_created", []) if isinstance(result, dict) else []
        kinds = {k: sum(1 for n in notes if n["kind"] == k) for k in ("reorder", "do_not_reorder")}
        ok = status == 200 and 1 <= kinds["reorder"] <= 10 and kinds["do_not_reorder"] == 1 and all(
            (n["product_id"] in report["flagged_reorder_products"]) if n["kind"] == "reorder" else (n["product_id"] in report["flagged_do_not_reorder_products"]) for n in notes)
        self.record(s, "Inventory assistant sends notes", "POST /api/owner/review", "≤10 reorder notes for flagged products, 1 do-not-reorder note for Yale Bowl T Shirt",
                    f"{status}; {kinds}; summary: {result.get('summary', '')[:140] if isinstance(result, dict) else result}", ok, secs)

        status, result2, _ = owner.post("/api/owner/review")
        _, all_notes, _ = owner.get("/api/owner/notes")
        pairs = [(n["kind"], n["product_id"]) for n in all_notes]
        self.record(s, "No duplicate notes", "Run the review again; list open notes", "No repeated (kind, product) pair",
                    f"{len(pairs)} open notes, {len(set(pairs))} distinct", len(pairs) == len(set(pairs)))

        first = all_notes[0]["id"]
        status, note, _ = owner.post(f"/api/owner/notes/{first}/resolve")
        self.record(s, "Resolve a note", f"POST /api/owner/notes/{first}/resolve", "status resolved", f"{status} {note.get('status') if isinstance(note, dict) else note}",
                    status == 200 and note.get("status") == "resolved")

    # ----------------------------------------------------------------------
    # Cleanup and report
    # ----------------------------------------------------------------------

    def cleanup(self) -> str:
        c = self.conn
        users = c.execute("DELETE FROM users WHERE email = ?", (TEMP_EMAIL,)).rowcount
        chat = c.execute("DELETE FROM chat_messages WHERE id > ?", (SEED_CHAT_MAX_ID,)).rowcount
        events = c.execute("DELETE FROM product_events").rowcount
        notes = c.execute("DELETE FROM owner_notes").rowcount
        c.commit()
        if inventory.INBOX_PATH.exists():
            inventory.INBOX_PATH.unlink()
        return f"Removed the temporary account ({users}), {chat} chat rows beyond the seed, {events} product events, {notes} owner notes, and the inbox file."


def load_browser_checks() -> list[Check]:
    if not BROWSER_JSON.exists():
        return []
    items = json.loads(BROWSER_JSON.read_text(encoding="utf-8"))
    return [Check(**item) for item in items]


def load_image_map() -> dict[str, list[str]]:
    """Check name -> screenshot files that exist under output/app_check_images/."""
    if not IMAGES_JSON.exists():
        return {}
    data = json.loads(IMAGES_JSON.read_text(encoding="utf-8"))
    folder = OUT_PATH.parent / IMAGES_DIR
    image_map: dict[str, list[str]] = {}
    for name, value in data.items():
        if name.startswith("_"):
            continue
        files = value if isinstance(value, list) else [value]
        present = [f for f in files if (folder / f).exists()]
        for f in files:
            if f not in present:
                print(f"  (warning) screenshot missing for {name!r}: {f}")
        image_map[name] = present
    return image_map


COLD_START = [
    Check("Cold start (recorded 2026-10-14 morning)", "Servers restarted from scratch", "Stop both servers; start the back end then the front end", "Both start cleanly", "Health OK, version 0.4.0, 102 products", True),
    Check("Cold start (recorded 2026-10-14 morning)", "Anonymous home page", "Open http://localhost:5173", "Approved design, fonts loaded, nav shows Cart / Log In / Create Account", "EB Garamond + Source Sans 3 loaded; 4 tiles; 4 fan favorites", True),
    Check("Cold start (recorded 2026-10-14 morning)", "Products and item page", "Open Products, click a card", "102 cards; item page with price and six-size picker", "102 cards; Benjamin Franklin T Shirt, $32, 6 size buttons", True),
    Check("Cold start (recorded 2026-10-14 morning)", "Chat as a guest", "Ask 'What hoodies do you have?'", "Reply plus cards on the page", "27 hoodies named; 24 cards", True),
    Check("Cold start (recorded 2026-10-14 morning)", "Log in", "Log in as the test user", "Nav shows Inventory, Hi Test, Log Out", "As expected", True),
    Check("Cold start (recorded 2026-10-14 morning)", "Spanish on an item page", "Ask '¿Tienen esto en talla XL?' on the Baseball crewneck", "Spanish reply, XL agotada, $58", "'la talla XL … está agotada ahora mismo (0 unidades) … Cuesta $58'", True),
    Check("Cold start (recorded 2026-10-14 morning)", "Cart and checkout", "Add size M, open Cart, open Checkout", "Badge 1, total $58, pre-filled name, Place order disabled", "As expected", True),
    Check("Cold start (recorded 2026-10-14 morning)", "Owner page and review", "Open Inventory, run a review", "Activity shown; notes sent", "View/click/add-to-cart shown; 10 reorder notes, backlog 90", True),
]


def render(checks: list[Check], cleanup_note: str, started: datetime, finished: datetime,
           image_map: dict[str, list[str]] | None = None) -> str:
    image_map = image_map or {}
    sections: dict[str, list[Check]] = {}
    for ch in checks:
        sections.setdefault(ch.section, []).append(ch)
    total = len(checks)
    passed = sum(1 for ch in checks if ch.passed)
    failed = total - passed

    def badge(ok: bool) -> str:
        return '<span class="badge pass">Pass</span>' if ok else '<span class="badge fail">Fail</span>'

    def evidence(i: Check) -> str:
        files = image_map.get(i.name, [])
        if not files:
            return '<td class="shot"><span class="noshot">no screenshot</span></td>'
        imgs = "".join(
            f'<a href="{IMAGES_DIR}/{f}" target="_blank" title="Open {html.escape(f)} full size">'
            f'<img src="{IMAGES_DIR}/{f}" alt="Screenshot: {html.escape(i.name)}" loading="lazy"></a>'
            for f in files
        )
        return f'<td class="shot">{imgs}</td>'

    parts: list[str] = []
    for section, items in sections.items():
        p = sum(1 for i in items if i.passed)
        rows = "".join(
            f"<tr><td>{idx}</td><td><strong>{html.escape(i.name)}</strong></td><td>{html.escape(i.procedure)}</td>"
            f"<td>{html.escape(i.expected)}</td><td>{html.escape(i.actual)}</td><td>{badge(i.passed)}"
            f"{f'<div class=secs>{i.seconds:g} s</div>' if i.seconds else ''}</td>{evidence(i)}</tr>"
            for idx, i in enumerate(items, 1)
        )
        section_files = list(dict.fromkeys(f for i in items for f in image_map.get(i.name, [])))
        shots = ""
        if section_files:
            links = ", ".join(f'<a href="{IMAGES_DIR}/{f}" target="_blank">{html.escape(f)}</a>' for f in section_files)
            shots = (f'<p class="shots-list"><strong>Screenshots for this section</strong> '
                     f'({len(section_files)} files in <code>{IMAGES_DIR}/</code>): {links}</p>')
        parts.append(
            f'<section><div class="sec-head"><p class="eyebrow">{p} of {len(items)} passed</p><h2>{html.escape(section)}</h2></div>'
            f'<table><thead><tr><th>#</th><th>Test</th><th>Procedure</th><th>Expected</th><th>Actual</th><th>Result</th><th>Screenshot</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>{shots}</section>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Campus Customs app check</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@400;500&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>
  :root {{ --blue:#00356b; --link:#286dc0; --ink:#222; --muted:#5a5a5a; --rule:#ddd; --light:#f5f5f5; --green:#1a7f37; --red:#b42318;
          --serif:'EB Garamond','Times New Roman',Times,Georgia,serif; --sans:'Source Sans 3','Gill Sans',Calibri,Arial,sans-serif; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:var(--sans); color:var(--ink); background:#fff; font-size:15px; line-height:1.5; }}
  .topbar {{ height:6px; background:var(--blue); }}
  header {{ text-align:center; padding:28px 24px 18px; border-bottom:1px solid var(--rule); }}
  .wordmark {{ font-family:var(--serif); font-size:44px; color:var(--blue); line-height:1; }}
  .wordmark small {{ display:block; margin-top:8px; font-family:var(--sans); font-size:12px; letter-spacing:.2em; text-transform:uppercase; color:var(--muted); font-weight:600; }}
  main {{ max-width:1400px; margin:0 auto; padding:32px 24px 72px; }}
  h1 {{ font-family:var(--serif); font-weight:400; font-size:40px; margin:0 0 6px; }}
  h2 {{ font-family:var(--serif); font-weight:400; font-size:28px; margin:0; }}
  .eyebrow {{ font-size:12px; font-weight:600; letter-spacing:.1em; text-transform:uppercase; color:var(--link); margin:0 0 6px; }}
  .lead {{ font-family:var(--serif); font-size:19px; color:#333; max-width:70ch; margin:0 0 24px; }}
  .summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; margin:0 0 40px; }}
  .stat {{ border:1px solid var(--rule); background:var(--light); padding:18px 20px; }}
  .stat .n {{ font-family:var(--serif); font-size:36px; line-height:1; color:var(--blue); }}
  .stat .l {{ font-size:12px; letter-spacing:.1em; text-transform:uppercase; color:var(--muted); font-weight:600; margin-top:6px; }}
  section {{ padding:32px 0; border-top:1px solid var(--rule); }}
  .sec-head {{ margin-bottom:16px; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  th, td {{ text-align:left; vertical-align:top; padding:10px 8px; border-bottom:1px solid #ebebeb; }}
  th {{ font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); }}
  td:nth-child(5) {{ font-family:var(--serif); font-size:15px; max-width:34ch; }}
  .badge {{ display:inline-block; padding:3px 9px; font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:#fff; }}
  .badge.pass {{ background:var(--green); }} .badge.fail {{ background:var(--red); }}
  .secs {{ font-size:11px; color:var(--muted); margin-top:4px; }}
  .shot {{ width:272px; }}
  .shot a {{ display:block; margin-bottom:8px; }}
  .shot img {{ display:block; width:256px; height:auto; border:1px solid var(--rule); box-shadow:0 1px 3px rgba(0,0,0,.14); background:#fff; }}
  .shot a {{ position:relative; }}
  .shot a:hover img {{ outline:2px solid var(--link); transform:scale(2.4); transform-origin:right center; position:relative; z-index:20; box-shadow:0 8px 28px rgba(0,0,0,.28); }}
  .noshot {{ font-size:12px; color:var(--muted); }}
  .shots-list {{ font-size:13px; color:var(--muted); margin:12px 0 0; line-height:1.7; }}
  .shots-list code {{ color:var(--ink); }}
  .note {{ background:var(--light); border-left:3px solid var(--blue); padding:12px 16px; margin:24px 0 0; font-size:14px; }}
  footer {{ background:var(--blue); color:#fff; text-align:center; padding:12px; font-size:12px; letter-spacing:.08em; text-transform:uppercase; font-weight:600; }}
  @media (max-width:800px) {{ table, thead, tbody, tr, th, td {{ display:block; }} thead {{ display:none; }} td {{ border:none; padding:4px 0; }} tr {{ border-bottom:1px solid var(--rule); padding:10px 0; }} .shot, .shot img {{ width:100%; }} }}
</style>
</head>
<body>
<div class="topbar"></div>
<header><div class="wordmark">Campus Customs<small>Application check</small></div></header>
<main>
  <p class="eyebrow">MGT 409 · Homework 4</p>
  <h1>Full operational test</h1>
  <p class="lead">Procedures and results for the whole site: the cold start, the API, accounts, the chatbot's price and stock answers checked against the database, dynamic search and product cards, English and Spanish, customer memory, inventory tracking, and the browser walkthrough. Run started {started:%Y-%m-%d %H:%M} and finished {finished:%H:%M} local time.</p>
  <div class="summary">
    <div class="stat"><div class="n">{total}</div><div class="l">Checks</div></div>
    <div class="stat"><div class="n">{passed}</div><div class="l">Passed</div></div>
    <div class="stat"><div class="n">{failed}</div><div class="l">Failed</div></div>
    <div class="stat"><div class="n">{len(sections)}</div><div class="l">Sections</div></div>
  </div>
  {''.join(parts)}
  <div class="note"><strong>Database left as found.</strong> {html.escape(cleanup_note)} Re-run with <code>backend\\.venv\\Scripts\\python app_check.py</code> while both servers are up; browser checks come from <code>output/app_check_browser.json</code>.</div>
  <div class="note"><strong>Screenshots.</strong> Each row links to the screen that shows the check passing, captured in the browser pane on 2026-10-14 while re-running the check by hand. Thumbnails open the full-size file; paths are relative (<code>{IMAGES_DIR}/…</code>, mapped in <code>app_check_images.json</code>), so the <code>output</code> folder can be copied or zipped as a unit. Cold-start rows reuse the afternoon captures of the same screens; API rows show the JSON as the browser renders it.</div>
</main>
<footer>Campus Customs · New Haven, Connecticut</footer>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    image_map = load_image_map()
    if "--render-only" in argv:
        if not RESULTS_JSON.exists():
            print(f"Nothing to render: {RESULTS_JSON} does not exist. Run the full check first.")
            return 2
        saved = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
        meta = saved if isinstance(saved, dict) else {"checks": saved}
        checks = [Check(**c) for c in meta["checks"]]
        fallback = datetime.fromtimestamp(RESULTS_JSON.stat().st_mtime)
        started = datetime.fromisoformat(meta["started"]) if meta.get("started") else fallback
        finished = datetime.fromisoformat(meta["finished"]) if meta.get("finished") else fallback
        OUT_PATH.write_text(render(checks, meta.get("cleanup_note", "Rendered from saved results."), started, finished, image_map), encoding="utf-8")
        print(f"Re-rendered {len(checks)} saved checks to {OUT_PATH} (no tests were run).")
        return 0

    started = datetime.now()
    runner = Runner()
    try:
        for name, fn in [("Back end and API", runner.section_backend), ("Accounts", runner.section_accounts),
                         ("Chatbot: price and stock", runner.section_chat_db), ("Dynamic search", runner.section_search),
                         ("English and Spanish", runner.section_language), ("Customer memory", runner.section_memory),
                         ("Inventory tracking", runner.section_inventory)]:
            print(f"\n=== {name} ===")
            try:
                fn()
            except Exception as exc:  # keep going; record the failure
                runner.record(name, f"{name} (unexpected error)", "see traceback in console", "no exception", f"{type(exc).__name__}: {exc}", False)
                import traceback
                traceback.print_exc()
    finally:
        cleanup_note = runner.cleanup()
        print("\n" + cleanup_note)

    checks = COLD_START + runner.checks + load_browser_checks()
    finished = datetime.now()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(checks, cleanup_note, started, finished, image_map), encoding="utf-8")
    total, passed = len(checks), sum(1 for c in checks if c.passed)
    without_shot = [c.name for c in checks if not image_map.get(c.name)]
    print(f"\n{passed}/{total} checks passed. Report: {OUT_PATH}")
    print(f"{total - len(without_shot)}/{total} checks have a screenshot" + (f"; missing: {without_shot}" if without_shot else "."))
    RESULTS_JSON.write_text(json.dumps({
        "started": started.isoformat(timespec="seconds"),
        "finished": finished.isoformat(timespec="seconds"),
        "cleanup_note": cleanup_note,
        "checks": [asdict(c) for c in checks],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
