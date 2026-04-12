import type { LucideIcon } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import AnimatedNumber from './AnimatedNumber'

type ColorVariant = 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'purple'

const VARIANT_STYLES: Record<ColorVariant, { icon: string; border: string }> = {
  primary: { icon: 'bg-primary/10 text-primary', border: 'border-l-primary' },
  success: { icon: 'bg-emerald-50 text-emerald-600', border: 'border-l-emerald-500' },
  warning: { icon: 'bg-amber-50 text-amber-600', border: 'border-l-amber-500' },
  danger: { icon: 'bg-red-50 text-red-600', border: 'border-l-red-500' },
  info: { icon: 'bg-blue-50 text-blue-600', border: 'border-l-blue-500' },
  neutral: { icon: 'bg-gray-100 text-gray-500', border: 'border-l-gray-400' },
  purple: { icon: 'bg-violet-50 text-violet-600', border: 'border-l-violet-500' },
}

interface DataCardProps {
  icon: LucideIcon
  label: string
  value: number | string
  variant?: ColorVariant
  sub?: string
  suffix?: string
  decimals?: number
  className?: string
}

export default function DataCard({
  icon: Icon,
  label,
  value,
  variant = 'primary',
  sub,
  suffix = '',
  decimals = 0,
  className,
}: DataCardProps) {
  const styles = VARIANT_STYLES[variant]
  const numericValue = typeof value === 'string' ? parseFloat(value) || 0 : value
  const isNumeric = typeof value === 'number' || !isNaN(parseFloat(value as string))

  return (
    <Card className={cn('border-l-4 py-0', styles.border, className)}>
      <CardContent className="flex items-center gap-4 py-4">
        <div className={cn('p-2.5 rounded-lg flex-shrink-0', styles.icon)}>
          <Icon size={20} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide truncate">{label}</p>
          <div className="flex items-baseline gap-1 mt-0.5">
            {isNumeric ? (
              <AnimatedNumber
                value={numericValue}
                suffix={suffix}
                decimals={decimals}
                className="text-2xl font-bold text-foreground"
              />
            ) : (
              <span className="text-2xl font-bold text-foreground">{value}{suffix}</span>
            )}
          </div>
          {sub && <p className="text-xs text-muted-foreground mt-0.5 truncate">{sub}</p>}
        </div>
      </CardContent>
    </Card>
  )
}
