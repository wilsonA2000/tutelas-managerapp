import React, { useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { motion } from 'motion/react'
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis,
  Tooltip as RechartsTooltip, ResponsiveContainer, Legend,
  RadialBarChart, RadialBar,
} from 'recharts'
import {
  FileText, CheckCircle, XCircle, BarChart2,
  Clock, User, MapPin, AlertCircle,
  Play, Loader2, Mail,
  Cpu, Download,
  Scale, Shield, Gavel, TrendingUp, Info,
} from 'lucide-react'
import { useExtractionProgress, useGmailProgress } from '../hooks/useProgressPolling'
import {
  getKPIs, getCharts, getActivity,
  checkInbox, getMonitorStatus,
  runExtractionAll, stopExtraction, generateExcel,
} from '../services/api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'
import DataCard from '../components/DataCard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Progress } from '@/components/ui/progress'
import { LayoutDashboard } from 'lucide-react'

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

function SectionTitle({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-widest">{title}</h2>
      <div className="flex-1 h-px bg-border" />
    </div>
  )
}

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-0">
        <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{title}</CardTitle>
        {subtitle && <p className="text-[10px] text-muted-foreground">{subtitle}</p>}
      </CardHeader>
      <CardContent>
        {children}
      </CardContent>
    </Card>
  )
}

function CustomYAxisTick({ x, y, payload, maxChars = 18 }: { x: number; y: number; payload: { value: string }; maxChars?: number }) {
  const text = payload.value || ''
  const display = text.length > maxChars ? text.slice(0, maxChars) + '...' : text
  return (
    <g transform={`translate(${x},${y})`}>
      <title>{text}</title>
      <text x={-6} y={0} dy={4} textAnchor="end" fontSize={10} fill="#6b7280" fontWeight={500}>
        {display}
      </text>
    </g>
  )
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-popover/95 backdrop-blur-sm border border-border rounded-lg px-3 py-2 shadow-lg">
      {label && <p className="text-[11px] font-medium text-foreground mb-1">{label}</p>}
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center gap-2 text-xs">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: p.color || p.fill }} />
          <span className="text-muted-foreground">{p.name}:</span>
          <span className="font-semibold text-foreground">{p.value}</span>
        </div>
      ))}
    </div>
  )
}

// Gradient colors for horizontal bars
const BAR_GRADIENTS = {
  blue: ['#3b82f6', '#1d4ed8'],
  teal: ['#14b8a6', '#0d9488'],
  violet: ['#8b5cf6', '#6d28d9'],
  rose: ['#f43f5e', '#e11d48'],
  emerald: ['#10b981', '#059669'],
  amber: ['#f59e0b', '#d97706'],
}

function LoadingChart() {
  return (
    <div className="h-52 flex items-center justify-center">
      <Loader2 className="w-6 h-6 animate-spin text-primary" />
    </div>
  )
}

const staggerItem = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0 },
}

const staggerContainer = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05 } },
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
  const progressQ = useExtractionProgress()
  const gmailStatusQ = useGmailProgress()
  const gmailChecking = gmailStatusQ.data?.in_progress ?? false
  const gmailStep = gmailStatusQ.data?.step ?? ''

  const checkInboxMut = useMutation({
    mutationFn: checkInbox,
    onSuccess: (data) => {
      if (data.status === 'started') {
        toast.success('Revision de Gmail iniciada...')
      } else if (data.status === 'running') {
        toast('Ya hay una revision en progreso', { icon: '\u2139\uFE0F' })
      }
    },
    onError: () => toast.error('Error al iniciar revision de Gmail'),
  })

  const lastGmailStep = useRef('')
  useEffect(() => {
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
      else if (data.status === 'running') toast('Ya hay una extraccion en progreso', { icon: '\u2139\uFE0F' })
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
      const url = `/api/reports/excel/download/${data.filename}`
      window.open(url, '_blank')
    },
    onError: () => toast.error('Error al generar Excel'),
  })

  // AI provider/token queries removed in v4.9 (Gemini eliminated)

  const kpis = kpisQ.data
  const charts = chartsQ.data
  const activity = activityQ.data
  const monitor = monitorQ.data
  const progress = progressQ.data
  const isExtracting = runAllMut.isPending || progress?.in_progress

  return (
    <PageShell>
      <PageHeader
        title="Panel Principal"
        subtitle="Gobernacion de Santander — Gestion de Tutelas 2026"
        icon={LayoutDashboard}
      />

      {/* Control Panel */}
      <div>
        <SectionTitle title="Centro de Control" />
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
          {/* Gmail */}
          <Card>
            <CardContent className="pt-4 space-y-3">
              <div className="flex items-center gap-2">
                <Mail size={16} className="text-blue-600" />
                <span className="text-sm font-medium">Revisar Gmail</span>
              </div>
              <p className="text-xs text-muted-foreground">
                Descarga correos nuevos, adjuntos y extrae datos
                {monitor?.last_check && `. Ultima: ${new Date(monitor.last_check).toLocaleTimeString('es-CO')}`}
              </p>
              {gmailChecking && (
                <div className="space-y-1.5">
                  <p className="text-xs text-blue-600 truncate">{gmailStep}</p>
                  {(gmailStatusQ.data?.progress_pct as number) > 0 && (
                    <Progress value={gmailStatusQ.data?.progress_pct as number} className="h-1.5" />
                  )}
                  {(gmailStatusQ.data?.elapsed_seconds as number) > 0 && (
                    <p className="text-[10px] text-muted-foreground">
                      {Math.floor((gmailStatusQ.data?.elapsed_seconds as number) / 60)}:{String((gmailStatusQ.data?.elapsed_seconds as number) % 60).padStart(2, '0')} transcurrido
                    </p>
                  )}
                </div>
              )}
              {!gmailChecking && gmailStep && gmailStep.startsWith('Completado') && (
                <p className="text-xs text-emerald-600 truncate">{gmailStep}</p>
              )}
              {!gmailChecking && gmailStep && gmailStatusQ.data?.error && (
                <p className="text-xs text-destructive truncate">{gmailStep}</p>
              )}
              <Button
                onClick={() => checkInboxMut.mutate()}
                disabled={gmailChecking}
                size="sm"
                className="w-full bg-blue-600 hover:bg-blue-700"
              >
                {gmailChecking ? <Loader2 size={13} className="animate-spin" /> : <Mail size={13} />}
                {gmailChecking ? 'Revisando...' : 'Revisar Gmail Ahora'}
              </Button>
            </CardContent>
          </Card>

          {/* Extraction */}
          <Card>
            <CardContent className="pt-4 space-y-3">
              <div className="flex items-center gap-2">
                <Cpu size={16} className="text-primary" />
                <span className="text-sm font-medium">Extraccion IA</span>
              </div>
              <p className="text-xs text-muted-foreground">
                Procesar todos los casos pendientes con IA. Lee documentos y extrae los 28 campos.
              </p>
              {isExtracting && progress?.total > 0 && (
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span className="truncate max-w-[140px]">{progress.case_name}</span>
                    <span>{progress.current}/{progress.total} ({progress.success ?? 0} OK, {progress.errors ?? 0} err)</span>
                  </div>
                  <Progress value={(progress.current / progress.total) * 100} className="h-1.5" />
                </div>
              )}
              {isExtracting ? (
                <Button
                  onClick={() => stopExtractionMut.mutate()}
                  variant="destructive"
                  size="sm"
                  className="w-full"
                >
                  <XCircle size={13} />
                  Detener Extraccion
                </Button>
              ) : (
                <Button
                  onClick={() => runAllMut.mutate()}
                  disabled={runAllMut.isPending}
                  size="sm"
                  className="w-full"
                >
                  <Play size={13} />
                  Extraer Pendientes
                </Button>
              )}
            </CardContent>
          </Card>

          {/* Excel */}
          <Card>
            <CardContent className="pt-4 space-y-3">
              <div className="flex items-center gap-2">
                <Download size={16} className="text-emerald-600" />
                <span className="text-sm font-medium">Corte Excel</span>
              </div>
              <p className="text-xs text-muted-foreground">
                Genera y descarga el Excel con el estado actual de todos los casos.
              </p>
              <Button
                onClick={() => excelMut.mutate()}
                disabled={excelMut.isPending}
                size="sm"
                className="w-full bg-emerald-600 hover:bg-emerald-700"
              >
                {excelMut.isPending ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                {excelMut.isPending ? 'Generando...' : 'Descargar Corte Excel'}
              </Button>
            </CardContent>
          </Card>

          {/* Workflow */}
          <Card>
            <CardContent className="pt-4 space-y-3">
              <div className="flex items-center gap-2">
                <FileText size={16} className="text-primary" />
                <span className="text-sm font-medium">Flujo de Trabajo</span>
              </div>
              <div className="space-y-2 text-xs text-muted-foreground">
                <div className="flex items-center gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-blue-500" />
                  <span>Gmail: revision manual por operador</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  <span>IA extrae datos de docs + emails</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-violet-500" />
                  <span>Datos se actualizan en tiempo real</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                  <span>Excel: solo cuando tu lo pidas</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Quality Panel */}
      {kpis?.calidad && (
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium">Confiabilidad de Datos</span>
              <span className={`text-xl font-bold ${
                (kpis.calidad.confiabilidad ?? 0) >= 80 ? 'text-emerald-600' :
                (kpis.calidad.confiabilidad ?? 0) >= 60 ? 'text-amber-500' : 'text-destructive'
              }`}>
                {kpis.calidad.confiabilidad ?? 0}%
              </span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
              <div className="bg-emerald-50 rounded-lg p-2.5">
                <p className="text-emerald-700 font-semibold">{kpis.calidad.docs_ok ?? 0}</p>
                <p className="text-emerald-600/70">Docs verificados OK</p>
              </div>
              <div className="bg-orange-50 rounded-lg p-2.5">
                <p className="text-orange-700 font-semibold">{kpis.calidad.docs_sospechosos ?? 0}</p>
                <p className="text-orange-600/70">Docs sospechosos</p>
              </div>
              <div className="bg-blue-50 rounded-lg p-2.5">
                <p className="text-blue-700 font-semibold">{kpis.calidad.extracciones_alta ?? 0}</p>
                <p className="text-blue-600/70">Extracciones ALTA conf.</p>
              </div>
              <div className="bg-muted rounded-lg p-2.5">
                <p className="text-foreground font-semibold">{kpis.calidad.docs_no_verificados ?? 0}</p>
                <p className="text-muted-foreground">Sin verificar</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* KPI Cards */}
      <div>
        <SectionTitle title="Resumen General" />
        <motion.div
          variants={staggerContainer}
          initial="hidden"
          animate="show"
          className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3"
        >
          {kpisQ.isLoading ? (
            Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-24 rounded-lg" />
            ))
          ) : kpisQ.isError ? (
            <div className="col-span-4 flex items-center gap-2 text-destructive text-sm">
              <AlertCircle size={16} />
              Error al cargar los KPIs
            </div>
          ) : (
            <>
              <motion.div variants={staggerItem}>
                <DataCard icon={FileText} label="Tutelas Unicas" value={kpis?.tutelas_unicas ?? kpis?.total ?? 0} variant="primary" sub={`${kpis?.total ?? 0} carpetas total (${kpis?.total_incidentes ?? 0} incidentes)`} />
              </motion.div>
              <motion.div variants={staggerItem}>
                <DataCard icon={CheckCircle} label="Activos" value={kpis?.activos ?? 0} variant="warning" sub="En tramite" />
              </motion.div>
              <motion.div variants={staggerItem}>
                <DataCard icon={XCircle} label="Inactivos" value={kpis?.inactivos ?? 0} variant="success" sub="Finalizados" />
              </motion.div>
              <motion.div variants={staggerItem}>
                <DataCard icon={BarChart2} label="Completitud" value={kpis?.completitud ?? 0} variant="info" suffix="%" decimals={1} sub={`${kpis?.campos_llenos ?? 0} campos completos`} />
              </motion.div>
              <motion.div variants={staggerItem}>
                <DataCard icon={Scale} label="Desfavorables" value={kpis?.favorabilidad?.desfavorable ?? kpis?.concede ?? 0} variant="danger" sub={`${kpis?.favorabilidad?.modificado ?? 0} modificados`} />
              </motion.div>
              <motion.div variants={staggerItem}>
                <DataCard icon={Shield} label="Favorables" value={kpis?.favorabilidad?.favorable ?? kpis?.niega ?? 0} variant="success" sub={`${kpis?.favorabilidad?.improcedente ?? 0} improcedentes`} />
              </motion.div>
              <motion.div variants={staggerItem}>
                <DataCard icon={TrendingUp} label="Impugnaciones" value={kpis?.con_impugnacion ?? 0} variant="warning" sub={`${kpis?.impugnaciones_resueltas ?? 0} resueltas, ${kpis?.impugnaciones_pendientes ?? 0} pendientes`} />
              </motion.div>
              <motion.div variants={staggerItem}>
                <DataCard icon={Gavel} label="Desacatos" value={kpis?.con_incidente ?? 0} variant="purple" sub={`${kpis?.desacatos?.SANCIONADO ?? 0} sancionados, ${kpis?.desacatos?.PENDIENTE ?? 0} pendientes`} />
              </motion.div>
            </>
          )}
        </motion.div>
        {kpis?.casos_excluidos && kpis.casos_excluidos.total_excluidos > 0 && (
          <p className="flex items-center gap-1.5 mt-2 text-xs text-muted-foreground">
            <Info size={12} />
            {kpis.casos_excluidos.total_excluidos} casos excluidos del analisis (pendientes revision, sin datos, o completitud &lt;20%)
          </p>
        )}
      </div>

      {/* Charts Row 1 */}
      <div>
        <SectionTitle title="Distribucion de Casos" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <ChartCard title="Casos por Mes">
            {chartsQ.isLoading ? <LoadingChart /> : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={charts?.by_month ?? []} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gradMonth" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.9} />
                      <stop offset="100%" stopColor="#1d4ed8" stopOpacity={0.7} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="month" tick={{ fontSize: 10, fill: '#6b7280' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
                  <RechartsTooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
                  <Bar dataKey="count" fill="url(#gradMonth)" radius={[6, 6, 0, 0]} name="Casos" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartCard>

          <ChartCard title="Favorabilidad Real (con 2da instancia)" subtitle="CONCEDE = Desfavorable para la Gobernacion | NIEGA = Favorable">
            {chartsQ.isLoading ? <LoadingChart /> : (() => {
              const data = charts?.by_favorabilidad ?? charts?.by_fallo ?? []
              const total = data.reduce((s: number, d: any) => s + (d.count || 0), 0)
              return (
                <div className="flex items-center gap-4">
                  <ResponsiveContainer width="55%" height={220}>
                    <PieChart>
                      <Pie
                        data={data}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={85}
                        paddingAngle={4}
                        dataKey="count"
                        nameKey="fallo"
                        strokeWidth={2}
                        stroke="var(--card)"
                      >
                        {data.map((entry: { fallo: string }) => (
                          <Cell key={entry.fallo} fill={FALLO_COLORS[entry.fallo] ?? '#9ca3af'} />
                        ))}
                      </Pie>
                      <RechartsTooltip content={<CustomTooltip />} />
                      <text x="50%" y="46%" textAnchor="middle" dominantBaseline="central" className="fill-foreground text-2xl font-bold">{total}</text>
                      <text x="50%" y="56%" textAnchor="middle" dominantBaseline="central" className="fill-muted-foreground text-[10px]">total fallos</text>
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="flex-1 space-y-2">
                    {data.map((entry: { fallo: string; count: number }) => {
                      const pct = total > 0 ? Math.round(entry.count / total * 100) : 0
                      return (
                        <div key={entry.fallo} className="flex items-center gap-2">
                          <div className="w-2.5 h-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: FALLO_COLORS[entry.fallo] ?? '#9ca3af' }} />
                          <span className="text-[11px] text-muted-foreground flex-1 truncate">{entry.fallo}</span>
                          <span className="text-xs font-semibold text-foreground tabular-nums">{entry.count}</span>
                          <span className="text-[10px] text-muted-foreground tabular-nums w-8 text-right">{pct}%</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })()}
          </ChartCard>
        </div>
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ChartCard title="Top 10 Ciudades">
          {chartsQ.isLoading ? <LoadingChart /> : (
            <ResponsiveContainer width="100%" height={380}>
              <BarChart data={charts?.by_city ?? []} layout="vertical" margin={{ top: 5, right: 30, left: 5, bottom: 5 }}>
                <defs>
                  <linearGradient id="gradCity" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#14b8a6" stopOpacity={0.8} />
                    <stop offset="100%" stopColor="#0d9488" stopOpacity={1} />
                  </linearGradient>
                </defs>
                <XAxis type="number" tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="ciudad" tick={<CustomYAxisTick maxChars={18} x={0} y={0} payload={{ value: '' }} />} width={140} axisLine={false} tickLine={false} />
                <RechartsTooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.03)' }} />
                <Bar dataKey="count" fill="url(#gradCity)" radius={[0, 6, 6, 0]} name="Casos" barSize={20} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Top 10 Abogados">
          {chartsQ.isLoading ? <LoadingChart /> : (
            <ResponsiveContainer width="100%" height={380}>
              <BarChart data={charts?.by_lawyer ?? []} layout="vertical" margin={{ top: 5, right: 30, left: 5, bottom: 5 }}>
                <defs>
                  <linearGradient id="gradLawyer" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.8} />
                    <stop offset="100%" stopColor="#1d4ed8" stopOpacity={1} />
                  </linearGradient>
                </defs>
                <XAxis type="number" tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="abogado" tick={<CustomYAxisTick maxChars={22} x={0} y={0} payload={{ value: '' }} />} width={160} axisLine={false} tickLine={false} />
                <RechartsTooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.03)' }} />
                <Bar dataKey="count" fill="url(#gradLawyer)" radius={[0, 6, 6, 0]} name="Casos" barSize={20} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>

      {/* Charts Row 3 */}
      <div>
        <SectionTitle title="Analisis por Materia" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <ChartCard title="Top 10 Derechos Vulnerados">
            {chartsQ.isLoading ? <LoadingChart /> : (
              <ResponsiveContainer width="100%" height={380}>
                <BarChart data={charts?.by_derecho ?? []} layout="vertical" margin={{ top: 5, right: 30, left: 5, bottom: 5 }}>
                  <defs>
                    <linearGradient id="gradDerecho" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.8} />
                      <stop offset="100%" stopColor="#6d28d9" stopOpacity={1} />
                    </linearGradient>
                  </defs>
                  <XAxis type="number" tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="derecho" tick={<CustomYAxisTick maxChars={20} x={0} y={0} payload={{ value: '' }} />} width={150} axisLine={false} tickLine={false} />
                  <RechartsTooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.03)' }} />
                  <Bar dataKey="count" fill="url(#gradDerecho)" radius={[0, 6, 6, 0]} name="Casos" barSize={20} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartCard>

          <ChartCard title="Fallos Desfavorables por Materia (CONCEDE)">
            {chartsQ.isLoading ? <LoadingChart /> : (
              <ResponsiveContainer width="100%" height={380}>
                <BarChart data={charts?.by_desfavorable ?? []} layout="vertical" margin={{ top: 5, right: 30, left: 5, bottom: 5 }}>
                  <defs>
                    <linearGradient id="gradDesf" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#f43f5e" stopOpacity={0.8} />
                      <stop offset="100%" stopColor="#e11d48" stopOpacity={1} />
                    </linearGradient>
                  </defs>
                  <XAxis type="number" tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="derecho" tick={<CustomYAxisTick maxChars={20} x={0} y={0} payload={{ value: '' }} />} width={150} axisLine={false} tickLine={false} />
                  <RechartsTooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.03)' }} />
                  <Bar dataKey="count" fill="url(#gradDesf)" radius={[0, 6, 6, 0]} name="Desfavorables" barSize={20} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartCard>
        </div>
      </div>

      {/* Charts Row 4 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ChartCard title="Casos por Oficina Responsable">
          {chartsQ.isLoading ? <LoadingChart /> : (
            <ResponsiveContainer width="100%" height={380}>
              <BarChart data={charts?.by_oficina ?? []} layout="vertical" margin={{ top: 5, right: 30, left: 5, bottom: 5 }}>
                <defs>
                  <linearGradient id="gradOficina" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#10b981" stopOpacity={0.8} />
                    <stop offset="100%" stopColor="#059669" stopOpacity={1} />
                  </linearGradient>
                </defs>
                <XAxis type="number" tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="oficina" tick={<CustomYAxisTick maxChars={24} x={0} y={0} payload={{ value: '' }} />} width={180} axisLine={false} tickLine={false} />
                <RechartsTooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.03)' }} />
                <Bar dataKey="count" fill="url(#gradOficina)" radius={[0, 6, 6, 0]} name="Casos" barSize={20} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>

        <ChartCard title="Estado de Incidentes de Desacato">
          {chartsQ.isLoading ? <LoadingChart /> : (
            <ResponsiveContainer width="100%" height={380}>
              <BarChart data={charts?.by_desacato ?? []} layout="vertical" margin={{ top: 5, right: 30, left: 5, bottom: 5 }}>
                <defs>
                  <linearGradient id="gradDesacato" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.8} />
                    <stop offset="100%" stopColor="#d97706" stopOpacity={1} />
                  </linearGradient>
                </defs>
                <XAxis type="number" tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} />
                <YAxis type="category" dataKey="estado" tick={<CustomYAxisTick maxChars={16} x={0} y={0} payload={{ value: '' }} />} width={120} axisLine={false} tickLine={false} />
                <RechartsTooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.03)' }} />
                <Bar dataKey="count" fill="url(#gradDesacato)" radius={[0, 6, 6, 0]} name="Incidentes" barSize={20} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>

      {/* Recent Activity */}
      <div>
        <SectionTitle title="Actividad Reciente" />
        <Card>
          <CardContent className="p-0">
            {activityQ.isLoading ? (
              <div className="divide-y divide-border">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-4 px-4 py-3">
                    <Skeleton className="w-8 h-8 rounded-full" />
                    <div className="flex-1 space-y-1.5">
                      <Skeleton className="h-3 w-3/4" />
                      <Skeleton className="h-3 w-1/2" />
                    </div>
                  </div>
                ))}
              </div>
            ) : activityQ.isError ? (
              <div className="flex items-center gap-2 text-destructive text-sm px-4 py-4">
                <AlertCircle size={16} />
                Error al cargar actividad
              </div>
            ) : !activity?.length ? (
              <div className="text-center py-10 text-muted-foreground text-sm">
                Sin actividad reciente
              </div>
            ) : (
              <div className="divide-y divide-border">
                {activity.slice(0, 15).map((item: {
                  id: number; type: string; description: string;
                  case_folder?: string; abogado?: string; ciudad?: string; created_at: string
                }) => {
                  const typeIcon =
                    item.type === 'update' ? <User size={14} /> :
                    item.type === 'extract' ? <BarChart2 size={14} /> :
                    item.type === 'email' ? <MapPin size={14} /> :
                    <Clock size={14} />

                  const typeColor =
                    item.type === 'update' ? 'bg-blue-100 text-blue-600' :
                    item.type === 'extract' ? 'bg-violet-100 text-violet-600' :
                    item.type === 'email' ? 'bg-emerald-100 text-emerald-600' :
                    'bg-muted text-muted-foreground'

                  const mainText = item.case_folder || item.description
                  const subText = item.case_folder ? item.description : ''

                  return (
                    <div key={item.id} className="flex items-start gap-3 px-4 py-3 hover:bg-muted/50 transition-colors">
                      <div className={`mt-0.5 p-1.5 rounded-full flex-shrink-0 ${typeColor}`}>
                        {typeIcon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-foreground truncate">{mainText}</p>
                        {subText && <p className="text-xs text-muted-foreground truncate mt-0.5">{subText}</p>}
                      </div>
                      <span className="text-xs text-muted-foreground flex-shrink-0 whitespace-nowrap">
                        {new Date(item.created_at).toLocaleDateString('es-CO', {
                          day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'
                        })}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </PageShell>
  )
}
