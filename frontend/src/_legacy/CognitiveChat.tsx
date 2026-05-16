import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import {
  Send, X, Sparkles, User, Loader2, Maximize2, Minimize2,
  Scale, ChevronDown, ChevronRight, MessageCircle,
} from 'lucide-react'
import api from '../services/api'
import { motion } from 'motion/react'
import { cn } from '@/lib/utils'

// ─── Tipos ─────────────────────────────────────────────────────

interface ToolTrace {
  name: string
  args: Record<string, unknown>
  result_summary: string
  duration_ms: number
}

interface ChatMessage {
  role: 'user' | 'assistant' | 'thinking'
  text: string
  tools?: ToolTrace[]
  total_ms?: number
  timestamp: number
}

interface ChatStatus {
  ready: boolean       // el chat (Tier-1 determinístico) siempre está disponible
}

// Sugerencias contextuales por vista ─────────────────────────

const SUGGESTIONS_GLOBAL = [
  '¿Cuántas tutelas activas hay?',
  'Top 5 derechos vulnerados más frecuentes',
  'Tutelas por dirección — distribución',
  '¿Cuántas tutelas con incidente en sanción?',
]

const SUGGESTIONS_CASE = [
  'Casos parecidos a este',
  '¿Cuál es el probable resultado de este caso?',
  '¿Hay algún incidente vinculado?',
]

// Lenguaje técnico → humano ─────────────────────────────────

const TOOL_LABELS: Record<string, string> = {
  search_similar_cases: 'Casos parecidos en el archivo',
  query_cases: 'Consulta a la base de tutelas',
  get_case: 'Detalle de un caso',
}

// ─── Componentes auxiliares ─────────────────────────────────

function ToolTracePill({ t }: { t: ToolTrace }) {
  const [open, setOpen] = useState(false)
  const label = TOOL_LABELS[t.name] ?? t.name
  return (
    <div className="rounded-md border border-border bg-muted/30 text-[11px]">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-1.5 px-2 py-1 text-left hover:bg-muted/60"
      >
        {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        <Scale size={11} className="text-primary" />
        <span className="flex-1 truncate">{label}</span>
        <span className="text-muted-foreground tabular-nums">{t.duration_ms.toFixed(0)}ms</span>
      </button>
      {open && (
        <div className="px-2 py-1.5 border-t border-border space-y-1 text-[10px] text-muted-foreground">
          <div className="font-mono whitespace-pre-wrap break-all">
            {JSON.stringify(t.args, null, 0).slice(0, 220)}
          </div>
          <div className="text-foreground/70">{t.result_summary}</div>
        </div>
      )}
    </div>
  )
}

function MessageBubble({ m }: { m: ChatMessage }) {
  if (m.role === 'thinking') {
    return (
      <div className="flex items-start gap-2 px-1">
        <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
          <Sparkles size={12} className="text-primary animate-pulse" />
        </div>
        <div className="flex-1 pt-1">
          <div className="text-xs text-muted-foreground italic">{m.text}</div>
        </div>
      </div>
    )
  }

  const isUser = m.role === 'user'
  return (
    <div className={cn('flex items-start gap-2 px-1', isUser && 'flex-row-reverse')}>
      <div className={cn(
        'w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-0.5',
        isUser ? 'bg-zinc-200 text-zinc-600' : 'bg-primary/10 text-primary'
      )}>
        {isUser ? <User size={12} /> : <Sparkles size={12} />}
      </div>
      <div className={cn('flex-1 min-w-0 max-w-[85%]', isUser && 'flex flex-col items-end')}>
        <div className={cn(
          'rounded-lg px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap break-words',
          isUser
            ? 'bg-primary text-primary-foreground'
            : 'bg-muted text-foreground'
        )}>
          {m.text}
        </div>
        {m.tools && m.tools.length > 0 && (
          <div className="mt-1.5 space-y-1 w-full">
            {m.tools.map((t, i) => <ToolTracePill key={i} t={t} />)}
          </div>
        )}
        {m.total_ms !== undefined && (
          <div className="text-[10px] text-muted-foreground mt-1">
            {(m.total_ms / 1000).toFixed(1)}s
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Chat principal ─────────────────────────────────────────

export default function CognitiveChat() {
  const params = useParams<{ id?: string }>()
  const currentCaseId = params.id ? parseInt(params.id, 10) : undefined
  const currentView = window.location.pathname

  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<ChatStatus | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Auto-scroll
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loading])

  // Health check al abrir (el chat Tier-1 está siempre disponible; no hace falta polling)
  useEffect(() => {
    if (!open) return
    let cancel = false
    api.get('/chat/health')
      .then(() => { if (!cancel) setStatus({ ready: true }) })
      .catch(() => { if (!cancel) setStatus({ ready: false }) })
    return () => { cancel = true }
  }, [open])

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 200)
  }, [open])

  const send = useCallback(async (text?: string) => {
    const q = (text ?? input).trim()
    if (!q || loading) return
    setInput('')
    const userMsg: ChatMessage = { role: 'user', text: q, timestamp: Date.now() }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const r = await api.post('/chat/', {
        message: q,
        context: currentCaseId
          ? { current_case_id: currentCaseId, current_view: currentView }
          : { current_view: currentView },
      }, { timeout: 30000 })

      setMessages(prev => [
        ...prev.filter(m => m.role !== 'thinking'),
        { role: 'assistant', text: r.data?.answer || 'Sin respuesta.', timestamp: Date.now() },
      ])
    } catch (e: unknown) {
      setMessages(prev => [
        ...prev.filter(m => m.role !== 'thinking'),
        {
          role: 'assistant',
          text: 'No pude procesar la consulta. Revisa que el backend esté disponible.',
          timestamp: Date.now(),
        },
      ])
    } finally {
      setLoading(false)
    }
  }, [input, loading, messages, currentCaseId, currentView])

  const suggestions = currentCaseId ? SUGGESTIONS_CASE : SUGGESTIONS_GLOBAL

  // Botón flotante cuando está cerrado
  if (!open) {
    return (
      <motion.button
        initial={{ scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-50 group flex items-center gap-2 pl-3 pr-4 py-2.5 rounded-full bg-primary text-primary-foreground shadow-lg hover:shadow-xl transition-shadow"
        aria-label="Abrir asistente jurídico"
      >
        <Sparkles size={16} className="group-hover:rotate-12 transition-transform" />
        <span className="text-sm font-medium">Asistente jurídico</span>
      </motion.button>
    )
  }

  return (
    <motion.div
      initial={{ x: '100%', opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      exit={{ x: '100%', opacity: 0 }}
      transition={{ type: 'spring', damping: 25, stiffness: 300 }}
      className={cn(
        'fixed top-0 right-0 z-50 h-full bg-card border-l border-border shadow-2xl flex flex-col',
        expanded ? 'w-[640px]' : 'w-[420px]'
      )}
    >
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-border bg-muted/30 flex items-center gap-2">
        <Sparkles size={16} className="text-primary" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold">Asistente jurídico</div>
          <div className="text-[10px] text-muted-foreground flex items-center gap-1.5">
            {status?.ready ? (
              <><span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> Listo</>
            ) : (
              <><span className="w-1.5 h-1.5 rounded-full bg-zinc-400" /> En espera</>
            )}
          </div>
        </div>
        <button onClick={() => setExpanded(!expanded)} className="p-1.5 hover:bg-muted rounded" title={expanded ? 'Reducir' : 'Expandir'}>
          {expanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        </button>
        <button onClick={() => setOpen(false)} className="p-1.5 hover:bg-muted rounded" title="Cerrar">
          <X size={14} />
        </button>
      </div>

      {/* Mensajes */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && (
          <div className="space-y-3 pt-4">
            <div className="text-center px-4">
              <Sparkles size={32} className="mx-auto text-primary/40 mb-2" />
              <p className="text-sm font-medium text-foreground">¿En qué te ayudo?</p>
              <p className="text-xs text-muted-foreground mt-1">
                {currentCaseId
                  ? `Estás viendo el caso #${currentCaseId}.`
                  : 'Pregúntame sobre las tutelas del cuadro o sobre el archivo histórico.'}
              </p>
            </div>
            <div className="space-y-1.5">
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  onClick={() => send(s)}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg border border-border bg-card hover:bg-muted hover:border-primary/30 transition-colors flex items-center gap-2"
                >
                  <MessageCircle size={11} className="text-muted-foreground shrink-0" />
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => <MessageBubble key={i} m={m} />)}
        {loading && messages[messages.length - 1]?.role !== 'thinking' && (
          <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
            <Loader2 size={12} className="animate-spin" />
            Consultando archivo…
          </div>
        )}
        <div ref={endRef} />
      </div>

      {/* Input */}
      <div className="flex-shrink-0 border-t border-border p-3">
        <div className="relative">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send()
              }
            }}
            disabled={loading}
            placeholder={loading ? 'Procesando…' : 'Escribe tu pregunta jurídica…'}
            rows={2}
            className="w-full text-sm px-3 py-2 pr-10 rounded-lg border border-input bg-background focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/30 resize-none"
          />
          <button
            onClick={() => send()}
            disabled={loading || !input.trim()}
            className="absolute bottom-2 right-2 p-1.5 rounded-md bg-primary text-primary-foreground disabled:opacity-30 hover:bg-primary/90"
            title="Enviar (Enter)"
          >
            <Send size={13} />
          </button>
        </div>
        <p className="text-[10px] text-muted-foreground mt-1.5 px-0.5">
          Las respuestas son orientativas. Verifica con el expediente.
        </p>
      </div>
    </motion.div>
  )
}
