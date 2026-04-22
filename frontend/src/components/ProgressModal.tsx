import { useState, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2, X, CheckCircle, AlertTriangle } from 'lucide-react'
import {
  getSyncStatus, getCheckInboxStatus, getExtractionProgress,
  stopExtraction, cancelCheckInbox, cancelSync,
} from '../services/api'
import { useSyncProgress, useGmailProgress, useExtractionProgress } from '../hooks/useProgressPolling'
import { Button } from '@/components/ui/button'

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
  const eta = (data.eta_seconds as number) || 0
  const phase = (data.phase as string) || ''
  const backendPct = data.progress_pct as number | undefined
  const pct = backendPct != null ? backendPct : (total > 0 ? Math.round((current / total) * 100) : 0)
  // Inferir paso actual desde la cadena phase ("Paso 2/7: ...") cuando current no se actualiza
  const phaseMatch = phase.match(/Paso\s+(\d+)\s*\/\s*(\d+)/i)
  const stepNum = phaseMatch ? parseInt(phaseMatch[1], 10) : current
  const stepTotal = phaseMatch ? parseInt(phaseMatch[2], 10) : total
  const elapsedStr = elapsed > 0 ? `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')} min` : ''
  const etaStr = eta > 0 ? `~${Math.floor(eta / 60)}:${String(eta % 60).padStart(2, '0')} min restante` : ''

  return (
    <div className="mb-4 last:mb-0">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-white">{process.label}</h3>
        {process.cancelFn && (
          <button
            onClick={() => cancelMut.mutate()}
            disabled={cancelMut.isPending}
            className="text-white/60 hover:text-white transition-colors"
            title="Cancelar"
          >
            <X size={16} />
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div className="h-3 bg-white/10 rounded-full overflow-hidden mb-2">
        {total > 0 ? (
          <div
            className="h-full rounded-full transition-all duration-500 ease-out"
            style={{
              width: `${pct}%`,
              background: 'linear-gradient(90deg, #3b82f6 0%, #8b5cf6 50%, #3b82f6 100%)',
              backgroundSize: '200% 100%',
              animation: 'shimmer 2s linear infinite',
            }}
          />
        ) : (
          <div
            className="h-full w-full rounded-full"
            style={{
              background: 'linear-gradient(90deg, transparent 0%, #3b82f6 50%, transparent 100%)',
              backgroundSize: '200% 100%',
              animation: 'shimmer 1.5s linear infinite',
            }}
          />
        )}
      </div>

      {total > 0 && (
        <>
          <div className="flex justify-between text-xs text-white/80">
            <span>
              {stepTotal > 0 ? `Paso ${stepNum} de ${stepTotal}` : `${current} de ${total}`}
              {elapsedStr ? ` \u00B7 ${elapsedStr}` : ''}
              {etaStr ? ` \u00B7 ${etaStr}` : ''}
            </span>
            <span className="font-bold text-white text-sm">{pct}%</span>
          </div>
          {phase && <p className="text-[11px] text-white/60 mt-1">{phase.replace(/^Paso\s+\d+\s*\/\s*\d+:\s*/i, '')}</p>}
          {(success > 0 || errors > 0 || docsVerified > 0) && (
            <div className="flex gap-3 mt-1 text-xs text-white/60">
              {success > 0 && <span className="text-green-300">{success} exitosos</span>}
              {errors > 0 && <span className="text-red-300">{errors} errores</span>}
              {docsVerified > 0 && <span className="text-blue-300">{docsVerified}{docsTotal > 0 ? `/${docsTotal}` : ''} docs</span>}
            </div>
          )}
        </>
      )}

      {step && !phase && <p className="text-xs text-white/60 truncate mt-1">{step}</p>}
    </div>
  )
}

interface CompletedDetail {
  text: string
  tone: 'add' | 'remove' | 'fix' | 'warn' | 'info'
}

interface CompletedResult {
  type: string
  label: string
  details: CompletedDetail[]
  hasErrors: boolean
}

export default function ProgressModal() {
  const qc = useQueryClient()
  const syncQ = useSyncProgress()
  const gmailQ = useGmailProgress()
  const extractQ = useExtractionProgress()

  const [completedResults, setCompletedResults] = useState<CompletedResult[]>([])
  const [showCompleted, setShowCompleted] = useState(false)

  const prevSync = useRef(false)
  const prevGmail = useRef(false)
  const prevExtract = useRef(false)

  useEffect(() => {
    const syncData = syncQ.data as Record<string, unknown> | undefined
    const syncActive = !!(syncData?.in_progress)
    if (prevSync.current && !syncActive) {
      const d = syncData || {} as Record<string, unknown>
      const details: CompletedDetail[] = []
      if ((d.docs_added as number) > 0) details.push({ text: `+${d.docs_added} documentos nuevos`, tone: 'add' })
      if ((d.new_cases as number) > 0) details.push({ text: `+${d.new_cases} casos nuevos`, tone: 'add' })
      if ((d.cases_removed as number) > 0) details.push({ text: `-${d.cases_removed} casos eliminados`, tone: 'remove' })
      if ((d.docs_removed as number) > 0) details.push({ text: `-${d.docs_removed} docs fantasma eliminados`, tone: 'remove' })
      if ((d.cases_fixed as number) > 0) details.push({ text: `${d.cases_fixed} casos arreglados`, tone: 'fix' })
      if ((d.paths_fixed as number) > 0) details.push({ text: `${d.paths_fixed} rutas corregidas`, tone: 'fix' })
      if ((d.folders_renamed as number) > 0) details.push({ text: `${d.folders_renamed} carpetas renombradas`, tone: 'fix' })
      if ((d.docs_moved as number) > 0) details.push({ text: `${d.docs_moved} docs reasignados`, tone: 'fix' })
      if ((d.docs_suspicious as number) > 0) details.push({ text: `${d.docs_suspicious} docs sospechosos (revisar)`, tone: 'warn' })
      if ((d.docs_verified as number) > 0) details.push({ text: `${d.docs_verified} docs verificados`, tone: 'info' })
      if (details.length === 0) details.push({ text: 'Sin cambios detectados', tone: 'info' })
      setCompletedResults(prev => [...prev, { type: 'sync', label: 'Sincronizacion de carpetas', details, hasErrors: false }])
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
    if (prevGmail.current && !gmailActive) {
      const d = gmailData || {} as Record<string, unknown>
      const details: CompletedDetail[] = []
      const emails = (d.emails_found as number) || 0
      const cases = (d.cases_processed as number) || 0
      const fields = (d.total_fields as number) || 0
      if (emails > 0) details.push({ text: `${emails} correos procesados`, tone: 'add' })
      else details.push({ text: 'Sin correos nuevos', tone: 'info' })
      if (cases > 0) details.push({ text: `${cases} casos actualizados`, tone: 'fix' })
      if (fields > 0) details.push({ text: `${fields} campos extraidos`, tone: 'info' })
      if (d.error) details.push({ text: `Error: ${d.error}`, tone: 'warn' })
      setCompletedResults(prev => [...prev, { type: 'gmail', label: 'Revisión Gmail', details, hasErrors: !!d.error }])
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
    if (prevExtract.current && !extActive) {
      const d = extData || {} as Record<string, unknown>
      const details: CompletedDetail[] = []
      const success = (d.success as number) || 0
      const errors = (d.errors as number) || 0
      const total = (d.total as number) || 0
      if (total > 0) details.push({ text: `${success}/${total} casos exitosos`, tone: success === total ? 'add' : 'fix' })
      if (errors > 0) details.push({ text: `${errors} con errores`, tone: 'warn' })
      // Lista explícita de casos fallidos (si el backend los devuelve)
      const failedCases = (d.failed_cases as Array<{ id: number; folder: string; reason: string }>) || []
      for (const fc of failedCases) {
        const label = fc.folder || `Caso ${fc.id}`
        const reason = fc.reason ? ` — ${fc.reason.slice(0, 60)}` : ''
        details.push({ text: `✗ ${label.slice(0, 50)}${reason}`, tone: 'warn' })
      }
      if (details.length === 0) details.push({ text: 'Extracción completada', tone: 'info' })
      setCompletedResults(prev => [...prev, { type: 'extraction', label: 'Extracción IA', details, hasErrors: errors > 0 }])
      setShowCompleted(true)
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['cases-table'] })
      qc.invalidateQueries({ queryKey: ['kpis'] })
      qc.invalidateQueries({ queryKey: ['charts'] })
      qc.invalidateQueries({ queryKey: ['review-queue'] })
    }
    prevExtract.current = extActive
  }, [extractQ.data, qc])

  // Auto-close de 60s pausable: si el usuario hace hover sobre el modal, no se cierra
  const [autoCloseHovered, setAutoCloseHovered] = useState(false)
  useEffect(() => {
    if (showCompleted && !autoCloseHovered) {
      const timer = setTimeout(() => { setShowCompleted(false); setCompletedResults([]) }, 60000)
      return () => clearTimeout(timer)
    }
  }, [showCompleted, autoCloseHovered])

  const activeProcesses = PROCESSES.filter((p) => {
    if (p.key === 'sync') return (syncQ.data as Record<string, unknown>)?.in_progress
    if (p.key === 'gmail') return (gmailQ.data as Record<string, unknown>)?.in_progress
    if (p.key === 'extraction') return (extractQ.data as Record<string, unknown>)?.in_progress
    return false
  })

  const hasActive = activeProcesses.length > 0
  const hasCompleted = showCompleted && completedResults.length > 0

  if (!hasActive && !hasCompleted) return null

  const handleClose = () => {
    if (!hasActive) {
      setShowCompleted(false)
      setCompletedResults([])
    }
  }

  return (
    <>
      <style>{`
        @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
      `}</style>

      {/* Overlay */}
      <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
        {/* Modal */}
        <div className="w-full max-w-md bg-gradient-to-br from-primary to-primary/80 rounded-xl border border-white/10 text-white p-6 shadow-2xl">

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
            <div
              onMouseEnter={() => setAutoCloseHovered(true)}
              onMouseLeave={() => setAutoCloseHovered(false)}
            >
              <div className="flex justify-center mb-4">
                <div className="w-14 h-14 rounded-full bg-green-500/20 flex items-center justify-center">
                  <CheckCircle size={28} className="text-green-400" />
                </div>
              </div>
              <h2 className="text-center text-white font-semibold text-lg mb-4">Completado</h2>

              {completedResults.map((result, i) => (
                <div key={i} className="mb-3 last:mb-0 bg-white/8 rounded-lg p-3.5 border border-white/5">
                  <div className="flex items-center gap-2 mb-2 pb-2 border-b border-white/10">
                    {result.hasErrors
                      ? <AlertTriangle size={16} className="text-amber-400" />
                      : <CheckCircle size={16} className="text-green-400" />}
                    <span className="text-sm font-semibold text-white">{result.label}</span>
                  </div>
                  <div className="space-y-1">
                    {result.details.map((detail, j) => {
                      const toneClass = {
                        add: 'text-green-300',
                        remove: 'text-red-300',
                        fix: 'text-blue-300',
                        warn: 'text-amber-300',
                        info: 'text-white/70',
                      }[detail.tone]
                      const dotClass = {
                        add: 'bg-green-400',
                        remove: 'bg-red-400',
                        fix: 'bg-blue-400',
                        warn: 'bg-amber-400',
                        info: 'bg-white/40',
                      }[detail.tone]
                      return (
                        <div key={j} className="flex items-center gap-2 text-xs">
                          <span className={`inline-block w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotClass}`} aria-hidden="true" />
                          <span className={toneClass}>{detail.text}</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ))}

              <Button
                variant="ghost"
                className="w-full mt-4 bg-white/10 hover:bg-white/20 text-white border-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
                onClick={handleClose}
              >
                Cerrar
              </Button>
              <p className="text-center text-white/40 text-[10px] mt-2">
                {autoCloseHovered ? 'Pausa automatica activa (mouse sobre el modal)' : 'Se cierra automaticamente en 60s'}
              </p>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
