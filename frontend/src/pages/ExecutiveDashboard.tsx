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
  ResponsiveContainer, LineChart, Line, PieChart, Pie, Cell, CartesianGrid,
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
    compliance_rate: number
    casos_criticos_rojos: number
    casos_vigilancia_amarillos: number
    casos_en_sancion: number
    casos_con_incidente_activo: number
  }
  compliance: Record<string, number>
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
  by_month: Array<{ month: string; count: number }>
  by_origen: Record<string, number>
  by_estado_incidente: Record<string, number>
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

  const complianceAsPct = Math.round(data.summary.compliance_rate * 100)
  const rojos = data.summary.casos_criticos_rojos
  const sancion = data.summary.casos_en_sancion
  const activos = data.summary.casos_con_incidente_activo

  return (
    <PageShell>
      <PageHeader
        title="Dashboard Ejecutivo"
        subtitle={`KPIs consolidados · Gobernación de Santander · ${data.summary.total_cases} casos activos`}
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
            icon={CheckCircle2} label="Tasa cumplimiento" value={`${complianceAsPct}%`}
            sublabel={`${data.compliance.completo}/${data.compliance.total_activos} COMPLETO`}
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
            <CardTitle className="text-sm flex items-center gap-2"><Briefcase size={16} />Clasificación v6.0</CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-1">
            {Object.entries(data.by_origen).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="text-muted-foreground">{k}:</span>
                <span className="font-semibold">{v}</span>
              </div>
            ))}
            <div className="border-t pt-1 mt-2 text-xs text-muted-foreground">Estados de incidente:</div>
            {Object.entries(data.by_estado_incidente).filter(([k]) => k !== 'N/A').map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="text-muted-foreground">{k}:</span>
                <span className={`font-semibold ${k === 'EN_SANCION' ? 'text-red-600' : k === 'ACTIVO' ? 'text-orange-500' : ''}`}>{v}</span>
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
