import { useState, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Search, Download, Filter, ChevronDown, ChevronUp, Check, X, Columns3 } from 'lucide-react'
import { getCasesTable, updateCase, generateExcel } from '../services/api'

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

type CaseRow = Record<string, string | number>

export default function Cuadro() {
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [sortCol, setSortCol] = useState('')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [editCell, setEditCell] = useState<{ id: number; col: string } | null>(null)
  const [editValue, setEditValue] = useState('')
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(new Set(HIDDEN_BY_DEFAULT))
  const [showColPicker, setShowColPicker] = useState(false)

  const COLUMNS = ALL_COLUMNS.filter(c => !hiddenCols.has(c.key))
  const [colFilters, setColFilters] = useState<Record<string, string>>({})

  const dataQ = useQuery({ queryKey: ['cases-table'], queryFn: getCasesTable })
  const allRows: CaseRow[] = dataQ.data ?? []

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
    return rows
  }, [allRows, search, colFilters])

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
      <div className="flex-shrink-0 p-4 border-b border-gray-200 bg-white">
        <div className="flex items-center justify-between mb-2">
          <div>
            <h1 className="text-xl font-bold text-gray-800">Cuadro de Tutelas</h1>
            <p className="text-xs text-gray-500">
              {sorted.length} de {allRows.length} casos | Click en celda para editar
            </p>
          </div>
          <div className="flex gap-2 relative">
            <button onClick={() => setShowColPicker(!showColPicker)}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-100 text-gray-700 text-xs font-medium rounded-lg hover:bg-gray-200">
              <Columns3 size={13} /> Columnas ({COLUMNS.length}/{ALL_COLUMNS.length})
            </button>
            <button onClick={() => excelMut.mutate()} disabled={excelMut.isPending}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white text-xs font-medium rounded-lg hover:bg-green-700 disabled:opacity-50">
              <Download size={13} /> Excel
            </button>
            {showColPicker && (
              <div className="absolute right-0 top-10 z-30 bg-white border border-gray-200 rounded-xl shadow-xl p-3 w-64 max-h-80 overflow-y-auto">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-gray-600">Columnas visibles</span>
                  <button onClick={() => setShowColPicker(false)} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
                </div>
                <div className="flex gap-1 mb-2">
                  <button onClick={() => setHiddenCols(new Set())} className="text-[10px] text-blue-600 hover:underline">Todas</button>
                  <span className="text-gray-300">|</span>
                  <button onClick={() => setHiddenCols(new Set(HIDDEN_BY_DEFAULT))} className="text-[10px] text-blue-600 hover:underline">Default</button>
                </div>
                {ALL_COLUMNS.map(col => (
                  <label key={col.key} className="flex items-center gap-2 py-0.5 cursor-pointer hover:bg-gray-50 rounded px-1">
                    <input type="checkbox" checked={!hiddenCols.has(col.key)}
                      onChange={() => {
                        const next = new Set(hiddenCols)
                        if (next.has(col.key)) next.delete(col.key)
                        else next.add(col.key)
                        setHiddenCols(next)
                      }}
                      className="rounded border-gray-300 text-[#1A5276] focus:ring-[#1A5276]"
                    />
                    <span className="text-xs text-gray-700">{col.label}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={14} />
          <input type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Buscar en todos los campos..."
            className="w-full pl-9 pr-4 py-2 text-xs border border-gray-300 rounded-lg bg-gray-50 focus:bg-white focus:border-[#1A5276] focus:outline-none" />
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table style={{ minWidth: totalWidth }} className="text-[10px]">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className="bg-[#1A5276] text-white px-1 py-2 text-[9px] font-semibold sticky left-0 z-20" style={{ width: 40 }}>#</th>
              {COLUMNS.map(col => (
                <th key={col.key} className="bg-[#1A5276] text-white px-1 py-1 text-[9px] font-semibold cursor-pointer select-none"
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
                    className="w-full mt-0.5 px-1 py-0.5 text-[8px] bg-white/20 border border-white/30 rounded text-white placeholder-white/50 focus:bg-white focus:text-gray-800 focus:outline-none" />
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
                        <span className={`inline-block px-1.5 py-0.5 rounded text-[9px] font-bold ${colors[tipo] ?? 'bg-gray-100 text-gray-600'}`}>
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
                          <span className="text-[8px] text-gray-500 w-6">{pct}%</span>
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
                            className="w-full px-1 py-1 text-[10px] border-2 border-[#1A5276] bg-blue-50 focus:outline-none" />
                          <button onClick={saveEdit} className="p-0.5 text-green-600"><Check size={12} /></button>
                          <button onClick={cancelEdit} className="p-0.5 text-red-500"><X size={12} /></button>
                        </div>
                      </td>
                    )
                  }

                  return (
                    <td key={col.key}
                      onClick={() => col.editable !== false && startEdit(row.id as number, col.key, val)}
                      className={`px-1 py-1 truncate cursor-pointer border-r border-gray-100 ${isEmpty ? 'bg-red-50' : ''}`}
                      style={{ width: col.width, maxWidth: col.width }}
                      title={val || 'Vacío — click para editar'}>
                      {val || <span className="text-red-300 text-[8px]">---</span>}
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
    </div>
  )
}
