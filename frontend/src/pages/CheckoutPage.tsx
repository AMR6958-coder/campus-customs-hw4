import { useEffect, useState, type ChangeEvent } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { useCart } from '../CartContext'
import { formatPrice } from '../format'

// Checkout shows the full order flow (contact, shipping, payment, summary)
// but this is a sample store: the "Place order" button is disabled on
// purpose and nothing typed here is sent anywhere or saved.

interface CheckoutForm {
  first_name: string
  last_name: string
  email: string
  phone: string
  address1: string
  address2: string
  city: string
  state: string
  zip: string
}

const EMPTY: CheckoutForm = {
  first_name: '',
  last_name: '',
  email: '',
  phone: '',
  address1: '',
  address2: '',
  city: '',
  state: '',
  zip: '',
}

export default function CheckoutPage() {
  const { items, count, subtotal } = useCart()
  const { user } = useAuth()
  const [form, setForm] = useState<CheckoutForm>(EMPTY)

  // Pre-fill contact details for logged-in shoppers, without overwriting typing.
  useEffect(() => {
    if (!user) return
    setForm((prev) => ({
      ...prev,
      first_name: prev.first_name || user.first_name,
      last_name: prev.last_name || user.last_name,
      email: prev.email || user.email,
    }))
  }, [user])

  function update(field: keyof CheckoutForm) {
    return (event: ChangeEvent<HTMLInputElement>) =>
      setForm((prev) => ({ ...prev, [field]: event.target.value }))
  }

  if (items.length === 0) {
    return (
      <>
        <p className="eyebrow">Checkout</p>
        <h1 className="page-title">Nothing to check out yet</h1>
        <p className="page-subtitle">Add something to your cart first.</p>
        <Link to="/products" className="btn">
          Shop all gear
        </Link>
      </>
    )
  }

  return (
    <>
      <p className="eyebrow">Checkout</p>
      <h1 className="page-title">Your order</h1>
      <p className="page-subtitle">
        {count} {count === 1 ? 'item' : 'items'} · {formatPrice(subtotal)}
      </p>

      <div className="demo-banner" role="note">
        This is a sample store. You can fill in your details to see how ordering works, but
        ordering is turned off: no payment is taken and nothing you type here is sent or saved.
      </div>

      <div className="checkout-layout">
        <form className="checkout-form" onSubmit={(event) => event.preventDefault()}>
          <section>
            <h3>Contact</h3>
            <div className="field-row">
              <div className="field">
                <label htmlFor="co-first">First name</label>
                <input id="co-first" autoComplete="given-name" value={form.first_name} onChange={update('first_name')} />
              </div>
              <div className="field">
                <label htmlFor="co-last">Last name</label>
                <input id="co-last" autoComplete="family-name" value={form.last_name} onChange={update('last_name')} />
              </div>
            </div>
            <div className="field-row">
              <div className="field">
                <label htmlFor="co-email">Email</label>
                <input id="co-email" type="email" autoComplete="email" value={form.email} onChange={update('email')} />
              </div>
              <div className="field">
                <label htmlFor="co-phone">Phone (optional)</label>
                <input id="co-phone" type="tel" autoComplete="tel" value={form.phone} onChange={update('phone')} />
              </div>
            </div>
          </section>

          <section>
            <h3>Shipping address</h3>
            <div className="field">
              <label htmlFor="co-address1">Street address</label>
              <input id="co-address1" autoComplete="address-line1" value={form.address1} onChange={update('address1')} />
            </div>
            <div className="field">
              <label htmlFor="co-address2">Apartment, suite, etc. (optional)</label>
              <input id="co-address2" autoComplete="address-line2" value={form.address2} onChange={update('address2')} />
            </div>
            <div className="field-row">
              <div className="field">
                <label htmlFor="co-city">City</label>
                <input id="co-city" autoComplete="address-level2" value={form.city} onChange={update('city')} />
              </div>
              <div className="field">
                <label htmlFor="co-state">State</label>
                <input id="co-state" autoComplete="address-level1" value={form.state} onChange={update('state')} />
              </div>
            </div>
            <div className="field-row">
              <div className="field">
                <label htmlFor="co-zip">ZIP code</label>
                <input id="co-zip" autoComplete="postal-code" inputMode="numeric" value={form.zip} onChange={update('zip')} />
              </div>
            </div>
          </section>

          <section>
            <h3>Payment</h3>
            <p className="field-note">
              Payment isn't connected on this sample site. These fields are here to show the
              flow; nothing entered is sent or stored.
            </p>
            <div className="field">
              <label htmlFor="co-card-name">Name on card</label>
              <input id="co-card-name" autoComplete="off" />
            </div>
            <div className="field">
              <label htmlFor="co-card-number">Card number</label>
              <input id="co-card-number" autoComplete="off" inputMode="numeric" placeholder="•••• •••• •••• ••••" />
            </div>
            <div className="field-row">
              <div className="field">
                <label htmlFor="co-card-exp">Expiry (MM/YY)</label>
                <input id="co-card-exp" autoComplete="off" placeholder="MM/YY" />
              </div>
              <div className="field">
                <label htmlFor="co-card-cvc">Security code</label>
                <input id="co-card-cvc" autoComplete="off" inputMode="numeric" placeholder="CVC" />
              </div>
            </div>
          </section>

          <div className="place-order">
            <button type="button" className="btn" disabled title="Ordering is disabled on this sample site">
              Place order
            </button>
            <p className="place-order-note">
              Ordering is disabled on this sample site. Everything up to this point works as it
              would in the real store.
            </p>
          </div>
        </form>

        <aside className="order-summary" aria-label="Order summary">
          <h3>Summary</h3>
          <ul className="summary-items">
            {items.map((line) => (
              <li key={`${line.product_id}-${line.size}`}>
                <span>
                  {line.quantity} × {line.name} ({line.size})
                </span>
                <span>{formatPrice(line.price * line.quantity)}</span>
              </li>
            ))}
          </ul>
          <dl>
            <div>
              <dt>Subtotal</dt>
              <dd>{formatPrice(subtotal)}</dd>
            </div>
            <div>
              <dt>Shipping</dt>
              <dd>Not calculated (demo)</dd>
            </div>
            <div className="total">
              <dt>Total</dt>
              <dd>{formatPrice(subtotal)}</dd>
            </div>
          </dl>
          <Link to="/cart" className="text-link">
            Edit cart
          </Link>
        </aside>
      </div>
    </>
  )
}
