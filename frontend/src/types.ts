// Shared TypeScript types. These mirror the Pydantic models in
// backend/models.py, so a change on one side should be reflected on the other.

export interface InventoryItem {
  size: string
  quantity: number
}

export interface Product {
  product_id: string
  name: string
  garment_type: string
  description: string
  colors: string[]
  search_tags: string[]
  image_file_path: string
  image_url: string
  price: number
  inventory: InventoryItem[]
  total_stock: number
}

// What the page needs to draw one product card. Chat replies carry these.
// A full Product also satisfies this shape (sizes_in_stock is optional).
export interface ProductCard {
  product_id: string
  name: string
  garment_type: string
  description: string
  price: number
  image_url: string
  sizes_in_stock?: string[]
  total_stock: number
}

// One line in the shopping cart. Kept in the browser only; nothing is ordered.
export interface CartItem {
  product_id: string
  name: string
  image_url: string
  price: number
  size: string
  quantity: number
  // Units in stock for this size when it was added; quantity is capped at this.
  max_quantity: number
}

export interface User {
  id: number
  first_name: string
  last_name: string
  email: string
  created_at: string
  // True for the store owner's account, who can see inventory notes.
  is_owner: boolean
}

// ---------- Inventory tracking (owner features) ----------

// "order" is reserved: checkout is a demo, so add_to_cart is the order signal.
export type ProductEventType = 'view' | 'click' | 'add_to_cart' | 'order'

export type NoteKind = 'reorder' | 'do_not_reorder'

export interface OwnerNote {
  id: number
  kind: NoteKind
  product_id: string
  product_name: string
  size: string | null
  message: string
  status: 'open' | 'resolved'
  created_at: string
}

export interface LowStockLine {
  product_id: string
  name: string
  size: string
  quantity: number
  par_level: number
  percent_of_par: number
}

export interface EngagementLine {
  product_id: string
  name: string
  views: number
  clicks: number
  add_to_cart_units: number
  order_units: number
  flagged_do_not_reorder: boolean
}

export interface InventoryReport {
  generated_at: string
  par_level: number
  reorder_threshold_percent: number
  window_days: number
  min_views_to_flag: number
  low_stock: LowStockLine[]
  engagement: EngagementLine[]
  flagged_reorder_products: string[]
  flagged_do_not_reorder_products: string[]
}

export interface ReviewResult {
  notes_created: OwnerNote[]
  summary: string
  used_agent: boolean
}

export type ChatRole = 'user' | 'assistant'

// "auto" = the assistant replies in whatever language the shopper writes in.
export type ChatLanguage = 'auto' | 'en' | 'es'

// One earlier message, sent to the server for shoppers who are not logged in.
// product_ids lists the products shown with that message, so the assistant
// knows what "it" referred to last even without a product page open.
export interface ChatTurn {
  role: ChatRole
  content: string
  product_ids: string[]
}

// A message as shown in the chat panel.
export interface ChatMessage {
  role: ChatRole
  content: string
  products?: ProductCard[]
  // True for messages the browser made up itself (welcome text, error notes).
  // These are never sent to the server as conversation history.
  local?: boolean
}

// One assistant reply plus everything the page needs to act on it.
export interface ChatResponse {
  reply: string
  products: ProductCard[]
  user: User | null
}

export interface ChatHistoryMessage {
  id: number
  role: ChatRole
  content: string
  products: ProductCard[]
  created_at: string
}
