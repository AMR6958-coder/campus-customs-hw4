"""The Campus Customs shopping assistant: a PydanticAI agent.

How it fits together:

* ``prompts/prompt.md`` holds the standing instructions (voice, honesty
  rules, safety basics, and the output contract). It is re-read whenever the
  file changes, so prompt edits apply to the next message without a restart.
* ``ShopDeps`` carries per-request context into the run: the database
  connection, the logged-in shopper (if any), the product page they are on
  (if any), and the products discussed most recently in this conversation.
* The functions decorated with ``@agent.tool`` are the only way the model can
  learn about products, prices, stock, and the shopper. They call
  ``tools.py`` and return the typed results defined in ``models.py``.
* The run ends with an ``AgentReply``: the text to show plus the product ids
  the page should display. An output validator rejects replies that are not
  backed by tool results.

The model itself is reached through the Portkey gateway, which forwards
OpenAI-compatible requests to OpenAI. Credentials come from ``backend/.env``.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext, capture_run_messages
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

import audit_trail
import tools
from models import (
    LOW_STOCK_THRESHOLD,
    AgentReply,
    CatalogueOverview,
    ChatTurn,
    FocusProduct,
    GarmentTypeCount,
    Product,
    ProductDetails,
    ProductSummary,
    RecentProduct,
    SearchResult,
    ShopperProfile,
    SizeStock,
    StockCheck,
    StockStatus,
    UserOut,
)

BACKEND_DIR = Path(__file__).resolve().parent
PROMPT_PATH = BACKEND_DIR / "prompts" / "prompt.md"

# The project's .env wins over any same-named variable inherited from the
# machine environment, so the key used is always the one in this folder.
load_dotenv(BACKEND_DIR / ".env", override=True)

PORTKEY_BASE_URL = os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1").strip()
MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip()
REQUEST_TIMEOUT_SECONDS = 60

# How many prior messages to give the model for context.
HISTORY_LIMIT = 20
# The most products a single reply may put on the page (a category question
# such as "what hoodies do you have?" should show every match as a card).
MAX_PRODUCTS_PER_REPLY = 24


# --------------------------------------------------------------------------
# Model (LLM) setup
# --------------------------------------------------------------------------


class AgentNotConfigured(RuntimeError):
    """Raised when no LLM credentials are available."""


@lru_cache(maxsize=1)
def get_model() -> OpenAIChatModel:
    """Build the chat model once and reuse it for every request."""
    api_key = (os.getenv("PORTKEY_API_KEY") or os.getenv("MYPORTKEY_API_KEY") or "").strip()
    if not api_key:
        raise AgentNotConfigured("PORTKEY_API_KEY is not set. Add it to backend/.env (see .env.example).")
    client = AsyncOpenAI(
        base_url=PORTKEY_BASE_URL,
        api_key=api_key,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=2,
    )
    return OpenAIChatModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


# --------------------------------------------------------------------------
# The prompt
# --------------------------------------------------------------------------

_prompt_cache: tuple[float, str] | None = None


def load_prompt() -> str:
    """Return prompts/prompt.md, re-reading it whenever the file changes."""
    global _prompt_cache
    modified = PROMPT_PATH.stat().st_mtime
    if _prompt_cache is None or _prompt_cache[0] != modified:
        _prompt_cache = (modified, PROMPT_PATH.read_text(encoding="utf-8"))
    return _prompt_cache[1]


# --------------------------------------------------------------------------
# Per-request context
# --------------------------------------------------------------------------


@dataclass
class ShopDeps:
    """Everything the agent knows about this request besides the message."""

    conn: sqlite3.Connection
    # The logged-in shopper, or None for an anonymous visitor.
    user: UserOut | None = None
    # The product page the shopper is on, if any.
    current_product_id: str | None = None
    # Products shown in this conversation, newest first (from saved history for
    # logged-in shoppers, or from the browser for anonymous ones).
    recent_product_ids: list[str] = field(default_factory=list)
    # "auto" (mirror the shopper), "en", or "es".
    language: str = "auto"
    # Filled in by run_agent when language is "auto": the language the latest
    # message appears to be in, so the model is told explicitly.
    detected_language: str | None = None


_SPANISH_MARKERS = {
    "hola", "gracias", "tienen", "tienes", "tiene", "hay", "cuanto", "cuanta", "cuantos", "cuesta",
    "cuestan", "talla", "tallas", "precio", "quiero", "busco", "algo", "para", "esta", "este",
    "esto", "donde", "como", "que", "cual", "sudadera", "camiseta", "chaqueta", "color", "colores",
    "tienda", "ropa", "disponible", "unidades", "muestrame", "ensename", "quedan", "en", "de",
    "la", "el", "los", "las", "un", "una", "con", "por", "del", "mi", "mis", "tu", "tus",
}
_ENGLISH_MARKERS = {
    "the", "do", "does", "you", "your", "have", "has", "is", "are", "what", "which", "how",
    "many", "much", "in", "of", "for", "with", "this", "that", "and", "any", "some", "show",
    "me", "sell", "stock", "size", "sizes", "price", "left", "there", "it", "them", "my", "a",
    "an", "to", "on", "at", "can", "i", "we", "please", "thanks", "hoodie", "hoodies", "shirt",
}


def detect_language(message: str) -> str | None:
    """Best-effort guess at the language of one message: 'es', 'en', or None.

    Looks for accents, inverted punctuation, and common words. Product names
    are English even in Spanish messages, so a Spanish verdict needs a clear
    margin. Used only to make the auto-language rule explicit for the model.
    """
    lowered = message.lower()
    spanish = 0
    if any(ch in lowered for ch in "¿¡"):
        spanish += 3
    if any(ch in lowered for ch in "áéíóúñü"):
        spanish += 2
    words = re.findall(r"[a-záéíóúñü]+", lowered)
    stripped = [re.sub(r"[áéíóúñü]", lambda m: {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", "ü": "u"}[m.group()], w) for w in words]
    spanish += sum(1 for w in stripped if w in _SPANISH_MARKERS)
    english = sum(1 for w in stripped if w in _ENGLISH_MARKERS)
    if spanish == 0 and english == 0:
        return None
    if spanish >= english + 1:
        return "es"
    if english >= spanish + 1:
        return "en"
    return None


def focus_product(deps: ShopDeps) -> FocusProduct | None:
    """The product the conversation is about right now, with full, fresh details.

    The page the shopper is on wins. Otherwise, the product the assistant showed
    most recently in this conversation. None if neither exists.
    """
    if deps.current_product_id:
        product = tools.get_product(deps.conn, deps.current_product_id)
        if product:
            return FocusProduct(**ProductDetails.from_product(product).model_dump(), source="viewing now")
    for pid in deps.recent_product_ids:
        product = tools.get_product(deps.conn, pid)
        if product:
            return FocusProduct(**ProductDetails.from_product(product).model_dump(), source="discussed most recently")
    return None


# --------------------------------------------------------------------------
# The agent
# --------------------------------------------------------------------------

# The model is supplied at run time (see run_agent) so the rest of the API
# still works when no LLM key is configured. ``instructions`` is a function,
# so the prompt file is consulted on every run.
#
# Every tool is registered with ``sequential=True``. The model sometimes asks
# for two tools in one step (for example get_current_product and
# get_shopper_profile), and PydanticAI would run them in parallel threads.
# They share one SQLite connection, which must not be used from two threads
# at once, so tools run one after another instead.
agent: Agent[ShopDeps, AgentReply] = Agent(
    name="campus_customs_assistant",
    deps_type=ShopDeps,
    output_type=AgentReply,
    instructions=load_prompt,
    retries=2,
)


@agent.instructions
def shopper_context(ctx: RunContext[ShopDeps]) -> str:
    """Dynamic instructions: language, who the shopper is, and which product is in focus."""
    lines: list[str] = []

    if ctx.deps.language == "es":
        lines.append("Language preference: reply in Spanish, whatever language the shopper writes in.")
    elif ctx.deps.language == "en":
        lines.append("Language preference: reply in English, whatever language the shopper writes in.")
    elif ctx.deps.detected_language == "es":
        lines.append(
            "Language: the shopper's latest message is in Spanish. Reply in Spanish, even if earlier "
            "messages were in English."
        )
    elif ctx.deps.detected_language == "en":
        lines.append(
            "Language: the shopper's latest message is in English. Reply in English, even if earlier "
            "messages were in Spanish."
        )
    else:
        lines.append(
            "Language: reply in the language of the shopper's latest message, English or Spanish. "
            "If they switch, switch with them."
        )

    user = ctx.deps.user
    if user:
        lines.append(
            f"The shopper is logged in as {user.first_name} {user.last_name} ({user.email}). "
            f"Call them {user.first_name} when it feels natural. "
            "Call get_shopper_profile if you need their account details or what they looked at before."
        )
    else:
        lines.append(
            "The shopper is not logged in, so you do not know their name. "
            "Do not guess it or ask for it; they can log in to be remembered."
        )

    focus = focus_product(ctx.deps)
    if focus is None:
        lines.append(
            "No product is in focus yet. If the shopper says 'this' or 'it' without naming an item, "
            "ask which item they mean or search for it."
        )
    elif focus.source == "viewing now":
        lines.append(
            "The shopper is on the page for the item below right now. When they say 'this', 'it', "
            "'this one', or ask about an item without naming it, they mean THIS item, even if earlier "
            "messages were about something else. Its full details, fresh from the database: "
            f"{focus.model_dump_json()}"
        )
    else:
        lines.append(
            "The shopper is not on a product page. The item discussed most recently in this "
            "conversation is below; 'it' or 'this' means this item unless they name another. "
            f"Its full details, fresh from the database: {focus.model_dump_json()}"
        )
    return "\n".join(lines)


def _status(quantity: int) -> StockStatus:
    if quantity == 0:
        return "out of stock"
    if quantity <= LOW_STOCK_THRESHOLD:
        return "low stock"
    return "in stock"


@agent.tool(sequential=True)
def search_products(ctx: RunContext[ShopDeps], query: str, max_results: int = 12) -> SearchResult:
    """Search the catalogue by keywords.

    Good queries are short: a garment type ("hoodie", "fleece", "quarter zip",
    "t-shirt"), a residential college or school ("Saybrook", "Law School"), a
    sport ("hockey"), a family word ("Dad", "Grandma"), a color ("navy"), or a
    slogan word ("bulldog"). Returns total_matches plus up to max_results
    products (best matches first) with price and the sizes currently in stock.
    For a category question ("what hoodies do you have?") ask for
    max_results=25 and put every returned product_id in product_ids so the
    page can show them all as cards. If total_matches is still larger than the
    list, tell the shopper there are more. total_matches of 0 means nothing in
    the store matches those words.
    """
    max_results = max(1, min(max_results, 25))
    hits = tools.search_products(ctx.deps.conn, query, max_results=500)
    return SearchResult(
        query=query,
        total_matches=len(hits),
        results=[ProductSummary.from_product(p) for p in hits[:max_results]],
    )


@agent.tool(sequential=True)
def get_product_details(ctx: RunContext[ShopDeps], product_id: str) -> ProductDetails | str:
    """Full details for one product: description, colors, price, tags, and the
    quantity in stock for every size. Use the product_id from a search result."""
    product = tools.get_product(ctx.deps.conn, product_id)
    if product is None:
        return f"No product with id '{product_id}'. Use search_products to find the right id."
    return ProductDetails.from_product(product)


@agent.tool(sequential=True)
def get_current_product(ctx: RunContext[ShopDeps]) -> FocusProduct | str:
    """The product the conversation is about right now, with full details fresh
    from the database: the item whose page the shopper is on, or else the item
    shown most recently in this conversation. Use it whenever the shopper says
    'this', 'it', or 'this one', or asks about color, size, price, or stock
    without naming an item."""
    focus = focus_product(ctx.deps)
    if focus is None:
        return "No product is in focus: the shopper is not on a product page and none has been discussed yet. Ask which item they mean, or search."
    return focus


@agent.tool(sequential=True)
def check_stock(ctx: RunContext[ShopDeps], product_id: str, size: str | None = None) -> StockCheck | str:
    """Check how many units of a product are in stock, for one size (XS, S, M,
    L, XL, XXL) or for every size when size is omitted. Quantities of 1 to 5
    count as low stock."""
    product = tools.get_product(ctx.deps.conn, product_id)
    if product is None:
        return f"No product with id '{product_id}'. Use search_products to find the right id."

    items = product.inventory
    note = None
    if size:
        wanted = tools.stock_for_size(product, size)
        if wanted is None:
            carried = ", ".join(item.size for item in product.inventory)
            note = f"Size {size.strip().upper()} is not carried for this product. Sizes carried: {carried}."
            items = []
        else:
            items = [wanted]

    sizes = [SizeStock(size=item.size, quantity=item.quantity, status=_status(item.quantity)) for item in items]
    return StockCheck(
        product_id=product.product_id,
        name=product.name,
        price_usd=product.price,
        sizes=sizes,
        out_of_stock_sizes=[s.size for s in sizes if s.quantity == 0],
        summary=note or _stock_summary(product.name, sizes),
        note=note,
    )


def _stock_summary(name: str, sizes: list[SizeStock]) -> str:
    """Spell out the stock position so the model has no room to blur it."""
    if len(sizes) == 1:
        s = sizes[0]
        if s.quantity == 0:
            return f"{name} in size {s.size} is OUT OF STOCK right now (0 left)."
        qualifier = " (low stock)" if s.status == "low stock" else ""
        return f"{name} in size {s.size}: {s.quantity} in stock{qualifier}."
    in_stock = [f"{s.size} ({s.quantity})" for s in sizes if s.status == "in stock"]
    low = [f"{s.size} ({s.quantity})" for s in sizes if s.status == "low stock"]
    out = [s.size for s in sizes if s.quantity == 0]
    parts = [f"{name}:"]
    parts.append("In stock: " + (", ".join(in_stock) if in_stock else "none") + ".")
    if low:
        parts.append("Low stock: " + ", ".join(low) + ".")
    parts.append("OUT OF STOCK: " + (", ".join(out) if out else "none") + ".")
    return " ".join(parts)


@agent.tool(sequential=True)
def list_garment_types(ctx: RunContext[ShopDeps]) -> CatalogueOverview:
    """What kinds of garments the store sells, with a product count for each,
    plus the overall price range. Useful for 'what do you have?' questions."""
    low, high = tools.price_range(ctx.deps.conn)
    return CatalogueOverview(
        garment_types=[
            GarmentTypeCount(type=name, products=count) for name, count in tools.list_garment_types(ctx.deps.conn)
        ],
        min_price_usd=low,
        max_price_usd=high,
    )


@agent.tool(sequential=True)
def get_shopper_profile(ctx: RunContext[ShopDeps]) -> ShopperProfile:
    """Who is chatting: name, email, when they joined, how many saved messages
    they have, and the products shown to them most recently (across visits).
    Use it to greet a returning shopper, answer 'do you remember me?', or pick
    up where they left off. For anonymous visitors it says so."""
    user = ctx.deps.user
    if user is None:
        return ShopperProfile(
            logged_in=False,
            recently_discussed=_recent_products(ctx.deps),
            note="Anonymous visitor: no name or email on record. Nothing is saved between visits unless they log in.",
        )
    return ShopperProfile(
        logged_in=True,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        member_since=user.created_at,
        messages_on_record=tools.count_messages_for_user(ctx.deps.conn, user.id),
        recently_discussed=_recent_products(ctx.deps),
        note="Use the first name naturally. Mention past items only when relevant. Never share this with anyone else.",
    )


def _recent_products(deps: ShopDeps) -> list[RecentProduct]:
    recent: list[RecentProduct] = []
    for pid in deps.recent_product_ids[:5]:
        product = tools.get_product(deps.conn, pid)
        if product:
            recent.append(RecentProduct(product_id=product.product_id, name=product.name))
    return recent


# --------------------------------------------------------------------------
# Guardrail: the reply must be backed by the database
# --------------------------------------------------------------------------
#
# The prompt tells the model not to invent prices or products. This validator
# enforces it. PydanticAI runs it on every AgentReply before the run ends; if
# it raises ModelRetry, the objection is sent back to the model, which must
# produce a corrected reply (up to the agent's retry limit).

CATALOGUE_TOOLS = {"search_products", "get_product_details", "get_current_product", "check_stock", "list_garment_types"}
PRICE_PATTERN = re.compile(r"\$\s?(\d{1,4}(?:\.\d{1,2})?)")


def _collect_prices(value: Any, found: set[float]) -> None:
    """Recursively gather every price_usd value inside a tool result."""
    if isinstance(value, BaseModel):
        value = value.model_dump()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "price_usd" and isinstance(item, (int, float)):
                found.add(float(item))
            else:
                _collect_prices(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_prices(item, found)


def _evidence_this_run(messages: list[ModelMessage]) -> tuple[set[str], set[float]]:
    """Which catalogue tools were called in this run, and which prices they returned."""
    tools_called: set[str] = set()
    prices_seen: set[float] = set()
    for message in messages:
        if isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    tools_called.add(part.tool_name)
        elif isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, ToolReturnPart):
                    _collect_prices(part.content, prices_seen)
    return tools_called, prices_seen


def find_reply_problems(
    reply: AgentReply,
    conn: sqlite3.Connection,
    tools_called: set[str],
    prices_seen: set[float],
    focus: Product | None = None,
) -> list[str]:
    """Return objections to a reply, or an empty list if it checks out.

    ``focus`` is the product in context (page or last discussed); its details
    were loaded from the database for this request, so quoting its price
    without a fresh tool call is allowed. Kept free of PydanticAI types so it
    can be unit-tested directly.
    """
    problems: list[str] = []

    referenced = {p.product_id: p for p in tools.fetch_products(conn, reply.product_ids)} if reply.product_ids else {}
    unknown = [pid for pid in reply.product_ids if pid not in referenced]
    if unknown:
        problems.append(
            f"These product_ids do not exist in the catalogue: {unknown}. "
            "Only use product_id values returned by the tools."
        )

    quoted = {float(p) for p in PRICE_PATTERN.findall(reply.reply)}

    looked_up = bool(tools_called & CATALOGUE_TOOLS)
    if (quoted or reply.product_ids) and not looked_up and focus is None:
        problems.append(
            "You quoted prices or picked products without looking anything up this turn. "
            "Call search_products, get_product_details, or check_stock first and answer from the results."
        )

    if quoted:
        allowed = set(prices_seen) | {p.price for p in referenced.values()}
        if focus is not None:
            allowed.add(focus.price)
        wrong = sorted(price for price in quoted if price not in allowed)
        if wrong:
            problems.append(
                f"These prices do not match the catalogue for the products you looked up: "
                f"{['$%g' % p for p in wrong]}. Quote prices exactly as the tools returned them."
            )

    return problems


def required_language(deps: ShopDeps) -> str | None:
    """'en' or 'es' when the reply language is settled, else None."""
    if deps.language in ("en", "es"):
        return deps.language
    return deps.detected_language


def wrong_language(reply: str, required: str | None) -> str | None:
    """An objection if the reply is confidently in the other language, else None.

    The detector needs a clear margin here so that short replies or English
    product names inside a Spanish sentence never trigger a false retry.
    """
    if required is None:
        return None
    lowered = reply.lower()
    words = re.findall(r"[a-záéíóúñü]+", lowered)
    stripped = [re.sub(r"[áéíóúñü]", lambda m: {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", "ü": "u"}[m.group()], w) for w in words]
    spanish = sum(1 for w in stripped if w in _SPANISH_MARKERS) + (2 if any(ch in lowered for ch in "áéíóúñ¿¡") else 0)
    english = sum(1 for w in stripped if w in _ENGLISH_MARKERS)
    if required == "en" and spanish >= english + 2:
        return "The reply must be in English (the shopper's language setting), not Spanish. Rewrite it in English, keeping the same facts."
    if required == "es" and english >= spanish + 2:
        return "La respuesta debe estar en español, no en inglés. Reescríbela en español con los mismos datos."
    return None


@agent.output_validator
def reply_is_grounded(ctx: RunContext[ShopDeps], output: AgentReply) -> AgentReply:
    tools_called, prices_seen = _evidence_this_run(ctx.messages)
    focus = focus_product(ctx.deps)
    focus_as_product = tools.get_product(ctx.deps.conn, focus.product_id) if focus else None
    problems = find_reply_problems(output, ctx.deps.conn, tools_called, prices_seen, focus_as_product)
    language_problem = wrong_language(output.reply, required_language(ctx.deps))
    if language_problem:
        problems.append(language_problem)
    if problems:
        raise ModelRetry(" ".join(problems))
    return output


# --------------------------------------------------------------------------
# Conversation memory
# --------------------------------------------------------------------------


def build_message_history(turns: list[ChatTurn]) -> list[ModelMessage]:
    """Turn stored (role, content) pairs into PydanticAI message objects.

    Only the text of earlier turns is replayed; tool calls from earlier runs
    are not needed because the facts they found are already in the replies.
    """
    history: list[ModelMessage] = []
    for turn in turns[-HISTORY_LIMIT:]:
        if turn.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=turn.content)]))
        else:
            history.append(ModelResponse(parts=[TextPart(content=turn.content)]))
    return history


def recent_product_ids_from_turns(turns: list[ChatTurn], limit: int = 5) -> list[str]:
    """Products shown in the conversation, newest first."""
    ids: list[str] = []
    for turn in reversed(turns):
        for pid in turn.product_ids:
            if pid not in ids:
                ids.append(pid)
            if len(ids) >= limit:
                return ids
    return ids


# --------------------------------------------------------------------------
# Running the agent
# --------------------------------------------------------------------------


def _with_page_context(message: str, deps: ShopDeps) -> str:
    """Attach the viewed item to the shopper's message.

    The same fact is in the instructions, but a note right next to the
    question is weighed more heavily by the model. This is what makes
    "how many larges of this one?" refer to the page the shopper is on, even
    when the conversation so far was about a different item.
    """
    notes: list[str] = []
    if deps.current_product_id:
        product = tools.get_product(deps.conn, deps.current_product_id)
        if product is not None:
            notes.append(
                f'[Page context: the shopper is viewing "{product.name}" (product_id {product.product_id}). '
                '"This", "it", and "this one" refer to that item.]'
            )
    # The language rule also goes next to the message: in a conversation that
    # has switched languages, an instruction far away loses to the recent turns.
    if deps.language == "es":
        notes.append("[Language: reply in Spanish, whatever language this message is in.]")
    elif deps.language == "en":
        notes.append("[Language: reply in English, whatever language this message is in.]")
    elif deps.detected_language == "es":
        notes.append("[Language: this message is in Spanish; reply in Spanish.]")
    elif deps.detected_language == "en":
        notes.append("[Language: this message is in English; reply in English.]")
    if not notes:
        return message
    return message + "\n\n" + "\n".join(notes)


def _audit_actor(deps: ShopDeps) -> dict[str, Any]:
    if deps.user is None:
        return {"guest": True}
    return {"user_id": deps.user.id, "email": deps.user.email, "first_name": deps.user.first_name}


def _audit_request(message: str, deps: ShopDeps, history: list[ChatTurn]) -> dict[str, Any]:
    return {
        "message": message,
        "language": deps.language,
        "detected_language": deps.detected_language,
        "page_product_id": deps.current_product_id,
        "recent_product_ids": list(deps.recent_product_ids),
        "history_turns": len(history),
    }


async def run_agent(message: str, deps: ShopDeps, history: list[ChatTurn]) -> AgentReply:
    """One conversational turn. Raises AgentNotConfigured if there is no LLM key.

    Every run, successful or not, appends one record to output/audit_trail.json
    with the tool calls, validator retries, usage, and the final reply.
    """
    if not deps.recent_product_ids:
        deps.recent_product_ids = recent_product_ids_from_turns(history)
    if deps.language == "auto":
        deps.detected_language = detect_language(message)

    run_id, started_at, clock = audit_trail.new_run_id(), audit_trail.utc_now(), time.perf_counter()
    audit = dict(agent="shop_assistant", run_id=run_id, started_at=started_at, model=MODEL_NAME,
                 prompt_file=PROMPT_PATH, actor=_audit_actor(deps), request=_audit_request(message, deps, history))

    with capture_run_messages() as messages:  # keeps the loop's messages even if the run raises
        try:
            result = await agent.run(
                _with_page_context(message, deps),
                deps=deps,
                model=get_model(),
                message_history=build_message_history(history),
            )
        except Exception as exc:
            audit_trail.record(**audit, duration_ms=int((time.perf_counter() - clock) * 1000), messages=list(messages), error=exc)
            raise

    output = result.output
    output.product_ids = output.product_ids[:MAX_PRODUCTS_PER_REPLY]
    audit_trail.record(**audit, duration_ms=int((time.perf_counter() - clock) * 1000), messages=result.new_messages(),
                       usage=result.usage, output={"reply": output.reply, "product_ids": list(output.product_ids)})
    return output
