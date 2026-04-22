import { useState, useEffect, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  ArrowLeft, Save, FileText, ExternalLink, Loader2,
  AlertCircle, RefreshCw, ChevronDown, ChevronUp, Trash2, Mail, Package,
} from 'lucide-react'
import { getCase, updateCase, getDocumentPreviewUrl, syncSingleCase, deleteCase, deleteDocument, suggestDocTarget, moveDocument, markDocOk, getCaseEmailPackages, setPiiMode, getPiiHints } from '../services/api'
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
      { key: 'ESTADO', label: 'Estado', type: 'select', options: ['ACTIVO', 'INACTIVO'] },
      { key: 'FECHA_RESPUESTA', label: 'Fecha de Respuesta', type: 'date' },
    ],
  },
  {
    title: 'Fallo Primera Instancia',
    fields: [
      { key: 'SENTIDO_FALLO_1ST', label: 'Sentido del Fallo', type: 'select', options: ['CONCEDE', 'NIEGA', 'IMPROCEDENTE'] },
      { key: 'FECHA_FALLO_1ST', label: 'Fecha del Fallo', type: 'date' },
    ],
  },
  {
    title: 'Impugnacion',
    fields: [
      { key: 'IMPUGNACION', label: 'Impugnacion', type: 'select', options: ['SI', 'NO'] },
      { key: 'QUIEN_IMPUGNO', label: 'Quien Impugno', type: 'select', options: ['Accionante', 'Accionado', 'Vinculado'] },
      { key: 'FOREST_IMPUGNACION', label: 'FOREST Impugnacion', type: 'text', mono: true },
      { key: 'JUZGADO_2ND', label: 'Juzgado Segunda Instancia', type: 'text' },
      { key: 'SENTIDO_FALLO_2ND', label: 'Sentido Fallo 2da Instancia', type: 'select', options: ['Confirma', 'Revoca', 'Modifica'] },
      { key: 'FECHA_FALLO_2ND', label: 'Fecha Fallo 2da Instancia', type: 'date' },
    ],
  },
  {
    title: 'Incidente de Desacato 1',
    fields: [
      { key: 'INCIDENTE', label: 'Incidente', type: 'select', options: ['SI', 'NO'] },
      { key: 'FECHA_APERTURA_INCIDENTE', label: 'Fecha Apertura', type: 'date' },
      { key: 'RESPONSABLE_DESACATO', label: 'Responsable Desacato', type: 'text' },
      { key: 'DECISION_INCIDENTE', label: 'Decision Incidente', type: 'textarea' },
    ],
  },
  {
    title: 'Incidente de Desacato 2',
    fields: [
      { key: 'INCIDENTE_2', label: 'Incidente 2', type: 'select', options: ['SI', 'NO'] },
      { key: 'FECHA_APERTURA_INCIDENTE_2', label: 'Fecha Apertura', type: 'date' },
      { key: 'RESPONSABLE_DESACATO_2', label: 'Responsable Desacato', type: 'text' },
      { key: 'DECISION_INCIDENTE_2', label: 'Decision Incidente', type: 'textarea' },
    ],
  },
  {
    title: 'Incidente de Desacato 3',
    fields: [
      { key: 'INCIDENTE_3', label: 'Incidente 3', type: 'select', options: ['SI', 'NO'] },
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

function DocumentPanel({ docs, onDeleteDoc }: { docs: Array<{ id: number; filename: string; doc_type: string; verificacion?: string; verificacion_detalle?: string }>; onDeleteDoc?: (docId: number) => void }) {
  const [previewDocId, setPreviewDocId] = useState<number | null>(null)
  const [resolveDocId, setResolveDocId] = useState<number | null>(null)
  const [suggestions, setSuggestions] = useState<Array<{ case_id: number; folder_name: string; confidence: string; reason: string }>>([])
  const [loadingSuggest, setLoadingSuggest] = useState(false)
  const qc = useQueryClient()

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

  async function handleResolve(docId: number) {
    setResolveDocId(docId); setLoadingSuggest(true); setSuggestions([])
    try { const data = await suggestDocTarget(docId); setSuggestions(data.suggestions || []) } catch { toast.error('Error buscando sugerencias') }
    setLoadingSuggest(false)
  }

  async function handleMove(docId: number, targetCaseId: number) {
    if (!confirm('Mover este documento al caso seleccionado?')) return
    try { await moveDocument(docId, targetCaseId); toast.success('Documento movido exitosamente'); setResolveDocId(null); qc.invalidateQueries({ queryKey: ['case'] }) } catch { toast.error('Error moviendo documento') }
  }

  async function handleMarkOk(docId: number) {
    try { await markDocOk(docId); toast.success('Documento marcado como OK'); setResolveDocId(null); qc.invalidateQueries({ queryKey: ['case'] }) } catch { toast.error('Error marcando documento') }
  }

  const previewDoc = docs.find(d => d.id === previewDocId)

  return (
    <div>
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

      {resolveDocId && (
        <Card className="mx-4 mt-3 border-destructive">
          <CardContent className="pt-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">Resolver documento</span>
              <button onClick={() => setResolveDocId(null)} className="text-xs text-muted-foreground hover:text-foreground">Cerrar</button>
            </div>
            <p className="text-xs text-muted-foreground truncate">{docs.find(d => d.id === resolveDocId)?.filename}</p>
            {loadingSuggest ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
                <Loader2 size={14} className="animate-spin" /> Buscando caso destino...
              </div>
            ) : suggestions.length > 0 ? (
              <div className="space-y-2">
                <p className="text-xs text-muted-foreground font-medium">Sugerencias:</p>
                {suggestions.map(s => (
                  <div key={s.case_id} className="flex items-center justify-between bg-muted p-2 rounded-lg text-xs">
                    <div className="min-w-0">
                      <p className="font-medium text-foreground truncate">{s.folder_name}</p>
                      <p className="text-muted-foreground">{s.reason}</p>
                      <StatusBadge type="status" value={s.confidence === 'ALTA' ? 'ok' : s.confidence === 'MEDIA' ? 'warning' : 'unknown'} className="mt-1" />
                    </div>
                    <Button size="xs" onClick={() => handleMove(resolveDocId, s.case_id)} className="ml-2">Mover</Button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground py-2">No se encontraron sugerencias de destino</p>
            )}
            <Separator />
            <Button variant="outline" size="xs" onClick={() => handleMarkOk(resolveDocId)} className="text-emerald-700 border-emerald-200 hover:bg-emerald-50">
              Pertenece aqui (marcar OK)
            </Button>
          </CardContent>
        </Card>
      )}

      {previewDoc && canPreview(previewDoc.filename) && (
        <div className="border-b border-border">
          <div className="flex items-center justify-between px-4 py-2 bg-muted">
            <span className="text-xs font-medium text-foreground truncate">{previewDoc.filename}</span>
            <div className="flex gap-2">
              <a href={getDocumentPreviewUrl(previewDoc.id)} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">Abrir en pestana</a>
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
                {doc.verificacion === 'OK' && <span className="text-xs text-emerald-600">\u2713</span>}
              </div>
            </div>
            <div className="flex flex-col items-end gap-1 flex-shrink-0 mt-1">
              {doc.verificacion === 'NO_PERTENECE' ? (
                <Button variant="destructive" size="xs" onClick={(e) => { e.stopPropagation(); handleResolve(doc.id) }}>Resolver</Button>
              ) : canPreview(doc.filename) ? (
                <span className="text-xs text-muted-foreground">Vista previa</span>
              ) : (
                <ExternalLink size={14} className="text-muted-foreground group-hover:text-primary transition-colors" />
              )}
              <button
                onClick={(e) => { e.stopPropagation(); onDeleteDoc?.(doc.id) }}
                className="text-muted-foreground hover:text-destructive transition-colors opacity-0 group-hover:opacity-100"
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

  return (
    <>
      <div className="flex-shrink-0 bg-muted border-b border-border">
        <div className="flex">
          <button onClick={() => setTab('docs')} className={cn('flex-1 px-4 py-2.5 text-sm font-medium flex items-center justify-center gap-2 border-b-2 transition-colors', tab === 'docs' ? 'border-primary text-primary bg-card' : 'border-transparent text-muted-foreground hover:text-foreground')}>
            <FileText size={14} />
            Documentos ({docs.length})
          </button>
          <button onClick={() => setTab('emails')} className={cn('flex-1 px-4 py-2.5 text-sm font-medium flex items-center justify-center gap-2 border-b-2 transition-colors', tab === 'emails' ? 'border-primary text-primary bg-card' : 'border-transparent text-muted-foreground hover:text-foreground')}>
            <Mail size={14} />
            Correos
            {packagesQ.data && packagesQ.data.packages_count > 0 && (
              <Badge variant="secondary" className="text-[10px] px-1.5">{packagesQ.data.packages_count}</Badge>
            )}
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {tab === 'docs' ? <DocumentPanel docs={docs} onDeleteDoc={onDeleteDoc} /> : <EmailPackagesTimeline query={packagesQ} />}
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
              {pkg.date_received && <span>\u00B7 {new Date(pkg.date_received).toLocaleDateString('es-CO', { day: '2-digit', month: 'short', year: '2-digit' })}</span>}
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

  const caseQ = useQuery({ queryKey: ['case', caseId], queryFn: () => getCase(caseId), enabled: !!caseId })

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

  const deleteDocMut = useMutation({
    mutationFn: (docId: number) => {
      if (!window.confirm('Eliminar este documento del caso y del disco?')) throw new Error('Cancelado')
      return deleteDocument(caseId, docId)
    },
    onSuccess: (data) => { toast.success(data.message); qc.invalidateQueries({ queryKey: ['case', caseId] }) },
    onError: (e) => { if ((e as Error).message !== 'Cancelado') toast.error('Error al eliminar documento') },
  })

  const piiHintsQ = useQuery({
    queryKey: ['pii-hints', caseId],
    queryFn: () => getPiiHints(caseId),
    enabled: !!caseId,
    staleTime: 60_000,
  })

  const piiMut = useMutation({
    mutationFn: (mode: 'selective' | 'aggressive' | null) => setPiiMode(caseId, mode),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['case', caseId] })
      qc.invalidateQueries({ queryKey: ['pii-hints', caseId] })
      toast.success(`Modo PII: ${data.pii_mode ?? 'default'}${data.requires_reextract ? ' — re-extrae el caso' : ''}`)
    },
    onError: () => toast.error('Error al cambiar modo PII'),
  })

  function toggleAggressive() {
    const current = (caseQ.data as any)?.pii_mode
    if (current === 'aggressive') {
      piiMut.mutate(null)
      return
    }
    if (!window.confirm('Activar anonimización AGGRESSIVE?\n\nTokeniza también nombres, diagnósticos y radicados. Reduce calidad de campos narrativos (~5-15%) pero maximiza privacidad. Útil para casos con menores con discapacidad, violencia de género o salud mental.\n\nRequiere re-extraer el caso.')) return
    piiMut.mutate('aggressive')
  }

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
          <Button variant="ghost" size="icon-sm" onClick={() => navigate('/cases')}>
            <ArrowLeft size={16} />
          </Button>
          <div>
            <h1 className="text-sm font-semibold text-foreground leading-tight">{caseData.folder_name}</h1>
            <p className="text-xs text-muted-foreground mt-0.5">ID #{caseId} — {caseData.documents?.length ?? 0} documento(s)</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {(caseData as any).pii_mode === 'aggressive' && (
            <Badge variant="outline" className="text-violet-700 border-violet-200 bg-violet-50" title="Anonimización agresiva: nombres y diagnósticos tokenizados">
              🔒 PII Aggressive
            </Badge>
          )}
          <Button
            variant={(caseData as any).pii_mode === 'aggressive' ? 'default' : 'ghost'}
            size="sm"
            onClick={toggleAggressive}
            disabled={piiMut.isPending}
            title={
              (caseData as any).pii_mode === 'aggressive'
                ? 'Desactivar anonimización agresiva'
                : (piiHintsQ.data?.recommend_aggressive
                    ? `Sugerencia: ${piiHintsQ.data.hints.join(', ')}`
                    : 'Activar anonimización agresiva')
            }
            className={piiHintsQ.data?.recommend_aggressive && (caseData as any).pii_mode !== 'aggressive'
              ? 'ring-2 ring-amber-400 animate-pulse'
              : ''}
          >
            🔒 {(caseData as any).pii_mode === 'aggressive' ? 'Aggressive' : 'Selective'}
          </Button>
          {dirty && <Badge variant="outline" className="text-amber-700 border-amber-200 bg-amber-50">Cambios sin guardar</Badge>}
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

      <ResizablePanels caseData={caseData} fields={fields} handleChange={handleChange} onDeleteDoc={(docId) => deleteDocMut.mutate(docId)} />
    </div>
  )
}
