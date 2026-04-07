import { useState } from 'react'
import { Routes, Route, NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard,
  Scale,
  Cpu,
  Mail,
  FileSpreadsheet,
  Settings,
  ChevronLeft,
  ChevronRight,
  Menu,
  Building2,
  ShieldAlert,
  ArrowUp,
  Table2,
  LogOut,
  Brain,
  Wrench,
} from 'lucide-react'

import Dashboard from './pages/Dashboard'
import CasesList from './pages/CasesList'
import CaseDetail from './pages/CaseDetail'
import Extraction from './pages/Extraction'
import Emails from './pages/Emails'
import Reports from './pages/Reports'
import SettingsPage from './pages/Settings'
import Seguimiento from './pages/Seguimiento'
import Cuadro from './pages/Cuadro'
import Intelligence from './pages/Intelligence'
import AgentTools from './pages/AgentTools'
import Login from './pages/Login'
import ProgressModal from './components/ProgressModal'
import NotificationCenter from './components/NotificationCenter'
import AgentChat from './components/AgentChat'
import { useAuth } from './contexts/AuthContext'

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, exact: true },
  { to: '/cases', label: 'Tutelas', icon: Scale },
  { to: '/cuadro', label: 'Cuadro', icon: Table2 },
  { to: '/extraction', label: 'Extraccion', icon: Cpu },
  { to: '/emails', label: 'Correos', icon: Mail },
  { to: '/reports', label: 'Reportes', icon: FileSpreadsheet },
  { to: '/intelligence', label: 'Inteligencia', icon: Brain },
  { to: '/agent', label: 'Agente IA', icon: Wrench },
  { to: '/settings', label: 'Configuracion', icon: Settings },
  { to: '/seguimiento', label: 'Seguimiento', icon: ShieldAlert },
]

export default function App() {
  const { isAuthenticated, fullName, logout } = useAuth()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()

  if (!isAuthenticated) {
    return <Login />
  }

  const sidebarWidth = collapsed ? 'w-16' : 'w-60'

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      <ProgressModal />
      <AgentChat />
      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-20 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`
          fixed lg:relative z-30 h-full flex flex-col
          bg-[#1A5276] text-white transition-all duration-300 ease-in-out
          ${sidebarWidth}
          ${mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 py-5 border-b border-white/10 min-h-[68px]">
          <div className="flex-shrink-0 w-8 h-8 bg-white/20 rounded-lg flex items-center justify-center">
            <Building2 size={18} className="text-white" />
          </div>
          {!collapsed && (
            <div className="overflow-hidden flex-1">
              <p className="text-xs font-bold leading-tight text-white/90 truncate">
                Gobernacion de
              </p>
              <p className="text-xs font-bold leading-tight text-white truncate">
                Santander
              </p>
            </div>
          )}
          {!collapsed && <NotificationCenter />}
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
          {navItems.map(({ to, label, icon: Icon, exact }) => {
            const isActive = exact
              ? location.pathname === to
              : location.pathname.startsWith(to)

            return (
              <NavLink
                key={to}
                to={to}
                onClick={() => setMobileOpen(false)}
                className={`
                  flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium
                  transition-all duration-150 group
                  ${isActive
                    ? 'bg-white/20 text-white shadow-sm'
                    : 'text-white/70 hover:bg-white/10 hover:text-white'
                  }
                  ${collapsed ? 'justify-center' : ''}
                `}
                title={collapsed ? label : undefined}
              >
                <Icon size={18} className="flex-shrink-0" />
                {!collapsed && <span className="truncate">{label}</span>}
              </NavLink>
            )
          })}
        </nav>

        {/* Collapse toggle */}
        <div className="hidden lg:flex px-3 py-3 border-t border-white/10">
          {!collapsed && (
            <div className="flex items-center gap-2 px-3 py-2 text-white/50 text-xs truncate">
              <span>{fullName || 'Usuario'}</span>
            </div>
          )}
          <button
            onClick={logout}
            className={`
              flex items-center gap-2 w-full px-3 py-2 rounded-lg
              text-red-300/70 hover:text-red-200 hover:bg-red-500/20
              text-xs font-medium transition-colors
              ${collapsed ? 'justify-center' : ''}
            `}
            title="Cerrar sesion"
          >
            <LogOut size={16} />
            {!collapsed && <span>Cerrar sesion</span>}
          </button>
          <button
            onClick={() => setCollapsed(!collapsed)}
            className={`
              flex items-center gap-2 w-full px-3 py-2 rounded-lg
              text-white/60 hover:text-white hover:bg-white/10
              text-xs font-medium transition-colors
              ${collapsed ? 'justify-center' : ''}
            `}
          >
            {collapsed ? <ChevronRight size={16} /> : (
              <>
                <ChevronLeft size={16} />
                <span>Colapsar</span>
              </>
            )}
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Top bar (mobile) */}
        <header className="lg:hidden flex items-center gap-3 px-4 py-3 bg-white border-b border-gray-200 shadow-sm">
          <button
            onClick={() => setMobileOpen(true)}
            className="p-2 rounded-lg text-gray-500 hover:bg-gray-100"
          >
            <Menu size={20} />
          </button>
          <div className="flex items-center gap-2">
            <Building2 size={18} className="text-[#1A5276]" />
            <span className="font-semibold text-[#1A5276] text-sm">
              Tutelas 2026
            </span>
          </div>
        </header>

        {/* Page content */}
        <main id="main-content" className="flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/cases" element={<CasesList />} />
            <Route path="/cases/:id" element={<CaseDetail />} />
            <Route path="/extraction" element={<Extraction />} />
            <Route path="/emails" element={<Emails />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/cuadro" element={<Cuadro />} />
            <Route path="/intelligence" element={<Intelligence />} />
            <Route path="/agent" element={<AgentTools />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/seguimiento" element={<Seguimiento />} />
          </Routes>
        </main>

        {/* Boton Ir Arriba */}
        <button
          onClick={() => document.getElementById('main-content')?.scrollTo({ top: 0, behavior: 'smooth' })}
          className="fixed bottom-6 right-6 z-40 w-10 h-10 bg-[#1A5276] text-white rounded-full shadow-lg hover:bg-[#154360] transition-all flex items-center justify-center opacity-70 hover:opacity-100"
          title="Ir arriba"
        >
          <ArrowUp size={18} />
        </button>
      </div>
    </div>
  )
}
