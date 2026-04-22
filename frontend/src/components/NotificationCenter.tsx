import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Bell, X, AlertTriangle, AlertCircle, Info, Check } from 'lucide-react'
import { getAlerts, getAlertCounts, dismissAlert, scanAlerts, markAlertsSeen } from '../services/api'
import toast from 'react-hot-toast'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'

const severityConfig = {
  CRITICAL: { icon: AlertCircle, color: 'text-red-500', bg: 'bg-red-50', border: 'border-l-red-400' },
  WARNING: { icon: AlertTriangle, color: 'text-amber-500', bg: 'bg-amber-50', border: 'border-l-amber-400' },
  INFO: { icon: Info, color: 'text-blue-500', bg: 'bg-blue-50', border: 'border-l-blue-400' },
}

const severityBadgeVariant: Record<string, 'destructive' | 'outline' | 'secondary'> = {
  CRITICAL: 'destructive',
  WARNING: 'outline',
  INFO: 'secondary',
}

export default function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const btnRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const queryClient = useQueryClient()

  const updatePos = useCallback(() => {
    if (btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      setPos({ top: rect.bottom + 8, left: Math.max(8, rect.right - 384) })
    }
  }, [])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node) && btnRef.current && !btnRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      updatePos()
      document.addEventListener('mousedown', handleClick)
    }
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open, updatePos])

  const { data: counts } = useQuery({
    queryKey: ['alertCounts'],
    queryFn: getAlertCounts,
    refetchInterval: 60000,
  })

  const { data: alerts = [] } = useQuery({
    queryKey: ['alerts'],
    queryFn: () => getAlerts(),
    enabled: open,
  })

  const dismissMut = useMutation({
    mutationFn: dismissAlert,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] })
      queryClient.invalidateQueries({ queryKey: ['alertCounts'] })
    },
  })

  const markSeenMut = useMutation({
    mutationFn: markAlertsSeen,
    onSuccess: () => {
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
    <>
      <button
        ref={btnRef}
        onClick={() => { if (!open) { setOpen(true); markSeenMut.mutate(); } else { setOpen(false); } }}
        className="relative p-1.5 rounded-lg text-white/80 hover:text-white hover:bg-white/15 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/60 transition-colors"
        title={newCount > 0 ? `${newCount} alertas nuevas` : 'Alertas'}
        aria-label={newCount > 0 ? `${newCount} alertas nuevas` : 'Centro de alertas'}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <Bell size={20} className={newCount > 0 ? 'animate-pulse' : ''} />
        {newCount > 0 && (
          <span
            className="absolute -top-1 -right-1 bg-red-600 ring-2 ring-primary text-white text-[11px] font-bold rounded-full min-w-[18px] h-[18px] px-1 flex items-center justify-center leading-none"
            aria-hidden="true"
          >
            {newCount > 99 ? '99+' : newCount}
          </span>
        )}
      </button>

      {open && createPortal(
        <div
          ref={panelRef}
          className="fixed w-80 sm:w-96 bg-popover rounded-lg shadow-lg ring-1 ring-foreground/10 z-50 flex flex-col"
          style={{ maxHeight: '70vh', top: pos.top, left: pos.left }}
        >
          {/* Header */}
          <div className="flex-shrink-0 flex items-center justify-between px-4 py-3 bg-muted/50 rounded-t-lg border-b">
            <div className="flex items-center gap-2">
              <Bell size={14} className="text-muted-foreground" />
              <span className="font-semibold text-sm text-foreground">Alertas</span>
              {newCount > 0 && (
                <Badge variant="destructive" className="h-4 text-[10px] px-1.5">
                  {newCount}
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="xs"
                onClick={() => scanMut.mutate()}
                disabled={scanMut.isPending}
                className="text-primary text-xs"
              >
                {scanMut.isPending ? 'Escaneando...' : 'Escanear'}
              </Button>
              <Button
                variant="ghost"
                size="icon-xs"
                onClick={() => setOpen(false)}
                className="text-muted-foreground"
              >
                <X size={14} />
              </Button>
            </div>
          </div>

          {/* Alert list — scrollable */}
          <div className="flex-1 overflow-y-auto overscroll-contain min-h-0">
            {(alerts as any[]).length === 0 ? (
              <div className="px-4 py-8 text-center text-muted-foreground text-sm">
                <Check className="w-8 h-8 mx-auto mb-2 text-green-400" />
                Sin alertas pendientes
              </div>
            ) : (
              <div>
                {(alerts as any[]).map((alert: any, idx: number) => {
                  const config = severityConfig[alert.severity as keyof typeof severityConfig] || severityConfig.INFO
                  const Icon = config.icon
                  return (
                    <div key={alert.id}>
                      <div className={`px-4 py-3 border-l-4 ${config.bg} ${config.border}`}>
                        <div className="flex items-start gap-2">
                          <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${config.color}`} />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-foreground truncate">{alert.title}</p>
                            {alert.description && (
                              <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{alert.description}</p>
                            )}
                            <div className="flex items-center gap-2 mt-1.5">
                              <span className="text-[10px] text-muted-foreground">
                                {new Date(alert.created_at).toLocaleDateString('es-CO')}
                              </span>
                              <Badge
                                variant={severityBadgeVariant[alert.severity] ?? 'outline'}
                                className="h-4 text-[10px] px-1.5"
                              >
                                {alert.severity}
                              </Badge>
                            </div>
                          </div>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            onClick={() => dismissMut.mutate(alert.id)}
                            className="text-muted-foreground flex-shrink-0"
                            title="Descartar"
                          >
                            <X size={13} />
                          </Button>
                        </div>
                      </div>
                      {idx < (alerts as any[]).length - 1 && <Separator />}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>,
        document.body
      )}
    </>
  )
}
