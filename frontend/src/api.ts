// Thin client for the FastAPI back end. Every call to the server goes through
// this file, so if the API changes there is exactly one place to update.
//
// Authentication uses a session cookie set by the back end. Because the Vite
// dev server proxies /api to the back end, requests are same-origin and the
// browser attaches the cookie automatically.

import type {
  ChatHistoryMessage,
  ChatLanguage,
  ChatResponse,
  ChatTurn,
  InventoryReport,
  OwnerNote,
  Product,
  ProductEventType,
  ReviewResult,
  User,
} from './types'

const API_BASE = '/api'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

// Pull a readable message out of a FastAPI error body. Validation errors
// (422) arrive as a list of {msg, loc, ...}; everything else as {detail: str}.
async function errorMessage(response: Response): Promise<string> {
  const fallback = `${response.status} ${response.statusText}`
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && 'detail' in body) {
      const detail = (body as { detail: unknown }).detail
      if (typeof detail === 'string') return detail
      if (Array.isArray(detail)) {
        const messages = detail
          .map((item: unknown) => {
            if (item && typeof item === 'object' && 'msg' in item) {
              const loc = (item as { loc?: unknown[] }).loc ?? []
              const field = String(loc[loc.length - 1] ?? '')
              const msg = String((item as { msg: unknown }).msg).replace(/^Value error, /, '')
              return field ? `${field}: ${msg}` : msg
            }
            return null
          })
          .filter((m): m is string => Boolean(m))
        if (messages.length) return messages.join('; ')
      }
    }
  } catch {
    // body was not JSON
  }
  return fallback
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: 'same-origin', ...init })
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

// ---------- Products ----------

export function fetchProducts(): Promise<Product[]> {
  return request<Product[]>('/products')
}

export function fetchProduct(productId: string): Promise<Product> {
  return request<Product>(`/products/${encodeURIComponent(productId)}`)
}

// ---------- Accounts ----------

export interface RegisterInput {
  first_name: string
  last_name: string
  email: string
  password: string
}

export function register(input: RegisterInput): Promise<User> {
  return postJson<User>('/auth/register', input)
}

export function login(email: string, password: string): Promise<User> {
  return postJson<User>('/auth/login', { email, password })
}

export function logout(): Promise<void> {
  return request<void>('/auth/logout', { method: 'POST' })
}

// Returns the logged-in user, or null if there is no valid session.
export async function fetchCurrentUser(): Promise<User | null> {
  try {
    return await request<User>('/auth/me')
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null
    throw err
  }
}

// ---------- Chat ----------

// Sends one chat turn to the shopping assistant.
// - `productId` tells it which item the shopper is looking at, so
//   "do you have this in blue?" makes sense.
// - `history` is the recent conversation. It only matters for shoppers who
//   are not logged in; logged-in shoppers' history lives on the server.
// - `language` is "auto" (mirror the shopper), "en", or "es".
export function sendChat(
  message: string,
  productId: string | undefined,
  history: ChatTurn[],
  language: ChatLanguage = 'auto',
): Promise<ChatResponse> {
  return postJson<ChatResponse>('/chat', {
    message,
    product_id: productId ?? null,
    history,
    language,
  })
}

// A logged-in shopper's saved conversation, oldest first.
export function fetchChatHistory(): Promise<ChatHistoryMessage[]> {
  return request<ChatHistoryMessage[]>('/chat/history')
}

// ---------- Product events (views, clicks, add-to-carts) ----------

// Fire-and-forget: tracking must never slow down or break the page.
export function trackEvent(
  productId: string,
  eventType: ProductEventType,
  size?: string,
  quantity = 1,
): void {
  fetch(`${API_BASE}/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    keepalive: true,
    body: JSON.stringify({ product_id: productId, event_type: eventType, size: size ?? null, quantity }),
  }).catch(() => {
    // ignore: analytics only
  })
}

// ---------- Owner: inventory report and notes ----------

export function fetchOwnerReport(): Promise<InventoryReport> {
  return request<InventoryReport>('/owner/report')
}

export function fetchOwnerNotes(includeResolved = false): Promise<OwnerNote[]> {
  return request<OwnerNote[]>(`/owner/notes?include_resolved=${includeResolved}`)
}

export function resolveOwnerNote(noteId: number): Promise<OwnerNote> {
  return request<OwnerNote>(`/owner/notes/${noteId}/resolve`, { method: 'POST' })
}

export function runOwnerReview(): Promise<ReviewResult> {
  return request<ReviewResult>('/owner/review', { method: 'POST' })
}
