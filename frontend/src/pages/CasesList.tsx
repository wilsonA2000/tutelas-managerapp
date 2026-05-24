import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Search, Filter, ChevronLeft, ChevronRight, AlertCircle, Loader2, RefreshCw, Scale, Lock, Link2 } from 'lucide-react'
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

const REVISION_FLAG_LABEL: Record<string, string> = {
  sin_accionante: 'sin accionante',
  sin_radicado: 'sin radicado',
  pocos_docs: '≤1 doc',
  docs_sospechosos: 'docs sosp.',
  sin_fallo: 'sin fallo',
  baja_completitud: 'baja compl.',
  incidente_sin_fecha: 'incidente s/fecha',
  sin_quien_impugno: 'impugna s/sujeto',
  necesita_revision: 'revisar',
  sin_extraer: 'sin extraer',
}

// Severidad → clases tailwind. Mantengo paleta consistente entre el filtro
// y los chips inline de la columna "Revisión".
const SEVERITY_STYLES: Record<string, { active: string; idle: string; chip: string }> = {
  critical:   { active: 'bg-rose-600 text-white border-rose-700 shadow-sm',
                idle:   'bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100',
                chip:   'bg-rose-50 text-rose-700 border-rose-200' },
  high:       { active: 'bg-orange-600 text-white border-orange-700 shadow-sm',
                idle:   'bg-orange-50 text-orange-700 border-orange-200 hover:bg-orange-100',
                chip:   'bg-orange-50 text-orange-700 border-orange-200' },
  warn:       { active: 'bg-amber-500 text-white border-amber-600 shadow-sm',
                idle:   'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100',
                chip:   'bg-amber-50 text-amber-700 border-amber-200' },
  procedural: { active: 'bg-violet-600 text-white border-violet-700 shadow-sm',
                idle:   'bg-violet-50 text-violet-700 border-violet-200 hover:bg-violet-100',
                chip:   'bg-violet-50 text-violet-700 border-violet-200' },
  info:       { active: 'bg-slate-700 text-white border-slate-800 shadow-sm',
                idle:   'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100',
                chip:   'bg-slate-50 text-slate-700 border-slate-200' },
}
const REVISION_SEVERITY: Record<string, string> = {
  sin_accionante: 'critical', sin_radicado: 'critical',
  pocos_docs: 'warn', docs_sospechosos: 'warn', baja_completitud: 'warn',
  incidente_sin_fecha: 'procedural', sin_quien_impugno: 'procedural',
  sin_fallo: 'info', necesita_revision: 'high', sin_extraer: 'warn',
}

interface RevisionFlag { value: string; label: string; severity: string; count: number }

export default function CasesList() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [search, setSearch] = useState('')
  const [estado, setEstado] = useState('')
  const [fallo, setFallo] = useState('')
  const [ciudad, setCiudad] = useState('')
  const [revision, setRevision] = useState('')
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

  const params = { search, estado, fallo, ciudad, revision, page, per_page: pageSize }

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
    if (key === 'revision') setRevision(value)
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
          {/* Chips de revisión: estado en vivo de las carpetas con conteos.
              Reemplaza el viejo dropdown (que solo exponía 2 de 9 categorías). */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-muted-foreground mr-1">Estado de carpetas:</span>
            <button
              type="button"
              onClick={() => handleFilter('revision', '')}
              className={`inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-1 rounded-md border transition-colors ${
                revision === ''
                  ? 'bg-slate-900 text-white border-slate-900 shadow-sm'
                  : 'bg-background text-foreground border-input hover:bg-muted'
              }`}
              title="Sin filtro de revisión — todas las carpetas"
            >
              Todas
              <span className="font-mono tabular-nums opacity-80">{filterOptions.revision_total ?? 0}</span>
            </button>
            {(filterOptions.revision_flags as RevisionFlag[] | undefined ?? [])
              .filter((f) => f.count > 0)
              .map((f) => {
                const sev = SEVERITY_STYLES[f.severity] ?? SEVERITY_STYLES.info
                const active = revision === f.value
                return (
                  <button
                    key={f.value}
                    type="button"
                    onClick={() => handleFilter('revision', active ? '' : f.value)}
                    className={`inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-1 rounded-md border transition-colors ${active ? sev.active : sev.idle}`}
                    title={`Filtrar carpetas con: ${f.label.toLowerCase()} (${f.count})`}
                  >
                    {f.label}
                    <span className={`font-mono tabular-nums ${active ? 'opacity-90' : 'opacity-80'}`}>{f.count}</span>
                  </button>
                )
              })}
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-border/60">
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
            {(search || estado || fallo || ciudad || revision) && (
              <button onClick={() => { setSearch(''); setEstado(''); setFallo(''); setCiudad(''); setRevision(''); setPage(1) }} className="text-xs text-destructive hover:underline">
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
                      {revision
                        ? <TableHead>Revisión</TableHead>
                        : <TableHead className="hidden xl:table-cell">Abogado</TableHead>}
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
                          {revision ? 'Ningún caso con esa condición de revisión 🎉' : 'No se encontraron casos'}
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
                              {c.tipo_actuacion === 'COMUNICACION' && (
                                <span
                                  className="mr-1 inline-flex items-center gap-0.5 text-[9px] font-semibold px-1 py-0.5 rounded bg-violet-50 text-violet-700 border border-violet-200 align-middle"
                                  title="Comunicación / carpeta libre sin radicado — no aparece en el cuadro Excel"
                                  onClick={(e) => e.stopPropagation()}
                                >📨 COM</span>
                              )}
                              {c.folder_name}
                            </span>
                          </TableCell>
                          <TableCell className="max-w-[180px]">
                            <span className="flex items-center gap-1">
                              {/Sujeto de especial protecci[oó]n/i.test(c.OBSERVACIONES || '') && (
                                <span title="Datos sensibles (sujeto de especial protección — manejar con reserva)" className="shrink-0 text-rose-500">
                                  <Lock size={11} />
                                </span>
                              )}
                              {c.tipo_acumulacion === 'RECTOR' && (
                                <span
                                  className="shrink-0 inline-flex items-center gap-0.5 text-[9px] font-semibold px-1 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200"
                                  title={`Expediente rector de acumulación (Dec. 2591/91 art. 13 + Dec. 1834/2015). Tutelas acumuladas a este despacho.`}
                                  onClick={(e) => e.stopPropagation()}
                                >
                                  <Link2 size={9} />Rector
                                </span>
                              )}
                              {c.tipo_acumulacion === 'ACUMULADO' && c.acumulado_a_case_id && (
                                <button
                                  type="button"
                                  className="shrink-0 inline-flex items-center gap-0.5 text-[9px] font-semibold px-1 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100"
                                  title={`Acumulado al expediente #${c.acumulado_a_case_id}. Pretensiones y sentencia se resuelven en el rector.`}
                                  onClick={(e) => { e.stopPropagation(); navigate(`/cases/${c.acumulado_a_case_id}`) }}
                                >
                                  <Link2 size={9} />Acum→#{c.acumulado_a_case_id}
                                </button>
                              )}
                              <span className="text-foreground font-medium text-sm truncate" title={c.ACCIONANTE || ''}>
                                {c.ACCIONANTE || <span className="text-muted-foreground">—</span>}
                              </span>
                            </span>
                          </TableCell>
                          <TableCell className="hidden md:table-cell">
                            <span className="text-muted-foreground text-xs">{c.JUZGADO || '—'}</span>
                          </TableCell>
                          <TableCell className="hidden lg:table-cell">
                            <span className="text-muted-foreground text-xs">{c.CIUDAD || '—'}</span>
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-col items-start gap-0.5">
                              {c.ESTADO ? <StatusBadge type="estado" value={c.ESTADO} /> : <span className="text-muted-foreground text-xs">—</span>}
                              {c.tipo_actuacion !== 'COMUNICACION' && (
                                <span
                                  className={`text-[9px] font-semibold px-1 py-0.5 rounded border ${c.extraido ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-100 text-slate-500 border-slate-200'}`}
                                  title={c.extraido ? 'El pipeline v9 extrajo este caso' : 'Sin extraer (el pipeline v9 no corrió sobre este caso)'}
                                >
                                  {c.extraido ? '✓ extraído' : 'sin extraer'}
                                </span>
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            {c.SENTIDO_FALLO_1ST ? <StatusBadge type="fallo" value={c.SENTIDO_FALLO_1ST} /> : <span className="text-muted-foreground text-xs">—</span>}
                          </TableCell>
                          {revision ? (
                            <TableCell>
                              <div className="flex flex-wrap items-center gap-1">
                                <span className={`text-[10px] font-semibold tabular-nums ${(c._completitud_pct ?? 0) < 30 ? 'text-rose-600' : (c._completitud_pct ?? 0) < 50 ? 'text-amber-600' : 'text-muted-foreground'}`}>
                                  {c._completitud_pct ?? 0}%
                                </span>
                                <span className="text-[10px] text-muted-foreground">· {c._n_docs ?? 0} doc{c._n_docs === 1 ? '' : 's'}</span>
                                {Object.keys(c._review ?? {}).map((k: string) => {
                                  const sev = SEVERITY_STYLES[REVISION_SEVERITY[k] ?? 'info'] ?? SEVERITY_STYLES.info
                                  const active = revision === k
                                  return (
                                    <button
                                      key={k}
                                      onClick={(e) => { e.stopPropagation(); handleFilter('revision', active ? '' : k) }}
                                      className={`text-[9px] px-1 py-0.5 rounded border transition-colors ${active ? sev.active : sev.chip + ' hover:brightness-95'}`}
                                      title={`Filtrar por ${REVISION_FLAG_LABEL[k] ?? k}`}
                                    >
                                      {REVISION_FLAG_LABEL[k] ?? k}
                                    </button>
                                  )
                                })}
                              </div>
                            </TableCell>
                          ) : (
                            <TableCell className="hidden xl:table-cell">
                              <span className="text-muted-foreground text-xs">{c.ABOGADO_RESPONSABLE || '—'}</span>
                            </TableCell>
                          )}
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
