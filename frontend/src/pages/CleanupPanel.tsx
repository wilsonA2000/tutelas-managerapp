import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Sparkles, Play, Eye, Loader2, CheckCircle, AlertTriangle,
  Hash, Mail, GitMerge, ArrowRightLeft, RefreshCw, Copy, FileSearch, TreePine,
  ChevronDown, ChevronUp, FileWarning, Folders, BarChart3, InboxIcon,
} from 'lucide-react'
import {
  getCleanupDiagnosis, runHashBackfill, runEmailsMdBackfill,
  runMoveNoPertenece, runMergeIdentity,
  runPurgeDuplicates, runMergeForestFragments, runBackfillRadicados,
  getHealthV50,
} from '../services/api'
import PageShell from '@/components/PageShell'
import PageHeader from '@/components/PageHeader'
import DataCard from '@/components/DataCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'

interface ActionResult {
  [key: string]: unknown
}

function ActionCard({ title, description, icon: Icon, onPreview, onExecute, isPreviewing, isExecuting, result, iconColor = 'text-primary' }: {
  title: string
  description: string
  icon: React.ElementType
  onPreview: () => void
  onExecute: () => void
  isPreviewing: boolean
  isExecuting: boolean
  result: ActionResult | null
  iconColor?: string
}) {
  const [expanded, setExpanded] = useState(false)
  const busy = isPreviewing || isExecuting

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div className={`mt-0.5 ${iconColor}`}><Icon size={20} /></div>
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-foreground text-sm">{title}</h3>
            <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
          </div>
          <div className="flex gap-2 flex-shrink-0">
            <Button
              variant="outline"
              size="sm"
              onClick={onPreview}
              disabled={busy}
            >
              {isPreviewing ? <Loader2 size={14} className="animate-spin" /> : <Eye size={14} />}
              Vista Previa
            </Button>
            <Button
              size="sm"
              onClick={onExecute}
              disabled={busy}
            >
              {isExecuting ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              Ejecutar
            </Button>
          </div>
        </div>

        {result && (
          <div className="mt-3 bg-muted/50 rounded-md p-3">
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-sm font-medium text-muted-foreground w-full"
            >
              <CheckCircle size={14} className="text-emerald-500" />
              <span>Resultado</span>
              {expanded ? <ChevronUp size={14} className="ml-1" /> : <ChevronDown size={14} className="ml-1" />}
            </button>
            {expanded && (
              <pre className="mt-2 text-xs text-muted-foreground overflow-x-auto whitespace-pre-wrap">
                {JSON.stringify(result, null, 2)}
              </pre>
            )}
            {!expanded && (
              <div className="mt-1 flex flex-wrap gap-2">
                {Object.entries(result).filter(([k]) => !['dry_run', 'duration_s', 'actions'].includes(k)).map(([k, v]) => (
                  <Badge key={k} variant="outline" className="text-xs font-normal">
                    {k}: <strong className="ml-1">{String(v)}</strong>
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function CleanupPanel() {
  const qc = useQueryClient()
  const [results, setResults] = useState<Record<string, ActionResult | null>>({})

  const diagQ = useQuery({
    queryKey: ['cleanup-diagnosis'],
    queryFn: getCleanupDiagnosis,
  })

  // v5.0 Salud de Datos (KPIs post-audit)
  const healthQ = useQuery({
    queryKey: ['cleanup-health-v50'],
    queryFn: getHealthV50,
  })
  const health = healthQ.data as {
    summary?: {
      folders_pendiente_revision_activos?: number
      completo_sin_rad23?: number
      folders_disonantes_b1_residual?: number
      obs_contaminadas_b4_residual?: number
      pares_duplicados_f9?: number
      docs_sospechosos_total?: number
    }
    top_sospechosos?: Array<{ case_id: number; folder: string; n_sospechosos: number }>
    duplicate_pairs?: Array<{ rad_corto: string; case_ids: number[] }>
  } | undefined

  const diag = diagQ.data as Record<string, unknown> | undefined

  // Mutations for each action
  const hashMut = useMutation({
    mutationFn: (dryRun: boolean) => runHashBackfill(dryRun),
    onSuccess: (data, dryRun) => {
      setResults(r => ({ ...r, hash: data }))
      toast.success(dryRun ? 'Preview hash backfill listo' : `Hash backfill: ${data.hashed} docs actualizados`)
      if (!dryRun) qc.invalidateQueries({ queryKey: ['cleanup-diagnosis'] })
    },
    onError: () => toast.error('Error en hash backfill'),
  })

  const emailMut = useMutation({
    mutationFn: (dryRun: boolean) => runEmailsMdBackfill(dryRun),
    onSuccess: (data, dryRun) => {
      setResults(r => ({ ...r, email: data }))
      toast.success(dryRun ? 'Preview email backfill listo' : `Email backfill: ${data.generated} generados`)
      if (!dryRun) qc.invalidateQueries({ queryKey: ['cleanup-diagnosis'] })
    },
    onError: () => toast.error('Error en email backfill'),
  })

  const moveMut = useMutation({
    mutationFn: (dryRun: boolean) => runMoveNoPertenece(dryRun, 'MEDIA'),
    onSuccess: (data, dryRun) => {
      setResults(r => ({ ...r, move: data }))
      toast.success(dryRun ? 'Preview move listo' : `Movidos: ${data.moved} docs`)
      if (!dryRun) qc.invalidateQueries({ queryKey: ['cleanup-diagnosis'] })
    },
    onError: () => toast.error('Error al mover docs'),
  })

  const mergeMut = useMutation({
    mutationFn: (dryRun: boolean) => runMergeIdentity(dryRun, true),
    onSuccess: (data, dryRun) => {
      setResults(r => ({ ...r, merge: data }))
      toast.success(dryRun ? 'Preview merge listo' : `Merge: ${data.groups_processed} grupos procesados`)
      if (!dryRun) qc.invalidateQueries({ queryKey: ['cleanup-diagnosis'] })
    },
    onError: () => toast.error('Error al merge'),
  })

  // v5.0 mutations
  const purgeMut = useMutation({
    mutationFn: (dryRun: boolean) => runPurgeDuplicates(dryRun, 'intra'),
    onSuccess: (data, dryRun) => {
      setResults(r => ({ ...r, purge: data }))
      toast.success(dryRun ? `Preview: ${data.intra_removed} duplicados eliminables` : `Purga: ${data.intra_removed} duplicados eliminados`)
      if (!dryRun) qc.invalidateQueries({ queryKey: ['cleanup-diagnosis'] })
    },
    onError: () => toast.error('Error al purgar duplicados'),
  })

  const forestMut = useMutation({
    mutationFn: (dryRun: boolean) => runMergeForestFragments(dryRun, 'MEDIA'),
    onSuccess: (data, dryRun) => {
      setResults(r => ({ ...r, forest: data }))
      toast.success(dryRun ? `Preview: ${data.fragments_merged} fragmentos fusionables` : `Fusion: ${data.fragments_merged} fragmentos fusionados`)
      if (!dryRun) qc.invalidateQueries({ queryKey: ['cleanup-diagnosis'] })
    },
    onError: () => toast.error('Error al fusionar fragmentos'),
  })

  const radMut = useMutation({
    mutationFn: (dryRun: boolean) => runBackfillRadicados(dryRun),
    onSuccess: (data, dryRun) => {
      setResults(r => ({ ...r, rad: data }))
      toast.success(dryRun ? `Preview: ${data.auto_assigned} radicados asignables` : `Backfill: ${data.auto_assigned} radicados asignados`)
      if (!dryRun) qc.invalidateQueries({ queryKey: ['cleanup-diagnosis'] })
    },
    onError: () => toast.error('Error al completar radicados'),
  })

  // Extract diagnosis from actual API structure
  const totals = diag?.totals as Record<string, number> | undefined
  const totalCases = totals?.cases ?? 0
  const totalDocs = totals?.documents ?? 0
  const totalEmails = totals?.emails ?? 0
  const casesCompleto = totals?.cases_completo ?? 0
  const casesRevision = totals?.cases_revision ?? 0

  const groups = diag?.identity_groups as Record<string, unknown> | undefined
  const autoMergeable = (groups?.auto_count as number) ?? 0
  const manualReview = (groups?.manual_count as number) ?? 0

  const docsNoHashObj = diag?.docs_without_hash as Record<string, unknown> | undefined
  const docsNoHash = (docsNoHashObj?.count as number) ?? 0

  const noPertenece = (diag?.docs_no_pertenece as Record<string, unknown>)?.count as number ?? 0
  const sospechoso = (diag?.docs_sospechoso as Record<string, unknown>)?.count as number ?? 0
  const fragments = (diag?.fragments as unknown[])?.length ?? 0

  const emailsObj = diag?.emails as Record<string, unknown> | undefined
  const emailsNoMd = (emailsObj?.missing_md as number) ?? 0

  // v5.0 metrics
  const forestFragments = (diag?.forest_fragments as unknown[]) ?? []
  const forestWithParent = forestFragments.filter((f: any) => f.suggested_parent_case_id).length
  const incompleteRads = diag?.incomplete_radicados as Record<string, unknown> | undefined
  const missingRads = (incompleteRads?.missing_count as number) ?? 0
  const dupCleanup = diag?.duplicate_cleanup as Record<string, unknown> | undefined
  const intraDups = ((dupCleanup?.intra_case as Record<string, unknown>)?.removable_docs as number) ?? 0

  const healthScore = Math.max(5, 100 - ((docsNoHash + autoMergeable + noPertenece + fragments + intraDups) / Math.max(totalDocs, 1)) * 100)
  const healthLabel = docsNoHash === 0 && autoMergeable === 0 && noPertenece === 0
    ? 'Excelente'
    : docsNoHash + autoMergeable + noPertenece < 10
    ? 'Buena'
    : 'Requiere atención'
  const healthColor = healthLabel === 'Excelente' ? 'text-emerald-600' : healthLabel === 'Buena' ? 'text-amber-600' : 'text-red-600'

  return (
    <PageShell>
      <PageHeader
        title="Panel de Limpieza"
        subtitle="Diagnóstico y mantenimiento automático de datos"
        icon={Sparkles}
        action={
          <Button
            variant="outline"
            onClick={() => { diagQ.refetch(); healthQ.refetch() }}
            disabled={diagQ.isFetching || healthQ.isFetching}
          >
            <RefreshCw size={16} className={(diagQ.isFetching || healthQ.isFetching) ? 'animate-spin' : ''} />
            Actualizar
          </Button>
        }
      />

      {/* ============================================================ */}
      {/* Salud de Datos V50 — KPIs accionables post auditoria          */}
      {/* ============================================================ */}
      {health?.summary && (
        <Card className="border-emerald-200">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-emerald-100 bg-emerald-50 rounded-t-lg">
            <div className="flex items-center gap-2">
              <CheckCircle size={14} className="text-emerald-600" />
              <span className="text-sm font-medium text-emerald-700">Salud de Datos</span>
              <Badge variant="outline" className="ml-1 text-[10px] text-emerald-700 border-emerald-200 bg-emerald-100">
                post auditoria v5.0
              </Badge>
            </div>
          </div>
          <CardContent className="pt-3">
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 text-xs">
              {[
                {
                  label: 'Carpetas [PENDIENTE]',
                  value: health.summary.folders_pendiente_revision_activos ?? 0,
                  target: 0,
                  hint: 'Folders sin clasificar',
                },
                {
                  label: 'Sin radicado judicial',
                  value: health.summary.completo_sin_rad23 ?? 0,
                  target: 0,
                  hint: 'Completos sin rad 23 digitos',
                },
                {
                  label: 'Carpetas con numero incorrecto',
                  value: health.summary.folders_disonantes_b1_residual ?? 0,
                  target: 0,
                  hint: 'Nombre folder ≠ radicado oficial',
                },
                {
                  label: 'Observaciones con mezcla',
                  value: health.summary.obs_contaminadas_b4_residual ?? 0,
                  target: 5,
                  hint: 'Mencionan radicados ajenos',
                },
                {
                  label: 'Posibles duplicados',
                  value: health.summary.pares_duplicados_f9 ?? 0,
                  target: 0,
                  hint: 'Mismo radicado, casos distintos',
                },
                {
                  label: 'Documentos por revisar',
                  value: health.summary.docs_sospechosos_total ?? 0,
                  target: 30,
                  hint: 'Sospechosos sin clasificar',
                },
              ].map(({ label, value, target, hint }) => {
                const ok = value <= target
                return (
                  <div
                    key={label}
                    className={`rounded-lg p-2.5 border ${ok ? 'bg-emerald-50 border-emerald-200 text-emerald-800' : 'bg-amber-50 border-amber-200 text-amber-800'}`}
                  >
                    <div className="flex items-baseline gap-1">
                      <p className="font-bold text-lg">{value}</p>
                      <p className="text-[10px] opacity-60">/ meta {target}</p>
                    </div>
                    <p className="font-medium text-[11px]">{label}</p>
                    <p className="text-[10px] opacity-70 mt-0.5">{hint}</p>
                  </div>
                )
              })}
            </div>

            {/* Top 3 docs sospechosos */}
            {health.top_sospechosos && health.top_sospechosos.length > 0 && (
              <details className="mt-3 text-xs">
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                  Top casos con documentos sospechosos ({health.top_sospechosos.length})
                </summary>
                <div className="mt-2 space-y-1">
                  {health.top_sospechosos.slice(0, 5).map(s => (
                    <div key={s.case_id} className="flex items-center justify-between px-2 py-1.5 bg-muted/40 rounded">
                      <span className="truncate">{s.folder}</span>
                      <Badge variant="outline" className="text-[10px] ml-2">{s.n_sospechosos} docs</Badge>
                    </div>
                  ))}
                </div>
              </details>
            )}

            {/* Duplicados potenciales */}
            {health.duplicate_pairs && health.duplicate_pairs.length > 0 && (
              <details className="mt-2 text-xs">
                <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                  Posibles duplicados ({health.duplicate_pairs.length}) — revisar manualmente
                </summary>
                <div className="mt-2 space-y-1">
                  {health.duplicate_pairs.slice(0, 8).map(p => (
                    <div key={p.rad_corto} className="flex items-center justify-between px-2 py-1.5 bg-muted/40 rounded">
                      <span className="font-mono text-[11px]">{p.rad_corto}</span>
                      <span className="text-[10px] text-muted-foreground">casos: {p.case_ids.join(', ')}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </CardContent>
        </Card>
      )}

      {/* Stats Grid */}
      {diagQ.isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-lg" />
          ))}
        </div>
      ) : diagQ.isError ? (
        <Alert variant="destructive">
          <AlertTriangle size={16} />
          <AlertDescription>Error al cargar diagnóstico</AlertDescription>
        </Alert>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
            <DataCard icon={Folders} label="Casos" value={totalCases} variant="primary" sub={`${casesCompleto} completos, ${casesRevision} en revisión`} />
            <DataCard icon={BarChart3} label="Documentos" value={totalDocs} variant="primary" />
            <DataCard icon={InboxIcon} label="Correos" value={totalEmails} variant="primary" />
            <DataCard
              icon={GitMerge}
              label="Posibles duplicados"
              value={autoMergeable}
              variant={autoMergeable > 0 ? 'warning' : 'success'}
              sub="Casos con misma identidad"
            />
            <DataCard
              icon={ArrowRightLeft}
              label="Docs mal ubicados"
              value={noPertenece}
              variant={noPertenece > 0 ? 'warning' : 'success'}
              sub="En carpeta incorrecta"
            />
            <DataCard
              icon={FileWarning}
              label="Por revisar"
              value={sospechoso}
              variant={sospechoso > 0 ? 'warning' : 'success'}
              sub="Requieren revisión manual"
            />
            <DataCard
              icon={Hash}
              label="Pendientes de verificar"
              value={docsNoHash}
              variant={docsNoHash > 0 ? 'danger' : 'success'}
              sub="Sin verificación de integridad"
            />
            <DataCard
              icon={Mail}
              label="Correos sin resumen"
              value={emailsNoMd}
              variant={emailsNoMd > 0 ? 'warning' : 'success'}
            />
            <DataCard
              icon={Folders}
              label="Casos parciales"
              value={fragments}
              variant={fragments > 0 ? 'warning' : 'success'}
              sub="Posibles fragmentos"
            />
            <DataCard
              icon={AlertTriangle}
              label="Revisión manual"
              value={manualReview}
              variant={manualReview > 0 ? 'warning' : 'success'}
              sub="Sin radicado identificado"
            />
            <DataCard
              icon={Copy}
              label="Duplicados internos"
              value={intraDups}
              variant={intraDups > 0 ? 'danger' : 'success'}
              sub="Copias eliminables"
            />
            <DataCard
              icon={TreePine}
              label="Fragmentos FOREST"
              value={forestWithParent}
              variant={forestWithParent > 0 ? 'warning' : 'success'}
              sub={`${forestFragments.length} detectados, ${forestWithParent} fusionables`}
            />
            <DataCard
              icon={FileSearch}
              label="Sin radicado 23d"
              value={missingRads}
              variant={missingRads > 0 ? 'warning' : 'success'}
              sub="Casos sin radicado judicial"
            />
          </div>

          {/* Health Bar */}
          {totalDocs > 0 && (
            <Card>
              <CardContent className="p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-foreground">Estado general de los datos</span>
                  <span className={`text-sm font-bold ${healthColor}`}>{healthLabel}</span>
                </div>
                <Progress value={healthScore} className="h-3" />
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Actions */}
      <div>
        <h2 className="text-sm font-semibold text-foreground mb-3 uppercase tracking-wide">Acciones de limpieza</h2>
        <div className="space-y-3">
          <ActionCard
            title="Verificar Integridad de Documentos"
            description="Revisa que todos los documentos tengan verificación de integridad. Permite detectar archivos duplicados."
            icon={Hash}
            iconColor="text-violet-600"
            onPreview={() => hashMut.mutate(true)}
            onExecute={() => { if (confirm('¿Ejecutar verificación de integridad?')) hashMut.mutate(false) }}
            isPreviewing={hashMut.isPending && hashMut.variables === true}
            isExecuting={hashMut.isPending && hashMut.variables === false}
            result={results.hash ?? null}
          />

          <ActionCard
            title="Fusionar Casos Duplicados"
            description="Detecta y fusiona casos que tienen el mismo radicado y accionante. Solo los que se pueden fusionar automáticamente."
            icon={GitMerge}
            iconColor="text-orange-600"
            onPreview={() => mergeMut.mutate(true)}
            onExecute={() => { if (confirm('¿Fusionar los casos duplicados detectados?')) mergeMut.mutate(false) }}
            isPreviewing={mergeMut.isPending && mergeMut.variables === true}
            isExecuting={mergeMut.isPending && mergeMut.variables === false}
            result={results.merge ?? null}
          />

          <ActionCard
            title="Reubicar Documentos"
            description="Mueve documentos que están en la carpeta equivocada al caso correcto, arrastrando los documentos relacionados del mismo correo."
            icon={ArrowRightLeft}
            iconColor="text-primary"
            onPreview={() => moveMut.mutate(true)}
            onExecute={() => { if (confirm('¿Reubicar los documentos detectados?')) moveMut.mutate(false) }}
            isPreviewing={moveMut.isPending && moveMut.variables === true}
            isExecuting={moveMut.isPending && moveMut.variables === false}
            result={results.move ?? null}
          />

          <ActionCard
            title="Generar Resumen de Correos"
            description="Genera un resumen legible para los correos que aún no lo tienen."
            icon={Mail}
            iconColor="text-teal-600"
            onPreview={() => emailMut.mutate(true)}
            onExecute={() => { if (confirm('¿Generar resúmenes de correos pendientes?')) emailMut.mutate(false) }}
            isPreviewing={emailMut.isPending && emailMut.variables === true}
            isExecuting={emailMut.isPending && emailMut.variables === false}
            result={results.email ?? null}
          />

          <h2 className="text-sm font-semibold text-foreground mt-6 mb-3 uppercase tracking-wide">Auditoría v5.0</h2>

          <ActionCard
            title="Purgar Documentos Duplicados"
            description={`Elimina ${intraDups} copias idénticas dentro del mismo caso. Los archivos se mueven a _duplicados/ (no se borran).`}
            icon={Copy}
            iconColor="text-red-600"
            onPreview={() => purgeMut.mutate(true)}
            onExecute={() => { if (confirm(`¿Eliminar ${intraDups} documentos duplicados? Los archivos se mueven a _duplicados/.`)) purgeMut.mutate(false) }}
            isPreviewing={purgeMut.isPending && purgeMut.variables === true}
            isExecuting={purgeMut.isPending && purgeMut.variables === false}
            result={results.purge ?? null}
          />

          <ActionCard
            title="Fusionar Fragmentos FOREST"
            description={`Vincula ${forestWithParent} incidentes/actuaciones creados como casos separados al caso original detectado por radicado.`}
            icon={TreePine}
            iconColor="text-emerald-600"
            onPreview={() => forestMut.mutate(true)}
            onExecute={() => { if (confirm(`¿Fusionar ${forestWithParent} fragmentos con su caso padre?`)) forestMut.mutate(false) }}
            isPreviewing={forestMut.isPending && forestMut.variables === true}
            isExecuting={forestMut.isPending && forestMut.variables === false}
            result={results.forest ?? null}
          />

          <ActionCard
            title="Completar Radicados Faltantes"
            description={`Busca el radicado de 23 dígitos en los documentos de ${missingRads} casos que no lo tienen. Solo asigna con alta confianza.`}
            icon={FileSearch}
            iconColor="text-blue-600"
            onPreview={() => radMut.mutate(true)}
            onExecute={() => { if (confirm('¿Asignar radicados encontrados con alta confianza?')) radMut.mutate(false) }}
            isPreviewing={radMut.isPending && radMut.variables === true}
            isExecuting={radMut.isPending && radMut.variables === false}
            result={results.rad ?? null}
          />
        </div>
      </div>
    </PageShell>
  )
}
