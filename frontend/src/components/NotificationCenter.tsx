import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, X, AlertTriangle, AlertCircle, Info, Check } from 'lucide-react'
import { getAlerts, getAlertCounts, dismissAlert, scanAlerts } from '../services/api'
import toast from 'react-hot-toast'

const severityConfig = {
  CRITICAL: { icon: AlertCircle, color: 'text-red-500', bg: 'bg-red-50', border: 'border-red-200' },
  WARNING: { icon: AlertTriangle, color: 'text-amber-500', bg: 'bg-amber-50', border: 'border-amber-200' },
  INFO: { icon: Info, color: 'text-blue-500', bg: 'bg-blue-50', border: 'border-blue-200' },
}

export default function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()

  const { data: counts } = useQuery({
    queryKey: ['alertCounts'],
    queryFn: getAlertCounts,
    refetchInterval: 60000,
  })

  const { data: alerts = [] } = useQuery({
    queryKey: ['alerts'],
    queryFn: () => getAlerts('NEW'),
    enabled: open,
  })

  const dismissMut = useMutation({
    mutationFn: dismissAlert,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ['alertCounts'] })
    },
  })

  const scanMut = useMutation({
    mutationFn: scanAlerts,
    onSuccess: (data) => {
      toast.success(`Escaneo completado: ${JSON.stringify(data.alerts_created)}`)
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ['alertCounts'] })
    },
  })

  const newCount = counts?.total_new || 0

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative p-2 text-white/70 hover:text-white transition"
        title="Alertas"
      >
        <Bell size={20} />
        {newCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] font-bold rounded-full w-5 h-5 flex items-center justify-center">
            {newCount > 99 ? '99+' : newCount}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="fixed left-16 top-16 w-80 sm:w-96 max-h-[70vh] bg-white rounded-xl shadow-2xl border border-gray-200 z-50 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b bg-gray-50">
              <h3 className="font-semibold text-sm text-gray-800">Alertas ({newCount})</h3>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => scanMut.mutate()}
                  disabled={scanMut.isPending}
                  className="text-xs text-[#1A5276] hover:underline disabled:opacity-50"
                >
                  {scanMut.isPending ? 'Escaneando...' : 'Escanear'}
                </button>
                <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600">
                  <X size={16} />
                </button>
              </div>
            </div>

            <div className="overflow-y-auto max-h-[60vh] divide-y divide-gray-100">
              {alerts.length === 0 ? (
                <div className="px-4 py-8 text-center text-gray-400 text-sm">
                  <Check className="w-8 h-8 mx-auto mb-2 text-green-400" />
                  Sin alertas pendientes
                </div>
              ) : (
                alerts.map((alert: any) => {
                  const config = severityConfig[alert.severity as keyof typeof severityConfig] || severityConfig.INFO
                  const Icon = config.icon
                  return (
                    <div key={alert.id} className={`px-4 py-3 ${config.bg} border-l-4 ${config.border}`}>
                      <div className="flex items-start gap-2">
                        <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${config.color}`} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-800 truncate">{alert.title}</p>
                          {alert.description && (
                            <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{alert.description}</p>
                          )}
                          <div className="flex items-center gap-2 mt-1">
                            <span className="text-[10px] text-gray-400">
                              {new Date(alert.created_at).toLocaleDateString('es-CO')}
                            </span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded ${config.bg} ${config.color} font-medium`}>
                              {alert.severity}
                            </span>
                          </div>
                        </div>
                        <button
                          onClick={() => dismissMut.mutate(alert.id)}
                          className="text-gray-400 hover:text-gray-600 flex-shrink-0"
                          title="Descartar"
                        >
                          <X size={14} />
                        </button>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
