"""Catalogue and inventory lookups backed by the SQLite database.

These plain functions are used two ways:

* The product API routes in main.py call them directly.
* The agent in agent.py wraps them as tools, so every price, size, and stock
  figure the assistant quotes comes from here rather than from the model's
  imagination.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

from models import LOW_STOCK_THRESHOLD, InventoryItem, Product

# Product images are served at this URL prefix, e.g. /media/products/foo.jpg.
MEDIA_URL_PREFIX = "/media/products"

# The order sizes should appear in, smallest to largest.
SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL"]

__all__ = ["LOW_STOCK_THRESHOLD", "MEDIA_URL_PREFIX", "SIZE_ORDER"]


# --------------------------------------------------------------------------
# Loading products
# --------------------------------------------------------------------------


def _parse_json_list(raw: str) -> list[str]:
    """The catalogue stores colors and tags as JSON text; turn them into lists."""
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _size_sort_key(item: InventoryItem) -> int:
    return SIZE_ORDER.index(item.size) if item.size in SIZE_ORDER else len(SIZE_ORDER)


def _load_inventory(conn: sqlite3.Connection, product_ids: list[str]) -> dict[str, list[InventoryItem]]:
    """Return {product_id: [InventoryItem, ...]} for the given products."""
    if not product_ids:
        return {}
    placeholders = ",".join("?" * len(product_ids))
    rows = conn.execute(
        f"SELECT product_id, size, quantity FROM inventory WHERE product_id IN ({placeholders})",
        product_ids,
    ).fetchall()

    by_product: dict[str, list[InventoryItem]] = {pid: [] for pid in product_ids}
    for row in rows:
        by_product[row["product_id"]].append(InventoryItem(size=row["size"], quantity=row["quantity"]))
    for items in by_product.values():
        items.sort(key=_size_sort_key)
    return by_product


def _row_to_product(row: sqlite3.Row, inventory: list[InventoryItem]) -> Product:
    """Combine a catalogue row and its inventory into the API's Product shape."""
    image_name = Path(row["image_file_path"]).name
    return Product(
        product_id=row["product_id"],
        name=row["name"],
        garment_type=row["garment_type"],
        description=row["description"],
        colors=_parse_json_list(row["colors"]),
        search_tags=_parse_json_list(row["search_tags"]),
        image_file_path=row["image_file_path"],
        image_url=f"{MEDIA_URL_PREFIX}/{image_name}",
        price=row["price"],
        inventory=inventory,
        total_stock=sum(item.quantity for item in inventory),
    )


def fetch_products(conn: sqlite3.Connection, product_ids: list[str] | None = None) -> list[Product]:
    """Load products with their inventory, sorted by name. Pass ``product_ids`` to filter."""
    if product_ids is None:
        rows = conn.execute("SELECT * FROM catalogue ORDER BY name").fetchall()
    elif not product_ids:
        return []
    else:
        placeholders = ",".join("?" * len(product_ids))
        rows = conn.execute(
            f"SELECT * FROM catalogue WHERE product_id IN ({placeholders}) ORDER BY name",
            product_ids,
        ).fetchall()

    inventory = _load_inventory(conn, [row["product_id"] for row in rows])
    return [_row_to_product(row, inventory.get(row["product_id"], [])) for row in rows]


def fetch_products_in_order(conn: sqlite3.Connection, product_ids: list[str]) -> list[Product]:
    """Like fetch_products, but keeps the caller's order and drops unknown ids and duplicates."""
    unique: list[str] = []
    for pid in product_ids:
        if pid not in unique:
            unique.append(pid)
    by_id = {p.product_id: p for p in fetch_products(conn, unique)}
    return [by_id[pid] for pid in unique if pid in by_id]


def get_product(conn: sqlite3.Connection, product_id: str) -> Product | None:
    products = fetch_products(conn, [product_id])
    return products[0] if products else None


# --------------------------------------------------------------------------
# Searching
# --------------------------------------------------------------------------

# Words that carry no meaning for a product search (English and Spanish; the
# Spanish entries are written without accents because _normalize strips them).
STOPWORDS = {
    # English
    "a", "an", "the", "and", "or", "of", "for", "in", "on", "with", "to", "at", "by",
    "do", "does", "did", "you", "your", "u", "have", "has", "got", "any", "some", "what",
    "whats", "which", "me", "i", "im", "is", "are", "it", "this", "that", "there", "my",
    "please", "show", "find", "looking", "want", "need", "like", "can", "get", "all",
    "something", "anything", "stuff", "items", "item", "things", "thing", "sell", "carry",
    "merch", "gear", "yale", "campus", "customs", "about", "how", "much", "cost", "price",
    "cheap", "cheapest", "expensive", "best", "nice", "cool", "good", "new", "buy",
    # Spanish
    "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas", "en", "con", "y",
    "o", "que", "cual", "cuales", "cuanto", "cuanta", "cuantos", "cuesta", "cuestan",
    "precio", "precios", "tienen", "tienes", "tiene", "hay", "quiero", "quisiera", "busco",
    "buscando", "algo", "alguna", "algun", "para", "por", "favor", "ver", "mostrar",
    "muestrame", "ensename", "mi", "mis", "su", "sus", "es", "son", "esta", "estan", "este",
    "esto", "hola", "gracias", "talla", "tallas", "color", "colores", "ropa", "prenda",
    "prendas", "articulo", "articulos", "tienda", "venden", "vendes", "comprar", "barato",
    "barata", "baratos", "baratas", "caro", "cara", "bonito", "bonita", "me", "te", "le",
    "lo", "al", "mas", "menos",
}

# A query word matches a product if any of its alternatives appears in the
# (English) catalogue text. Spanish keys are accent-free, matching _normalize.
SYNONYMS: dict[str, list[str]] = {
    # English variants
    "blue": ["blue", "navy"],
    "grey": ["grey", "gray"],
    "tee": ["shirt"],
    "tshirt": ["shirt"],
    "hoody": ["hoodie"],
    "sweater": ["sweater", "sweatshirt", "crewneck"],
    "jumper": ["sweatshirt", "crewneck"],
    "grandmother": ["grandma"],
    "grandfather": ["grandpa"],
    "mother": ["mom"],
    "father": ["dad"],
    # Spanish garments
    "sudadera": ["sweatshirt", "hoodie", "crewneck"],
    "capucha": ["hoodie", "hooded"],
    "camiseta": ["shirt"],
    "playera": ["shirt"],
    "remera": ["shirt"],
    "camisa": ["shirt"],
    "chaqueta": ["jacket"],
    "chamarra": ["jacket"],
    "abrigo": ["jacket", "fleece"],
    "polar": ["fleece"],
    "forro": ["fleece"],
    "sueter": ["sweater", "sweatshirt", "crewneck"],
    "jersey": ["sweatshirt", "crewneck"],
    "cremallera": ["zip"],
    "cierre": ["zip"],
    "manga": ["sleeve"],
    "larga": ["long"],
    "corta": ["short"],
    "pesado": ["heavyweight"],
    "pesada": ["heavyweight"],
    "clasico": ["classic"],
    "clasica": ["classic"],
    # Spanish colors
    "azul": ["blue", "navy"],
    "marino": ["navy"],
    "gris": ["gray", "grey"],
    "blanco": ["white"],
    "blanca": ["white"],
    "rojo": ["red"],
    "roja": ["red"],
    "negro": ["black"],
    "negra": ["black"],
    "rosa": ["pink"],
    "rosado": ["pink"],
    # Spanish family
    "mama": ["mom"],
    "madre": ["mom"],
    "papa": ["dad"],
    "padre": ["dad"],
    "abuela": ["grandma"],
    "abuelo": ["grandpa"],
    "tia": ["aunt"],
    "tio": ["uncle"],
    "hermano": ["brother"],
    "primo": ["cousin"],
    "prima": ["cousin"],
    "familia": ["mom", "dad", "grandma", "grandpa", "aunt", "uncle", "brother", "cousin"],
    # Spanish sports
    "beisbol": ["baseball"],
    "futbol": ["football", "soccer"],
    "baloncesto": ["basketball"],
    "basquetbol": ["basketball"],
    "natacion": ["swimming"],
    "tenis": ["tennis"],
    "vela": ["sailing"],
    "voleibol": ["volleyball"],
    "atletismo": ["track"],
    "esgrima": ["fencing"],
    "buceo": ["diving"],
    "clavados": ["diving"],
    "deporte": ["sports"],
    "deportivo": ["sports"],
    "deportiva": ["sports"],
    "juego": ["game"],
    "partido": ["game"],
    # Spanish schools and colleges
    "derecho": ["law"],
    "leyes": ["law"],
    "medicina": ["medicine"],
    "enfermeria": ["nursing"],
    "arquitectura": ["architecture"],
    "musica": ["music"],
    "arte": ["art"],
    "ingenieria": ["engineering"],
    "negocios": ["management"],
    "administracion": ["management"],
    "gestion": ["management"],
    "salud": ["health"],
    "publica": ["public"],
    "divinidad": ["divinity"],
    "teologia": ["divinity"],
    "bosque": ["forest"],
    "forestal": ["forest"],
    "universidad": ["university"],
    "escuela": ["school"],
    "facultad": ["school"],
    "colegio": ["college"],
    "residencial": ["college"],
}


def _normalize(text: str) -> str:
    """Lower-case, strip accents, and turn punctuation into spaces.

    'Quarter-Zip' -> 'quarter zip', 'béisbol' -> 'beisbol', so Spanish queries
    match the accent-free keys above and the English catalogue text.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]+", " ", without_accents.lower())


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _query_terms(query: str) -> list[list[str]]:
    """Turn a free-text query into a list of alternatives per meaningful word."""
    words = [w for w in _normalize(query).split() if len(w) > 1]
    terms: list[list[str]] = []
    for word in words:
        if word in STOPWORDS:
            continue
        # Look the word up as typed, then in singular form ("sudaderas" -> "sudadera").
        key = word if word in SYNONYMS else _singular(word)
        terms.append(SYNONYMS.get(key, [key]))
    return terms


def search_products(conn: sqlite3.Connection, query: str, max_results: int = 10) -> list[Product]:
    """Keyword search across name, garment type, description, colors, and tags.

    Each meaningful word in the query must appear somewhere in the product
    (for two-word queries); longer queries may miss one word. Results are
    ranked by where the words matched: names and types count more than
    descriptions.
    """
    terms = _query_terms(query)
    if not terms:
        return []
    required = len(terms) if len(terms) <= 2 else len(terms) - 1

    scored: list[tuple[int, str, Product]] = []
    for product in fetch_products(conn):
        fields = {
            "name": (_normalize(product.name), 3),
            "type": (_normalize(product.garment_type), 2),
            "tags": (_normalize(" ".join(product.search_tags)), 2),
            "colors": (_normalize(" ".join(product.colors)), 2),
            "description": (_normalize(product.description), 1),
        }
        score = 0
        matched = 0
        for alternatives in terms:
            term_score = 0
            for text, weight in fields.values():
                if any(alt in text for alt in alternatives):
                    term_score += weight
            if term_score:
                matched += 1
                score += term_score
        if matched >= required:
            scored.append((score, product.name, product))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [product for _, _, product in scored[:max_results]]


# --------------------------------------------------------------------------
# Stock and catalogue facts
# --------------------------------------------------------------------------


def stock_for_size(product: Product, size: str) -> InventoryItem | None:
    wanted = size.strip().upper()
    for item in product.inventory:
        if item.size.upper() == wanted:
            return item
    return None


def list_garment_types(conn: sqlite3.Connection) -> list[tuple[str, int]]:
    """Distinct garment types with product counts, merged case-insensitively."""
    counts: dict[str, int] = {}
    for row in conn.execute("SELECT garment_type FROM catalogue"):
        key = row["garment_type"].strip().lower()
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def price_range(conn: sqlite3.Connection) -> tuple[float, float]:
    row = conn.execute("SELECT MIN(price), MAX(price) FROM catalogue").fetchone()
    return float(row[0]), float(row[1])


# --------------------------------------------------------------------------
# Customer memory (chat_messages)
# --------------------------------------------------------------------------


def product_ids_from_json(raw: str | None) -> list[str]:
    """Pull product ids out of a saved products_json value, in stored order."""
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []
    ids: list[str] = []
    for item in items if isinstance(items, list) else []:
        pid = item.get("product_id") if isinstance(item, dict) else None
        if isinstance(pid, str) and pid not in ids:
            ids.append(pid)
    return ids


def recent_product_ids_for_user(conn: sqlite3.Connection, user_id: int, limit: int = 5) -> list[str]:
    """Products the assistant showed this shopper most recently, newest first."""
    rows = conn.execute(
        "SELECT products_json FROM chat_messages WHERE user_id = ? AND role = 'assistant' "
        "AND products_json IS NOT NULL ORDER BY id DESC LIMIT 20",
        (user_id,),
    ).fetchall()
    ids: list[str] = []
    for row in rows:
        for pid in product_ids_from_json(row["products_json"]):
            if pid not in ids:
                ids.append(pid)
            if len(ids) >= limit:
                return ids
    return ids


def count_messages_for_user(conn: sqlite3.Connection, user_id: int) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM chat_messages WHERE user_id = ?", (user_id,)).fetchone()[0])
