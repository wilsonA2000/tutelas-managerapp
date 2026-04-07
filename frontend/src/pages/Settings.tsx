import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Settings, CheckCircle, XCircle, RefreshCw,
  Mail, Cpu, Database, Shield, AlertTriangle,
  Loader2,
} from 'lucide-react'
import { getSettingsStatus } from '../services/api'

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
    label: 'Google Gemini (IA)',
    description: 'Motor de inteligencia artificial multimodal para extraccion de campos',
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

function StatusIndicator({ ok }: { ok: boolean | null | undefined }) {
  if (ok === null || ok === undefined) {
    return (
      <div className="flex items-center gap-1.5 text-gray-400">
        <div className="w-2 h-2 rounded-full bg-gray-300" />
        <span className="text-xs font-medium">Desconocido</span>
      </div>
    )
  }
  if (ok) {
    return (
      <div className="flex items-center gap-1.5 text-green-600">
        <CheckCircle size={16} />
        <span className="text-xs font-semibold">Configurado</span>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-1.5 text-red-500">
      <XCircle size={16} />
      <span className="text-xs font-semibold">No configurado</span>
    </div>
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
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Configuracion</h1>
          <p className="text-sm text-gray-500 mt-1">
            Estado de los servicios y componentes del sistema
          </p>
        </div>
        <button
          onClick={() => qc.invalidateQueries({ queryKey: ['settings-status'] })}
          className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
        >
          <RefreshCw size={14} className={statusQ.isFetching ? 'animate-spin' : ''} />
          Actualizar
        </button>
      </div>

      {/* Global status banner */}
      {!statusQ.isLoading && (
        <div className={`flex items-center gap-3 p-4 rounded-xl border ${
          allOk
            ? 'bg-green-50 border-green-200'
            : anyError
            ? 'bg-red-50 border-red-200'
            : 'bg-amber-50 border-amber-200'
        }`}>
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
        </div>
      )}

      {/* Services Grid */}
      <div>
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
          Estado de Servicios
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {SERVICES.map((service) => {
            const Icon = service.icon
            const ok = statusData[service.key]

            return (
              <div
                key={service.key}
                className={`bg-white rounded-xl border shadow-sm p-5 transition-all ${
                  ok === false
                    ? 'border-red-200'
                    : ok === true
                    ? 'border-gray-200'
                    : 'border-gray-200'
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <div className={`p-2.5 rounded-lg ${
                      ok === true ? 'bg-green-50' : ok === false ? 'bg-red-50' : 'bg-gray-100'
                    }`}>
                      <Icon size={20} className={service.iconColor} />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-gray-800">{service.label}</p>
                      <p className="text-xs text-gray-500 mt-1">{service.description}</p>
                    </div>
                  </div>
                  <div className="flex-shrink-0">
                    {statusQ.isLoading ? (
                      <Loader2 size={16} className="animate-spin text-gray-300" />
                    ) : (
                      <StatusIndicator ok={ok} />
                    )}
                  </div>
                </div>

                {/* Extra info */}
                {statusData[`${service.key}_detail`] && (
                  <div className="mt-3 pt-3 border-t border-gray-100">
                    <p className="text-xs text-gray-400 font-mono">
                      {statusData[`${service.key}_detail`]}
                    </p>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* System Info */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="flex items-center gap-2 px-5 py-3 border-b border-gray-100 bg-gray-50">
          <Settings size={15} className="text-gray-400" />
          <h2 className="text-sm font-semibold text-gray-700">Informacion del Sistema</h2>
        </div>
        <div className="divide-y divide-gray-100">
          {[
            { label: 'Entidad', value: 'Gobernacion de Santander' },
            { label: 'Modulo', value: 'Gestion de Tutelas 2026' },
            { label: 'Version', value: '2.0.0' },
            { label: 'Backend', value: 'FastAPI + Python 3.10 + SQLAlchemy' },
            { label: 'Frontend', value: 'React 19 + Vite + Tailwind CSS v4' },
            { label: 'Base de datos', value: 'SQLite (local)' },
            { label: 'Motor IA', value: 'Google Gemini 2.5 Flash (Multimodal)' },
            { label: 'Extraccion', value: 'PDF multimodal + DOCX + OCR nativo' },
          ].map((row) => (
            <div key={row.label} className="flex items-center px-5 py-3">
              <span className="text-xs text-gray-500 w-40 font-medium">{row.label}</span>
              <span className="text-sm text-gray-800 font-mono">{row.value}</span>
            </div>
          ))}
          {statusData.cases_count !== undefined && (
            <div className="flex items-center px-5 py-3">
              <span className="text-xs text-gray-500 w-40 font-medium">Casos en DB</span>
              <span className="text-sm text-gray-800 font-mono font-semibold text-[#1A5276]">
                {statusData.cases_count}
              </span>
            </div>
          )}
          {statusData.documents_count !== undefined && (
            <div className="flex items-center px-5 py-3">
              <span className="text-xs text-gray-500 w-40 font-medium">Documentos en DB</span>
              <span className="text-sm text-gray-800 font-mono font-semibold text-[#1A5276]">
                {statusData.documents_count}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* .env Instructions */}
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">
          Variables de entorno requeridas
        </h3>
        <pre className="text-xs font-mono text-gray-600 bg-white border border-gray-200 rounded-lg p-4 overflow-x-auto leading-relaxed">
{`# Archivo: tutelas-app/.env

GMAIL_USER=correo@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
GOOGLE_API_KEY=AIza...           # Gemini (principal)
ANTHROPIC_API_KEY=sk-ant-...     # Claude (opcional)
OPENAI_API_KEY=sk-proj-...       # GPT (opcional)
BASE_DIR=/ruta/a/carpetas/tutelas`}
        </pre>
      </div>
    </div>
  )
}
