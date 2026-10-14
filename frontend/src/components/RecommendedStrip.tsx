import { useEffect, useRef } from 'react'
import { usePicks } from '../PicksContext'
import ProductCard from './ProductCard'

// Shows the products the assistant most recently recommended, on whatever
// page the shopper is on. Hidden until the assistant picks something, and
// scrolled into view whenever a new set of picks arrives.
export default function RecommendedStrip() {
  const { picks, clearPicks } = usePicks()
  const ref = useRef<HTMLElement>(null)

  useEffect(() => {
    if (picks.length > 0) {
      ref.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [picks])

  if (picks.length === 0) return null

  return (
    <section ref={ref} className="picks" aria-label="Products picked by the assistant">
      <div className="section-head">
        <div>
          <p className="eyebrow">From your assistant</p>
          <h2>Picked for you</h2>
        </div>
        <button type="button" className="link-button" onClick={clearPicks}>
          Clear
        </button>
      </div>
      <p className="page-subtitle">
        {picks.length} {picks.length === 1 ? 'item' : 'items'} that match what you asked about.
        Click any card for sizes and stock.
      </p>
      <div className="product-grid">
        {picks.map((product) => (
          <ProductCard key={product.product_id} product={product} />
        ))}
      </div>
    </section>
  )
}
