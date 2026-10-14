import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { fetchProducts } from '../api'
import ProductCard from '../components/ProductCard'
import type { Product } from '../types'

// Each collection tile uses a real product photo from the catalogue.
const collections = [
  {
    label: 'Residential colleges',
    title: 'Rep your college',
    blurb: 'From Benjamin Franklin to Trumbull, in crewnecks, quarter-zips, and fleece.',
    image: '/media/products/saybrook-college-crewneck.jpg',
  },
  {
    label: 'Graduate & professional schools',
    title: 'Gear for every corner of campus',
    blurb: 'Law, Medicine, Management, Art, Music, and more.',
    image: '/media/products/school-of-management-crest-t-shirt.jpg',
  },
  {
    label: 'Bulldog athletics',
    title: 'Cheer loud, stay warm',
    blurb: 'Baseball, hockey, sailing, squash, and the rest of the roster.',
    image: '/media/products/yale-sports-hoodie-hockey.jpg',
  },
  {
    label: 'Yale family',
    title: 'Everyone gets a Bulldog',
    blurb: 'Mom, Dad, Grandma, Grandpa, Aunt, Uncle. Show off the Bulldog in the family.',
    image: '/media/products/yale-dad-hoodie.jpg',
  },
]

// Photos for the hero collage, with a short caption each.
const collage = [
  { image: '/media/products/basic-hoodie-big-yale.jpg', caption: 'Basic Hoodie, Big Yale' },
  { image: '/media/products/champion-reverse-weave-crewneck.jpg', caption: 'Champion Reverse Weave' },
  { image: '/media/products/2025-yale-vs-harvard-t-shirt.jpg', caption: 'The Game, 2025' },
  { image: '/media/products/benjamin-franklin-fleece-jacket.jpg', caption: 'Benjamin Franklin Fleece' },
]

// A few crowd-pleasers to spotlight on the home page. If any of these are
// missing from the catalogue we fall back to the first few products.
const FEATURED_IDS = [
  'basic-hoodie-big-yale',
  'champion-reverse-weave-crewneck',
  '2025-yale-vs-harvard-t-shirt',
  'saybrook-sweater-fleece-jacket',
]

function pickFeatured(products: Product[]): Product[] {
  const byId = new Map(products.map((p) => [p.product_id, p]))
  const picked = FEATURED_IDS.map((id) => byId.get(id)).filter((p): p is Product => Boolean(p))
  return picked.length === FEATURED_IDS.length ? picked : products.slice(0, 4)
}

function openChat() {
  window.dispatchEvent(new CustomEvent('open-chat'))
}

export default function HomePage() {
  const [featured, setFeatured] = useState<Product[]>([])

  useEffect(() => {
    let cancelled = false
    fetchProducts()
      .then((products) => {
        if (!cancelled) setFeatured(pickFeatured(products))
      })
      .catch(() => {
        if (!cancelled) setFeatured([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow">Campus Customs · New Haven</p>
          <h1>Bulldog pride, made for every day.</h1>
          <p>
            Hoodies, crewnecks, tees, and fleece in classic Yale Blue. For students, alumni,
            families, and anyone who bleeds blue on game day.
          </p>
          <div className="hero-actions">
            <Link to="/products" className="btn">
              Shop all gear
            </Link>
            <Link to="/about" className="text-link">
              Our story
            </Link>
          </div>
        </div>
        <div className="hero-collage" aria-label="A few of our favorites">
          {collage.map((item) => (
            <figure key={item.image}>
              <img src={item.image} alt={item.caption} />
              <figcaption>{item.caption}</figcaption>
            </figure>
          ))}
        </div>
      </section>

      <section className="section">
        <div className="section-head">
          <div>
            <p className="eyebrow">Collections</p>
            <h2>Shop by spirit</h2>
          </div>
          <Link to="/products" className="text-link">
            See everything
          </Link>
        </div>
        <div className="tile-grid">
          {collections.map((collection) => (
            <Link to="/products" className="tile" key={collection.title}>
              <div className="tile-media">
                <img src={collection.image} alt="" loading="lazy" />
              </div>
              <p className="eyebrow">{collection.label}</p>
              <h3>{collection.title}</h3>
              <p>{collection.blurb}</p>
              <span className="text-link">Explore</span>
            </Link>
          ))}
        </div>
      </section>

      {featured.length > 0 && (
        <section className="section">
          <div className="section-head">
            <div>
              <p className="eyebrow">Fan favorites</p>
              <h2>What everyone's wearing</h2>
            </div>
            <Link to="/products" className="text-link">
              Shop all
            </Link>
          </div>
          <div className="product-grid">
            {featured.map((product) => (
              <ProductCard key={product.product_id} product={product} />
            ))}
          </div>
        </section>
      )}

      <section className="section">
        <div className="callout">
          <div>
            <p className="eyebrow">Ask the assistant</p>
            <h2>Not sure what to get?</h2>
            <p>
              Our assistant knows every item, every size, and what's actually on the shelf. Ask
              about prices, colors, or what to wear to The Game.
            </p>
          </div>
          <button type="button" className="btn" onClick={openChat}>
            Start a chat
          </button>
        </div>
      </section>
    </>
  )
}
