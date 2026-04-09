import React, { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import gsap from 'gsap'
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import {
  FileText, CheckCircle, XCircle, BarChart2,
  Clock, User, MapPin, AlertCircle,
  Play, Loader2, Mail,
  Cpu, Download,
  Scale, Shield, Gavel, TrendingUp, Info,
} from 'lucide-react'
import {
  getKPIs, getCharts, getActivity,
  getExtractionProgress, checkInbox, getCheckInboxStatus, getMonitorStatus,
  runExtractionAll, stopExtraction, generateExcel,
  getAIProviders, setAIProvider, getTokenMetrics,
} from '../services/api'
import AnimatedNumber from '../components/AnimatedNumber'

const FALLO_COLORS: Record<string, string> = {
  CONCEDE: '#ef4444',
  NIEGA: '#22c55e',
  IMPROCEDENTE: '#f97316',
  PENDIENTE: '#9ca3af',
  DESFAVORABLE: '#ef4444',
  FAVORABLE: '#22c55e',
  MODIFICADO: '#8b5cf6',
  'SIN FALLO': '#9ca3af',
}

const CHART_PRIMARY = '#1A5276'
const CHART_SECONDARY = '#2E86C1'

/* Gradient definitions for KPI cards */
const KPI_GRADIENTS: Record<string, { from: string; to: string; accent: string }> = {
  tutelas: { from: '#1A5276', to: '#2E86C1', accent: '#1A5276' },
  activos: { from: '#d97706', to: '#fbbf24', accent: '#d97706' },
  inactivos: { from: '#059669', to: '#34d399', accent: '#059669' },
  completitud: { from: '#2E86C1', to: '#5dade2', accent: '#2E86C1' },
  desfavorables: { from: '#dc2626', to: '#f87171', accent: '#dc2626' },
  favorables: { from: '#059669', to: '#34d399', accent: '#059669' },
  impugnaciones: { from: '#ea580c', to: '#fb923c', accent: '#ea580c' },
  desacatos: { from: '#7c3aed', to: '#a78bfa', accent: '#7c3aed' },
}

function KPICard({
  icon: Icon,
  label,
  value,
  gradient,
  sub,
  tooltip,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  gradient: { from: string; to: string; accent: string }
  sub?: string
  tooltip?: string
}) {
  const numericValue = typeof value === 'string' ? parseFloat(value) : value
  const isPercent = typeof value === 'string' && value.includes('%')

  return (
    <div
      className="kpi-card relative overflow-hidden rounded-2xl border border-gray-100 bg-white shadow-md hover:shadow-xl hover:-translate-y-0.5 transition-all duration-300 p-5 group"
      style={{ borderLeft: `4px solid ${gradient.accent}` }}
    >
      <div className="flex items-start gap-4">
        <div
          className="kpi-icon p-3 rounded-xl shadow-md flex-shrink-0"
          style={{ background: `linear-gradient(135deg, ${gradient.from}, ${gradient.to})` }}
        >
          <Icon size={22} className="text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[11px] text-gray-400 font-semibold uppercase tracking-widest">{label}</p>
          {!isNaN(numericValue) ? (
            <AnimatedNumber
              value={numericValue}
              suffix={isPercent ? '%' : ''}
              decimals={isPercent ? 1 : 0}
              className="text-3xl font-extrabold text-gray-800 mt-1 block"
            />
          ) : (
            <p className="text-3xl font-extrabold text-gray-800 mt-1">{value}</p>
          )}
          {sub && <p className="text-[11px] text-gray-400 mt-1.5 truncate">{sub}</p>}
        </div>
      </div>
      {tooltip && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-gray-800 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none w-64 z-50 shadow-lg">
          {tooltip}
          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-800" />
        </div>
      )}
      {/* Decorative gradient blob */}
      <div
        className="absolute -top-6 -right-6 w-24 h-24 rounded-full opacity-[0.04]"
        style={{ background: gradient.accent }}
      />
    </div>
  )
}

function SectionTitle({ title }: { title: string }) {
  return (
    <div className="section-title flex items-center gap-3 mb-5">
      <div className="w-1 h-6 rounded-full bg-gradient-to-b from-[#1A5276] to-[#2E86C1]" />
      <h2 className="text-sm font-bold text-gray-600 uppercase tracking-widest">{title}</h2>
      <div className="flex-1 h-px bg-gradient-to-r from-gray-200 to-transparent" />
    </div>
  )
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="chart-card bg-white rounded-2xl border border-gray-100 shadow-md hover:shadow-lg transition-all duration-300 p-6">
      <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-5 flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-[#2E86C1] flex-shrink-0" />
        {title}
      </h3>
      {children}
    </div>
  )
}

function CustomYAxisTick({ x, y, payload, maxChars = 18 }: { x: number; y: number; payload: { value: string }; maxChars?: number }) {
  const text = payload.value || ''
  const display = text.length > maxChars ? text.slice(0, maxChars) + '...' : text
  return (
    <g transform={`translate(${x},${y})`}>
      <title>{text}</title>
      <text x={-6} y={0} dy={4} textAnchor="end" fontSize={10} fill="#6b7280">
        {display}
      </text>
    </g>
  )
}

function LoadingChart() {
  return (
    <div className="h-52 flex items-center justify-center">
      <div className="w-8 h-8 border-2 border-[#1A5276] border-t-transparent rounded-full animate-spin" />
    </div>
  )
}


export default function Dashboard() {
  const qc = useQueryClient()
  const kpisQ = useQuery({ queryKey: ['kpis'], queryFn: getKPIs })
  const chartsQ = useQuery({ queryKey: ['charts'], queryFn: getCharts })
  const activityQ = useQuery({ queryKey: ['activity'], queryFn: getActivity })
  const monitorQ = useQuery({
    queryKey: ['monitor-status'],
    queryFn: getMonitorStatus,
    refetchInterval: 10000,
  })
  const progressQ = useQuery({
    queryKey: ['extraction-progress'],
    queryFn: getExtractionProgress,
    refetchInterval: 3000,
  })

  const gmailStatusQ = useQuery({
    queryKey: ['gmail-check-status'],
    queryFn: getCheckInboxStatus,
    refetchInterval: 2000,
  })
  const gmailChecking = gmailStatusQ.data?.in_progress ?? false
  const gmailStep = gmailStatusQ.data?.step ?? ''

  const checkInboxMut = useMutation({
    mutationFn: checkInbox,
    onSuccess: (data) => {
      if (data.status === 'started') {
        toast.success('Revision de Gmail iniciada...')
      } else if (data.status === 'running') {
        toast('Ya hay una revision en progreso', { icon: 'ℹ️' })
      }
    },
    onError: () => toast.error('Error al iniciar revision de Gmail'),
  })

  // Detectar cuando Gmail check termina (solo una vez)
  const lastGmailStep = React.useRef('')
  React.useEffect(() => {
    if (!gmailChecking && gmailStep && gmailStep.startsWith('Completado') && lastGmailStep.current !== gmailStep) {
      lastGmailStep.current = gmailStep
      qc.invalidateQueries({ queryKey: ['kpis'] })
      qc.invalidateQueries({ queryKey: ['charts'] })
      qc.invalidateQueries({ queryKey: ['activity'] })
      qc.invalidateQueries({ queryKey: ['token-metrics'] })
    }
  }, [gmailChecking, gmailStep, qc])

  const runAllMut = useMutation({
    mutationFn: runExtractionAll,
    onSuccess: (data) => {
      if (data.status === 'started') toast.success('Extraccion masiva iniciada en background')
      else if (data.status === 'running') toast('Ya hay una extraccion en progreso', { icon: 'ℹ️' })
    },
    onError: () => toast.error('Error al iniciar extraccion'),
  })

  const stopExtractionMut = useMutation({
    mutationFn: stopExtraction,
    onSuccess: (data) => {
      toast.success(data.message)
      qc.invalidateQueries({ queryKey: ['kpis'] })
      qc.invalidateQueries({ queryKey: ['token-metrics'] })
    },
  })

  const excelMut = useMutation({
    mutationFn: generateExcel,
    onSuccess: (data) => {
      toast.success(`Excel generado: ${data.cases_count} casos`)
      // Descargar automáticamente
      const url = `/api/reports/excel/download/${data.filename}`
      window.open(url, '_blank')
    },
    onError: () => toast.error('Error al generar Excel'),
  })

  const aiProvidersQ = useQuery({ queryKey: ['ai-providers'], queryFn: getAIProviders })
  const tokenMetricsQ = useQuery({ queryKey: ['token-metrics'], queryFn: getTokenMetrics, refetchInterval: 15000 })

  const setProviderMut = useMutation({
    mutationFn: ({ provider, model }: { provider: string; model: string }) => setAIProvider(provider, model),
    onSuccess: (data) => {
      if (data.error) { toast.error(data.error); return }
      toast.success(data.message)
      qc.invalidateQueries({ queryKey: ['ai-providers'] })
    },
    onError: () => toast.error('Error al cambiar proveedor'),
  })

  const kpis = kpisQ.data
  const charts = chartsQ.data
  const activity = activityQ.data
  const monitor = monitorQ.data
  const progress = progressQ.data
  const isExtracting = runAllMut.isPending || progress?.in_progress
  const aiProviders = aiProvidersQ.data
  const tokenMetrics = tokenMetricsQ.data

  /* GSAP entrance animations */
  const dashRef = useRef<HTMLDivElement>(null)
  const animatedRef = useRef(false)

  useEffect(() => {
    if (!kpisQ.isLoading && !chartsQ.isLoading && !animatedRef.current && dashRef.current) {
      animatedRef.current = true
      const ctx = gsap.context(() => {
        gsap.from('.kpi-card', { y: 16, duration: 0.4, stagger: 0.06, ease: 'power2.out' })
        gsap.from('.kpi-icon', { scale: 0.7, duration: 0.3, stagger: 0.06, ease: 'back.out(1.7)', delay: 0.1 })
      }, dashRef)
      return () => ctx.revert()
    }
  }, [kpisQ.isLoading, chartsQ.isLoading])

  return (
    <div ref={dashRef} className="p-6 space-y-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-extrabold text-gray-800 tracking-tight">Dashboard</h1>
        <p className="text-sm text-gray-400 mt-1">
          Gobernacion de Santander — Gestion de Tutelas 2026
        </p>
        <div className="w-16 h-1 rounded-full bg-gradient-to-r from-[#1A5276] to-[#2E86C1] mt-3" />
      </div>

      {/* Control Panel */}
      <div>
        <SectionTitle title="Centro de Control" />
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">

          {/* Gmail Monitor — Solo manual */}
          <div className="control-card bg-white rounded-2xl border border-gray-100 shadow-md hover:shadow-lg transition-all duration-300 p-5">
            <div className="flex items-center gap-2 mb-3">
              <Mail size={18} className="text-blue-600" />
              <h3 className="text-sm font-semibold text-gray-700">Revisar Gmail</h3>
            </div>
            <p className="text-xs text-gray-400 mb-2">
              Descarga correos nuevos, adjuntos y extrae datos con IA
              {monitor?.last_check && `. Ultima: ${new Date(monitor.last_check).toLocaleTimeString('es-CO')}`}
            </p>
            {gmailChecking && (
              <div className="mb-2">
                <p className="text-xs text-blue-600 mb-1.5 truncate">{gmailStep}</p>
                {(gmailStatusQ.data?.progress_pct as number) > 0 && (
                  <div className="w-full bg-gray-200 rounded-full h-1.5 mb-1">
                    <div
                      className="bg-blue-600 h-1.5 rounded-full transition-all duration-500"
                      style={{ width: `${gmailStatusQ.data?.progress_pct ?? 0}%` }}
                    />
                  </div>
                )}
                {(gmailStatusQ.data?.elapsed_seconds as number) > 0 && (
                  <p className="text-[10px] text-gray-400">
                    {Math.floor((gmailStatusQ.data?.elapsed_seconds as number) / 60)}:{String((gmailStatusQ.data?.elapsed_seconds as number) % 60).padStart(2, '0')} transcurrido
                  </p>
                )}
              </div>
            )}
            {!gmailChecking && gmailStep && gmailStep.startsWith('Completado') && (
              <p className="text-xs text-green-600 mb-2 truncate">{gmailStep}</p>
            )}
            {!gmailChecking && gmailStep && gmailStatusQ.data?.error && (
              <p className="text-xs text-red-500 mb-2 truncate">{gmailStep}</p>
            )}
            <button
              onClick={() => checkInboxMut.mutate()}
              disabled={gmailChecking}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {gmailChecking ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Mail size={13} />
              )}
              {gmailChecking ? 'Revisando...' : 'Revisar Gmail Ahora'}
            </button>
          </div>

          {/* Extraction Manual - All Pending */}
          <div className="control-card bg-white rounded-2xl border border-gray-100 shadow-md hover:shadow-lg transition-all duration-300 p-5">
            <div className="flex items-center gap-2 mb-3">
              <Cpu size={18} className="text-purple-600" />
              <h3 className="text-sm font-semibold text-gray-700">Extraccion IA</h3>
            </div>
            <p className="text-xs text-gray-400 mb-3">
              Procesar todos los casos pendientes con IA (Groq). Lee documentos y extrae los 28 campos.
            </p>
            {isExtracting && progress?.total > 0 && (
              <div className="mb-2">
                <div className="flex justify-between text-xs text-gray-500 mb-1">
                  <span className="truncate max-w-[140px]">{progress.case_name}</span>
                  <span>{progress.current}/{progress.total} ({progress.success ?? 0} OK, {progress.errors ?? 0} err)</span>
                </div>
                <div className="w-full bg-gray-200 rounded-full h-1.5">
                  <div
                    className="bg-purple-600 h-1.5 rounded-full transition-all"
                    style={{ width: `${(progress.current / progress.total) * 100}%` }}
                  />
                </div>
              </div>
            )}
            {isExtracting ? (
              <button
                onClick={() => stopExtractionMut.mutate()}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-red-600 text-white text-xs font-medium rounded-lg hover:bg-red-700 transition-colors"
              >
                <XCircle size={13} />
                Detener Extraccion
              </button>
            ) : (
              <button
                onClick={() => runAllMut.mutate()}
                disabled={runAllMut.isPending}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-purple-600 text-white text-xs font-medium rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors"
              >
                <Play size={13} />
                Extraer Pendientes
              </button>
            )}
          </div>

          {/* Download Excel */}
          <div className="control-card bg-white rounded-2xl border border-gray-100 shadow-md hover:shadow-lg transition-all duration-300 p-5">
            <div className="flex items-center gap-2 mb-3">
              <Download size={18} className="text-green-600" />
              <h3 className="text-sm font-semibold text-gray-700">Corte Excel</h3>
            </div>
            <p className="text-xs text-gray-400 mb-3">
              Genera y descarga el Excel con el estado actual de todos los casos. Datos en tiempo real.
            </p>
            <button
              onClick={() => excelMut.mutate()}
              disabled={excelMut.isPending}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-green-600 text-white text-xs font-medium rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              {excelMut.isPending ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Download size={13} />
              )}
              {excelMut.isPending ? 'Generando...' : 'Descargar Corte Excel'}
            </button>
          </div>

          {/* Status */}
          <div className="control-card bg-white rounded-2xl border border-gray-100 shadow-md hover:shadow-lg transition-all duration-300 p-5">
            <div className="flex items-center gap-2 mb-3">
              <FileText size={18} className="text-[#1A5276]" />
              <h3 className="text-sm font-semibold text-gray-700">Flujo de Trabajo</h3>
            </div>
            <div className="space-y-2 text-xs text-gray-500">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-blue-500" />
                <span>Gmail: revision manual por operador</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-green-500" />
                <span>IA extrae datos de docs + emails</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-purple-500" />
                <span>Datos se actualizan en tiempo real</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-amber-500" />
                <span>Excel: solo cuando tu lo pidas</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* AI Provider + Token Metrics */}
      <div>
        <SectionTitle title="Proveedor de IA y Consumo de Tokens" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

          {/* Provider Selector */}
          <div className="control-card bg-white rounded-2xl border border-gray-100 shadow-md p-5">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Modelo de IA Activo</h3>
            <div className="space-y-2">
              {(aiProviders?.providers ?? []).map((p: {
                id: string; name: string; configured: boolean;
                models: { id: string; label: string; input_price: number; output_price: number }[]
              }) => (
                <div key={p.id}>
                  <p className="text-xs font-semibold text-gray-500 uppercase mb-1">
                    {p.name} {!p.configured && <span className="text-red-400">(sin API key)</span>}
                  </p>
                  {p.models.map((m) => {
                    const isActive = aiProviders?.active_provider === p.id && aiProviders?.active_model === m.id
                    return (
                      <button
                        key={m.id}
                        onClick={() => setProviderMut.mutate({ provider: p.id, model: m.id })}
                        disabled={!p.configured || setProviderMut.isPending}
                        className={`w-full text-left px-3 py-2 rounded-lg text-xs mb-1 border transition-colors ${
                          isActive
                            ? 'bg-[#1A5276] text-white border-[#1A5276]'
                            : p.configured
                              ? 'bg-gray-50 text-gray-700 border-gray-200 hover:border-[#1A5276] hover:bg-blue-50'
                              : 'bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed'
                        }`}
                      >
                        <div className="flex justify-between items-center">
                          <span className="font-medium">{m.label}</span>
                          {isActive && <span className="text-[10px] bg-white/20 px-1.5 py-0.5 rounded">ACTIVO</span>}
                        </div>
                        <div className="text-[10px] mt-0.5 opacity-75">
                          ${m.input_price}/1M in · ${m.output_price}/1M out
                        </div>
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          </div>

          {/* Token Totals + By Provider */}
          <div className="control-card bg-white rounded-2xl border border-gray-100 shadow-md p-5">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Consumo de Tokens</h3>
            {tokenMetrics?.totals && tokenMetrics.totals.total_calls > 0 ? (
              <div className="space-y-3">
                {/* Totales globales */}
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div className="bg-gray-50 rounded-lg p-2">
                    <p className="text-lg font-bold text-[#1A5276]">
                      {((tokenMetrics.totals.tokens_total || 0) / 1000).toFixed(1)}K
                    </p>
                    <p className="text-[10px] text-gray-500">Tokens Total</p>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-2">
                    <p className="text-lg font-bold text-gray-800">{tokenMetrics.totals.total_calls}</p>
                    <p className="text-[10px] text-gray-500">Llamadas</p>
                  </div>
                  <div className="bg-gray-50 rounded-lg p-2">
                    <p className={`text-lg font-bold ${tokenMetrics.totals.total_cost_usd > 0 ? 'text-amber-600' : 'text-green-600'}`}>
                      ${tokenMetrics.totals.total_cost_usd?.toFixed(4) ?? '0'}
                    </p>
                    <p className="text-[10px] text-gray-500">Costo USD</p>
                  </div>
                </div>

                {/* Desglose por proveedor/modelo */}
                {(tokenMetrics?.by_provider ?? []).length > 0 && (
                  <div>
                    <p className="text-[10px] font-semibold text-gray-400 uppercase mb-2">Por Modelo</p>
                    <div className="space-y-1.5">
                      {(tokenMetrics.by_provider ?? []).map((p: {
                        provider: string; model: string;
                        tokens_input: number; tokens_output: number;
                        calls: number; fields_extracted: number;
                      }, i: number) => (
                        <div key={i} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
                          <div>
                            <span className="text-xs font-medium text-gray-700">{p.provider}</span>
                            <span className="text-[10px] text-gray-400 ml-1">/ {p.model.split('-').slice(-3).join('-')}</span>
                          </div>
                          <div className="flex gap-3 text-[10px] text-gray-500">
                            <span>{((p.tokens_input + p.tokens_output) / 1000).toFixed(1)}K tok</span>
                            <span>{p.calls} calls</span>
                            <span>{p.fields_extracted} campos</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-gray-400 text-center py-4">Sin consumo registrado. Ejecute una extraccion para ver metricas.</p>
            )}
          </div>

          {/* Recent Calls */}
          <div className="control-card bg-white rounded-2xl border border-gray-100 shadow-md p-5">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Historial de Llamadas</h3>
            {(tokenMetrics?.recent_calls ?? []).length === 0 ? (
              <p className="text-xs text-gray-400 text-center py-4">Sin llamadas registradas</p>
            ) : (
              <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {(tokenMetrics?.recent_calls ?? []).filter((c: { error: string | null }) => !c.error).slice(0, 10).map((call: {
                  id: number; provider: string; model: string;
                  tokens_input: number; tokens_output: number;
                  cost_total: string; fields_extracted: number;
                  duration_ms: number; timestamp: string;
                }) => (
                  <div key={call.id} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2 text-xs">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full bg-green-500 flex-shrink-0" />
                      <span className="font-medium text-gray-700">{call.provider}</span>
                      <span className="text-gray-400">
                        {call.timestamp ? new Date(call.timestamp).toLocaleString('es-CO', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''}
                      </span>
                    </div>
                    <div className="flex gap-3 text-[10px] text-gray-500">
                      <span>{call.tokens_input + call.tokens_output} tok</span>
                      <span>{call.fields_extracted} campos</span>
                      <span>{call.duration_ms ? `${(call.duration_ms/1000).toFixed(1)}s` : ''}</span>
                      {parseFloat(call.cost_total || '0') > 0 && (
                        <span className="text-amber-600">${parseFloat(call.cost_total).toFixed(4)}</span>
                      )}
                    </div>
                  </div>
                ))}
                {/* Errores separados al final */}
                {(tokenMetrics?.recent_calls ?? []).filter((c: { error: string | null }) => c.error).length > 0 && (
                  <div className="mt-2 pt-2 border-t border-gray-100">
                    <p className="text-[10px] text-red-400 font-semibold mb-1">Errores recientes</p>
                    {(tokenMetrics.recent_calls ?? []).filter((c: { error: string | null }) => c.error).slice(0, 3).map((call: {
                      id: number; error: string; timestamp: string;
                    }) => (
                      <p key={call.id} className="text-[10px] text-red-400 truncate">
                        {call.timestamp ? new Date(call.timestamp).toLocaleTimeString('es-CO', { hour: '2-digit', minute: '2-digit' }) : ''}: {call.error}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Quality Panel */}
      {kpis?.calidad && (
        <div className="chart-card bg-white rounded-2xl border border-gray-100 shadow-md p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-700">Confiabilidad de Datos</h3>
            <span className={`text-2xl font-bold ${
              (kpis.calidad.confiabilidad ?? 0) >= 80 ? 'text-green-600' :
              (kpis.calidad.confiabilidad ?? 0) >= 60 ? 'text-amber-500' : 'text-red-500'
            }`}>
              {kpis.calidad.confiabilidad ?? 0}%
            </span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="bg-green-50 rounded-lg p-2.5">
              <p className="text-green-600 font-semibold">{kpis.calidad.docs_ok ?? 0}</p>
              <p className="text-green-500">Docs verificados OK</p>
            </div>
            <div className="bg-orange-50 rounded-lg p-2.5">
              <p className="text-orange-600 font-semibold">{kpis.calidad.docs_sospechosos ?? 0}</p>
              <p className="text-orange-500">Docs sospechosos</p>
            </div>
            <div className="bg-blue-50 rounded-lg p-2.5">
              <p className="text-blue-600 font-semibold">{kpis.calidad.extracciones_alta ?? 0}</p>
              <p className="text-blue-500">Extracciones ALTA conf.</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-2.5">
              <p className="text-gray-600 font-semibold">{kpis.calidad.docs_no_verificados ?? 0}</p>
              <p className="text-gray-500">Sin verificar</p>
            </div>
          </div>
        </div>
      )}

      {/* KPI Cards */}
      <div>
        <SectionTitle title="Resumen General" />
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5">
          {kpisQ.isLoading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="bg-white rounded-2xl border border-gray-100 p-5 animate-pulse h-24" />
            ))
          ) : kpisQ.isError ? (
            <div className="col-span-4 flex items-center gap-2 text-red-500 text-sm">
              <AlertCircle size={16} />
              Error al cargar los KPIs
            </div>
          ) : (
            <>
              <KPICard
                icon={FileText}
                label="Tutelas Unicas"
                value={kpis?.tutelas_unicas ?? kpis?.total ?? 0}
                gradient={KPI_GRADIENTS.tutelas}
                sub={`${kpis?.total ?? 0} carpetas total (${kpis?.total_incidentes ?? 0} incidentes)`}
                tooltip="Cuenta solo tutelas base, excluyendo incidentes de desacato que tienen carpeta separada"
              />
              <KPICard
                icon={CheckCircle}
                label="Activos"
                value={kpis?.activos ?? 0}
                gradient={KPI_GRADIENTS.activos}
                sub="En tramite"
                tooltip="Casos con campo ESTADO = ACTIVO. Incluye tutelas e incidentes que aun no han finalizado"
              />
              <KPICard
                icon={XCircle}
                label="Inactivos"
                value={kpis?.inactivos ?? 0}
                gradient={KPI_GRADIENTS.inactivos}
                sub="Finalizados"
                tooltip="Casos con campo ESTADO = INACTIVO. Tutelas con fallo ejecutoriado o proceso terminado"
              />
              <KPICard
                icon={BarChart2}
                label="Completitud"
                value={`${kpis?.completitud ?? 0}%`}
                gradient={KPI_GRADIENTS.completitud}
                sub={`${kpis?.campos_llenos ?? 0} campos completos`}
                tooltip="Porcentaje de campos con datos vs total de campos posibles (36 campos x N casos). Solo incluye casos con mas del 20% de datos"
              />
              <KPICard
                icon={Scale}
                label="Desfavorables"
                value={kpis?.favorabilidad?.desfavorable ?? kpis?.concede ?? 0}
                gradient={KPI_GRADIENTS.desfavorables}
                sub={`${kpis?.favorabilidad?.modificado ?? 0} modificados`}
                tooltip="Fallo definitivo DESFAVORABLE para la Gobernacion. Si hay 2da instancia que REVOCA un CONCEDE, se cuenta como FAVORABLE"
              />
              <KPICard
                icon={Shield}
                label="Favorables"
                value={kpis?.favorabilidad?.favorable ?? kpis?.niega ?? 0}
                gradient={KPI_GRADIENTS.favorables}
                sub={`${kpis?.favorabilidad?.improcedente ?? 0} improcedentes`}
                tooltip="Fallo definitivo FAVORABLE. Incluye: NIEGA + IMPROCEDENTE + REVOCADOS en 2da instancia"
              />
              <KPICard
                icon={TrendingUp}
                label="Impugnaciones"
                value={kpis?.con_impugnacion ?? 0}
                gradient={KPI_GRADIENTS.impugnaciones}
                sub={`${kpis?.impugnaciones_resueltas ?? 0} resueltas, ${kpis?.impugnaciones_pendientes ?? 0} pendientes`}
              />
              <KPICard
                icon={Gavel}
                label="Desacatos"
                value={kpis?.con_incidente ?? 0}
                gradient={KPI_GRADIENTS.desacatos}
                sub={`${kpis?.desacatos?.SANCIONADO ?? 0} sancionados, ${kpis?.desacatos?.PENDIENTE ?? 0} pendientes`}
                tooltip={`Sancionados: ${kpis?.desacatos?.SANCIONADO ?? 0} | En consulta: ${kpis?.desacatos?.['EN CONSULTA'] ?? 0} | En tramite: ${kpis?.desacatos?.['EN TRÁMITE'] ?? 0} | Cumplidos: ${kpis?.desacatos?.CUMPLIDO ?? 0} | Archivados: ${kpis?.desacatos?.ARCHIVADO ?? 0} | Pendientes: ${kpis?.desacatos?.PENDIENTE ?? 0}`}
              />
            </>
          )}
        </div>
        {/* Excluded cases info banner */}
        {kpis?.casos_excluidos && kpis.casos_excluidos.total_excluidos > 0 && (
          <div className="flex items-center gap-2 mt-3 px-1 text-xs text-gray-400 group relative">
            <Info size={13} className="flex-shrink-0" />
            <span>{kpis.casos_excluidos.total_excluidos} casos excluidos del analisis (pendientes revision, sin datos, o completitud &lt;20%)</span>
            <div className="absolute bottom-full left-0 mb-2 px-3 py-2 bg-gray-800 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none w-72 z-50 shadow-lg">
              <p>Pendiente revision: {kpis.casos_excluidos.pendiente_revision}</p>
              <p>Pendiente identificacion: {kpis.casos_excluidos.pendiente_identificacion}</p>
              <p>Sin datos basicos: {kpis.casos_excluidos.sin_datos_basicos}</p>
              <p>Baja completitud (&lt;20%): {kpis.casos_excluidos.baja_completitud}</p>
              <div className="absolute top-full left-4 border-4 border-transparent border-t-gray-800" />
            </div>
          </div>
        )}
      </div>

      {/* Charts Row 1 */}
      <div>
        <SectionTitle title="Distribucion de Casos" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* By Month */}
          <ChartCard title="Casos por Mes">
            {chartsQ.isLoading ? <LoadingChart /> : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={charts?.by_month ?? []} margin={{ top: 0, right: 10, left: -20, bottom: 0 }}>

                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ borderRadius: '10px', fontSize: '12px', border: '1px solid #e5e7eb', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}
                  />
                  <Bar dataKey="count" fill="#1A5276" radius={[6, 6, 0, 0]} name="Casos" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartCard>

          {/* By Favorabilidad Real */}
          <ChartCard title="Favorabilidad Real (con 2da instancia)">
            {chartsQ.isLoading ? <LoadingChart /> : (
              <ResponsiveContainer width="100%" height={260}>
                <PieChart>
                  <Pie
                    data={charts?.by_favorabilidad ?? charts?.by_fallo ?? []}
                    cx="50%"
                    cy="45%"
                    innerRadius={55}
                    outerRadius={90}
                    paddingAngle={3}
                    dataKey="count"
                    nameKey="fallo"
                    label={({ fallo, percent, cx, midAngle, outerRadius: or }) => {
                      const RADIAN = Math.PI / 180
                      const radius = or + 22
                      const x = cx + radius * Math.cos(-midAngle * RADIAN)
                      const y = cx + radius * Math.sin(-midAngle * RADIAN)
                      return (
                        <text x={x} y={y} textAnchor={x > cx ? 'start' : 'end'} dominantBaseline="central" fontSize={10} fill="#4b5563">
                          {fallo} {(percent * 100).toFixed(0)}%
                        </text>
                      )
                    }}
                    labelLine={true}
                  >
                    {(charts?.by_favorabilidad ?? charts?.by_fallo ?? []).map((entry: { fallo: string }) => (
                      <Cell
                        key={entry.fallo}
                        fill={FALLO_COLORS[entry.fallo] ?? '#9ca3af'}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ borderRadius: '10px', fontSize: '12px', border: '1px solid #e5e7eb', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }}
                    formatter={(val: number, name: string) => [val, name]}
                  />
                  <Legend
                    formatter={(value: string) => (
                      <span style={{ fontSize: '11px', color: '#374151' }}>{value}</span>
                    )}
                  />
                </PieChart>
              </ResponsiveContainer>
            )}
          </ChartCard>
        </div>
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* By City */}
        <ChartCard title="Top 10 Ciudades">
          {chartsQ.isLoading ? <LoadingChart /> : (
            <ResponsiveContainer width="100%" height={340}>
              <BarChart
                data={charts?.by_city ?? []}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 5, bottom: 5 }}
              >

                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="ciudad"
                  tick={<CustomYAxisTick maxChars={18} x={0} y={0} payload={{ value: '' }} />}
                  width={140}
                />
                <Tooltip contentStyle={{ borderRadius: '10px', fontSize: '12px', border: '1px solid #e5e7eb', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }} />
                <Bar dataKey="count" fill="#2E86C1" radius={[0, 6, 6, 0]} name="Casos" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        {/* By Lawyer */}
        <ChartCard title="Top 10 Abogados">
          {chartsQ.isLoading ? <LoadingChart /> : (
            <ResponsiveContainer width="100%" height={340}>
              <BarChart
                data={charts?.by_lawyer ?? []}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 5, bottom: 5 }}
              >

                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis
                  type="category"
                  dataKey="abogado"
                  tick={<CustomYAxisTick maxChars={22} x={0} y={0} payload={{ value: '' }} />}
                  width={160}
                />
                <Tooltip contentStyle={{ borderRadius: '10px', fontSize: '12px', border: '1px solid #e5e7eb', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }} />
                <Bar dataKey="count" fill="#1A5276" radius={[0, 6, 6, 0]} name="Casos" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>

      {/* Charts Row 3: Derechos y Oficinas */}
      <div>
        <SectionTitle title="Analisis por Materia" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Derechos Vulnerados */}
          <ChartCard title="Top 10 Derechos Vulnerados">
            {chartsQ.isLoading ? <LoadingChart /> : (
              <ResponsiveContainer width="100%" height={340}>
                <BarChart
                  data={charts?.by_derecho ?? []}
                  layout="vertical"
                  margin={{ top: 5, right: 30, left: 5, bottom: 5 }}
                >

                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="derecho" tick={<CustomYAxisTick maxChars={20} x={0} y={0} payload={{ value: '' }} />} width={150} />
                  <Tooltip contentStyle={{ borderRadius: '10px', fontSize: '12px', border: '1px solid #e5e7eb', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }} />
                  <Bar dataKey="count" fill="#6366f1" radius={[0, 6, 6, 0]} name="Casos" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartCard>

          {/* Fallos Desfavorables por Derecho */}
          <ChartCard title="Fallos Desfavorables por Materia (CONCEDE)">
            {chartsQ.isLoading ? <LoadingChart /> : (
              <ResponsiveContainer width="100%" height={340}>
                <BarChart
                  data={charts?.by_desfavorable ?? []}
                  layout="vertical"
                  margin={{ top: 5, right: 30, left: 5, bottom: 5 }}
                >

                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="derecho" tick={<CustomYAxisTick maxChars={20} x={0} y={0} payload={{ value: '' }} />} width={150} />
                  <Tooltip contentStyle={{ borderRadius: '10px', fontSize: '12px', border: '1px solid #e5e7eb', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }} />
                  <Bar dataKey="count" fill="#ef4444" radius={[0, 6, 6, 0]} name="Fallos desfavorables" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartCard>
        </div>
      </div>

      {/* Charts Row 4: Oficinas */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChartCard title="Casos por Oficina Responsable">
          {chartsQ.isLoading ? <LoadingChart /> : (
            <ResponsiveContainer width="100%" height={340}>
              <BarChart
                data={charts?.by_oficina ?? []}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 5, bottom: 5 }}
              >

                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="oficina" tick={<CustomYAxisTick maxChars={24} x={0} y={0} payload={{ value: '' }} />} width={180} />
                <Tooltip contentStyle={{ borderRadius: '10px', fontSize: '12px', border: '1px solid #e5e7eb', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }} />
                <Bar dataKey="count" fill="#10b981" radius={[0, 6, 6, 0]} name="Casos" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        {/* Desacatos categorizados */}
        <ChartCard title="Estado de Incidentes de Desacato">
          {chartsQ.isLoading ? <LoadingChart /> : (
            <ResponsiveContainer width="100%" height={340}>
              <BarChart
                data={charts?.by_desacato ?? []}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 5, bottom: 5 }}
              >

                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="estado" tick={<CustomYAxisTick maxChars={16} x={0} y={0} payload={{ value: '' }} />} width={120} />
                <Tooltip contentStyle={{ borderRadius: '10px', fontSize: '12px', border: '1px solid #e5e7eb', boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }} />
                <Bar dataKey="count" fill="#8b5cf6" radius={[0, 6, 6, 0]} name="Incidentes" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>

      {/* Recent Activity */}
      <div>
        <SectionTitle title="Actividad Reciente" />
        <div className="bg-white rounded-2xl border border-gray-100 shadow-md overflow-hidden">
          {activityQ.isLoading ? (
            <div className="divide-y divide-gray-100">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex items-center gap-4 px-5 py-3 animate-pulse">
                  <div className="w-8 h-8 rounded-full bg-gray-200 flex-shrink-0" />
                  <div className="flex-1 space-y-1">
                    <div className="h-3 bg-gray-200 rounded w-3/4" />
                    <div className="h-3 bg-gray-200 rounded w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          ) : activityQ.isError ? (
            <div className="flex items-center gap-2 text-red-500 text-sm px-5 py-4">
              <AlertCircle size={16} />
              Error al cargar actividad
            </div>
          ) : !activity?.length ? (
            <div className="text-center py-10 text-gray-400 text-sm">
              Sin actividad reciente
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {activity.map((item: {
                id: number
                type: string
                description: string
                case_folder?: string
                abogado?: string
                ciudad?: string
                created_at: string
              }) => {
                const typeIcon =
                  item.type === 'update' ? <User size={14} /> :
                  item.type === 'extract' ? <BarChart2 size={14} /> :
                  item.type === 'email' ? <MapPin size={14} /> :
                  <Clock size={14} />

                const typeColor =
                  item.type === 'update' ? 'bg-blue-100 text-blue-600' :
                  item.type === 'extract' ? 'bg-purple-100 text-purple-600' :
                  item.type === 'email' ? 'bg-green-100 text-green-600' :
                  'bg-gray-100 text-gray-500'

                return (
                  <div key={item.id} className="activity-item flex items-start gap-4 px-5 py-3 hover:bg-gray-50/80 transition-colors even:bg-gray-50/40">
                    <div className={`mt-0.5 p-1.5 rounded-full flex-shrink-0 ${typeColor}`}>
                      {typeIcon}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-700 truncate">{item.description}</p>
                      <div className="flex items-center gap-3 mt-0.5">
                        {item.case_folder && (
                          <span className="text-xs text-gray-400">{item.case_folder}</span>
                        )}
                        {item.abogado && (
                          <span className="text-xs text-gray-400">- {item.abogado}</span>
                        )}
                      </div>
                    </div>
                    <span className="text-xs text-gray-400 flex-shrink-0 whitespace-nowrap">
                      {new Date(item.created_at).toLocaleDateString('es-CO', {
                        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'
                      })}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Chat IA floating button + panel */}
    </div>
  )
}
