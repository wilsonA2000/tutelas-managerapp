import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { MessageCircle, Send, X, Loader2, HelpCircle } from 'lucide-react'
import { chatWithAI, runAgent } from '../services/api'

interface ChatMessage {
  role: 'user' | 'ai'
  text: string
  steps?: any[]
  duration?: number
}

export default function AgentChat() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: 'ai', text: 'Soy tu **Agente Juridico IA**. Tengo 14 herramientas especializadas.\n\nPuedo: buscar casos, analizar abogados, predecir resultados, verificar plazos, escanear alertas, buscar en Knowledge Base y mas.\n\n**Dime que necesitas en lenguaje natural.**' },
  ])
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend() {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', text: q }])
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
      }])
    } catch {
      try {
        const data = await chatWithAI(q)
        setMessages(prev => [...prev, { role: 'ai', text: data.response || 'Sin respuesta' }])
      } catch {
        setMessages(prev => [...prev, { role: 'ai', text: 'Error al consultar el agente. Intenta de nuevo.' }])
      }
    } finally {
      setLoading(false)
    }
  }

  function renderMd(text: string) {
    return text
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/^\* /gm, '<li style="margin-left:16px">')
      .replace(/^- /gm, '<li style="margin-left:16px">')
      .replace(/\n/g, '<br/>')
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 bg-[#1A5276] text-white rounded-full shadow-lg hover:bg-[#154360] transition-all hover:scale-105"
      >
        <MessageCircle size={20} />
        <span className="text-sm font-medium hidden sm:inline">Agente IA</span>
      </button>
    )
  }

  return (
    <div className="fixed bottom-0 right-0 z-50 w-full sm:w-[480px] sm:bottom-4 sm:right-4 flex flex-col bg-white border border-gray-200 rounded-t-2xl sm:rounded-2xl shadow-2xl overflow-hidden" style={{ height: '560px' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-[#1A5276] to-[#154360] text-white flex-shrink-0">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-white/20 rounded-lg flex items-center justify-center">
            <MessageCircle size={15} />
          </div>
          <div>
            <span className="font-semibold text-sm">Agente Juridico IA</span>
            <span className="text-[10px] text-white/60 ml-2">14 herramientas</span>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => { setOpen(false); navigate('/agent'); }}
            className="p-1.5 hover:bg-white/20 rounded-lg transition-colors"
            title="Ver herramientas y ayuda"
          >
            <HelpCircle size={16} />
          </button>
          <button onClick={() => setOpen(false)} className="p-1.5 hover:bg-white/20 rounded-lg transition-colors">
            <X size={16} />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-gray-50">
        {messages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[90%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
              msg.role === 'user'
                ? 'bg-[#1A5276] text-white rounded-br-md'
                : 'bg-white border border-gray-200 text-gray-700 rounded-bl-md shadow-sm'
            }`}>
              {msg.role === 'ai' ? (
                <div dangerouslySetInnerHTML={{ __html: renderMd(msg.text) }} />
              ) : (
                msg.text
              )}
              {msg.steps && msg.steps.length > 0 && (
                <div className="mt-2 pt-2 border-t border-gray-100">
                  <p className="text-[10px] text-gray-400 font-medium mb-1">HERRAMIENTAS USADAS:</p>
                  {msg.steps.map((s: any, j: number) => (
                    <span key={j} className={`inline-block text-[10px] px-1.5 py-0.5 rounded mr-1 mb-0.5 ${
                      s.status === 'completed' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                    }`}>
                      {s.tool}
                    </span>
                  ))}
                  {msg.duration && (
                    <span className="text-[10px] text-gray-400 ml-1">{msg.duration}ms</span>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-md px-4 py-3 shadow-sm">
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <Loader2 size={14} className="animate-spin" />
                Ejecutando herramientas...
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="flex items-center gap-2 px-3 py-3 border-t border-gray-200 bg-white flex-shrink-0">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Instruccion para el agente..."
          disabled={loading}
          className="flex-1 text-sm border border-gray-200 rounded-xl px-3 py-2 focus:border-[#1A5276] focus:outline-none focus:ring-1 focus:ring-[#1A5276]/20 disabled:opacity-50"
        />
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          className="p-2.5 bg-[#1A5276] text-white rounded-xl hover:bg-[#154360] disabled:opacity-40 transition-colors"
        >
          <Send size={16} />
        </button>
      </div>

      {/* Quick commands */}
      {messages.length <= 1 && (
        <div className="px-3 pb-3 flex flex-wrap gap-1.5 bg-white">
          {[
            'Dame las estadisticas generales',
            'Escanear alertas criticas',
            'Predecir resultado para Bucaramanga',
            'Buscar caso personero Guavata',
            'Analizar abogado Cruz',
            'Casos por municipio',
          ].map((q) => (
            <button
              key={q}
              onClick={() => { setInput(q); }}
              className="text-xs bg-gray-100 text-gray-600 px-2.5 py-1.5 rounded-lg hover:bg-[#1A5276]/10 hover:text-[#1A5276] transition-colors"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
