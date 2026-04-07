import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Brain, Search, BarChart3, Settings2, Cpu,
  ChevronDown, ChevronRight, Zap, HelpCircle,
  MessageCircle, Wrench, Sparkles, Shield,
  Terminal, ArrowRight, Copy, Check,
} from 'lucide-react'
import { getAgentTools, getAgentTokenStats } from '../services/api'
import toast from 'react-hot-toast'

const categoryConfig: Record<string, { icon: any; color: string; bg: string; label: string; description: string }> = {
  search: {
    icon: Search, color: 'text-blue-600', bg: 'bg-blue-50 border-blue-200',
    label: 'Busqueda', description: 'Buscar casos, emails y conocimiento en todo el sistema',
  },
  analysis: {
    icon: BarChart3, color: 'text-purple-600', bg: 'bg-purple-50 border-purple-200',
    label: 'Analisis', description: 'Verificar plazos, predecir resultados, analizar rendimiento',
  },
  management: {
    icon: Settings2, color: 'text-amber-600', bg: 'bg-amber-50 border-amber-200',
    label: 'Gestion', description: 'Estadisticas, alertas, municipios, administracion del sistema',
  },
  extraction: {
    icon: Cpu, color: 'text-green-600', bg: 'bg-green-50 border-green-200',
    label: 'Extraccion', description: 'Extraer datos de documentos con IA, validar FOREST',
  },
}

const exampleCommands = [
  { command: 'Dame las estadisticas generales', description: 'Resumen completo: casos, documentos, emails, favorabilidad', tool: 'estadisticas_generales' },
  { command: 'Buscar caso personero Guavata', description: 'Busca por radicado, accionante, juzgado o texto libre', tool: 'buscar_caso' },
  { command: 'Analizar abogado Cruz', description: 'Rendimiento: casos asignados, activos, tasa favorabilidad', tool: 'analizar_abogado' },
  { command: 'Escanear alertas criticas', description: 'Detecta plazos vencidos, anomalias, emails sin caso', tool: 'escanear_alertas' },
  { command: 'Predecir resultado para Bucaramanga', description: 'Prediccion basada en datos historicos de juzgados', tool: 'predecir_resultado' },
  { command: 'Verificar plazo del caso 27', description: 'Calcula dias restantes para cumplimiento de fallo', tool: 'verificar_plazo' },
  { command: 'Buscar en Knowledge Base educacion Vetas', description: 'Full-text search en 2389 entradas (PDFs, emails, DOCX)', tool: 'buscar_conocimiento' },
  { command: 'Casos por municipio', description: 'Lista casos agrupados por ciudad con conteo', tool: 'casos_por_municipio' },
  { command: 'Validar FOREST 20260054965', description: 'Verifica si un numero FOREST es real o alucinado', tool: 'validar_forest' },
  { command: 'Ver razonamiento del caso 93', description: 'Cadena de razonamiento de la ultima extraccion IA', tool: 'ver_razonamiento' },
]

export default function AgentTools() {
  const { data: toolsData, isLoading } = useQuery({
    queryKey: ['agent-tools'],
    queryFn: getAgentTools,
  })
  const { data: tokenData } = useQuery({
    queryKey: ['agent-tokens'],
    queryFn: getAgentTokenStats,
  })
  const [expandedCat, setExpandedCat] = useState<string | null>(null)
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null)

  const tools = toolsData?.tools || []
  const toolsByCategory: Record<string, any[]> = {}
  for (const tool of tools) {
    if (!toolsByCategory[tool.category]) toolsByCategory[tool.category] = []
    toolsByCategory[tool.category].push(tool)
  }

  const copyCommand = (cmd: string) => {
    navigator.clipboard.writeText(cmd)
    setCopiedCmd(cmd)
    toast.success('Comando copiado')
    setTimeout(() => setCopiedCmd(null), 2000)
  }

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-start gap-4">
        <div className="w-14 h-14 bg-gradient-to-br from-[#1A5276] to-[#154360] rounded-2xl flex items-center justify-center flex-shrink-0 shadow-lg">
          <Brain className="w-7 h-7 text-white" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Agente Juridico IA</h1>
          <p className="text-sm text-gray-500 mt-1">
            {tools.length} herramientas especializadas en tutelas colombianas.
            Dale instrucciones en lenguaje natural y el agente decide que herramientas usar.
          </p>
        </div>
      </div>

      {/* How it works */}
      <div className="bg-gradient-to-r from-[#1A5276]/5 to-[#154360]/5 rounded-2xl p-6 border border-[#1A5276]/10">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2 mb-4">
          <Sparkles size={18} className="text-[#1A5276]" />
          Como funciona el Agente
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
          {[
            { step: '1', title: 'Tu instruccion', desc: 'Escribes en lenguaje natural', icon: MessageCircle },
            { step: '2', title: 'Planifica', desc: 'IA decide que herramientas usar', icon: Brain },
            { step: '3', title: 'Ejecuta', desc: 'Corre las herramientas en orden', icon: Zap },
            { step: '4', title: 'Valida', desc: 'Verifica resultados y conflictos', icon: Shield },
            { step: '5', title: 'Responde', desc: 'Te muestra resultados + razonamiento', icon: Terminal },
          ].map((s, i) => (
            <div key={i} className="flex flex-col items-center text-center">
              <div className="w-10 h-10 bg-white rounded-xl border border-[#1A5276]/20 flex items-center justify-center mb-2 shadow-sm">
                <s.icon size={18} className="text-[#1A5276]" />
              </div>
              <p className="text-xs font-bold text-[#1A5276]">Paso {s.step}</p>
              <p className="text-xs font-semibold text-gray-700">{s.title}</p>
              <p className="text-[10px] text-gray-400">{s.desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Tools by category */}
      <div>
        <h2 className="font-semibold text-gray-800 flex items-center gap-2 mb-4">
          <Wrench size={18} />
          Herramientas disponibles ({tools.length})
        </h2>

        {isLoading ? (
          <div className="text-center py-8 text-gray-400">Cargando herramientas...</div>
        ) : (
          <div className="space-y-3">
            {Object.entries(categoryConfig).map(([catKey, catInfo]) => {
              const catTools = toolsByCategory[catKey] || []
              if (catTools.length === 0) return null
              const isExpanded = expandedCat === catKey
              const Icon = catInfo.icon

              return (
                <div key={catKey} className={`rounded-xl border overflow-hidden ${catInfo.bg}`}>
                  <button
                    onClick={() => setExpandedCat(isExpanded ? null : catKey)}
                    className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-white/50 transition"
                  >
                    <Icon size={20} className={catInfo.color} />
                    <div className="flex-1">
                      <p className="font-semibold text-gray-800">{catInfo.label}</p>
                      <p className="text-xs text-gray-500">{catInfo.description}</p>
                    </div>
                    <span className="text-xs font-bold text-gray-400 bg-white px-2 py-1 rounded-full">
                      {catTools.length}
                    </span>
                    {isExpanded ? <ChevronDown size={16} className="text-gray-400" /> : <ChevronRight size={16} className="text-gray-400" />}
                  </button>

                  {isExpanded && (
                    <div className="border-t bg-white/80 divide-y divide-gray-100">
                      {catTools.map((tool: any) => (
                        <div key={tool.name} className="px-5 py-4">
                          <div className="flex items-start gap-3">
                            <code className="text-xs bg-gray-100 text-[#1A5276] px-2 py-1 rounded font-mono flex-shrink-0">
                              {tool.name}
                            </code>
                            <div className="flex-1">
                              <p className="text-sm text-gray-700">{tool.description}</p>
                              {tool.params && tool.params.length > 0 && (
                                <div className="mt-2 space-y-1">
                                  {tool.params.map((p: any) => (
                                    <div key={p.name} className="flex items-center gap-2 text-xs">
                                      <code className="bg-gray-50 px-1.5 py-0.5 rounded text-gray-600 font-mono">{p.name}</code>
                                      <span className="text-gray-400">{p.type}</span>
                                      <span className="text-gray-500">- {p.description}</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Example commands */}
      <div>
        <h2 className="font-semibold text-gray-800 flex items-center gap-2 mb-4">
          <HelpCircle size={18} />
          Ejemplos de instrucciones
        </h2>
        <p className="text-sm text-gray-500 mb-4">
          Copia cualquier comando y pegalo en el chat del Agente IA (boton flotante en la esquina inferior derecha).
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {exampleCommands.map((ex, i) => (
            <div
              key={i}
              className="group bg-white rounded-xl border border-gray-200 p-4 hover:border-[#1A5276]/30 hover:shadow-sm transition cursor-pointer"
              onClick={() => copyCommand(ex.command)}
            >
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 bg-gray-50 rounded-lg flex items-center justify-center flex-shrink-0 group-hover:bg-[#1A5276]/10 transition">
                  <ArrowRight size={14} className="text-gray-400 group-hover:text-[#1A5276]" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 group-hover:text-[#1A5276] transition">
                    "{ex.command}"
                  </p>
                  <p className="text-xs text-gray-400 mt-1">{ex.description}</p>
                  <div className="flex items-center gap-2 mt-2">
                    <code className="text-[10px] bg-gray-50 text-gray-500 px-1.5 py-0.5 rounded font-mono">
                      {ex.tool}
                    </code>
                    <span className="text-[10px] text-gray-300">
                      {copiedCmd === ex.command ? (
                        <span className="flex items-center gap-1 text-green-500"><Check size={10} /> Copiado</span>
                      ) : (
                        <span className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition"><Copy size={10} /> Click para copiar</span>
                      )}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Token Management */}
      {tokenData && (
        <div className="bg-white rounded-xl border p-5">
          <h2 className="font-semibold text-gray-800 flex items-center gap-2 mb-4">
            <Zap size={18} className="text-amber-500" />
            Gestion de Tokens e IA
          </h2>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <div className="text-center p-3 bg-green-50 rounded-lg">
              <p className="text-xl font-bold text-green-600">${tokenData.stats.total_cost_usd}</p>
              <p className="text-[10px] text-gray-500">Costo total USD</p>
            </div>
            <div className="text-center p-3 bg-blue-50 rounded-lg">
              <p className="text-xl font-bold text-blue-600">{(tokenData.stats.total_tokens / 1000).toFixed(0)}K</p>
              <p className="text-[10px] text-gray-500">Tokens consumidos</p>
            </div>
            <div className="text-center p-3 bg-purple-50 rounded-lg">
              <p className="text-xl font-bold text-purple-600">{tokenData.stats.calls_month}</p>
              <p className="text-[10px] text-gray-500">Llamadas este mes</p>
            </div>
            <div className="text-center p-3 rounded-lg" style={{
              backgroundColor: tokenData.stats.budget_status === 'OK' ? '#f0fdf4' :
                tokenData.stats.budget_status === 'WARNING' ? '#fffbeb' : '#fef2f2'
            }}>
              <p className={`text-xl font-bold ${
                tokenData.stats.budget_status === 'OK' ? 'text-green-600' :
                tokenData.stats.budget_status === 'WARNING' ? 'text-amber-600' : 'text-red-600'
              }`}>{tokenData.stats.budget_status}</p>
              <p className="text-[10px] text-gray-500">Estado presupuesto</p>
            </div>
          </div>

          {/* Savings comparison */}
          {tokenData.savings && (
            <div className="bg-gradient-to-r from-green-50 to-emerald-50 rounded-lg p-4 mb-4 border border-green-200">
              <p className="text-xs font-semibold text-green-800 mb-2">Ahorro usando Gemini Flash (gratis)</p>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <p className="text-lg font-bold text-green-600">${tokenData.savings.savings.vs_gpt4o}</p>
                  <p className="text-[10px] text-gray-500">vs GPT-4o</p>
                </div>
                <div>
                  <p className="text-lg font-bold text-green-600">${tokenData.savings.savings.vs_claude_sonnet}</p>
                  <p className="text-[10px] text-gray-500">vs Claude Sonnet</p>
                </div>
                <div>
                  <p className="text-lg font-bold text-green-600">${tokenData.savings.savings.vs_claude_haiku}</p>
                  <p className="text-[10px] text-gray-500">vs Claude Haiku</p>
                </div>
              </div>
            </div>
          )}

          {/* Optimization tips */}
          {tokenData.savings?.optimization_tips && (
            <div className="space-y-1.5">
              <p className="text-xs font-semibold text-gray-600">Tips de optimizacion:</p>
              {tokenData.savings.optimization_tips.map((tip: string, i: number) => (
                <p key={i} className="text-xs text-gray-500 flex items-start gap-2">
                  <Sparkles size={12} className="text-amber-400 flex-shrink-0 mt-0.5" />
                  {tip}
                </p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Technical info */}
      <div className="bg-gray-50 rounded-xl border p-5">
        <h3 className="text-sm font-semibold text-gray-600 mb-3">Informacion tecnica</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
          <div>
            <p className="text-2xl font-bold text-[#1A5276]">{tools.length}</p>
            <p className="text-xs text-gray-500">Herramientas</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-[#1A5276]">92</p>
            <p className="text-xs text-gray-500">API Endpoints</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-[#1A5276]">2389</p>
            <p className="text-xs text-gray-500">KB Entries</p>
          </div>
          <div>
            <p className="text-2xl font-bold text-[#1A5276]">1M</p>
            <p className="text-xs text-gray-500">Tokens Context</p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {['Gemini 2.5 Flash (gratis)', 'SQLite FTS5', 'FastAPI', 'React 19', 'JWT Auth', 'Tool Registry'].map(tag => (
            <span key={tag} className="text-[10px] px-2 py-1 bg-white border rounded-full text-gray-500">{tag}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
