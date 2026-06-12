import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Save, FileText, ExternalLink, Loader2,
  AlertCircle, RefreshCw, ChevronDown, ChevronUp, Trash2, Mail, Package, Lock, FolderInput, Search, Pencil, FolderPlus, Link2, History,
} from 'lucide-react'
import HistorialModal from '../components/HistorialModal'
import { getCase, getCases, updateCase, renameCaseFolder, getDocumentPreviewUrl, syncSingleCase, deleteCase, deleteDocument, suggestDocTarget, moveDocument, markDocOk, getCaseEmailPackages, createCase, getCaseAcumulacion, compareCases, mergeCases, type CaseCompareResult } from '../services/api'
import StatusBadge from '../components/StatusBadge'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { cn } from '@/lib/utils'

// ─── Field Definitions ──────────────────────────────────────────────────────

type FieldType = 'text' | 'textarea' | 'date' | 'select'

interface FieldDef {
  key: string
  label: string
  type: FieldType
  options?: string[]
  mono?: boolean
}

interface SectionDef {
  title: string
  fields: FieldDef[]
}

const SECTIONS: SectionDef[] = [
  {
    title: 'Identificación del expediente',
    fields: [
      { key: 'RADICADO_23_DIGITOS', label: 'Radicado (23 dígitos)', type: 'text', mono: true },
      { key: 'RADICADO_FOREST', label: 'Radicado FOREST', type: 'text', mono: true },
    ],
  },
  {
    title: 'Partes procesales',
    fields: [
      { key: 'ACCIONANTE', label: 'Accionante', type: 'text' },
      { key: 'ACCIONADOS', label: 'Accionado(s)', type: 'textarea' },
      { key: 'VINCULADOS', label: 'Vinculados', type: 'textarea' },
    ],
  },
  {
    title: 'Proceso y hechos',
    fields: [
      { key: 'JUZGADO', label: 'Juzgado de primera instancia', type: 'text' },
      { key: 'CIUDAD', label: 'Municipio donde se vulneró el derecho', type: 'text' },
      { key: 'FECHA_INGRESO', label: 'Fecha de ingreso', type: 'date' },
      { key: 'DERECHO_VULNERADO', label: 'Derechos vulnerados', type: 'textarea' },
      { key: 'ASUNTO', label: 'Asunto (resumen)', type: 'textarea' },
      { key: 'PRETENSIONES', label: 'Pretensiones (transcripción literal)', type: 'textarea' },
    ],
  },
  {
    title: 'Gestión interna SED',
    fields: [
      { key: 'ABOGADO_CANONICAL', label: 'Abogado de tutelas (oficial)', type: 'text' },
      { key: 'ABOGADO_RESPONSABLE', label: 'Firmante en documentos', type: 'text' },
      { key: 'DEPENDENCIA_CANONICAL', label: 'Dependencia (código SED)', type: 'text' },
      { key: 'OFICINA_RESPONSABLE', label: 'Oficina responsable (extraída)', type: 'text' },
      { key: 'ESTADO', label: 'Estado del trámite', type: 'select', options: ['ACTIVO', 'INACTIVO'] },
      { key: 'FECHA_RESPUESTA', label: 'Fecha de respuesta de la SED', type: 'date' },
    ],
  },
  {
    title: 'Fallo de primera instancia',
    fields: [
      { key: 'SENTIDO_FALLO_1ST', label: 'Sentido del fallo', type: 'select', options: ['CONCEDE', 'NIEGA', 'IMPROCEDENTE'] },
      { key: 'FECHA_FALLO_1ST', label: 'Fecha del fallo', type: 'date' },
    ],
  },
  {
    title: 'Recurso de impugnación',
    fields: [
      { key: 'IMPUGNACION', label: '¿Hay impugnación?', type: 'select', options: ['SI', 'NO'] },
      { key: 'QUIEN_IMPUGNO', label: 'Quién impugnó', type: 'select', options: ['Accionante', 'Accionado', 'Vinculado'] },
      { key: 'FOREST_IMPUGNACION', label: 'Radicado FOREST de la impugnación', type: 'text', mono: true },
      { key: 'JUZGADO_2ND', label: 'Juzgado de segunda instancia', type: 'text' },
      { key: 'SENTIDO_FALLO_2ND', label: 'Sentido del fallo de 2da instancia', type: 'select', options: ['Confirma', 'Revoca', 'Modifica'] },
      { key: 'FECHA_FALLO_2ND', label: 'Fecha del fallo de 2da instancia', type: 'date' },
    ],
  },
  {
    title: 'Incidente de desacato (primer trámite)',
    fields: [
      { key: 'INCIDENTE', label: '¿Se abrió incidente?', type: 'select', options: ['SI', 'NO'] },
      { key: 'FECHA_APERTURA_INCIDENTE', label: 'Fecha de apertura del incidente', type: 'date' },
      { key: 'RESPONSABLE_DESACATO', label: 'Responsable del desacato', type: 'text' },
      { key: 'DECISION_INCIDENTE', label: 'Decisión del juez sobre el incidente', type: 'textarea' },
    ],
  },
  {
    title: 'Incidente de desacato (segundo trámite)',
    fields: [
      { key: 'INCIDENTE_2', label: '¿Hay segundo incidente?', type: 'select', options: ['SI', 'NO'] },
      { key: 'FECHA_APERTURA_INCIDENTE_2', label: 'Fecha de apertura', type: 'date' },
      { key: 'RESPONSABLE_DESACATO_2', label: 'Responsable del desacato', type: 'text' },
      { key: 'DECISION_INCIDENTE_2', label: 'Decisión del juez', type: 'textarea' },
    ],
  },
  {
    title: 'Incidente de desacato (tercer trámite)',
    fields: [
      { key: 'INCIDENTE_3', label: '¿Hay tercer incidente?', type: 'select', options: ['SI', 'NO'] },
      { key: 'FECHA_APERTURA_INCIDENTE_3', label: 'Fecha de apertura', type: 'date' },
      { key: 'RESPONSABLE_DESACATO_3', label: 'Responsable del desacato', type: 'text' },
      { key: 'DECISION_INCIDENTE_3', label: 'Decisión del juez', type: 'textarea' },
    ],
  },
  {
    title: 'Observaciones del expediente',
    fields: [
      { key: 'OBSERVACIONES', label: 'Notas y trazabilidad', type: 'textarea' },
    ],
  },
]

// ─── Form Field Component ────────────────────────────────────────────────────

function FormField({ def, value, onChange }: { def: FieldDef; value: string; onChange: (key: string, val: string) => void }) {
  if (def.type === 'textarea') {
    return (
      <Textarea
        value={value}
        onChange={(e) => onChange(def.key, e.target.value)}
        rows={3}
        className={cn('resize-y min-h-[72px]', def.mono && 'font-mono')}
      />
    )
  }

  if (def.type === 'select') {
    return (
      <select
        value={value}
        onChange={(e) => onChange(def.key, e.target.value)}
        className="w-full h-8 text-sm border border-input rounded-lg px-2.5 bg-background focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/30"
      >
        <option value="">— Seleccionar —</option>
        {def.options?.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    )
  }

  // Date fields: DB stores DD/MM/YYYY, HTML date input needs YYYY-MM-DD
  if (def.type === 'date') {
    const toISO = (v: string) => {
      const m = v.match(/^(\d{2})\/(\d{2})\/(\d{4})$/)
      return m ? `${m[3]}-${m[2]}-${m[1]}` : v
    }
    const fromISO = (v: string) => {
      const m = v.match(/^(\d{4})-(\d{2})-(\d{2})$/)
      return m ? `${m[3]}/${m[2]}/${m[1]}` : v
    }
    return (
      <Input
        type="date"
        value={toISO(value)}
        onChange={(e) => onChange(def.key, fromISO(e.target.value))}
      />
    )
  }

  return (
    <Input
      type="text"
      value={value}
      onChange={(e) => onChange(def.key, e.target.value)}
      className={cn(def.mono && 'font-mono')}
    />
  )
}

// ─── Section Component ───────────────────────────────────────────────────────

function FormSection({ section, fields, onChange, defaultOpen = true }: {
  section: SectionDef; fields: Record<string, string>; onChange: (key: string, val: string) => void; defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <Card className="overflow-hidden py-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-muted/50 hover:bg-muted transition-colors"
      >
        <span className="text-sm font-medium text-primary">{section.title}</span>
        {open ? <ChevronUp size={14} className="text-muted-foreground" /> : <ChevronDown size={14} className="text-muted-foreground" />}
      </button>

      {open && (
        <CardContent className="pt-3 pb-4 grid grid-cols-1 md:grid-cols-2 gap-3">
          {section.fields.map((f) => (
            <div key={f.key} className={f.type === 'textarea' || f.key === 'OBSERVACIONES' ? 'col-span-full' : ''}>
              <Label className="text-xs uppercase tracking-wide mb-1 block">{f.label}</Label>
              <FormField def={f} value={fields[f.key] ?? ''} onChange={onChange} />
            </div>
          ))}
        </CardContent>
      )}
    </Card>
  )
}

// ─── Document Panel ──────────────────────────────────────────────────────────

function DocumentPanel({ caseId, docs, onDeleteDoc }: { caseId: number; docs: Array<{ id: number; filename: string; doc_type: string; verificacion?: string; verificacion_detalle?: string }>; onDeleteDoc?: (docId: number) => void }) {
  const [previewDocId, setPreviewDocId] = useState<number | null>(null)
  const [resolveDocId, setResolveDocId] = useState<number | null>(null)
  const [suggestions, setSuggestions] = useState<Array<{ case_id: number; folder_name: string; confidence: string; reason: string }>>([])
  const [loadingSuggest, setLoadingSuggest] = useState(false)
  // Buscador de caso destino (mover documento manualmente a cualquier expediente)
  const [moveSearch, setMoveSearch] = useState('')
  const [moveResults, setMoveResults] = useState<Array<{ id: number; folder_name: string; ACCIONANTE?: string; RADICADO_23_DIGITOS?: string }>>([])
  const [moveLoading, setMoveLoading] = useState(false)
  // Mini-form "Crear expediente" dentro del mismo modal — para cuando el buscador no
  // encuentra el caso destino. Dos modos:
  //  - TUTELA: rad (largo o corto) + accionante → folder_name = "<rad_corto> <ACCIONANTE>".
  //  - COMUNICACION: folder_name libre + obs obligatorio. Carpeta sin radicado (oficios,
  //    comunicaciones, etc.). Marcada con tipo_actuacion=COMUNICACION → excluida del cuadro.
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [createTipo, setCreateTipo] = useState<'TUTELA' | 'COMUNICACION'>('TUTELA')
  const [createRad23, setCreateRad23] = useState('')
  const [createAccionante, setCreateAccionante] = useState('')
  const [createJuzgado, setCreateJuzgado] = useState('')
  const [createCiudad, setCreateCiudad] = useState('')
  const [createFolderName, setCreateFolderName] = useState('')
  const [createObservaciones, setCreateObservaciones] = useState('')
  const [createBusy, setCreateBusy] = useState(false)
  // Modal de reconciliación: se dispara automáticamente cuando un move deja al
  // case origen vacío Y es similar al destino (mismo rad corto, accionante, etc.).
  const [reconcileData, setReconcileData] = useState<CaseCompareResult | null>(null)
  const [reconcileBusy, setReconcileBusy] = useState(false)
  const qc = useQueryClient()

  useEffect(() => {
    const q = moveSearch.trim()
    if (resolveDocId == null || q.length < 2) { setMoveResults([]); return }
    setMoveLoading(true)
    const t = setTimeout(async () => {
      try {
        const data = await getCases({ search: q, per_page: 10 })
        setMoveResults((data?.items ?? []).filter((c: { folder_name?: string }) => c.folder_name !== '__SIN_RADICADO__'))
      } catch { setMoveResults([]) }
      setMoveLoading(false)
    }, 280)
    return () => clearTimeout(t)
  }, [moveSearch, resolveDocId])

  // ── Modal de reconciliación — hooks ANTES del early return (Rules of Hooks) ──
  const [reconcileSelected, setReconcileSelected] = useState<Set<string>>(new Set())
  const [reconcileDelete, setReconcileDelete] = useState(true)
  useEffect(() => {
    if (reconcileData) {
      // Por default todos los exclusivos están seleccionados.
      setReconcileSelected(new Set(reconcileData.exclusive_in_source.map(f => f.field)))
      setReconcileDelete(reconcileData.source_can_be_deleted)
    } else {
      setReconcileSelected(new Set())
    }
  }, [reconcileData])

  // Early return DESPUÉS de todos los hooks: si el caso queda sin docs (p. ej. al
  // mover el último documento a una carpeta nueva) el conteo de hooks no cambia
  // y se evita el crash "Rendered fewer hooks than expected" (pantalla blanca).
  if (!docs?.length) {
    return <div className="text-center py-12 text-muted-foreground text-sm">No hay documentos en este caso</div>
  }

  function getIcon(filename: string) {
    if (filename.toLowerCase().endsWith('.pdf')) return '\uD83D\uDCC4'
    if (filename.toLowerCase().endsWith('.docx') || filename.toLowerCase().endsWith('.doc')) return '\uD83D\uDCDD'
    if (filename.toLowerCase().endsWith('.md')) return '\uD83D\uDCE7'
    if (filename.toLowerCase().match(/\.(png|jpg|jpeg)$/)) return '\uD83D\uDDBC\uFE0F'
    return '\uD83D\uDCCE'
  }

  function canPreview(filename: string) {
    return filename.toLowerCase().match(/\.(pdf|png|jpg|jpeg|docx|doc|md)$/)
  }

  const DOC_TYPE_LABELS: Record<string, string> = {
    AUTO_ADMISORIO: 'Auto Admisorio', SENTENCIA: 'Sentencia', RESPUESTA_DOCX: 'Respuesta',
    GMAIL: 'Correo', SCREENSHOT: 'Captura', IMPUGNACION: 'Impugnacion',
    INCIDENTE: 'Incidente', OTRO: 'Otro',
  }

  const TYPE_COLORS: Record<string, string> = {
    AUTO_ADMISORIO: 'bg-blue-100 text-blue-700', SENTENCIA: 'bg-violet-100 text-violet-700',
    RESPUESTA_DOCX: 'bg-emerald-100 text-emerald-700', GMAIL: 'bg-amber-100 text-amber-700',
    SCREENSHOT: 'bg-muted text-muted-foreground', IMPUGNACION: 'bg-red-100 text-red-700',
    INCIDENTE: 'bg-orange-100 text-orange-700', OTRO: 'bg-muted text-muted-foreground',
  }

  const noPerteneceDocs = docs.filter(d => d.verificacion === 'NO_PERTENECE')
  const sospechosoDocs = docs.filter(d => d.verificacion === 'SOSPECHOSO')

  function resetCreateForm() {
    setShowCreateForm(false); setCreateTipo('TUTELA')
    setCreateRad23(''); setCreateAccionante(''); setCreateJuzgado(''); setCreateCiudad('')
    setCreateFolderName(''); setCreateObservaciones(''); setCreateBusy(false)
  }
  function closeResolve() { setResolveDocId(null); setSuggestions([]); setMoveSearch(''); setMoveResults([]); resetCreateForm() }

  // Abre el panel en modo "buscar caso destino" (cualquier documento, sin auto-sugerencias)
  function openMover(docId: number) {
    setResolveDocId(docId); setSuggestions([]); setMoveSearch(''); setMoveResults([]); resetCreateForm()
  }

  async function handleCreateAndMove() {
    if (resolveDocId == null) return
    const observaciones = createObservaciones.trim()
    setCreateBusy(true)
    try {
      let newCase
      if (createTipo === 'COMUNICACION') {
        const folder = createFolderName.trim()
        if (!folder) { toast.error('Falta el nombre de la carpeta'); setCreateBusy(false); return }
        if (!observaciones) { toast.error('Las observaciones (motivo del traslado) son obligatorias para carpetas sin radicado'); setCreateBusy(false); return }
        newCase = await createCase({
          tipo: 'COMUNICACION',
          folder_name: folder,
          observaciones,
          accionante: createAccionante.trim() || undefined,
        })
      } else {
        const radInput = createRad23.trim()
        const accionante = createAccionante.trim()
        const digits = radInput.replace(/\D/g, '')
        const isShort = /^\s*20\d{2}[\s\-/_]*\d{1,5}(?:[\s\-/_]+\d{1,3})?\s*$/.test(radInput)
        if (digits.length < 21 && !isShort) {
          toast.error('Radicado inválido. Use los 23 dígitos completos o el corto AAAA-NNNNN (ej. 2026-00028 o 2026-00028-00).')
          setCreateBusy(false); return
        }
        if (!accionante) { toast.error('Falta el nombre del accionante'); setCreateBusy(false); return }
        newCase = await createCase({
          radicado_23_digitos: radInput,
          accionante,
          juzgado: createJuzgado.trim() || undefined,
          ciudad: createCiudad.trim() || undefined,
          observaciones: observaciones || undefined,
        })
      }
      toast.success(`Carpeta «${newCase.folder_name}» creada`)
      const moveRes = await moveDocument(resolveDocId, newCase.id)
      toast.success(moveRes?.message || 'Documento movido a la nueva carpeta')
      closeResolve()
      qc.invalidateQueries({ queryKey: ['case'] })
      qc.invalidateQueries({ queryKey: ['cases'] })
      await maybeOfferReconciliation(caseId, newCase.id)
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg || 'No se pudo crear la carpeta')
      setCreateBusy(false)
    }
  }

  // Abre el panel para un doc NO_PERTENECE: además precarga las sugerencias automáticas
  async function handleResolve(docId: number) {
    setResolveDocId(docId); setMoveSearch(''); setMoveResults([]); setLoadingSuggest(true); setSuggestions([])
    try { const data = await suggestDocTarget(docId); setSuggestions(data.suggestions || []) } catch { toast.error('Error buscando sugerencias') }
    setLoadingSuggest(false)
  }

  async function handleMove(docId: number, targetCaseId: number, targetName: string) {
    if (!confirm(`Mover este documento a "${targetName}"?\n\nSi el documento vino por correo, se moverán también todos los adjuntos de ese mismo correo (hermanos viajan juntos).`)) return
    try {
      const data = await moveDocument(docId, targetCaseId)
      toast.success(data?.message || 'Documento movido')
      closeResolve()
      qc.invalidateQueries({ queryKey: ['case'] })
      qc.invalidateQueries({ queryKey: ['cases'] })
      await maybeOfferReconciliation(caseId, targetCaseId)
    } catch { toast.error('Error moviendo documento') }
  }

  // Tras un move, si el case origen quedó vacío Y es similar al destino,
  // ofrecemos al usuario migrar campos exclusivos antes de eliminar el origen.
  async function maybeOfferReconciliation(sourceId: number, targetId: number) {
    try {
      const cmp = await compareCases(sourceId, targetId)
      const hasSignals = (cmp.similarity_signals?.length ?? 0) > 0
      const hasExclusive = (cmp.exclusive_in_source?.length ?? 0) > 0
      if (cmp.source_can_be_deleted && hasSignals && hasExclusive) {
        setReconcileData(cmp)
      }
    } catch {
      // silencioso: la reconciliación es opcional
    }
  }

  async function handleMarkOk(docId: number) {
    try { await markDocOk(docId); toast.success('Documento marcado como OK'); closeResolve(); qc.invalidateQueries({ queryKey: ['case'] }) } catch { toast.error('Error marcando documento') }
  }

  const previewDoc = docs.find(d => d.id === previewDocId)

  async function handleApplyReconciliation() {
    if (!reconcileData) return
    setReconcileBusy(true)
    try {
      const res = await mergeCases(reconcileData.source.id, reconcileData.target.id, {
        fields: Array.from(reconcileSelected),
        merge_observations: reconcileSelected.has('observaciones'),
        delete_source: reconcileDelete,
      })
      const n = res?.migrated?.length ?? 0
      toast.success(`${n} campo${n === 1 ? '' : 's'} migrado${n === 1 ? '' : 's'}${res?.source_deleted ? ' · expediente origen eliminado' : ''}`)
      setReconcileData(null)
      qc.invalidateQueries({ queryKey: ['case'] })
      qc.invalidateQueries({ queryKey: ['cases'] })
    } catch {
      toast.error('Error aplicando reconciliación')
    } finally {
      setReconcileBusy(false)
    }
  }

  return (
    <div>
      {reconcileData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" role="dialog" aria-modal="true">
          <Card className="w-full max-w-2xl max-h-[85vh] overflow-auto">
            <CardContent className="pt-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold flex items-center gap-1.5">
                  <FolderInput size={14} className="text-violet-600" /> Reconciliación de expediente
                </span>
                <button onClick={() => setReconcileData(null)} className="text-xs text-muted-foreground hover:text-foreground">Cerrar</button>
              </div>

              <div className="text-xs space-y-1 p-2.5 rounded-md bg-amber-50 border border-amber-200">
                <p className="font-medium text-amber-900">
                  El expediente origen <span className="font-mono">#{reconcileData.source.id}</span> «{reconcileData.source.folder_name}» quedó vacío después del traslado.
                </p>
                <p className="text-amber-800">
                  Detecto que es similar al destino <span className="font-mono">#{reconcileData.target.id}</span> «{reconcileData.target.folder_name}»:
                </p>
                <ul className="text-amber-800 list-disc pl-5">
                  {reconcileData.similarity_signals.map((s, i) => <li key={i}>{s.label}</li>)}
                </ul>
              </div>

              {reconcileData.exclusive_in_source.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-foreground">Campos con valor en origen que NO están en destino:</p>
                  <div className="space-y-1">
                    {reconcileData.exclusive_in_source.map(f => {
                      const checked = reconcileSelected.has(f.field)
                      return (
                        <label key={f.field} className="flex items-start gap-2 p-2 rounded border border-border hover:bg-muted/50 cursor-pointer text-xs">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => {
                              const next = new Set(reconcileSelected)
                              if (e.target.checked) next.add(f.field); else next.delete(f.field)
                              setReconcileSelected(next)
                            }}
                            className="mt-0.5"
                          />
                          <div className="min-w-0 flex-1">
                            <div className="font-medium text-foreground">{f.label}</div>
                            <div className="font-mono text-[10px] text-muted-foreground break-all">{(f.value || '').slice(0, 200)}{(f.value || '').length > 200 ? '…' : ''}</div>
                            {f.suggested_action === 'merge_text' && f.target_existing && (
                              <div className="text-[10px] text-violet-700 mt-0.5">↳ se fusionará con el texto existente del destino (no lo reemplaza)</div>
                            )}
                          </div>
                        </label>
                      )
                    })}
                  </div>
                </div>
              )}

              {reconcileData.differs.length > 0 && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                    Campos que difieren ({reconcileData.differs.length}) — informativo, NO se tocan
                  </summary>
                  <div className="mt-1.5 space-y-1 pl-2 border-l-2 border-border">
                    {reconcileData.differs.map(d => (
                      <div key={d.field} className="text-[10px]">
                        <div className="font-medium">{d.label}</div>
                        <div className="text-muted-foreground">origen: {d.source_value.slice(0, 80)}{d.source_value.length > 80 ? '…' : ''}</div>
                        <div className="text-muted-foreground">destino: {d.target_value.slice(0, 80)}{d.target_value.length > 80 ? '…' : ''}</div>
                      </div>
                    ))}
                  </div>
                </details>
              )}

              <label className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={reconcileDelete}
                  onChange={(e) => setReconcileDelete(e.target.checked)}
                  disabled={!reconcileData.source_can_be_deleted}
                />
                <span>
                  Eliminar el expediente origen <span className="font-mono">#{reconcileData.source.id}</span> después de migrar
                  {!reconcileData.source_can_be_deleted && <span className="text-amber-700"> (no se puede: aún tiene documentos/emails)</span>}
                </span>
              </label>

              <div className="flex gap-2 pt-1">
                <Button onClick={handleApplyReconciliation} disabled={reconcileBusy || reconcileSelected.size === 0} className="flex-1">
                  {reconcileBusy ? (<><Loader2 size={12} className="animate-spin mr-1.5" /> Aplicando…</>) : `Migrar ${reconcileSelected.size} campo${reconcileSelected.size === 1 ? '' : 's'}${reconcileDelete ? ' y eliminar origen' : ''}`}
                </Button>
                <Button variant="outline" onClick={() => setReconcileData(null)} disabled={reconcileBusy}>Mantener como está</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
      {noPerteneceDocs.length > 0 && (
        <Alert variant="destructive" className="mx-4 mt-3">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {noPerteneceDocs.length} documento{noPerteneceDocs.length > 1 ? 's' : ''} NO pertenece{noPerteneceDocs.length > 1 ? 'n' : ''} a este caso. Usa el boton "Resolver" para reasignarlos.
          </AlertDescription>
        </Alert>
      )}
      {sospechosoDocs.length > 0 && (
        <div className="mx-4 mt-2 p-2 bg-amber-50 border border-amber-200 rounded-lg">
          <div className="flex items-center gap-2 text-amber-700 text-xs font-medium">
            <AlertCircle size={12} />
            {sospechosoDocs.length} documento{sospechosoDocs.length > 1 ? 's' : ''} sospechoso{sospechosoDocs.length > 1 ? 's' : ''}
          </div>
        </div>
      )}

      {resolveDocId != null && (() => {
        const rdoc = docs.find(d => d.id === resolveDocId)
        const isMisfiled = rdoc?.verificacion === 'NO_PERTENECE' || rdoc?.verificacion === 'SOSPECHOSO'
        return (
        <Card className={cn('mx-4 mt-3', isMisfiled && 'border-destructive')}>
          <CardContent className="pt-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium flex items-center gap-1.5"><FolderInput size={14} /> Mover documento a otro expediente</span>
              <button onClick={closeResolve} className="text-xs text-muted-foreground hover:text-foreground">Cerrar</button>
            </div>
            <p className="text-xs text-muted-foreground truncate" title={rdoc?.filename}>{rdoc?.filename}</p>

            {/* Buscador de caso destino — escribe radicado, accionante o nombre de carpeta */}
            <div>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" size={13} />
                <Input
                  autoFocus
                  placeholder="Buscar expediente por radicado, accionante o carpeta…"
                  value={moveSearch}
                  onChange={(e) => setMoveSearch(e.target.value)}
                  className="pl-8 h-8 text-sm"
                />
              </div>
              {moveSearch.trim().length >= 2 && (
                <div className="mt-1.5 max-h-56 overflow-y-auto rounded-lg border border-border divide-y divide-border">
                  {moveLoading ? (
                    <div className="flex items-center gap-2 text-xs text-muted-foreground p-2"><Loader2 size={13} className="animate-spin" /> Buscando…</div>
                  ) : moveResults.length === 0 ? (
                    <div className="text-xs text-muted-foreground p-2">Sin coincidencias</div>
                  ) : moveResults.map((c) => (
                    <button
                      key={c.id}
                      onClick={() => handleMove(resolveDocId, c.id, c.folder_name)}
                      className="w-full text-left flex items-center justify-between gap-2 p-2 hover:bg-primary/5 transition-colors"
                    >
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-foreground truncate">{c.folder_name}</p>
                        <p className="text-[10px] text-muted-foreground truncate">
                          {c.ACCIONANTE || '(sin accionante)'}{c.RADICADO_23_DIGITOS ? ` · ${c.RADICADO_23_DIGITOS}` : ''}
                        </p>
                      </div>
                      <FolderInput size={13} className="text-primary shrink-0" />
                    </button>
                  ))}
                </div>
              )}
              <p className="text-[10px] text-muted-foreground mt-1">Si el documento llegó por correo, se moverán también los demás adjuntos de ese mismo correo (hermanos viajan juntos).</p>

              {/* Crear carpeta nueva — TUTELA (con radicado) o COMUNICACION (libre, sin radicado).
                  Uso típico de COMUNICACION: el doc es un oficio/comunicación que no pertenece a
                  ninguna tutela y no tiene radicado propio. */}
              {!showCreateForm ? (
                <button
                  onClick={() => setShowCreateForm(true)}
                  className="mt-2 flex items-center gap-1.5 text-xs text-primary hover:underline"
                  title="Crear una carpeta nueva (tutela con radicado o comunicación libre) y mover este documento allí"
                >
                  <FolderPlus size={13} /> ¿No encuentras dónde poner el documento? Crear carpeta nueva
                </button>
              ) : (
                <div className="mt-2 p-2.5 rounded-lg border border-primary/30 bg-primary/5 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium flex items-center gap-1.5"><FolderPlus size={13} /> Crear carpeta nueva</span>
                    <button onClick={resetCreateForm} className="text-[10px] text-muted-foreground hover:text-foreground">Cancelar</button>
                  </div>

                  {/* Toggle tipo */}
                  <div role="radiogroup" aria-label="Tipo de carpeta" className="grid grid-cols-2 gap-1 p-0.5 bg-background border border-border rounded-md">
                    <button
                      role="radio"
                      aria-checked={createTipo === 'TUTELA'}
                      onClick={() => setCreateTipo('TUTELA')}
                      className={`text-[11px] py-1 px-2 rounded transition-colors ${
                        createTipo === 'TUTELA'
                          ? 'bg-primary text-primary-foreground shadow-sm'
                          : 'text-muted-foreground hover:bg-muted'
                      }`}
                    >
                      Tutela (con radicado)
                    </button>
                    <button
                      role="radio"
                      aria-checked={createTipo === 'COMUNICACION'}
                      onClick={() => setCreateTipo('COMUNICACION')}
                      className={`text-[11px] py-1 px-2 rounded transition-colors ${
                        createTipo === 'COMUNICACION'
                          ? 'bg-violet-600 text-white shadow-sm'
                          : 'text-muted-foreground hover:bg-muted'
                      }`}
                      title="Carpeta libre sin radicado — para oficios/comunicaciones. Excluida del cuadro Excel."
                    >
                      📨 Comunicación (sin radicado)
                    </button>
                  </div>

                  {createTipo === 'TUTELA' ? (
                    <div className="grid grid-cols-1 gap-1.5">
                      <div>
                        <Input
                          placeholder="Radicado: 23 dígitos o corto 2026-00028"
                          value={createRad23}
                          onChange={(e) => setCreateRad23(e.target.value)}
                          className="h-8 text-xs font-mono"
                          maxLength={25}
                        />
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                          Si el juzgado no proporcionó los 23 dígitos, usa el corto (ej. <span className="font-mono">2026-00028</span>) — el expediente quedará en <span className="font-medium">REVISIÓN</span> hasta que se complete.
                        </p>
                      </div>
                      <Input
                        placeholder="Accionante (nombre completo)"
                        value={createAccionante}
                        onChange={(e) => setCreateAccionante(e.target.value)}
                        className="h-8 text-xs"
                      />
                      <div className="grid grid-cols-2 gap-1.5">
                        <Input
                          placeholder="Juzgado (opcional)"
                          value={createJuzgado}
                          onChange={(e) => setCreateJuzgado(e.target.value)}
                          className="h-8 text-xs"
                        />
                        <Input
                          placeholder="Ciudad (opcional)"
                          value={createCiudad}
                          onChange={(e) => setCreateCiudad(e.target.value)}
                          className="h-8 text-xs"
                        />
                      </div>
                      <textarea
                        placeholder="Observaciones / motivo del traslado (opcional)"
                        value={createObservaciones}
                        onChange={(e) => setCreateObservaciones(e.target.value)}
                        className="text-xs px-2.5 py-1.5 border border-input rounded-md bg-background focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/30 min-h-[44px] resize-y"
                        maxLength={500}
                      />
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 gap-1.5">
                      <div>
                        <Input
                          placeholder="Nombre de la carpeta (ej. Oficio Procuraduria 1234)"
                          value={createFolderName}
                          onChange={(e) => setCreateFolderName(e.target.value)}
                          className="h-8 text-xs"
                          maxLength={200}
                        />
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                          Texto libre — sin radicado. Esta carpeta queda marcada como <span className="font-medium text-violet-700">📨 Comunicación</span> y <span className="font-medium">no aparece en el cuadro Excel</span> de tutelas.
                        </p>
                      </div>
                      <Input
                        placeholder="Accionante / remitente (opcional)"
                        value={createAccionante}
                        onChange={(e) => setCreateAccionante(e.target.value)}
                        className="h-8 text-xs"
                      />
                      <div>
                        <textarea
                          placeholder="Observaciones / motivo del traslado (obligatorio)"
                          value={createObservaciones}
                          onChange={(e) => setCreateObservaciones(e.target.value)}
                          className="w-full text-xs px-2.5 py-1.5 border border-input rounded-md bg-background focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/30 min-h-[56px] resize-y"
                          maxLength={500}
                          required
                        />
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                          {createObservaciones.length}/500 — ej: <em>"Doc no pertenecía al expediente 2026-00095. Es un oficio de la Procuraduría sin radicado propio."</em>
                        </p>
                      </div>
                    </div>
                  )}

                  <Button size="xs" onClick={handleCreateAndMove} disabled={createBusy} className="w-full">
                    {createBusy ? (<><Loader2 size={12} className="animate-spin mr-1.5" /> Creando y moviendo…</>) : 'Crear carpeta y mover documento'}
                  </Button>
                  <p className="text-[10px] text-muted-foreground">Se crea la carpeta en disco y se trasladan el documento + sus hermanos del mismo correo.</p>
                </div>
              )}
            </div>

            {/* Sugerencias automáticas (cuando se abrió desde "Resolver" en un doc NO_PERTENECE) */}
            {(loadingSuggest || suggestions.length > 0) && (
              <div className="space-y-1.5">
                <p className="text-xs text-muted-foreground font-medium">Sugerencias automáticas:</p>
                {loadingSuggest ? (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground py-1"><Loader2 size={13} className="animate-spin" /> Buscando…</div>
                ) : suggestions.map(s => (
                  <div key={s.case_id} className="flex items-center justify-between bg-muted p-2 rounded-lg text-xs">
                    <div className="min-w-0">
                      <p className="font-medium text-foreground truncate">{s.folder_name}</p>
                      <p className="text-muted-foreground">{s.reason}</p>
                      <StatusBadge type="status" value={s.confidence === 'ALTA' ? 'ok' : s.confidence === 'MEDIA' ? 'warning' : 'unknown'} className="mt-1" />
                    </div>
                    <Button size="xs" onClick={() => handleMove(resolveDocId, s.case_id, s.folder_name)} className="ml-2">Mover</Button>
                  </div>
                ))}
              </div>
            )}

            {isMisfiled && (
              <>
                <Separator />
                <Button variant="outline" size="xs" onClick={() => handleMarkOk(resolveDocId)} className="text-emerald-700 border-emerald-200 hover:bg-emerald-50">
                  No, sí pertenece a este caso (marcar OK)
                </Button>
              </>
            )}
          </CardContent>
        </Card>
        )
      })()}

      {previewDoc && canPreview(previewDoc.filename) && (
        <div className="border-b border-border">
          <div className="flex items-center justify-between gap-2 px-4 py-1.5 bg-muted">
            <span className="text-xs font-medium text-foreground truncate" title={previewDoc.filename}>{previewDoc.filename}</span>
            <div className="flex items-center gap-3 shrink-0">
              {previewDoc.verificacion === 'SOSPECHOSO' && (
                <Button variant="outline" size="xs" onClick={() => handleMarkOk(previewDoc.id)} className="text-emerald-700 border-emerald-200 hover:bg-emerald-50" title="Marcar como correcto: quita el estado 'sospechoso'">
                  No es sospechoso
                </Button>
              )}
              <button onClick={() => openMover(previewDoc.id)} className="flex items-center gap-1 text-xs text-primary hover:underline" title="Trasladar este documento a otro expediente">
                <FolderInput size={13} /> Trasladar
              </button>
              <button onClick={() => onDeleteDoc?.(previewDoc.id)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-destructive transition-colors" title="Eliminar este documento">
                <Trash2 size={13} /> Eliminar
              </button>
              <a href={getDocumentPreviewUrl(previewDoc.id)} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">Abrir en pestaña</a>
              <button onClick={() => setPreviewDocId(null)} className="text-xs text-muted-foreground hover:text-foreground">Cerrar</button>
            </div>
          </div>
          <iframe src={getDocumentPreviewUrl(previewDoc.id)} className="w-full bg-card" style={{ height: '500px' }} title={previewDoc.filename} />
        </div>
      )}

      <div className="divide-y divide-border">
        {docs.map((doc) => (
          <div
            key={doc.id}
            onClick={() => canPreview(doc.filename) ? setPreviewDocId(doc.id === previewDocId ? null : doc.id) : window.open(getDocumentPreviewUrl(doc.id), '_blank')}
            className={cn(
              'flex items-start gap-3 px-4 py-3 cursor-pointer transition-colors group',
              doc.id === previewDocId ? 'bg-primary/10' : 'hover:bg-primary/5'
            )}
          >
            <span className="text-lg flex-shrink-0 mt-0.5">{getIcon(doc.filename)}</span>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-foreground group-hover:text-primary truncate font-medium transition-colors max-w-[280px]" title={doc.filename}>
                {doc.filename}
              </p>
              <div className="flex items-center gap-1 mt-1 flex-wrap">
                <Badge variant="secondary" className={cn('text-[10px]', TYPE_COLORS[doc.doc_type])}>
                  {DOC_TYPE_LABELS[doc.doc_type] ?? doc.doc_type}
                </Badge>
                {doc.verificacion === 'NO_PERTENECE' && <Badge variant="destructive" className="text-[10px]">NO PERTENECE</Badge>}
                {doc.verificacion === 'SOSPECHOSO' && <Badge variant="outline" className="text-[10px] text-amber-700 border-amber-200 bg-amber-50">Sospechoso</Badge>}
                {doc.verificacion === 'OK' && <span className="text-xs text-emerald-600" title="Verificado">{'\u2713'}</span>}
              </div>
            </div>
            <div className="flex flex-col items-end gap-1 flex-shrink-0 mt-1">
              {doc.verificacion === 'NO_PERTENECE' ? (
                <Button variant="destructive" size="xs" onClick={(e) => { e.stopPropagation(); handleResolve(doc.id) }}>Resolver</Button>
              ) : doc.verificacion === 'SOSPECHOSO' ? (
                <Button variant="outline" size="xs" onClick={(e) => { e.stopPropagation(); handleMarkOk(doc.id) }} className="text-emerald-700 border-emerald-200 hover:bg-emerald-50" title="Marcar como correcto: quita el estado 'sospechoso'">
                  No es sospechoso
                </Button>
              ) : canPreview(doc.filename) ? (
                <span className="text-xs text-muted-foreground">Vista previa</span>
              ) : (
                <ExternalLink size={14} className="text-muted-foreground group-hover:text-primary transition-colors" />
              )}
              <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button
                  onClick={(e) => { e.stopPropagation(); openMover(doc.id) }}
                  className="text-muted-foreground hover:text-primary transition-colors"
                  title="Mover este documento a otro expediente"
                >
                  <FolderInput size={12} />
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); onDeleteDoc?.(doc.id) }}
                  className="text-muted-foreground hover:text-destructive transition-colors"
                  title="Eliminar documento"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Resizable Panels ─────────────────────────────────────────────────────

function ResizablePanels({ caseData, fields, handleChange, onDeleteDoc }: {
  caseData: Record<string, unknown>; fields: Record<string, string>; handleChange: (key: string, value: string) => void; onDeleteDoc?: (docId: number) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [dividerX, setDividerX] = useState(60)
  const [isDragging, setIsDragging] = useState(false)

  const onMouseDown = useCallback((e: React.MouseEvent) => { e.preventDefault(); setIsDragging(true) }, [])

  useEffect(() => {
    if (!isDragging) return
    const onMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      const pct = ((e.clientX - rect.left) / rect.width) * 100
      setDividerX(Math.max(30, Math.min(80, pct)))
    }
    const onMouseUp = () => setIsDragging(false)
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => { document.removeEventListener('mousemove', onMouseMove); document.removeEventListener('mouseup', onMouseUp) }
  }, [isDragging])

  const docs = (caseData.documents ?? []) as Array<{ id: number; filename: string; doc_type: string; verificacion?: string; verificacion_detalle?: string }>

  return (
    <div ref={containerRef} className="flex-1 overflow-hidden flex min-h-0" style={{ cursor: isDragging ? 'col-resize' : undefined }}>
      <div className="overflow-y-auto p-6 space-y-3 min-w-0" style={{ width: `${dividerX}%` }}>
        {SECTIONS.map((section, i) => (
          <FormSection key={section.title} section={section} fields={fields} onChange={handleChange} defaultOpen={i < 3} />
        ))}
        <div className="h-6" />
      </div>

      <div
        onMouseDown={onMouseDown}
        className={cn(
          'hidden lg:flex w-2 flex-shrink-0 cursor-col-resize items-center justify-center transition-colors',
          isDragging ? 'bg-primary/20' : 'bg-muted hover:bg-primary/10'
        )}
      >
        <div className={cn('w-0.5 h-8 rounded-full transition-colors', isDragging ? 'bg-primary' : 'bg-border')} />
      </div>

      <div className="flex flex-col min-h-0 min-w-0 border-l border-border" style={{ width: `${100 - dividerX}%` }}>
        <RightPanelWithTabs caseId={caseData.id as number} docs={docs} onDeleteDoc={onDeleteDoc as (docId: number) => void} />
      </div>
    </div>
  )
}

// ─── Right Panel con tabs ─────────────────────

function RightPanelWithTabs({ caseId, docs, onDeleteDoc }: {
  caseId: number; docs: Array<{ id: number; filename: string; doc_type: string; verificacion?: string; verificacion_detalle?: string }>; onDeleteDoc: (docId: number) => void
}) {
  const [tab, setTab] = useState<'docs' | 'emails'>('docs')
  const packagesQ = useQuery({ queryKey: ['case-email-packages', caseId], queryFn: () => getCaseEmailPackages(caseId), enabled: tab === 'emails' })

  const TabButton = ({ id, icon, label, badge }: { id: typeof tab; icon: React.ReactNode; label: string; badge?: React.ReactNode }) => (
    <button
      onClick={() => setTab(id)}
      className={cn(
        'flex-1 px-3 py-2.5 text-sm font-medium flex items-center justify-center gap-2 border-b-2 transition-colors',
        tab === id ? 'border-primary text-primary bg-card' : 'border-transparent text-muted-foreground hover:text-foreground'
      )}
    >
      {icon}
      {label}
      {badge}
    </button>
  )

  return (
    <>
      <div className="flex-shrink-0 bg-muted border-b border-border">
        <div className="flex">
          <TabButton id="docs" icon={<FileText size={14} />} label={`Documentos (${docs.length})`} />
          <TabButton id="emails" icon={<Mail size={14} />} label="Correos" badge={
            packagesQ.data && packagesQ.data.packages_count > 0 ? (
              <Badge variant="secondary" className="text-[10px] px-1.5">{packagesQ.data.packages_count}</Badge>
            ) : undefined
          } />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {tab === 'docs' && <DocumentPanel caseId={caseId} docs={docs} onDeleteDoc={onDeleteDoc} />}
        {tab === 'emails' && <EmailPackagesTimeline query={packagesQ} />}
      </div>
    </>
  )
}

function EmailPackagesTimeline({ query }: { query: any }) {
  if (query.isLoading) {
    return <div className="p-6 flex items-center justify-center text-muted-foreground"><Loader2 className="animate-spin" size={16} /><span className="ml-2 text-xs">Cargando paquetes...</span></div>
  }
  if (query.isError) return <div className="p-4 text-xs text-destructive">Error al cargar paquetes email</div>
  const data = query.data
  if (!data || data.packages_count === 0) {
    return (
      <div className="p-6 text-center text-muted-foreground">
        <Mail size={32} className="mx-auto mb-2 opacity-30" />
        <p className="text-xs">Sin paquetes email vinculados</p>
        <p className="text-[10px] mt-1">Este caso no tiene correos con documents vinculados (v4.8 Provenance).</p>
      </div>
    )
  }

  return (
    <div className="p-4 space-y-3">
      <p className="text-[11px] text-muted-foreground mb-2">
        {data.packages_count} {data.packages_count === 1 ? 'correo vinculado' : 'correos vinculados'} — cada uno es un paquete inmutable (body + adjuntos).
      </p>
      {data.packages.map((pkg: any) => (
        <Card key={pkg.email_id} className="hover:ring-1 hover:ring-primary/20 transition-all py-0">
          <div className="px-3 py-2 bg-primary/5 border-b border-border rounded-t-lg">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <Package size={13} className="text-primary shrink-0" />
                <span className="text-xs font-medium text-foreground truncate">{pkg.subject || '(Sin asunto)'}</span>
              </div>
              <Badge variant="secondary" className="text-[10px]">{pkg.document_count} {pkg.document_count === 1 ? 'doc' : 'docs'}</Badge>
            </div>
            <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
              <span className="truncate max-w-[160px]">{pkg.sender}</span>
              {pkg.date_received && <span>{'\u00B7'} {new Date(pkg.date_received).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: '2-digit' })}</span>}
            </div>
          </div>
          <CardContent className="p-2 space-y-0.5">
            {pkg.documents.map((doc: any) => (
              <div key={doc.id} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted">
                <FileText size={11} className="text-muted-foreground shrink-0" />
                <span className="text-[11px] text-foreground truncate flex-1">{doc.filename}</span>
                <span className="text-[9px] text-muted-foreground shrink-0">{doc.doc_type}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

// ─── Main Component ──────────────────────────────────────────────────────

export default function CaseDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const caseId = parseInt(id ?? '0', 10)
  const [historialOpen, setHistorialOpen] = useState(false)

  const caseQ = useQuery({ queryKey: ['case', caseId], queryFn: () => getCase(caseId), enabled: !!caseId })
  const acumQ = useQuery({
    queryKey: ['case-acumulacion', caseId],
    queryFn: () => getCaseAcumulacion(caseId),
    enabled: !!caseId,
    staleTime: 60_000,
  })

  const [fields, setFields] = useState<Record<string, string>>({})
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (caseQ.data) {
      const initial: Record<string, string> = {}
      SECTIONS.forEach((s) => { s.fields.forEach((f) => { initial[f.key] = caseQ.data[f.key] ?? '' }) })
      setFields(initial)
      setDirty(false)
    }
  }, [caseQ.data])

  const saveMutation = useMutation({
    mutationFn: () => updateCase(caseId, fields),
    onSuccess: () => { toast.success('Caso actualizado exitosamente'); qc.invalidateQueries({ queryKey: ['case', caseId] }); qc.invalidateQueries({ queryKey: ['cases'] }); setDirty(false) },
    onError: () => toast.error('Error al guardar los cambios'),
  })

  const syncMutation = useMutation({
    mutationFn: () => syncSingleCase(caseId),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['case', caseId] })
      if (data.docs_added > 0 || data.docs_removed > 0 || data.docs_moved > 0 || data.docs_suspicious > 0) toast.success(data.message)
      else toast('Carpeta sincronizada, sin cambios', { icon: '\u2705' })
    },
    onError: () => toast.error('Error al sincronizar carpeta'),
  })

  const deleteCaseMut = useMutation({
    mutationFn: () => {
      if (!window.confirm(`Eliminar caso "${caseQ.data?.folder_name}"?\n\nSe eliminara la carpeta y todos los documentos del disco. Esta accion NO se puede deshacer.`)) throw new Error('Cancelado')
      return deleteCase(caseId)
    },
    onSuccess: (data) => { toast.success(data.message); qc.invalidateQueries({ queryKey: ['cases'] }); navigate('/cases') },
    onError: (e) => { if ((e as Error).message !== 'Cancelado') toast.error('Error al eliminar') },
  })

  const renameMutation = useMutation({
    mutationFn: () => {
      const current = caseQ.data?.folder_name ?? ''
      const v = window.prompt('Nuevo nombre de la carpeta del expediente:', current)
      if (v === null) throw new Error('Cancelado')
      const name = v.trim()
      if (!name || name === current) throw new Error('Cancelado')
      return renameCaseFolder(caseId, name)
    },
    onSuccess: () => { toast.success('Carpeta renombrada'); qc.invalidateQueries({ queryKey: ['case', caseId] }); qc.invalidateQueries({ queryKey: ['cases'] }) },
    onError: (e) => {
      if ((e as Error).message === 'Cancelado') return
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail || 'No se pudo renombrar la carpeta')
    },
  })

  const deleteDocMut = useMutation({
    mutationFn: (docId: number) => {
      if (!window.confirm('Eliminar este documento del caso y del disco?')) throw new Error('Cancelado')
      return deleteDocument(caseId, docId)
    },
    onSuccess: (data) => { toast.success(data.message); qc.invalidateQueries({ queryKey: ['case', caseId] }) },
    onError: (e) => { if ((e as Error).message !== 'Cancelado') toast.error('Error al eliminar documento') },
  })

  // Sujetos de especial protección detectados por v9 (sembrado en `observaciones`) —
  // indicador pasivo para el operador: el expediente trae datos sensibles, manejar con reserva.
  const _obsText = String((caseQ.data as any)?.OBSERVACIONES ?? '')
  const sensitiveCategories: string[] = (() => {
    const m = _obsText.match(/Sujeto de especial protecci[oó]n:\s*([^\n]+)/i)
    return m ? m[1].split(',').map((s) => s.trim()).filter(Boolean) : []
  })()
  const hasMedidaProvisional = /Se solicit[oó] medida provisional/i.test(_obsText)

  function handleChange(key: string, val: string) { setFields((prev) => ({ ...prev, [key]: val })); setDirty(true) }

  if (caseQ.isLoading) {
    return <div className="flex items-center justify-center h-64"><Loader2 size={32} className="animate-spin text-primary" /></div>
  }

  if (caseQ.isError || !caseQ.data) {
    return (
      <div className="p-6">
        <Alert variant="destructive">
          <AlertCircle className="h-5 w-5" />
          <AlertDescription>
            <p className="font-semibold">Error al cargar el caso</p>
            <p className="text-sm mt-1">No se pudo obtener la informacion del caso #{caseId}</p>
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const caseData = caseQ.data

  return (
    <div className="h-full flex flex-col">
      {/* Top bar */}
      <div className="flex-shrink-0 flex items-center justify-between px-6 py-3 bg-card border-b border-border">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => {
              // Volver a la página anterior (Seguimiento, Cuadro, Auditoría, etc.).
              // Si no hay historial (acceso directo por URL), caer a /cases.
              if (window.history.length > 1) navigate(-1)
              else navigate('/cases')
            }}
            title="Volver"
          >
            <ArrowLeft size={16} />
          </Button>
          <div>
            <div className="flex items-center gap-1.5">
              <h1 className="text-sm font-semibold text-foreground leading-tight">{caseData.folder_name}</h1>
              <Button
                variant="ghost"
                size="icon-sm"
                className="h-5 w-5 text-muted-foreground hover:text-foreground"
                title="Renombrar carpeta del expediente"
                onClick={() => renameMutation.mutate()}
                disabled={renameMutation.isPending}
              >
                {renameMutation.isPending ? <Loader2 size={11} className="animate-spin" /> : <Pencil size={11} />}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              Expediente #{caseId} · {caseData.documents?.length ?? 0} documento{(caseData.documents?.length ?? 0) === 1 ? '' : 's'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {Boolean(caseData.ESTADO) && (
            <Badge
              variant="outline"
              className={(caseData.ESTADO as string) === 'ACTIVO'
                ? 'text-emerald-700 border-emerald-200 bg-emerald-50'
                : 'text-slate-600 border-slate-200 bg-slate-50'}
              title="Estado procesal del expediente (cuadro vivo)"
            >
              {caseData.ESTADO as string}
            </Badge>
          )}
          {sensitiveCategories.length > 0 && (
            <Badge variant="outline" className="text-rose-700 border-rose-200 bg-rose-50 gap-1" title={`Datos sensibles — manejar con reserva (iniciales, no compartir nombres externamente). Detectado: ${sensitiveCategories.join(', ')}`}>
              <Lock size={11} />
              {sensitiveCategories.includes('menor de edad') ? 'Menor de edad' : 'Datos sensibles'}
              {sensitiveCategories.length > 1 ? ` +${sensitiveCategories.length - 1}` : ''}
            </Badge>
          )}
          {hasMedidaProvisional && (
            <Badge variant="outline" className="text-amber-700 border-amber-200 bg-amber-50" title="El escrito de tutela solicitó medida provisional / cautelar">
              Medida provisional
            </Badge>
          )}
          {dirty && <Badge variant="outline" className="text-amber-700 border-amber-200 bg-amber-50">Cambios sin guardar</Badge>}
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setHistorialOpen(true)}
            title="Ver historial completo del expediente (creación, cambios, traslados, correos)"
          >
            <History size={14} />
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending} title="Sincronizar carpeta">
            <RefreshCw size={14} className={syncMutation.isPending || caseQ.isFetching ? 'animate-spin' : ''} />
          </Button>
          <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending || !dirty}>
            {saveMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            Guardar
          </Button>
          <Button variant="ghost" size="icon-sm" onClick={() => deleteCaseMut.mutate()} disabled={deleteCaseMut.isPending} className="text-destructive hover:text-destructive" title="Eliminar caso">
            <Trash2 size={14} />
          </Button>
        </div>
      </div>

      {acumQ.data && acumQ.data.tipo && (
        <AcumulacionBanner data={acumQ.data} onNavigate={(id) => navigate(`/cases/${id}`)} />
      )}

      <ResizablePanels caseData={caseData} fields={fields} handleChange={handleChange} onDeleteDoc={(docId) => deleteDocMut.mutate(docId)} />

      <HistorialModal
        caseId={historialOpen ? caseId : null}
        caseLabel={caseData?.folder_name as string | undefined}
        onClose={() => setHistorialOpen(false)}
      />
    </div>
  )
}

function AcumulacionBanner({ data, onNavigate }: { data: import('../services/api').CaseAcumulacion; onNavigate: (id: number) => void }) {
  if (!data.tipo) return null
  const isRector = data.tipo === 'RECTOR'
  const accent = isRector ? 'bg-indigo-50 border-indigo-200 text-indigo-900' : 'bg-amber-50 border-amber-200 text-amber-900'
  const radCorto = (rad?: string) => (rad && rad.length >= 21 ? `${rad.slice(12, 16)}-${rad.slice(16, 21)}` : rad ?? '')
  return (
    <div className={`flex-shrink-0 flex items-start gap-2.5 px-6 py-2.5 border-b ${accent}`}>
      <Link2 size={14} className="mt-0.5 flex-shrink-0" />
      <div className="text-xs leading-relaxed flex-1">
        {isRector ? (
          <>
            <span className="font-semibold">Expediente rector de acumulación.</span>{' '}
            {data.acumulados.length > 0 ? (
              <>
                Acumula a este despacho{' '}
                {data.acumulados.map((c, i) => (
                  <span key={c.id}>
                    {i > 0 && (i === data.acumulados.length - 1 ? ' y ' : ', ')}
                    <button
                      type="button"
                      className="font-medium underline decoration-dotted hover:decoration-solid"
                      onClick={() => onNavigate(c.id)}
                      title={c.folder_name}
                    >
                      #{c.id} ({radCorto(c.radicado_23_digitos)})
                    </button>
                  </span>
                ))}.
              </>
            ) : (
              <span>(sin acumulados registrados)</span>
            )}
            {data.fecha && <span className="ml-1 text-indigo-700/70">Auto del {data.fecha}.</span>}
          </>
        ) : (
          <>
            <span className="font-semibold">Expediente acumulado.</span>{' '}
            {data.rector ? (
              <>
                Fue acumulado al expediente{' '}
                <button
                  type="button"
                  className="font-medium underline decoration-dotted hover:decoration-solid"
                  onClick={() => data.rector && onNavigate(data.rector.id)}
                  title={data.rector.folder_name}
                >
                  #{data.rector.id} ({radCorto(data.rector.radicado_23_digitos)})
                </button>
                {data.fecha && <span className="text-amber-700/70"> por auto del {data.fecha}</span>}.
                <span className="block text-amber-700/70 mt-0.5">Las pretensiones y la sentencia se resuelven conjuntamente en el rector.</span>
              </>
            ) : (
              <span>(rector no identificado)</span>
            )}
          </>
        )}
      </div>
    </div>
  )
}
