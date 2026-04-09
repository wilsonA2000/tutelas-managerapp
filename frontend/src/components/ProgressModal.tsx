import { useState, useEffect, useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, X, CheckCircle, AlertTriangle } from 'lucide-react'
import {
  getSyncStatus, getCheckInboxStatus, getExtractionProgress,
  stopExtraction, cancelCheckInbox, cancelSync,
} from '../services/api'
import { useSyncProgress, useGmailProgress, useExtractionProgress } from '../hooks/useProgressPolling'

interface ProcessInfo {
  key: string
  label: string
  statusFn: () => Promise<Record<string, unknown>>
  cancelFn?: () => Promise<Record<string, unknown>>
}

const PROCESSES: ProcessInfo[] = [
  { key: 'sync', label: 'Sincronizando Carpetas', statusFn: getSyncStatus, cancelFn: cancelSync },
  { key: 'gmail', label: 'Revisando Gmail', statusFn: getCheckInboxStatus, cancelFn: cancelCheckInbox },
  { key: 'extraction', label: 'Extraccion IA', statusFn: getExtractionProgress, cancelFn: stopExtraction },
]

function ProcessTracker({ process }: { process: ProcessInfo }) {
  const qc = useQueryClient()
  const statusQ = useQuery({
    queryKey: [`progress-${process.key}`],
    queryFn: process.statusFn,
    refetchInterval: 1500,
  })

  const cancelMut = useMutation({
    mutationFn: process.cancelFn!,
    onSuccess: () => qc.invalidateQueries({ queryKey: [`progress-${process.key}`] }),
  })

  const data = statusQ.data as Record<string, unknown> | undefined
  if (!data) return null

  const inProgress = data.in_progress as boolean
  if (!inProgress) return null

  const step = (data.step as string) || (data.case_name as string) || ''
  const current = (data.current as number) || 0
  const total = (data.total as number) || 0
  const success = (data.success as number) || (data.emails_found as number) || 0
  const errors = (data.errors as number) || 0
  const docsVerified = (data.docs_verified as number) || 0
  const docsTotal = (data.docs_total as number) || 0
  const elapsed = (data.elapsed_seconds as number) || 0
  // Usar progress_pct del backend si disponible, sino calcular de current/total
  const backendPct = data.progress_pct as number | undefined
  const pct = backendPct != null ? backendPct : (total > 0 ? Math.round((current / total) * 100) : 0)
  // Formato de tiempo transcurrido
  const elapsedStr = elapsed > 0 ? `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}` : ''

  return (
    <div className="mb-4 last:mb-0">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white">{process.label}</h3>
        {process.cancelFn && (
          <button onClick={() => cancelMut.mutate()} disabled={cancelMut.isPending}
            className="text-white/60 hover:text-white transition-colors" title="Cancelar">
            <X size={16} />
          </button>
        )}
      </div>
      {total > 0 ? (
        <>
          <div className="w-full bg-white/10 rounded-full h-3 mb-2 overflow-hidden">
            <div className="h-full rounded-full transition-all duration-500 ease-out relative"
              style={{ width: `${Math.max(pct, 2)}%`, background: 'linear-gradient(90deg, #3b82f6 0%, #8b5cf6 50%, #3b82f6 100%)', backgroundSize: '200% 100%', animation: 'shimmer 2s linear infinite' }}>
              <div className="absolute inset-0 bg-white/20 animate-pulse" />
            </div>
          </div>
          <div className="flex justify-between text-xs text-white/70">
            <span>{current} de {total}{elapsedStr ? ` · ${elapsedStr}` : ''}</span>
            <span className="font-bold text-white text-sm">{pct}%</span>
          </div>
          {(success > 0 || errors > 0 || docsVerified > 0) && (
            <div className="flex gap-3 mt-1 text-xs text-white/50">
              {success > 0 && <span className="text-green-300">{success} exitosos</span>}
              {errors > 0 && <span className="text-red-300">{errors} errores</span>}
              {docsVerified > 0 && <span className="text-blue-300">{docsVerified}{docsTotal > 0 ? `/${docsTotal}` : ''} docs</span>}
            </div>
          )}
        </>
      ) : (
        <div className="w-full bg-white/10 rounded-full h-3 mb-2 overflow-hidden">
          <div className="h-full rounded-full w-full"
            style={{ background: 'linear-gradient(90deg, transparent 0%, #3b82f6 50%, transparent 100%)', backgroundSize: '200% 100%', animation: 'shimmer 1.5s linear infinite' }} />
        </div>
      )}
      {step && <p className="text-xs text-white/50 truncate mt-1">{step}</p>}
    </div>
  )
}

interface CompletedResult {
  type: string
  label: string
  details: string[]
  hasErrors: boolean
}

export default function ProgressModal() {
  const qc = useQueryClient()
  const syncQ = useSyncProgress()
  const gmailQ = useGmailProgress()
  const extractQ = useExtractionProgress()

  const [completedResults, setCompletedResults] = useState<CompletedResult[]>([])
  const [showCompleted, setShowCompleted] = useState(false)

  // Track previous states to detect completion
  const prevSync = useRef(false)
  const prevGmail = useRef(false)
  const prevExtract = useRef(false)

  useEffect(() => {
    const syncData = syncQ.data as Record<string, unknown> | undefined
    const syncActive = !!(syncData?.in_progress)
    if (prevSync.current && !syncActive && syncData?.step) {
      const d = syncData
      const details: string[] = []
      if ((d.docs_added as number) > 0) details.push(`+${d.docs_added} documentos nuevos`)
      if ((d.new_cases as number) > 0) details.push(`+${d.new_cases} casos nuevos`)
      if ((d.cases_removed as number) > 0) details.push(`-${d.cases_removed} casos eliminados`)
      if ((d.paths_fixed as number) > 0) details.push(`${d.paths_fixed} rutas corregidas`)
      if ((d.docs_moved as number) > 0) details.push(`${d.docs_moved} docs reasignados`)
      if ((d.docs_suspicious as number) > 0) details.push(`${d.docs_suspicious} docs sospechosos`)
      if ((d.docs_verified as number) > 0) details.push(`${d.docs_verified} docs verificados`)
      if (details.length === 0) details.push('Sin cambios detectados')
      setCompletedResults(prev => [...prev, { type: 'sync', label: 'Sincronizacion', details, hasErrors: false }])
      setShowCompleted(true)
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['cases-table'] })
      qc.invalidateQueries({ queryKey: ['kpis'] })
      qc.invalidateQueries({ queryKey: ['review-queue'] })
    }
    prevSync.current = syncActive
  }, [syncQ.data, qc])

  useEffect(() => {
    const gmailData = gmailQ.data as Record<string, unknown> | undefined
    const gmailActive = !!(gmailData?.in_progress)
    if (prevGmail.current && !gmailActive && gmailData?.step) {
      const d = gmailData
      const details: string[] = []
      const emails = (d.emails_found as number) || 0
      const cases = (d.cases_processed as number) || 0
      const fields = (d.total_fields as number) || 0
      if (emails > 0) details.push(`${emails} correos procesados`)
      else details.push('Sin correos nuevos')
      if (cases > 0) details.push(`${cases} casos actualizados`)
      if (fields > 0) details.push(`${fields} campos extraidos`)
      if (d.error) details.push(`Error: ${d.error}`)
      setCompletedResults(prev => [...prev, { type: 'gmail', label: 'Gmail', details, hasErrors: !!d.error }])
      setShowCompleted(true)
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['emails'] })
      qc.invalidateQueries({ queryKey: ['kpis'] })
      qc.invalidateQueries({ queryKey: ['review-queue'] })
    }
    prevGmail.current = gmailActive
  }, [gmailQ.data, qc])

  useEffect(() => {
    const extData = extractQ.data as Record<string, unknown> | undefined
    const extActive = !!(extData?.in_progress)
    if (prevExtract.current && !extActive && extData?.case_name) {
      const d = extData
      const details: string[] = []
      const success = (d.success as number) || 0
      const errors = (d.errors as number) || 0
      const total = (d.total as number) || 0
      if (total > 0) details.push(`${success}/${total} casos exitosos`)
      if (errors > 0) details.push(`${errors} con errores`)
      if (details.length === 0) details.push('Extraccion completada')
      setCompletedResults(prev => [...prev, { type: 'extraction', label: 'Extraccion IA', details, hasErrors: errors > 0 }])
      setShowCompleted(true)
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['cases-table'] })
      qc.invalidateQueries({ queryKey: ['kpis'] })
      qc.invalidateQueries({ queryKey: ['charts'] })
      qc.invalidateQueries({ queryKey: ['review-queue'] })
    }
    prevExtract.current = extActive
  }, [extractQ.data, qc])

  // Auto-dismiss completed after 15 seconds
  useEffect(() => {
    if (showCompleted) {
      const timer = setTimeout(() => { setShowCompleted(false); setCompletedResults([]) }, 15000)
      return () => clearTimeout(timer)
    }
  }, [showCompleted])

  const activeProcesses = PROCESSES.filter((p) => {
    if (p.key === 'sync') return (syncQ.data as Record<string, unknown>)?.in_progress
    if (p.key === 'gmail') return (gmailQ.data as Record<string, unknown>)?.in_progress
    if (p.key === 'extraction') return (extractQ.data as Record<string, unknown>)?.in_progress
    return false
  })

  const hasActive = activeProcesses.length > 0
  const hasCompleted = showCompleted && completedResults.length > 0

  if (!hasActive && !hasCompleted) return null

  return (
    <>
      <style>{`
        @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
      `}</style>

      <div className="fixed inset-0 z-50 flex items-center justify-center">
        <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => { if (!hasActive) { setShowCompleted(false); setCompletedResults([]) } }} />

        <div className="relative z-10 w-full max-w-md mx-4">
          <div className="bg-gradient-to-br from-[#1A5276] to-[#0E3A5C] rounded-2xl shadow-2xl p-6 border border-white/10">

            {/* Active processes */}
            {hasActive && (
              <>
                <div className="flex justify-center mb-5">
                  <div className="relative">
                    <div className="w-16 h-16 rounded-full border-4 border-white/10 flex items-center justify-center">
                      <Loader2 size={28} className="text-white animate-spin" />
                    </div>
                    <div className="absolute -top-1 -right-1 w-5 h-5 bg-blue-500 rounded-full flex items-center justify-center">
                      <span className="text-white text-[10px] font-bold">{activeProcesses.length}</span>
                    </div>
                  </div>
                </div>
                <h2 className="text-center text-white font-semibold text-lg mb-1">Procesando</h2>
                <p className="text-center text-white/50 text-xs mb-5">Puede navegar entre modulos.</p>
                {activeProcesses.map((p) => <ProcessTracker key={p.key} process={p} />)}
              </>
            )}

            {/* Completed results */}
            {hasCompleted && !hasActive && (
              <>
                <div className="flex justify-center mb-4">
                  <div className="w-14 h-14 rounded-full bg-green-500/20 flex items-center justify-center">
                    <CheckCircle size={28} className="text-green-400" />
                  </div>
                </div>
                <h2 className="text-center text-white font-semibold text-lg mb-4">Completado</h2>

                {completedResults.map((result, i) => (
                  <div key={i} className="mb-3 last:mb-0 bg-white/5 rounded-lg p-3">
                    <div className="flex items-center gap-2 mb-1.5">
                      {result.hasErrors
                        ? <AlertTriangle size={14} className="text-amber-400" />
                        : <CheckCircle size={14} className="text-green-400" />}
                      <span className="text-sm font-medium text-white">{result.label}</span>
                    </div>
                    {result.details.map((detail, j) => (
                      <p key={j} className="text-xs text-white/60 ml-6">{detail}</p>
                    ))}
                  </div>
                ))}

                <button
                  onClick={() => { setShowCompleted(false); setCompletedResults([]) }}
                  className="w-full mt-4 py-2 bg-white/10 hover:bg-white/20 text-white text-sm font-medium rounded-lg transition-colors"
                >
                  Cerrar
                </button>
                <p className="text-center text-white/30 text-[10px] mt-2">Se cierra automaticamente en 15s</p>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
