import { useQuery } from '@tanstack/react-query'
import { Loader2, Sparkles, FileText, Scale, AlertCircle } from 'lucide-react'
import { getSimilarCases, type SimilarResponse, type SimilarNeighbor, type SimilarConsensus } from '../services/api'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { cn } from '@/lib/utils'

// Lenguaje técnico → jurídico ──────────────────────────────────────

const DEPENDENCIA_LABELS: Record<string, string> = {
  DIRECCION_TALENTO_DOCENTE: 'Talento Humano Docente',
  DIRECCION_ESTRATEGICA: 'Dirección Estratégica',
  DIRECCION_PERMANENCIA: 'Permanencia Escolar',
  DIRECCION_ADMIN_FINANCIERA: 'Administrativa y Financiera',
  APOYO_DIRECTO: 'Apoyo Directo Despacho',
  HISTORIAS_LABORALES: 'Historias Laborales',
  NOMINA: 'Nómina',
  COBERTURA_EDUCATIVA: 'Cobertura Educativa',
  CALIDAD_EDUCATIVA: 'Calidad Educativa',
  FINANCIERA: 'Grupo Financiera',
  CARRERA_DOCENTE: 'Carrera Docente',
  PRESTACIONES_SOCIALES: 'Prestaciones Sociales',
  INSPECCION_VIGILANCIA: 'Inspección y Vigilancia',
  SIN_ASIGNAR: 'Sin asignar',
}

const TARGET_LABELS: Record<string, string> = {
  tema: 'Tema',
  dependencia: 'Dependencia',
  direccion: 'Dirección',
  tipo: 'Tipo',
  fallo: 'Fallo histórico',
}

const FALLO_STYLES: Record<string, { label: string; cls: string }> = {
  CONCEDE: { label: 'Concedido', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  NIEGA: { label: 'Negado', cls: 'bg-rose-50 text-rose-700 border-rose-200' },
  IMPROCEDENTE: { label: 'Improcedente', cls: 'bg-zinc-100 text-zinc-700 border-zinc-300' },
  CUMPLIDO: { label: 'Cumplido', cls: 'bg-blue-50 text-blue-700 border-blue-200' },
}

function humanLabel(value: string | null, dict = DEPENDENCIA_LABELS): string {
  if (!value) return '—'
  return dict[value] ?? value.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase())
}

function similarityLabel(score: number) {
  if (score >= 0.70) return { label: 'Muy similar', cls: 'bg-emerald-100 text-emerald-800', dot: 'bg-emerald-500' }
  if (score >= 0.60) return { label: 'Bastante similar', cls: 'bg-blue-100 text-blue-800', dot: 'bg-blue-500' }
  if (score >= 0.50) return { label: 'Algo similar', cls: 'bg-amber-100 text-amber-800', dot: 'bg-amber-500' }
  return { label: 'Lejano', cls: 'bg-zinc-100 text-zinc-700', dot: 'bg-zinc-400' }
}

function confidenceLabel(c: number) {
  if (c >= 0.80) return { label: 'Alta', cls: 'text-emerald-700' }
  if (c >= 0.60) return { label: 'Media', cls: 'text-blue-700' }
  return { label: 'Parcial', cls: 'text-amber-700' }
}

// ─── Componentes ──────────────────────────────────────────────

function ConsensusCard({ c }: { c: SimilarConsensus }) {
  const conf = confidenceLabel(c.confidence)
  const targetLabel = TARGET_LABELS[c.target] ?? c.target
  const valueLabel = c.target === 'fallo'
    ? FALLO_STYLES[c.value]?.label ?? c.value
    : humanLabel(c.value)

  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-muted/40 border border-border">
      <Sparkles size={14} className="text-primary shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-[11px] text-muted-foreground uppercase tracking-wide">{targetLabel}</div>
        <div className="text-sm font-medium truncate">{valueLabel}</div>
      </div>
      <div className="text-right shrink-0">
        <div className={cn('text-xs font-semibold', conf.cls)}>{conf.label}</div>
        <div className="text-[10px] text-muted-foreground">
          {c.n_valid} de {c.n_neighbors} casos
        </div>
      </div>
    </div>
  )
}

function FalloDistribution({ neighbors }: { neighbors: SimilarNeighbor[] }) {
  const counts: Record<string, number> = {}
  let withFallo = 0
  for (const n of neighbors) {
    if (n.fallo) {
      counts[n.fallo] = (counts[n.fallo] ?? 0) + 1
      withFallo++
    }
  }
  if (withFallo === 0) return null

  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1])
  return (
    <Alert className="bg-primary/5 border-primary/20">
      <Scale className="h-4 w-4" />
      <AlertDescription className="text-sm">
        <span className="font-medium">Predicción de resultado: </span>
        <span className="text-muted-foreground">de {withFallo} casos similares con fallo registrado, </span>
        {sorted.map(([fallo, n], i) => {
          const style = FALLO_STYLES[fallo]
          return (
            <span key={fallo}>
              {i > 0 && ', '}
              <span className={cn('font-semibold', style?.cls.split(' ').filter(c => c.startsWith('text-')).join(' '))}>
                {n} {n === 1 ? 'fue' : 'fueron'} {style?.label.toLowerCase() ?? fallo}
              </span>
            </span>
          )
        })}
        .
      </AlertDescription>
    </Alert>
  )
}

function NeighborCard({ n }: { n: SimilarNeighbor }) {
  const sim = similarityLabel(n.score)
  const fallo = n.fallo ? FALLO_STYLES[n.fallo] : null
  const dep = humanLabel(n.dependencia)
  const tema = humanLabel(n.tema, {})

  return (
    <Card className="overflow-hidden hover:ring-1 hover:ring-primary/30 transition-all py-0">
      <div className="px-3 py-2 bg-muted/30 border-b border-border flex items-center justify-between">
        <div className="flex items-center gap-2">
          <FileText size={13} className="text-muted-foreground" />
          <span className="text-xs font-medium">
            Caso histórico #{n.case_id}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className={cn('w-1.5 h-1.5 rounded-full', sim.dot)} />
          <Badge className={cn('text-[10px] px-1.5 border-0', sim.cls)}>{sim.label}</Badge>
        </div>
      </div>
      <CardContent className="p-3 space-y-2">
        <div className="flex flex-wrap gap-1.5">
          {n.tema && (
            <Badge variant="outline" className="text-[10px]">
              {tema}
            </Badge>
          )}
          {n.dependencia && (
            <Badge variant="outline" className="text-[10px]">
              {dep}
            </Badge>
          )}
          {fallo && (
            <Badge className={cn('text-[10px] border', fallo.cls)}>
              {fallo.label}
            </Badge>
          )}
        </div>
        {n.text_preview && (
          <p className="text-[11px] text-muted-foreground line-clamp-3 leading-relaxed">
            {n.text_preview}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

// ─── Panel principal ───────────────────────────────────────

export function SimilarCasesPanel({ caseId }: { caseId: number }) {
  const q = useQuery({
    queryKey: ['similar-cases', caseId],
    queryFn: () => getSimilarCases(caseId, 5, 'historical'),
    enabled: !!caseId,
    staleTime: 5 * 60_000,
  })

  if (q.isLoading) {
    return (
      <div className="p-6 flex items-center justify-center text-muted-foreground">
        <Loader2 className="animate-spin" size={16} />
        <span className="ml-2 text-xs">Buscando casos parecidos en el archivo histórico…</span>
      </div>
    )
  }

  if (q.isError) {
    return (
      <Alert variant="destructive" className="m-4">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          No fue posible consultar el archivo histórico de tutelas.
        </AlertDescription>
      </Alert>
    )
  }

  const data = q.data as SimilarResponse | undefined
  if (!data || data.neighbors.length === 0) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <Sparkles size={28} className="mx-auto mb-2 opacity-30" />
        <p className="text-xs">No se encontraron casos similares en el archivo histórico.</p>
        <p className="text-[10px] mt-1">El caso puede ser atípico o tener poca información extraída.</p>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-4">
      <div>
        <p className="text-[11px] text-muted-foreground mb-1">
          Encontré <span className="font-semibold text-foreground">{data.neighbors.length} tutelas anteriores</span> con
          asunto y pretensiones parecidas. Esto ayuda a clasificar el caso y anticipar el probable resultado.
        </p>
      </div>

      <FalloDistribution neighbors={data.neighbors} />

      {data.consensus.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium px-1">
            Sugerencia de clasificación
          </div>
          {data.consensus.map(c => <ConsensusCard key={c.target} c={c} />)}
        </div>
      )}

      <div className="space-y-2">
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground font-medium px-1">
          Casos parecidos del archivo
        </div>
        {data.neighbors.map(n => <NeighborCard key={n.case_id} n={n} />)}
      </div>

      <p className="text-[10px] text-muted-foreground italic px-1 pt-2 border-t border-border">
        Estas sugerencias son orientativas. Verifica siempre con el expediente antes de clasificar o asignar.
      </p>
    </div>
  )
}

export default SimilarCasesPanel
