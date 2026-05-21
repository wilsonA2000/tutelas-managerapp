/**
 * Modal "Historial del expediente" — vista cronológica de todos los eventos
 * de un case (creación, modificaciones, traslados, cambios de estado, notas).
 *
 * Reutilizable en /seguimiento (botón 🕐 por fila) y /cases/:id (botón al
 * lado del nombre del expediente).
 */
import { useQuery } from '@tanstack/react-query'
import {
  Clock, FileText, Mail, Plus, Edit3, Move, Trash2,
  Check, StickyNote, Cpu,
  X, Loader2,
} from 'lucide-react'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { getCaseAudit, type AuditEvent } from '../services/api'
import { cn } from '@/lib/utils'
import { useState } from 'react'

type ActionIcon = { icon: React.ElementType; color: string; label: string }

const ACTION_CONFIG: Record<string, ActionIcon> = {
  // Compliance
  COMPLIANCE_STATE_CHANGED:   { icon: Edit3,        color: 'text-indigo-600 bg-indigo-50',   label: 'Estado' },
  COMPLIANCE_NOTE_ADDED:      { icon: StickyNote,   color: 'text-amber-600 bg-amber-50',     label: 'Nota' },
  COMPLIANCE_EVIDENCE_LINKED: { icon: Check,        color: 'text-emerald-600 bg-emerald-50', label: 'Evidencia' },
  COMPLIANCE_CREATED:         { icon: Plus,         color: 'text-cyan-600 bg-cyan-50',       label: 'Compliance' },
  // Case
  CASE_CREATED:               { icon: Plus,         color: 'text-emerald-600 bg-emerald-50', label: 'Creación' },
  CASE_FOLDER_RENAMED:        { icon: Edit3,        color: 'text-slate-600 bg-slate-50',     label: 'Rename' },
  CASE_ACUMULADO:             { icon: Move,         color: 'text-violet-600 bg-violet-50',   label: 'Acumulado' },
  CASE_DELETED:               { icon: Trash2,       color: 'text-red-600 bg-red-50',         label: 'Borrado' },
  // Documentos
  DOC_ADDED:                  { icon: FileText,     color: 'text-blue-600 bg-blue-50',       label: 'Doc' },
  DOC_REMOVED:                { icon: Trash2,       color: 'text-red-600 bg-red-50',         label: 'Doc removido' },
  DOC_MOVED:                  { icon: Move,         color: 'text-violet-600 bg-violet-50',   label: 'Doc movido' },
  DOC_TYPE_CHANGED:           { icon: Edit3,        color: 'text-slate-600 bg-slate-50',     label: 'Doc tipo' },
  DOC_EXTRACTED:              { icon: Cpu,          color: 'text-blue-600 bg-blue-50',       label: 'Extracción' },
  // Extracción
  FIELD_EXTRACTED:            { icon: Cpu,          color: 'text-sky-600 bg-sky-50',         label: 'Campo extraído' },
  FIELD_MODIFIED:             { icon: Edit3,        color: 'text-amber-600 bg-amber-50',     label: 'Campo' },
  EDICION_MANUAL:             { icon: Edit3,        color: 'text-amber-600 bg-amber-50',     label: 'Edición' },
  EXTRACTION_RUN:             { icon: Cpu,          color: 'text-blue-600 bg-blue-50',       label: 'Extracción' },
  EXTRACTION_V9:              { icon: Cpu,          color: 'text-blue-600 bg-blue-50',       label: 'v9 pipeline' },
  EXTRACT_REGEX:              { icon: Cpu,          color: 'text-blue-600 bg-blue-50',       label: 'Regex' },
  // Correos
  EMAIL_RECEIVED:             { icon: Mail,         color: 'text-emerald-600 bg-emerald-50', label: 'Email' },
  EMAIL_LINKED:               { icon: Mail,         color: 'text-blue-600 bg-blue-50',       label: 'Email link' },
  IMPORT_EMAIL:               { icon: Mail,         color: 'text-emerald-600 bg-emerald-50', label: 'Email' },
  // Misc
  MANUAL_MOVE:                { icon: Move,         color: 'text-violet-600 bg-violet-50',   label: 'Move' },
}

function getActionConfig(action: string): ActionIcon {
  if (ACTION_CONFIG[action]) return ACTION_CONFIG[action]
  // Fallback por prefijo
  if (action.startsWith('COMPLIANCE_')) return { icon: Edit3, color: 'text-indigo-600 bg-indigo-50', label: 'Compliance' }
  if (action.startsWith('DOC_'))        return { icon: FileText, color: 'text-blue-600 bg-blue-50', label: 'Doc' }
  if (action.startsWith('EMAIL_'))      return { icon: Mail, color: 'text-emerald-600 bg-emerald-50', label: 'Email' }
  if (action.startsWith('EXTRACT'))     return { icon: Cpu, color: 'text-sky-600 bg-sky-50', label: 'Extracción' }
  if (action.startsWith('CLEAR') || action.startsWith('NORMALIZE') || action.startsWith('DERIVE')) {
    return { icon: Edit3, color: 'text-stone-600 bg-stone-50', label: action.split(' ')[0] }
  }
  return { icon: Edit3, color: 'text-slate-600 bg-slate-50', label: action.slice(0, 12) }
}

const ACTOR_COLOR: Record<string, string> = {
  wilson:              'text-amber-700 bg-amber-50 border-amber-200',
  usuario:             'text-amber-700 bg-amber-50 border-amber-200',
  system:              'text-slate-600 bg-slate-50 border-slate-200',
  gmail_monitor:       'text-emerald-700 bg-emerald-50 border-emerald-200',
  gmail_api:           'text-emerald-700 bg-emerald-50 border-emerald-200',
  ai_deepseek:         'text-sky-700 bg-sky-50 border-sky-200',
  ai_anthropic:        'text-sky-700 bg-sky-50 border-sky-200',
  ai_heuristic:        'text-sky-700 bg-sky-50 border-sky-200',
  v9_regex:            'text-cyan-700 bg-cyan-50 border-cyan-200',
  extractor_v2:        'text-cyan-700 bg-cyan-50 border-cyan-200',
  manual_audit:        'text-violet-700 bg-violet-50 border-violet-200',
}

function actorBadgeClass(actor: string | null): string {
  if (!actor) return 'text-slate-600 bg-slate-50 border-slate-200'
  for (const key of Object.keys(ACTOR_COLOR)) {
    if (actor.startsWith(key)) return ACTOR_COLOR[key]
  }
  return 'text-slate-600 bg-slate-50 border-slate-200'
}

function buildDescription(ev: AuditEvent): string {
  if (ev.description) return ev.description
  // Fallback: construir descripción desde action + field + values
  const parts: string[] = []
  if (ev.field_name) parts.push(ev.field_name)
  if (ev.old_value != null && ev.new_value != null && ev.old_value !== ev.new_value) {
    parts.push(`${ev.old_value} → ${ev.new_value}`)
  } else if (ev.new_value != null) {
    parts.push(`= ${ev.new_value}`)
  }
  return parts.join(' ') || ev.action
}

function fmtDate(ts: string | null): string {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return d.toLocaleString('es-CO', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return ts.slice(0, 16) }
}

interface HistorialModalProps {
  caseId: number | null
  caseLabel?: string         // texto descriptivo del case (folder_name, accionante, etc.)
  onClose: () => void
}

export default function HistorialModal({ caseId, caseLabel, onClose }: HistorialModalProps) {
  const [filtro, setFiltro] = useState<string>('')

  const q = useQuery({
    queryKey: ['case-audit', caseId, filtro],
    queryFn: () => getCaseAudit(caseId!, filtro ? { action_prefix: filtro } : {}),
    enabled: caseId != null,
  })

  const items = q.data?.items ?? []

  const FILTROS = [
    { value: '', label: 'Todo' },
    { value: 'COMPLIANCE_', label: 'Estado / Notas' },
    { value: 'DOC_', label: 'Documentos' },
    { value: 'EMAIL_', label: 'Correos' },
    { value: 'EXTRACT', label: 'Extracción' },
    { value: 'CASE_', label: 'Génesis' },
  ]

  return (
    <Dialog open={caseId != null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Clock size={16} className="text-primary" />
            Historial del expediente
          </DialogTitle>
          {caseLabel && (
            <p className="text-xs text-muted-foreground mt-1">{caseLabel}</p>
          )}
        </DialogHeader>

        {/* Filtros */}
        <div className="flex flex-wrap gap-1.5">
          {FILTROS.map(f => (
            <button
              key={f.value}
              onClick={() => setFiltro(f.value)}
              className={cn(
                'px-2.5 py-1 rounded-full text-[10px] font-medium border transition-colors',
                filtro === f.value
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'bg-card text-muted-foreground border-border hover:border-primary hover:text-primary'
              )}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Timeline */}
        <div className="flex-1 min-h-0 overflow-y-auto border border-border rounded-md bg-muted/20">
          {q.isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={24} className="animate-spin text-primary" />
            </div>
          ) : items.length === 0 ? (
            <div className="text-center py-12 text-xs text-muted-foreground">
              {filtro ? `Sin eventos en la categoría "${FILTROS.find(f => f.value === filtro)?.label}"` : 'Sin historial registrado'}
            </div>
          ) : (
            <ol className="divide-y divide-border">
              {items.map((ev) => {
                const cfg = getActionConfig(ev.action)
                const Icon = cfg.icon
                return (
                  <li key={ev.id} className="flex items-start gap-3 p-3 hover:bg-muted/40 transition-colors">
                    {/* Icono */}
                    <div className={cn('shrink-0 w-7 h-7 rounded-full flex items-center justify-center', cfg.color)}>
                      <Icon size={13} />
                    </div>
                    {/* Contenido */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-[11px] font-semibold text-foreground">{cfg.label}</span>
                        {ev.actor && (
                          <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-medium border', actorBadgeClass(ev.actor))}>
                            {ev.actor.length > 24 ? ev.actor.slice(0, 22) + '…' : ev.actor}
                          </span>
                        )}
                        <span className="text-[10px] text-muted-foreground ml-auto">{fmtDate(ev.ts)}</span>
                      </div>
                      <p className="text-[11px] text-foreground mt-1 leading-relaxed">
                        {buildDescription(ev)}
                      </p>
                      {ev.action !== 'COMPLIANCE_NOTE_ADDED' && (
                        <p className="text-[9px] text-muted-foreground/70 mt-0.5 font-mono">
                          {ev.action}{ev.entity_type ? ` · ${ev.entity_type}${ev.entity_id ? '#' + ev.entity_id : ''}` : ''}
                        </p>
                      )}
                    </div>
                  </li>
                )
              })}
            </ol>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
          <span>{q.data?.total ?? 0} eventos</span>
          <button
            onClick={onClose}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded border border-border text-xs hover:bg-muted"
          >
            <X size={12} /> Cerrar
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
