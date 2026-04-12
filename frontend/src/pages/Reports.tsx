import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import {
  FileSpreadsheet, Download, RefreshCw, Loader2,
  TrendingUp, CheckCircle, Clock, AlertCircle, ExternalLink,
} from 'lucide-react'
import { generateExcel, getExcelList, getMetrics } from '../services/api'
import PageShell from '@/components/PageShell'
import PageHeader from '@/components/PageHeader'
import DataCard from '@/components/DataCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'

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

const METRIC_ICONS = [TrendingUp, CheckCircle, Clock, AlertCircle]
const METRIC_VARIANTS: Array<'primary' | 'success' | 'warning' | 'info'> = [
  'primary', 'success', 'warning', 'info',
]

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

  const generateAction = (
    <Button
      onClick={() => generateMutation.mutate()}
      disabled={generateMutation.isPending}
    >
      {generateMutation.isPending ? (
        <Loader2 size={15} className="animate-spin" />
      ) : (
        <FileSpreadsheet size={15} />
      )}
      {generateMutation.isPending ? 'Generando...' : 'Generar Excel'}
    </Button>
  )

  return (
    <PageShell>
      <PageHeader
        title="Reportes"
        subtitle="Generación de reportes Excel con todos los datos de tutelas"
        icon={FileSpreadsheet}
        action={generateAction}
      />

      {/* Metrics */}
      {metricsQ.isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      ) : metrics.length > 0 ? (
        <div className="space-y-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Resumen de Datos
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {metrics.map((m, i) => {
              const Icon = METRIC_ICONS[i % METRIC_ICONS.length]
              const variant = METRIC_VARIANTS[i % METRIC_VARIANTS.length]
              const numericVal = typeof m.value === 'number'
                ? m.value
                : parseFloat(String(m.value)) || 0
              return (
                <DataCard
                  key={i}
                  icon={Icon}
                  label={m.label}
                  value={numericVal}
                  variant={variant}
                  sub={m.sub}
                />
              )
            })}
          </div>
        </div>
      ) : null}

      {/* Excel Files List */}
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 py-3 px-5 border-b bg-muted/30">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <FileSpreadsheet size={15} className="text-emerald-600" />
            Archivos Generados
            {excelFiles.length > 0 && (
              <span className="text-muted-foreground font-normal">({excelFiles.length})</span>
            )}
          </CardTitle>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-muted-foreground hover:text-foreground"
            onClick={() => qc.invalidateQueries({ queryKey: ['excel-list'] })}
          >
            <RefreshCw size={13} className={excelListQ.isFetching ? 'animate-spin' : ''} />
          </Button>
        </CardHeader>

        <CardContent className="p-0">
          {excelListQ.isLoading ? (
            <div className="flex items-center justify-center py-10">
              <Loader2 size={24} className="animate-spin text-primary" />
            </div>
          ) : excelFiles.length === 0 ? (
            <div className="text-center py-14">
              <FileSpreadsheet size={40} className="mx-auto text-muted-foreground/30 mb-3" />
              <p className="text-sm text-muted-foreground">No hay archivos Excel generados</p>
              <p className="text-xs text-muted-foreground/70 mt-1">
                Haga clic en "Generar Excel" para crear el primer reporte
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Archivo</TableHead>
                  <TableHead>Generado</TableHead>
                  <TableHead className="w-20 text-right">Tamaño</TableHead>
                  <TableHead className="w-28"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {excelFiles.map((file, i) => (
                  <TableRow key={file.id ?? i}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <div className="p-2 bg-emerald-50 rounded-lg flex-shrink-0">
                          <FileSpreadsheet size={15} className="text-emerald-600" />
                        </div>
                        <span className="text-sm font-medium truncate max-w-[280px]">{file.filename}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(file.created_at)}
                    </TableCell>
                    <TableCell className="text-right text-sm text-muted-foreground tabular-nums">
                      {file.size_kb ? `${file.size_kb} KB` : '—'}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="outline" size="sm" render={<a href={file.url ?? `/api/reports/excel/download/${file.filename}`} target="_blank" rel="noopener noreferrer" />}>
                          <Download size={13} />
                          Descargar
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Info Box */}
      <Alert className="border-blue-200 bg-blue-50">
        <ExternalLink size={15} className="text-blue-500" />
        <AlertDescription>
          <p className="font-semibold text-blue-800 mb-1.5">Información sobre el reporte Excel</p>
          <ul className="text-xs text-blue-700 space-y-1 list-disc list-inside">
            <li>El archivo incluye los 28 campos de cada caso</li>
            <li>Se generan con formato de tabla y encabezados coloreados</li>
            <li>Los datos se exportan directamente desde la base de datos</li>
            <li>Compatible con Microsoft Excel y Google Sheets</li>
          </ul>
        </AlertDescription>
      </Alert>
    </PageShell>
  )
}
