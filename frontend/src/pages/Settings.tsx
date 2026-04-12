import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Settings, CheckCircle, XCircle, RefreshCw,
  Mail, Cpu, Database, Shield, AlertTriangle,
  Loader2,
} from 'lucide-react'
import { getSettingsStatus } from '../services/api'
import PageShell from '@/components/PageShell'
import PageHeader from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'

interface StatusItem {
  key: string
  label: string
  description: string
  icon: React.ElementType
  iconColor: string
}

const SERVICES: StatusItem[] = [
  {
    key: 'gmail',
    label: 'Gmail API',
    description: 'Lectura de notificaciones judiciales desde el correo oficial',
    icon: Mail,
    iconColor: 'text-red-500',
  },
  {
    key: 'groq',
    label: 'Inteligencia Artificial',
    description: 'DeepSeek V3.2 + Claude Haiku 3 para extraccion de campos',
    icon: Cpu,
    iconColor: 'text-purple-500',
  },
  {
    key: 'database',
    label: 'Base de Datos SQLite',
    description: 'Almacenamiento local de casos y documentos',
    icon: Database,
    iconColor: 'text-blue-500',
  },
  {
    key: 'folders',
    label: 'Carpetas de Casos',
    description: 'Acceso al directorio de tutelas escaneados',
    icon: Shield,
    iconColor: 'text-green-500',
  },
]

function StatusBadge({ ok }: { ok: boolean | null | undefined }) {
  if (ok === null || ok === undefined) {
    return (
      <Badge variant="outline" className="gap-1.5 text-muted-foreground">
        <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground/40" />
        Desconocido
      </Badge>
    )
  }
  if (ok) {
    return (
      <Badge variant="outline" className="gap-1.5 border-green-200 text-green-700 bg-green-50">
        <CheckCircle size={11} />
        Configurado
      </Badge>
    )
  }
  return (
    <Badge variant="destructive" className="gap-1.5">
      <XCircle size={11} />
      No configurado
    </Badge>
  )
}

export default function SettingsPage() {
  const qc = useQueryClient()

  const statusQ = useQuery({
    queryKey: ['settings-status'],
    queryFn: getSettingsStatus,
    refetchInterval: 30_000,
  })

  const statusData = statusQ.data ?? {}

  const allOk = SERVICES.every((s) => statusData[s.key] === true)
  const anyError = SERVICES.some((s) => statusData[s.key] === false)

  return (
    <PageShell>
      <PageHeader
        title="Configuración"
        subtitle="Estado de los servicios y componentes del sistema"
        icon={Settings}
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={() => qc.invalidateQueries({ queryKey: ['settings-status'] })}
          >
            <RefreshCw size={14} className={statusQ.isFetching ? 'animate-spin' : ''} />
            Actualizar
          </Button>
        }
      />

      {/* Global status banner */}
      {!statusQ.isLoading && (
        <Card className={`border ${
          allOk
            ? 'border-green-200 bg-green-50'
            : anyError
            ? 'border-red-200 bg-red-50'
            : 'border-amber-200 bg-amber-50'
        }`}>
          <CardContent className="flex items-center gap-3 py-4">
            {allOk ? (
              <CheckCircle size={20} className="text-green-600 flex-shrink-0" />
            ) : anyError ? (
              <XCircle size={20} className="text-red-500 flex-shrink-0" />
            ) : (
              <AlertTriangle size={20} className="text-amber-500 flex-shrink-0" />
            )}
            <div>
              <p className={`font-semibold text-sm ${
                allOk ? 'text-green-800' : anyError ? 'text-red-800' : 'text-amber-800'
              }`}>
                {allOk
                  ? 'Sistema operativo — todos los servicios activos'
                  : anyError
                  ? 'Algunos servicios requieren configuracion'
                  : 'Estado parcialmente operativo'}
              </p>
              {anyError && (
                <p className="text-xs mt-0.5 text-red-600">
                  Configure las variables de entorno necesarias en el archivo .env del servidor
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Services Grid */}
      <div>
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
          Estado de Servicios
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {SERVICES.map((service) => {
            const Icon = service.icon
            const ok = statusData[service.key]

            return (
              <Card
                key={service.key}
                className={ok === false ? 'border-red-200' : undefined}
              >
                <CardContent className="py-5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3">
                      <div className={`p-2.5 rounded-lg flex-shrink-0 ${
                        ok === true ? 'bg-green-50' : ok === false ? 'bg-red-50' : 'bg-muted'
                      }`}>
                        <Icon size={20} className={service.iconColor} />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-foreground">{service.label}</p>
                        <p className="text-xs text-muted-foreground mt-1">{service.description}</p>
                      </div>
                    </div>
                    <div className="flex-shrink-0">
                      {statusQ.isLoading ? (
                        <Loader2 size={16} className="animate-spin text-muted-foreground/40" />
                      ) : (
                        <StatusBadge ok={ok} />
                      )}
                    </div>
                  </div>

                  {statusData[`${service.key}_detail`] && (
                    <>
                      <Separator className="my-3" />
                      <p className="text-xs text-muted-foreground font-mono">
                        {statusData[`${service.key}_detail`]}
                      </p>
                    </>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      </div>

      {/* System Info */}
      <Card>
        <div className="flex items-center gap-2 px-5 py-3 border-b bg-muted/40 rounded-t-xl">
          <Settings size={14} className="text-muted-foreground" />
          <p className="text-sm font-semibold text-foreground">Información del Sistema</p>
        </div>
        <CardContent className="p-0">
          <div className="divide-y divide-border">
            {[
              { label: 'Entidad', value: 'Gobernación de Santander' },
              { label: 'Módulo', value: 'Gestión de Tutelas 2026' },
              { label: 'Versión', value: '4.9' },
            ].map((row) => (
              <div key={row.label} className="flex items-center px-5 py-3">
                <span className="text-xs text-muted-foreground w-40 font-medium">{row.label}</span>
                <span className="text-sm text-foreground font-mono">{row.value}</span>
              </div>
            ))}
            {statusData.cases_count !== undefined && (
              <div className="flex items-center px-5 py-3">
                <span className="text-xs text-muted-foreground w-40 font-medium">Casos en DB</span>
                <span className="text-sm font-mono font-semibold text-primary">
                  {statusData.cases_count}
                </span>
              </div>
            )}
            {statusData.documents_count !== undefined && (
              <div className="flex items-center px-5 py-3">
                <span className="text-xs text-muted-foreground w-40 font-medium">Documentos en DB</span>
                <span className="text-sm font-mono font-semibold text-primary">
                  {statusData.documents_count}
                </span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </PageShell>
  )
}
