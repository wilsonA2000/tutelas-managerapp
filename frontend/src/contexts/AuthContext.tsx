import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import axios from 'axios'
import api from '../services/api'

interface AuthState {
  token: string | null
  refreshToken: string | null
  username: string
  fullName: string
  isAuthenticated: boolean
}

interface AuthContextType extends AuthState {
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

const STORAGE_KEY = 'tutelas_auth'

function loadStoredAuth(): AuthState {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      if (parsed.token) {
        return { ...parsed, isAuthenticated: true }
      }
    }
  } catch { /* ignore */ }
  return { token: null, refreshToken: null, username: '', fullName: '', isAuthenticated: false }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>(loadStoredAuth)

  const login = async (username: string, password: string) => {
    const res = await axios.post('/api/auth/login', { username, password })
    const { access_token, refresh_token, username: user, full_name } = res.data
    const newAuth: AuthState = {
      token: access_token,
      refreshToken: refresh_token,
      username: user,
      fullName: full_name,
      isAuthenticated: true,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(newAuth))
    setAuth(newAuth)
  }

  const logout = () => {
    localStorage.removeItem(STORAGE_KEY)
    setAuth({ token: null, refreshToken: null, username: '', fullName: '', isAuthenticated: false })
  }

  // Setup axios interceptors for auth header
  // Aplicado tanto al `axios` global (para login/refresh) como a la instancia
  // `api` (axios.create() — para todas las llamadas /api/* del cliente, ej. v9).
  // Bug previo: solo se aplicaba al global → la instancia `api` no enviaba
  // Authorization → endpoints con `Depends(require_auth)` devolvían 401.
  useEffect(() => {
    const reqHandler = (config: any) => {
      if (auth.token && !config.url?.includes('/auth/login')) {
        config.headers.Authorization = `Bearer ${auth.token}`
      }
      return config
    }

    const resHandler = async (error: any) => {
      const originalRequest = error.config
      const url: string = originalRequest?.url || ''
      // No re-intentar el propio /auth/refresh (provoca loop infinito si el
      // refresh token también está caducado).
      const isRefreshCall = url.includes('/auth/refresh') || url.includes('/auth/login')
      if (
        error.response?.status === 401 &&
        !originalRequest._retry &&
        auth.refreshToken &&
        !isRefreshCall
      ) {
        originalRequest._retry = true
        try {
          const res = await axios.post('/api/auth/refresh', { refresh_token: auth.refreshToken })
          const { access_token, refresh_token } = res.data
          const updated = { ...auth, token: access_token, refreshToken: refresh_token }
          localStorage.setItem(STORAGE_KEY, JSON.stringify(updated))
          setAuth(updated)
          originalRequest.headers.Authorization = `Bearer ${access_token}`
          return axios(originalRequest)
        } catch {
          logout()
        }
      }
      // Si fue un 401 en el refresh mismo, hacer logout silencioso para limpiar
      // tokens stale (típico tras restart del backend con JWT secret nuevo).
      if (error.response?.status === 401 && isRefreshCall) {
        logout()
      }
      return Promise.reject(error)
    }

    const reqGlobal = axios.interceptors.request.use(reqHandler)
    const resGlobal = axios.interceptors.response.use(r => r, resHandler)
    const reqApi = api.interceptors.request.use(reqHandler)
    const resApi = api.interceptors.response.use(r => r, resHandler)

    return () => {
      axios.interceptors.request.eject(reqGlobal)
      axios.interceptors.response.eject(resGlobal)
      api.interceptors.request.eject(reqApi)
      api.interceptors.response.eject(resApi)
    }
  }, [auth.token, auth.refreshToken])

  return (
    <AuthContext.Provider value={{ ...auth, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
