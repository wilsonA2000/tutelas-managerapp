import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Brain, TrendingUp, Scale, Users, Calendar, Search,
  CheckCircle, BarChart3,
} from 'lucide-react'
import {
  getIntelFavorability, getIntelAppeals, getIntelLawyers,
  getIntelTrends, getIntelRights, getIntelPredict,
  getCalendarEvents, getDeadlineSummary,
} from '../services/api'
import PageShell from '@/components/PageShell'
import PageHeader from '@/components/PageHeader'
import DataCard from '@/components/DataCard'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Table, TableHeader, TableBody, TableRow, TableHead, TableCell,
} from '@/components/ui/table'
import { Progress } from '@/components/ui/progress'

export default function Intelligence() {
  const [predictParams, setPredictParams] = useState({ juzgado: '', derecho: '', ciudad: '' })
  const [calendarShowAll, setCalendarShowAll] = useState(false)

  const { data: favorability } = useQuery({ queryKey: ['intel-fav'], queryFn: getIntelFavorability })
  const { data: appeals } = useQuery({ queryKey: ['intel-appeals'], queryFn: getIntelAppeals })
  const { data: lawyers } = useQuery({ queryKey: ['intel-lawyers'], queryFn: getIntelLawyers })
  const { data: _trends } = useQuery({ queryKey: ['intel-trends'], queryFn: getIntelTrends })
  const { data: rights } = useQuery({ queryKey: ['intel-rights'], queryFn: getIntelRights })
  const { data: calendar, enabled: _calEnabled } = useQuery({ queryKey: ['intel-calendar'], queryFn: getCalendarEvents }) as any
  const { data: deadlines } = useQuery({ queryKey: ['intel-deadlines'], queryFn: getDeadlineSummary })
  const { data: prediction, refetch: runPredict } = useQuery({
    queryKey: ['intel-predict', predictParams],
    queryFn: () => getIntelPredict(predictParams),
    enabled: false,
  })

  const INITIAL_SHOW = 10
  const calendarItems: any[] = calendar ?? []



  const deadlineAction = deadlines && (
    <div className="flex gap-2">
      {deadlines.vencidos > 0 && (
        <Badge variant="destructive">{deadlines.vencidos} vencidos</Badge>
      )}
      {deadlines.urgentes > 0 && (
        <Badge className="bg-amber-100 text-amber-700 hover:bg-amber-100">
          {deadlines.urgentes} urgentes
        </Badge>
      )}
      <Badge variant="secondary">{deadlines.total} eventos</Badge>
    </div>
  )

  return (
    <PageShell>
      <PageHeader
        title="Inteligencia Legal"
        subtitle="Análisis de favorabilidad, plazos y predicción de resultados"
        icon={Brain}
        action={deadlineAction}
      />

      <Tabs defaultValue="analytics">
        <TabsList>
          <TabsTrigger value="analytics" className="flex items-center gap-2">
            <BarChart3 size={15} /> Estadísticas
          </TabsTrigger>
          <TabsTrigger value="calendar" className="flex items-center gap-2">
            <Calendar size={15} /> Calendario
          </TabsTrigger>
          <TabsTrigger value="predict" className="flex items-center gap-2">
            <Brain size={15} /> Predicción
          </TabsTrigger>
        </TabsList>

        {/* ANALYTICS TAB */}
        <TabsContent value="analytics" className="space-y-6 mt-6">

          {/* Appeals Summary */}
          {appeals && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Scale size={16} className="text-primary" /> Impugnaciones
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <DataCard
                    icon={Scale}
                    label="Total"
                    value={appeals.total_impugnaciones}
                    variant="neutral"
                  />
                  <DataCard
                    icon={CheckCircle}
                    label="Resueltas"
                    value={appeals.resueltas}
                    variant="success"
                  />
                  <DataCard
                    icon={Calendar}
                    label="Pendientes"
                    value={appeals.pendientes}
                    variant="warning"
                  />
                  <DataCard
                    icon={TrendingUp}
                    label="Tasa Revocación"
                    value={appeals.tasa_revocacion}
                    suffix="%"
                    variant="info"
                  />
                </div>
              </CardContent>
            </Card>
          )}

          {/* Favorability by Juzgado */}
          {favorability && favorability.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <TrendingUp size={16} className="text-primary" /> Favorabilidad por Juzgado (Top 10)
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {favorability.slice(0, 10).map((j: any, i: number) => (
                    <div key={i} className="flex items-center gap-3">
                      <span className="text-xs text-muted-foreground w-5 text-right font-mono">{i + 1}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm truncate text-foreground">{j.juzgado}</p>
                        <div className="flex items-center gap-2 mt-1">
                          <Progress value={j.tasa_favorabilidad} className="h-1.5 flex-1" />
                          <span className="text-xs font-mono text-muted-foreground w-12 text-right">
                            {j.tasa_favorabilidad}%
                          </span>
                        </div>
                      </div>
                      <Badge variant="outline" className="text-xs font-normal shrink-0">
                        {j.total} casos
                      </Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Lawyer Performance */}
          {lawyers && lawyers.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Users size={16} className="text-primary" /> Rendimiento por Abogado
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Abogado</TableHead>
                      <TableHead className="text-center w-20">Total</TableHead>
                      <TableHead className="text-center w-20">Activos</TableHead>
                      <TableHead className="text-center w-24">Favorables</TableHead>
                      <TableHead className="text-center w-20">Tasa %</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {lawyers.map((l: any, i: number) => (
                      <TableRow key={i}>
                        <TableCell className="truncate max-w-[200px] font-medium">{l.abogado}</TableCell>
                        <TableCell className="text-center font-mono text-sm">{l.total_casos}</TableCell>
                        <TableCell className="text-center font-mono text-sm">{l.activos}</TableCell>
                        <TableCell className="text-center font-mono text-sm text-emerald-600 font-semibold">{l.favorables}</TableCell>
                        <TableCell className="text-center">
                          <Badge
                            variant="secondary"
                            className={
                              l.tasa_favorabilidad >= 60
                                ? 'bg-emerald-100 text-emerald-700'
                                : l.tasa_favorabilidad >= 40
                                  ? 'bg-amber-100 text-amber-700'
                                  : 'bg-red-100 text-red-700'
                            }
                          >
                            {l.tasa_favorabilidad}%
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {/* Rights Analysis */}
          {rights && rights.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Derechos Vulnerados</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2">
                  {rights.map((r: any, i: number) => (
                    <Badge
                      key={i}
                      variant="secondary"
                      className="bg-primary/10 text-primary hover:bg-primary/15 px-3 py-1 text-xs font-medium"
                    >
                      {r.derecho} ({r.count})
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* CALENDAR TAB */}
        <TabsContent value="calendar" className="mt-6">
          <Card>
            <CardHeader className="pb-3 flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base flex items-center gap-2">
                <Calendar size={16} className="text-primary" /> Plazos y Vencimientos
              </CardTitle>
              {calendarItems.length > 0 && (
                <span className="text-xs text-muted-foreground">{calendarItems.length} eventos</span>
              )}
            </CardHeader>
            <CardContent className="p-0">
              <div className="divide-y">
                {calendarItems.length > 0
                  ? calendarItems.slice(0, calendarShowAll ? undefined : INITIAL_SHOW).map((event: any, i: number) => (
                    <div key={i} className="px-6 py-3 flex items-center gap-4">
                      <Badge
                        variant="secondary"
                        className={
                          event.severity === 'VENCIDO' ? 'bg-red-100 text-red-700' :
                          event.severity === 'URGENTE' ? 'bg-amber-100 text-amber-700' :
                          event.severity === 'EN_PLAZO' ? 'bg-emerald-100 text-emerald-700' :
                          'bg-blue-100 text-blue-700'
                        }
                      >
                        {event.severity}
                      </Badge>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{event.folder_name}</p>
                        <p className="text-xs text-muted-foreground">{event.description}</p>
                      </div>
                      {event.days_left !== null && (
                        <span className={`text-sm font-mono tabular-nums ${event.days_left < 0 ? 'text-destructive' : 'text-muted-foreground'}`}>
                          {event.days_left < 0 ? `${Math.abs(event.days_left)}d vencido` : `${event.days_left}d`}
                        </span>
                      )}
                    </div>
                  ))
                  : (
                    <div className="px-6 py-10 text-center text-muted-foreground">
                      <CheckCircle className="w-8 h-8 mx-auto mb-2 text-emerald-500" />
                      <p className="text-sm">Sin eventos pendientes</p>
                    </div>
                  )}
              </div>
              {calendarItems.length > INITIAL_SHOW && (
                <div className="p-3 text-center border-t">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setCalendarShowAll(!calendarShowAll)}
                    className="text-primary"
                  >
                    {calendarShowAll ? 'Ver menos' : `Ver todos (${calendarItems.length})`}
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* PREDICT TAB */}
        <TabsContent value="predict" className="mt-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Brain size={16} className="text-primary" /> Predictor de Resultados
              </CardTitle>
              <p className="text-sm text-muted-foreground mt-1">
                Predice el resultado probable basado en datos históricos de {favorability?.length || 0} juzgados.
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <Input
                  placeholder="Juzgado (parcial)..."
                  value={predictParams.juzgado}
                  onChange={e => setPredictParams(p => ({ ...p, juzgado: e.target.value }))}
                />
                <Input
                  placeholder="Derecho vulnerado..."
                  value={predictParams.derecho}
                  onChange={e => setPredictParams(p => ({ ...p, derecho: e.target.value }))}
                />
                <Input
                  placeholder="Ciudad..."
                  value={predictParams.ciudad}
                  onChange={e => setPredictParams(p => ({ ...p, ciudad: e.target.value }))}
                />
              </div>

              <Button onClick={() => runPredict()} className="flex items-center gap-2">
                <Search size={15} />
                Predecir
              </Button>

              {prediction && (
                <div className="p-4 bg-muted/40 rounded-lg border space-y-3">
                  <div className="flex items-center gap-4">
                    <span className={`text-2xl font-bold tracking-tight ${
                      prediction.prediction === 'CONCEDE' ? 'text-destructive' :
                      prediction.prediction === 'NIEGA' ? 'text-emerald-600' :
                      'text-amber-600'
                    }`}>
                      {prediction.prediction}
                    </span>
                    <div className="flex-1 max-w-[200px] space-y-1">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-muted-foreground">Confianza</span>
                        <span className={`text-xs font-bold ${
                          prediction.confidence >= 60 ? 'text-emerald-600' :
                          prediction.confidence >= 35 ? 'text-amber-600' :
                          'text-destructive'
                        }`}>{prediction.confidence}%</span>
                      </div>
                      <Progress
                        value={Math.min(prediction.confidence, 100)}
                        className="h-2"
                      />
                    </div>
                    <Badge variant="outline" className="text-xs font-normal">
                      {prediction.sample_size} casos
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">{prediction.message}</p>
                  {prediction.breakdown && (
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(prediction.breakdown).map(([key, val]) => (
                        <Badge key={key} variant="outline" className="text-xs font-normal">
                          {key}: {val as number}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </PageShell>
  )
}
