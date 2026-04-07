import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Search, Filter, ChevronLeft, ChevronRight, AlertCircle, Loader2, RefreshCw } from 'lucide-react'
import { getCases, getFilterOptions, syncFolders, getSyncStatus } from '../services/api'

type BadgeEstado = 'ACTIVO' | 'INACTIVO'
type BadgeFallo = 'CONCEDE' | 'NIEGA' | 'IMPROCEDENTE' | ''

function EstadoBadge({ estado }: { estado: string }) {
  const styles: Record<string, string> = {
    ACTIVO: 'bg-amber-100 text-amber-700 border border-amber-200',
    INACTIVO: 'bg-green-100 text-green-700 border border-green-200',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${styles[estado] ?? 'bg-gray-100 text-gray-600'}`}>
      {estado || '—'}
    </span>
  )
}

function FalloBadge({ fallo }: { fallo: string }) {
  const styles: Record<string, string> = {
    CONCEDE: 'bg-red-100 text-red-700 border border-red-200',
    NIEGA: 'bg-green-100 text-green-700 border border-green-200',
    IMPROCEDENTE: 'bg-orange-100 text-orange-700 border border-orange-200',
  }
  if (!fallo) return <span className="text-gray-300 text-xs">—</span>
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${styles[fallo] ?? 'bg-gray-100 text-gray-600'}`}>
      {fallo}
    </span>
  )
}

export default function CasesList() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [estado, setEstado] = useState('')
  const [fallo, setFallo] = useState('')
  const [ciudad, setCiudad] = useState('')
  const [page, setPage] = useState(1)
  const pageSize = 20

  const syncStatusQ = useQuery({
    queryKey: ['sync-status'],
    queryFn: getSyncStatus,
    refetchInterval: 2000,
  })
  const isSyncing = syncStatusQ.data?.in_progress ?? false

  const syncMut = useMutation({
    mutationFn: syncFolders,
    onSuccess: (data) => {
      if (data.status === 'started') toast.success('Sincronizacion iniciada')
      else if (data.status === 'running') toast('Ya hay una sincronizacion en progreso', { icon: 'ℹ️' })
    },
    onError: () => toast.error('Error al sincronizar'),
  })

  // Refrescar datos cuando sync termina (ProgressModal muestra el resumen)
  const lastSyncStep = useRef('')
  const syncStep = syncStatusQ.data?.step ?? ''
  useEffect(() => {
    if (!isSyncing && syncStep.startsWith('Listo') && lastSyncStep.current !== syncStep) {
      lastSyncStep.current = syncStep
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['filter-options'] })
      qc.invalidateQueries({ queryKey: ['kpis'] })
    }
  }, [isSyncing, syncStep, qc])

  const params = {
    search,
    estado,
    fallo,
    ciudad,
    page,
    page_size: pageSize,
  }

  const casesQ = useQuery({
    queryKey: ['cases', params],
    queryFn: () => getCases(params),
    placeholderData: (prev) => prev,
  })

  const filtersQ = useQuery({
    queryKey: ['filter-options'],
    queryFn: getFilterOptions,
  })

  const cases = casesQ.data?.items ?? []
  const total = casesQ.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  function handleSearch(v: string) {
    setSearch(v)
    setPage(1)
  }

  function handleFilter(key: string, value: string) {
    if (key === 'estado') setEstado(value)
    if (key === 'fallo') setFallo(value)
    if (key === 'ciudad') setCiudad(value)
    setPage(1)
  }

  const filterOptions = filtersQ.data ?? {}

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Tutelas</h1>
          <p className="text-sm text-gray-500 mt-1">
            {casesQ.isFetching
              ? 'Cargando...'
              : `${total} caso${total !== 1 ? 's' : ''} encontrado${total !== 1 ? 's' : ''}`
            }
          </p>
        </div>
        <button
          onClick={() => syncMut.mutate()}
          disabled={isSyncing}
          className="flex items-center gap-2 px-4 py-2.5 bg-[#1A5276] text-white text-sm font-medium rounded-lg hover:bg-[#154360] disabled:opacity-50 transition-colors shadow-sm"
        >
          {isSyncing ? (
            <Loader2 size={15} className="animate-spin" />
          ) : (
            <RefreshCw size={15} />
          )}
          {isSyncing ? 'Sincronizando...' : 'Sincronizar'}
        </button>
      </div>

      {/* Search + Filters */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 space-y-3">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
          <input
            type="text"
            placeholder="Buscar por accionante, radicado, juzgado..."
            value={search}
            onChange={(e) => handleSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2.5 text-sm border border-gray-300 rounded-lg bg-gray-50 focus:bg-white focus:border-[#1A5276] focus:outline-none focus:ring-2 focus:ring-[#1A5276]/20 transition-all"
          />
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 text-gray-400">
            <Filter size={14} />
            <span className="text-xs font-medium">Filtros:</span>
          </div>

          <select
            value={estado}
            onChange={(e) => handleFilter('estado', e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white focus:border-[#1A5276] focus:outline-none focus:ring-2 focus:ring-[#1A5276]/20 text-gray-700"
          >
            <option value="">Todos los estados</option>
            <option value="ACTIVO">Activo</option>
            <option value="INACTIVO">Inactivo</option>
          </select>

          <select
            value={fallo}
            onChange={(e) => handleFilter('fallo', e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white focus:border-[#1A5276] focus:outline-none focus:ring-2 focus:ring-[#1A5276]/20 text-gray-700"
          >
            <option value="">Todos los fallos</option>
            <option value="CONCEDE">Concede</option>
            <option value="NIEGA">Niega</option>
            <option value="IMPROCEDENTE">Improcedente</option>
          </select>

          <select
            value={ciudad}
            onChange={(e) => handleFilter('ciudad', e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white focus:border-[#1A5276] focus:outline-none focus:ring-2 focus:ring-[#1A5276]/20 text-gray-700 max-w-[200px]"
          >
            <option value="">Todas las ciudades</option>
            {(filterOptions.ciudades ?? []).map((c: string) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          {(search || estado || fallo || ciudad) && (
            <button
              onClick={() => { setSearch(''); setEstado(''); setFallo(''); setCiudad(''); setPage(1) }}
              className="text-xs text-red-500 hover:text-red-700 underline"
            >
              Limpiar filtros
            </button>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {casesQ.isError ? (
          <div className="flex items-center gap-2 text-red-500 text-sm px-5 py-8">
            <AlertCircle size={16} />
            Error al cargar los casos. Verifique que el servidor este activo.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50">
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide w-10">#</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Radicado</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Accionante</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">Juzgado</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden lg:table-cell">Ciudad</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Estado</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Fallo</th>
                    <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden xl:table-cell">Abogado</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {casesQ.isLoading ? (
                    Array.from({ length: 8 }).map((_, i) => (
                      <tr key={i} className="animate-pulse">
                        {Array.from({ length: 8 }).map((_, j) => (
                          <td key={j} className="px-4 py-3">
                            <div className="h-3 bg-gray-200 rounded w-3/4" />
                          </td>
                        ))}
                      </tr>
                    ))
                  ) : cases.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="text-center py-12 text-gray-400">
                        No se encontraron casos
                      </td>
                    </tr>
                  ) : (
                    cases.map((c: {
                      id: number
                      folder_name: string
                      ACCIONANTE?: string
                      JUZGADO?: string
                      CIUDAD?: string
                      ESTADO?: string
                      SENTIDO_FALLO_1ST?: string
                      ABOGADO_RESPONSABLE?: string
                    }, idx: number) => (
                      <tr
                        key={c.id}
                        onClick={() => navigate(`/cases/${c.id}`)}
                        className="hover:bg-[#1A5276]/5 cursor-pointer transition-colors"
                      >
                        <td className="px-4 py-3 text-gray-400 text-xs">
                          {(page - 1) * pageSize + idx + 1}
                        </td>
                        <td className="px-4 py-3">
                          <span className="font-mono text-xs text-[#1A5276] font-medium">
                            {c.folder_name}
                          </span>
                          {c.CIUDAD && (
                            <span className="ml-1.5 text-[10px] text-gray-400 font-normal">
                              ({c.CIUDAD})
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-gray-800 font-medium">
                            {c.ACCIONANTE || <span className="text-gray-300">—</span>}
                          </span>
                        </td>
                        <td className="px-4 py-3 hidden md:table-cell">
                          <span className="text-gray-600 text-xs">
                            {c.JUZGADO || <span className="text-gray-300">—</span>}
                          </span>
                        </td>
                        <td className="px-4 py-3 hidden lg:table-cell">
                          <span className="text-gray-600 text-xs">{c.CIUDAD || '—'}</span>
                        </td>
                        <td className="px-4 py-3">
                          <EstadoBadge estado={c.ESTADO as BadgeEstado ?? ''} />
                        </td>
                        <td className="px-4 py-3">
                          <FalloBadge fallo={c.SENTIDO_FALLO_1ST as BadgeFallo ?? ''} />
                        </td>
                        <td className="px-4 py-3 hidden xl:table-cell">
                          <span className="text-gray-500 text-xs">
                            {c.ABOGADO_RESPONSABLE || '—'}
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100 bg-gray-50">
                <p className="text-xs text-gray-500">
                  Pagina {page} de {totalPages} — {total} casos
                </p>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setPage(Math.max(1, page - 1))}
                    disabled={page === 1}
                    className="p-1.5 rounded-lg text-gray-500 hover:bg-white hover:shadow-sm disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  {Array.from({ length: Math.min(5, totalPages) }).map((_, i) => {
                    const p = Math.max(1, Math.min(totalPages - 4, page - 2)) + i
                    return (
                      <button
                        key={p}
                        onClick={() => setPage(p)}
                        className={`min-w-[32px] h-8 px-2 rounded-lg text-xs font-medium transition-all ${
                          p === page
                            ? 'bg-[#1A5276] text-white shadow-sm'
                            : 'text-gray-600 hover:bg-white hover:shadow-sm'
                        }`}
                      >
                        {p}
                      </button>
                    )
                  })}
                  <button
                    onClick={() => setPage(Math.min(totalPages, page + 1))}
                    disabled={page === totalPages}
                    className="p-1.5 rounded-lg text-gray-500 hover:bg-white hover:shadow-sm disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
                {casesQ.isFetching && (
                  <Loader2 size={14} className="animate-spin text-[#1A5276]" />
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
