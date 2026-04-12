import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import axios from 'axios'

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

  // Setup axios interceptor for auth header
  useEffect(() => {
    const requestInterceptor = axios.interceptors.request.use((config) => {
      if (auth.token && !config.url?.includes('/auth/login')) {
        config.headers.Authorization = `Bearer ${auth.token}`
      }
      return config
    })

    const responseInterceptor = axios.interceptors.response.use(
      (response) => response,
      async (error) => {
        const originalRequest = error.config
        if (error.response?.status === 401 && !originalRequest._retry && auth.refreshToken) {
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
        return Promise.reject(error)
      }
    )

    return () => {
      axios.interceptors.request.eject(requestInterceptor)
      axios.interceptors.response.eject(responseInterceptor)
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
