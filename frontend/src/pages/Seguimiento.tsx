import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  AlertTriangle, Shield, CheckCircle, Clock, XCircle, Check,
  ExternalLink, Loader2, Cpu, RefreshCw, ShieldAlert,
  Ban, GitBranch, Infinity as InfinityIcon, Calendar, Zap, FileQuestion,
  StickyNote, ChevronDown, Hourglass, Scale, Pause, AlertCircle, History,
} from 'lucide-react'
import HistorialModal from '@/components/HistorialModal'
import { getSeguimiento, scanFallos, extractOrder, updateSeguimiento } from '../services/api'
import PageShell from '@/components/PageShell'
import PageHeader from '@/components/PageHeader'
import DataCard from '@/components/DataCard'
import { Button } from '@/components/ui/button'
import {
  Table, TableHeader, TableBody, TableRow,
  TableHead, TableCell,
} from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

const SEMAFORO_CONFIG: Record<string, {
  color: string; bg: string; border: string
  icon: React.ElementType; label: string
}> = {
  VENCIDO:     { color: 'text-red-700',    bg: 'bg-red-100',    border: 'border-red-300',    icon: XCircle,       label: 'Vencido' },
  URGENTE:     { color: 'text-orange-700', bg: 'bg-orange-100', border: 'border-orange-300', icon: AlertTriangle, label: 'Urgente (<3 días)' },
  POR_VENCER:  { color: 'text-amber-700',  bg: 'bg-amber-100',  border: 'border-amber-300',  icon: Clock,         label: 'Por vencer (<7 días)' },
  EN_PLAZO:    { color: 'text-green-700',  bg: 'bg-green-100',  border: 'border-green-300',  icon: Shield,        label: 'En plazo' },
  CUMPLIDO:    { color: 'text-blue-700',   bg: 'bg-blue-100',   border: 'border-blue-300',   icon: CheckCircle,   label: 'Cumplido' },
  IMPUGNADO:   { color: 'text-purple-700', bg: 'bg-purple-100', border: 'border-purple-300', icon: Clock,         label: 'Impugnado' },
  PERMANENTE:  { color: 'text-indigo-700', bg: 'bg-indigo-100', border: 'border-indigo-300', icon: InfinityIcon,  label: 'Permanente' },
  CONDICIONAL: { color: 'text-cyan-700',   bg: 'bg-cyan-100',   border: 'border-cyan-300',   icon: GitBranch,     label: 'Condicional' },
  SIN_PLAZO:   { color: 'text-gray-600',   bg: 'bg-gray-100',   border: 'border-gray-300',   icon: FileQuestion,  label: 'Sin plazo' },
  NO_APLICA:   { color: 'text-stone-600',  bg: 'bg-stone-100',  border: 'border-stone-300',  icon: Ban,           label: 'No aplica' },
  EN_PROCESO:  { color: 'text-sky-700',    bg: 'bg-sky-100',    border: 'border-sky-300',    icon: Clock,         label: 'En proceso' },
}

const TIPO_PLAZO_CONFIG: Record<string, { color: string; label: string; icon: React.ElementType }> = {
  NUMERICO:    { color: 'bg-amber-50 text-amber-800 border-amber-200',     label: 'N días',     icon: Clock },
  FECHA:       { color: 'bg-orange-50 text-orange-800 border-orange-200',  label: 'Fecha exacta', icon: Calendar },
  INMEDIATO:   { color: 'bg-red-50 text-red-800 border-red-200',           label: 'Inmediato',  icon: Zap },
  PERMANENTE:  { color: 'bg-indigo-50 text-indigo-800 border-indigo-200',  label: 'Permanente', icon: InfinityIcon },
  CONDICIONAL: { color: 'bg-cyan-50 text-cyan-800 border-cyan-200',        label: 'Condicional', icon: GitBranch },
  SIN_PLAZO:   { color: 'bg-gray-50 text-gray-700 border-gray-200',        label: 'Sin plazo',  icon: FileQuestion },
}

const DESTINATARIO_CONFIG: Record<string, { color: string; label: string }> = {
  SED_DIRECTA:           { color: 'bg-emerald-50 text-emerald-800 border-emerald-200', label: 'SED directa' },
  SED_VINCULADA:         { color: 'bg-teal-50 text-teal-800 border-teal-200',         label: 'SED vinculada' },
  TERCERO_SED_VINCULADA: { color: 'bg-blue-50 text-blue-800 border-blue-200',         label: 'Tercero + SED' },
  TERCERO_NO_SED:        { color: 'bg-gray-50 text-gray-700 border-gray-200',         label: 'Tercero (sin SED)' },
  SED_OTRA:              { color: 'bg-violet-50 text-violet-800 border-violet-200',   label: 'SED otra' },
  SED_DESVINCULADA:      { color: 'bg-stone-50 text-stone-600 border-stone-200',      label: 'SED desvinculada' },
}

function TipoPlazoChip({ tipo }: { tipo: string | undefined }) {
  if (!tipo) return null
  const cfg = TIPO_PLAZO_CONFIG[tipo]
  if (!cfg) return null
  const Icon = cfg.icon
  return (
    <span className={cn('inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border', cfg.color)}>
      <Icon size={10} />
      {cfg.label}
    </span>
  )
}

function DestinatarioChip({ tipo }: { tipo: string | undefined }) {
  if (!tipo) return null
  const cfg = DESTINATARIO_CONFIG[tipo]
  if (!cfg) return null
  return (
    <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border', cfg.color)}>
      {cfg.label}
    </span>
  )
}

// v8.3: mini-timeline visual del estado del caso en el funnel
const PIPELINE_STAGES = [
  { key: 'FALLO_1ST', label: '1ra', flag: 'has_fallo_1st' as const },
  { key: 'IMPUGNACION', label: 'Imp', flag: 'has_impugnacion' as const },
  { key: 'FALLO_2ND', label: '2da', flag: 'has_fallo_2nd' as const },
  { key: 'INCIDENTE', label: 'Inc', flag: 'has_incidente' as const },
  { key: 'CUMPLIDO', label: 'OK', flag: 'is_cumplido' as const },
]

type Pipeline = {
  current: string
  has_fallo_1st: boolean; has_impugnacion: boolean
  has_fallo_2nd: boolean; has_incidente: boolean; is_cumplido: boolean
}

function MiniTimeline({ pipeline }: { pipeline: Pipeline | undefined }) {
  if (!pipeline) return null
  return (
    <div className="flex items-center gap-0.5 mt-1">
      {PIPELINE_STAGES.map((s, idx) => {
        const reached = pipeline[s.flag]
        const isCurrent = pipeline.current === s.key
        return (
          <div key={s.key} className="flex items-center">
            <span
              className={cn(
                'inline-block px-1.5 py-0.5 rounded text-[9px] font-bold border',
                reached
                  ? isCurrent
                    ? 'bg-primary text-white border-primary'
                    : 'bg-emerald-100 text-emerald-700 border-emerald-300'
                  : 'bg-gray-50 text-gray-400 border-gray-200',
              )}
              title={`${s.key}${reached ? ' ✓' : ''}${isCurrent ? ' (etapa actual)' : ''}`}
            >
              {s.label}
            </span>
            {idx < PIPELINE_STAGES.length - 1 && (
              <span className={cn(
                'inline-block w-1.5 h-px mx-0.5',
                reached ? 'bg-emerald-400' : 'bg-gray-200',
              )} />
            )}
          </div>
        )
      })}
    </div>
  )
}

function SemaforoBadge({ semaforo }: { semaforo: string }) {
  const cfg = SEMAFORO_CONFIG[semaforo] ?? SEMAFORO_CONFIG.SIN_PLAZO
  const Icon = cfg.icon
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border',
      cfg.bg, cfg.color, cfg.border
    )}>
      <Icon size={13} />
      {cfg.label}
    </span>
  )
}

// Apila una nota nueva al campo notas existente, con timestamp legible.
function _appendNota(prev: string | null | undefined, nueva: string): string {
  const ts = new Date().toLocaleDateString('es-CO', { day: '2-digit', month: '2-digit', year: 'numeric' })
  const entry = `[${ts}] ${nueva}`
  return (prev && prev.trim()) ? `${prev.trim()}\n${entry}` : entry
}

// Cuenta cuántas líneas con formato [DD/MM/YYYY] tiene el campo notas.
function _countNotas(notas: string | null | undefined): number {
  if (!notas) return 0
  return (notas.match(/^\[\d{2}\/\d{2}\/\d{4}\]/gm) || []).length
}

export default function Seguimiento() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [filtroSemaforo, setFiltroSemaforo] = useState('')

  // Modal de nota libre
  const [notaModal, setNotaModal] = useState<{ id: number; folder: string; currentNotas: string } | null>(null)
  const [notaTexto, setNotaTexto] = useState('')

  // Modal de historial (audit log del case)
  const [historialCaseId, setHistorialCaseId] = useState<number | null>(null)
  const [historialLabel, setHistorialLabel] = useState<string>('')

  const dataQ = useQuery({
    queryKey: ['seguimiento', filtroSemaforo],
    queryFn: () => getSeguimiento(filtroSemaforo ? { urgencia: filtroSemaforo } : {}),
  })

  const scanMut = useMutation({
    mutationFn: scanFallos,
    onSuccess: (data) => {
      toast.success(data.message)
      qc.invalidateQueries({ queryKey: ['seguimiento'] })
    },
    onError: () => toast.error('Error al escanear fallos'),
  })

  const extractMut = useMutation({
    mutationFn: extractOrder,
    onSuccess: (data) => {
      if (data.error) {
        toast.error(data.error)
      } else {
        toast.success(`Orden extraida: ${data.plazo_dias ?? 0} dias de plazo`)
        qc.invalidateQueries({ queryKey: ['seguimiento'] })
      }
    },
    onError: () => toast.error('Error al extraer orden con IA'),
  })

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, string | number>; toastMsg?: string }) =>
      updateSeguimiento(id, body),
    onSuccess: (_data, variables) => {
      toast.success(variables.toastMsg ?? 'Actualizado')
      qc.invalidateQueries({ queryKey: ['seguimiento'] })
    },
  })

  const items = dataQ.data?.items ?? []
  const resumen = dataQ.data?.resumen ?? {}

  const FILTER_LABELS: Record<string, string> = {
    '': 'Todos', VENCIDO: 'Vencido', URGENTE: 'Urgente',
    POR_VENCER: 'Por Vencer', EN_PLAZO: 'En Plazo',
    IMPUGNADO: 'Impugnado', CUMPLIDO: 'Cumplido',
    EN_PROCESO: 'En Proceso', CONDICIONAL: 'Condicional',
    SIN_PLAZO: 'Sin Plazo', NO_APLICA: 'No Aplica',
  }

  return (
    <PageShell>
      <PageHeader
        title="Seguimiento de Cumplimientos"
        subtitle="Control de fallos desfavorables y plazos de cumplimiento"
        icon={ShieldAlert}
        action={
          <Button
            size="sm"
            onClick={() => scanMut.mutate()}
            disabled={scanMut.isPending}
          >
            {scanMut.isPending
              ? <Loader2 size={15} className="animate-spin mr-1.5" />
              : <RefreshCw size={15} className="mr-1.5" />}
            {scanMut.isPending ? 'Escaneando...' : 'Escanear Fallos'}
          </Button>
        }
      />

      {/* Summary cards */}
      {resumen.total > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
          <DataCard icon={Shield}        label="Total"        value={resumen.total      ?? 0} variant="primary"  />
          <DataCard icon={XCircle}       label="Vencidos"     value={resumen.vencidos   ?? 0} variant="danger"   sub="candidatos a desacato" />
          <DataCard icon={AlertTriangle} label="Urgentes"     value={resumen.urgentes   ?? 0} variant="warning"  sub="<3 días" />
          <DataCard icon={Clock}         label="En Proceso"   value={resumen.en_proceso ?? 0} variant="info"     sub="con evidencia parcial" />
          <DataCard icon={CheckCircle}   label="En Plazo"     value={resumen.en_plazo   ?? 0} variant="success"  />
          <DataCard icon={CheckCircle}   label="Cumplidos"    value={resumen.cumplidos  ?? 0} variant="neutral"  sub="con evidencia" />
          <DataCard icon={FileQuestion}  label="Sin Plazo"    value={resumen.sin_plazo  ?? 0} variant="neutral"  sub="vigilables sin fecha" />
          <DataCard icon={Ban}           label="No Aplica"    value={resumen.no_aplica  ?? 0} variant="neutral"  sub="SED desvinculada / inconsist." />
        </div>
      )}

      {/* Filter chips */}
      <div className="bg-card rounded-xl border border-border shadow-sm px-4 py-3 flex flex-wrap gap-2 items-center">
        <span className="text-xs font-semibold text-muted-foreground mr-1">Filtrar:</span>
        {['', 'VENCIDO', 'URGENTE', 'POR_VENCER', 'EN_PLAZO', 'EN_PROCESO', 'CONDICIONAL', 'SIN_PLAZO', 'IMPUGNADO', 'CUMPLIDO', 'NO_APLICA'].map((f) => (
          <button
            key={f}
            onClick={() => setFiltroSemaforo(f)}
            className={cn(
              'px-3 py-1.5 rounded-full text-xs font-medium border transition-colors',
              filtroSemaforo === f
                ? 'bg-primary text-primary-foreground border-primary'
                : 'bg-card text-muted-foreground border-border hover:border-primary hover:text-primary'
            )}
          >
            {FILTER_LABELS[f] ?? f}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        {dataQ.isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={24} className="animate-spin text-primary" />
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-12">
            <Shield size={40} className="mx-auto text-muted-foreground/30 mb-3" />
            <p className="text-sm text-muted-foreground">No hay seguimientos registrados</p>
            <p className="text-xs text-muted-foreground/60 mt-1">
              Use "Escanear Fallos" para detectar tutelas con fallos desfavorables
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table className="table-fixed w-full">
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead className="text-xs font-semibold text-muted-foreground uppercase tracking-wide w-[140px]">
                    Estado
                  </TableHead>
                  <TableHead className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                    Caso / Orden de cumplimiento
                  </TableHead>
                  <TableHead className="text-xs font-semibold text-muted-foreground uppercase tracking-wide w-[130px]">
                    Plazo
                  </TableHead>
                  <TableHead className="w-[100px]" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item: {
                  id: number; case_id: number; semaforo: string;
                  folder_name: string; radicado_corto?: string;
                  accionante: string; juzgado: string;
                  orden_judicial: string; plazo_dias: number;
                  dias_restantes: number | null; fecha_limite: string;
                  responsable: string; instancia: string; sentido_fallo: string;
                  impugnado: string; requiere_cumplimiento: string;
                  estado: string; notas: string; extraido_por_ia: string;
                  pipeline?: Pipeline;
                  // v2 — orden discreta
                  ordinal_nombre?: string; tipo_plazo?: string;
                  destinatario_tipo?: string; accion_resumida?: string;
                  condicion?: string; verbo_orden?: string;
                  fecha_especifica?: string; evidencia_doc_id?: number;
                }) => (
                  <TableRow key={item.id} className="hover:bg-muted/30 transition-colors">
                    {/* Semaforo */}
                    <TableCell className="py-3">
                      <SemaforoBadge semaforo={item.semaforo} />
                    </TableCell>

                    {/* Caso / Orden — columna fusionada */}
                    <TableCell className="py-3">
                      <div className="flex items-baseline gap-2 flex-wrap">
                        {item.radicado_corto && (
                          <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-bold border bg-primary/10 text-primary border-primary/30">
                            {item.radicado_corto}
                          </span>
                        )}
                        <p className="font-medium text-foreground text-xs">
                          {item.accionante || item.folder_name}
                        </p>
                      </div>
                      <p className="text-[10px] text-muted-foreground mt-0.5 truncate" title={item.juzgado}>{item.juzgado}</p>

                      {/* Chips fila 1: instancia + ordinal + sentido + impugnado */}
                      <div className="flex gap-1.5 mt-1.5 flex-wrap">
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0.5 h-auto font-normal text-muted-foreground">
                          {item.instancia}
                        </Badge>
                        {item.ordinal_nombre && (
                          <Badge variant="outline" className="text-[10px] px-1.5 py-0.5 h-auto font-normal text-foreground bg-foreground/5 border-foreground/20">
                            {item.ordinal_nombre}
                          </Badge>
                        )}
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0.5 h-auto font-normal text-destructive bg-destructive/5 border-destructive/20">
                          {item.sentido_fallo}
                        </Badge>
                        {item.impugnado === 'SI' && (
                          <Badge variant="outline" className="text-[10px] px-1.5 py-0.5 h-auto font-normal text-violet-700 bg-violet-50 border-violet-200">
                            Impugnado
                          </Badge>
                        )}
                      </div>

                      {/* Chips fila 2: tipo_plazo + destinatario_tipo + verbo + evidencia (solo si v2) */}
                      {(item.tipo_plazo || item.destinatario_tipo || item.evidencia_doc_id) && (
                        <div className="flex flex-wrap gap-1 mt-1.5">
                          {item.tipo_plazo && <TipoPlazoChip tipo={item.tipo_plazo} />}
                          {item.destinatario_tipo && <DestinatarioChip tipo={item.destinatario_tipo} />}
                          {item.verbo_orden && (
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border bg-slate-50 text-slate-700 border-slate-200">
                              {item.verbo_orden}
                            </span>
                          )}
                          {item.evidencia_doc_id && (
                            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border bg-emerald-50 text-emerald-800 border-emerald-200" title={`Documento de evidencia #${item.evidencia_doc_id}`}>
                              <CheckCircle size={10} /> evidencia
                            </span>
                          )}
                        </div>
                      )}

                      {/* Acción resumida */}
                      {item.accion_resumida ? (
                        <p className="text-xs text-foreground line-clamp-2 mt-1.5">{item.accion_resumida}</p>
                      ) : item.orden_judicial ? (
                        <p className="text-xs text-muted-foreground line-clamp-2 mt-1.5">
                          {item.orden_judicial}
                        </p>
                      ) : (
                        <button
                          onClick={() => extractMut.mutate(item.id)}
                          disabled={extractMut.isPending}
                          className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 font-medium transition-colors mt-1.5"
                        >
                          <Cpu size={12} />
                          Obtener datos
                        </button>
                      )}

                      {/* Anotaciones especiales: condición / fecha específica */}
                      {item.condicion && (
                        <p className="text-[10px] text-cyan-700 mt-1 italic line-clamp-2">
                          <GitBranch size={10} className="inline mr-1" />
                          <strong>Condición:</strong> {item.condicion}
                        </p>
                      )}
                      {item.fecha_especifica && (
                        <p className="text-[10px] text-orange-700 mt-1">
                          <Calendar size={10} className="inline mr-1" />
                          Fecha exacta: <strong>{item.fecha_especifica}</strong>
                        </p>
                      )}

                      <MiniTimeline pipeline={item.pipeline} />
                    </TableCell>

                    {/* Plazo */}
                    <TableCell className="py-3">
                      {item.fecha_limite ? (
                        <div>
                          <p className="text-xs font-mono text-foreground">{item.fecha_limite}</p>
                          {item.dias_restantes !== null && (
                            <p className={cn(
                              'text-[10px] font-semibold mt-0.5',
                              item.dias_restantes < 0 ? 'text-destructive' :
                              item.dias_restantes <= 3 ? 'text-orange-600' :
                              'text-emerald-600'
                            )}>
                              {item.dias_restantes < 0
                                ? `Vencido hace ${Math.abs(item.dias_restantes)} dias`
                                : item.dias_restantes === 0
                                ? 'Vence HOY'
                                : `${item.dias_restantes} dias restantes`}
                            </p>
                          )}
                        </div>
                      ) : (
                        <div className="flex flex-col gap-1">
                          <span className="text-[10px] text-muted-foreground italic">Sin fecha limite</span>
                          {!item.orden_judicial && (
                            <button
                              onClick={() => extractMut.mutate(item.id)}
                              disabled={extractMut.isPending}
                              className="flex items-center gap-1 text-[10px] text-primary hover:text-primary/80 font-medium transition-colors"
                            >
                              <Cpu size={10} />
                              Obtener plazo
                            </button>
                          )}
                        </div>
                      )}
                    </TableCell>

                    {/* Acciones */}
                    <TableCell className="py-3">
                      <div className="flex flex-col gap-1 items-stretch">
                        {/* Cumplido */}
                        {item.estado !== 'CUMPLIDO' && (
                          <button
                            onClick={() => updateMut.mutate({
                              id: item.id,
                              body: {
                                estado: 'CUMPLIDO',
                                fecha_cumplimiento: new Date().toLocaleDateString('es-CO', {
                                  day: '2-digit', month: '2-digit', year: 'numeric',
                                }),
                                notas: _appendNota(item.notas, 'CUMPLIDO marcado manualmente'),
                              },
                              toastMsg: '✓ Marcado CUMPLIDO. Se movió al filtro "Cumplido".',
                            })}
                            className="inline-flex items-center justify-center gap-1 text-[10px] font-medium px-2 py-1 rounded border border-emerald-300 text-emerald-700 bg-emerald-50/40 hover:bg-emerald-100 hover:border-emerald-400 transition-colors"
                            title="Marcar como cumplido"
                          >
                            <Check size={11} /> Cumplido
                          </button>
                        )}

                        {/* Sin competencia (NO_APLICA con razón explícita) */}
                        {item.estado !== 'NO_APLICA' && (
                          <button
                            onClick={() => updateMut.mutate({
                              id: item.id,
                              body: {
                                estado: 'NO_APLICA',
                                notas: _appendNota(item.notas, 'SIN_COMPETENCIA: SED Santander no es competente — municipio certificado o falta legitimación por pasiva'),
                              },
                              toastMsg: '🚫 Marcado SIN COMPETENCIA. Se movió al filtro "No Aplica".',
                            })}
                            className="inline-flex items-center justify-center gap-1 text-[10px] font-medium px-2 py-1 rounded border border-stone-300 text-stone-700 bg-stone-50/40 hover:bg-stone-100 hover:border-stone-400 transition-colors"
                            title="Marcar sin competencia (NO_APLICA por falta de legitimación pasiva)"
                          >
                            <Ban size={11} /> Sin comp.
                          </button>
                        )}

                        {/* Dropdown "Estado ▾" con TODOS los estados disponibles */}
                        <DropdownMenu>
                          <DropdownMenuTrigger
                            className="inline-flex items-center justify-center gap-1 text-[10px] font-medium px-2 py-1 rounded border border-indigo-300 text-indigo-700 bg-indigo-50/40 hover:bg-indigo-100 hover:border-indigo-400 transition-colors"
                            title={`Cambiar estado (actual: ${item.estado})`}
                          >
                            Estado <ChevronDown size={11} />
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-52">
                            <div className="px-2 py-1.5 text-[10px] uppercase tracking-wide text-muted-foreground font-semibold">
                              Estado actual: {item.estado}
                            </div>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              disabled={item.estado === 'PENDIENTE'}
                              onClick={() => updateMut.mutate({
                                id: item.id,
                                body: {
                                  estado: 'PENDIENTE',
                                  fecha_cumplimiento: '',
                                  notas: _appendNota(item.notas, `Estado cambiado a PENDIENTE (desde ${item.estado})`),
                                },
                                toastMsg: '⏸ Marcado PENDIENTE. Se movió al filtro "Todos / por vencer".',
                              })}
                            >
                              <Pause size={12} className="mr-2 text-slate-600" />
                              <div className="flex flex-col">
                                <span className="font-medium">Pendiente</span>
                                <span className="text-[9px] text-muted-foreground">esperando acción</span>
                              </div>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              disabled={item.estado === 'EN_PROCESO'}
                              onClick={() => updateMut.mutate({
                                id: item.id,
                                body: {
                                  estado: 'EN_PROCESO',
                                  notas: _appendNota(item.notas, `Estado cambiado a EN_PROCESO (desde ${item.estado}) — SED está gestionando respuesta`),
                                },
                                toastMsg: '⏳ Marcado EN_PROCESO. Se movió al filtro "En Proceso".',
                              })}
                            >
                              <Hourglass size={12} className="mr-2 text-sky-600" />
                              <div className="flex flex-col">
                                <span className="font-medium">En proceso</span>
                                <span className="text-[9px] text-muted-foreground">SED gestionando</span>
                              </div>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              disabled={item.estado === 'CUMPLIDO'}
                              onClick={() => updateMut.mutate({
                                id: item.id,
                                body: {
                                  estado: 'CUMPLIDO',
                                  fecha_cumplimiento: new Date().toLocaleDateString('es-CO', { day: '2-digit', month: '2-digit', year: 'numeric' }),
                                  notas: _appendNota(item.notas, 'Estado cambiado a CUMPLIDO'),
                                },
                                toastMsg: '✓ Marcado CUMPLIDO.',
                              })}
                            >
                              <Check size={12} className="mr-2 text-emerald-600" />
                              <div className="flex flex-col">
                                <span className="font-medium">Cumplido</span>
                                <span className="text-[9px] text-muted-foreground">orden ejecutada</span>
                              </div>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              disabled={item.estado === 'IMPUGNADO'}
                              onClick={() => updateMut.mutate({
                                id: item.id,
                                body: {
                                  estado: 'IMPUGNADO',
                                  impugnado: 'SI',
                                  notas: _appendNota(item.notas, `Estado cambiado a IMPUGNADO (desde ${item.estado})`),
                                },
                                toastMsg: '⚖ Marcado IMPUGNADO. Se movió al filtro "Impugnado".',
                              })}
                            >
                              <Scale size={12} className="mr-2 text-violet-600" />
                              <div className="flex flex-col">
                                <span className="font-medium">Impugnado</span>
                                <span className="text-[9px] text-muted-foreground">recurso interpuesto</span>
                              </div>
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              disabled={item.estado === 'VENCIDO'}
                              onClick={() => updateMut.mutate({
                                id: item.id,
                                body: {
                                  estado: 'VENCIDO',
                                  notas: _appendNota(item.notas, `Estado cambiado a VENCIDO manualmente (desde ${item.estado}) — candidato a desacato`),
                                },
                                toastMsg: '⚠ Marcado VENCIDO. Candidato a desacato.',
                              })}
                            >
                              <AlertCircle size={12} className="mr-2 text-red-600" />
                              <div className="flex flex-col">
                                <span className="font-medium">Vencido</span>
                                <span className="text-[9px] text-muted-foreground">candidato a desacato</span>
                              </div>
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              disabled={item.estado === 'NO_APLICA'}
                              onClick={() => updateMut.mutate({
                                id: item.id,
                                body: {
                                  estado: 'NO_APLICA',
                                  notas: _appendNota(item.notas, `Estado cambiado a NO_APLICA (desde ${item.estado})`),
                                },
                                toastMsg: '🚫 Marcado NO_APLICA.',
                              })}
                            >
                              <Ban size={12} className="mr-2 text-stone-600" />
                              <div className="flex flex-col">
                                <span className="font-medium">No aplica</span>
                                <span className="text-[9px] text-muted-foreground">sin obligación SED</span>
                              </div>
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>

                        {/* Nota libre — con conteo visible si hay notas previas */}
                        <button
                          onClick={() => {
                            setNotaModal({ id: item.id, folder: item.accionante || item.folder_name, currentNotas: item.notas || '' })
                            setNotaTexto('')
                          }}
                          className="inline-flex items-center justify-center gap-1 text-[10px] font-medium px-2 py-1 rounded border border-amber-300 text-amber-700 bg-amber-50/40 hover:bg-amber-100 hover:border-amber-400 transition-colors"
                          title={_countNotas(item.notas) > 0 ? `Ver/agregar notas (${_countNotas(item.notas)} existentes)` : 'Agregar nota libre al expediente'}
                        >
                          <StickyNote size={11} />
                          {_countNotas(item.notas) > 0 ? `Notas (${_countNotas(item.notas)})` : 'Nota'}
                        </button>

                        {/* Historial — todo el audit log del case */}
                        <button
                          onClick={() => {
                            setHistorialCaseId(item.case_id)
                            setHistorialLabel(`${item.radicado_corto ? item.radicado_corto + ' · ' : ''}${item.accionante || item.folder_name}`)
                          }}
                          className="inline-flex items-center justify-center gap-1 text-[10px] font-medium px-2 py-1 rounded border border-cyan-300 text-cyan-700 bg-cyan-50/40 hover:bg-cyan-100 hover:border-cyan-400 transition-colors"
                          title="Ver historial completo del expediente (cambios, creación, traslados, etc.)"
                        >
                          <History size={11} /> Historial
                        </button>

                        {/* Ver tutela */}
                        <button
                          onClick={() => item.case_id && navigate(`/cases/${item.case_id}`)}
                          className="inline-flex items-center justify-center gap-1 text-[10px] font-medium px-2 py-1 rounded border border-slate-300 text-slate-700 hover:bg-slate-100 transition-colors"
                          title="Abrir expediente"
                        >
                          <ExternalLink size={11} /> Abrir
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      {/* Modal de nota libre — historial visible + agregar nueva sin cerrar */}
      <Dialog open={!!notaModal} onOpenChange={(open) => !open && setNotaModal(null)}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <StickyNote size={16} className="text-amber-600" />
              Notas del expediente
            </DialogTitle>
            <p className="text-xs text-muted-foreground mt-1">
              <span className="font-medium text-foreground">{notaModal?.folder}</span>
            </p>
          </DialogHeader>

          {/* Historial — siempre visible, scrolleable */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                Historial ({_countNotas(notaModal?.currentNotas)} {_countNotas(notaModal?.currentNotas) === 1 ? 'nota' : 'notas'})
              </p>
            </div>
            <div className="rounded border border-border bg-muted/30 p-3 max-h-48 overflow-y-auto">
              {notaModal?.currentNotas ? (
                <pre className="text-[11px] text-foreground whitespace-pre-wrap font-sans leading-relaxed">{notaModal.currentNotas}</pre>
              ) : (
                <p className="text-[11px] text-muted-foreground italic">Sin notas todavía — agregá la primera abajo.</p>
              )}
            </div>
          </div>

          {/* Agregar nueva */}
          <div className="space-y-1.5">
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">Agregar nueva nota</p>
            <Textarea
              value={notaTexto}
              onChange={(e) => setNotaTexto(e.target.value)}
              placeholder="Escribí la nota (contexto jurídico, acción tomada, recordatorio, etc.)"
              rows={4}
              className="resize-none"
              autoFocus
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setNotaModal(null)}>Cerrar</Button>
            <Button
              onClick={() => {
                if (!notaModal || !notaTexto.trim()) return
                const nuevaNotas = _appendNota(notaModal.currentNotas, notaTexto.trim())
                updateMut.mutate({
                  id: notaModal.id,
                  body: { notas: nuevaNotas },
                  toastMsg: '📝 Nota agregada al historial.',
                }, {
                  onSuccess: () => {
                    // Refrescar el modal con la nota nueva apilada — NO cerrar.
                    setNotaModal({ ...notaModal, currentNotas: nuevaNotas })
                    setNotaTexto('')
                  },
                })
              }}
              disabled={!notaTexto.trim() || updateMut.isPending}
            >
              {updateMut.isPending ? <Loader2 size={14} className="animate-spin mr-1.5" /> : <StickyNote size={14} className="mr-1.5" />}
              Guardar nota
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Historial del expediente (audit log) */}
      <HistorialModal
        caseId={historialCaseId}
        caseLabel={historialLabel}
        onClose={() => setHistorialCaseId(null)}
      />
    </PageShell>
  )
}
