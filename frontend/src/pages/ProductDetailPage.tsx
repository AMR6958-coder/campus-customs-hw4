import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, fetchProduct, trackEvent } from '../api'
import { useCart } from '../CartContext'
import { formatPrice } from '../format'
import type { InventoryItem, Product } from '../types'

type Status = 'loading' | 'ready' | 'missing' | 'error'

const LOW_STOCK = 5

function stockText(item: InventoryItem): { text: string; className: string } {
  if (item.quantity === 0) return { text: 'Out of stock', className: 'stock-out' }
  if (item.quantity <= LOW_STOCK) return { text: `${item.quantity} left`, className: 'stock-low' }
  return { text: `${item.quantity} in stock`, className: 'stock-ok' }
}

export default function ProductDetailPage() {
  const { productId = '' } = useParams()
  const { addItem } = useCart()
  const [product, setProduct] = useState<Product | null>(null)
  const [status, setStatus] = useState<Status>('loading')
  const [selectedSize, setSelectedSize] = useState<string | null>(null)
  const [quantity, setQuantity] = useState(1)
  const [addedNote, setAddedNote] = useState('')

  useEffect(() => {
    let cancelled = false
    setStatus('loading')
    setAddedNote('')
    fetchProduct(productId)
      .then((data) => {
        if (cancelled) return
        setProduct(data)
        // Pre-select the first size that is actually in stock.
        const firstAvailable = data.inventory.find((item) => item.quantity > 0)
        setSelectedSize(firstAvailable ? firstAvailable.size : null)
        setQuantity(1)
        setStatus('ready')
        trackEvent(data.product_id, 'view')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setStatus(err instanceof ApiError && err.status === 404 ? 'missing' : 'error')
      })
    return () => {
      cancelled = true
    }
  }, [productId])

  if (status === 'loading') return <div className="status">Loading…</div>
  if (status === 'missing') {
    return (
      <div className="status">
        We couldn't find that item. <Link to="/products">Back to all products</Link>
      </div>
    )
  }
  if (status === 'error' || !product) {
    return <div className="status error">Couldn't load this item. Is the back end running?</div>
  }

  const selected = product.inventory.find((item) => item.size === selectedSize) ?? null
  const maxQuantity = selected?.quantity ?? 0
  const canAdd = selected !== null && maxQuantity > 0

  function handleAdd() {
    if (!product || !selected || selected.quantity === 0) return
    const qty = Math.max(1, Math.min(quantity, selected.quantity))
    addItem(
      {
        product_id: product.product_id,
        name: product.name,
        image_url: product.image_url,
        price: product.price,
        size: selected.size,
        max_quantity: selected.quantity,
      },
      qty,
    )
    setAddedNote(`Added ${qty} × ${product.name} (size ${selected.size}) to your cart.`)
    trackEvent(product.product_id, 'add_to_cart', selected.size, qty)
  }

  return (
    <>
      <Link to="/products" className="back-link">
        ← All products
      </Link>
      <div className="product-detail">
        <div className="product-info">
          <p className="eyebrow">{product.garment_type}</p>
          <h1>{product.name}</h1>
          <p className="price">{formatPrice(product.price)}</p>
          <p className="desc">{product.description}</p>

          <h3>Colors</h3>
          <div className="chips">
            {product.colors.map((color) => (
              <span className="chip" key={color}>
                {color}
              </span>
            ))}
          </div>

          <h3>Choose a size</h3>
          <div className="size-picker" role="radiogroup" aria-label="Size">
            {product.inventory.map((item) => {
              const stock = stockText(item)
              const isSelected = selectedSize === item.size
              return (
                <button
                  type="button"
                  key={item.size}
                  className={`size-option${isSelected ? ' selected' : ''}`}
                  disabled={item.quantity === 0}
                  aria-pressed={isSelected}
                  onClick={() => {
                    setSelectedSize(item.size)
                    setQuantity(1)
                    setAddedNote('')
                  }}
                >
                  <span className="size-option-size">{item.size}</span>
                  <span className={`size-option-stock ${stock.className}`}>{stock.text}</span>
                </button>
              )
            })}
          </div>
          <p className="total-stock">{product.total_stock} units in stock across all sizes.</p>

          <div className="add-to-cart">
            <label className="qty">
              <span>Qty</span>
              <input
                type="number"
                min={1}
                max={Math.max(1, maxQuantity)}
                value={quantity}
                disabled={!canAdd}
                onChange={(event) => {
                  const next = Number.parseInt(event.target.value, 10)
                  setQuantity(Number.isNaN(next) ? 1 : Math.max(1, Math.min(next, maxQuantity)))
                }}
              />
            </label>
            <button type="button" className="btn" disabled={!canAdd} onClick={handleAdd}>
              {canAdd ? 'Add to cart' : 'Sold out'}
            </button>
          </div>
          {addedNote && (
            <p className="added-note" role="status">
              {addedNote} <Link to="/cart">View cart →</Link>
            </p>
          )}
        </div>

        <div className="product-image">
          <img src={product.image_url} alt={product.name} />
        </div>
      </div>
    </>
  )
}
