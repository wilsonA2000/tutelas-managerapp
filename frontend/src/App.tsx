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
  Sparkles,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'

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
import CleanupPanel from './pages/CleanupPanel'
import Login from './pages/Login'
import ProgressModal from './components/ProgressModal'
import NotificationCenter from './components/NotificationCenter'
import AgentChat from './components/AgentChat'
import { useAuth } from './contexts/AuthContext'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'

const navItems = [
  { to: '/', label: 'Panel Principal', icon: LayoutDashboard, exact: true },
  { to: '/cases', label: 'Tutelas', icon: Scale },
  { to: '/cuadro', label: 'Cuadro', icon: Table2 },
  { to: '/seguimiento', label: 'Seguimiento', icon: ShieldAlert },
  { to: '/emails', label: 'Correos', icon: Mail },
  { to: '/intelligence', label: 'Inteligencia', icon: Brain },
  { to: '/reports', label: 'Reportes', icon: FileSpreadsheet },
  { to: '/extraction', label: 'Extraccion', icon: Cpu },
  { to: '/agent', label: 'Agente IA', icon: Wrench },
  { to: '/cleanup', label: 'Limpieza', icon: Sparkles },
  { to: '/settings', label: 'Configuracion', icon: Settings },
]

export default function App() {
  const { isAuthenticated, fullName, logout } = useAuth()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()

  if (!isAuthenticated) {
    return <Login />
  }

  const sidebarWidth = collapsed ? 'w-16' : 'w-56'

  return (
    <TooltipProvider>
      <div className="flex h-screen bg-background overflow-hidden">
        <ProgressModal />
        <AgentChat />

        {/* Mobile overlay */}
        <AnimatePresence>
          {mobileOpen && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="fixed inset-0 bg-black/40 z-20 lg:hidden"
              onClick={() => setMobileOpen(false)}
            />
          )}
        </AnimatePresence>

        {/* Sidebar */}
        <aside
          className={`
            fixed lg:relative z-30 h-full flex flex-col
            bg-primary text-primary-foreground transition-all duration-200 ease-out
            ${sidebarWidth}
            ${mobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
          `}
        >
          {/* Logo */}
          <div className="flex items-center gap-3 px-4 py-4 border-b border-white/10 min-h-[60px]">
            <div className="flex-shrink-0 w-8 h-8 bg-white/15 rounded-lg flex items-center justify-center">
              <Building2 size={16} className="text-white" />
            </div>
            {!collapsed && (
              <div className="overflow-hidden flex-1">
                <p className="text-[11px] font-semibold leading-tight text-white/80 truncate">
                  Gobernacion de
                </p>
                <p className="text-[11px] font-semibold leading-tight text-white truncate">
                  Santander
                </p>
              </div>
            )}
            {!collapsed && <NotificationCenter />}
          </div>

          {/* Navigation */}
          <ScrollArea className="flex-1">
            <nav className="px-2 py-3 space-y-0.5">
              {navItems.map(({ to, label, icon: Icon, exact }) => {
                const isActive = exact
                  ? location.pathname === to
                  : location.pathname.startsWith(to)

                const link = (
                  <NavLink
                    key={to}
                    to={to}
                    onClick={() => setMobileOpen(false)}
                    className={`
                      flex items-center gap-2.5 px-2.5 py-2 rounded-md text-[13px] font-medium
                      transition-colors duration-100
                      ${isActive
                        ? 'bg-white/15 text-white'
                        : 'text-white/60 hover:bg-white/8 hover:text-white/90'
                      }
                      ${collapsed ? 'justify-center' : ''}
                    `}
                  >
                    <Icon size={16} className="flex-shrink-0" />
                    {!collapsed && <span className="truncate">{label}</span>}
                  </NavLink>
                )

                if (collapsed) {
                  return (
                    <Tooltip key={to}>
                      <TooltipTrigger render={<div />}>
                        {link}
                      </TooltipTrigger>
                      <TooltipContent side="right">{label}</TooltipContent>
                    </Tooltip>
                  )
                }

                return link
              })}
            </nav>
          </ScrollArea>

          {/* Footer */}
          <div className="hidden lg:block px-2 py-2 border-t border-white/10 space-y-0.5">
            {!collapsed && (
              <div className="px-2.5 py-1.5 text-white/40 text-[11px] truncate">
                {fullName || 'Usuario'}
              </div>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={logout}
              className={`
                w-full text-red-300/70 hover:text-red-200 hover:bg-red-500/20
                text-xs font-medium
                ${collapsed ? 'justify-center px-0' : 'justify-start'}
              `}
            >
              <LogOut size={14} />
              {!collapsed && <span>Cerrar sesion</span>}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setCollapsed(!collapsed)}
              className={`
                w-full text-white/50 hover:text-white hover:bg-white/10
                text-xs font-medium
                ${collapsed ? 'justify-center px-0' : 'justify-start'}
              `}
            >
              {collapsed ? <ChevronRight size={14} /> : (
                <>
                  <ChevronLeft size={14} />
                  <span>Colapsar</span>
                </>
              )}
            </Button>
          </div>
        </aside>

        {/* Main content */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Top bar (mobile) */}
          <header className="lg:hidden flex items-center gap-3 px-4 py-3 bg-card border-b border-border">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={18} />
            </Button>
            <div className="flex items-center gap-2">
              <Building2 size={16} className="text-primary" />
              <span className="font-semibold text-primary text-sm">
                Tutelas 2026
              </span>
            </div>
          </header>

          {/* Page content */}
          <main id="main-content" className="flex-1 overflow-y-auto">
            <AnimatePresence mode="wait">
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.12 }}
              >
                <Routes location={location}>
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
                  <Route path="/cleanup" element={<CleanupPanel />} />
                </Routes>
              </motion.div>
            </AnimatePresence>
          </main>

          {/* Scroll to top */}
          <button
            onClick={() => document.getElementById('main-content')?.scrollTo({ top: 0, behavior: 'smooth' })}
            className="fixed bottom-6 right-6 z-40 w-9 h-9 bg-primary text-primary-foreground rounded-lg shadow-md hover:shadow-lg transition-all flex items-center justify-center opacity-60 hover:opacity-100"
            title="Ir arriba"
          >
            <ArrowUp size={16} />
          </button>
        </div>
      </div>
    </TooltipProvider>
  )
}
