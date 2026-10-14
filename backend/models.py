"""Pydantic models: the shapes of data the API sends and receives, and the
shapes the agent's tools return to the model.

The TypeScript interfaces in frontend/src/types.ts mirror the API models
one-to-one. The tool-result models exist so that the model always sees the
same field names, and so that type checkers catch mistakes in agent.py.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

LOW_STOCK_THRESHOLD = 5

# --------------------------------------------------------------------------
# Products (API)
# --------------------------------------------------------------------------


class InventoryItem(BaseModel):
    size: str
    quantity: int


class Product(BaseModel):
    """A full catalogue record with inventory. Used by the product pages."""

    product_id: str
    name: str
    garment_type: str
    description: str
    colors: list[str]
    search_tags: list[str]
    image_file_path: str
    image_url: str
    price: float
    inventory: list[InventoryItem]
    total_stock: int

    def sizes_in_stock(self) -> list[str]:
        return [item.size for item in self.inventory if item.quantity > 0]

    def low_stock_sizes(self) -> list[str]:
        return [item.size for item in self.inventory if 0 < item.quantity <= LOW_STOCK_THRESHOLD]

    def sizes_out_of_stock(self) -> list[str]:
        """Sizes we carry but currently have zero of."""
        return [item.size for item in self.inventory if item.quantity == 0]


class ProductCard(BaseModel):
    """What the page needs to draw one product card.

    Chat replies carry these instead of full Product records: enough to show
    a photo, name, price, blurb, and availability, and to link to the item.
    """

    product_id: str
    name: str
    garment_type: str
    description: str
    price: float
    image_url: str
    sizes_in_stock: list[str] = Field(default_factory=list)
    total_stock: int

    @classmethod
    def from_product(cls, product: Product) -> ProductCard:
        return cls(
            product_id=product.product_id,
            name=product.name,
            garment_type=product.garment_type,
            description=product.description,
            price=product.price,
            image_url=product.image_url,
            sizes_in_stock=product.sizes_in_stock(),
            total_stock=product.total_stock,
        )


# --------------------------------------------------------------------------
# Users (API)
# --------------------------------------------------------------------------


class UserOut(BaseModel):
    """What the API reveals about a user. Never includes the password hash."""

    id: int
    first_name: str
    last_name: str
    email: str
    created_at: str
    # True for the store owner's account (OWNER_EMAIL), who can see inventory notes.
    is_owner: bool = False


# --------------------------------------------------------------------------
# Chat (API)
# --------------------------------------------------------------------------

Role = Literal["user", "assistant"]

# "auto" = reply in whatever language the shopper writes in (English or Spanish).
ChatLanguage = Literal["auto", "en", "es"]


class ChatTurn(BaseModel):
    """One earlier message in the conversation.

    Loaded from chat_messages for logged-in shoppers, or sent by the browser
    for anonymous ones. ``product_ids`` lists the products that were shown
    with the message, so the server knows what "it" referred to last.
    """

    role: Role
    content: str = Field(max_length=4000)
    product_ids: list[str] = Field(default_factory=list, max_length=24)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # The product the shopper is currently viewing, if any.
    product_id: str | None = None
    # Recent conversation, used only when the shopper is not logged in.
    # Logged-in shoppers' history is stored on the server instead.
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    # Reply language. "auto" mirrors the shopper; "en" / "es" force one.
    language: ChatLanguage = "auto"


class ChatResponse(BaseModel):
    """One assistant reply plus everything the page needs to act on it."""

    reply: str
    # Cards the page should display for this reply, in the assistant's order.
    products: list[ProductCard]
    # Who the server thinks is logged in (None for anonymous shoppers).
    user: UserOut | None


class ChatHistoryMessage(BaseModel):
    """A saved message, as returned by GET /api/chat/history."""

    id: int
    role: Role
    content: str
    products: list[ProductCard]
    created_at: str


# --------------------------------------------------------------------------
# Product events and owner notes (inventory tracking)
# --------------------------------------------------------------------------

# "order" is reserved: checkout is a demo, so add_to_cart is the order signal.
ProductEventType = Literal["view", "click", "add_to_cart", "order"]
NoteKind = Literal["reorder", "do_not_reorder"]
NoteStatus = Literal["open", "resolved"]


class ProductEventIn(BaseModel):
    """One shopper interaction with a product, sent by the browser."""

    product_id: str
    event_type: ProductEventType
    size: str | None = None
    quantity: int = Field(default=1, ge=1, le=100)


class OwnerNote(BaseModel):
    """A note from the inventory assistant to the store owner."""

    id: int
    kind: NoteKind
    product_id: str
    product_name: str
    size: str | None = None
    message: str
    status: NoteStatus
    created_at: str


class LowStockLine(BaseModel):
    product_id: str
    name: str
    size: str
    quantity: int
    par_level: int = Field(description="Units a full size slot holds.")
    percent_of_par: float


class EngagementLine(BaseModel):
    product_id: str
    name: str
    views: int = Field(description="Item page opens in the window.")
    clicks: int = Field(description="Product card clicks in the window.")
    add_to_cart_units: int = Field(description="Units added to carts in the window (the order signal in this demo).")
    order_units: int = Field(default=0, description="Reserved for real orders; always 0 in the demo.")
    flagged_do_not_reorder: bool = Field(description="Enough attention, zero add-to-carts.")


class InventoryReport(BaseModel):
    generated_at: str
    par_level: int
    reorder_threshold_percent: int
    window_days: int
    min_views_to_flag: int
    low_stock: list[LowStockLine] = Field(description="Every size at or below the reorder line.")
    engagement: list[EngagementLine] = Field(description="Per-product activity in the window, most viewed first.")
    flagged_reorder_products: list[str] = Field(description="product_ids with at least one low size, most urgent first.")
    flagged_do_not_reorder_products: list[str] = Field(description="product_ids viewed but never added to a cart.")
    max_notes_per_review: int = Field(description="How many products of each kind one review handles.")
    reorder_queue: list[str] = Field(
        description="The flagged reorder products to handle in this review: most urgent first, "
        "without an open reorder note, capped at max_notes_per_review."
    )
    do_not_reorder_queue: list[str] = Field(
        description="The flagged do-not-reorder products to handle in this review, without an open note, capped."
    )
    reorder_backlog: int = Field(description="Flagged reorder products left for later reviews.")
    do_not_reorder_backlog: int = Field(description="Flagged do-not-reorder products left for later reviews.")


class ReviewOutput(BaseModel):
    """What the inventory agent returns at the end of a review."""

    summary: str = Field(description="One short paragraph: what was sent, what was skipped and why.")


class ReviewResult(BaseModel):
    notes_created: list[OwnerNote]
    summary: str
    used_agent: bool = Field(description="False when no LLM key was configured and template notes were used.")


# --------------------------------------------------------------------------
# The agent's structured output
# --------------------------------------------------------------------------


class AgentReply(BaseModel):
    """What the agent must produce at the end of every run."""

    reply: str = Field(description="The message to show the shopper, in plain text.")
    product_ids: list[str] = Field(
        default_factory=list,
        description=(
            "product_id values of the items the shopper should see on the page as product cards, "
            "in the order they are mentioned. For a category question include every match "
            "received. Empty for greetings, small talk, or when nothing matched."
        ),
    )


# --------------------------------------------------------------------------
# What the agent's tools return to the model
# --------------------------------------------------------------------------


class ProductSummary(BaseModel):
    """Compact view of a product for the model: no image paths or long tag lists."""

    product_id: str
    name: str
    garment_type: str
    price_usd: float
    colors: list[str]
    sizes_in_stock: list[str]
    low_stock_sizes: list[str] = Field(description="Sizes with 1 to 5 units left.")
    sizes_out_of_stock: list[str] = Field(description="Sizes we carry but have 0 of right now.")
    total_stock: int

    @classmethod
    def from_product(cls, product: Product) -> ProductSummary:
        return cls(
            product_id=product.product_id,
            name=product.name,
            garment_type=product.garment_type,
            price_usd=product.price,
            colors=product.colors,
            sizes_in_stock=product.sizes_in_stock(),
            low_stock_sizes=product.low_stock_sizes(),
            sizes_out_of_stock=product.sizes_out_of_stock(),
            total_stock=product.total_stock,
        )


class ProductDetails(ProductSummary):
    """Everything about one product, including stock for every size."""

    description: str
    search_tags: list[str]
    stock_by_size: dict[str, int]

    @classmethod
    def from_product(cls, product: Product) -> ProductDetails:
        summary = ProductSummary.from_product(product)
        return cls(
            **summary.model_dump(),
            description=product.description,
            search_tags=product.search_tags,
            stock_by_size={item.size: item.quantity for item in product.inventory},
        )


class SearchResult(BaseModel):
    query: str
    total_matches: int = Field(description="How many products matched in total; 0 means nothing matched.")
    results: list[ProductSummary] = Field(description="Best matches first; may be fewer than total_matches.")


StockStatus = Literal["in stock", "low stock", "out of stock"]


class SizeStock(BaseModel):
    size: str
    quantity: int
    status: StockStatus


class StockCheck(BaseModel):
    product_id: str
    name: str
    price_usd: float
    sizes: list[SizeStock] = Field(description="Quantity and status per size (just the one size if one was asked for).")
    out_of_stock_sizes: list[str] = Field(description="Sizes in this result with 0 units. Tell the shopper plainly.")
    summary: str = Field(description="Plain-language summary of the stock position to relay to the shopper.")
    note: str | None = Field(default=None, description="Set when the requested size is not carried at all.")


class GarmentTypeCount(BaseModel):
    type: str
    products: int


class CatalogueOverview(BaseModel):
    garment_types: list[GarmentTypeCount]
    min_price_usd: float
    max_price_usd: float


class FocusProduct(ProductDetails):
    """The product the conversation is about right now, with full details."""

    source: Literal["viewing now", "discussed most recently"] = Field(
        description="'viewing now' = the shopper is on this item's page; "
        "'discussed most recently' = the last item the assistant showed in this conversation."
    )


class RecentProduct(BaseModel):
    product_id: str
    name: str


class ShopperProfile(BaseModel):
    """What the store knows about the person chatting. Never includes passwords."""

    logged_in: bool
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    member_since: str | None = Field(default=None, description="Account creation date (UTC).")
    messages_on_record: int = Field(default=0, description="Saved chat messages from earlier visits and this one.")
    recently_discussed: list[RecentProduct] = Field(
        default_factory=list, description="Products the assistant showed this shopper most recently, newest first."
    )
    note: str = Field(description="Guidance on how to use this profile.")
