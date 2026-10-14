import { Link, Route, Routes } from 'react-router-dom'
import ChatWidget from './components/ChatWidget'
import NavBar from './components/NavBar'
import RecommendedStrip from './components/RecommendedStrip'
import AboutPage from './pages/AboutPage'
import CartPage from './pages/CartPage'
import CheckoutPage from './pages/CheckoutPage'
import CreateAccountPage from './pages/CreateAccountPage'
import HomePage from './pages/HomePage'
import LoginPage from './pages/LoginPage'
import OwnerPage from './pages/OwnerPage'
import ProductDetailPage from './pages/ProductDetailPage'
import ProductsPage from './pages/ProductsPage'

export default function App() {
  return (
    <>
      <NavBar />
      <main className="page">
        <RecommendedStrip />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/products/:productId" element={<ProductDetailPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/cart" element={<CartPage />} />
          <Route path="/checkout" element={<CheckoutPage />} />
          <Route path="/owner" element={<OwnerPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/create-account" element={<CreateAccountPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="footer">
        <div className="footer-inner">
          <div>
            <Link to="/" className="wordmark">
              Campus Customs
            </Link>
            <p className="footer-tagline">
              Yale apparel and gear for students, alumni, families, and fans. A short walk from
              Old Campus in downtown New Haven.
            </p>
          </div>
          <div>
            <h4>Shop</h4>
            <ul>
              <li>
                <Link to="/products">All products</Link>
              </li>
              <li>
                <Link to="/about">About us</Link>
              </li>
              <li>
                <Link to="/create-account">Create an account</Link>
              </li>
            </ul>
          </div>
          <div>
            <h4>Visit</h4>
            <ul>
              <li>
                <span>Downtown New Haven, Connecticut</span>
              </li>
              <li>
                <span>Questions? Ask the assistant in the corner.</span>
              </li>
            </ul>
          </div>
        </div>
        <div className="footer-bottom">
          © {new Date().getFullYear()} Campus Customs · New Haven, Connecticut
        </div>
      </footer>
      <ChatWidget />
    </>
  )
}

function NotFound() {
  return <div className="status">We couldn't find that page.</div>
}
