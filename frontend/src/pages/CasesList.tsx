import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Search, Filter, ChevronLeft, ChevronRight, AlertCircle, Loader2, RefreshCw, Scale } from 'lucide-react'
import { getCases, getFilterOptions, syncFolders, getSyncStatus } from '../services/api'
import PageHeader from '../components/PageHeader'
import PageShell from '../components/PageShell'
import StatusBadge from '../components/StatusBadge'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'

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
      else if (data.status === 'running') toast('Ya hay una sincronizacion en progreso', { icon: '\u2139\uFE0F' })
    },
    onError: () => toast.error('Error al sincronizar'),
  })

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

  const params = { search, estado, fallo, ciudad, page, page_size: pageSize }

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
  const filterOptions = filtersQ.data ?? {}

  function handleSearch(v: string) { setSearch(v); setPage(1) }
  function handleFilter(key: string, value: string) {
    if (key === 'estado') setEstado(value)
    if (key === 'fallo') setFallo(value)
    if (key === 'ciudad') setCiudad(value)
    setPage(1)
  }

  return (
    <PageShell>
      <PageHeader
        title="Tutelas"
        subtitle={casesQ.isFetching ? 'Cargando...' : `${total} caso${total !== 1 ? 's' : ''} encontrado${total !== 1 ? 's' : ''}`}
        icon={Scale}
        action={
          <Button onClick={() => syncMut.mutate()} disabled={isSyncing}>
            {isSyncing ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {isSyncing ? 'Sincronizando...' : 'Sincronizar'}
          </Button>
        }
      />

      {/* Search + Filters */}
      <Card>
        <CardContent className="pt-4 space-y-3">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" size={15} />
            <Input
              placeholder="Buscar por accionante, radicado, juzgado..."
              value={search}
              onChange={(e) => handleSearch(e.target.value)}
              className="pl-8"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Filter size={13} />
              <span className="text-xs font-medium">Filtros:</span>
            </div>
            <select value={estado} onChange={(e) => handleFilter('estado', e.target.value)} className="text-sm border border-input rounded-lg px-2.5 py-1.5 bg-background focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/30 text-foreground">
              <option value="">Todos los estados</option>
              <option value="ACTIVO">Activo</option>
              <option value="INACTIVO">Inactivo</option>
            </select>
            <select value={fallo} onChange={(e) => handleFilter('fallo', e.target.value)} className="text-sm border border-input rounded-lg px-2.5 py-1.5 bg-background focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/30 text-foreground">
              <option value="">Todos los fallos</option>
              <option value="CONCEDE">Concede</option>
              <option value="NIEGA">Niega</option>
              <option value="IMPROCEDENTE">Improcedente</option>
            </select>
            <select value={ciudad} onChange={(e) => handleFilter('ciudad', e.target.value)} className="text-sm border border-input rounded-lg px-2.5 py-1.5 bg-background focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/30 text-foreground max-w-[200px]">
              <option value="">Todas las ciudades</option>
              {(filterOptions.ciudades ?? []).map((c: string) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            {(search || estado || fallo || ciudad) && (
              <button onClick={() => { setSearch(''); setEstado(''); setFallo(''); setCiudad(''); setPage(1) }} className="text-xs text-destructive hover:underline">
                Limpiar filtros
              </button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {casesQ.isError ? (
            <div className="flex items-center gap-2 text-destructive text-sm px-4 py-8">
              <AlertCircle size={16} />
              Error al cargar los casos. Verifique que el servidor este activo.
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-10">#</TableHead>
                      <TableHead>Radicado</TableHead>
                      <TableHead>Accionante</TableHead>
                      <TableHead className="hidden md:table-cell">Juzgado</TableHead>
                      <TableHead className="hidden lg:table-cell">Ciudad</TableHead>
                      <TableHead>Estado</TableHead>
                      <TableHead>Fallo</TableHead>
                      <TableHead className="hidden xl:table-cell">Abogado</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {casesQ.isLoading ? (
                      Array.from({ length: 8 }).map((_, i) => (
                        <TableRow key={i}>
                          {Array.from({ length: 8 }).map((_, j) => (
                            <TableCell key={j}><Skeleton className="h-3 w-3/4" /></TableCell>
                          ))}
                        </TableRow>
                      ))
                    ) : cases.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={8} className="text-center py-12 text-muted-foreground">
                          No se encontraron casos
                        </TableCell>
                      </TableRow>
                    ) : (
                      cases.map((c: any, idx: number) => (
                        <TableRow
                          key={c.id}
                          onClick={() => navigate(`/cases/${c.id}`)}
                          className="cursor-pointer hover:bg-primary/5"
                        >
                          <TableCell className="text-muted-foreground text-xs">
                            {(page - 1) * pageSize + idx + 1}
                          </TableCell>
                          <TableCell className="max-w-[200px]">
                            <span className="font-mono text-xs text-primary font-medium truncate block" title={c.folder_name}>
                              {c.folder_name}
                            </span>
                          </TableCell>
                          <TableCell className="max-w-[180px]">
                            <span className="text-foreground font-medium text-sm truncate block" title={c.ACCIONANTE || ''}>
                              {c.ACCIONANTE || <span className="text-muted-foreground">—</span>}
                            </span>
                          </TableCell>
                          <TableCell className="hidden md:table-cell">
                            <span className="text-muted-foreground text-xs">{c.JUZGADO || '—'}</span>
                          </TableCell>
                          <TableCell className="hidden lg:table-cell">
                            <span className="text-muted-foreground text-xs">{c.CIUDAD || '—'}</span>
                          </TableCell>
                          <TableCell>
                            {c.ESTADO ? <StatusBadge type="estado" value={c.ESTADO} /> : <span className="text-muted-foreground text-xs">—</span>}
                          </TableCell>
                          <TableCell>
                            {c.SENTIDO_FALLO_1ST ? <StatusBadge type="fallo" value={c.SENTIDO_FALLO_1ST} /> : <span className="text-muted-foreground text-xs">—</span>}
                          </TableCell>
                          <TableCell className="hidden xl:table-cell">
                            <span className="text-muted-foreground text-xs">{c.ABOGADO_RESPONSABLE || '—'}</span>
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-border">
                  <p className="text-xs text-muted-foreground">
                    Pagina {page} de {totalPages} — {total} casos
                  </p>
                  <div className="flex items-center gap-1">
                    <Button variant="ghost" size="icon-xs" onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1}>
                      <ChevronLeft size={14} />
                    </Button>
                    {Array.from({ length: Math.min(5, totalPages) }).map((_, i) => {
                      const p = Math.max(1, Math.min(totalPages - 4, page - 2)) + i
                      return (
                        <Button key={p} variant={p === page ? 'default' : 'ghost'} size="xs" onClick={() => setPage(p)} className="min-w-[28px]">
                          {p}
                        </Button>
                      )
                    })}
                    <Button variant="ghost" size="icon-xs" onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page === totalPages}>
                      <ChevronRight size={14} />
                    </Button>
                  </div>
                  {casesQ.isFetching && <Loader2 size={14} className="animate-spin text-primary" />}
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </PageShell>
  )
}
