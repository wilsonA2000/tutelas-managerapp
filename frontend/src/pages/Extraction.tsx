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

interface ExtractionResult {
  case_id: number
  folder_name: string
  status: 'success' | 'error' | 'partial'
  fields_extracted: number
  message?: string
}

interface ReviewCase {
  case_id: number
  id?: number
  folder_name: string
  accionante?: string
  ACCIONANTE?: string
  low_confidence_fields: string[]
  empty_fields: string[]
  document_count: number
  completitud?: number
  missing_fields?: string[]
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
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowCaseDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])
  const [results, setResults] = useState<ExtractionResult[]>([])
  const [showResults, setShowResults] = useState(false)

  const reviewQ = useQuery({
    queryKey: ['review-queue'],
    queryFn: getReviewQueue,
  })

  const mismatchedQ = useQuery({
    queryKey: ['mismatched-docs'],
    queryFn: getMismatchedDocs,
  })

  const suspiciousQ = useQuery({
    queryKey: ['suspicious-docs'],
    queryFn: getSuspiciousDocs,
  })

  const verifyAllMut = useMutation({
    mutationFn: verifyAllDocs,
    onSuccess: (data) => {
      toast.success(`Verificados: ${data.total} docs (${data.sospechoso || 0} sospechosos)`)
      qc.invalidateQueries({ queryKey: ['suspicious-docs'] })
    },
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
    onSuccess: (data) => {
      if (data.status === 'started') toast.success('Sincronizacion iniciada')
      qc.invalidateQueries({ queryKey: ['review-queue'] })
      qc.invalidateQueries({ queryKey: ['cases-all'] })
    },
    onError: () => toast.error('Error al sincronizar'),
  })

  const allCasesQ = useQuery({
    queryKey: ['cases-all'],
    queryFn: () => getCases({ page: 1, per_page: 500 }),
  })

  const batchMutation = useMutation({
    mutationFn: extractBatch,
    onSuccess: (data) => {
      if (data.status === 'started') toast.success(data.message)
      else if (data.status === 'running') toast('Ya hay una extraccion en progreso', { icon: 'ℹ️' })
      else if (data.status === 'empty') toast('No hay casos pendientes', { icon: 'ℹ️' })
    },
    onError: () => toast.error('Error al iniciar extraccion'),
  })

  const [singleResult, setSingleResult] = useState<any>(null)

  const handleExtractionSuccess = (data: any) => {
    if (data.status === 'completed') {
      const mode = data.reasoning ? 'Agent' : 'Pipeline'
      const classified = data.classification?.docs_movidos > 0
        ? ` | ${data.classification.docs_movidos} docs movidos`
        : ''
      toast.success(`${mode}: ${data.fields_extracted} campos en ${data.elapsed_seconds}s${classified}`)
      setResults(prev => [...prev, {
        case_id: data.case_id,
        folder_name: data.folder_name,
        status: 'success',
        fields_extracted: data.fields_extracted,
        message: `${data.documents_processed || data.fields_extracted} campos | ${data.elapsed_seconds}s | ${data.tokens?.provider || ''}/${data.tokens?.model || ''}${classified}`,
      }])
      setShowResults(true)
      setSingleResult(data)
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['cases-table'] })
      qc.invalidateQueries({ queryKey: ['kpis'] })
      qc.invalidateQueries({ queryKey: ['review-queue'] })
    } else if (data.status === 'running') {
      toast('Ya hay una extraccion en progreso', { icon: 'ℹ️' })
    } else if (data.status === 'error') {
      toast.error(data.message || 'Error en extraccion')
    }
  }

  const singleMutation = useMutation({
    mutationFn: (id: number) => extractSingle(id),
    onSuccess: handleExtractionSuccess,
    onError: () => toast.error('Error al iniciar extraccion'),
  })

  const agentMutation = useMutation({
    mutationFn: ({ id, classify }: { id: number; classify: boolean }) => agentExtract(id, classify),
    onSuccess: handleExtractionSuccess,
    onError: () => toast.error('Error al iniciar extraccion con agente'),
  })

  const dismissOneMut = useMutation({
    mutationFn: dismissMismatchedDoc,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['mismatched-docs'] }); toast.success('Alerta resuelta') },
  })

  const dismissAllMut = useMutation({
    mutationFn: dismissAllMismatchedDocs,
    onSuccess: (data) => { qc.invalidateQueries({ queryKey: ['mismatched-docs'] }); toast.success(data.message) },
  })

  const [auditResult, setAuditResult] = useState<Record<string, unknown> | null>(null)

  const auditMut = useMutation({
    mutationFn: runFullAudit,
    onSuccess: (data) => {
      setAuditResult(data)
      qc.invalidateQueries({ queryKey: ['suspicious-docs'] })
      qc.invalidateQueries({ queryKey: ['review-queue'] })
      qc.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: () => toast.error('Error al ejecutar auditoría'),
  })

  const isLoading = batchMutation.isPending || singleMutation.isPending || agentMutation.isPending

  const reviewQueue: ReviewCase[] = reviewQ.data ?? []
  const allCases = allCasesQ.data?.items ?? []

  function statusIcon(status: string) {
    if (status === 'success') return <CheckCircle size={14} className="text-green-500" />
    if (status === 'error') return <XCircle size={14} className="text-red-500" />
    return <Clock size={14} className="text-amber-500" />
  }

  function statusBg(status: string) {
    if (status === 'success') return 'bg-green-50 border-green-200'
    if (status === 'error') return 'bg-red-50 border-red-200'
    return 'bg-amber-50 border-amber-200'
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Extraccion</h1>
          <p className="text-sm text-gray-500 mt-1">
            Extraccion automatica de campos desde documentos PDF y DOCX usando IA
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => auditMut.mutate()}
            disabled={auditMut.isPending}
            className="flex items-center gap-2 px-4 py-2.5 bg-amber-500 text-white text-sm font-medium rounded-lg hover:bg-amber-600 disabled:opacity-50 transition-colors shadow-sm"
          >
            {auditMut.isPending ? <Loader2 size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
            {auditMut.isPending ? 'Auditando...' : 'Auditoría'}
          </button>
          <button
            onClick={() => syncMut.mutate()}
            disabled={isSyncing}
            className="flex items-center gap-2 px-4 py-2.5 bg-[#1A5276] text-white text-sm font-medium rounded-lg hover:bg-[#154360] disabled:opacity-50 transition-colors shadow-sm"
          >
            {isSyncing ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            {isSyncing ? 'Sincronizando...' : 'Sincronizar Carpetas'}
          </button>
        </div>
      </div>

      {/* Audit Results Modal */}
      {auditResult && (
        <div className="bg-white rounded-xl border border-amber-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-amber-100 bg-amber-50">
            <div className="flex items-center gap-2">
              <ClipboardCheck size={15} className="text-amber-600" />
              <h2 className="text-sm font-semibold text-amber-700">
                Resultado de Auditoría
                {(auditResult.total_problemas as number) > 0 && (
                  <span className="ml-2 bg-amber-100 text-amber-700 text-xs px-2 py-0.5 rounded-full">{auditResult.total_problemas as number} problemas</span>
                )}
              </h2>
            </div>
            <button onClick={() => setAuditResult(null)} className="text-amber-400 hover:text-amber-600"><XCircle size={16} /></button>
          </div>
          <div className="p-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 text-xs">
            <div className="bg-blue-50 rounded-lg p-3">
              <p className="font-bold text-blue-700 text-lg">{auditResult.disco as number}</p>
              <p className="text-blue-500">Carpetas en disco</p>
            </div>
            <div className={(auditResult.verificacion as Record<string,number>)?.sospechoso > 0 ? 'bg-orange-50 rounded-lg p-3' : 'bg-green-50 rounded-lg p-3'}>
              <p className="font-bold text-lg" style={{color: (auditResult.verificacion as Record<string,number>)?.sospechoso > 0 ? '#c2410c' : '#15803d'}}>{(auditResult.verificacion as Record<string,number>)?.sospechoso ?? 0}</p>
              <p className="text-gray-500">Docs sospechosos</p>
            </div>
            <div className="bg-green-50 rounded-lg p-3">
              <p className="font-bold text-green-700 text-lg">{(auditResult.verificacion as Record<string,number>)?.ok ?? 0}</p>
              <p className="text-green-500">Docs verificados OK</p>
            </div>
            <div className={((auditResult.emails_sin_caso as number) > 0) ? 'bg-red-50 rounded-lg p-3' : 'bg-green-50 rounded-lg p-3'}>
              <p className="font-bold text-lg" style={{color: (auditResult.emails_sin_caso as number) > 0 ? '#dc2626' : '#15803d'}}>{auditResult.emails_sin_caso as number}</p>
              <p className="text-gray-500">Emails sin caso</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="font-bold text-gray-700 text-lg">{(auditResult.pendientes as string[])?.length ?? 0}</p>
              <p className="text-gray-500">Pendiente revisión</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="font-bold text-gray-700 text-lg">{(auditResult.vacias as string[])?.length ?? 0}</p>
              <p className="text-gray-500">Carpetas vacías</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="font-bold text-gray-700 text-lg">{(auditResult.sin_accionante as unknown[])?.length ?? 0}</p>
              <p className="text-gray-500">Sin accionante</p>
            </div>
            <div className="bg-gray-50 rounded-lg p-3">
              <p className="font-bold text-gray-700 text-lg">{auditResult.docs_fantasma_limpiados as number}</p>
              <p className="text-gray-500">Fantasma limpiados</p>
            </div>
          </div>
          {/* Detalles de problemas */}
          {((auditResult.vacias as string[])?.length > 0 || (auditResult.pendientes as string[])?.length > 0 || (auditResult.solo_disco as string[])?.length > 0) && (
            <div className="px-4 pb-4 text-xs space-y-2">
              {(auditResult.vacias as string[])?.length > 0 && (
                <div><span className="font-semibold text-gray-600">Carpetas vacías:</span> {(auditResult.vacias as string[]).join(', ')}</div>
              )}
              {(auditResult.pendientes as string[])?.length > 0 && (
                <div><span className="font-semibold text-gray-600">Pendiente revisión:</span> {(auditResult.pendientes as string[]).join(', ')}</div>
              )}
              {(auditResult.solo_disco as string[])?.length > 0 && (
                <div><span className="font-semibold text-gray-600">En disco sin DB:</span> {(auditResult.solo_disco as string[]).join(', ')}</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Action Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Batch */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <div className="flex items-start gap-3 mb-4">
            <div className="p-2.5 bg-[#1A5276]/10 rounded-lg">
              <Zap size={20} className="text-[#1A5276]" />
            </div>
            <div>
              <h2 className="font-semibold text-gray-800">Extraccion por Lotes</h2>
              <p className="text-xs text-gray-500 mt-1">
                Procesa todos los casos con campos incompletos automaticamente
              </p>
            </div>
          </div>

          {reviewQ.data && (
            <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              <p className="text-xs text-amber-700 font-medium">
                {reviewQueue.length} caso(s) pendientes de revision
              </p>
            </div>
          )}

          <div className="mb-3">
            <label className="text-xs text-gray-500 font-medium">Cantidad de casos:</label>
            <div className="flex gap-2 mt-1">
              {[5, 10, 25, 0].map(n => (
                <button key={n} onClick={() => setBatchSize(n)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                    batchSize === n ? 'bg-[#1A5276] text-white border-[#1A5276]' : 'bg-white text-gray-600 border-gray-300 hover:border-[#1A5276]'
                  }`}>
                  {n === 0 ? 'Todos' : n}
                </button>
              ))}
            </div>
          </div>

          <button
            onClick={() => {
              if (batchSize === 0) {
                batchMutation.mutate()
              } else {
                // Enviar solo los primeros N case_ids de los pendientes
                const pendingIds = (allCases.filter((c: { processing_status: string }) =>
                  c.processing_status === 'PENDIENTE' || c.processing_status === 'REVISION'
                ) as { id: number }[]).slice(0, batchSize).map(c => c.id)
                if (pendingIds.length > 0) {
                  batchMutation.mutate(pendingIds)
                } else {
                  toast('No hay casos pendientes', { icon: 'i' })
                }
              }
            }}
            disabled={isLoading}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-[#1A5276] text-white font-medium rounded-lg hover:bg-[#154360] disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
          >
            {batchMutation.isPending ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Play size={16} />
            )}
            {batchMutation.isPending ? 'Extrayendo...' : 'Extraer Todos los Pendientes'}
          </button>
        </div>

        {/* Single / Agent */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <div className="flex items-start gap-3 mb-4">
            <div className={`p-2.5 rounded-lg ${extractionMode === 'agent' ? 'bg-emerald-50' : 'bg-purple-50'}`}>
              {extractionMode === 'agent' ? <Brain size={20} className="text-emerald-600" /> : <Cpu size={20} className="text-purple-600" />}
            </div>
            <div>
              <h2 className="font-semibold text-gray-800">Extraccion Individual</h2>
              <p className="text-xs text-gray-500 mt-1">
                Extrae campos de un caso especifico
              </p>
            </div>
          </div>

          {/* Mode Selector */}
          <div className="mb-3">
            <label className="text-xs text-gray-500 font-medium">Metodo de extraccion:</label>
            <div className="flex gap-2 mt-1">
              <button
                onClick={() => setExtractionMode('single')}
                className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border transition-colors ${
                  extractionMode === 'single'
                    ? 'bg-purple-600 text-white border-purple-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-purple-400'
                }`}
              >
                <Cpu size={13} />
                Pipeline
              </button>
              <button
                onClick={() => setExtractionMode('agent')}
                className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border transition-colors ${
                  extractionMode === 'agent'
                    ? 'bg-emerald-600 text-white border-emerald-600'
                    : 'bg-white text-gray-600 border-gray-300 hover:border-emerald-400'
                }`}
              >
                <Brain size={13} />
                Agente IA
              </button>
            </div>
            <p className="text-[10px] text-gray-400 mt-1">
              {extractionMode === 'single'
                ? 'Pipeline directo: lee docs, llama IA, extrae campos'
                : 'Agente: regex + IA fusionados, razonamiento explicable, validacion cruzada'}
            </p>
          </div>

          {/* Classify Docs Option (only for agent) */}
          {extractionMode === 'agent' && (
            <label className="flex items-center gap-2 mb-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg cursor-pointer hover:bg-amber-100 transition-colors">
              <input
                type="checkbox"
                checked={classifyDocs}
                onChange={(e) => setClassifyDocs(e.target.checked)}
                className="rounded border-amber-300 text-amber-600 focus:ring-amber-500"
              />
              <FolderCheck size={14} className="text-amber-600" />
              <span className="text-xs text-amber-800">
                Clasificar documentos (mover los que no pertenecen)
              </span>
            </label>
          )}

          <div className="mb-4 relative" ref={dropdownRef}>
            <input
              type="text"
              placeholder="Buscar caso por nombre, radicado..."
              value={caseSearch}
              onChange={(e) => { setCaseSearch(e.target.value); setShowCaseDropdown(true); if (!e.target.value) setSelectedCaseId('') }}
              onFocus={() => setShowCaseDropdown(true)}
              className={`w-full text-sm border border-gray-300 rounded-lg px-3 py-2.5 bg-white focus:outline-none focus:ring-2 ${
                extractionMode === 'agent'
                  ? 'focus:border-emerald-500 focus:ring-emerald-500/20'
                  : 'focus:border-purple-500 focus:ring-purple-500/20'
              }`}
            />
            {selectedCaseId && (
              <button
                onClick={() => { setSelectedCaseId(''); setCaseSearch(''); setShowCaseDropdown(false) }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-xs"
              >
                &times;
              </button>
            )}
            {showCaseDropdown && caseSearch.length >= 1 && (
              <div className="absolute z-20 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-56 overflow-y-auto">
                {allCases
                  .filter((c: { folder_name: string; CIUDAD?: string; ACCIONANTE?: string }) => {
                    const term = caseSearch.toLowerCase()
                    return (c.folder_name || '').toLowerCase().includes(term) ||
                      (c.CIUDAD || '').toLowerCase().includes(term) ||
                      (c.ACCIONANTE || '').toLowerCase().includes(term)
                  })
                  .slice(0, 20)
                  .map((c: { id: number; folder_name: string; CIUDAD?: string }) => (
                    <button
                      key={c.id}
                      onClick={() => {
                        setSelectedCaseId(c.id)
                        setCaseSearch(c.folder_name + (c.CIUDAD ? ` (${c.CIUDAD})` : ''))
                        setShowCaseDropdown(false)
                      }}
                      className={`w-full text-left px-3 py-2 text-sm hover:bg-purple-50 transition-colors ${
                        selectedCaseId === c.id ? 'bg-purple-50 text-purple-700 font-medium' : 'text-gray-700'
                      }`}
                    >
                      <span className="font-mono text-xs text-gray-500">{c.folder_name}</span>
                      {c.CIUDAD && <span className="text-[10px] text-gray-400 ml-1">({c.CIUDAD})</span>}
                    </button>
                  ))}
                {allCases.filter((c: { folder_name: string; CIUDAD?: string; ACCIONANTE?: string }) => {
                  const term = caseSearch.toLowerCase()
                  return (c.folder_name || '').toLowerCase().includes(term) ||
                    (c.CIUDAD || '').toLowerCase().includes(term) ||
                    (c.ACCIONANTE || '').toLowerCase().includes(term)
                }).length === 0 && (
                  <div className="px-3 py-3 text-xs text-gray-400 text-center">Sin resultados</div>
                )}
              </div>
            )}
          </div>

          <button
            onClick={() => {
              if (!selectedCaseId) return
              if (extractionMode === 'agent') {
                agentMutation.mutate({ id: selectedCaseId as number, classify: classifyDocs })
              } else {
                singleMutation.mutate(selectedCaseId as number)
              }
            }}
            disabled={isLoading || !selectedCaseId}
            className={`w-full flex items-center justify-center gap-2 px-4 py-3 text-white font-medium rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm ${
              extractionMode === 'agent'
                ? 'bg-emerald-600 hover:bg-emerald-700'
                : 'bg-purple-600 hover:bg-purple-700'
            }`}
          >
            {(singleMutation.isPending || agentMutation.isPending) ? (
              <Loader2 size={16} className="animate-spin" />
            ) : extractionMode === 'agent' ? (
              <Brain size={16} />
            ) : (
              <Play size={16} />
            )}
            {(singleMutation.isPending || agentMutation.isPending)
              ? 'Extrayendo...'
              : extractionMode === 'agent'
                ? `Extraer con Agente${classifyDocs ? ' + Clasificar' : ''}`
                : 'Extraer Caso Individual'}
          </button>
        </div>
      </div>

      {/* Results */}
      {showResults && results.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-gray-50">
            <h2 className="text-sm font-semibold text-gray-700">
              Resultados de Extraccion ({results.length})
            </h2>
            <button
              onClick={() => setShowResults(false)}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              Cerrar
            </button>
          </div>
          <div className="divide-y divide-gray-100 max-h-80 overflow-y-auto">
            {results.map((r, i) => (
              <div
                key={i}
                className={`flex items-center gap-3 px-5 py-3 border-l-4 ${statusBg(r.status)}`}
              >
                {statusIcon(r.status)}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-700 truncate">{r.folder_name}</p>
                  {r.message && (
                    <p className="text-xs text-gray-500 truncate">{r.message}</p>
                  )}
                </div>
                <span className="text-xs font-medium text-gray-500 flex-shrink-0">
                  {r.fields_extracted} campos
                </span>
                <button
                  onClick={() => navigate(`/cases/${r.case_id}`)}
                  className="p-1 rounded text-gray-400 hover:text-[#1A5276]"
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Detailed Single Extraction Result */}
      {singleResult && singleResult.status === 'completed' && (
        <div className="bg-white rounded-xl border border-green-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-green-100 bg-green-50">
            <h2 className="text-sm font-semibold text-green-800">
              Resultado Detallado: {singleResult.folder_name}
            </h2>
            <button onClick={() => setSingleResult(null)} className="text-xs text-gray-400 hover:text-gray-600">Cerrar</button>
          </div>
          <div className="p-5 space-y-4">
            {/* Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              <div className="text-center p-2 bg-blue-50 rounded-lg">
                <p className="text-lg font-bold text-blue-700">{singleResult.fields_extracted}</p>
                <p className="text-[10px] text-gray-500">Campos</p>
              </div>
              <div className="text-center p-2 bg-green-50 rounded-lg">
                <p className="text-lg font-bold text-green-700">{singleResult.documents_processed}</p>
                <p className="text-[10px] text-gray-500">Docs procesados</p>
              </div>
              <div className="text-center p-2 bg-amber-50 rounded-lg">
                <p className="text-lg font-bold text-amber-700">{singleResult.documents_excluded}</p>
                <p className="text-[10px] text-gray-500">Docs excluidos</p>
              </div>
              <div className="text-center p-2 bg-purple-50 rounded-lg">
                <p className="text-lg font-bold text-purple-700">{singleResult.elapsed_seconds}s</p>
                <p className="text-[10px] text-gray-500">Tiempo</p>
              </div>
              <div className="text-center p-2 bg-gray-50 rounded-lg">
                <p className="text-lg font-bold text-gray-700">${singleResult.tokens?.cost || '0'}</p>
                <p className="text-[10px] text-gray-500">{singleResult.tokens?.provider}/{singleResult.tokens?.model}</p>
              </div>
            </div>

            {/* Tokens detail */}
            {singleResult.tokens && (
              <div className="text-xs text-gray-500">
                Tokens: {singleResult.tokens.input?.toLocaleString()} input + {singleResult.tokens.output?.toLocaleString()} output
              </div>
            )}

            {/* Fields extracted */}
            <div>
              <p className="text-xs font-semibold text-gray-600 mb-2">Campos extraidos:</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-1">
                {Object.entries(singleResult.fields || {}).map(([key, val]) => (
                  <div key={key} className="flex items-start gap-2 text-xs">
                    <span className="font-mono text-gray-400 w-32 flex-shrink-0 truncate">{key}</span>
                    <span className="text-gray-700 truncate">{String(val).substring(0, 60)}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Classification results (Agent mode) */}
            {singleResult.classification && (
              <div className={`rounded-lg p-3 border ${singleResult.classification.docs_movidos > 0 ? 'bg-amber-50 border-amber-200' : 'bg-green-50 border-green-200'}`}>
                <p className="text-xs font-semibold mb-1" style={{color: singleResult.classification.docs_movidos > 0 ? '#92400e' : '#15803d'}}>
                  Clasificacion de documentos:
                </p>
                <p className="text-xs text-gray-600">
                  {singleResult.classification.docs_ok} OK / {singleResult.classification.docs_total} total
                  {singleResult.classification.docs_movidos > 0 && (
                    <span className="text-amber-700 font-medium"> — {singleResult.classification.docs_movidos} movidos a PENDIENTE DE UBICACION</span>
                  )}
                </p>
                {singleResult.classification.docs_movidos_list?.map((f: string, i: number) => (
                  <p key={i} className="text-[10px] text-amber-600 ml-2">- {f}</p>
                ))}
                {singleResult.classification.classification_error && (
                  <p className="text-[10px] text-gray-400 mt-1">{singleResult.classification.classification_error}</p>
                )}
              </div>
            )}

            {/* Confidence (Agent mode) */}
            {singleResult.confidence_avg > 0 && (
              <div className="text-xs text-gray-500 bg-gray-50 rounded-lg p-2 border border-gray-200">
                Confianza promedio: <span className={`font-bold ${singleResult.confidence_avg >= 70 ? 'text-green-600' : singleResult.confidence_avg >= 40 ? 'text-amber-600' : 'text-red-600'}`}>{singleResult.confidence_avg}%</span>
                {singleResult.warnings?.length > 0 && (
                  <span className="text-amber-600 ml-2">| {singleResult.warnings.length} advertencias</span>
                )}
              </div>
            )}

            {/* Reasoning (Agent mode) */}
            {singleResult.reasoning?.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-emerald-700 font-semibold hover:underline">
                  Razonamiento del agente ({singleResult.reasoning.length} campos)
                </summary>
                <div className="mt-2 space-y-1 max-h-48 overflow-y-auto">
                  {singleResult.reasoning.map((r: any, i: number) => (
                    <div key={i} className="bg-emerald-50 rounded p-2 border border-emerald-100">
                      <span className="font-mono text-emerald-800">{r.campo || r.field_name}</span>
                      <span className="text-gray-500 ml-1">= {r.valor || r.value}</span>
                      <span className={`ml-2 text-[10px] ${(r.confianza || r.confidence) >= 70 ? 'text-green-600' : 'text-amber-600'}`}>
                        ({r.confianza || r.confidence}%)
                      </span>
                      {(r.razonamiento || r.reasoning) && (
                        <p className="text-[10px] text-gray-400 mt-0.5">{r.razonamiento || r.reasoning}</p>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            )}

            {/* Reassigned docs */}
            {singleResult.reassigned_docs?.length > 0 && (
              <div className="bg-amber-50 rounded-lg p-3 border border-amber-200">
                <p className="text-xs font-semibold text-amber-800 mb-1">Documentos reasignados automaticamente:</p>
                {singleResult.reassigned_docs.map((d: any, i: number) => (
                  <p key={i} className="text-xs text-amber-700">
                    {d.filename}: {d.from_case} → {d.to_case} ({d.reason})
                  </p>
                ))}
              </div>
            )}

            {/* Cases created */}
            {singleResult.cases_created?.length > 0 && (
              <div className="bg-blue-50 rounded-lg p-3 border border-blue-200">
                <p className="text-xs font-semibold text-blue-800 mb-1">Casos nuevos creados automaticamente:</p>
                {singleResult.cases_created.map((c: any, i: number) => (
                  <p key={i} className="text-xs text-blue-700">
                    {c.folder_name} (ID {c.case_id}) — desde doc: {c.from_doc}
                  </p>
                ))}
              </div>
            )}

            {/* Corrections injected */}
            {singleResult.corrections_injected > 0 && (
              <div className="text-xs text-purple-600 bg-purple-50 rounded-lg p-2 border border-purple-200">
                {singleResult.corrections_injected} correcciones historicas inyectadas como aprendizaje
              </div>
            )}

            {/* Suspicious docs */}
            {singleResult.suspicious_docs?.length > 0 && (
              <div className="bg-red-50 rounded-lg p-3 border border-red-200">
                <p className="text-xs font-semibold text-red-800 mb-1">Documentos sospechosos:</p>
                {singleResult.suspicious_docs.map((d: any, i: number) => (
                  <p key={i} className="text-xs text-red-700">
                    [{d.status}] {d.filename}: {d.detail}
                  </p>
                ))}
              </div>
            )}

            <button
              onClick={() => navigate(`/cases/${singleResult.case_id}`)}
              className="text-xs text-[#1A5276] hover:underline"
            >
              Ver detalle del caso →
            </button>
          </div>
        </div>
      )}

      {/* Mismatched Documents Alert */}
      {(mismatchedQ.data ?? []).length > 0 && (
        <div className="bg-white rounded-xl border border-red-200 shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-3 border-b border-red-100 bg-red-50">
            <div className="flex items-center gap-2">
              <ShieldAlert size={15} className="text-red-500" />
              <h2 className="text-sm font-semibold text-red-700">
                Documentos que NO corresponden al caso
                <span className="ml-2 bg-red-100 text-red-700 text-xs px-2 py-0.5 rounded-full font-medium">
                  {(mismatchedQ.data ?? []).length}
                </span>
              </h2>
            </div>
            <button
              onClick={() => dismissAllMut.mutate()}
              disabled={dismissAllMut.isPending}
              className="flex items-center gap-1.5 text-xs text-red-600 hover:text-red-800 font-medium disabled:opacity-50"
            >
              <Trash2 size={12} />
              Resolver todas
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-red-100 bg-red-50/50">
                  <th className="text-left px-4 py-2 text-xs font-semibold text-red-600 uppercase">Caso</th>
                  <th className="text-left px-4 py-2 text-xs font-semibold text-red-600 uppercase">Documento</th>
                  <th className="text-left px-4 py-2 text-xs font-semibold text-red-600 uppercase">Radicado encontrado</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-red-100">
                {(mismatchedQ.data ?? []).map((m: { id: number; case_id: number; case_name: string; filename: string; radicado_encontrado: string }, i: number) => (
                  <tr key={i} className="hover:bg-red-50/30">
                    <td className="px-4 py-2.5">
                      <span className="font-mono text-xs text-gray-700">{m.case_name}</span>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-600">{m.filename}</td>
                    <td className="px-4 py-2.5">
                      <span className="bg-red-100 text-red-700 text-xs px-2 py-0.5 rounded font-mono">{m.radicado_encontrado}</span>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => dismissOneMut.mutate(m.id)}
                          disabled={dismissOneMut.isPending}
                          className="text-xs text-red-500 hover:text-red-700 font-medium disabled:opacity-50"
                        >
                          Resolver
                        </button>
                        <button onClick={() => navigate(`/cases/${m.case_id}`)} className="p-1 text-gray-400 hover:text-red-600">
                          <ChevronRight size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Suspicious Documents */}
      {(suspiciousQ.data ?? []).length > 0 && (() => {
        const allDocs = suspiciousQ.data ?? []
        const noPertenece = allDocs.filter((d: any) => d.verificacion === 'NO_PERTENECE')
        const sospechosos = allDocs.filter((d: any) => d.verificacion === 'SOSPECHOSO')
        return (
          <>
            {/* NO_PERTENECE — Rojo */}
            {noPertenece.length > 0 && (
              <div className="bg-white rounded-xl border border-red-200 shadow-sm overflow-hidden">
                <div className="flex items-center justify-between px-5 py-3 border-b border-red-100 bg-red-50">
                  <div className="flex items-center gap-2">
                    <ShieldAlert size={15} className="text-red-500" />
                    <h2 className="text-sm font-semibold text-red-700">
                      Documentos que NO Pertenecen
                      <span className="ml-2 bg-red-100 text-red-700 text-xs px-2 py-0.5 rounded-full font-medium">
                        {noPertenece.length}
                      </span>
                    </h2>
                  </div>
                  <button
                    onClick={() => verifyAllMut.mutate()}
                    disabled={verifyAllMut.isPending}
                    className="flex items-center gap-1.5 text-xs text-red-600 hover:text-red-800 font-medium disabled:opacity-50"
                  >
                    <SearchIcon size={12} />
                    {verifyAllMut.isPending ? 'Verificando...' : 'Re-verificar'}
                  </button>
                </div>
                <div className="overflow-x-auto max-h-72 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-red-100 bg-red-50/50 sticky top-0">
                        <th className="text-left px-4 py-2 text-xs font-semibold text-red-600 uppercase">Carpeta</th>
                        <th className="text-left px-4 py-2 text-xs font-semibold text-red-600 uppercase">Documento</th>
                        <th className="text-left px-4 py-2 text-xs font-semibold text-red-600 uppercase">Detalle</th>
                        <th className="px-4 py-2" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-red-100">
                      {noPertenece.map((d: any) => (
                        <tr key={d.doc_id} className="hover:bg-red-50/30">
                          <td className="px-4 py-2.5">
                            <span className="font-mono text-xs text-gray-700">{d.case_name?.substring(0, 35)}</span>
                          </td>
                          <td className="px-4 py-2.5 text-xs text-gray-600">{d.filename?.substring(0, 35)}</td>
                          <td className="px-4 py-2.5">
                            <span className="text-xs text-red-600">{d.detalle?.substring(0, 60)}</span>
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <div className="flex items-center justify-end gap-2">
                              <button onClick={() => markOkMut.mutate(d.doc_id)} disabled={markOkMut.isPending}
                                className="text-xs text-green-600 hover:text-green-800 font-medium disabled:opacity-50">OK</button>
                              <button onClick={() => navigate(`/cases/${d.case_id}`)} className="px-2 py-0.5 text-xs bg-red-50 text-red-600 border border-red-200 rounded hover:bg-red-100">
                                Resolver
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* SOSPECHOSOS — Naranja */}
            {sospechosos.length > 0 && (
              <div className="bg-white rounded-xl border border-orange-200 shadow-sm overflow-hidden">
                <div className="flex items-center justify-between px-5 py-3 border-b border-orange-100 bg-orange-50">
                  <div className="flex items-center gap-2">
                    <FileWarning size={15} className="text-orange-500" />
                    <h2 className="text-sm font-semibold text-orange-700">
                      Documentos Sospechosos
                      <span className="ml-2 bg-orange-100 text-orange-700 text-xs px-2 py-0.5 rounded-full font-medium">
                        {sospechosos.length}
                      </span>
                    </h2>
                  </div>
                </div>
                <div className="overflow-x-auto max-h-72 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-orange-100 bg-orange-50/50 sticky top-0">
                        <th className="text-left px-4 py-2 text-xs font-semibold text-orange-600 uppercase">Carpeta</th>
                        <th className="text-left px-4 py-2 text-xs font-semibold text-orange-600 uppercase">Documento</th>
                        <th className="text-left px-4 py-2 text-xs font-semibold text-orange-600 uppercase">Detalle</th>
                        <th className="px-4 py-2" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-orange-100">
                      {sospechosos.map((d: any) => (
                        <tr key={d.doc_id} className="hover:bg-orange-50/30">
                          <td className="px-4 py-2.5">
                            <span className="font-mono text-xs text-gray-700">{d.case_name?.substring(0, 35)}</span>
                          </td>
                          <td className="px-4 py-2.5 text-xs text-gray-600">{d.filename?.substring(0, 35)}</td>
                          <td className="px-4 py-2.5">
                            <span className="text-xs text-orange-600">{d.detalle?.substring(0, 50)}</span>
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <div className="flex items-center justify-end gap-2">
                              <button onClick={() => markOkMut.mutate(d.doc_id)} disabled={markOkMut.isPending}
                                className="text-xs text-green-600 hover:text-green-800 font-medium disabled:opacity-50">OK</button>
                              <button onClick={() => navigate(`/cases/${d.case_id}`)} className="p-1 text-gray-400 hover:text-orange-600">
                                <ChevronRight size={14} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )
      })()}

      {/* Review Queue */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-gray-50">
          <div className="flex items-center gap-2">
            <AlertCircle size={15} className={reviewQueue.length > 0 ? 'text-amber-500' : 'text-green-400'} />
            <h2 className="text-sm font-semibold text-gray-700">
              Cola de Revision
              {reviewQueue.length > 0 && (
                <span className="ml-2 bg-amber-100 text-amber-700 text-xs px-2 py-0.5 rounded-full font-medium">
                  {reviewQueue.length}
                </span>
              )}
            </h2>
          </div>
          {reviewQueue.length > 0 && (
            <button
              onClick={() => qc.invalidateQueries({ queryKey: ['review-queue'] })}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-200 transition-colors"
            >
              <RefreshCw size={14} className={reviewQ.isFetching ? 'animate-spin' : ''} />
            </button>
          )}
        </div>

        {reviewQ.isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={24} className="animate-spin text-[#1A5276]" />
          </div>
        ) : reviewQueue.length === 0 ? (
          <div className="text-center py-10">
            <CheckCircle size={32} className="mx-auto text-green-400 mb-2" />
            <p className="text-sm text-gray-500">Todos los casos estan completos</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Caso</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Accionante</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase">Completitud</th>
                  <th className="text-left px-4 py-2.5 text-xs font-semibold text-gray-500 uppercase hidden lg:table-cell">Campos Faltantes</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {reviewQueue.map((c) => (
                  <tr key={c.case_id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-xs text-[#1A5276] font-medium">{c.folder_name}</span>
                        {(c as any).docs_no_pertenece > 0 && (
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-bold bg-red-100 text-red-700" title={`${(c as any).docs_no_pertenece} doc(s) NO pertenecen`}>
                            {(c as any).docs_no_pertenece}
                          </span>
                        )}
                        {(c as any).docs_sospechosos > 0 && (
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700" title={`${(c as any).docs_sospechosos} doc(s) sospechosos`}>
                            {(c as any).docs_sospechosos}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-700 text-xs">{c.accionante || c.ACCIONANTE || '—'}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 bg-gray-200 rounded-full h-1.5 w-20">
                          <div
                            className="bg-[#1A5276] h-1.5 rounded-full"
                            style={{ width: `${100 - (c.empty_fields?.length ?? 0) / 28 * 100}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-500">{Math.round(100 - (c.empty_fields?.length ?? 0) / 28 * 100)}%</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell">
                      <div className="flex flex-wrap gap-1">
                        {(c.empty_fields ?? c.missing_fields ?? []).slice(0, 4).map((f) => (
                          <span
                            key={f}
                            className="bg-red-50 text-red-600 border border-red-200 text-xs px-1.5 py-0.5 rounded font-mono"
                          >
                            {f}
                          </span>
                        ))}
                        {(c.empty_fields ?? c.missing_fields ?? []).length > 4 && (
                          <span className="text-xs text-gray-400">
                            +{(c.missing_fields ?? []).length - 4} mas
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => {
                            const id = c.case_id || (c as unknown as {id: number}).id
                            if (id) singleMutation.mutate(id)
                            else toast.error('ID de caso no encontrado')
                          }}
                          disabled={isLoading}
                          className="text-xs text-purple-600 hover:text-purple-800 font-medium disabled:opacity-50"
                        >
                          Extraer
                        </button>
                        <button
                          onClick={() => navigate(`/cases/${c.case_id}`)}
                          className="p-1 text-gray-400 hover:text-[#1A5276]"
                        >
                          <ChevronRight size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
