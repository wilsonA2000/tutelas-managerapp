import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Brain, TrendingUp, Scale, Users, Calendar, Search,
  AlertTriangle, CheckCircle, Clock, BarChart3,
} from 'lucide-react'
import {
  getIntelFavorability, getIntelAppeals, getIntelLawyers,
  getIntelTrends, getIntelRights, getIntelPredict,
  getCalendarEvents, getDeadlineSummary,
} from '../services/api'

export default function Intelligence() {
  const [predictParams, setPredictParams] = useState({ juzgado: '', derecho: '', ciudad: '' })
  const [activeTab, setActiveTab] = useState<'analytics' | 'calendar' | 'predict'>('analytics')

  const { data: favorability } = useQuery({ queryKey: ['intel-fav'], queryFn: getIntelFavorability })
  const { data: appeals } = useQuery({ queryKey: ['intel-appeals'], queryFn: getIntelAppeals })
  const { data: lawyers } = useQuery({ queryKey: ['intel-lawyers'], queryFn: getIntelLawyers })
  const { data: trends } = useQuery({ queryKey: ['intel-trends'], queryFn: getIntelTrends })
  const { data: rights } = useQuery({ queryKey: ['intel-rights'], queryFn: getIntelRights })
  const { data: calendar } = useQuery({ queryKey: ['intel-calendar'], queryFn: getCalendarEvents, enabled: activeTab === 'calendar' })
  const { data: deadlines } = useQuery({ queryKey: ['intel-deadlines'], queryFn: getDeadlineSummary })
  const { data: prediction, refetch: runPredict } = useQuery({
    queryKey: ['intel-predict', predictParams],
    queryFn: () => getIntelPredict(predictParams),
    enabled: false,
  })

  const tabs = [
    { id: 'analytics', label: 'Analytics', icon: BarChart3 },
    { id: 'calendar', label: 'Calendario', icon: Calendar },
    { id: 'predict', label: 'Predictor', icon: Brain },
  ] as const

  const severityColors: Record<string, string> = {
    VENCIDO: 'bg-red-100 text-red-800',
    URGENTE: 'bg-amber-100 text-amber-800',
    EN_PLAZO: 'bg-green-100 text-green-800',
    INFO: 'bg-blue-100 text-blue-800',
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Brain className="w-7 h-7 text-[#1A5276]" />
          <h1 className="text-xl font-bold text-gray-800">Inteligencia Legal</h1>
        </div>

        {/* Deadline summary cards */}
        {deadlines && (
          <div className="flex gap-2">
            {deadlines.vencidos > 0 && (
              <span className="px-3 py-1 bg-red-100 text-red-700 rounded-full text-xs font-bold">
                {deadlines.vencidos} vencidos
              </span>
            )}
            {deadlines.urgentes > 0 && (
              <span className="px-3 py-1 bg-amber-100 text-amber-700 rounded-full text-xs font-bold">
                {deadlines.urgentes} urgentes
              </span>
            )}
            <span className="px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-bold">
              {deadlines.total} eventos
            </span>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-lg w-fit">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition ${
              activeTab === tab.id ? 'bg-white text-[#1A5276] shadow' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <tab.icon size={16} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* ANALYTICS TAB */}
      {activeTab === 'analytics' && (
        <div className="space-y-6">
          {/* Appeals Summary */}
          {appeals && (
            <div className="bg-white rounded-xl shadow-sm border p-5">
              <h3 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
                <Scale size={18} /> Impugnaciones
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="text-center p-3 bg-gray-50 rounded-lg">
                  <p className="text-2xl font-bold text-gray-800">{appeals.total_impugnaciones}</p>
                  <p className="text-xs text-gray-500">Total</p>
                </div>
                <div className="text-center p-3 bg-green-50 rounded-lg">
                  <p className="text-2xl font-bold text-green-600">{appeals.resueltas}</p>
                  <p className="text-xs text-gray-500">Resueltas</p>
                </div>
                <div className="text-center p-3 bg-amber-50 rounded-lg">
                  <p className="text-2xl font-bold text-amber-600">{appeals.pendientes}</p>
                  <p className="text-xs text-gray-500">Pendientes</p>
                </div>
                <div className="text-center p-3 bg-blue-50 rounded-lg">
                  <p className="text-2xl font-bold text-blue-600">{appeals.tasa_revocacion}%</p>
                  <p className="text-xs text-gray-500">Tasa Revocacion</p>
                </div>
              </div>
            </div>
          )}

          {/* Favorability by Juzgado */}
          {favorability && favorability.length > 0 && (
            <div className="bg-white rounded-xl shadow-sm border p-5">
              <h3 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
                <TrendingUp size={18} /> Favorabilidad por Juzgado (Top 10)
              </h3>
              <div className="space-y-2">
                {favorability.slice(0, 10).map((j: any, i: number) => (
                  <div key={i} className="flex items-center gap-3">
                    <span className="text-xs text-gray-500 w-6">{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm truncate">{j.juzgado}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <div className="flex-1 bg-gray-100 rounded-full h-2">
                          <div
                            className="bg-green-500 h-2 rounded-full"
                            style={{ width: `${j.tasa_favorabilidad}%` }}
                          />
                        </div>
                        <span className="text-xs font-mono text-gray-600 w-12">
                          {j.tasa_favorabilidad}%
                        </span>
                      </div>
                    </div>
                    <span className="text-xs text-gray-400">{j.total} casos</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Lawyer Performance */}
          {lawyers && lawyers.length > 0 && (
            <div className="bg-white rounded-xl shadow-sm border p-5">
              <h3 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
                <Users size={18} /> Rendimiento por Abogado
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-gray-500 border-b">
                      <th className="text-left py-2">Abogado</th>
                      <th className="text-center py-2">Total</th>
                      <th className="text-center py-2">Activos</th>
                      <th className="text-center py-2">Favorables</th>
                      <th className="text-center py-2">Tasa %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lawyers.map((l: any, i: number) => (
                      <tr key={i} className="border-b border-gray-50">
                        <td className="py-2 truncate max-w-[200px]">{l.abogado}</td>
                        <td className="text-center py-2 font-mono">{l.total_casos}</td>
                        <td className="text-center py-2 font-mono">{l.activos}</td>
                        <td className="text-center py-2 font-mono text-green-600">{l.favorables}</td>
                        <td className="text-center py-2">
                          <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                            l.tasa_favorabilidad >= 60 ? 'bg-green-100 text-green-700' :
                            l.tasa_favorabilidad >= 40 ? 'bg-amber-100 text-amber-700' :
                            'bg-red-100 text-red-700'
                          }`}>
                            {l.tasa_favorabilidad}%
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Rights Analysis */}
          {rights && rights.length > 0 && (
            <div className="bg-white rounded-xl shadow-sm border p-5">
              <h3 className="font-semibold text-gray-800 mb-3">Derechos Vulnerados</h3>
              <div className="flex flex-wrap gap-2">
                {rights.map((r: any, i: number) => (
                  <span key={i} className="px-3 py-1.5 bg-[#1A5276]/10 text-[#1A5276] rounded-full text-xs font-medium">
                    {r.derecho} ({r.count})
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* CALENDAR TAB */}
      {activeTab === 'calendar' && (
        <div className="bg-white rounded-xl shadow-sm border">
          <div className="p-5 border-b">
            <h3 className="font-semibold text-gray-800 flex items-center gap-2">
              <Calendar size={18} /> Plazos y Vencimientos
            </h3>
          </div>
          <div className="divide-y">
            {calendar && calendar.length > 0 ? calendar.map((event: any, i: number) => (
              <div key={i} className="px-5 py-3 flex items-center gap-4">
                <span className={`px-2 py-1 rounded text-xs font-bold ${severityColors[event.severity] || 'bg-gray-100'}`}>
                  {event.severity}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{event.folder_name}</p>
                  <p className="text-xs text-gray-500">{event.description}</p>
                </div>
                {event.days_left !== null && (
                  <span className={`text-sm font-mono ${event.days_left < 0 ? 'text-red-600' : 'text-gray-600'}`}>
                    {event.days_left < 0 ? `${Math.abs(event.days_left)}d vencido` : `${event.days_left}d`}
                  </span>
                )}
              </div>
            )) : (
              <div className="px-5 py-8 text-center text-gray-400">
                <CheckCircle className="w-8 h-8 mx-auto mb-2" />
                Sin eventos pendientes
              </div>
            )}
          </div>
        </div>
      )}

      {/* PREDICT TAB */}
      {activeTab === 'predict' && (
        <div className="bg-white rounded-xl shadow-sm border p-5">
          <h3 className="font-semibold text-gray-800 mb-4 flex items-center gap-2">
            <Brain size={18} /> Predictor de Resultados
          </h3>
          <p className="text-sm text-gray-500 mb-4">
            Predice el resultado probable basado en datos historicos de {favorability?.length || 0} juzgados.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
            <input
              type="text"
              placeholder="Juzgado (parcial)..."
              value={predictParams.juzgado}
              onChange={e => setPredictParams(p => ({ ...p, juzgado: e.target.value }))}
              className="px-3 py-2 border rounded-lg text-sm"
            />
            <input
              type="text"
              placeholder="Derecho vulnerado..."
              value={predictParams.derecho}
              onChange={e => setPredictParams(p => ({ ...p, derecho: e.target.value }))}
              className="px-3 py-2 border rounded-lg text-sm"
            />
            <input
              type="text"
              placeholder="Ciudad..."
              value={predictParams.ciudad}
              onChange={e => setPredictParams(p => ({ ...p, ciudad: e.target.value }))}
              className="px-3 py-2 border rounded-lg text-sm"
            />
          </div>

          <button
            onClick={() => runPredict()}
            className="px-4 py-2 bg-[#1A5276] text-white rounded-lg text-sm hover:bg-[#154360] flex items-center gap-2"
          >
            <Search size={16} />
            Predecir
          </button>

          {prediction && (
            <div className="mt-4 p-4 bg-gray-50 rounded-lg">
              <div className="flex items-center gap-3 mb-3">
                <span className={`text-2xl font-bold ${
                  prediction.prediction === 'CONCEDE' ? 'text-red-600' :
                  prediction.prediction === 'NIEGA' ? 'text-green-600' :
                  'text-amber-600'
                }`}>
                  {prediction.prediction}
                </span>
                <div className="flex-1 max-w-[200px]">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-gray-500">Confianza</span>
                    <span className={`text-xs font-bold ${
                      prediction.confidence >= 60 ? 'text-green-600' :
                      prediction.confidence >= 35 ? 'text-amber-600' :
                      'text-red-500'
                    }`}>{prediction.confidence}%</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div className={`h-2 rounded-full transition-all ${
                      prediction.confidence >= 60 ? 'bg-green-500' :
                      prediction.confidence >= 35 ? 'bg-amber-500' :
                      'bg-red-400'
                    }`} style={{ width: `${Math.min(prediction.confidence, 100)}%` }} />
                  </div>
                </div>
                <span className="text-xs text-gray-400">{prediction.sample_size} casos</span>
              </div>
              <p className="text-sm text-gray-600">{prediction.message}</p>
              {prediction.breakdown && (
                <div className="flex gap-3 mt-2">
                  {Object.entries(prediction.breakdown).map(([key, val]) => (
                    <span key={key} className="text-xs bg-white px-2 py-1 rounded border">
                      {key}: {val as number}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
