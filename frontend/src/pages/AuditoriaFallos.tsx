/**
 * Auditoría integral de fallos e incidentes — v8.2
 *
 * Vista unificada para hacer seguimiento completo:
 * - Por etapa procesal (incidente sanción, consulta, activo, fallos 1ra/2da)
 * - Por abogado canónico (carga, críticos, plazos)
 * - Por dependencia
 * - Cruce con bitácora administrativa importada del Excel
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle, Flame, Clock, Scale, ShieldCheck, RefreshCw,
  Users, Building2, Filter, ExternalLink,
} from 'lucide-react'
import api from '@/services/api'
import PageHeader from '@/components/PageHeader'
import PageShell from '@/components/PageShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

interface AuditCard {
  case_id: number
  folder_name: string
  radicado: string
  accionante: string
  abogado_canonical: string | null
  abogado_short_display: string | null
  dependencia_canonical: string | null
  etapa: string
  origen: string
  estado_incidente: string
  sentido_fallo_1st: string | null
  fecha_fallo_1st: string | null
  sentido_fallo_2nd: string | null
  fecha_fallo_2nd: string | null
  fecha_apertura_incidente: string | null
  compliance: {
    instancia: string
    sentido_fallo: string
    fecha_fallo: string
    fecha_limite: string | null
    dias_restantes: number | null
    estado: string
    impugnado: string
  } | null
  ultima_actuacion: {
    fecha: string | null
    tipo: string
    tema: string | null
    observaciones: string
  } | null
  risk_level: string
  risk_score: number
  risk_reasons: string[]
}

interface Dashboard {
  generated_at: string
  total_cases: number
  rojos: number
  amarillos: number
  by_etapa: Record<string, number>
  by_abogado: Array<{ abogado: string; total: number; criticos: number; incidentes: number; vencidos: number }>
  by_dependencia: Array<{ dependencia: string; total: number; criticos: number; incidentes: number }>
}

const ETAPA_LABEL: Record<string, string> = {
  INCIDENTE_SANCION: 'Sanción',
  INCIDENTE_CONSULTA: 'Consulta',
  INCIDENTE_ACTIVO: 'Incidente activo',
  INCIDENTE_HUERFANO: 'Huérfano',
  INCIDENTE_CUMPLIDO: 'Cumplido',
  FALLO_2DA: 'Fallo 2da',
  FALLO_1RA: 'Fallo 1ra',
  EN_TRAMITE: 'En trámite',
}

const ETAPA_COLORS: Record<string, string> = {
  INCIDENTE_SANCION: 'bg-red-500/10 text-red-700 border-red-500/30',
  INCIDENTE_CONSULTA: 'bg-purple-500/10 text-purple-700 border-purple-500/30',
  INCIDENTE_ACTIVO: 'bg-orange-500/10 text-orange-700 border-orange-500/30',
  INCIDENTE_HUERFANO: 'bg-amber-500/10 text-amber-700 border-amber-500/30',
  INCIDENTE_CUMPLIDO: 'bg-green-500/10 text-green-700 border-green-500/30',
  FALLO_2DA: 'bg-blue-500/10 text-blue-700 border-blue-500/30',
  FALLO_1RA: 'bg-sky-500/10 text-sky-700 border-sky-500/30',
  EN_TRAMITE: 'bg-slate-500/10 text-slate-700 border-slate-500/30',
}

const RISK_COLORS: Record<string, string> = {
  ROJO: 'bg-red-500 text-white',
  AMARILLO: 'bg-yellow-400 text-yellow-900',
  VERDE: 'bg-green-500 text-white',
  'N/A': 'bg-slate-400 text-white',
}

function shortName(full: string | null): string {
  if (!full) return '—'
  const parts = full.split(' ')
  return parts.length >= 2 ? `${parts[0]} ${parts[parts.length - 1]}` : full
}

function CaseCard({ c }: { c: AuditCard }) {
  return (
    <Link to={`/cases/${c.case_id}`} className="block">
      <div className="p-3 bg-card border rounded-lg hover:shadow-md transition-all">
        <div className="flex items-start gap-2 mb-2">
          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${RISK_COLORS[c.risk_level] || 'bg-slate-400 text-white'}`}>
            {c.risk_level}
          </span>
          <Badge variant="outline" className={`text-[10px] ${ETAPA_COLORS[c.etapa] || ''}`}>
            {ETAPA_LABEL[c.etapa] || c.etapa}
          </Badge>
          <span className="text-[10px] text-muted-foreground ml-auto">#{c.case_id}</span>
        </div>
        <div className="text-sm font-medium truncate">{c.folder_name || c.accionante}</div>
        <div className="flex flex-wrap items-center gap-2 mt-1.5 text-[11px] text-muted-foreground">
          {c.abogado_canonical && (
            <span className="flex items-center gap-1">
              <Users size={10} /> {shortName(c.abogado_canonical)}
            </span>
          )}
          {c.dependencia_canonical && (
            <span className="flex items-center gap-1">
              <Building2 size={10} /> {c.dependencia_canonical.replace(/^DIRECCION_/, '').replace(/_/g, ' ')}
            </span>
          )}
          {c.compliance?.dias_restantes !== null && c.compliance?.dias_restantes !== undefined && (
            <span className={`flex items-center gap-1 font-medium ${
              c.compliance.dias_restantes < 0 ? 'text-red-600' :
              c.compliance.dias_restantes <= 3 ? 'text-orange-600' : 'text-emerald-700'
            }`}>
              <Clock size={10} />
              {c.compliance.dias_restantes < 0
                ? `Vencido ${Math.abs(c.compliance.dias_restantes)}d`
                : `${c.compliance.dias_restantes}d restantes`}
            </span>
          )}
        </div>
        {c.risk_reasons.length > 0 && (
          <ul className="mt-2 space-y-0.5">
            {c.risk_reasons.slice(0, 2).map((r, i) => (
              <li key={i} className="text-[11px] text-muted-foreground flex gap-1">
                <span className="text-red-500">→</span>
                <span className="truncate">{r}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Link>
  )
}

export default function AuditoriaFallos() {
  const [tab, setTab] = useState<'overview' | 'cases' | 'abogados' | 'dependencias'>('overview')
  const [dashboard, setDashboard] = useState<Dashboard | null>(null)
  const [cases, setCases] = useState<AuditCard[]>([])
  const [loading, setLoading] = useState(true)
  const [filterEtapa, setFilterEtapa] = useState<string>('')
  const [filterAbogado, setFilterAbogado] = useState<string>('')
  const [filterRisk, setFilterRisk] = useState<string>('')

  async function loadDashboard() {
    setLoading(true)
    try {
      const r = await api.get('/auditoria/dashboard')
      setDashboard(r.data)
    } finally {
      setLoading(false)
    }
  }

  async function loadCases() {
    setLoading(true)
    try {
      const params: any = { limit: 200, only_active: true }
      if (filterEtapa) params.etapa = filterEtapa
      if (filterAbogado) params.abogado = filterAbogado
      if (filterRisk) params.risk_level = filterRisk
      const r = await api.get('/auditoria/cases', { params })
      setCases(r.data.items)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadDashboard() }, [])
  useEffect(() => {
    if (tab === 'cases') loadCases()
  }, [tab, filterEtapa, filterAbogado, filterRisk])

  return (
    <PageShell>
      <PageHeader
        title="Auditoría integral de fallos"
        subtitle="Seguimiento procesal por etapa, abogado y dependencia · v8.2"
        action={
          <Button onClick={loadDashboard} variant="outline" size="sm" disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Actualizar
          </Button>
        }
      />

      {/* Tabs */}
      <div className="border-b mb-4 flex gap-1 -mt-2">
        {[
          { id: 'overview', label: 'Vista general', icon: Scale },
          { id: 'cases', label: 'Cases', icon: AlertTriangle },
          { id: 'abogados', label: 'Por abogado', icon: Users },
          { id: 'dependencias', label: 'Por dependencia', icon: Building2 },
        ].map((t) => {
          const Icon = t.icon
          const active = tab === t.id
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id as any)}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                active
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              <Icon size={14} />
              {t.label}
            </button>
          )
        })}
      </div>

      {tab === 'overview' && dashboard && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <Card className="border-red-500/30 bg-red-500/5">
              <CardContent className="p-4">
                <div className="text-xs uppercase text-red-700 font-semibold flex items-center gap-1.5"><Flame size={12}/>Críticos ROJO</div>
                <div className="text-3xl font-bold text-red-600 mt-1">{dashboard.rojos}</div>
                <div className="text-[11px] text-muted-foreground mt-1">Intervención inmediata</div>
              </CardContent>
            </Card>
            <Card className="border-yellow-400/40 bg-yellow-500/5">
              <CardContent className="p-4">
                <div className="text-xs uppercase text-yellow-700 font-semibold flex items-center gap-1.5"><AlertTriangle size={12}/>Vigilar AMARILLO</div>
                <div className="text-3xl font-bold text-yellow-600 mt-1">{dashboard.amarillos}</div>
                <div className="text-[11px] text-muted-foreground mt-1">Próximos días</div>
              </CardContent>
            </Card>
            <Card className="border-orange-400/40 bg-orange-500/5">
              <CardContent className="p-4">
                <div className="text-xs uppercase text-orange-700 font-semibold flex items-center gap-1.5"><AlertTriangle size={12}/>En sanción</div>
                <div className="text-3xl font-bold text-orange-600 mt-1">{dashboard.by_etapa['INCIDENTE_SANCION'] || 0}</div>
                <div className="text-[11px] text-muted-foreground mt-1">Auto sanción dictado</div>
              </CardContent>
            </Card>
            <Card className="border-blue-400/40 bg-blue-500/5">
              <CardContent className="p-4">
                <div className="text-xs uppercase text-blue-700 font-semibold flex items-center gap-1.5"><Scale size={12}/>Total casos</div>
                <div className="text-3xl font-bold text-blue-600 mt-1">{dashboard.total_cases}</div>
                <div className="text-[11px] text-muted-foreground mt-1">Activos en BD</div>
              </CardContent>
            </Card>
          </div>

          <Card className="mb-6">
            <CardHeader className="pb-2"><CardTitle className="text-sm">Distribución por etapa procesal</CardTitle></CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                {Object.entries(dashboard.by_etapa)
                  .sort((a, b) => b[1] - a[1])
                  .map(([etapa, count]) => (
                    <button
                      key={etapa}
                      onClick={() => { setFilterEtapa(etapa); setTab('cases') }}
                      className={`p-3 rounded-lg border-2 text-left ${ETAPA_COLORS[etapa] || ''} hover:opacity-80`}
                    >
                      <div className="text-2xl font-bold">{count}</div>
                      <div className="text-xs">{ETAPA_LABEL[etapa] || etapa}</div>
                    </button>
                  ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}

      {tab === 'cases' && (
        <>
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <span className="text-xs font-semibold flex items-center gap-1"><Filter size={12}/>Filtros:</span>
            {['', 'ROJO', 'AMARILLO'].map((r) => (
              <button
                key={r}
                onClick={() => setFilterRisk(r)}
                className={`px-2.5 py-1 rounded text-[11px] font-medium border ${
                  filterRisk === r ? 'bg-primary text-primary-foreground border-primary' : 'bg-card hover:border-primary'
                }`}
              >
                {r || 'Todos'}
              </button>
            ))}
            <span className="mx-2 text-muted-foreground text-xs">·</span>
            {['', 'INCIDENTE_SANCION', 'INCIDENTE_ACTIVO', 'FALLO_1RA', 'FALLO_2DA'].map((e) => (
              <button
                key={e}
                onClick={() => setFilterEtapa(e)}
                className={`px-2.5 py-1 rounded text-[11px] font-medium border ${
                  filterEtapa === e ? 'bg-primary text-primary-foreground border-primary' : 'bg-card hover:border-primary'
                }`}
              >
                {e ? (ETAPA_LABEL[e] || e) : 'Todas'}
              </button>
            ))}
          </div>
          {cases.length === 0 ? (
            <div className="p-12 text-center text-muted-foreground">
              <ShieldCheck size={32} className="mx-auto mb-2 opacity-50" />
              {loading ? 'Cargando...' : 'No hay cases con los filtros aplicados'}
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {cases.map((c) => <CaseCard key={c.case_id} c={c} />)}
            </div>
          )}
        </>
      )}

      {tab === 'abogados' && dashboard && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Carga por abogado canónico</CardTitle></CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground border-b">
                <tr>
                  <th className="text-left py-2">Abogado</th>
                  <th className="text-right">Total</th>
                  <th className="text-right">Críticos</th>
                  <th className="text-right">Incidentes</th>
                  <th className="text-right">Vencidos</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {dashboard.by_abogado.map((a) => (
                  <tr key={a.abogado} className="border-b hover:bg-muted/30">
                    <td className="py-2 font-medium">{a.abogado}</td>
                    <td className="text-right">{a.total}</td>
                    <td className={`text-right font-semibold ${a.criticos > 0 ? 'text-red-600' : ''}`}>{a.criticos}</td>
                    <td className={`text-right ${a.incidentes > 0 ? 'text-orange-600' : ''}`}>{a.incidentes}</td>
                    <td className={`text-right ${a.vencidos > 0 ? 'text-red-700 font-bold' : ''}`}>{a.vencidos}</td>
                    <td className="text-right">
                      <button
                        onClick={() => { setFilterAbogado(a.abogado); setTab('cases') }}
                        className="text-primary text-xs hover:underline flex items-center gap-1 ml-auto"
                      >
                        Ver <ExternalLink size={11} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {tab === 'dependencias' && dashboard && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Carga por dependencia</CardTitle></CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground border-b">
                <tr>
                  <th className="text-left py-2">Dependencia</th>
                  <th className="text-right">Total</th>
                  <th className="text-right">Críticos</th>
                  <th className="text-right">Incidentes</th>
                </tr>
              </thead>
              <tbody>
                {dashboard.by_dependencia.map((d) => (
                  <tr key={d.dependencia} className="border-b hover:bg-muted/30">
                    <td className="py-2 font-medium">{d.dependencia.replace(/_/g, ' ')}</td>
                    <td className="text-right">{d.total}</td>
                    <td className={`text-right font-semibold ${d.criticos > 0 ? 'text-red-600' : ''}`}>{d.criticos}</td>
                    <td className={`text-right ${d.incidentes > 0 ? 'text-orange-600' : ''}`}>{d.incidentes}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </PageShell>
  )
}
