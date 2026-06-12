/**
 * Executive Dashboard — Propuesta 9.9 de la tesis v6.0.
 *
 * KPIs consolidados para el Secretario de Educación y jefe de oficina jurídica.
 * Consume GET /api/dashboard/executive.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip,
  ResponsiveContainer, PieChart, Pie, Cell, CartesianGrid,
} from 'recharts'
import {
  AlertTriangle, Scale, Clock, CheckCircle2,
  MapPin, Building2, UserCircle2, TrendingUp,
  RefreshCw, Briefcase, Flame,
} from 'lucide-react'
import api from '@/services/api'
import PageHeader from '@/components/PageHeader'
import PageShell from '@/components/PageShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const FALLO_COLORS: Record<string, string> = {
  CONCEDE: '#ef4444',
  NIEGA: '#22c55e',
  IMPROCEDENTE: '#f97316',
  MODIFICA: '#8b5cf6',
  OTRO: '#6b7280',
}

interface Executive {
  generated_at: string
  summary: {
    total_cases: number
    pct_resueltas: number
    casos_criticos_rojos: number
    casos_vigilancia_amarillos: number
    casos_en_sancion: number
    casos_con_incidente_activo: number
  }
  estado_procesal: { activos: number; inactivos: number; sin_estado: number; total: number; pct_resueltas: number }
  response_times: {
    avg_days: number | null
    median_days: number | null
    p75_days: number | null
    sample_size: number
    sin_respuesta_total: number
    sin_respuesta_con_fallo: number
  }
  impugnacion: Record<string, number>
  fallos_distribution: Array<{ sentido: string; count: number; pct: number }>
  fallos_2nd_distribution?: Array<{ sentido: string; count: number; pct: number }>
  pipeline_funnel?: Array<{ stage: string; label: string; count: number; pct_total: number }>
  compliance_plazos?: {
    concedidas_pendientes_cumplimiento: number
    concedidas_cerradas: number
    en_sancion: number
    top_pendientes: Array<{ case_id: number; folder_name: string; dias_desde_fallo: number; fecha_fallo: string; abogado: string }>
  }
  by_month: Array<{ month: string; count: number }>
  incidentes_decision: Record<string, number>
  top_municipios: Array<{ municipio: string; count: number }>
  top_oficinas: Array<{ oficina: string; count: number }>
  top_abogados: Array<{ abogado: string; total_casos: number; casos_activos_incidente: number }>
  top_accionantes_recurrentes: Array<{ accionante: string; procesos: number }>
}

function KPICard({ icon: Icon, label, value, sublabel, color = 'text-primary', link }: any) {
  const inner = (
    <div className="p-5 bg-card rounded-xl border hover:shadow-md transition-shadow h-full">
      <div className="flex items-center gap-2 text-muted-foreground text-xs uppercase tracking-wide mb-2">
        <Icon size={14} />
        {label}
      </div>
      <div className={`text-3xl font-bold ${color}`}>{value}</div>
      {sublabel && <div className="text-xs text-muted-foreground mt-1">{sublabel}</div>}
    </div>
  )
  return link ? <Link to={link} className="block">{inner}</Link> : inner
}

function Section({ title, children }: any) {
  return (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">{title}</h3>
      {children}
    </div>
  )
}

export default function ExecutiveDashboard() {
  const [data, setData] = useState<Executive | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true); setError(null)
    try {
      const res = await api.get('/dashboard/executive')
      setData(res.data)
    } catch (e: any) {
      setError(e?.message || 'Error cargando dashboard')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  if (loading || !data) {
    return (
      <PageShell>
        <PageHeader title="Dashboard Ejecutivo" subtitle="Cargando KPIs..." />
      </PageShell>
    )
  }

  const resueltasPct = Math.round(data.summary.pct_resueltas * 100)
  const rojos = data.summary.casos_criticos_rojos
  const sancion = data.summary.casos_en_sancion
  const activos = data.summary.casos_con_incidente_activo

  return (
    <PageShell>
      <PageHeader
        title="Dashboard Ejecutivo"
        subtitle={`KPIs consolidados · Gobernación de Santander · ${data.summary.total_cases} casos (${data.estado_procesal.activos} activos)`}
        action={
          <Button onClick={load} variant="outline" size="sm" disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Actualizar
          </Button>
        }
      />

      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/40 rounded-lg text-red-600 dark:text-red-400">{error}</div>
      )}

      {/* Fila superior: KPIs grandes */}
      <Section title="Indicadores clave">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <KPICard
            icon={Flame} label="Críticos (ROJO)" value={rojos}
            sublabel="Intervención inmediata" color="text-red-600 dark:text-red-400"
            link="/alertas"
          />
          <KPICard
            icon={AlertTriangle} label="En sanción" value={sancion}
            sublabel="Desacato con auto de sanción" color="text-red-600 dark:text-red-400"
          />
          <KPICard
            icon={Briefcase} label="Incidentes activos" value={activos}
            sublabel="Requieren seguimiento" color="text-orange-500"
          />
          <KPICard
            icon={CheckCircle2} label="Resueltas" value={`${resueltasPct}%`}
            sublabel={`${data.estado_procesal.inactivos}/${data.estado_procesal.total} cerradas (INACTIVO)`}
            color="text-green-600 dark:text-green-400"
          />
        </div>
      </Section>

      {/* Tendencia mensual + distribución fallos */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <TrendingUp size={16} /> Casos por mes de ingreso
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={data.by_month}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                <XAxis dataKey="month" tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <RechartsTooltip />
                <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Scale size={16} /> Distribución de fallos 1ra instancia
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={data.fallos_distribution}
                  dataKey="count"
                  nameKey="sentido"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={2}
                  label={(e: any) => `${e.sentido}: ${e.pct}%`}
                >
                  {data.fallos_distribution.map((f) => (
                    <Cell key={f.sentido} fill={FALLO_COLORS[f.sentido] || '#9ca3af'} />
                  ))}
                </Pie>
                <RechartsTooltip />
              </PieChart>
            </ResponsiveContainer>
            <p className="text-xs text-muted-foreground mt-2 text-center">
              {data.fallos_distribution.find(f => f.sentido === 'CONCEDE')?.pct ?? 0}% concedidos (desfavorables para la Gobernación)
            </p>
          </CardContent>
        </Card>
      </div>

      {/* v8.3: Pipeline ejecutivo + Fallos 2nd + Plazos cumplimiento */}
      {data.pipeline_funnel && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Scale size={16} /> Pipeline ejecutivo
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {data.pipeline_funnel.map((s) => (
                <div key={s.stage} className="text-xs">
                  <div className="flex justify-between mb-0.5">
                    <span className="text-muted-foreground">{s.label}</span>
                    <span className="font-semibold">{s.count} <span className="text-muted-foreground">({s.pct_total}%)</span></span>
                  </div>
                  <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
                    <div className="h-full bg-primary" style={{ width: `${s.pct_total}%` }} />
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          {data.fallos_2nd_distribution && data.fallos_2nd_distribution.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Scale size={16} /> Fallos 2da instancia
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm space-y-1">
                {data.fallos_2nd_distribution.map((f) => (
                  <div key={f.sentido} className="flex justify-between">
                    <span className="text-muted-foreground">{f.sentido}:</span>
                    <span className="font-semibold">{f.count} <span className="text-xs text-muted-foreground">({f.pct}%)</span></span>
                  </div>
                ))}
                <p className="text-xs text-muted-foreground mt-2 border-t pt-1">
                  CONFIRMA = mantienen fallo de 1ra. REVOCA = lo tumban.
                </p>
              </CardContent>
            </Card>
          )}

          {data.compliance_plazos && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Clock size={16} /> Cumplimiento de fallos
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm space-y-1">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Cerradas (INACTIVO):</span>
                  <span className="font-semibold text-green-600">{data.compliance_plazos.concedidas_cerradas}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Pendientes (&gt;10d):</span>
                  <span className="font-semibold text-amber-600">{data.compliance_plazos.concedidas_pendientes_cumplimiento}</span>
                </div>
                <div className="flex justify-between border-t pt-1 mt-2">
                  <span className="text-muted-foreground">En sanción:</span>
                  <span className="font-semibold text-red-600">{data.compliance_plazos.en_sancion}</span>
                </div>
                {data.compliance_plazos.top_pendientes.length > 0 && (
                  <div className="border-t pt-1 mt-2 space-y-0.5">
                    <p className="text-xs font-semibold text-muted-foreground">Más antiguos:</p>
                    {data.compliance_plazos.top_pendientes.slice(0, 4).map((p) => (
                      <div key={p.case_id} className="text-xs text-muted-foreground truncate" title={p.folder_name}>
                        <Link to={`/cases/${p.case_id}`} className="hover:text-primary">
                          #{p.case_id} · {p.dias_desde_fallo}d · {p.abogado || 'sin abogado'}
                        </Link>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Métricas operativas */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2"><Clock size={16} />Tiempo de respuesta</CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-1">
            <div className="flex justify-between"><span className="text-muted-foreground">Promedio:</span><span className="font-semibold">{data.response_times.avg_days ?? '—'} días</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Mediana:</span><span className="font-semibold">{data.response_times.median_days ?? '—'} días</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">p75:</span><span className="font-semibold">{data.response_times.p75_days ?? '—'} días</span></div>
            <div className="flex justify-between border-t pt-1 mt-2"><span className="text-muted-foreground">Sin respuesta:</span><span className="font-semibold text-orange-500">{data.response_times.sin_respuesta_total}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Sin respuesta con fallo:</span><span className="font-semibold text-red-500">{data.response_times.sin_respuesta_con_fallo}</span></div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2"><Scale size={16} />Impugnaciones</CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-1">
            <div className="flex justify-between"><span className="text-muted-foreground">Total con fallo:</span><span className="font-semibold">{data.impugnacion.total_con_fallo}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Impugnadas:</span><span className="font-semibold">{data.impugnacion.total_impugnadas}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Tasa impugnación:</span><span className="font-semibold">{Math.round(data.impugnacion.impugnacion_rate * 100)}%</span></div>
            <div className="flex justify-between border-t pt-1 mt-2"><span className="text-muted-foreground">Concedidas:</span><span className="font-semibold">{data.impugnacion.concedidas}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Concedidas impugnadas:</span><span className="font-semibold">{data.impugnacion.concedidas_impugnadas}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Tasa imp. s/ concedidas:</span><span className="font-semibold">{Math.round(data.impugnacion.rate_impugnacion_sobre_concedidas * 100)}%</span></div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2"><Briefcase size={16} />Incidentes de desacato</CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-1">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Estado procesal:</span>
              <span className="font-semibold">{data.estado_procesal.activos} activos · {data.estado_procesal.inactivos} inactivos</span>
            </div>
            <div className="border-t pt-1 mt-2 text-xs text-muted-foreground">Incidentes por decisión:</div>
            {Object.entries(data.incidentes_decision).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="text-muted-foreground">{k}:</span>
                <span className={`font-semibold ${k === 'SANCIONA' ? 'text-red-600' : k === 'EN_TRAMITE' ? 'text-orange-500' : ''}`}>{v}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Rankings */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2"><UserCircle2 size={16} />Abogados con más carga</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              {data.top_abogados.map((a) => (
                <div key={a.abogado} className="flex items-center justify-between text-sm p-2 rounded hover:bg-muted">
                  <span className="truncate">{a.abogado}</span>
                  <span className="shrink-0 ml-2 flex items-center gap-2">
                    <span className="font-semibold">{a.total_casos}</span>
                    {a.casos_activos_incidente > 0 && (
                      <span className="text-xs px-2 py-0.5 bg-red-500/10 text-red-600 rounded">
                        {a.casos_activos_incidente} incid.
                      </span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2"><MapPin size={16} />Top municipios</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              {data.top_municipios.map((m) => (
                <div key={m.municipio} className="flex items-center justify-between text-sm p-2 rounded hover:bg-muted">
                  <span className="truncate">{m.municipio}</span>
                  <span className="font-semibold ml-2 shrink-0">{m.count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2"><Building2 size={16} />Top oficinas responsables</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              {data.top_oficinas.map((o) => (
                <div key={o.oficina} className="flex items-center justify-between text-sm p-2 rounded hover:bg-muted">
                  <span className="truncate">{o.oficina}</span>
                  <span className="font-semibold ml-2 shrink-0">{o.count}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2"><UserCircle2 size={16} />Accionantes recurrentes</CardTitle>
          </CardHeader>
          <CardContent>
            {data.top_accionantes_recurrentes.length === 0 ? (
              <div className="text-sm text-muted-foreground p-2">No hay accionantes con más de 1 proceso.</div>
            ) : (
              <div className="space-y-1.5">
                {data.top_accionantes_recurrentes.map((a) => (
                  <div key={a.accionante} className="flex items-center justify-between text-sm p-2 rounded hover:bg-muted">
                    <span className="truncate">{a.accionante}</span>
                    <span className="font-semibold ml-2 shrink-0">{a.procesos} procesos</span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 text-xs text-muted-foreground text-center">
        Generado: {data.generated_at} · v6.0 Propuesta 9.9
      </div>
    </PageShell>
  )
}
