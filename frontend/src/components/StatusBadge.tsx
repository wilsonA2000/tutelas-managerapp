import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

type BadgeType = 'estado' | 'fallo' | 'semaforo' | 'status'

const ESTADO_STYLES: Record<string, string> = {
  COMPLETO: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  ACTIVO: 'bg-amber-100 text-amber-800 border-amber-200',
  PENDIENTE: 'bg-gray-100 text-gray-600 border-gray-200',
  REVISION: 'bg-blue-100 text-blue-800 border-blue-200',
  DUPLICATE_MERGED: 'bg-purple-100 text-purple-800 border-purple-200',
  INACTIVO: 'bg-gray-100 text-gray-500 border-gray-200',
}

const FALLO_STYLES: Record<string, string> = {
  CONCEDE: 'bg-red-100 text-red-800 border-red-200',
  NIEGA: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  IMPROCEDENTE: 'bg-orange-100 text-orange-800 border-orange-200',
  PENDIENTE: 'bg-gray-100 text-gray-600 border-gray-200',
  FAVORABLE: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  DESFAVORABLE: 'bg-red-100 text-red-800 border-red-200',
  MODIFICADO: 'bg-violet-100 text-violet-800 border-violet-200',
  'SIN FALLO': 'bg-gray-100 text-gray-500 border-gray-200',
}

const SEMAFORO_STYLES: Record<string, string> = {
  VENCIDO: 'bg-red-100 text-red-800 border-red-200',
  CRITICO: 'bg-red-100 text-red-700 border-red-200',
  URGENTE: 'bg-amber-100 text-amber-800 border-amber-200',
  EN_TERMINO: 'bg-blue-100 text-blue-800 border-blue-200',
  CUMPLIDO: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  SIN_PLAZO: 'bg-gray-100 text-gray-500 border-gray-200',
  Pendiente: 'bg-gray-100 text-gray-600 border-gray-200',
}

const STATUS_STYLES: Record<string, string> = {
  ok: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  error: 'bg-red-100 text-red-800 border-red-200',
  warning: 'bg-amber-100 text-amber-800 border-amber-200',
  unknown: 'bg-gray-100 text-gray-500 border-gray-200',
}

const TYPE_MAP: Record<BadgeType, Record<string, string>> = {
  estado: ESTADO_STYLES,
  fallo: FALLO_STYLES,
  semaforo: SEMAFORO_STYLES,
  status: STATUS_STYLES,
}

interface StatusBadgeProps {
  type: BadgeType
  value: string
  className?: string
}

export default function StatusBadge({ type, value, className }: StatusBadgeProps) {
  const styles = TYPE_MAP[type]
  const colorClass = styles[value] || 'bg-gray-100 text-gray-600 border-gray-200'

  return (
    <Badge
      variant="outline"
      className={cn(
        'text-[11px] font-medium border rounded-md px-2 py-0.5',
        colorClass,
        className
      )}
    >
      {value.replace(/_/g, ' ')}
    </Badge>
  )
}
