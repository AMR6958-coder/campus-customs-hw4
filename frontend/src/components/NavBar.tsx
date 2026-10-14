import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../AuthContext'
import { useCart } from '../CartContext'

const pages = [
  { to: '/', label: 'Home', end: true },
  { to: '/products', label: 'Products' },
  { to: '/about', label: 'About Us' },
]

// Header in the yale.edu pattern: a thin blue stripe, a small uppercase
// utility row, a large centered serif wordmark, then a serif navigation row
// with thin rules that stays pinned while the page scrolls.
export default function NavBar() {
  const { user, loading, logout } = useAuth()
  const { count } = useCart()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/')
  }

  return (
    <header className="site-header">
      <div className="topbar" aria-hidden="true" />

      <div className="utility">
        <span>Yale gear · New Haven, Connecticut</span>
        <span>
          {!loading && user
            ? `Signed in as ${user.first_name} ${user.last_name}`
            : 'For students, alumni, families & fans'}
        </span>
      </div>

      <div className="masthead">
        <NavLink to="/" className="wordmark">
          Campus Customs
          <small>Yale apparel &amp; gear</small>
        </NavLink>
      </div>

      <nav className="main-nav" aria-label="Main navigation">
        <div className="main-nav-inner">
          {pages.map((page) => (
            <NavLink key={page.to} to={page.to} end={page.end}>
              {page.label}
            </NavLink>
          ))}
          <NavLink to="/cart" aria-label={`Cart, ${count} ${count === 1 ? 'item' : 'items'}`}>
            Cart
            {count > 0 && <span className="cart-badge">{count}</span>}
          </NavLink>

          {/* Account area: hidden until we know whether someone is logged in. */}
          {!loading && user && (
            <>
              {user.is_owner && <NavLink to="/owner">Inventory</NavLink>}
              <span className="nav-user">Hi, {user.first_name}</span>
              <button type="button" className="nav-button" onClick={handleLogout}>
                Log Out
              </button>
            </>
          )}
          {!loading && !user && (
            <>
              <NavLink to="/login">Log In</NavLink>
              <NavLink to="/create-account">Create Account</NavLink>
            </>
          )}
        </div>
      </nav>
    </header>
  )
}
