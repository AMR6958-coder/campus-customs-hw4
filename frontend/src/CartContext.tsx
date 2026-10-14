// The shopping cart. Lives in the browser and is saved to localStorage so it
// survives reloads. Nothing here talks to the back end: this is a sample
// store, and the checkout page's "Place order" button is intentionally off.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import type { CartItem } from './types'

const STORAGE_KEY = 'campus-customs-cart'

function loadCart(): CartItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as CartItem[]) : []
  } catch {
    return []
  }
}

function saveCart(items: CartItem[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
  } catch {
    // Storage unavailable (private mode, blocked). The cart still works for this visit.
  }
}

const sameLine = (a: CartItem, productId: string, size: string) =>
  a.product_id === productId && a.size === size

interface CartState {
  items: CartItem[]
  /** Total units across all lines. Shown in the nav badge. */
  count: number
  subtotal: number
  addItem: (item: Omit<CartItem, 'quantity'>, quantity: number) => void
  setQuantity: (productId: string, size: string, quantity: number) => void
  removeItem: (productId: string, size: string) => void
  clearCart: () => void
}

const CartContext = createContext<CartState | null>(null)

export function CartProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<CartItem[]>(loadCart)

  useEffect(() => {
    saveCart(items)
  }, [items])

  const addItem = useCallback((item: Omit<CartItem, 'quantity'>, quantity: number) => {
    setItems((prev) => {
      const index = prev.findIndex((line) => sameLine(line, item.product_id, item.size))
      if (index === -1) {
        return [...prev, { ...item, quantity: Math.min(quantity, item.max_quantity) }]
      }
      const next = [...prev]
      const existing = next[index]
      next[index] = {
        ...existing,
        max_quantity: item.max_quantity,
        quantity: Math.min(existing.quantity + quantity, item.max_quantity),
      }
      return next
    })
  }, [])

  const setQuantity = useCallback((productId: string, size: string, quantity: number) => {
    setItems((prev) =>
      prev.map((line) =>
        sameLine(line, productId, size)
          ? { ...line, quantity: Math.max(1, Math.min(quantity, line.max_quantity)) }
          : line,
      ),
    )
  }, [])

  const removeItem = useCallback((productId: string, size: string) => {
    setItems((prev) => prev.filter((line) => !sameLine(line, productId, size)))
  }, [])

  const clearCart = useCallback(() => setItems([]), [])

  const value = useMemo(() => {
    const count = items.reduce((sum, line) => sum + line.quantity, 0)
    const subtotal = items.reduce((sum, line) => sum + line.price * line.quantity, 0)
    return { items, count, subtotal, addItem, setQuantity, removeItem, clearCart }
  }, [items, addItem, setQuantity, removeItem, clearCart])

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>
}

export function useCart(): CartState {
  const context = useContext(CartContext)
  if (!context) throw new Error('useCart must be used inside <CartProvider>')
  return context
}
