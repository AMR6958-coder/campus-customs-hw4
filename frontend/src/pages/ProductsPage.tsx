import { useEffect, useState } from 'react'
import { fetchProducts } from '../api'
import ProductCard from '../components/ProductCard'
import type { Product } from '../types'

type Status = 'loading' | 'ready' | 'error'

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([])
  const [status, setStatus] = useState<Status>('loading')
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    fetchProducts()
      .then((data) => {
        if (cancelled) return
        setProducts(data)
        setStatus('ready')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <>
      <p className="eyebrow">The catalogue</p>
      <h1 className="page-title">All Products</h1>
      <p className="page-subtitle">
        {status === 'ready'
          ? `${products.length} items, all in stock somewhere on the shelf.`
          : 'Browse the full Campus Customs catalogue.'}
      </p>

      {status === 'loading' && <div className="status">Loading products…</div>}
      {status === 'error' && (
        <div className="status error">
          Couldn't load products. Is the back end running? ({error})
        </div>
      )}
      {status === 'ready' && (
        <div className="product-grid">
          {products.map((product) => (
            <ProductCard key={product.product_id} product={product} />
          ))}
        </div>
      )}
    </>
  )
}
