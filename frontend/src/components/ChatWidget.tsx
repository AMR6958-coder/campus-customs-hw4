import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, matchPath, useLocation } from 'react-router-dom'
import { ApiError, fetchChatHistory, sendChat, trackEvent } from '../api'
import { useAuth } from '../AuthContext'
import { usePicks } from '../PicksContext'
import { formatPrice, slugToWords } from '../format'
import type { ChatLanguage, ChatMessage, ChatTurn, User } from '../types'

// How many recent messages anonymous shoppers send along for context.
const HISTORY_TO_SEND = 20
const LANGUAGE_KEY = 'campus-customs-chat-language'

// The site itself stays in English; only the conversation is bilingual.
const UI = {
  auto: {
    placeholder: 'Ask in English or Spanish…',
    pending: 'Checking the shelves…',
    offline: "Sorry, I can't reach the store right now. Please try again in a moment.",
    welcome: (name: string | null) =>
      `${name ? `Hi, ${name}!` : 'Hi!'} I'm the Campus Customs assistant. Ask me in English or Spanish about hoodies, tees, sizes, prices, or what's in stock. ¡También hablo español!`,
  },
  en: {
    placeholder: 'Ask about Yale gear…',
    pending: 'Checking the shelves…',
    offline: "Sorry, I can't reach the store right now. Please try again in a moment.",
    welcome: (name: string | null) =>
      `${name ? `Hi, ${name}!` : 'Hi!'} I'm the Campus Customs assistant. Ask me about hoodies, tees, sizes, prices, or what's in stock.`,
  },
  es: {
    placeholder: 'Pregunta sobre ropa de Yale…',
    pending: 'Revisando el inventario…',
    offline: 'Lo siento, no puedo conectar con la tienda ahora mismo. Inténtalo de nuevo en un momento.',
    welcome: (name: string | null) =>
      `${name ? `¡Hola, ${name}!` : '¡Hola!'} Soy el asistente de Campus Customs. Pregúntame sobre sudaderas, camisetas, tallas, precios o qué hay en stock.`,
  },
} as const

function loadLanguage(): ChatLanguage {
  try {
    const saved = localStorage.getItem(LANGUAGE_KEY)
    return saved === 'en' || saved === 'es' ? saved : 'auto'
  } catch {
    return 'auto'
  }
}

function welcomeFor(user: User | null, language: ChatLanguage): ChatMessage {
  return {
    role: 'assistant',
    content: UI[language].welcome(user ? user.first_name : null),
    local: true,
  }
}

// The assistant replies in plain text, but older saved messages (from the
// seed data) use **markdown bold**. Render those as bold instead of asterisks.
function renderText(text: string) {
  const parts = text.split('**')
  if (parts.length < 3) return text
  return parts.map((part, index) =>
    index % 2 === 1 ? <strong key={index}>{part}</strong> : <span key={index}>{part}</span>,
  )
}

export default function ChatWidget() {
  const { user, loading: authLoading } = useAuth()
  const { setPicks } = usePicks()
  const [open, setOpen] = useState(false)
  const [language, setLanguage] = useState<ChatLanguage>(loadLanguage)
  const [messages, setMessages] = useState<ChatMessage[]>([welcomeFor(null, 'auto')])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  const text = UI[language]

  // If the shopper is on a single-item page, pass that product along with each
  // message so the assistant knows what "this" refers to.
  const { pathname } = useLocation()
  const productId = matchPath('/products/:productId', pathname)?.params.productId

  // Logged-in shoppers get their saved conversation back; everyone else starts fresh.
  useEffect(() => {
    if (authLoading) return
    if (!user) {
      setMessages([welcomeFor(null, language)])
      return
    }
    let cancelled = false
    fetchChatHistory()
      .then((history) => {
        if (cancelled) return
        const restored: ChatMessage[] = history.map((m) => ({
          role: m.role,
          content: m.content,
          products: m.products,
        }))
        setMessages(restored.length > 0 ? restored : [welcomeFor(user, language)])
      })
      .catch(() => {
        if (!cancelled) setMessages([welcomeFor(user, language)])
      })
    return () => {
      cancelled = true
    }
    // The welcome only depends on the language at load time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, authLoading])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, open])

  // Lets other parts of the site (the home-page callout) open the panel.
  useEffect(() => {
    const handleOpen = () => setOpen(true)
    window.addEventListener('open-chat', handleOpen)
    return () => window.removeEventListener('open-chat', handleOpen)
  }, [])

  function changeLanguage(next: ChatLanguage) {
    setLanguage(next)
    try {
      localStorage.setItem(LANGUAGE_KEY, next)
    } catch {
      // ignore
    }
    // Swap the welcome text if that is all that has been said so far.
    setMessages((prev) =>
      prev.length === 1 && prev[0].local ? [welcomeFor(user, next)] : prev,
    )
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const message = input.trim()
    if (!message || sending) return

    // The server remembers logged-in shoppers itself. For anonymous shoppers
    // we send the recent conversation so follow-up questions still make sense.
    const history: ChatTurn[] = user
      ? []
      : messages
          .filter((m) => !m.local)
          .slice(-HISTORY_TO_SEND)
          .map((m) => ({
            role: m.role,
            content: m.content,
            product_ids: (m.products ?? []).map((p) => p.product_id),
          }))

    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: message }])
    setSending(true)
    try {
      const result = await sendChat(message, productId, history, language)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: result.reply, products: result.products },
      ])
      if (result.products.length > 0) setPicks(result.products)
    } catch (err) {
      // 502/503 carry a friendly message from the server; anything else is "offline".
      const content =
        err instanceof ApiError && (err.status === 502 || err.status === 503)
          ? err.message
          : text.offline
      setMessages((prev) => [...prev, { role: 'assistant', content, local: true }])
    } finally {
      setSending(false)
    }
  }

  return (
    <>
      {open && (
        <div className="chat-panel" role="dialog" aria-label="Chat with Campus Customs">
          <div className="chat-header">
            <div>
              <strong>Campus Customs Assistant</strong>
              <small>English · Español</small>
            </div>
            <div className="chat-header-controls">
              <select
                className="chat-lang"
                value={language}
                onChange={(event) => changeLanguage(event.target.value as ChatLanguage)}
                aria-label="Chat language"
              >
                <option value="auto">Auto</option>
                <option value="en">English</option>
                <option value="es">Español</option>
              </select>
              <button type="button" onClick={() => setOpen(false)} aria-label="Close chat">
                ×
              </button>
            </div>
          </div>
          {productId && (
            <div className="chat-context">Asking about: {slugToWords(productId)}</div>
          )}
          <div className="chat-messages">
            {messages.map((message, index) => (
              <div key={index} className={`msg ${message.role}`}>
                <div className="msg-text">{renderText(message.content)}</div>
                {message.products && message.products.length > 0 && (
                  <div className="msg-products">
                    {message.products.map((product) => (
                      <Link
                        key={product.product_id}
                        to={`/products/${product.product_id}`}
                        className="msg-product"
                        title={product.description}
                        onClick={() => trackEvent(product.product_id, 'click')}
                      >
                        <img src={product.image_url} alt="" loading="lazy" />
                        <span className="msg-product-name">{product.name}</span>
                        <span className="msg-product-price">{formatPrice(product.price)}</span>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {sending && <div className="msg assistant pending">{text.pending}</div>}
            <div ref={endRef} />
          </div>
          <form className="chat-form" onSubmit={handleSubmit}>
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder={text.placeholder}
              aria-label="Message"
            />
            <button type="submit" disabled={sending || !input.trim()}>
              {language === 'es' ? 'Enviar' : 'Send'}
            </button>
          </form>
        </div>
      )}
      <button
        type="button"
        className="chat-fab"
        onClick={() => setOpen((prev) => !prev)}
        aria-label={open ? 'Close chat' : 'Open chat'}
      >
        {open ? '×' : '💬'}
      </button>
    </>
  )
}
