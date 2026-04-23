/**
 * EarlyWarning — Propuesta 9.4 de la tesis v6.0.
 *
 * Dashboard semáforo de alertas tempranas. Consume GET /api/alerts/early-warning
 * y muestra conteos por nivel + lista de casos críticos con razones explícitas.
 *
 * Sin dependencias nuevas: usa Tailwind + shadcn/ui ya instalados.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ShieldCheck, CircleAlert, RefreshCw, Filter } from 'lucide-react'
import api from '@/services/api'
import PageHeader from '@/components/PageHeader'
import PageShell from '@/components/PageShell'
import { Button } from '@/components/ui/button'

type Level = 'ROJO' | 'AMARILLO' | 'VERDE' | 'N/A'

interface RiskCase {
  case_id: number
  folder_name: string
  origen: string
  estado_incidente: string
  level: Level
  score: number
  reasons: string[]
  days_since_incidente: number | null
  days_since_fallo_1st: number | null
  has_response: boolean
  abogado_responsable: string
  entropy_score: number | null
}

interface Summary {
  total_cases_evaluated: number
  by_level: Record<string, number>
  red: RiskCase[]
  yellow: RiskCase[]
  green_count: number
  na_count: number
  generated_at: string
}

const LEVEL_STYLES: Record<Level, { bg: string; border: string; text: string; accent: string; label: string; icon: any }> = {
  ROJO: {
    bg: 'bg-red-500/10',
    border: 'border-red-500/40',
    text: 'text-red-600 dark:text-red-400',
    accent: 'bg-red-500',
    label: 'Crítico',
    icon: AlertTriangle,
  },
  AMARILLO: {
    bg: 'bg-yellow-500/10',
    border: 'border-yellow-500/40',
    text: 'text-yellow-600 dark:text-yellow-400',
    accent: 'bg-yellow-500',
    label: 'Vigilar',
    icon: CircleAlert,
  },
  VERDE: {
    bg: 'bg-green-500/10',
    border: 'border-green-500/40',
    text: 'text-green-600 dark:text-green-400',
    accent: 'bg-green-500',
    label: 'En regla',
    icon: ShieldCheck,
  },
  'N/A': {
    bg: 'bg-slate-500/10',
    border: 'border-slate-500/40',
    text: 'text-slate-500',
    accent: 'bg-slate-500',
    label: 'N/A',
    icon: ShieldCheck,
  },
}

function LevelCard({ level, count, onClick, active }: { level: Level; count: number; onClick: () => void; active: boolean }) {
  const s = LEVEL_STYLES[level]
  const Icon = s.icon
  return (
    <button
      onClick={onClick}
      className={`
        p-5 rounded-xl border-2 text-left transition-all
        ${s.bg} ${active ? s.border : 'border-transparent'}
        hover:${s.border} hover:scale-[1.02]
      `}
    >
      <div className="flex items-center justify-between mb-2">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${s.accent}`}>
          <Icon size={20} className="text-white" />
        </div>
        <span className={`text-xs font-semibold uppercase tracking-wide ${s.text}`}>
          {s.label}
        </span>
      </div>
      <div className={`text-4xl font-bold ${s.text}`}>{count}</div>
      <div className="text-xs text-muted-foreground mt-1">
        {level === 'ROJO' ? 'Intervención inmediata' : level === 'AMARILLO' ? 'Vigilar próximos días' : level === 'VERDE' ? 'Caso en cumplimiento' : 'No aplicable'}
      </div>
    </button>
  )
}

function CaseRow({ c }: { c: RiskCase }) {
  const s = LEVEL_STYLES[c.level]
  return (
    <Link
      to={`/cases/${c.case_id}`}
      className={`block p-4 rounded-lg border ${s.border} ${s.bg} hover:shadow-md transition-shadow`}
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`px-2 py-0.5 rounded text-xs font-bold ${s.text} ${s.bg}`}>
              {c.level} · score {c.score.toFixed(2)}
            </span>
            <span className="text-xs text-muted-foreground">
              #{c.case_id} · {c.origen}
            </span>
            {c.estado_incidente !== 'N/A' && (
              <span className="px-2 py-0.5 rounded bg-slate-500/10 text-xs font-medium">
                {c.estado_incidente}
              </span>
            )}
          </div>
          <div className="font-medium truncate">{c.folder_name}</div>
        </div>
        <div className="text-right text-xs text-muted-foreground shrink-0">
          {c.abogado_responsable || '—'}
        </div>
      </div>
      <ul className="mt-2 space-y-0.5 text-sm">
        {c.reasons.slice(0, 3).map((r, i) => (
          <li key={i} className="text-muted-foreground flex gap-2">
            <span className={s.text}>→</span>
            <span>{r}</span>
          </li>
        ))}
      </ul>
    </Link>
  )
}

export default function EarlyWarning() {
  const [data, setData] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Level | 'ALL'>('ALL')

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get('/alerts/early-warning')
      setData(res.data)
    } catch (e: any) {
      setError(e?.message || 'Error cargando alertas')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const total = data?.total_cases_evaluated ?? 0
  const rojos = data?.by_level?.ROJO ?? 0
  const amarillos = data?.by_level?.AMARILLO ?? 0
  const verdes = data?.by_level?.VERDE ?? 0
  const na = data?.by_level?.['N/A'] ?? 0

  const shownCases: RiskCase[] =
    filter === 'ROJO' ? data?.red ?? [] :
    filter === 'AMARILLO' ? data?.yellow ?? [] :
    [...(data?.red ?? []), ...(data?.yellow ?? [])]

  return (
    <PageShell>
      <PageHeader
        title="Alertas Tempranas"
        subtitle="Semáforo institucional de riesgo procesal — v6.0 Propuesta 9.4"
        action={
          <Button onClick={load} variant="outline" size="sm" disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            {loading ? 'Cargando...' : 'Actualizar'}
          </Button>
        }
      />

      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/40 rounded-lg text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {data && (
        <>
          <div className="flex items-center justify-between mb-4 text-sm text-muted-foreground">
            <span>{total} casos evaluados · Generado {data.generated_at}</span>
            <div className="flex items-center gap-2">
              <Filter size={14} />
              <span>Filtrar:</span>
              <Button
                size="sm"
                variant={filter === 'ALL' ? 'default' : 'outline'}
                onClick={() => setFilter('ALL')}
              >
                Rojos + Amarillos
              </Button>
              <Button
                size="sm"
                variant={filter === 'ROJO' ? 'default' : 'outline'}
                onClick={() => setFilter('ROJO')}
              >
                Solo rojos
              </Button>
              <Button
                size="sm"
                variant={filter === 'AMARILLO' ? 'default' : 'outline'}
                onClick={() => setFilter('AMARILLO')}
              >
                Solo amarillos
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <LevelCard level="ROJO" count={rojos} onClick={() => setFilter('ROJO')} active={filter === 'ROJO'} />
            <LevelCard level="AMARILLO" count={amarillos} onClick={() => setFilter('AMARILLO')} active={filter === 'AMARILLO'} />
            <LevelCard level="VERDE" count={verdes} onClick={() => setFilter('ALL')} active={false} />
            <LevelCard level="N/A" count={na} onClick={() => setFilter('ALL')} active={false} />
          </div>

          <div>
            <h3 className="font-semibold text-lg mb-3">
              {filter === 'ROJO' ? `${shownCases.length} casos críticos` :
               filter === 'AMARILLO' ? `${shownCases.length} casos a vigilar` :
               `${shownCases.length} casos rojos + amarillos`}
            </h3>
            {shownCases.length === 0 ? (
              <div className="p-8 bg-green-500/10 border border-green-500/40 rounded-lg text-center">
                <ShieldCheck size={40} className="text-green-500 mx-auto mb-2" />
                <p className="text-green-700 dark:text-green-400 font-medium">
                  No hay casos en este nivel
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {shownCases.map((c) => (
                  <CaseRow key={c.case_id} c={c} />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </PageShell>
  )
}
