import { Link } from 'react-router-dom'
import { useCart } from '../CartContext'
import { formatPrice } from '../format'

export default function CartPage() {
  const { items, count, subtotal, setQuantity, removeItem } = useCart()

  if (items.length === 0) {
    return (
      <>
        <p className="eyebrow">Your cart</p>
        <h1 className="page-title">Your cart is empty</h1>
        <p className="page-subtitle">
          Browse the catalogue, or ask the assistant what to wear to The Game.
        </p>
        <Link to="/products" className="btn">
          Shop all gear
        </Link>
      </>
    )
  }

  return (
    <>
      <p className="eyebrow">Your cart</p>
      <h1 className="page-title">Cart</h1>
      <p className="page-subtitle">
        {count} {count === 1 ? 'item' : 'items'}, ready when you are.
      </p>

      <div className="cart-layout">
        <ul className="cart-list">
          {items.map((line) => (
            <li className="cart-row" key={`${line.product_id}-${line.size}`}>
              <Link to={`/products/${line.product_id}`} className="cart-thumb">
                <img src={line.image_url} alt="" />
              </Link>
              <div className="cart-info">
                <Link to={`/products/${line.product_id}`} className="cart-name">
                  {line.name}
                </Link>
                <p className="cart-meta">
                  Size {line.size} · {formatPrice(line.price)} each
                </p>
                <div className="cart-controls">
                  <label>
                    Qty{' '}
                    <input
                      type="number"
                      min={1}
                      max={line.max_quantity}
                      value={line.quantity}
                      aria-label={`Quantity for ${line.name}, size ${line.size}`}
                      onChange={(event) => {
                        const next = Number.parseInt(event.target.value, 10)
                        setQuantity(line.product_id, line.size, Number.isNaN(next) ? 1 : next)
                      }}
                    />
                  </label>
                  <span className="cart-max">{line.max_quantity} in stock</span>
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => removeItem(line.product_id, line.size)}
                  >
                    Remove
                  </button>
                </div>
              </div>
              <div className="cart-line">{formatPrice(line.price * line.quantity)}</div>
            </li>
          ))}
        </ul>

        <aside className="order-summary" aria-label="Order summary">
          <h3>Summary</h3>
          <dl>
            <div>
              <dt>Subtotal</dt>
              <dd>{formatPrice(subtotal)}</dd>
            </div>
            <div>
              <dt>Shipping</dt>
              <dd>Calculated at checkout</dd>
            </div>
            <div className="total">
              <dt>Total</dt>
              <dd>{formatPrice(subtotal)}</dd>
            </div>
          </dl>
          <Link to="/checkout" className="btn btn-block">
            Proceed to checkout
          </Link>
          <Link to="/products" className="text-link">
            Continue shopping
          </Link>
        </aside>
      </div>
    </>
  )
}
