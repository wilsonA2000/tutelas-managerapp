import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  Cpu, Play, RefreshCw, AlertCircle, Loader2,
  CheckCircle, XCircle, Clock, ChevronRight,
  Zap, ShieldAlert, Trash2, FileWarning, Search as SearchIcon, ClipboardCheck, Brain, FolderCheck,
} from 'lucide-react'
import { extractBatch, extractSingle, agentExtract, getReviewQueue, getCases, syncFolders, getSyncStatus, getMismatchedDocs, dismissMismatchedDoc, dismissAllMismatchedDocs, verifyAllDocs, getSuspiciousDocs, markDocOk, runFullAudit } from '../services/api'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

const FIELD_LABELS: Record<string, string> = {
  RADICADO_23_DIGITOS: 'Radicado 23d', RADICADO_FOREST: 'Forest',
  ABOGADO_RESPONSABLE: 'Abogado', ACCIONANTE: 'Accionante', ACCIONADOS: 'Accionados',
  VINCULADOS: 'Vinculados', DERECHO_VULNERADO: 'Derecho', JUZGADO: 'Juzgado',
  CIUDAD: 'Ciudad', FECHA_INGRESO: 'Fecha ingreso', ASUNTO: 'Asunto',
  PRETENSIONES: 'Pretensiones', OFICINA_RESPONSABLE: 'Oficina',
  SENTIDO_FALLO: 'Fallo', FECHA_FALLO: 'Fecha fallo',
  IMPUGNACION: 'Impugnacion', OBSERVACIONES: 'Observaciones',
}
const humanizeField = (f: string) => FIELD_LABELS[f] || f.replace(/_/g, ' ').toLowerCase()

interface ExtractionResult {
  case_id: number; folder_name: string; status: 'success' | 'error' | 'partial'; fields_extracted: number; message?: string
}

interface ReviewCase {
  case_id: number; id?: number; folder_name: string; accionante?: string; ACCIONANTE?: string
  low_confidence_fields: string[]; empty_fields: string[]; document_count: number
  completitud?: number; missing_fields?: string[]
}

export default function Extraction() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [selectedCaseId, setSelectedCaseId] = useState<number | ''>('')
  const [caseSearch, setCaseSearch] = useState('')
  const [showCaseDropdown, setShowCaseDropdown] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const [batchSize, setBatchSize] = useState<number>(5)
  const [extractionMode, setExtractionMode] = useState<'single' | 'agent'>('single')
  const [classifyDocs, setClassifyDocs] = useState(false)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) setShowCaseDropdown(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const [results, setResults] = useState<ExtractionResult[]>([])
  const [showResults, setShowResults] = useState(false)

  const reviewQ = useQuery({ queryKey: ['review-queue'], queryFn: getReviewQueue })
  const mismatchedQ = useQuery({ queryKey: ['mismatched-docs'], queryFn: getMismatchedDocs })
  const suspiciousQ = useQuery({ queryKey: ['suspicious-docs'], queryFn: getSuspiciousDocs })

  const verifyAllMut = useMutation({
    mutationFn: verifyAllDocs,
    onSuccess: (data) => { toast.success(`Verificados: ${data.total} docs (${data.sospechoso || 0} sospechosos)`); qc.invalidateQueries({ queryKey: ['suspicious-docs'] }) },
    onError: () => toast.error('Error al verificar'),
  })

  const markOkMut = useMutation({
    mutationFn: markDocOk,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['suspicious-docs'] }); toast.success('Marcado como OK') },
  })

  const syncStatusQ = useQuery({ queryKey: ['sync-status-ext'], queryFn: getSyncStatus, refetchInterval: 2000 })
  const isSyncing = syncStatusQ.data?.in_progress ?? false

  const syncMut = useMutation({
    mutationFn: syncFolders,
    onSuccess: (data) => { if (data.status === 'started') toast.success('Sincronizacion iniciada'); qc.invalidateQueries({ queryKey: ['review-queue'] }); qc.invalidateQueries({ queryKey: ['cases-all'] }) },
    onError: () => toast.error('Error al sincronizar'),
  })

  const allCasesQ = useQuery({ queryKey: ['cases-all'], queryFn: () => getCases({ page: 1, per_page: 500 }) })

  const batchMutation = useMutation({
    mutationFn: (caseIds?: number[]) => extractBatch(caseIds, classifyDocs),
    onSuccess: (data) => {
      if (data.status === 'started') toast.success(data.message)
      else if (data.status === 'running') toast('Ya hay una extraccion en progreso', { icon: '\u2139\uFE0F' })
      else if (data.status === 'empty') toast('No hay casos pendientes', { icon: '\u2139\uFE0F' })
    },
    onError: () => toast.error('Error al iniciar extraccion'),
  })

  const [singleResult, setSingleResult] = useState<any>(null)

  const handleExtractionSuccess = (data: any) => {
    if (data.status === 'completed') {
      const mode = data.reasoning ? 'Agent' : 'Pipeline'
      const classified = data.classification?.docs_movidos > 0 ? ` | ${data.classification.docs_movidos} docs movidos` : ''
      toast.success(`${mode}: ${data.fields_extracted} campos en ${data.elapsed_seconds}s${classified}`)
      setResults(prev => [...prev, { case_id: data.case_id, folder_name: data.folder_name, status: 'success', fields_extracted: data.fields_extracted, message: `${data.documents_processed || data.fields_extracted} campos | ${data.elapsed_seconds}s | ${data.tokens?.provider || ''}/${data.tokens?.model || ''}${classified}` }])
      setShowResults(true); setSingleResult(data)
      qc.invalidateQueries({ queryKey: ['cases'] }); qc.invalidateQueries({ queryKey: ['cases-table'] }); qc.invalidateQueries({ queryKey: ['kpis'] }); qc.invalidateQueries({ queryKey: ['review-queue'] })
    } else if (data.status === 'running') toast('Ya hay una extraccion en progreso', { icon: '\u2139\uFE0F' })
    else if (data.status === 'error') toast.error(data.message || 'Error en extraccion')
  }

  const singleMutation = useMutation({ mutationFn: (id: number) => extractSingle(id), onSuccess: handleExtractionSuccess, onError: () => toast.error('Error al iniciar extraccion') })
  const agentMutation = useMutation({ mutationFn: ({ id, classify }: { id: number; classify: boolean }) => agentExtract(id, classify), onSuccess: handleExtractionSuccess, onError: () => toast.error('Error al iniciar extraccion con agente') })
  const dismissOneMut = useMutation({ mutationFn: dismissMismatchedDoc, onSuccess: () => { qc.invalidateQueries({ queryKey: ['mismatched-docs'] }); toast.success('Alerta resuelta') } })
  const dismissAllMut = useMutation({ mutationFn: dismissAllMismatchedDocs, onSuccess: (data) => { qc.invalidateQueries({ queryKey: ['mismatched-docs'] }); toast.success(data.message) } })

  const [auditResult, setAuditResult] = useState<Record<string, unknown> | null>(null)
  const auditMut = useMutation({
    mutationFn: runFullAudit,
    onSuccess: (data) => { setAuditResult(data); qc.invalidateQueries({ queryKey: ['suspicious-docs'] }); qc.invalidateQueries({ queryKey: ['review-queue'] }); qc.invalidateQueries({ queryKey: ['cases'] }) },
    onError: () => toast.error('Error al ejecutar auditoria'),
  })

  const isLoading = batchMutation.isPending || singleMutation.isPending || agentMutation.isPending
  const reviewQueue: ReviewCase[] = reviewQ.data ?? []
  const allCases = allCasesQ.data?.items ?? []

  function statusIcon(status: string) {
    if (status === 'success') return <CheckCircle size={14} className="text-emerald-500" />
    if (status === 'error') return <XCircle size={14} className="text-destructive" />
    return <Clock size={14} className="text-amber-500" />
  }

  return (
    <PageShell>
      <PageHeader
        title="Extraccion"
        subtitle="Extraccion automatica de campos desde documentos PDF y DOCX usando IA"
        icon={Cpu}
        action={
          <TooltipProvider delay={200}>
            <div className="flex gap-2">
              <Tooltip>
                <TooltipTrigger render={<div className="inline-flex" />}>
                  <Button
                    variant="outline"
                    onClick={() => {
                      // U4: warning antes de accion destructiva
                      const msg = 'Auditoria general verifica integridad completa:\n\n'
                        + '• Compara disco ↔ base de datos\n'
                        + '• Identifica documentos sospechosos\n'
                        + '• Detecta carpetas vacias y sin accionante\n'
                        + '• Limpia documentos fantasma (REGISTROS de DB sin archivo en disco)\n\n'
                        + 'Tarda 30-60 segundos. ¿Continuar?'
                      if (window.confirm(msg)) auditMut.mutate()
                    }}
                    disabled={auditMut.isPending}
                    className="text-amber-700 border-amber-200 hover:bg-amber-50"
                  >
                    {auditMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <ClipboardCheck size={14} />}
                    {auditMut.isPending ? 'Auditando...' : 'Auditoria'}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs max-w-xs">Verifica integridad disco ↔ DB, detecta problemas y limpia registros fantasma.</p>
                </TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger render={<div className="inline-flex" />}>
                  <Button onClick={() => syncMut.mutate()} disabled={isSyncing}>
                    {isSyncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                    {isSyncing ? 'Sincronizando...' : 'Sincronizar Carpetas'}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs max-w-xs">Registra en la DB las carpetas que estan en disco pero no en la base. No mueve archivos.</p>
                </TooltipContent>
              </Tooltip>
            </div>
          </TooltipProvider>
        }
      />

      {/* Audit Results */}
      {auditResult && (
        <Card className="border-amber-200">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-amber-100 bg-amber-50 rounded-t-lg">
            <div className="flex items-center gap-2">
              <ClipboardCheck size={14} className="text-amber-600" />
              <span className="text-sm font-medium text-amber-700">
                Resultado de Auditoria
                {(auditResult.total_problemas as number) > 0 && <Badge variant="outline" className="ml-2 text-amber-700 border-amber-200 bg-amber-100">{auditResult.total_problemas as number} problemas</Badge>}
              </span>
            </div>
            <Button variant="ghost" size="icon-xs" onClick={() => setAuditResult(null)}><XCircle size={14} /></Button>
          </div>
          <CardContent className="pt-3">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
              {[
                { label: 'Carpetas en disco', value: auditResult.disco as number, color: 'bg-blue-50 text-blue-700' },
                { label: 'Docs sospechosos', value: (auditResult.verificacion as Record<string,number>)?.sospechoso ?? 0, color: (auditResult.verificacion as Record<string,number>)?.sospechoso > 0 ? 'bg-orange-50 text-orange-700' : 'bg-emerald-50 text-emerald-700' },
                { label: 'Docs verificados OK', value: (auditResult.verificacion as Record<string,number>)?.ok ?? 0, color: 'bg-emerald-50 text-emerald-700' },
                { label: 'Emails sin caso', value: auditResult.emails_sin_caso as number, color: (auditResult.emails_sin_caso as number) > 0 ? 'bg-red-50 text-red-700' : 'bg-emerald-50 text-emerald-700' },
                { label: 'Pendiente revision', value: (auditResult.pendientes as string[])?.length ?? 0, color: 'bg-muted text-foreground' },
                { label: 'Carpetas vacias', value: (auditResult.vacias as string[])?.length ?? 0, color: 'bg-muted text-foreground' },
                { label: 'Sin accionante', value: (auditResult.sin_accionante as unknown[])?.length ?? 0, color: 'bg-muted text-foreground' },
                { label: 'Fantasma limpiados', value: auditResult.docs_fantasma_limpiados as number, color: 'bg-muted text-foreground' },
              ].map(({ label, value, color }) => (
                <div key={label} className={cn('rounded-lg p-2.5', color)}>
                  <p className="font-bold text-lg">{value}</p>
                  <p className="opacity-70">{label}</p>
                </div>
              ))}
            </div>
            {((auditResult.vacias as string[])?.length > 0 || (auditResult.pendientes as string[])?.length > 0 || (auditResult.solo_disco as string[])?.length > 0) && (
              <div className="mt-3 text-xs space-y-1 text-muted-foreground">
                {(auditResult.vacias as string[])?.length > 0 && <div><span className="font-medium text-foreground">Carpetas vacias:</span> {(auditResult.vacias as string[]).join(', ')}</div>}
                {(auditResult.pendientes as string[])?.length > 0 && <div><span className="font-medium text-foreground">Pendiente revision:</span> {(auditResult.pendientes as string[]).join(', ')}</div>}
                {(auditResult.solo_disco as string[])?.length > 0 && <div><span className="font-medium text-foreground">En disco sin DB:</span> {(auditResult.solo_disco as string[]).join(', ')}</div>}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Action Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Batch */}
        <Card>
          <CardContent className="pt-4 space-y-3">
            <div className="flex items-start gap-3">
              <div className="p-2 bg-primary/10 rounded-lg"><Zap size={18} className="text-primary" /></div>
              <div>
                <h2 className="font-medium text-foreground text-sm">Extraccion por Lotes</h2>
                <p className="text-xs text-muted-foreground mt-0.5">Procesa todos los casos con campos incompletos</p>
              </div>
            </div>

            {reviewQ.data && reviewQueue.length > 0 && (
              <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                <p className="text-xs text-amber-700 font-medium">
                  {reviewQueue.length} caso(s) con campos incompletos o baja confianza
                </p>
                <p className="text-[10px] text-amber-600 mt-0.5">Requieren extraccion o revision manual</p>
              </div>
            )}

            <div>
              <label className="text-xs text-muted-foreground font-medium">Cantidad de casos:</label>
              <div className="flex gap-1.5 mt-1">
                {[5, 10, 25, 0].map(n => (
                  <Button key={n} variant={batchSize === n ? 'default' : 'outline'} size="xs" onClick={() => setBatchSize(n)}>
                    {n === 0 ? 'Todos' : n}
                  </Button>
                ))}
              </div>
            </div>

            <TooltipProvider delay={200}>
              <Tooltip>
                <TooltipTrigger render={<div className="inline-flex" />}>
                  <label className="flex items-center gap-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg cursor-pointer hover:bg-amber-100 transition-colors">
                    <input
                      type="checkbox"
                      checked={classifyDocs}
                      onChange={(e) => {
                        // U3: warning al activar accion destructiva
                        if (e.target.checked) {
                          const ok = window.confirm(
                            '¿Activar clasificacion de documentos?\n\n'
                            + 'Esta opcion MUEVE archivos fisicos entre carpetas cuando el sistema '
                            + 'detecta que un documento pertenece a otro caso.\n\n'
                            + 'Los cambios son dificiles de revertir. Se recomienda hacer backup antes.'
                          )
                          if (!ok) return
                        }
                        setClassifyDocs(e.target.checked)
                      }}
                      className="rounded border-amber-300 text-amber-600 focus:ring-amber-500"
                    />
                    <FolderCheck size={14} className="text-amber-600" />
                    <span className="text-xs text-amber-800">
                      Clasificar documentos <span className="text-[10px] opacity-75">(MUEVE archivos fisicos)</span>
                    </span>
                  </label>
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs max-w-xs">
                    Verifica cada documento contra los datos del caso y MUEVE los que no pertenecen al caso correcto.
                    Accion destructiva — requiere backup previo.
                  </p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>

            <Button
              onClick={() => {
                if (batchSize === 0) { batchMutation.mutate(undefined) }
                else {
                  const pendingIds = (allCases.filter((c: { processing_status: string }) => c.processing_status === 'PENDIENTE' || c.processing_status === 'REVISION') as { id: number }[]).slice(0, batchSize).map(c => c.id)
                  if (pendingIds.length > 0) batchMutation.mutate(pendingIds)
                  else toast('No hay casos pendientes', { icon: 'i' })
                }
              }}
              disabled={isLoading}
              className="w-full"
              size="lg"
            >
              {batchMutation.isPending ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />}
              {batchMutation.isPending ? 'Extrayendo...' : `Extraer Pendientes${classifyDocs ? ' + Clasificar' : ''} (3 en paralelo)`}
            </Button>
          </CardContent>
        </Card>

        {/* Single / Agent */}
        <Card>
          <CardContent className="pt-4 space-y-3">
            <div className="flex items-start gap-3">
              <div className={cn('p-2 rounded-lg', extractionMode === 'agent' ? 'bg-emerald-50' : 'bg-primary/10')}>
                {extractionMode === 'agent' ? <Brain size={18} className="text-emerald-600" /> : <Cpu size={18} className="text-primary" />}
              </div>
              <div>
                <h2 className="font-medium text-foreground text-sm">Extraccion Individual</h2>
                <p className="text-xs text-muted-foreground mt-0.5">Extrae campos de un caso especifico</p>
              </div>
            </div>

            <div>
              <label className="text-xs text-muted-foreground font-medium">Metodo de extraccion:</label>
              <div className="flex gap-1.5 mt-1">
                <Button variant={extractionMode === 'single' ? 'default' : 'outline'} size="sm" className="flex-1" onClick={() => setExtractionMode('single')}>
                  <Cpu size={13} /> Estandar
                </Button>
                <Button
                  variant={extractionMode === 'agent' ? 'default' : 'outline'}
                  size="sm"
                  className={cn('flex-1', extractionMode === 'agent' && 'bg-emerald-600 hover:bg-emerald-700')}
                  onClick={() => setExtractionMode('agent')}
                >
                  <Brain size={13} /> Avanzado
                </Button>
              </div>
              <p className="text-[10px] text-muted-foreground mt-1">
                {extractionMode === 'single' ? 'Extraccion rapida de campos desde los documentos' : 'Extraccion avanzada con mayor precision y validacion cruzada'}
              </p>
            </div>

            {extractionMode === 'agent' && (
              <label className="flex items-center gap-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg cursor-pointer hover:bg-amber-100 transition-colors">
                <input type="checkbox" checked={classifyDocs} onChange={(e) => setClassifyDocs(e.target.checked)} className="rounded border-amber-300 text-amber-600 focus:ring-amber-500" />
                <FolderCheck size={14} className="text-amber-600" />
                <span className="text-xs text-amber-800">Clasificar documentos (mover los que no pertenecen)</span>
              </label>
            )}

            <div className="relative" ref={dropdownRef}>
              <Input
                placeholder="Buscar caso por nombre, radicado..."
                value={caseSearch}
                onChange={(e) => { setCaseSearch(e.target.value); setShowCaseDropdown(true); if (!e.target.value) setSelectedCaseId('') }}
                onFocus={() => setShowCaseDropdown(true)}
              />
              {selectedCaseId && (
                <button onClick={() => { setSelectedCaseId(''); setCaseSearch(''); setShowCaseDropdown(false) }} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-xs">&times;</button>
              )}
              {showCaseDropdown && caseSearch.length >= 1 && (
                <div className="absolute z-20 w-full mt-1 bg-card border border-border rounded-lg shadow-lg max-h-56 overflow-y-auto">
                  {allCases.filter((c: { folder_name: string; CIUDAD?: string; ACCIONANTE?: string }) => {
                    const term = caseSearch.toLowerCase()
                    return (c.folder_name || '').toLowerCase().includes(term) || (c.CIUDAD || '').toLowerCase().includes(term) || (c.ACCIONANTE || '').toLowerCase().includes(term)
                  }).slice(0, 20).map((c: { id: number; folder_name: string; CIUDAD?: string }) => (
                    <button key={c.id} onClick={() => { setSelectedCaseId(c.id); setCaseSearch(c.folder_name + (c.CIUDAD ? ` (${c.CIUDAD})` : '')); setShowCaseDropdown(false) }}
                      className={cn('w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors', selectedCaseId === c.id && 'bg-primary/5 text-primary font-medium')}>
                      <span className="font-mono text-xs text-muted-foreground">{c.folder_name}</span>
                      {c.CIUDAD && <span className="text-[10px] text-muted-foreground ml-1">({c.CIUDAD})</span>}
                    </button>
                  ))}
                  {allCases.filter((c: { folder_name: string; CIUDAD?: string; ACCIONANTE?: string }) => {
                    const term = caseSearch.toLowerCase()
                    return (c.folder_name || '').toLowerCase().includes(term) || (c.CIUDAD || '').toLowerCase().includes(term) || (c.ACCIONANTE || '').toLowerCase().includes(term)
                  }).length === 0 && <div className="px-3 py-3 text-xs text-muted-foreground text-center">Sin resultados</div>}
                </div>
              )}
            </div>

            <Button
              onClick={() => {
                if (!selectedCaseId) return
                if (extractionMode === 'agent') agentMutation.mutate({ id: selectedCaseId as number, classify: classifyDocs })
                else singleMutation.mutate(selectedCaseId as number)
              }}
              disabled={isLoading || !selectedCaseId}
              className={cn('w-full', extractionMode === 'agent' && 'bg-emerald-600 hover:bg-emerald-700')}
              size="lg"
            >
              {(singleMutation.isPending || agentMutation.isPending) ? <Loader2 size={15} className="animate-spin" /> : extractionMode === 'agent' ? <Brain size={15} /> : <Play size={15} />}
              {(singleMutation.isPending || agentMutation.isPending) ? 'Extrayendo...' : extractionMode === 'agent' ? `Extraer con Agente${classifyDocs ? ' + Clasificar' : ''}` : 'Extraer Caso Individual'}
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Results */}
      {showResults && results.length > 0 && (
        <Card>
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-muted/50 rounded-t-lg">
            <span className="text-sm font-medium">Resultados de Extraccion ({results.length})</span>
            <button onClick={() => setShowResults(false)} className="text-xs text-muted-foreground hover:text-foreground">Cerrar</button>
          </div>
          <CardContent className="p-0 max-h-80 overflow-y-auto">
            <div className="divide-y divide-border">
              {results.map((r, i) => (
                <div key={i} className={cn('flex items-center gap-3 px-4 py-2.5 border-l-4', r.status === 'success' ? 'border-l-emerald-500 bg-emerald-50/50' : r.status === 'error' ? 'border-l-red-500 bg-red-50/50' : 'border-l-amber-500 bg-amber-50/50')}>
                  {statusIcon(r.status)}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{r.folder_name}</p>
                    {r.message && <p className="text-xs text-muted-foreground truncate">{r.message}</p>}
                  </div>
                  <Badge variant="secondary" className="text-xs">{r.fields_extracted} campos</Badge>
                  <Button variant="ghost" size="icon-xs" onClick={() => navigate(`/cases/${r.case_id}`)}><ChevronRight size={14} /></Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Detailed Single Result */}
      {singleResult && singleResult.status === 'completed' && (
        <Card className="border-emerald-200">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-emerald-100 bg-emerald-50 rounded-t-lg">
            <span className="text-sm font-medium text-emerald-800">Resultado Detallado: {singleResult.folder_name}</span>
            <button onClick={() => setSingleResult(null)} className="text-xs text-muted-foreground hover:text-foreground">Cerrar</button>
          </div>
          <CardContent className="pt-4 space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              {[
                { label: 'Campos', value: singleResult.fields_extracted, color: 'bg-blue-50 text-blue-700' },
                { label: 'Docs procesados', value: singleResult.documents_processed, color: 'bg-emerald-50 text-emerald-700' },
                { label: 'Docs excluidos', value: singleResult.documents_excluded, color: 'bg-amber-50 text-amber-700' },
                { label: 'Tiempo', value: `${singleResult.elapsed_seconds}s`, color: 'bg-blue-50 text-primary' },
                { label: `${singleResult.tokens?.provider}/${singleResult.tokens?.model}`, value: `$${singleResult.tokens?.cost || '0'}`, color: 'bg-muted text-foreground' },
              ].map(({ label, value, color }) => (
                <div key={label} className={cn('text-center p-2 rounded-lg', color)}>
                  <p className="text-lg font-bold">{value}</p>
                  <p className="text-[10px] opacity-70">{label}</p>
                </div>
              ))}
            </div>

            {singleResult.tokens && <p className="text-xs text-muted-foreground">Tokens: {singleResult.tokens.input?.toLocaleString()} input + {singleResult.tokens.output?.toLocaleString()} output</p>}

            <div>
              <p className="text-xs font-medium text-foreground mb-2">Campos extraidos:</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-1">
                {Object.entries(singleResult.fields || {}).map(([key, val]) => (
                  <div key={key} className="flex items-start gap-2 text-xs">
                    <span className="font-mono text-muted-foreground w-32 flex-shrink-0 truncate">{key}</span>
                    <span className="text-foreground truncate">{String(val).substring(0, 60)}</span>
                  </div>
                ))}
              </div>
            </div>

            {singleResult.classification && (
              <div className={cn('rounded-lg p-3 border', singleResult.classification.docs_movidos > 0 ? 'bg-amber-50 border-amber-200' : 'bg-emerald-50 border-emerald-200')}>
                <p className={cn('text-xs font-medium mb-1', singleResult.classification.docs_movidos > 0 ? 'text-amber-800' : 'text-emerald-800')}>Clasificacion de documentos:</p>
                <p className="text-xs text-muted-foreground">{singleResult.classification.docs_ok} OK / {singleResult.classification.docs_total} total
                  {singleResult.classification.docs_movidos > 0 && <span className="text-amber-700 font-medium"> — {singleResult.classification.docs_movidos} movidos a PENDIENTE DE UBICACION</span>}</p>
                {singleResult.classification.docs_movidos_list?.map((f: string, i: number) => <p key={i} className="text-[10px] text-amber-600 ml-2">- {f}</p>)}
                {singleResult.classification.classification_error && <p className="text-[10px] text-muted-foreground mt-1">{singleResult.classification.classification_error}</p>}
              </div>
            )}

            {singleResult.confidence_avg > 0 && (
              <div className="text-xs text-muted-foreground bg-muted rounded-lg p-2 border border-border">
                Confianza promedio: <span className={cn('font-bold', singleResult.confidence_avg >= 70 ? 'text-emerald-600' : singleResult.confidence_avg >= 40 ? 'text-amber-600' : 'text-destructive')}>{singleResult.confidence_avg}%</span>
                {singleResult.warnings?.length > 0 && <span className="text-amber-600 ml-2">| {singleResult.warnings.length} advertencias</span>}
              </div>
            )}

            {singleResult.reasoning?.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-emerald-700 font-medium hover:underline">Razonamiento del agente ({singleResult.reasoning.length} campos)</summary>
                <div className="mt-2 space-y-1 max-h-48 overflow-y-auto">
                  {singleResult.reasoning.map((r: any, i: number) => (
                    <div key={i} className="bg-emerald-50 rounded p-2 border border-emerald-100">
                      <span className="font-mono text-emerald-800">{r.campo || r.field_name}</span>
                      <span className="text-muted-foreground ml-1">= {r.valor || r.value}</span>
                      <span className={cn('ml-2 text-[10px]', (r.confianza || r.confidence) >= 70 ? 'text-emerald-600' : 'text-amber-600')}>({r.confianza || r.confidence}%)</span>
                      {(r.razonamiento || r.reasoning) && <p className="text-[10px] text-muted-foreground mt-0.5">{r.razonamiento || r.reasoning}</p>}
                    </div>
                  ))}
                </div>
              </details>
            )}

            {singleResult.reassigned_docs?.length > 0 && (
              <div className="bg-amber-50 rounded-lg p-3 border border-amber-200">
                <p className="text-xs font-medium text-amber-800 mb-1">Documentos reasignados automaticamente:</p>
                {singleResult.reassigned_docs.map((d: any, i: number) => <p key={i} className="text-xs text-amber-700">{d.filename}: {d.from_case} → {d.to_case} ({d.reason})</p>)}
              </div>
            )}
            {singleResult.cases_created?.length > 0 && (
              <div className="bg-blue-50 rounded-lg p-3 border border-blue-200">
                <p className="text-xs font-medium text-blue-800 mb-1">Casos nuevos creados automaticamente:</p>
                {singleResult.cases_created.map((c: any, i: number) => <p key={i} className="text-xs text-blue-700">{c.folder_name} (ID {c.case_id}) — desde doc: {c.from_doc}</p>)}
              </div>
            )}
            {singleResult.corrections_injected > 0 && <div className="text-xs text-primary bg-primary/5 rounded-lg p-2 border border-primary/20">{singleResult.corrections_injected} correcciones historicas inyectadas como aprendizaje</div>}
            {singleResult.suspicious_docs?.length > 0 && (
              <div className="bg-red-50 rounded-lg p-3 border border-red-200">
                <p className="text-xs font-medium text-red-800 mb-1">Documentos sospechosos:</p>
                {singleResult.suspicious_docs.map((d: any, i: number) => <p key={i} className="text-xs text-red-700">[{d.status}] {d.filename}: {d.detail}</p>)}
              </div>
            )}
            <button onClick={() => navigate(`/cases/${singleResult.case_id}`)} className="text-xs text-primary hover:underline">Ver detalle del caso →</button>
          </CardContent>
        </Card>
      )}

      {/* Mismatched Documents */}
      {(mismatchedQ.data ?? []).length > 0 && (
        <Card className="border-red-200">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-red-100 bg-red-50 rounded-t-lg">
            <div className="flex items-center gap-2">
              <ShieldAlert size={14} className="text-red-500" />
              <span className="text-sm font-medium text-red-700">Documentos que NO corresponden al caso</span>
              <Badge variant="destructive" className="text-[10px]">{(mismatchedQ.data ?? []).length}</Badge>
            </div>
            <Button variant="ghost" size="xs" onClick={() => dismissAllMut.mutate()} disabled={dismissAllMut.isPending} className="text-red-600 hover:text-red-800">
              <Trash2 size={12} /> Resolver todas
            </Button>
          </div>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow className="bg-red-50/50">
                  <TableHead className="text-red-600">Caso</TableHead>
                  <TableHead className="text-red-600">Documento</TableHead>
                  <TableHead className="text-red-600">Radicado encontrado</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(mismatchedQ.data ?? []).map((m: any, i: number) => (
                  <TableRow key={i}>
                    <TableCell><span className="font-mono text-xs">{m.case_name}</span></TableCell>
                    <TableCell className="text-xs text-muted-foreground">{m.filename}</TableCell>
                    <TableCell><Badge variant="destructive" className="font-mono text-[10px]">{m.radicado_encontrado}</Badge></TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="xs" onClick={() => dismissOneMut.mutate(m.id)} disabled={dismissOneMut.isPending} className="text-destructive">Resolver</Button>
                        <Button variant="ghost" size="icon-xs" onClick={() => navigate(`/cases/${m.case_id}`)}><ChevronRight size={14} /></Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* Suspicious Documents */}
      {(suspiciousQ.data ?? []).length > 0 && (() => {
        const allDocs = suspiciousQ.data ?? []
        const noPertenece = allDocs.filter((d: any) => d.verificacion === 'NO_PERTENECE')
        const sospechosos = allDocs.filter((d: any) => d.verificacion === 'SOSPECHOSO')
        return (
          <>
            {noPertenece.length > 0 && (
              <Card className="border-red-200">
                <div className="flex items-center justify-between px-4 py-2.5 border-b border-red-100 bg-red-50 rounded-t-lg">
                  <div className="flex items-center gap-2">
                    <ShieldAlert size={14} className="text-red-500" />
                    <span className="text-sm font-medium text-red-700">Documentos que NO Pertenecen</span>
                    <Badge variant="destructive" className="text-[10px]">{noPertenece.length}</Badge>
                  </div>
                  <Button variant="ghost" size="xs" onClick={() => verifyAllMut.mutate()} disabled={verifyAllMut.isPending} className="text-red-600">
                    <SearchIcon size={12} /> {verifyAllMut.isPending ? 'Verificando...' : 'Re-verificar'}
                  </Button>
                </div>
                <CardContent className="p-0 max-h-72 overflow-y-auto">
                  <Table>
                    <TableHeader><TableRow className="bg-red-50/50 sticky top-0"><TableHead className="text-red-600">Carpeta</TableHead><TableHead className="text-red-600">Documento</TableHead><TableHead className="text-red-600">Detalle</TableHead><TableHead /></TableRow></TableHeader>
                    <TableBody>
                      {noPertenece.map((d: any) => (
                        <TableRow key={d.doc_id}>
                          <TableCell><span className="font-mono text-xs">{d.case_name?.substring(0, 35)}</span></TableCell>
                          <TableCell className="text-xs text-muted-foreground">{d.filename?.substring(0, 35)}</TableCell>
                          <TableCell className="text-xs text-red-600">{d.detalle?.substring(0, 60)}</TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Button variant="ghost" size="xs" onClick={() => markOkMut.mutate(d.doc_id)} disabled={markOkMut.isPending} className="text-emerald-600">OK</Button>
                              <Button variant="destructive" size="xs" onClick={() => navigate(`/cases/${d.case_id}`)}>Resolver</Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            )}
            {sospechosos.length > 0 && (
              <Card className="border-orange-200">
                <div className="flex items-center justify-between px-4 py-2.5 border-b border-orange-100 bg-orange-50 rounded-t-lg">
                  <div className="flex items-center gap-2">
                    <FileWarning size={14} className="text-orange-500" />
                    <span className="text-sm font-medium text-orange-700">Documentos Sospechosos</span>
                    <Badge variant="outline" className="text-[10px] text-orange-700 border-orange-200 bg-orange-100">{sospechosos.length}</Badge>
                  </div>
                </div>
                <CardContent className="p-0 max-h-72 overflow-y-auto">
                  <Table>
                    <TableHeader><TableRow className="bg-orange-50/50 sticky top-0"><TableHead className="text-orange-600">Carpeta</TableHead><TableHead className="text-orange-600">Documento</TableHead><TableHead className="text-orange-600">Detalle</TableHead><TableHead /></TableRow></TableHeader>
                    <TableBody>
                      {sospechosos.map((d: any) => (
                        <TableRow key={d.doc_id}>
                          <TableCell><span className="font-mono text-xs">{d.case_name?.substring(0, 35)}</span></TableCell>
                          <TableCell className="text-xs text-muted-foreground">{d.filename?.substring(0, 35)}</TableCell>
                          <TableCell className="text-xs text-orange-600">{d.detalle?.substring(0, 50)}</TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Button variant="ghost" size="xs" onClick={() => markOkMut.mutate(d.doc_id)} disabled={markOkMut.isPending} className="text-emerald-600">OK</Button>
                              <Button variant="ghost" size="icon-xs" onClick={() => navigate(`/cases/${d.case_id}`)}><ChevronRight size={14} /></Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            )}
          </>
        )
      })()}

      {/* Review Queue */}
      <Card>
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-border bg-muted/50 rounded-t-lg">
          <div className="flex items-center gap-2">
            <AlertCircle size={14} className={reviewQueue.length > 0 ? 'text-amber-500' : 'text-emerald-400'} />
            <span className="text-sm font-medium">Cola de Revision</span>
            {reviewQueue.length > 0 && <Badge variant="outline" className="text-amber-700 border-amber-200 bg-amber-100 text-[10px]">{reviewQueue.length}</Badge>}
          </div>
          {reviewQueue.length > 0 && (
            <Button variant="ghost" size="icon-xs" onClick={() => qc.invalidateQueries({ queryKey: ['review-queue'] })}>
              <RefreshCw size={13} className={reviewQ.isFetching ? 'animate-spin' : ''} />
            </Button>
          )}
        </div>
        <CardContent className="p-0">
          {reviewQ.isLoading ? (
            <div className="flex items-center justify-center py-8"><Loader2 size={24} className="animate-spin text-primary" /></div>
          ) : reviewQueue.length === 0 ? (
            <div className="text-center py-10"><CheckCircle size={32} className="mx-auto text-emerald-400 mb-2" /><p className="text-sm text-muted-foreground">Todos los casos estan completos</p></div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Caso</TableHead>
                  <TableHead>Accionante</TableHead>
                  <TableHead>Completitud</TableHead>
                  <TableHead className="hidden lg:table-cell">Campos Faltantes</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {reviewQueue.map((c) => (
                  <TableRow key={c.case_id}>
                    <TableCell>
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-xs text-primary font-medium">{c.folder_name}</span>
                        {(c as any).docs_no_pertenece > 0 && <Badge variant="destructive" className="text-[10px]">{(c as any).docs_no_pertenece}</Badge>}
                        {(c as any).docs_sospechosos > 0 && <Badge variant="outline" className="text-[10px] text-amber-700 border-amber-200 bg-amber-50">{(c as any).docs_sospechosos}</Badge>}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs">{c.accionante || c.ACCIONANTE || '\u2014'}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Progress value={Math.max(0, c.completitud ?? (100 - (c.empty_fields?.length ?? 0) / Math.max(c.empty_fields?.length ?? 28, 28) * 100))} className="h-1.5 w-20" />
                        <span className="text-xs text-muted-foreground">{Math.max(0, Math.round(c.completitud ?? (100 - (c.empty_fields?.length ?? 0) / Math.max(c.empty_fields?.length ?? 28, 28) * 100)))}%</span>
                      </div>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell">
                      <div className="flex flex-wrap gap-1">
                        {(c.empty_fields ?? c.missing_fields ?? []).slice(0, 4).map((f) => (
                          <Badge key={f} variant="outline" className="text-[10px] text-destructive border-red-200 bg-red-50">{humanizeField(f)}</Badge>
                        ))}
                        {(c.empty_fields ?? c.missing_fields ?? []).length > 4 && <span className="text-xs text-muted-foreground">+{(c.missing_fields ?? []).length - 4} mas</span>}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="xs" onClick={() => { const id = c.case_id || (c as unknown as {id: number}).id; if (id) singleMutation.mutate(id); else toast.error('ID de caso no encontrado') }} disabled={isLoading} className="text-primary">Extraer</Button>
                        <Button variant="ghost" size="icon-xs" onClick={() => navigate(`/cases/${c.case_id}`)}><ChevronRight size={14} /></Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </PageShell>
  )
}
