import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Brain, Search, BarChart3, Settings2, Cpu,
  ChevronDown, ChevronRight, Zap, HelpCircle,
  MessageCircle, Wrench, Sparkles, Shield,
  Terminal, ArrowRight, Copy, Check,
} from 'lucide-react'
import { getAgentTools } from '../services/api'
import toast from 'react-hot-toast'
import PageShell from '@/components/PageShell'
import PageHeader from '@/components/PageHeader'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'

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
    label: 'Gestión', description: 'Estadísticas, alertas, municipios, administracion del sistema',
  },
  extraction: {
    icon: Cpu, color: 'text-green-600', bg: 'bg-green-50 border-green-200',
    label: 'Extracción', description: 'Extraer datos de documentos con IA, validar FOREST',
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
    <TooltipProvider>
      <PageShell className="max-w-5xl mx-auto">
        <PageHeader
          title="Agente Juridico IA"
          subtitle={`${tools.length} herramientas especializadas en tutelas colombianas. Dale instrucciones en lenguaje natural y el agente decide que herramientas usar.`}
          icon={Brain}
        />

        {/* How it works */}
        <Card className="border-primary/10 bg-primary/5">
          <CardContent className="py-6">
            <h2 className="font-semibold text-foreground flex items-center gap-2 mb-4">
              <Sparkles size={18} className="text-primary" />
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
                  <div className="w-10 h-10 bg-background rounded-xl border border-primary/20 flex items-center justify-center mb-2 shadow-sm">
                    <s.icon size={18} className="text-primary" />
                  </div>
                  <p className="text-xs font-bold text-primary">Paso {s.step}</p>
                  <p className="text-xs font-semibold text-foreground">{s.title}</p>
                  <p className="text-[10px] text-muted-foreground">{s.desc}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Tools by category */}
        <div>
          <h2 className="font-semibold text-foreground flex items-center gap-2 mb-4">
            <Wrench size={18} />
            Herramientas disponibles ({tools.length})
          </h2>

          {isLoading ? (
            <div className="text-center py-8 text-muted-foreground">Cargando herramientas...</div>
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
                        <p className="font-semibold text-foreground">{catInfo.label}</p>
                        <p className="text-xs text-muted-foreground">{catInfo.description}</p>
                      </div>
                      <Badge variant="outline" className="bg-background text-muted-foreground font-bold">
                        {catTools.length}
                      </Badge>
                      {isExpanded
                        ? <ChevronDown size={16} className="text-muted-foreground" />
                        : <ChevronRight size={16} className="text-muted-foreground" />}
                    </button>

                    {isExpanded && (
                      <div className="border-t bg-white/80 divide-y divide-border">
                        {catTools.map((tool: any) => (
                          <div key={tool.name} className="px-5 py-4">
                            <div className="flex items-start gap-3">
                              <code className="text-xs bg-muted text-primary px-2 py-1 rounded font-mono flex-shrink-0">
                                {tool.name}
                              </code>
                              <div className="flex-1">
                                <p className="text-sm text-foreground">{tool.description}</p>
                                {tool.params && tool.params.length > 0 && (
                                  <div className="mt-2 space-y-1">
                                    {tool.params.map((p: any) => (
                                      <div key={p.name} className="flex items-center gap-2 text-xs">
                                        <code className="bg-muted px-1.5 py-0.5 rounded text-muted-foreground font-mono">{p.name}</code>
                                        <span className="text-muted-foreground/60">{p.type}</span>
                                        <span className="text-muted-foreground">- {p.description}</span>
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
          <h2 className="font-semibold text-foreground flex items-center gap-2 mb-2">
            <HelpCircle size={18} />
            Ejemplos de instrucciones
          </h2>
          <p className="text-sm text-muted-foreground mb-4">
            Copia cualquier comando y pegalo en el chat del Agente IA (boton flotante en la esquina inferior derecha).
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {exampleCommands.map((ex, i) => (
              <Tooltip key={i}>
                <TooltipTrigger render={<div />}>
                  <Card
                    className="group cursor-pointer hover:border-primary/30 hover:shadow-sm transition"
                    onClick={() => copyCommand(ex.command)}
                  >
                    <CardContent className="py-4">
                      <div className="flex items-start gap-3">
                        <div className="w-8 h-8 bg-muted rounded-lg flex items-center justify-center flex-shrink-0 group-hover:bg-primary/10 transition">
                          <ArrowRight size={14} className="text-muted-foreground group-hover:text-primary" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-foreground group-hover:text-primary transition">
                            "{ex.command}"
                          </p>
                          <p className="text-xs text-muted-foreground mt-1">{ex.description}</p>
                          <div className="flex items-center gap-2 mt-2">
                            <code className="text-[10px] bg-muted text-muted-foreground px-1.5 py-0.5 rounded font-mono">
                              {ex.tool}
                            </code>
                            <span className="text-[10px] text-muted-foreground/50">
                              {copiedCmd === ex.command ? (
                                <span className="flex items-center gap-1 text-green-500"><Check size={10} /> Copiado</span>
                              ) : (
                                <span className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition"><Copy size={10} /> Click para copiar</span>
                              )}
                            </span>
                          </div>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </TooltipTrigger>
                <TooltipContent side="top">
                  <p>Copiar y usar en el Agente IA</p>
                </TooltipContent>
              </Tooltip>
            ))}
          </div>
        </div>

        {/* Secciones de tokens/Gemini e info técnica eliminadas v4.9 — no relevantes para abogados */}
      </PageShell>
    </TooltipProvider>
  )
}
