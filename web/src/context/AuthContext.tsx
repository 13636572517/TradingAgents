// web/src/context/AuthContext.tsx
import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from "react"
import { api } from "../api/client"

interface AuthContextValue {
  token: string | null
  username: string | null
  isAdmin: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem("auth_token")
  )
  const [username, setUsername] = useState<string | null>(() =>
    localStorage.getItem("auth_username")
  )
  const [isAdmin, setIsAdmin] = useState<boolean>(() =>
    localStorage.getItem("auth_is_admin") === "true"
  )

  useEffect(() => {
    if (!token) return
    api.getMe().then((u) => {
      setIsAdmin(u.is_admin)
      localStorage.setItem("auth_is_admin", String(u.is_admin))
    }).catch(() => {})
  }, [token])

  const login = useCallback(async (uname: string, password: string) => {
    const resp = await api.login(uname, password)
    localStorage.setItem("auth_token", resp.access_token)
    localStorage.setItem("auth_username", uname)
    setToken(resp.access_token)
    setUsername(uname)
    const me = await api.getMe()
    setIsAdmin(me.is_admin)
    localStorage.setItem("auth_is_admin", String(me.is_admin))
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem("auth_token")
    localStorage.removeItem("auth_username")
    localStorage.removeItem("auth_is_admin")
    setToken(null)
    setUsername(null)
    setIsAdmin(false)
  }, [])

  return (
    <AuthContext.Provider value={{ token, username, isAdmin, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
