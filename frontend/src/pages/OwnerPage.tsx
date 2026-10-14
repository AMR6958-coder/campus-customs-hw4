import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, fetchOwnerNotes, fetchOwnerReport, resolveOwnerNote, runOwnerReview } from '../api'
import { useAuth } from '../AuthContext'
import type { InventoryReport, OwnerNote, ReviewResult } from '../types'

// The store owner's view: the inventory report the rules produce, the notes
// the inventory assistant has sent, and a button to run a fresh review.
export default function OwnerPage() {
  const { user, loading } = useAuth()
  const [report, setReport] = useState<InventoryReport | null>(null)
  const [notes, setNotes] = useState<OwnerNote[]>([])
  const [showResolved, setShowResolved] = useState(false)
  const [review, setReview] = useState<ReviewResult | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const [nextReport, nextNotes] = await Promise.all([fetchOwnerReport(), fetchOwnerNotes(true)])
      setReport(nextReport)
      setNotes(nextNotes)
      setError('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load the inventory report.')
    }
  }, [])

  useEffect(() => {
    if (user?.is_owner) void load()
  }, [user, load])

  if (loading) return <div className="status">Loading…</div>
  if (!user) {
    return (
      <div className="status">
        This page is for the store owner. <Link to="/login">Log in</Link> to continue.
      </div>
    )
  }
  if (!user.is_owner) {
    return <div className="status">This page is for the store owner's account.</div>
  }

  async function handleReview() {
    setRunning(true)
    setError('')
    try {
      const result = await runOwnerReview()
      setReview(result)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The review failed. Please try again.')
    } finally {
      setRunning(false)
    }
  }

  async function handleResolve(noteId: number) {
    try {
      await resolveOwnerNote(noteId)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not resolve that note.')
    }
  }

  const openNotes = notes.filter((n) => n.status === 'open')
  const resolvedNotes = notes.filter((n) => n.status === 'resolved')

  return (
    <>
      <p className="eyebrow">Store owner</p>
      <h1 className="page-title">Inventory notes</h1>
      <p className="page-subtitle">
        What shoppers are viewing, what they are adding to carts, and which sizes are running low.
        The inventory assistant turns this into notes for you.
      </p>

      <div className="owner-toolbar">
        <button type="button" className="btn" onClick={handleReview} disabled={running}>
          {running ? 'Reviewing…' : 'Run inventory review'}
        </button>
        {report && (
          <span className="owner-rules">
            Reorder line: {report.reorder_threshold_percent}% of {report.par_level} units per size
            ({Math.floor((report.par_level * report.reorder_threshold_percent) / 100)} or fewer).
            Window: last {report.window_days} days. Flag after {report.min_views_to_flag} views or
            clicks with no add-to-carts.
          </span>
        )}
      </div>

      {error && (
        <div className="form-error" role="alert">
          {error}
        </div>
      )}

      {review && (
        <div className="form-note" role="status">
          <strong>Review complete.</strong> {review.summary}
          {!review.used_agent && ' (Template notes were used because no LLM key is configured.)'}
        </div>
      )}

      <section className="section">
        <div className="section-head">
          <div>
            <p className="eyebrow">From the inventory assistant</p>
            <h2>Open notes</h2>
          </div>
          <button type="button" className="link-button" onClick={() => setShowResolved((v) => !v)}>
            {showResolved ? 'Hide resolved' : `Show resolved (${resolvedNotes.length})`}
          </button>
        </div>
        {openNotes.length === 0 ? (
          <p className="status">No open notes. Run a review to check the latest numbers.</p>
        ) : (
          <ul className="note-list">
            {openNotes.map((note) => (
              <NoteCard key={note.id} note={note} onResolve={handleResolve} />
            ))}
          </ul>
        )}
        {showResolved && resolvedNotes.length > 0 && (
          <ul className="note-list resolved">
            {resolvedNotes.map((note) => (
              <NoteCard key={note.id} note={note} />
            ))}
          </ul>
        )}
      </section>

      {report && (
        <section className="section">
          <div className="section-head">
            <div>
              <p className="eyebrow">Generated {report.generated_at}</p>
              <h2>The numbers behind the notes</h2>
            </div>
          </div>

          <div className="report-grid">
            <div>
              <h3 className="report-title">Sizes at or below the reorder line</h3>
              {report.low_stock.length === 0 ? (
                <p className="status">Nothing is low right now.</p>
              ) : (
                <table className="report-table">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Size</th>
                      <th>Left</th>
                      <th>% of par</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.low_stock.map((line) => (
                      <tr key={`${line.product_id}-${line.size}`}>
                        <td>
                          <Link to={`/products/${line.product_id}`}>{line.name}</Link>
                        </td>
                        <td>{line.size}</td>
                        <td className={line.quantity === 0 ? 'stock-out' : 'stock-low'}>{line.quantity}</td>
                        <td>{line.percent_of_par}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div>
              <h3 className="report-title">Shopper activity, last {report.window_days} days</h3>
              {report.engagement.length === 0 ? (
                <p className="status">No activity recorded yet. Browse a few items and come back.</p>
              ) : (
                <table className="report-table">
                  <thead>
                    <tr>
                      <th>Product</th>
                      <th>Views</th>
                      <th>Clicks</th>
                      <th>Added to cart</th>
                      <th>Flag</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.engagement.map((line) => (
                      <tr key={line.product_id}>
                        <td>
                          <Link to={`/products/${line.product_id}`}>{line.name}</Link>
                        </td>
                        <td>{line.views}</td>
                        <td>{line.clicks}</td>
                        <td>{line.add_to_cart_units}</td>
                        <td>
                          {line.flagged_do_not_reorder ? (
                            <span className="flag flag-hold">Viewed, not ordered</span>
                          ) : (
                            ''
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </section>
      )}
    </>
  )
}

function NoteCard({ note, onResolve }: { note: OwnerNote; onResolve?: (id: number) => void }) {
  const label = note.kind === 'reorder' ? 'Reorder' : 'Do not reorder'
  return (
    <li className={`note-card ${note.kind}`}>
      <div className="note-head">
        <span className={`note-kind ${note.kind}`}>{label}</span>
        <Link to={`/products/${note.product_id}`} className="note-product">
          {note.product_name}
        </Link>
        {note.size && <span className="note-size">Sizes {note.size}</span>}
        <span className="note-date">{note.created_at} UTC</span>
      </div>
      <p className="note-message">{note.message}</p>
      {onResolve && (
        <button type="button" className="link-button" onClick={() => onResolve(note.id)}>
          Mark resolved
        </button>
      )}
    </li>
  )
}
