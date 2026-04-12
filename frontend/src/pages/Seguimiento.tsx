import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  AlertTriangle, Shield, CheckCircle, Clock, XCircle,
  ExternalLink, Loader2, Cpu, RefreshCw, ShieldAlert,
} from 'lucide-react'
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
import { cn } from '@/lib/utils'

const SEMAFORO_CONFIG: Record<string, {
  color: string; bg: string; border: string
  icon: React.ElementType; label: string
}> = {
  VENCIDO:    { color: 'text-red-700',    bg: 'bg-red-100',    border: 'border-red-300',    icon: XCircle,       label: 'Vencido' },
  URGENTE:    { color: 'text-orange-700', bg: 'bg-orange-100', border: 'border-orange-300', icon: AlertTriangle, label: 'Urgente (<3 dias)' },
  POR_VENCER: { color: 'text-amber-700',  bg: 'bg-amber-100',  border: 'border-amber-300',  icon: Clock,         label: 'Por vencer (<7 dias)' },
  EN_PLAZO:   { color: 'text-green-700',  bg: 'bg-green-100',  border: 'border-green-300',  icon: Shield,        label: 'En plazo' },
  CUMPLIDO:   { color: 'text-blue-700',   bg: 'bg-blue-100',   border: 'border-blue-300',   icon: CheckCircle,   label: 'Cumplido' },
  IMPUGNADO:  { color: 'text-purple-700', bg: 'bg-purple-100', border: 'border-purple-300', icon: Clock,         label: 'Impugnado' },
  SIN_PLAZO:  { color: 'text-gray-600',   bg: 'bg-gray-100',   border: 'border-gray-300',   icon: Clock,         label: 'Pendiente' },
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

export default function Seguimiento() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [filtroSemaforo, setFiltroSemaforo] = useState('')

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
    mutationFn: ({ id, body }: { id: number; body: Record<string, string | number> }) =>
      updateSeguimiento(id, body),
    onSuccess: () => {
      toast.success('Actualizado')
      qc.invalidateQueries({ queryKey: ['seguimiento'] })
    },
  })

  const items = dataQ.data?.items ?? []
  const resumen = dataQ.data?.resumen ?? {}

  const FILTER_LABELS: Record<string, string> = {
    '': 'Todos', VENCIDO: 'Vencido', URGENTE: 'Urgente',
    POR_VENCER: 'Por Vencer', EN_PLAZO: 'En Plazo',
    IMPUGNADO: 'Impugnado', CUMPLIDO: 'Cumplido',
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
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <DataCard icon={Shield}        label="Total Fallos" value={resumen.total      ?? 0} variant="primary"  />
          <DataCard icon={XCircle}       label="Vencidos"     value={resumen.vencidos   ?? 0} variant="danger"   />
          <DataCard icon={AlertTriangle} label="Urgentes"     value={resumen.urgentes   ?? 0} variant="warning"  />
          <DataCard icon={Clock}         label="Por Vencer"   value={resumen.por_vencer ?? 0} variant="info"     />
          <DataCard icon={CheckCircle}   label="En Plazo"     value={resumen.en_plazo   ?? 0} variant="success"  />
          <DataCard icon={CheckCircle}   label="Cumplidos"    value={resumen.cumplidos  ?? 0} variant="neutral"  />
        </div>
      )}

      {/* Filter chips */}
      <div className="bg-card rounded-xl border border-border shadow-sm px-4 py-3 flex flex-wrap gap-2 items-center">
        <span className="text-xs font-semibold text-muted-foreground mr-1">Filtrar:</span>
        {['', 'VENCIDO', 'URGENTE', 'POR_VENCER', 'EN_PLAZO', 'IMPUGNADO', 'CUMPLIDO'].map((f) => (
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
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead className="text-xs font-semibold text-muted-foreground uppercase tracking-wide w-[150px]">
                    Estado
                  </TableHead>
                  <TableHead className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                    Caso
                  </TableHead>
                  <TableHead className="text-xs font-semibold text-muted-foreground uppercase tracking-wide hidden lg:table-cell">
                    Orden Judicial
                  </TableHead>
                  <TableHead className="text-xs font-semibold text-muted-foreground uppercase tracking-wide w-[130px]">
                    Plazo
                  </TableHead>
                  <TableHead className="text-xs font-semibold text-muted-foreground uppercase tracking-wide hidden md:table-cell">
                    Responsable
                  </TableHead>
                  <TableHead className="w-24" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item: {
                  id: number; case_id: number; semaforo: string;
                  folder_name: string; accionante: string; juzgado: string;
                  orden_judicial: string; plazo_dias: number;
                  dias_restantes: number | null; fecha_limite: string;
                  responsable: string; instancia: string; sentido_fallo: string;
                  impugnado: string; requiere_cumplimiento: string;
                  estado: string; notas: string; extraido_por_ia: string;
                }) => (
                  <TableRow key={item.id} className="hover:bg-muted/30 transition-colors">
                    {/* Semaforo */}
                    <TableCell className="py-3">
                      <SemaforoBadge semaforo={item.semaforo} />
                    </TableCell>

                    {/* Caso */}
                    <TableCell className="py-3">
                      <p className="font-medium text-foreground text-xs">
                        {item.accionante || item.folder_name}
                      </p>
                      <p className="text-[10px] text-muted-foreground mt-0.5">{item.juzgado}</p>
                      <div className="flex gap-1.5 mt-1 flex-wrap">
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0.5 h-auto font-normal text-muted-foreground">
                          {item.instancia}
                        </Badge>
                        <Badge variant="outline" className="text-[10px] px-1.5 py-0.5 h-auto font-normal text-destructive bg-destructive/5 border-destructive/20">
                          {item.sentido_fallo}
                        </Badge>
                        {item.impugnado === 'SI' && (
                          <Badge variant="outline" className="text-[10px] px-1.5 py-0.5 h-auto font-normal text-violet-700 bg-violet-50 border-violet-200">
                            Impugnado
                          </Badge>
                        )}
                      </div>
                    </TableCell>

                    {/* Orden */}
                    <TableCell className="py-3 hidden lg:table-cell max-w-xs">
                      {item.orden_judicial ? (
                        <p className="text-xs text-muted-foreground line-clamp-3">
                          {item.orden_judicial}
                        </p>
                      ) : (
                        <button
                          onClick={() => extractMut.mutate(item.id)}
                          disabled={extractMut.isPending}
                          className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 font-medium transition-colors"
                        >
                          <Cpu size={12} />
                          Obtener datos
                        </button>
                      )}
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

                    {/* Responsable */}
                    <TableCell className="py-3 hidden md:table-cell">
                      <span className="text-xs text-muted-foreground">
                        {item.responsable || '---'}
                      </span>
                    </TableCell>

                    {/* Acciones */}
                    <TableCell className="py-3">
                      <div className="flex items-center gap-1">
                        {item.estado !== 'CUMPLIDO' && (
                          <button
                            onClick={() => updateMut.mutate({
                              id: item.id,
                              body: {
                                estado: 'CUMPLIDO',
                                fecha_cumplimiento: new Date().toLocaleDateString('es-CO', {
                                  day: '2-digit', month: '2-digit', year: 'numeric',
                                }),
                              },
                            })}
                            className="text-[10px] text-emerald-600 hover:text-emerald-800 font-medium px-2 py-1 rounded hover:bg-emerald-50 transition-colors"
                            title="Marcar como cumplido"
                          >
                            Cumplido
                          </button>
                        )}
                        <button
                          onClick={() => item.case_id && navigate(`/cases/${item.case_id}`)}
                          className="p-1.5 text-muted-foreground hover:text-primary rounded hover:bg-primary/5 transition-colors"
                          title="Ver tutela"
                        >
                          <ExternalLink size={14} />
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
    </PageShell>
  )
}
