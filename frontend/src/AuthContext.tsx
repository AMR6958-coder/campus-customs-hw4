// Keeps track of who is logged in and shares that with every component.
//
// On first load we ask the back end "who am I?" (GET /api/auth/me). If the
// browser has a valid session cookie the user comes back; otherwise null.
// login / register / logout call the API and update the shared state.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import * as api from './api'
import type { User } from './types'

interface AuthState {
  user: User | null
  /** True until the first "who am I?" check finishes. */
  loading: boolean
  login: (email: string, password: string) => Promise<User>
  register: (input: api.RegisterInput) => Promise<User>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    api
      .fetchCurrentUser()
      .then((current) => {
        if (!cancelled) setUser(current)
      })
      .catch(() => {
        // Back end unreachable: treat as logged out.
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const current = await api.login(email, password)
    setUser(current)
    return current
  }, [])

  const register = useCallback(async (input: api.RegisterInput) => {
    const current = await api.register(input)
    setUser(current)
    return current
  }, [])

  const logout = useCallback(async () => {
    await api.logout()
    setUser(null)
  }, [])

  const value = useMemo(
    () => ({ user, loading, login, register, logout }),
    [user, loading, login, register, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>')
  return context
}
