import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  FileSpreadsheet, Download, RefreshCw, Loader2,
  TrendingUp, CheckCircle, Clock, AlertCircle, ExternalLink,
} from 'lucide-react'
import { generateExcel, getExcelList, getMetrics } from '../services/api'

interface ExcelFile {
  id?: number
  filename: string
  created_at: string
  size_kb?: number
  url?: string
  path?: string
}

interface MetricItem {
  label: string
  value: string | number
  sub?: string
}

export default function Reports() {
  const qc = useQueryClient()

  const excelListQ = useQuery({
    queryKey: ['excel-list'],
    queryFn: getExcelList,
  })

  const metricsQ = useQuery({
    queryKey: ['metrics'],
    queryFn: getMetrics,
  })

  const generateMutation = useMutation({
    mutationFn: generateExcel,
    onSuccess: (data) => {
      toast.success('Excel generado exitosamente')
      qc.invalidateQueries({ queryKey: ['excel-list'] })
      if (data?.download_url || data?.filename) {
        window.open(data.download_url ?? `/api/reports/excel/download/${data.filename}`, '_blank')
      }
    },
    onError: () => {
      toast.error('Error al generar el Excel')
    },
  })

  const excelFiles: ExcelFile[] = excelListQ.data ?? []
  const metrics: MetricItem[] = metricsQ.data?.summary ?? []

  function formatDate(iso: string) {
    try {
      return new Date(iso).toLocaleString('es-CO', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    } catch {
      return iso
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Reportes</h1>
          <p className="text-sm text-gray-500 mt-1">
            Generacion de reportes Excel con todos los datos de tutelas
          </p>
        </div>

        <button
          onClick={() => generateMutation.mutate()}
          disabled={generateMutation.isPending}
          className="flex items-center gap-2 px-5 py-2.5 bg-[#1A5276] text-white font-medium rounded-lg hover:bg-[#154360] disabled:opacity-50 transition-colors shadow-sm"
        >
          {generateMutation.isPending ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <FileSpreadsheet size={16} />
          )}
          {generateMutation.isPending ? 'Generando...' : 'Generar Excel'}
        </button>
      </div>

      {/* Metrics */}
      {metricsQ.isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="bg-white rounded-xl border border-gray-200 p-4 animate-pulse h-20" />
          ))}
        </div>
      ) : metrics.length > 0 ? (
        <div>
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
            Resumen de Datos
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {metrics.map((m, i) => {
              const icons = [TrendingUp, CheckCircle, Clock, AlertCircle]
              const colors = [
                'bg-[#1A5276] text-white',
                'bg-green-600 text-white',
                'bg-amber-500 text-white',
                'bg-blue-500 text-white',
              ]
              const Icon = icons[i % icons.length]
              return (
                <div
                  key={i}
                  className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 flex items-start gap-3"
                >
                  <div className={`p-2 rounded-lg ${colors[i % colors.length]}`}>
                    <Icon size={16} />
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 font-medium">{m.label}</p>
                    <p className="text-xl font-bold text-gray-800">{m.value}</p>
                    {m.sub && <p className="text-xs text-gray-400">{m.sub}</p>}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ) : null}

      {/* Excel Files List */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-gray-50">
          <div className="flex items-center gap-2">
            <FileSpreadsheet size={15} className="text-green-600" />
            <h2 className="text-sm font-semibold text-gray-700">
              Archivos Generados
              {excelFiles.length > 0 && (
                <span className="ml-2 text-gray-400 font-normal">({excelFiles.length})</span>
              )}
            </h2>
          </div>
          <button
            onClick={() => qc.invalidateQueries({ queryKey: ['excel-list'] })}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-200 transition-colors"
          >
            <RefreshCw size={14} className={excelListQ.isFetching ? 'animate-spin' : ''} />
          </button>
        </div>

        {excelListQ.isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={24} className="animate-spin text-[#1A5276]" />
          </div>
        ) : excelFiles.length === 0 ? (
          <div className="text-center py-12">
            <FileSpreadsheet size={40} className="mx-auto text-gray-300 mb-3" />
            <p className="text-sm text-gray-500">No hay archivos Excel generados</p>
            <p className="text-xs text-gray-400 mt-1">
              Haga clic en "Generar Excel" para crear el primer reporte
            </p>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {excelFiles.map((file, i) => (
              <div
                key={file.id ?? i}
                className="flex items-center gap-4 px-5 py-4 hover:bg-gray-50 transition-colors"
              >
                <div className="p-2.5 bg-green-50 rounded-lg flex-shrink-0">
                  <FileSpreadsheet size={18} className="text-green-600" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{file.filename}</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {formatDate(file.created_at)}
                    {file.size_kb && ` — ${file.size_kb} KB`}
                  </p>
                </div>
                <a
                  href={file.url ?? `/api/reports/excel/download/${file.filename}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-[#1A5276] border border-[#1A5276]/30 rounded-lg hover:bg-[#1A5276] hover:text-white transition-colors font-medium"
                >
                  <Download size={14} />
                  Descargar
                </a>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Info Box */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
        <div className="flex items-start gap-3">
          <ExternalLink size={16} className="text-blue-500 mt-0.5 flex-shrink-0" />
          <div>
            <p className="text-sm font-semibold text-blue-800">Informacion sobre el reporte Excel</p>
            <ul className="text-xs text-blue-700 mt-2 space-y-1 list-disc list-inside">
              <li>El archivo incluye los 28 campos de cada caso</li>
              <li>Se generan con formato de tabla y encabezados coloreados</li>
              <li>Los datos se exportan directamente desde la base de datos</li>
              <li>Compatible con Microsoft Excel y Google Sheets</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
