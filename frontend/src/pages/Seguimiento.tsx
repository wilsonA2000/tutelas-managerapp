import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import {
  AlertTriangle, Shield, CheckCircle, Clock, XCircle,
  ExternalLink, Loader2, Search, Cpu, RefreshCw, ChevronDown,
} from 'lucide-react'
import { getSeguimiento, scanFallos, extractOrder, updateSeguimiento } from '../services/api'

const SEMAFORO_CONFIG: Record<string, { color: string; bg: string; border: string; icon: React.ElementType; label: string }> = {
  VENCIDO:    { color: 'text-red-700',    bg: 'bg-red-100',    border: 'border-red-300',    icon: XCircle,       label: 'Vencido' },
  URGENTE:    { color: 'text-orange-700',  bg: 'bg-orange-100',  border: 'border-orange-300',  icon: AlertTriangle, label: 'Urgente (<3 dias)' },
  POR_VENCER: { color: 'text-amber-700',  bg: 'bg-amber-100',  border: 'border-amber-300',  icon: Clock,         label: 'Por vencer (<7 dias)' },
  EN_PLAZO:   { color: 'text-green-700',  bg: 'bg-green-100',  border: 'border-green-300',  icon: Shield,        label: 'En plazo' },
  CUMPLIDO:   { color: 'text-blue-700',   bg: 'bg-blue-100',   border: 'border-blue-300',   icon: CheckCircle,   label: 'Cumplido' },
  IMPUGNADO:  { color: 'text-purple-700', bg: 'bg-purple-100', border: 'border-purple-300', icon: Clock,         label: 'Impugnado' },
  SIN_PLAZO:  { color: 'text-gray-600',   bg: 'bg-gray-100',   border: 'border-gray-300',   icon: Clock,         label: 'Sin plazo definido' },
}

function SemaforoBadge({ semaforo }: { semaforo: string }) {
  const cfg = SEMAFORO_CONFIG[semaforo] ?? SEMAFORO_CONFIG.SIN_PLAZO
  const Icon = cfg.icon
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${cfg.bg} ${cfg.color} ${cfg.border}`}>
      <Icon size={13} />
      {cfg.label}
    </span>
  )
}

function ResumenCards({ resumen }: { resumen: Record<string, number> }) {
  const cards = [
    { key: 'total', label: 'Total Fallos', color: 'bg-[#1A5276]', text: 'text-white' },
    { key: 'vencidos', label: 'Vencidos', color: 'bg-red-500', text: 'text-white' },
    { key: 'urgentes', label: 'Urgentes', color: 'bg-orange-500', text: 'text-white' },
    { key: 'por_vencer', label: 'Por Vencer', color: 'bg-amber-500', text: 'text-white' },
    { key: 'en_plazo', label: 'En Plazo', color: 'bg-green-500', text: 'text-white' },
    { key: 'cumplidos', label: 'Cumplidos', color: 'bg-blue-500', text: 'text-white' },
    { key: 'impugnados', label: 'Impugnados', color: 'bg-purple-500', text: 'text-white' },
  ]
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {cards.map(c => (
        <div key={c.key} className={`${c.color} ${c.text} rounded-xl p-4 text-center shadow-sm`}>
          <p className="text-2xl font-bold">{resumen[c.key] ?? 0}</p>
          <p className="text-xs font-medium opacity-90">{c.label}</p>
        </div>
      ))}
    </div>
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
    mutationFn: ({ id, body }: { id: number; body: Record<string, string | number> }) => updateSeguimiento(id, body),
    onSuccess: () => {
      toast.success('Actualizado')
      qc.invalidateQueries({ queryKey: ['seguimiento'] })
    },
  })

  const items = dataQ.data?.items ?? []
  const resumen = dataQ.data?.resumen ?? {}

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Seguimiento de Cumplimientos</h1>
          <p className="text-sm text-gray-500 mt-1">
            Control de fallos desfavorables y plazos de cumplimiento
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => scanMut.mutate()}
            disabled={scanMut.isPending}
            className="flex items-center gap-2 px-4 py-2.5 bg-[#1A5276] text-white text-sm font-medium rounded-lg hover:bg-[#154360] disabled:opacity-50 transition-colors shadow-sm"
          >
            {scanMut.isPending ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            {scanMut.isPending ? 'Escaneando...' : 'Escanear Fallos'}
          </button>
        </div>
      </div>

      {/* Resumen Semáforo */}
      {resumen.total > 0 && <ResumenCards resumen={resumen} />}

      {/* Filtros */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 flex flex-wrap gap-3 items-center">
        <span className="text-xs font-semibold text-gray-500">Filtrar:</span>
        {['', 'VENCIDO', 'URGENTE', 'POR_VENCER', 'EN_PLAZO', 'IMPUGNADO', 'CUMPLIDO'].map(f => (
          <button
            key={f}
            onClick={() => setFiltroSemaforo(f)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${
              filtroSemaforo === f
                ? 'bg-[#1A5276] text-white border-[#1A5276]'
                : 'bg-white text-gray-600 border-gray-300 hover:border-[#1A5276]'
            }`}
          >
            {f || 'Todos'}
          </button>
        ))}
      </div>

      {/* Tabla */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {dataQ.isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={24} className="animate-spin text-[#1A5276]" />
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-12">
            <Shield size={40} className="mx-auto text-gray-300 mb-3" />
            <p className="text-sm text-gray-500">No hay seguimientos registrados</p>
            <p className="text-xs text-gray-400 mt-1">
              Use "Escanear Fallos" para detectar tutelas con fallos desfavorables
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">Estado</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">Caso</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase hidden lg:table-cell">Orden Judicial</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">Plazo</th>
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase hidden md:table-cell">Responsable</th>
                  <th className="px-4 py-3 w-24" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.map((item: {
                  id: number; case_id: number; semaforo: string;
                  folder_name: string; accionante: string; juzgado: string;
                  orden_judicial: string; plazo_dias: number;
                  dias_restantes: number | null; fecha_limite: string;
                  responsable: string; instancia: string; sentido_fallo: string;
                  impugnado: string; requiere_cumplimiento: string;
                  estado: string; notas: string; extraido_por_ia: string;
                }) => (
                  <tr key={item.id} className="hover:bg-gray-50 transition-colors">
                    {/* Semáforo */}
                    <td className="px-4 py-3">
                      <SemaforoBadge semaforo={item.semaforo} />
                    </td>

                    {/* Caso */}
                    <td className="px-4 py-3">
                      <p className="font-medium text-gray-800 text-xs">{item.accionante || item.folder_name}</p>
                      <p className="text-[10px] text-gray-400 mt-0.5">{item.juzgado}</p>
                      <div className="flex gap-1.5 mt-1">
                        <span className="text-[10px] bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">{item.instancia}</span>
                        <span className="text-[10px] bg-red-50 text-red-600 px-1.5 py-0.5 rounded">{item.sentido_fallo}</span>
                        {item.impugnado === 'SI' && (
                          <span className="text-[10px] bg-purple-50 text-purple-600 px-1.5 py-0.5 rounded">Impugnado</span>
                        )}
                      </div>
                    </td>

                    {/* Orden */}
                    <td className="px-4 py-3 hidden lg:table-cell max-w-xs">
                      {item.orden_judicial ? (
                        <p className="text-xs text-gray-600 line-clamp-3">{item.orden_judicial}</p>
                      ) : (
                        <button
                          onClick={() => extractMut.mutate(item.id)}
                          disabled={extractMut.isPending}
                          className="flex items-center gap-1 text-xs text-purple-600 hover:text-purple-800 font-medium"
                        >
                          <Cpu size={12} />
                          Extraer con IA
                        </button>
                      )}
                    </td>

                    {/* Plazo */}
                    <td className="px-4 py-3">
                      {item.fecha_limite ? (
                        <div>
                          <p className="text-xs font-mono text-gray-700">{item.fecha_limite}</p>
                          {item.dias_restantes !== null && (
                            <p className={`text-[10px] font-semibold mt-0.5 ${
                              item.dias_restantes < 0 ? 'text-red-600' :
                              item.dias_restantes <= 3 ? 'text-orange-600' :
                              'text-green-600'
                            }`}>
                              {item.dias_restantes < 0
                                ? `Vencido hace ${Math.abs(item.dias_restantes)} dias`
                                : item.dias_restantes === 0
                                ? 'Vence HOY'
                                : `${item.dias_restantes} dias restantes`
                              }
                            </p>
                          )}
                        </div>
                      ) : (
                        <div className="flex flex-col gap-1">
                          <span className="text-[10px] text-gray-400 italic">Pendiente de extraccion</span>
                          {!item.orden_judicial && (
                            <button
                              onClick={() => extractMut.mutate(item.id)}
                              disabled={extractMut.isPending}
                              className="flex items-center gap-1 text-[10px] text-purple-600 hover:text-purple-800 font-medium"
                            >
                              <Cpu size={10} />
                              Extraer plazo
                            </button>
                          )}
                        </div>
                      )}
                    </td>

                    {/* Responsable */}
                    <td className="px-4 py-3 hidden md:table-cell">
                      <span className="text-xs text-gray-600">{item.responsable || '---'}</span>
                    </td>

                    {/* Acciones */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1">
                        {item.estado !== 'CUMPLIDO' && (
                          <button
                            onClick={() => updateMut.mutate({ id: item.id, body: { estado: 'CUMPLIDO', fecha_cumplimiento: new Date().toLocaleDateString('es-CO', { day: '2-digit', month: '2-digit', year: 'numeric' }) } })}
                            className="text-[10px] text-green-600 hover:text-green-800 font-medium px-2 py-1 rounded hover:bg-green-50"
                            title="Marcar como cumplido"
                          >
                            Cumplido
                          </button>
                        )}
                        <button
                          onClick={() => item.case_id && navigate(`/cases/${item.case_id}`)}
                          className="p-1.5 text-gray-400 hover:text-[#1A5276] rounded hover:bg-blue-50"
                          title="Ver tutela"
                        >
                          <ExternalLink size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
