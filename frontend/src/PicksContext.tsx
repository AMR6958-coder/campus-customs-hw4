// Products the assistant has picked out for the shopper. The chat widget sets
// them; the RecommendedStrip at the top of every page shows them.

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import type { ProductCard } from './types'

interface PicksState {
  picks: ProductCard[]
  setPicks: (products: ProductCard[]) => void
  clearPicks: () => void
}

const PicksContext = createContext<PicksState | null>(null)

export function PicksProvider({ children }: { children: ReactNode }) {
  const [picks, setPicks] = useState<ProductCard[]>([])
  const value = useMemo(
    () => ({ picks, setPicks, clearPicks: () => setPicks([]) }),
    [picks],
  )
  return <PicksContext.Provider value={value}>{children}</PicksContext.Provider>
}

export function usePicks(): PicksState {
  const context = useContext(PicksContext)
  if (!context) throw new Error('usePicks must be used inside <PicksProvider>')
  return context
}
