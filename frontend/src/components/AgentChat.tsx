import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  MessageCircle, Send, X, Loader2, HelpCircle, Bot, User,
  Sparkles, Zap, RotateCcw, Minimize2, Maximize2,
  Search, BarChart3, Shield, Brain,
} from 'lucide-react'
import { chatWithAI, runAgent } from '../services/api'
import { motion, AnimatePresence } from 'motion/react'
import { cn } from '@/lib/utils'

interface ChatMessage {
  role: 'user' | 'ai'
  text: string
  steps?: any[]
  duration?: number
  timestamp?: Date
}

const QUICK_COMMANDS = [
  { text: 'Estadisticas generales', icon: BarChart3, color: 'text-blue-600 bg-blue-50 border-blue-200 hover:bg-blue-100' },
  { text: 'Escanear alertas criticas', icon: Shield, color: 'text-amber-600 bg-amber-50 border-amber-200 hover:bg-amber-100' },
  { text: 'Consultar cuadro de tutelas', icon: Search, color: 'text-emerald-600 bg-emerald-50 border-emerald-200 hover:bg-emerald-100' },
  { text: 'Casos con fallo concede', icon: Brain, color: 'text-purple-600 bg-purple-50 border-purple-200 hover:bg-purple-100' },
  { text: 'Predecir resultado Bucaramanga', icon: Sparkles, color: 'text-rose-600 bg-rose-50 border-rose-200 hover:bg-rose-100' },
  { text: 'Casos por municipio', icon: BarChart3, color: 'text-cyan-600 bg-cyan-50 border-cyan-200 hover:bg-cyan-100' },
]

const WELCOME_MSG: ChatMessage = {
  role: 'ai',
  text: 'Soy tu **Agente Juridico IA** de la Gobernacion de Santander.\n\nTengo **16 herramientas** especializadas y acceso directo al **Cuadro de Tutelas**.\n\nPuedo consultar datos en tiempo real, analizar abogados, predecir resultados, verificar plazos, escanear alertas y mucho mas.\n\n**Escribeme lo que necesitas en lenguaje natural.**',
  timestamp: new Date(),
}

export default function AgentChat() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME_MSG])
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 300)
  }, [open])

  const handleSend = useCallback(async () => {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', text: q, timestamp: new Date() }])
    setLoading(true)
    try {
      const data = await runAgent(q)

      let responseText = ''
      if (data.answer) {
        responseText = data.answer
      } else if (data.plan) {
        responseText = `**Plan:** ${data.plan}\n\n`
        for (const step of (data.steps || [])) {
          const icon = step.status === 'completed' ? '**OK**' : '**ERROR**'
          responseText += `${icon} **${step.tool}** (${step.reason})\n`
          if (step.result?.result) {
            const res = step.result.result
            if (typeof res === 'object' && !Array.isArray(res)) {
              for (const [k, v] of Object.entries(res).slice(0, 6)) {
                const val = typeof v === 'object' ? JSON.stringify(v) : String(v)
                responseText += `- ${k}: ${val.substring(0, 120)}\n`
              }
            } else if (Array.isArray(res)) {
              responseText += `- ${res.length} resultados\n`
              for (const item of res.slice(0, 3)) {
                if (typeof item === 'object') {
                  const summary = Object.entries(item as Record<string, unknown>).slice(0, 3).map(([k,v]) => `${k}=${v}`).join(', ')
                  responseText += `  - ${summary}\n`
                }
              }
            }
          }
          responseText += '\n'
        }
        if (data.total_duration_ms) {
          responseText += `\n*${data.total_duration_ms}ms*`
        }
      }

      setMessages(prev => [...prev, {
        role: 'ai',
        text: responseText || 'Sin respuesta del agente',
        steps: data.steps,
        duration: data.total_duration_ms,
        timestamp: new Date(),
      }])
    } catch {
      try {
        const data = await chatWithAI(q)
        setMessages(prev => [...prev, { role: 'ai', text: data.response || 'Sin respuesta', timestamp: new Date() }])
      } catch {
        setMessages(prev => [...prev, { role: 'ai', text: 'Error al consultar el agente. Intenta de nuevo.', timestamp: new Date() }])
      }
    } finally {
      setLoading(false)
    }
  }, [input, loading])

  const handleReset = () => {
    setMessages([WELCOME_MSG])
    setInput('')
  }

  function renderMd(text: string) {
    return text
      .replace(/\*\*(.+?)\*\*/g, '<strong class="font-semibold text-foreground">$1</strong>')
      .replace(/\*(.+?)\*/g, '<em class="text-muted-foreground text-xs">$1</em>')
      .replace(/^- /gm, '<span class="flex items-start gap-1.5 mt-1"><span class="w-1 h-1 rounded-full bg-primary/40 mt-2 flex-shrink-0"></span><span>')
      .replace(/\n(?=<span class="flex)/g, '</span></span>\n')
      .replace(/\n/g, '<br/>')
  }

  // --- Floating button ---
  if (!open) {
    return (
      <motion.button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2.5 pl-4 pr-5 py-3.5 bg-primary text-primary-foreground rounded-2xl shadow-xl hover:shadow-2xl transition-shadow group"
        whileHover={{ scale: 1.03, y: -2 }}
        whileTap={{ scale: 0.97 }}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: 'spring', stiffness: 400, damping: 25 }}
      >
        <div className="relative">
          <Bot size={22} className="group-hover:rotate-12 transition-transform duration-300" />
          <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-emerald-400 rounded-full border-2 border-primary animate-pulse" />
        </div>
        <span className="text-sm font-semibold hidden sm:inline tracking-tight">Agente IA</span>
      </motion.button>
    )
  }

  // --- Chat panel ---
  const panelSize = expanded
    ? 'w-full h-full sm:w-[640px] sm:h-[85vh] sm:max-h-[800px]'
    : 'w-full sm:w-[440px] h-[600px]'

  return (
    <AnimatePresence>
      {/* Backdrop on mobile */}
      <motion.div
        className="fixed inset-0 z-40 bg-black/20 backdrop-blur-[2px] sm:hidden"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={() => setOpen(false)}
      />

      <motion.div
        data-testid="agent-chat-panel"
        className={cn(
          'fixed bottom-0 right-0 z-50 flex flex-col',
          'bg-background border border-border/60',
          'rounded-t-2xl sm:rounded-2xl',
          'shadow-[0_25px_60px_-12px_rgba(0,0,0,0.25)]',
          'sm:bottom-4 sm:right-4',
          'overflow-hidden',
          panelSize,
        )}
        initial={{ opacity: 0, y: 40, scale: 0.95 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 40, scale: 0.95 }}
        transition={{ type: 'spring', stiffness: 350, damping: 30 }}
        layout
      >
        {/* ── Header ── */}
        <div className="flex items-center justify-between px-4 py-3 bg-primary text-primary-foreground flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="relative">
              <div className="w-9 h-9 bg-white/15 rounded-xl flex items-center justify-center backdrop-blur-sm border border-white/10">
                <Bot size={18} />
              </div>
              <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-emerald-400 rounded-full border-2 border-primary" />
            </div>
            <div>
              <h3 className="font-semibold text-sm leading-tight tracking-tight">Agente Juridico IA</h3>
              <p className="text-[10px] text-white/50 leading-tight">
                {loading ? 'Procesando...' : '16 herramientas + Cuadro en vivo'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-0.5">
            <button
              onClick={handleReset}
              className="p-1.5 hover:bg-white/15 rounded-lg transition-colors"
              title="Nueva conversacion"
            >
              <RotateCcw size={14} />
            </button>
            <button
              onClick={() => setExpanded(!expanded)}
              className="p-1.5 hover:bg-white/15 rounded-lg transition-colors hidden sm:flex"
              title={expanded ? 'Reducir' : 'Expandir'}
            >
              {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            </button>
            <button
              onClick={() => { setOpen(false); navigate('/agent'); }}
              className="p-1.5 hover:bg-white/15 rounded-lg transition-colors"
              title="Ver herramientas"
            >
              <HelpCircle size={14} />
            </button>
            <button
              onClick={() => setOpen(false)}
              className="p-1.5 hover:bg-white/15 rounded-lg transition-colors"
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* ── Messages ── */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 bg-muted/30 overscroll-contain">
          {messages.map((msg, i) => (
            <motion.div
              key={i}
              className={cn('flex gap-2.5', msg.role === 'user' ? 'justify-end' : 'justify-start')}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i === messages.length - 1 ? 0.1 : 0 }}
            >
              {/* AI avatar */}
              {msg.role === 'ai' && (
                <div className="w-7 h-7 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Bot size={14} className="text-primary" />
                </div>
              )}

              <div className={cn(
                'max-w-[85%] rounded-2xl px-4 py-3 text-[13px] leading-relaxed',
                msg.role === 'user'
                  ? 'bg-primary text-primary-foreground rounded-br-md'
                  : 'bg-card border border-border/60 text-foreground rounded-bl-md shadow-sm'
              )}>
                {msg.role === 'ai' ? (
                  <div
                    className="[&_strong]:text-primary [&_li]:text-[12px]"
                    dangerouslySetInnerHTML={{ __html: renderMd(msg.text) }}
                  />
                ) : (
                  <span>{msg.text}</span>
                )}

                {/* Tool badges */}
                {msg.steps && msg.steps.length > 0 && (
                  <div className="mt-3 pt-2.5 border-t border-border/40">
                    <p className="text-[10px] text-muted-foreground font-medium mb-1.5 uppercase tracking-wider">
                      Herramientas ejecutadas
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {msg.steps.map((s: any, j: number) => (
                        <span key={j} className={cn(
                          'inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-md font-medium border',
                          s.status === 'completed'
                            ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                            : 'bg-red-50 text-red-700 border-red-200'
                        )}>
                          <Zap size={8} />
                          {s.tool}
                        </span>
                      ))}
                    </div>
                    {msg.duration && (
                      <p className="text-[10px] text-muted-foreground mt-1.5">{(msg.duration / 1000).toFixed(1)}s</p>
                    )}
                  </div>
                )}
              </div>

              {/* User avatar */}
              {msg.role === 'user' && (
                <div className="w-7 h-7 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center flex-shrink-0 mt-0.5">
                  <User size={14} className="text-primary" />
                </div>
              )}
            </motion.div>
          ))}

          {/* Loading indicator */}
          {loading && (
            <motion.div
              className="flex gap-2.5 justify-start"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <div className="w-7 h-7 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center flex-shrink-0">
                <Bot size={14} className="text-primary" />
              </div>
              <div className="bg-card border border-border/60 rounded-2xl rounded-bl-md px-4 py-3 shadow-sm">
                <div className="flex items-center gap-2.5">
                  <div className="flex gap-1">
                    {[0, 1, 2].map(i => (
                      <motion.div
                        key={i}
                        className="w-1.5 h-1.5 rounded-full bg-primary/40"
                        animate={{ scale: [1, 1.5, 1], opacity: [0.4, 1, 0.4] }}
                        transition={{ repeat: Infinity, duration: 1, delay: i * 0.2 }}
                      />
                    ))}
                  </div>
                  <span className="text-xs text-muted-foreground">Ejecutando herramientas...</span>
                </div>
              </div>
            </motion.div>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* ── Quick commands (only on first message) ── */}
        <AnimatePresence>
          {messages.length <= 1 && !loading && (
            <motion.div
              className="px-3 py-2.5 border-t border-border/40 bg-background"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
            >
              <p className="text-[10px] text-muted-foreground font-medium mb-2 uppercase tracking-wider px-1">
                Sugerencias rapidas
              </p>
              <div className="grid grid-cols-2 gap-1.5">
                {QUICK_COMMANDS.map(({ text, icon: Icon, color }) => (
                  <button
                    key={text}
                    onClick={() => { setInput(text); setTimeout(() => inputRef.current?.focus(), 50) }}
                    className={cn(
                      'flex items-center gap-2 text-[11px] font-medium px-2.5 py-2 rounded-lg border transition-colors text-left',
                      color,
                    )}
                  >
                    <Icon size={12} className="flex-shrink-0" />
                    <span className="truncate">{text}</span>
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Input ── */}
        <div className="flex items-center gap-2 px-3 py-3 border-t border-border/40 bg-background flex-shrink-0">
          <div className="flex-1 relative">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="Pregunta al agente..."
              disabled={loading}
              className={cn(
                'w-full text-sm bg-muted/50 border border-border rounded-xl px-4 py-2.5',
                'placeholder:text-muted-foreground/50',
                'focus:bg-background focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/10',
                'disabled:opacity-40 transition-all',
              )}
            />
          </div>
          <motion.button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            className={cn(
              'p-2.5 rounded-xl transition-colors flex-shrink-0',
              input.trim()
                ? 'bg-primary text-primary-foreground shadow-md hover:shadow-lg'
                : 'bg-muted text-muted-foreground',
            )}
            whileHover={input.trim() ? { scale: 1.05 } : {}}
            whileTap={input.trim() ? { scale: 0.95 } : {}}
          >
            <Send size={16} />
          </motion.button>
        </div>
      </motion.div>
    </AnimatePresence>
  )
}
