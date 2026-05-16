import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'motion/react'
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis,
  Tooltip as RechartsTooltip, ResponsiveContainer,
} from 'recharts'
import {
  FileText, CheckCircle, XCircle, BarChart2, AlertCircle,
  Scale, Shield, Gavel, TrendingUp, Info, LayoutDashboard,
} from 'lucide-react'
import { getKPIs, getCharts } from '../services/api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'
import DataCard from '../components/DataCard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

const FALLO_COLORS: Record<string, string> = {
  CONCEDE: '#ef4444',
  NIEGA: '#22c55e',
  IMPROCEDENTE: '#f97316',
  PENDIENTE: '#9ca3af',
  DESFAVORABLE: '#ef4444',
  FAVORABLE: '#22c55e',
  MODIFICADO: '#8b5cf6',
  OTRO: '#fbbf24',
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
      <CardHeader className="pb-1">
        <CardTitle className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{title}</CardTitle>
        {subtitle && <p className="text-[10px] text-muted-foreground">{subtitle}</p>}
      </CardHeader>
      <CardContent>
        {children}
      </CardContent>
    </Card>
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

function LoadingChart({ height = 'h-52' }: { height?: string }) {
  return (
    <div className={`${height} flex items-center justify-center text-sm text-muted-foreground animate-pulse`}>
      Cargando…
    </div>
  )
}

// Lista de rangos (barra horizontal en HTML/CSS) — robusta y siempre con etiquetas visibles.
type RankItem = { label: string; count: number }
function RankBars({ data, color, isLoading }: { data: RankItem[]; color: string; isLoading?: boolean }) {
  if (isLoading) return <LoadingChart height="h-40" />
  if (!data?.length) return <div className="h-40 flex items-center justify-center text-sm text-muted-foreground">Sin datos para esta métrica</div>
  const max = Math.max(...data.map((d) => d.count), 1)
  const total = data.reduce((s, d) => s + d.count, 0)
  return (
    <div className="space-y-1.5 py-1">
      {data.map((d, i) => {
        const pct = total > 0 ? Math.round((d.count / total) * 100) : 0
        const w = Math.max(3, Math.round((d.count / max) * 100))
        return (
          <div key={`${d.label}-${i}`} className="flex items-center gap-2 text-xs">
            <span className="w-40 shrink-0 truncate text-right text-muted-foreground" title={d.label}>{d.label}</span>
            <div className="flex-1 h-5 rounded bg-muted/40 overflow-hidden">
              <div className="h-full rounded transition-all" style={{ width: `${w}%`, backgroundColor: color }} />
            </div>
            <span className="w-8 shrink-0 text-right font-semibold tabular-nums text-foreground">{d.count}</span>
            <span className="w-9 shrink-0 text-right text-[10px] tabular-nums text-muted-foreground">{pct}%</span>
          </div>
        )
      })}
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
  const kpisQ = useQuery({ queryKey: ['kpis'], queryFn: getKPIs })
  const chartsQ = useQuery({ queryKey: ['charts'], queryFn: getCharts })

  const kpis = kpisQ.data
  const charts = chartsQ.data
  const chartsLoading = chartsQ.isLoading

  // Adaptadores: el endpoint devuelve {ciudad|abogado|derecho|oficina|estado, count} → {label, count}
  const cityData: RankItem[] = (charts?.by_city ?? []).map((d: any) => ({ label: d.ciudad, count: d.count }))
  const lawyerData: RankItem[] = (charts?.by_lawyer ?? []).map((d: any) => ({ label: d.abogado, count: d.count }))
  const derechoData: RankItem[] = (charts?.by_derecho ?? []).map((d: any) => ({ label: d.derecho, count: d.count }))
  const desfavData: RankItem[] = (charts?.by_desfavorable ?? []).map((d: any) => ({ label: d.derecho, count: d.count }))
  const oficinaData: RankItem[] = (charts?.by_oficina ?? []).map((d: any) => ({ label: d.oficina, count: d.count }))
  const desacatoData: RankItem[] = (charts?.by_desacato ?? []).map((d: any) => ({ label: d.estado, count: d.count }))

  return (
    <PageShell>
      <PageHeader
        title="Panel Principal"
        subtitle="Gobernacion de Santander — Gestion de Tutelas 2026"
        icon={LayoutDashboard}
      />

      {/* Quality Panel — calidad documental del expediente */}
      {kpis?.calidad && (
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium">Calidad del expediente</span>
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
                <p className="text-blue-700 font-semibold">
                  {kpis.calidad.campos_criticos
                    ? `${Object.values(kpis.calidad.campos_criticos as Record<string, number>).reduce((a, b) => a + b, 0)}/${(kpis.total ?? 0) * 5}`
                    : '—'}
                </p>
                <p className="text-blue-600/70">Campos clave extraídos</p>
              </div>
              <div className="bg-muted rounded-lg p-2.5">
                <p className="text-foreground font-semibold">{kpis.calidad.docs_no_verificados ?? 0}</p>
                <p className="text-muted-foreground">Docs sin verificar</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* KPI Cards */}
      <div>
        <SectionTitle title="Resumen del cuadro de tutelas" />
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
                <DataCard icon={FileText} label="Expedientes" value={kpis?.total_carpetas ?? kpis?.total ?? 0} variant="primary" sub={`${kpis?.total ?? 0} con datos para métricas · ${kpis?.total_incidentes ?? 0} incidentes`} />
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
                <DataCard icon={Shield} label="Favorables" value={kpis?.favorabilidad?.favorable ?? kpis?.niega ?? 0} variant="success" sub={`${kpis?.favorabilidad?.improcedente ?? 0} improcedentes, ${kpis?.favorabilidad?.otro ?? 0} otros`} />
              </motion.div>
              <motion.div variants={staggerItem}>
                <DataCard icon={TrendingUp} label="Impugnaciones" value={kpis?.con_impugnacion ?? 0} variant="warning" sub={`${kpis?.impugnaciones_resueltas ?? 0} resueltas, ${kpis?.impugnaciones_pendientes ?? 0} pendientes`} />
              </motion.div>
              <motion.div variants={staggerItem}>
                <DataCard icon={Gavel} label="Desacatos" value={kpis?.con_incidente ?? 0} variant="purple" sub={`${kpis?.desacatos?.SANCIONADO ?? 0} sancionados`} />
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

      {/* Charts Row 1 — temporal + favorabilidad */}
      <div>
        <SectionTitle title="Distribucion de Casos" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <ChartCard title="Tutelas por Mes de Ingreso" subtitle="fecha del auto admisorio">
            {chartsLoading ? <LoadingChart /> : (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={charts?.by_month ?? []} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                  <defs>
                    <linearGradient id="gradMonth" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.9} />
                      <stop offset="100%" stopColor="#1d4ed8" stopOpacity={0.7} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="month" tick={{ fontSize: 10, fill: '#6b7280' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: '#9ca3af' }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <RechartsTooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
                  <Bar dataKey="count" fill="url(#gradMonth)" radius={[6, 6, 0, 0]} name="Tutelas" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </ChartCard>

          <ChartCard title="Favorabilidad Real (con 2da instancia)" subtitle="CONCEDE = desfavorable para la Gobernacion · NIEGA = favorable">
            {chartsLoading ? <LoadingChart /> : (() => {
              const data = charts?.by_favorabilidad ?? charts?.by_fallo ?? []
              const total = data.reduce((s: number, d: any) => s + (d.count || 0), 0)
              return (
                <div className="flex items-center gap-4">
                  <ResponsiveContainer width="48%" height={220}>
                    <PieChart>
                      <Pie
                        data={data}
                        cx="50%"
                        cy="50%"
                        innerRadius={58}
                        outerRadius={84}
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
                      <text x="50%" y="56%" textAnchor="middle" dominantBaseline="central" className="fill-muted-foreground text-[10px]">expedientes</text>
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="flex-1 space-y-1.5">
                    {data.map((entry: { fallo: string; count: number }) => {
                      const pct = total > 0 ? Math.round((entry.count / total) * 100) : 0
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

      {/* Charts Row 2 — geografía y abogados */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ChartCard title="Top 10 Municipios" subtitle="municipio del juzgado que conoce la tutela (lugar de los hechos)">
          <RankBars data={cityData} color="#14b8a6" isLoading={chartsLoading} />
        </ChartCard>
        <ChartCard title="Top 10 Abogados" subtitle="abogado que proyectó la respuesta de la SED (no la jefatura que revisa/aprueba)">
          <RankBars data={lawyerData} color="#3b82f6" isLoading={chartsLoading} />
        </ChartCard>
      </div>

      {/* Charts Row 3 — materia */}
      <div>
        <SectionTitle title="Analisis por Materia" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <ChartCard title="Derechos Fundamentales Invocados" subtitle="conteo por derecho (un caso puede invocar varios)">
            <RankBars data={derechoData} color="#8b5cf6" isLoading={chartsLoading} />
          </ChartCard>
          <ChartCard title="Fallos Desfavorables por Materia" subtitle="derechos en los casos con fallo 1ra = CONCEDE">
            <RankBars data={desfavData} color="#f43f5e" isLoading={chartsLoading} />
          </ChartCard>
        </div>
      </div>

      {/* Charts Row 4 — oficina y desacatos */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ChartCard title="Casos por Oficina Responsable" subtitle="Dirección de la SED dueña del asunto de fondo">
          <RankBars data={oficinaData} color="#10b981" isLoading={chartsLoading} />
        </ChartCard>
        <ChartCard title="Estado de Incidentes de Desacato" subtitle={`${kpis?.con_incidente ?? 0} expedientes con incidente`}>
          <RankBars data={desacatoData} color="#f59e0b" isLoading={chartsLoading} />
        </ChartCard>
      </div>
    </PageShell>
  )
}
