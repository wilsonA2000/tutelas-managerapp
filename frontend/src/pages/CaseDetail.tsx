import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Save, FileText, ExternalLink, Loader2,
  AlertCircle, RefreshCw, ChevronDown, ChevronUp, Trash2,
} from 'lucide-react'
import { getCase, updateCase, getDocumentPreviewUrl, syncSingleCase, deleteCase, deleteDocument } from '../services/api'

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
    title: 'Identificacion',
    fields: [
      { key: 'RADICADO_23_DIGITOS', label: 'Radicado 23 Digitos', type: 'text', mono: true },
      { key: 'RADICADO_FOREST', label: 'Radicado FOREST', type: 'text', mono: true },
    ],
  },
  {
    title: 'Partes',
    fields: [
      { key: 'ACCIONANTE', label: 'Accionante', type: 'text' },
      { key: 'ACCIONADOS', label: 'Accionados', type: 'textarea' },
      { key: 'VINCULADOS', label: 'Vinculados', type: 'textarea' },
    ],
  },
  {
    title: 'Proceso',
    fields: [
      { key: 'JUZGADO', label: 'Juzgado', type: 'text' },
      { key: 'CIUDAD', label: 'Ciudad', type: 'text' },
      { key: 'FECHA_INGRESO', label: 'Fecha de Ingreso', type: 'date' },
      { key: 'DERECHO_VULNERADO', label: 'Derecho Vulnerado', type: 'textarea' },
      { key: 'ASUNTO', label: 'Asunto', type: 'textarea' },
      { key: 'PRETENSIONES', label: 'Pretensiones', type: 'textarea' },
    ],
  },
  {
    title: 'Gestion',
    fields: [
      { key: 'OFICINA_RESPONSABLE', label: 'Oficina Responsable', type: 'text' },
      { key: 'ABOGADO_RESPONSABLE', label: 'Abogado Responsable', type: 'text' },
      {
        key: 'ESTADO', label: 'Estado', type: 'select',
        options: ['ACTIVO', 'INACTIVO'],
      },
      { key: 'FECHA_RESPUESTA', label: 'Fecha de Respuesta', type: 'date' },
    ],
  },
  {
    title: 'Fallo Primera Instancia',
    fields: [
      {
        key: 'SENTIDO_FALLO_1ST', label: 'Sentido del Fallo', type: 'select',
        options: ['CONCEDE', 'NIEGA', 'IMPROCEDENTE'],
      },
      { key: 'FECHA_FALLO_1ST', label: 'Fecha del Fallo', type: 'date' },
    ],
  },
  {
    title: 'Impugnacion',
    fields: [
      {
        key: 'IMPUGNACION', label: 'Impugnacion', type: 'select',
        options: ['SI', 'NO'],
      },
      {
        key: 'QUIEN_IMPUGNO', label: 'Quien Impugno', type: 'select',
        options: ['Accionante', 'Accionado', 'Vinculado'],
      },
      { key: 'FOREST_IMPUGNACION', label: 'FOREST Impugnacion', type: 'text', mono: true },
      { key: 'JUZGADO_2ND', label: 'Juzgado Segunda Instancia', type: 'text' },
      {
        key: 'SENTIDO_FALLO_2ND', label: 'Sentido Fallo 2da Instancia', type: 'select',
        options: ['Confirma', 'Revoca', 'Modifica'],
      },
      { key: 'FECHA_FALLO_2ND', label: 'Fecha Fallo 2da Instancia', type: 'date' },
    ],
  },
  {
    title: 'Incidente de Desacato 1',
    fields: [
      {
        key: 'INCIDENTE', label: 'Incidente', type: 'select',
        options: ['SI', 'NO'],
      },
      { key: 'FECHA_APERTURA_INCIDENTE', label: 'Fecha Apertura', type: 'date' },
      { key: 'RESPONSABLE_DESACATO', label: 'Responsable Desacato', type: 'text' },
      { key: 'DECISION_INCIDENTE', label: 'Decision Incidente', type: 'textarea' },
    ],
  },
  {
    title: 'Incidente de Desacato 2',
    fields: [
      {
        key: 'INCIDENTE_2', label: 'Incidente 2', type: 'select',
        options: ['SI', 'NO'],
      },
      { key: 'FECHA_APERTURA_INCIDENTE_2', label: 'Fecha Apertura', type: 'date' },
      { key: 'RESPONSABLE_DESACATO_2', label: 'Responsable Desacato', type: 'text' },
      { key: 'DECISION_INCIDENTE_2', label: 'Decision Incidente', type: 'textarea' },
    ],
  },
  {
    title: 'Incidente de Desacato 3',
    fields: [
      {
        key: 'INCIDENTE_3', label: 'Incidente 3', type: 'select',
        options: ['SI', 'NO'],
      },
      { key: 'FECHA_APERTURA_INCIDENTE_3', label: 'Fecha Apertura', type: 'date' },
      { key: 'RESPONSABLE_DESACATO_3', label: 'Responsable Desacato', type: 'text' },
      { key: 'DECISION_INCIDENTE_3', label: 'Decision Incidente', type: 'textarea' },
    ],
  },
  {
    title: 'Observaciones',
    fields: [
      { key: 'OBSERVACIONES', label: 'Observaciones', type: 'textarea' },
    ],
  },
]

// ─── Form Field Component ────────────────────────────────────────────────────

function FormField({
  def,
  value,
  onChange,
}: {
  def: FieldDef
  value: string
  onChange: (key: string, val: string) => void
}) {
  const base =
    'w-full text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white ' +
    'focus:border-[#1A5276] focus:outline-none focus:ring-2 focus:ring-[#1A5276]/20 ' +
    'transition-all text-gray-800 placeholder-gray-300 ' +
    (def.mono ? 'font-mono' : '')

  if (def.type === 'textarea') {
    return (
      <textarea
        value={value}
        onChange={(e) => onChange(def.key, e.target.value)}
        rows={3}
        className={`${base} resize-y min-h-[72px]`}
      />
    )
  }

  if (def.type === 'select') {
    return (
      <select
        value={value}
        onChange={(e) => onChange(def.key, e.target.value)}
        className={base}
      >
        <option value="">— Seleccionar —</option>
        {def.options?.map((opt) => (
          <option key={opt} value={opt}>{opt}</option>
        ))}
      </select>
    )
  }

  if (def.type === 'date') {
    return (
      <input
        type="date"
        value={value}
        onChange={(e) => onChange(def.key, e.target.value)}
        className={base}
      />
    )
  }

  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(def.key, e.target.value)}
      className={base}
    />
  )
}

// ─── Section Component ───────────────────────────────────────────────────────

function FormSection({
  section,
  fields,
  onChange,
  defaultOpen = true,
}: {
  section: SectionDef
  fields: Record<string, string>
  onChange: (key: string, val: string) => void
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <span className="text-sm font-semibold text-[#1A5276]">{section.title}</span>
        {open ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
      </button>

      {open && (
        <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          {section.fields.map((f) => (
            <div
              key={f.key}
              className={
                f.type === 'textarea' || f.key === 'OBSERVACIONES'
                  ? 'col-span-full'
                  : ''
              }
            >
              <label className="block text-xs font-medium text-gray-500 mb-1.5 uppercase tracking-wide">
                {f.label}
              </label>
              <FormField def={f} value={fields[f.key] ?? ''} onChange={onChange} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Document Panel ──────────────────────────────────────────────────────────

function DocumentPanel({ docs, onDeleteDoc }: { docs: Array<{ id: number; filename: string; doc_type: string }>; onDeleteDoc?: (docId: number) => void }) {
  const [previewDocId, setPreviewDocId] = useState<number | null>(null)

  if (!docs?.length) {
    return (
      <div className="text-center py-12 text-gray-400 text-sm">
        No hay documentos en este caso
      </div>
    )
  }

  function getIcon(filename: string) {
    if (filename.toLowerCase().endsWith('.pdf')) return '📄'
    if (filename.toLowerCase().endsWith('.docx') || filename.toLowerCase().endsWith('.doc')) return '📝'
    if (filename.toLowerCase().endsWith('.md')) return '📧'
    if (filename.toLowerCase().match(/\.(png|jpg|jpeg)$/)) return '🖼️'
    return '📎'
  }

  function canPreview(filename: string) {
    return filename.toLowerCase().match(/\.(pdf|png|jpg|jpeg|docx|doc|md)$/)
  }

  const DOC_TYPE_LABELS: Record<string, string> = {
    AUTO_ADMISORIO: 'Auto Admisorio',
    SENTENCIA: 'Sentencia',
    RESPUESTA_DOCX: 'Respuesta',
    GMAIL: 'Correo',
    SCREENSHOT: 'Captura',
    IMPUGNACION: 'Impugnacion',
    INCIDENTE: 'Incidente',
    OTRO: 'Otro',
  }

  const TYPE_COLORS: Record<string, string> = {
    AUTO_ADMISORIO: 'bg-blue-100 text-blue-700',
    SENTENCIA: 'bg-purple-100 text-purple-700',
    RESPUESTA_DOCX: 'bg-green-100 text-green-700',
    GMAIL: 'bg-yellow-100 text-yellow-700',
    SCREENSHOT: 'bg-gray-100 text-gray-600',
    IMPUGNACION: 'bg-red-100 text-red-700',
    INCIDENTE: 'bg-orange-100 text-orange-700',
    OTRO: 'bg-gray-100 text-gray-500',
  }

  const previewDoc = docs.find(d => d.id === previewDocId)

  return (
    <div>
      {/* Preview iframe */}
      {previewDoc && canPreview(previewDoc.filename) && (
        <div className="border-b border-gray-200">
          <div className="flex items-center justify-between px-4 py-2 bg-gray-50">
            <span className="text-xs font-medium text-gray-600 truncate">{previewDoc.filename}</span>
            <div className="flex gap-2">
              <a
                href={getDocumentPreviewUrl(previewDoc.id)}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-[#1A5276] hover:underline"
              >
                Abrir en pestaña
              </a>
              <button
                onClick={() => setPreviewDocId(null)}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                Cerrar
              </button>
            </div>
          </div>
          <iframe
            src={getDocumentPreviewUrl(previewDoc.id)}
            className="w-full bg-white"
            style={{ height: '500px' }}
            title={previewDoc.filename}
          />
        </div>
      )}

      {/* Document list */}
      <div className="divide-y divide-gray-100">
        {docs.map((doc) => (
          <div
            key={doc.id}
            onClick={() => canPreview(doc.filename) ? setPreviewDocId(doc.id === previewDocId ? null : doc.id) : window.open(getDocumentPreviewUrl(doc.id), '_blank')}
            className={`flex items-start gap-3 px-4 py-3 cursor-pointer transition-colors group ${
              doc.id === previewDocId ? 'bg-[#1A5276]/10' : 'hover:bg-[#1A5276]/5'
            }`}
          >
            <span className="text-lg flex-shrink-0 mt-0.5">{getIcon(doc.filename)}</span>
            <div className="flex-1 min-w-0">
              <p className="text-xs text-gray-700 group-hover:text-[#1A5276] truncate font-medium transition-colors max-w-[280px]" title={doc.filename}>
                {doc.filename}
              </p>
              <span className={`mt-1 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${TYPE_COLORS[doc.doc_type] ?? 'bg-gray-100 text-gray-500'}`}>
                {DOC_TYPE_LABELS[doc.doc_type] ?? doc.doc_type}
              </span>
            </div>
            <div className="flex flex-col items-end gap-1 flex-shrink-0 mt-1">
              {canPreview(doc.filename) ? (
                <span className="text-xs text-gray-400">Vista previa</span>
              ) : (
                <ExternalLink size={14} className="text-gray-300 group-hover:text-[#1A5276] transition-colors" />
              )}
              <button
                onClick={(e) => { e.stopPropagation(); onDeleteDoc?.(doc.id) }}
                className="text-gray-300 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
                title="Eliminar documento"
              >
                <Trash2 size={12} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Main Component ──────────────────────────────────────────────────────────

// ─── Resizable Panels ─────────────────────────────────────────────────────

function ResizablePanels({
  caseData,
  fields,
  handleChange,
  onDeleteDoc,
}: {
  caseData: Record<string, unknown>
  fields: Record<string, string>
  handleChange: (key: string, value: string) => void
  onDeleteDoc?: (docId: number) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [dividerX, setDividerX] = useState(60) // porcentaje para el panel izquierdo
  const [isDragging, setIsDragging] = useState(false)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

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
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [isDragging])

  const docs = (caseData.documents ?? []) as Array<{ id: number; filename: string; doc_type: string }>

  return (
    <div ref={containerRef} className="flex-1 overflow-hidden flex min-h-0" style={{ cursor: isDragging ? 'col-resize' : undefined }}>
      {/* LEFT — Formulario */}
      <div className="overflow-y-auto p-6 space-y-3 min-w-0" style={{ width: `${dividerX}%` }}>
        {SECTIONS.map((section, i) => (
          <FormSection
            key={section.title}
            section={section}
            fields={fields}
            onChange={handleChange}
            defaultOpen={i < 3}
          />
        ))}
        <div className="h-6" />
      </div>

      {/* DIVIDER arrastrable */}
      <div
        onMouseDown={onMouseDown}
        className={`hidden lg:flex w-2 flex-shrink-0 cursor-col-resize items-center justify-center group transition-colors ${
          isDragging ? 'bg-[#1A5276]/20' : 'bg-gray-100 hover:bg-[#1A5276]/10'
        }`}
      >
        <div className={`w-0.5 h-8 rounded-full transition-colors ${
          isDragging ? 'bg-[#1A5276]' : 'bg-gray-300 group-hover:bg-[#1A5276]'
        }`} />
      </div>

      {/* RIGHT — Documentos */}
      <div className="flex flex-col min-h-0 min-w-0 border-l border-gray-200" style={{ width: `${100 - dividerX}%` }}>
        <div className="flex-shrink-0 px-4 py-3 bg-gray-50 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <FileText size={15} className="text-[#1A5276]" />
            <h2 className="text-sm font-semibold text-gray-700">
              Documentos ({docs.length})
            </h2>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          <DocumentPanel docs={docs} onDeleteDoc={onDeleteDoc} />
        </div>
      </div>
    </div>
  )
}

// ─── Main Component ──────────────────────────────────────────────────────

export default function CaseDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const caseId = parseInt(id ?? '0', 10)

  const caseQ = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => getCase(caseId),
    enabled: !!caseId,
  })

  const [fields, setFields] = useState<Record<string, string>>({})
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (caseQ.data) {
      const initial: Record<string, string> = {}
      SECTIONS.forEach((s) => {
        s.fields.forEach((f) => {
          initial[f.key] = caseQ.data[f.key] ?? ''
        })
      })
      setFields(initial)
      setDirty(false)
    }
  }, [caseQ.data])

  const saveMutation = useMutation({
    mutationFn: () => updateCase(caseId, fields),
    onSuccess: () => {
      toast.success('Caso actualizado exitosamente')
      qc.invalidateQueries({ queryKey: ['case', caseId] })
      qc.invalidateQueries({ queryKey: ['cases'] })
      setDirty(false)
    },
    onError: () => {
      toast.error('Error al guardar los cambios')
    },
  })

  const syncMutation = useMutation({
    mutationFn: () => syncSingleCase(caseId),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['case', caseId] })
      if (data.docs_added > 0 || data.docs_removed > 0) {
        toast.success(data.message)
      } else {
        toast('Carpeta sincronizada, sin cambios', { icon: '\u2705' })
      }
    },
    onError: () => toast.error('Error al sincronizar carpeta'),
  })

  const deleteCaseMut = useMutation({
    mutationFn: () => {
      if (!window.confirm(`¿Eliminar caso "${caseQ.data?.folder_name}"?\n\nSe eliminará la carpeta y todos los documentos del disco. Esta acción NO se puede deshacer.`)) {
        throw new Error('Cancelado')
      }
      return deleteCase(caseId)
    },
    onSuccess: (data) => {
      toast.success(data.message)
      qc.invalidateQueries({ queryKey: ['cases'] })
      navigate('/cases')
    },
    onError: (e) => { if ((e as Error).message !== 'Cancelado') toast.error('Error al eliminar') },
  })

  const deleteDocMut = useMutation({
    mutationFn: (docId: number) => {
      if (!window.confirm('¿Eliminar este documento del caso y del disco?')) {
        throw new Error('Cancelado')
      }
      return deleteDocument(caseId, docId)
    },
    onSuccess: (data) => {
      toast.success(data.message)
      qc.invalidateQueries({ queryKey: ['case', caseId] })
    },
    onError: (e) => { if ((e as Error).message !== 'Cancelado') toast.error('Error al eliminar documento') },
  })

  function handleChange(key: string, val: string) {
    setFields((prev) => ({ ...prev, [key]: val }))
    setDirty(true)
  }

  if (caseQ.isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={32} className="animate-spin text-[#1A5276]" />
      </div>
    )
  }

  if (caseQ.isError || !caseQ.data) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-xl p-5 flex items-center gap-3 text-red-700">
          <AlertCircle size={20} />
          <div>
            <p className="font-semibold">Error al cargar el caso</p>
            <p className="text-sm mt-1">No se pudo obtener la informacion del caso #{caseId}</p>
          </div>
        </div>
      </div>
    )
  }

  const caseData = caseQ.data

  return (
    <div className="h-full flex flex-col">
      {/* Top bar */}
      <div className="flex-shrink-0 flex items-center justify-between px-6 py-4 bg-white border-b border-gray-200 shadow-sm">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/cases')}
            className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 transition-colors"
          >
            <ArrowLeft size={18} />
          </button>
          <div>
            <h1 className="text-base font-bold text-gray-800 leading-tight">
              {caseData.folder_name}
            </h1>
            <p className="text-xs text-gray-400 mt-0.5">
              ID #{caseId} — {caseData.documents?.length ?? 0} documento(s)
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {dirty && (
            <span className="text-xs text-amber-600 font-medium bg-amber-50 border border-amber-200 px-2 py-1 rounded-lg">
              Cambios sin guardar
            </span>
          )}
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="p-2 rounded-lg text-gray-500 hover:bg-gray-100 transition-colors"
            title="Sincronizar carpeta"
          >
            <RefreshCw size={16} className={syncMutation.isPending || caseQ.isFetching ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !dirty}
            className="flex items-center gap-2 px-4 py-2 bg-[#1A5276] text-white text-sm font-medium rounded-lg hover:bg-[#154360] disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
          >
            {saveMutation.isPending ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Save size={14} />
            )}
            Guardar
          </button>
          <button
            onClick={() => deleteCaseMut.mutate()}
            disabled={deleteCaseMut.isPending}
            className="p-2 rounded-lg text-red-400 hover:bg-red-50 hover:text-red-600 transition-colors"
            title="Eliminar caso"
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>

      {/* Content — two columns */}
      <ResizablePanels
        caseData={caseData}
        fields={fields}
        handleChange={handleChange}
        onDeleteDoc={(docId) => deleteDocMut.mutate(docId)}
      />
    </div>
  )
}
