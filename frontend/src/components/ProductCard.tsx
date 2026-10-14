import { Link } from 'react-router-dom'
import { trackEvent } from '../api'
import { formatPrice, truncate } from '../format'
import type { ProductCard as ProductCardData } from '../types'

// Renders one product tile. Accepts either a full Product (product pages) or
// the lighter ProductCard the chat assistant returns; both have these fields.
// Clicking a card records a "click" event for the inventory report.
export default function ProductCard({ product }: { product: ProductCardData }) {
  return (
    <Link
      to={`/products/${product.product_id}`}
      className="product-card"
      onClick={() => trackEvent(product.product_id, 'click')}
    >
      <div className="thumb">
        <img src={product.image_url} alt={product.name} loading="lazy" />
      </div>
      <div className="body">
        <p className="eyebrow kind">{product.garment_type}</p>
        <p className="name">{product.name}</p>
        <span className="price">{formatPrice(product.price)}</span>
        <p className="desc">{truncate(product.description)}</p>
      </div>
    </Link>
  )
}
