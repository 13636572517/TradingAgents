// web/src/context/AuthContext.tsx
import { createContext, useContext, useState, useCallback, type ReactNode } from "react"
import { api } from "../api/client"

interface AuthContextValue {
  token: string | null
  username: string | null
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

  const login = useCallback(async (uname: string, password: string) => {
    const resp = await api.login(uname, password)  // throws on 401
    localStorage.setItem("auth_token", resp.access_token)
    localStorage.setItem("auth_username", uname)
    setToken(resp.access_token)
    setUsername(uname)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem("auth_token")
    localStorage.removeItem("auth_username")
    setToken(null)
    setUsername(null)
  }, [])

  return (
    <AuthContext.Provider value={{ token, username, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
