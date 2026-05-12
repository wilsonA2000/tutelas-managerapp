import { useState, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Search, Download, ChevronDown, ChevronUp, Check, X, Columns3, Table2, AlertTriangle, Sparkles } from 'lucide-react'
import {
  getCasesTable, updateCase, generateExcel,
  v9ExtractBatch,
  type V9BatchResponse, type V9ExtractionResult,
} from '../services/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
} from '@/components/ui/dropdown-menu'

// Columnas ocultas por defecto (se muestran con toggle)
const HIDDEN_BY_DEFAULT = new Set([
  'INCIDENTE_2', 'FECHA_APERTURA_INCIDENTE_2', 'RESPONSABLE_DESACATO_2', 'DECISION_INCIDENTE_2',
  'INCIDENTE_3', 'FECHA_APERTURA_INCIDENTE_3', 'RESPONSABLE_DESACATO_3', 'DECISION_INCIDENTE_3',
  'VINCULADOS', 'PRETENSIONES', 'FOREST_IMPUGNACION', 'JUZGADO_2ND', 'FECHA_FALLO_2ND',
])

const ALL_COLUMNS = [
  { key: 'tipo_actuacion', label: 'Tipo', width: 85, editable: false },
  { key: 'completitud', label: '%', width: 45, editable: false },
  { key: 'RADICADO_23_DIGITOS', label: 'Radicado 23D', width: 160 },
  { key: 'RADICADO_FOREST', label: 'Forest', width: 100 },
  { key: 'ACCIONANTE', label: 'Accionante', width: 180 },
  { key: 'ACCIONADOS', label: 'Accionados', width: 160 },
  { key: 'VINCULADOS', label: 'Vinculados', width: 140 },
  { key: 'DERECHO_VULNERADO', label: 'Derecho', width: 130 },
  { key: 'JUZGADO', label: 'Juzgado', width: 180 },
  { key: 'CIUDAD', label: 'Ciudad', width: 110 },
  { key: 'FECHA_INGRESO', label: 'F.Ingreso', width: 90 },
  { key: 'ASUNTO', label: 'Asunto', width: 200 },
  { key: 'PRETENSIONES', label: 'Pretensiones', width: 200 },
  { key: 'OFICINA_RESPONSABLE', label: 'Oficina', width: 140 },
  { key: 'CATEGORIA_TEMATICA', label: 'Categoría', width: 140 },
  { key: 'ABOGADO_RESPONSABLE', label: 'Abogado', width: 140 },
  { key: 'ESTADO', label: 'Estado', width: 70 },
  { key: 'FECHA_RESPUESTA', label: 'F.Respuesta', width: 90 },
  { key: 'SENTIDO_FALLO_1ST', label: 'Fallo 1ra', width: 90 },
  { key: 'FECHA_FALLO_1ST', label: 'F.Fallo 1ra', width: 90 },
  { key: 'IMPUGNACION', label: 'Impugn.', width: 65 },
  { key: 'QUIEN_IMPUGNO', label: 'Quien Impugnó', width: 110 },
  { key: 'FOREST_IMPUGNACION', label: 'Forest Imp.', width: 100 },
  { key: 'JUZGADO_2ND', label: 'Juzgado 2da', width: 160 },
  { key: 'SENTIDO_FALLO_2ND', label: 'Fallo 2da', width: 80 },
  { key: 'FECHA_FALLO_2ND', label: 'F.Fallo 2da', width: 90 },
  { key: 'INCIDENTE', label: 'Incid.', width: 55 },
  { key: 'FECHA_APERTURA_INCIDENTE', label: 'F.Incidente', width: 90 },
  { key: 'RESPONSABLE_DESACATO', label: 'Resp.Desacato', width: 130 },
  { key: 'DECISION_INCIDENTE', label: 'Decision Inc.', width: 140 },
  { key: 'INCIDENTE_2', label: 'Inc.2', width: 50 },
  { key: 'FECHA_APERTURA_INCIDENTE_2', label: 'F.Inc.2', width: 90 },
  { key: 'RESPONSABLE_DESACATO_2', label: 'Resp.Des.2', width: 130 },
  { key: 'DECISION_INCIDENTE_2', label: 'Decision Inc.2', width: 140 },
  { key: 'INCIDENTE_3', label: 'Inc.3', width: 50 },
  { key: 'FECHA_APERTURA_INCIDENTE_3', label: 'F.Inc.3', width: 90 },
  { key: 'RESPONSABLE_DESACATO_3', label: 'Resp.Des.3', width: 130 },
  { key: 'DECISION_INCIDENTE_3', label: 'Decision Inc.3', width: 140 },
  { key: 'OBSERVACIONES', label: 'Observaciones', width: 220 },
]

type ConfBand = 'OK' | 'REVISAR' | 'BAJO'
type CaseRow = Record<string, string | number | Record<string, ConfBand>>

export default function Cuadro() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [sortCol, setSortCol] = useState('')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [editCell, setEditCell] = useState<{ id: number; col: string } | null>(null)
  const [editValue, setEditValue] = useState('')
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(new Set(HIDDEN_BY_DEFAULT))

  const COLUMNS = ALL_COLUMNS.filter(c => !hiddenCols.has(c.key))
  const [colFilters, setColFilters] = useState<Record<string, string>>({})
  const [onlyFindings, setOnlyFindings] = useState(false)

  // v9: panel de preview / aplicar extracción simplificada
  const [v9Open, setV9Open] = useState(false)
  const [v9Limit, setV9Limit] = useState(10)
  const [v9Data, setV9Data] = useState<V9BatchResponse | null>(null)

  const v9Mut = useMutation({
    mutationFn: (params: { limit: number; apply: boolean }) => v9ExtractBatch(params),
    onSuccess: (data) => {
      setV9Data(data)
      const verb = data.applied ? 'aplicada' : 'previsualizada'
      toast.success(
        `v9 ${verb}: ${data.count} casos · ${data.summary.avg_completitud}% avg · ` +
        `${data.summary.ms_per_case}ms/caso · ${data.summary.total_llm_calls} LLM calls`
      )
      if (data.applied) qc.invalidateQueries({ queryKey: ['cases-table'] })
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(`v9 error: ${msg}`)
    },
  })

  const dataQ = useQuery({ queryKey: ['cases-table'], queryFn: getCasesTable })
  const allRows: CaseRow[] = dataQ.data ?? []

  // v8.3: extrae # findings (bandas REVISAR + BAJO) por fila
  const findingsCount = useCallback((row: CaseRow): number => {
    const conf = row._confidences as Record<string, ConfBand> | undefined
    if (!conf) return 0
    return Object.values(conf).filter(b => b === 'REVISAR' || b === 'BAJO').length
  }, [])

  const updateMut = useMutation({
    mutationFn: ({ id, fields }: { id: number; fields: Record<string, string> }) => updateCase(id, fields),
    onSuccess: () => {
      toast.success('Guardado')
      qc.invalidateQueries({ queryKey: ['cases-table'] })
    },
    onError: () => toast.error('Error al guardar'),
  })

  const excelMut = useMutation({
    mutationFn: generateExcel,
    onSuccess: (data) => {
      toast.success('Excel generado')
      if (data.download_url || data.filename) window.open(data.download_url ?? `/api/reports/excel/download/${data.filename}`, '_blank')
    },
  })

  // Filtrar
  const filtered = useMemo(() => {
    let rows = allRows
    if (search) {
      const s = search.toLowerCase()
      rows = rows.filter(r => Object.values(r).some(v => String(v).toLowerCase().includes(s)))
    }
    for (const [col, val] of Object.entries(colFilters)) {
      if (val) {
        const v = val.toLowerCase()
        rows = rows.filter(r => String(r[col] || '').toLowerCase().includes(v))
      }
    }
    if (onlyFindings) {
      rows = rows.filter(r => findingsCount(r) > 0)
    }
    return rows
  }, [allRows, search, colFilters, onlyFindings, findingsCount])

  // Ordenar
  const sorted = useMemo(() => {
    if (!sortCol) return filtered
    return [...filtered].sort((a, b) => {
      const av = String(a[sortCol] || ''), bv = String(b[sortCol] || '')
      const cmp = av.localeCompare(bv, 'es', { numeric: true })
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [filtered, sortCol, sortDir])

  const handleSort = useCallback((col: string) => {
    if (sortCol === col) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortCol(col)
      setSortDir('asc')
    }
  }, [sortCol])

  const startEdit = (id: number, col: string, value: string) => {
    setEditCell({ id, col })
    setEditValue(value)
  }

  const saveEdit = () => {
    if (!editCell) return
    updateMut.mutate({ id: editCell.id, fields: { [editCell.col]: editValue } })
    setEditCell(null)
  }

  const cancelEdit = () => setEditCell(null)

  const totalWidth = COLUMNS.reduce((s, c) => s + c.width, 0) + 50

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-border bg-background">
        <div className="flex items-center justify-between mb-2.5">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 rounded-lg bg-primary/10">
              <Table2 size={16} className="text-primary" />
            </div>
            <div>
              <h1 className="text-base font-semibold tracking-tight text-foreground">Cuadro de Tutelas</h1>
              <p className="text-xs text-muted-foreground">
                {sorted.length} de {allRows.length} casos &mdash; clic en celda para editar
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant={onlyFindings ? 'default' : 'outline'}
              size="sm"
              className="gap-1.5 text-xs h-8"
              onClick={() => setOnlyFindings(v => !v)}
              title="Solo casos con celdas en banda REVISAR o BAJO"
            >
              <AlertTriangle size={13} className={onlyFindings ? '' : 'text-amber-500'} />
              Solo findings
            </Button>
            {/* Column picker via shadcn DropdownMenu */}
            <DropdownMenu>
              <DropdownMenuTrigger
                render={<Button variant="outline" size="sm" className="gap-1.5 text-xs h-8" />}
              >
                <Columns3 size={13} />
                Columnas ({COLUMNS.length}/{ALL_COLUMNS.length})
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64 max-h-80 overflow-y-auto">
                <div className="px-2 py-1.5 flex items-center gap-2 border-b">
                  <button
                    onClick={() => setHiddenCols(new Set())}
                    className="text-xs text-primary hover:underline"
                  >
                    Todas
                  </button>
                  <span className="text-muted-foreground/40">|</span>
                  <button
                    onClick={() => setHiddenCols(new Set(HIDDEN_BY_DEFAULT))}
                    className="text-xs text-primary hover:underline"
                  >
                    Default
                  </button>
                </div>
                {ALL_COLUMNS.map(col => (
                  <DropdownMenuCheckboxItem
                    key={col.key}
                    checked={!hiddenCols.has(col.key)}
                    onCheckedChange={() => {
                      const next = new Set(hiddenCols)
                      if (next.has(col.key)) next.delete(col.key)
                      else next.add(col.key)
                      setHiddenCols(next)
                    }}
                    className="text-xs"
                  >
                    {col.label}
                  </DropdownMenuCheckboxItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            <Button
              size="sm"
              variant="outline"
              className="gap-1.5 text-xs h-8 border-violet-500 text-violet-700 hover:bg-violet-50"
              onClick={() => { setV9Open(true); v9Mut.mutate({ limit: v9Limit, apply: false }) }}
              disabled={v9Mut.isPending}
              title="Pipeline v9 simplificado: extracción determinística sin contradicciones"
            >
              <Sparkles size={13} />
              {v9Mut.isPending ? 'v9...' : 'v9 Preview'}
            </Button>

            <Button
              size="sm"
              className="gap-1.5 text-xs h-8 bg-emerald-600 hover:bg-emerald-700 text-white"
              onClick={() => excelMut.mutate()}
              disabled={excelMut.isPending}
            >
              <Download size={13} />
              Excel
            </Button>
          </div>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={13} />
          <Input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Buscar en todos los campos..."
            className="pl-8 h-8 text-xs bg-muted/40 border-border focus:bg-background"
          />
        </div>
      </div>

      {/* Table — all cell editing logic preserved exactly */}
      <div className="flex-1 overflow-auto">
        <table style={{ minWidth: totalWidth }} className="text-xs">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className="bg-primary text-white px-1 py-2 text-[11px] font-semibold sticky left-0 z-20" style={{ width: 40 }}>#</th>
              {COLUMNS.map(col => (
                <th key={col.key} className="bg-primary text-white px-1 py-1 text-[11px] font-semibold cursor-pointer select-none"
                  style={{ width: col.width, minWidth: col.width }}
                  onClick={() => handleSort(col.key)}>
                  <div className="flex items-center gap-0.5">
                    <span className="truncate">{col.label}</span>
                    {sortCol === col.key && (sortDir === 'asc' ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
                  </div>
                  {/* Column filter */}
                  <input type="text" value={colFilters[col.key] || ''} placeholder="Filtrar..."
                    onClick={e => e.stopPropagation()}
                    onChange={e => setColFilters(f => ({ ...f, [col.key]: e.target.value }))}
                    className="w-full mt-0.5 px-1 py-0.5 text-[10px] bg-white/20 border border-white/30 rounded text-white placeholder-white/50 focus:bg-white focus:text-gray-800 focus:outline-none" />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, idx) => (
              <tr key={row.id as number} className={`${idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'} hover:bg-blue-50`}>
                <td className="px-1 py-1 text-center text-gray-400 font-mono sticky left-0 bg-inherit border-r border-gray-200" style={{ width: 40 }}>
                  {idx + 1}
                </td>
                {COLUMNS.map(col => {
                  const val = String(row[col.key] ?? '')
                  const isEditing = editCell?.id === row.id && editCell?.col === col.key
                  const isEmpty = !val.trim() && col.key !== 'completitud' && col.key !== 'tipo_actuacion'
                  const isCompletitud = col.key === 'completitud'
                  const isTipo = col.key === 'tipo_actuacion'

                  if (isTipo) {
                    const tipo = val || 'TUTELA'
                    const colors: Record<string, string> = {
                      TUTELA: 'bg-blue-100 text-blue-700',
                      INCIDENTE: 'bg-purple-100 text-purple-700',
                    }
                    return (
                      <td key={col.key} className="px-1 py-1 text-center" style={{ width: col.width }}>
                        <span className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-bold ${colors[tipo] ?? 'bg-gray-100 text-gray-600'}`}>
                          {tipo}
                        </span>
                      </td>
                    )
                  }

                  if (isCompletitud) {
                    const pct = Number(val) || 0
                    return (
                      <td key={col.key} className="px-1 py-1 text-center" style={{ width: col.width }}>
                        <div className="flex items-center gap-1">
                          <div className="flex-1 bg-gray-200 rounded-full h-1.5">
                            <div className={`h-1.5 rounded-full ${pct >= 70 ? 'bg-green-500' : pct >= 40 ? 'bg-amber-500' : 'bg-red-400'}`}
                              style={{ width: `${pct}%` }} />
                          </div>
                          <span className="text-[10px] text-gray-500 w-6">{pct}%</span>
                        </div>
                      </td>
                    )
                  }

                  if (isEditing) {
                    return (
                      <td key={col.key} className="px-0 py-0" style={{ width: col.width }}>
                        <div className="flex items-center">
                          <input type="text" value={editValue} onChange={e => setEditValue(e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter') saveEdit(); if (e.key === 'Escape') cancelEdit(); }}
                            autoFocus
                            className="w-full px-1 py-1 text-xs border-2 border-primary bg-blue-50 focus:outline-none" />
                          <button onClick={saveEdit} className="p-0.5 text-green-600"><Check size={12} /></button>
                          <button onClick={cancelEdit} className="p-0.5 text-red-500"><X size={12} /></button>
                        </div>
                      </td>
                    )
                  }

                  // v8.3: banda de confianza por celda
                  const conf = row._confidences as Record<string, ConfBand> | undefined
                  const band = conf?.[col.key]
                  const bandClass =
                    band === 'REVISAR' ? 'bg-amber-50 border-l-2 border-l-amber-400' :
                    band === 'BAJO'    ? 'bg-red-50 border-l-2 border-l-red-400' : ''
                  const bandTitle =
                    band === 'REVISAR' ? '⚠ Revisar — confianza media' :
                    band === 'BAJO'    ? '⚠ Confianza baja — verificar manualmente' : ''

                  return (
                    <td key={col.key}
                      onClick={() => col.editable !== false && startEdit(row.id as number, col.key, val)}
                      className={`px-1 py-1 truncate cursor-pointer border-r border-gray-100 ${isEmpty ? 'bg-gray-50/50' : ''} ${bandClass}`}
                      style={{ width: col.width, maxWidth: col.width }}
                      title={bandTitle ? `${bandTitle}\n${val || 'Vacío'}` : (val || 'Vacío — click para editar')}>
                      {val || <span className="text-gray-300 text-[10px]">---</span>}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {dataQ.isLoading && <div className="text-center py-8 text-gray-400 text-sm">Cargando...</div>}
        {!dataQ.isLoading && sorted.length === 0 && <div className="text-center py-8 text-gray-400 text-sm">Sin resultados</div>}
      </div>

      {/* v9 Preview Modal */}
      {v9Open && (
        <V9PreviewModal
          open={v9Open}
          onClose={() => setV9Open(false)}
          data={v9Data}
          loading={v9Mut.isPending}
          limit={v9Limit}
          setLimit={setV9Limit}
          onRefresh={() => v9Mut.mutate({ limit: v9Limit, apply: false })}
          onApply={() => v9Mut.mutate({ limit: v9Limit, apply: true })}
        />
      )}
    </div>
  )
}

// ============================================================
// v9 Preview Modal — muestra resultados batch de v9 con summary + tabla
// ============================================================

interface V9ModalProps {
  open: boolean
  onClose: () => void
  data: V9BatchResponse | null
  loading: boolean
  limit: number
  setLimit: (n: number) => void
  onRefresh: () => void
  onApply: () => void
}

function V9PreviewModal({ open, onClose, data, loading, limit, setLimit, onRefresh, onApply }: V9ModalProps) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-5xl w-full max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div className="flex items-center gap-2">
            <Sparkles size={18} className="text-violet-600" />
            <h2 className="font-semibold text-base">Pipeline v9 — Preview batch</h2>
            {data?.dry_run === false && data?.applied && (
              <span className="bg-emerald-100 text-emerald-700 text-[10px] px-2 py-0.5 rounded">APLICADO</span>
            )}
            {data?.dry_run && (
              <span className="bg-amber-100 text-amber-700 text-[10px] px-2 py-0.5 rounded">DRY-RUN</span>
            )}
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700"><X size={20} /></button>
        </div>

        {/* Toolbar */}
        <div className="border-b px-4 py-2 bg-gray-50 flex items-center gap-3 text-xs">
          <label className="flex items-center gap-1">
            Casos:
            <input
              type="number" min={1} max={100} value={limit}
              onChange={e => setLimit(Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
              className="w-16 px-1 py-0.5 border rounded"
            />
          </label>
          <Button size="sm" variant="outline" onClick={onRefresh} disabled={loading} className="h-7 text-xs">
            {loading ? 'Corriendo...' : 'Re-ejecutar preview'}
          </Button>
          {data && !data.applied && data.count > 0 && (
            <Button
              size="sm" onClick={onApply} disabled={loading}
              className="h-7 text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
            >
              Aplicar a {data.count} casos
            </Button>
          )}
        </div>

        {/* Summary */}
        <div className="px-4 py-3 border-b bg-violet-50/40">
          {loading && <div className="text-sm text-gray-500">Procesando...</div>}
          {!loading && !data && <div className="text-sm text-gray-500">Sin datos. Click "Re-ejecutar preview".</div>}
          {!loading && data && (
            <div className="grid grid-cols-4 gap-3 text-xs">
              <Metric label="Casos" value={`${data.count}`} />
              <Metric label="Completitud avg" value={`${data.summary.avg_completitud}%`} highlight={data.summary.avg_completitud >= 60} />
              <Metric label="Tiempo / caso" value={`${data.summary.ms_per_case}ms`} highlight={data.summary.ms_per_case < 5000} />
              <Metric label="Total LLM calls" value={`${data.summary.total_llm_calls}`} highlight={data.summary.total_llm_calls < data.count} />
            </div>
          )}
          {data && data.errors_count > 0 && (
            <div className="mt-2 text-xs text-rose-600 flex items-center gap-1">
              <AlertTriangle size={12} /> {data.errors_count} errores — revisa logs
            </div>
          )}
        </div>

        {/* Resultados (tabla) */}
        <div className="flex-1 overflow-auto">
          {data && data.results.length > 0 && (
            <table className="text-[11px] w-full">
              <thead className="bg-gray-100 sticky top-0">
                <tr className="text-left">
                  <th className="px-2 py-1.5 w-16">Case</th>
                  <th className="px-2 py-1.5">Folder</th>
                  <th className="px-2 py-1.5 w-16 text-center">%</th>
                  <th className="px-2 py-1.5 w-20 text-center">Docs</th>
                  <th className="px-2 py-1.5 w-16 text-center">LLM</th>
                  <th className="px-2 py-1.5 w-20 text-right">ms</th>
                  <th className="px-2 py-1.5">Abogado canónico</th>
                  <th className="px-2 py-1.5">Dependencia (L1/L2/L3)</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map(r => <V9ResultRow key={r.case_id} r={r} />)}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

function Metric({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className={`p-2 rounded border ${highlight ? 'bg-emerald-50 border-emerald-200' : 'bg-white border-gray-200'}`}>
      <div className="text-gray-500 text-[10px] uppercase tracking-wide">{label}</div>
      <div className="font-semibold text-sm">{value}</div>
    </div>
  )
}

function V9ResultRow({ r }: { r: V9ExtractionResult }) {
  const [expanded, setExpanded] = useState(false)
  const cano = r.canonical
  const sedHier = [cano.direccion_l1, cano.grupo_l2, cano.equipo_l3].filter(Boolean).join(' › ') || '—'
  return (
    <>
      <tr className="border-t hover:bg-gray-50 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <td className="px-2 py-1.5 font-mono">#{r.case_id}</td>
        <td className="px-2 py-1.5 truncate max-w-[200px]">{r.folder_name}</td>
        <td className={`px-2 py-1.5 text-center font-semibold ${r.completitud >= 60 ? 'text-emerald-700' : r.completitud >= 30 ? 'text-amber-700' : 'text-rose-700'}`}>
          {r.completitud}%
        </td>
        <td className="px-2 py-1.5 text-center">
          {r.docs.processed}{r.docs.failed > 0 && <span className="text-rose-500"> ({r.docs.failed} fail)</span>}
        </td>
        <td className="px-2 py-1.5 text-center">{r.llm_calls}</td>
        <td className="px-2 py-1.5 text-right font-mono">{r.timing_ms.__total ?? 0}</td>
        <td className="px-2 py-1.5 truncate max-w-[180px]">
          {cano.abogado || <span className="text-gray-300">—</span>}
          {cano.abogado && <span className="text-[9px] text-gray-400 ml-1">({cano.abogado_confidence.toFixed(2)})</span>}
        </td>
        <td className="px-2 py-1.5 truncate max-w-[220px]">{sedHier}</td>
      </tr>
      {expanded && (
        <tr className="bg-violet-50/30">
          <td colSpan={8} className="px-3 py-2 text-[10px]">
            <div className="font-semibold mb-1 text-violet-800">Campos extraídos ({Object.values(r.values).filter(Boolean).length}/38):</div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
              {Object.entries(r.values).filter(([, v]) => v).map(([k, v]) => (
                <div key={k} className="flex gap-1 truncate">
                  <span className="font-mono text-violet-700 w-24 flex-shrink-0">[{r.sources[k] || '?'}]</span>
                  <span className="font-medium w-32 flex-shrink-0 truncate">{k}:</span>
                  <span className="text-gray-700 truncate">{String(v)}</span>
                </div>
              ))}
            </div>
            {r.missing_fields.length > 0 && (
              <div className="mt-1 text-gray-500">
                <span className="font-semibold">Vacíos ({r.missing_fields.length}):</span> {r.missing_fields.join(', ')}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}
